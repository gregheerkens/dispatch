# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
# Web UI (opens browser at http://127.0.0.1:5151)
python assistant/server.py
# or on Windows: dispatch-web.bat

# CLI
python assistant/dispatch.py                    # general dispatch mode
python assistant/dispatch.py --lane jobs        # specific lane
python assistant/dispatch.py --standup          # morning standup
python assistant/dispatch.py --draft            # draft new vault note
python assistant/dispatch.py --query "text"     # single non-interactive question

# One-time setup (new installs only)
python init_vault.py --name "Your Name"
```

## Dependencies

```bash
pip install anthropic fastapi uvicorn python-dotenv rich watchdog
```

Requires `.env` with `ANTHROPIC_API_KEY`. See `.env.example`.

## Architecture

**The vault is the brain. The agents are the interface.**

```
assistant/
  server.py       — FastAPI + SSE streaming server, tool execution loop
  agents.py       — Agent definitions: 6 lane agents + Dispatch coordinator
  vault.py        — RAG layer: loads all .md files, builds context, manages persistence
  dispatch.py     — CLI with rich formatting, lane detection
  static/
    index.html    — 6-column web UI, one column per lane
```

### Data flow

1. At startup, `Vault` loads all `.md` files from the vault root into memory
2. On chat, `build_context()` packs lane notes into the context window (60k char budget, priority order: Self/README → today's daily note → recent daily summaries → lane notes)
3. The agent response streams via SSE; tool calls (`create_note`, `update_note`, `update_memory`, `list_notes`) are intercepted and executed before streaming continues
4. Conversation history persists to `Agents/<lane>/history.json` (capped at 100 messages)
5. Agent observations persist to `Agents/<lane>/memory.md` (full rewrite, not append)

### Standup (two-phase)

- **Phase 1:** Six lane agents run in parallel via `asyncio.as_completed`, each sees only their own lane (~2-3k tokens). Uses `claude-sonnet-4-6`.
- **Phase 2:** Dispatch reads all six reports + previous standup for continuity, streams cross-lane synthesis. Uses `claude-opus-4-6`.
- Result saved to `Daily/YYYY-MM-DD-standup.md` with frontmatter and callout blocks.

### Agents

Seven agents total — six lane-specific plus `dispatch` (coordinator). Defined in `agents.py` as `AGENTS: dict[str, Agent]`. Each has a system prompt, color, and tools access. The programmatic roster block (`ROSTER_BLOCK`) is injected into every system prompt so agents know who the other agents are.

**Lane → Agent:** `jobs`, `build`, `learn`, `home`, `write`, `self`, `dispatch`

### Vault structure

The `Agents/` and `Daily/` folders are gitignored (private data). Lane folders (`Jobs/`, `Build/`, etc.) are tracked but personal note content inside them may also be excluded per `.gitignore`.

`Vault.build_context()` is the core RAG method — read it before changing how context is assembled.

## Key Env Vars

| Var | Default | Purpose |
|-----|---------|---------|
| `ANTHROPIC_API_KEY` | required | Anthropic API access |
| `VAULT_PATH` | project root | Path to vault directory |
| `DISPATCH_MODEL` | `claude-opus-4-6` | Model for Dispatch coordinator |
