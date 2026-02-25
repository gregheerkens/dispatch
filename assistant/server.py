"""
Dispatch Web Server
FastAPI backend — serves the UI and streams agent responses.
"""

import sys
import os
import json
import asyncio
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
from agents import get_agent, AGENTS, TOOLS

load_dotenv(Path(__file__).parent.parent / ".env")

VAULT_PATH = os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))
MODEL      = os.getenv("DISPATCH_MODEL", "claude-opus-4-6")
API_KEY    = os.getenv("ANTHROPIC_API_KEY")

# Per-lane conversation histories (in-memory, session-scoped)
conversations: dict[str, list] = {lane: [] for lane in AGENTS}

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

class RememberRequest(BaseModel):
    lane: str
    note: str


# ── Tool execution ────────────────────────────────────────────────────────────

def execute_tool(name: str, tool_input: dict, lane: str = "dispatch") -> dict:
    """Execute a tool call and return a result dict."""
    try:
        if name == "update_memory":
            note = tool_input.get("note", "").strip()
            if not note:
                return {"success": False, "message": "Note cannot be empty"}
            from datetime import datetime
            existing = vault.agent_memory(lane) or ""
            entry = f"\n| {datetime.now().strftime('%Y-%m-%d')} | {note} |"
            if "## Memory Log" in existing:
                updated = existing.rstrip() + entry + "\n"
            else:
                updated = (
                    existing.rstrip()
                    + f"\n\n## Memory Log\n| Date | Note |\n|------|------|\n{entry}\n"
                )
            vault.update_agent_memory(lane, updated)
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

    agent   = get_agent(lane)
    memory  = vault.agent_memory(lane) or ""
    focus   = [lane.capitalize()] if lane != "dispatch" else None
    context = vault.build_context(focus_lanes=focus)

    memory_block = f"\n\n---\n\n# YOUR PRIVATE MEMORY\n\n{memory}" if memory else ""
    memory_instruction = (
        "\n\n---\n\n# MEMORY TOOL\n\n"
        "You have an `update_memory` tool. Use it during conversations to log things worth "
        "remembering — Greg's preferences, patterns, decisions, and observations specific to "
        "your lane. Your memory is private to you and persists across all conversations. "
        "Call it whenever you learn something your future self should know."
    )
    system = f"{agent['system']}{memory_block}{memory_instruction}\n\n---\n\n# VAULT CONTEXT\n\n{context}"

    # User message into history immediately — save so even a failed response isn't lost
    conversations[lane].append({"role": "user", "content": body.message})
    try:
        vault.save_history(lane, conversations[lane])
    except Exception:
        pass
    # API context: recent 8 messages for token efficiency (vault provides the rest)
    base_history = list(conversations[lane][-8:])

    async def generate():
        current_messages = list(base_history)
        new_turns: list[dict] = []  # assistant + tool turns to append after

        try:
            while True:
                response = await client.messages.create(
                    model=MODEL,
                    max_tokens=2048,
                    system=system,
                    messages=current_messages,
                    tools=TOOLS,
                )

                if response.stop_reason == "tool_use":
                    tool_results = []
                    assistant_content = serialize_content(response.content)

                    for block in response.content:
                        if block.type == "tool_use":
                            # Emit working indicator to UI
                            yield f"data: {json.dumps({'tool_working': {'name': block.name, 'input': block.input}})}\n\n"

                            result = execute_tool(block.name, block.input, lane=lane)

                            # Emit done indicator to UI
                            yield f"data: {json.dumps({'tool_done': {'name': block.name, **result}})}\n\n"

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            })

                    # Extend messages with tool turns and loop
                    current_messages = current_messages + [
                        {"role": "assistant", "content": assistant_content},
                        {"role": "user", "content": tool_results},
                    ]
                    new_turns.extend([
                        {"role": "assistant", "content": assistant_content},
                        {"role": "user", "content": tool_results},
                    ])
                    continue

                # end_turn — extract final text
                final_text = next(
                    (b.text for b in response.content if b.type == "text"), ""
                )

                # Persist BEFORE streaming — save_history must survive a mid-stream cancellation
                new_turns.append({"role": "assistant", "content": final_text})
                for turn in new_turns:
                    conversations[lane].append(turn)
                conversations[lane] = conversations[lane][-100:]
                try:
                    vault.save_history(lane, conversations[lane])
                except Exception:
                    pass  # don't let a disk error kill the response

                # Stream text in chunks
                chunk_size = 12
                for i in range(0, len(final_text), chunk_size):
                    yield f"data: {json.dumps({'text': final_text[i:i+chunk_size]})}\n\n"
                    await asyncio.sleep(0.006)

                yield f"data: {json.dumps({'done': True})}\n\n"
                break

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
    LANE_IDS = ['jobs', 'build', 'learn', 'home', 'write', 'self']
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

        # Only this lane's notes — not the full vault
        lane_notes = vault.by_lane(lane_id.capitalize())
        lane_context = "\n\n".join(
            f"### {n.title}\n{n.content}" for n in lane_notes
        ) or "No notes in this lane yet."

        memory_block = f"\n\n---\n\n# YOUR PRIVATE MEMORY\n\n{memory}" if memory else ""
        system = (
            f"{agent['system']}{memory_block}\n\n"
            f"---\n\n# YOUR LANE NOTES\n\n{lane_context}"
        )
        try:
            msg = await client.messages.create(
                model="claude-sonnet-4-6", max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": STANDUP_PROMPT}],
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

        # Phase 2 — dispatch synthesis (streaming)
        agent  = get_agent("dispatch")
        memory = vault.agent_memory("dispatch") or ""

        reports_block = "\n\n".join(
            f"**{lid.upper()} AGENT REPORT:**\n{rpt}"
            for lid, rpt in reports.items()
        )
        memory_block = f"\n\n---\n\n# YOUR PRIVATE MEMORY\n\n{memory}" if memory else ""
        system = (
            f"{agent['system']}{memory_block}\n\n"
            f"---\n\n# LANE AGENT REPORTS\n\n{reports_block}"
        )
        synthesis_prompt = (
            "You've received standup reports from all 6 lane officers. "
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

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/remember")
async def remember(body: RememberRequest):
    if body.lane not in AGENTS:
        raise HTTPException(404, f"Unknown lane: {body.lane}")
    from datetime import datetime
    existing = vault.agent_memory(body.lane) or ""
    entry = f"\n| {datetime.now().strftime('%Y-%m-%d')} | {body.note} |"
    if "## Conversation Log" in existing:
        updated = existing.rstrip() + entry + "\n"
    else:
        updated = (existing.rstrip()
                   + f"\n\n## Conversation Log\n| Date | Key Insight |\n|------|------------|\n{entry}\n")
    vault.update_agent_memory(body.lane, updated)
    return {"ok": True}


@app.get("/api/history/{lane}")
async def get_history(lane: str):
    """Return displayable history — user/assistant text only, no tool turns."""
    if lane not in conversations:
        raise HTTPException(404)
    display = []
    for msg in conversations[lane]:
        if isinstance(msg.get("content"), str) and msg["content"].strip():
            display.append({"role": msg["role"], "text": msg["content"]})
    return display


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
