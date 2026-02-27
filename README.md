# Dispatch

A personal command center built on Obsidian and Claude.

Six lanes plus a Finance Officer. One standup. One assistant that knows your actual life.

---

## What It Is

Dispatch is a structured Obsidian vault paired with a Claude-powered assistant that reads your notes as live context. Every job application, project, home maintenance item, and daily note you write becomes queryable context for a set of lane-specific AI agents.

The result is an assistant that doesn't start from zero every conversation — it knows what you applied to last week, what projects are stalled, what's overdue at the house.

**The vault is the brain. The agents are the interface.**

---

## The Six Lanes

| Lane | Purpose |
|------|---------|
| **Jobs** | Applications, contacts, follow-ups, market intel |
| **Build** | Apps, games, makerspace projects |
| **Learn** | Courses, skills, staying current |
| **Home** | Maintenance, systems, vendors, property |
| **Write** | Ideas, drafts, published work |
| **Self** | Health, habits, honest reflection |

Each lane has its own agent with a focused system prompt and a private memory file that persists observations about you across sessions.

### Finance Officer

A seventh agent operates at a different tier. The Finance Officer reads across all lanes (money touches everything), participates in the standup, and is accessible via a dedicated modal in the web UI rather than a persistent column. Its memory file is a financial ledger — burn rate, runway, salary floor, crypto position — kept current and used as the basis for offer math and cross-lane financial flags.

---

## Architecture

```
Dispatch/
├── assistant/
│   ├── agents.py       — Agent definitions and system prompts (6 lane + Finance + Dispatch)
│   ├── vault.py        — Vault reader and context builder (the RAG layer)
│   ├── dispatch.py     — CLI interface
│   ├── server.py       — FastAPI web server
│   └── static/
│       └── index.html  — 6-column web UI + Finance modal
├── Templates/          — Obsidian templates with YAML frontmatter
├── Jobs/               — Job applications (Dataview-queryable)
├── Build/              — Projects
├── Learn/              — Courses and skills
├── Home/               — Maintenance items
├── Write/              — Writing pipeline
├── Self/               — Personal notes
├── Finance/            — Financial documents (offer analysis, budgets, snapshots)
├── Daily/              — Daily notes and standup minutes
├── Agents/             — Private per-agent memory files (gitignored)
└── Tags.md             — Tag taxonomy reference
```

### How the RAG works

The vault reader loads all markdown files at startup. Each note's content, lane, and metadata is available to the assistant. When you send a message, the relevant lane's notes are packed into the Claude context window alongside the agent's system prompt and private memory. The standup runs all seven agents in parallel — lane officers see their own notes, Finance sees the full vault — then streams a cross-lane synthesis.

### Dataview

Lane READMEs contain live Dataview queries that auto-populate as you add notes using the templates. Your job pipeline, active projects, and home systems inventory stay current without manual list maintenance.

---

## Quick Start

### 1. Clone and install

```bash
git clone <repo>
cd Dispatch
pip install anthropic fastapi uvicorn python-dotenv rich watchdog
```

### 2. Configure

```bash
cp .env.example .env
# Add your Anthropic API key to .env
```

### 3. Initialize your vault

```bash
python init_vault.py --name "Your Name"
```

This creates your personal lane READMEs, blank agent memory files, and Obsidian config. Nothing personal is generated — you fill it in.

### 4. Open in Obsidian

Open the `Dispatch/` folder as a vault in Obsidian. Install the **Templater**, **Dataview**, and **Tasks** plugins.

### 5. Run the web UI

```bash
# Windows
dispatch-web.bat

# Mac/Linux
python assistant/server.py
```

Opens at `http://127.0.0.1:5151`

### 6. Or use the CLI

```bash
python assistant/dispatch.py --standup       # morning standup
python assistant/dispatch.py --lane jobs     # talk to one agent
python assistant/dispatch.py                 # general dispatch mode
```

---

## The Standup

The morning standup is two phases:

**Phase 1** — Seven agents run in parallel. The six lane officers each read only their own lane notes (~2-3k tokens each). The Finance Officer reads the full vault. Each reports in 3 sentences: status, most important thing, cross-lane flags.

**Phase 2** — Dispatch reads all seven reports and streams a cross-lane synthesis: dependencies, top 3 priorities, anything being avoided.

Reports appear in each lane column. The synthesis streams into an overlay. The full standup is saved as a dated note in `Daily/` with proper frontmatter and callout blocks.

Total token cost is roughly equivalent to one full-vault single-agent call.

---

## Agent Memory

Each agent has a private memory file at `Agents/<lane>/memory.md`. These are gitignored — they contain observations about you that accumulate over time. The jobs agent might note that you undersell yourself in cover letters. The self agent tracks what you've said directly about your situation.

Memory files are plain markdown. Edit them directly in Obsidian whenever you want to correct or add something.

---

## Requirements

- Python 3.9+
- [Anthropic API key](https://console.anthropic.com)
- [Obsidian](https://obsidian.md) (free)
- Obsidian plugins: Templater, Dataview, Tasks

---

## Philosophy

The vault is not a to-do list. It's a knowledge base about your life that gets smarter the more you write in it. The agents don't replace the work — they reduce the friction of knowing what to work on next.

Write everything down. The assistant reads it. Dispatch.
