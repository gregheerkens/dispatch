"""
Dispatch Web Server
FastAPI backend — serves the UI and streams agent responses.
"""

import sys
import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from vault import Vault
from agents import get_agent, AGENTS, TOOLS, DEBRIEF_TOOLS, ROSTER_BLOCK

load_dotenv(Path(__file__).parent.parent / ".env")

VAULT_PATH   = os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))
MODEL        = os.getenv("DISPATCH_MODEL", "claude-opus-4-6")   # Dispatch + standup synthesis
LANE_MODEL   = os.getenv("LANE_MODEL",     "claude-sonnet-4-6") # Lane officers (regular chat)
HAIKU_MODEL  = os.getenv("HAIKU_MODEL",    "claude-haiku-4-5-20251001")  # Cheap consolidation tasks
API_KEY      = os.getenv("ANTHROPIC_API_KEY")

# Per-lane conversation histories (in-memory, session-scoped)
conversations: dict[str, list] = {lane: [] for lane in AGENTS}

# Debrief conversation (in-memory, session-scoped, not persisted)
debrief_conversation: list = []

MEMORY_TEMPLATE = (
    "## Current State\n"
    "(Where things stand in this lane right now.)\n\n"
    "## Active Threads\n"
    "(Ongoing items with actions pending. Remove when resolved.)\n\n"
    "## Key Facts\n"
    "(Important facts Greg has shared: numbers, names, dates, decisions.)\n\n"
    "## Cross-Lane\n"
    "(Messages received from other officers relevant to this lane.)"
)

MEMORY_INSTRUCTION = (
    "\n\n---\n\n# MEMORY TOOL\n\n"
    "You have an `update_memory` tool. Your memory is your working record of Greg's situation in your lane — "
    "it is what you will know next session, at standup, and when Dispatch needs to brief from your lane. "
    "Default to writing. If Greg tells you something about his situation, update memory. "
    "If something changes, correct it. If a thread is resolved, note that. "
    "Maintain the four sections: Current State / Active Threads / Key Facts / Cross-Lane. "
    "Edit sections in place. A memory that's slightly too detailed is far more useful than one with gaps. "
    "Critically: when a pipeline item closes, a task completes, or a status changes — update memory immediately. "
    "Do not wait for the next exchange. Stale status in memory is actively harmful."
)


def _memory_block(memory: str) -> str:
    content = memory.strip() if memory and memory.strip() else MEMORY_TEMPLATE
    return f"\n\n---\n\n# YOUR PRIVATE MEMORY\n\n{content}"

vault:  Vault | None = None
client: anthropic.AsyncAnthropic | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vault, client
    vault  = Vault(VAULT_PATH)
    client = anthropic.AsyncAnthropic(api_key=API_KEY)
    # Restore persisted histories
    for lane in AGENTS:
        saved = vault.load_history(lane)
        if saved:
            conversations[lane] = saved
    yield


app = FastAPI(lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Models ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    retry: bool = False

class RememberRequest(BaseModel):
    lane: str
    note: str


# ── Tool execution ────────────────────────────────────────────────────────────

def execute_tool(name: str, tool_input: dict, lane: str = "dispatch") -> dict:
    """Execute a tool call and return a result dict."""
    try:
        if name == "update_memory":
            content = tool_input.get("content", "").strip()
            if not content:
                return {"success": False, "message": "Content cannot be empty"}
            vault.update_agent_memory(lane, content)
            return {"success": True, "message": "Memory updated"}

        elif name == "create_note":
            path = vault.create_note(
                lane=tool_input["lane"],
                title=tool_input["title"],
                content=tool_input["content"],
            )
            rel = str(path.relative_to(vault.root))
            return {"success": True, "path": rel, "message": f"Created {rel}"}

        elif name == "update_note":
            path = vault.update_note(
                path_str=tool_input["path"],
                content=tool_input["content"],
            )
            return {"success": True, "path": tool_input["path"], "message": f"Updated {tool_input['path']}"}

        elif name == "list_notes":
            notes = vault.list_notes(tool_input["lane"])
            return {"success": True, "notes": notes, "message": f"{len(notes)} notes in {tool_input['lane']}"}

        elif name == "update_officer_memory":
            officer = tool_input.get("officer", "").lower()
            content = tool_input.get("content", "").strip()
            if officer not in {k for k in AGENTS if k != "dispatch"}:
                return {"success": False, "message": f"Unknown officer: {officer}"}
            if not content:
                return {"success": False, "message": "Content cannot be empty"}
            vault.update_agent_memory(officer, content)
            return {"success": True, "message": f"{officer.capitalize()} Officer memory updated"}

        else:
            return {"success": False, "message": f"Unknown tool: {name}"}

    except Exception as e:
        return {"success": False, "message": str(e)}


def serialize_content(blocks) -> list[dict]:
    """Serialize SDK content blocks to plain dicts for message history."""
    result = []
    for block in blocks:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return result


def _extract_cross_lane(report: str, valid_lanes: set) -> dict[str, list[str]]:
    """
    Parse `TO [LANE]: message` lines from a standup report.
    Strips markdown decorators (bullets, bold, backticks) before matching.
    Returns {lane_id: [message, ...]} for each lane mentioned.
    """
    tagged: dict[str, list[str]] = {}
    for line in report.splitlines():
        clean = line.strip().lstrip("-*•>`| ").replace("**", "")
        upper = clean.upper()
        for lid in valid_lanes:
            prefix = f"TO {lid.upper()}:"
            if upper.startswith(prefix):
                msg = clean[len(prefix):].strip()
                if msg:
                    tagged.setdefault(lid, []).append(msg)
    return tagged


async def _agentic_generate(initial_messages, system, tools, execute_lane, on_complete=None, model=None):
    """
    Shared agentic tool-use loop used by chat and debrief endpoints.
    Handles the tool call/response cycle then streams final text as SSE.
    on_complete(new_turns) is called after the final turn is assembled
    but before text is streamed — use it for persistence.
    """
    current_messages = list(initial_messages)
    new_turns: list[dict] = []

    try:
        while True:
            response = await client.messages.create(
                model=model or MODEL,
                max_tokens=2048,
                system=system,
                messages=current_messages,
                tools=tools,
                timeout=120.0,
            )

            if response.stop_reason == "tool_use":
                tool_results = []
                assistant_content = serialize_content(response.content)

                for block in response.content:
                    if block.type == "tool_use":
                        yield f"data: {json.dumps({'tool_working': {'name': block.name, 'input': block.input}})}\n\n"
                        result = execute_tool(block.name, block.input, lane=execute_lane)
                        yield f"data: {json.dumps({'tool_done': {'name': block.name, **result}})}\n\n"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                current_messages = current_messages + [
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user",      "content": tool_results},
                ]
                new_turns.extend([
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user",      "content": tool_results},
                ])
                continue

            final_text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )

            # Persist BEFORE streaming — must survive a mid-stream cancellation
            new_turns.append({"role": "assistant", "content": final_text})
            if on_complete:
                on_complete(new_turns)

            chunk_size = 12
            for i in range(0, len(final_text), chunk_size):
                yield f"data: {json.dumps({'text': final_text[i:i+chunk_size]})}\n\n"
                await asyncio.sleep(0.006)

            yield f"data: {json.dumps({'done': True})}\n\n"
            break

    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/status")
async def status():
    vault.refresh()
    return {"notes": len(vault.notes), "agents": list(AGENTS.keys())}


@app.post("/api/chat/{lane}")
async def chat(lane: str, body: ChatRequest):
    if lane not in AGENTS:
        raise HTTPException(404, f"Unknown lane: {lane}")

    vault.refresh()
    agent  = get_agent(lane)
    memory = vault.agent_memory(lane) or ""
    # Lane officers get their own notes only — keeps context ~2-4k tokens instead of ~15k.
    # Dispatch and Finance keep full vault (they reason across all lanes).
    if lane in ("dispatch", "finance"):
        context = vault.build_context()
    else:
        context = vault.build_lane_context(lane.capitalize())

    system = (
        f"{agent['system']}{_memory_block(memory)}{MEMORY_INSTRUCTION}"
        f"{ROSTER_BLOCK}\n\n---\n\n# VAULT CONTEXT\n\n{context}"
    )

    # User message into history — skip on retry (already present from failed attempt)
    if not body.retry:
        conversations[lane].append({"role": "user", "content": body.message})
        if lane != "finance":
            try:
                vault.save_history(lane, conversations[lane])
            except Exception:
                pass
    base_history = list(conversations[lane][-20:])
    chat_model = MODEL if lane == "dispatch" else LANE_MODEL

    def on_complete(new_turns):
        for turn in new_turns:
            conversations[lane].append(turn)
        conversations[lane] = conversations[lane][-100:]
        if lane != "finance":
            try:
                vault.save_history(lane, conversations[lane])
            except Exception:
                pass  # don't let a disk error kill the response

    async def generate():
        async for chunk in _agentic_generate(base_history, system, TOOLS, lane, on_complete, model=chat_model):
            yield chunk

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/standup")
async def standup():
    """
    Collaborative standup — two phases, cost-controlled.

    Phase 1: 6 parallel non-streaming calls. Each lane agent reads ONLY
    their own lane notes (~2-3k tokens each, not the full vault).
    They report in 3-4 sentences. Runs in parallel — arrives fast.

    Phase 2: Dispatch receives all 6 short reports and synthesizes
    cross-lane priorities. Streams into the overlay.

    Total token cost ≈ single full-vault dispatch call.
    """
    vault.refresh()
    LANE_IDS = ['jobs', 'build', 'learn', 'home', 'write', 'self', 'finance']
    NOW = datetime.now().strftime("%A, %B %d, %Y %H:%M")
    STANDUP_PROMPT = (
        "It's standup time. Report on your lane using markdown formatting.\n\n"
        "**Status** — 2-3 sentences on current state.\n\n"
        "**Priority** — The single most important thing right now.\n\n"
        "**Cross-lane** — Specific asks or flags for other lane officers. "
        "Format each as `TO [LANE]: message`. Or `Nothing to flag.`\n\n"
        "Be specific and direct. Use bullet points where it helps. "
        "This goes to your colleagues and to Dispatch."
    )

    async def get_lane_report(lane_id: str) -> tuple[str, str]:
        agent  = get_agent(lane_id)
        memory = vault.agent_memory(lane_id) or ""

        if lane_id == "finance":
            # Finance reads the full vault — money touches every lane
            lane_context_header = "VAULT CONTEXT"
            lane_context = vault.build_context(focus_lanes=None)
        else:
            # Lane officers see only their own notes (~2-3k tokens each)
            lane_notes = vault.by_lane(lane_id.capitalize())
            lane_context_header = "YOUR LANE NOTES"
            lane_context = "\n\n".join(
                f"### {n.title}\n{n.content}" for n in lane_notes
            ) or "No notes in this lane yet."

        # Previous standup report for this officer — so they can report delta, not just state
        prev_report = next(
            (m["content"] for m in reversed(conversations[lane_id])
             if m["role"] == "assistant"
             and isinstance(m["content"], str)
             and m["content"].startswith("[STANDUP")),
            None,
        )
        prev_block = (
            f"\n\n---\n\n# YOUR PREVIOUS STANDUP REPORT\n\n{prev_report}"
            if prev_report else ""
        )

        system = (
            f"{agent['system']}{_memory_block(memory)}{ROSTER_BLOCK}\n\n"
            f"---\n\n# CURRENT DATE AND TIME\n\n{NOW}"
            f"{prev_block}\n\n"
            f"---\n\n# {lane_context_header}\n\n{lane_context}"
        )
        try:
            msg = await client.messages.create(
                model="claude-sonnet-4-6", max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": STANDUP_PROMPT}],
                timeout=60.0,
            )
            return lane_id, msg.content[0].text
        except Exception as e:
            return lane_id, f"[Unavailable: {e}]"

    async def generate():
        # Phase 1 — stream each report as it arrives (as_completed, not gather)
        reports: dict[str, str] = {}
        tasks = [get_lane_report(lid) for lid in LANE_IDS]
        for future in asyncio.as_completed(tasks):
            lane_id, report = await future
            reports[lane_id] = report
            yield f"data: {json.dumps({'phase': 1, 'lane': lane_id, 'report': report})}\n\n"

        # Log standup to each officer's conversation history.
        # Each officer gets their own report (assistant role) so they remember what they said.
        # Cross-lane TO [LANE]: lines arrive as user messages — a note handed to them.
        date_str = datetime.now().strftime("%Y-%m-%d")
        valid_lanes = set(LANE_IDS)

        # Build incoming cross-lane map: {target_lane: [(from_lane, msg), ...]}
        incoming: dict[str, list] = {lid: [] for lid in LANE_IDS}
        for from_lane, report in reports.items():
            for target, messages in _extract_cross_lane(report, valid_lanes).items():
                if target in incoming:
                    for msg in messages:
                        incoming[target].append((from_lane, msg))

        for lid in LANE_IDS:
            report = reports.get(lid, "")
            if not report or report.startswith("[Unavailable"):
                continue
            entries = [{"role": "assistant", "content": f"[STANDUP {date_str}]\n{report}"}]
            if incoming[lid]:
                notes = "\n".join(
                    f"FROM {src.upper()}: {msg}" for src, msg in incoming[lid]
                )
                entries.append({"role": "user", "content": f"[STANDUP INCOMING — {date_str}]\n{notes}"})
            for entry in entries:
                conversations[lid].append(entry)
            conversations[lid] = conversations[lid][-100:]
            if lid != "finance":
                try:
                    vault.save_history(lid, conversations[lid])
                except Exception:
                    pass

        # Phase 2 — dispatch synthesis (streaming)
        agent  = get_agent("dispatch")
        memory = vault.agent_memory("dispatch") or ""

        reports_block = "\n\n".join(
            f"**{lid.upper()} AGENT REPORT:**\n{rpt}"
            for lid, rpt in reports.items()
        )
        last = vault.last_standup()
        last_standup_block = (
            f"\n\n---\n\n# PREVIOUS STANDUP\n\n{last.content}" if last else ""
        )
        system = (
            f"{agent['system']}{_memory_block(memory)}{ROSTER_BLOCK}\n\n"
            f"---\n\n# CURRENT DATE AND TIME\n\n{NOW}\n\n"
            f"{last_standup_block}"
            f"---\n\n# LANE AGENT REPORTS\n\n{reports_block}"
        )
        synthesis_prompt = (
            "You've received standup reports from all lane officers. "
            "Produce a complete synthesis with these sections:\n\n"
            "## Cross-Lane Messages\n"
            "Explicit asks or flags between lane officers, drawn from their reports. "
            "Format each as **[FROM → TO]** message. If none, omit this section.\n\n"
            "## Dependencies & Conflicts\n"
            "Cross-lane dependencies, blockers, or handoffs that need coordination.\n\n"
            "## Top 3 Today\n"
            "Greg's ranked priorities today, one sentence each.\n\n"
            "## Today's Schedule\n"
            "Time-blocked plan using a markdown table: | Time | Task | Lane |\n"
            "Greg's energy pattern: rough mornings, peaks 2–6 PM. "
            "Schedule demanding tasks in the afternoon window.\n\n"
            "## Anything Being Avoided\n"
            "What's being dodged across the board — name it, or 'Nothing flagged.'\n\n"
            "Direct. No filler. This gets saved to the vault."
        )
        synthesis = ""
        try:
            async with client.messages.stream(
                model=MODEL, max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": synthesis_prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    synthesis += text
                    yield f"data: {json.dumps({'phase': 2, 'text': text})}\n\n"
        except Exception as e:
            synthesis = f"Synthesis error: {e}"
            yield f"data: {json.dumps({'phase': 2, 'text': synthesis})}\n\n"

        # Save standup minutes to vault
        try:
            saved_path = vault.write_standup_note(reports, synthesis)
            yield f"data: {json.dumps({'saved': saved_path})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'save_error': str(e)})}\n\n"

        # ── Phase 3: Memory consolidation ─────────────────────────────────
        # Parallel Haiku calls update each officer's memory from their standup
        # report and any cross-lane messages they received. Cheap, fast, reliable.
        async def consolidate_officer_memory(lane_id: str) -> tuple[str, bool]:
            report  = reports.get(lane_id, "")
            cross   = incoming.get(lane_id, [])
            current = vault.agent_memory(lane_id) or ""
            cross_text = (
                "\n\nCross-lane messages received:\n"
                + "\n".join(f"FROM {src.upper()}: {msg}" for src, msg in cross)
                if cross else ""
            )
            try:
                resp = await client.messages.create(
                    model=HAIKU_MODEL,
                    max_tokens=1500,
                    timeout=45.0,
                    system=(
                        "Update this lane officer's private memory after standup. "
                        "Memory has four sections: Current State, Active Threads, Key Facts, Cross-Lane. "
                        "Update each section based on the standup report and any cross-lane messages. "
                        "Preserve accurate existing entries. Remove resolved threads. "
                        "Keep total under 300 words. Return only the updated memory, no preamble."
                    ),
                    messages=[{"role": "user", "content": (
                        f"CURRENT MEMORY:\n{current or '(empty — use the four-section template)'}\n\n"
                        f"STANDUP REPORT:\n{report}"
                        f"{cross_text}\n\n"
                        "Write the complete updated memory."
                    )}],
                )
                vault.update_agent_memory(lane_id, resp.content[0].text.strip())
                return lane_id, True
            except Exception:
                return lane_id, False

        consolidation_tasks = [consolidate_officer_memory(lid) for lid in LANE_IDS]
        for future in asyncio.as_completed(consolidation_tasks):
            lid, success = await future
            yield f"data: {json.dumps({'phase': 3, 'lane': lid, 'success': success})}\n\n"

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/remember")
async def remember(body: RememberRequest):
    if body.lane not in AGENTS:
        raise HTTPException(404, f"Unknown lane: {body.lane}")
    existing = vault.agent_memory(body.lane) or ""
    entry = f"\n| {datetime.now().strftime('%Y-%m-%d')} | {body.note} |"
    if "## Conversation Log" in existing:
        updated = existing.rstrip() + entry + "\n"
    else:
        updated = (existing.rstrip()
                   + f"\n\n## Conversation Log\n| Date | Key Insight |\n|------|------------|\n{entry}\n")
    vault.update_agent_memory(body.lane, updated)
    return {"ok": True}


@app.post("/api/debrief")
async def debrief(body: ChatRequest):
    """
    Debrief — Dispatch as a fully-armed record editor.

    Dispatch sees all officer memories + the most recent standup note, then
    uses the standard agentic tool loop to make targeted corrections based on
    what Greg reports actually happened. Uses Opus — this is a master override.
    """
    global debrief_conversation

    vault.refresh()
    NOW = datetime.now().strftime("%A, %B %d, %Y %H:%M")

    if not body.retry:
        debrief_conversation.append({"role": "user", "content": body.message})

    # All officer memories — Dispatch needs to see what it's correcting
    officer_parts = []
    for officer in [k for k in AGENTS if k != "dispatch"]:
        mem = vault.agent_memory(officer)
        if mem:
            officer_parts.append(f"### {officer.upper()} OFFICER\n{mem.strip()}")

    officer_block = (
        "\n\n---\n\n# OFFICER MEMORIES\n\n" + "\n\n".join(officer_parts)
        if officer_parts else ""
    )

    # Most recent standup note (including today's if it exists)
    standups = sorted(
        [n for n in vault.notes if n.lane == "Daily" and "standup" in n.path.name],
        key=lambda n: n.path.name,
        reverse=True,
    )
    standup_block = ""
    if standups:
        latest = standups[0]
        standup_block = (
            f"\n\n---\n\n# MOST RECENT STANDUP ({latest.path.name})\n\n{latest.content}"
        )

    dispatch_memory = vault.agent_memory("dispatch") or ""

    system = (
        f"{AGENTS['dispatch']['system']}"
        f"{_memory_block(dispatch_memory)}"
        f"{MEMORY_INSTRUCTION}"
        f"{ROSTER_BLOCK}"
        f"\n\n---\n\n# CURRENT DATE AND TIME\n\n{NOW}"
        "\n\n---\n\n# DEBRIEF MODE\n\n"
        "Greg is correcting the record — what actually happened vs. what was captured. "
        "Read his message, compare it against the officer memories and standup note below, "
        "then make targeted corrections using `update_officer_memory` or `update_note`. "
        "Only change what his correction actually affects. Preserve everything else intact."
        f"{officer_block}"
        f"{standup_block}"
    )

    def on_complete(new_turns):
        for turn in new_turns:
            debrief_conversation.append(turn)

    async def generate():
        async for chunk in _agentic_generate(
            initial_messages=list(debrief_conversation),
            system=system,
            tools=DEBRIEF_TOOLS,
            execute_lane="dispatch",
            on_complete=on_complete,
            model=MODEL,
        ):
            yield chunk

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.delete("/api/debrief")
async def clear_debrief():
    """Clear the debrief conversation (call when closing the modal or starting fresh)."""
    global debrief_conversation
    debrief_conversation = []
    return {"ok": True}


@app.get("/api/history/{lane}")
async def get_history(lane: str):
    """Return displayable history — user/assistant text only, no tool turns. Includes actual array index."""
    if lane not in conversations:
        raise HTTPException(404)
    display = []
    for i, msg in enumerate(conversations[lane]):
        if isinstance(msg.get("content"), str) and msg["content"].strip():
            display.append({"role": msg["role"], "text": msg["content"], "idx": i})
    return display


@app.delete("/api/history/{lane}/{idx}")
async def delete_history_message(lane: str, idx: int):
    """Delete a single message from a lane's history by its array index."""
    if lane not in conversations:
        raise HTTPException(404)
    if idx < 0 or idx >= len(conversations[lane]):
        raise HTTPException(400, f"Index {idx} out of range")
    conversations[lane].pop(idx)
    try:
        vault.save_history(lane, conversations[lane])
    except Exception:
        pass
    return {"ok": True}


@app.delete("/api/history/{lane}")
async def clear_history(lane: str):
    if lane not in conversations:
        raise HTTPException(404)
    conversations[lane] = []
    vault.save_history(lane, [])
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading

    def open_browser():
        import time; time.sleep(1)
        webbrowser.open("http://127.0.0.1:5151")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=5151)
