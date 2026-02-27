"""
init_vault.py — Initialize a fresh Dispatch vault.

Creates folder structure, blank lane READMEs with Dataview queries,
blank agent memory files, Obsidian config, and .env from example.

Run once when setting up for a new user. Safe to re-run — skips
files that already exist unless --force is passed.

Usage:
    python init_vault.py --name "Your Name"
    python init_vault.py --name "Your Name" --force
"""

import argparse
import os
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent


def exists(path: Path, force: bool) -> bool:
    """Return True if we should skip this file."""
    return path.exists() and not force


def write(path: Path, content: str, force: bool, label: str = ""):
    if exists(path, force):
        print(f"  skip   {path.relative_to(ROOT)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  create {path.relative_to(ROOT)}{' — ' + label if label else ''}")


def init_folders():
    dirs = [
        ROOT / "Jobs",
        ROOT / "Build",
        ROOT / "Learn",
        ROOT / "Home",
        ROOT / "Write",
        ROOT / "Self",
        ROOT / "Daily",
        ROOT / "Templates",
        ROOT / "Assets",
        ROOT / "Finance",
        ROOT / "Agents" / "dispatch",
        ROOT / "Agents" / "jobs",
        ROOT / "Agents" / "build",
        ROOT / "Agents" / "learn",
        ROOT / "Agents" / "home",
        ROOT / "Agents" / "write",
        ROOT / "Agents" / "self",
        ROOT / "Agents" / "finance",
        ROOT / "assistant" / "static",
        ROOT / ".obsidian",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def init_env(force: bool):
    env_example = ROOT / ".env.example"
    env_file    = ROOT / ".env"
    if env_file.exists() and not force:
        print(f"  skip   .env (already exists — add your API key if not done)")
        return
    if env_example.exists():
        shutil.copy(env_example, env_file)
        print(f"  create .env (from .env.example — add your ANTHROPIC_API_KEY)")
    else:
        write(env_file, (
            "ANTHROPIC_API_KEY=your_key_here\n"
            f"VAULT_PATH={ROOT}\n"
            "DISPATCH_MODEL=claude-opus-4-6\n"
        ), force)


def init_obsidian(force: bool):
    write(ROOT / ".obsidian" / "app.json", """{
  "defaultViewMode": "source",
  "foldHeading": false,
  "showLineNumber": false,
  "readableLineLength": true,
  "strictLineBreaks": false,
  "newFileLocation": "folder",
  "newFileFolderPath": "Daily",
  "attachmentFolderPath": "Assets"
}
""", force)

    write(ROOT / ".obsidian" / "appearance.json", """{
  "theme": "obsidian",
  "cssTheme": "",
  "baseFontSize": 16,
  "enabledCssSnippets": []
}
""", force)


def init_lane_readmes(name: str, force: bool):
    write(ROOT / "Jobs" / "README.md", f"""---
type: reference
lane: jobs
tags:
  - jobs
  - reference
---

# Jobs Lane

## Active Search
- **Target Roles:**
- **Pay Floor:**
- **Remote OK:**

## Pipeline

```dataview
TABLE company, role, date_applied, status, follow_up AS "Follow Up"
FROM "Jobs"
WHERE type = "application" AND status != "dead"
SORT date_applied DESC
```

## Contacts

```dataview
TABLE company, title, warmth, last_contact, next_followup AS "Next Follow-up"
FROM "Jobs"
WHERE type = "contact"
SORT last_contact DESC
```

## All Applications (including closed)

```dataview
TABLE company, role, date_applied, status
FROM "Jobs"
WHERE type = "application"
SORT date_applied DESC
```

## Market Notes


## Job Fairs / Events
| Date | Event | Location | Notes |
|------|-------|----------|-------|
| | | | |
""", force)

    write(ROOT / "Build" / "README.md", f"""---
type: reference
lane: build
tags:
  - build
  - reference
---

# Build Lane

## Active Projects

```dataview
TABLE stack, started, status
FROM "Build"
WHERE type = "project" AND status = "active"
SORT started DESC
```

## All Projects

```dataview
TABLE stack, started, status
FROM "Build"
WHERE type = "project"
SORT started DESC
```

## Equipment / Makerspace


## Ideas Inbox


## Shipped

""", force)

    write(ROOT / "Learn" / "README.md", f"""---
type: reference
lane: learn
tags:
  - learn
  - reference
---

# Learn Lane

## Active Courses
| Course | Platform | Started | Progress |
|--------|----------|---------|----------|
| | | | |

## Reading
| Title | Type | Status | Key Takeaway |
|-------|------|--------|--------------|
| | | | |

## Skills Inventory

### Strong

### Working Knowledge

### Learning

### Gap (jobs keep asking for this)

## Notes

""", force)

    write(ROOT / "Home" / "README.md", f"""---
type: reference
lane: home
tags:
  - home
  - reference
---

# Home Lane

## Systems Index

```dataview
TABLE category, location, warranty_expires AS "Warranty"
FROM "Home"
WHERE type = "maintenance"
SORT category ASC
```

## Overdue / Urgent

```dataview
TABLE category, location
FROM "Home"
WHERE type = "maintenance" AND contains(tags, "urgent")
```

## Seasonal Calendar
| Month | Task |
|-------|------|
| Jan | |
| Feb | |
| Mar | |
| Apr | |
| May | |
| Jun | |
| Jul | |
| Aug | |
| Sep | |
| Oct | |
| Nov | |
| Dec | |

## Open Items
- [ ]

## Vendors
| Name | Trade | Phone | Rating |
|------|-------|-------|--------|
| | | | |
""", force)

    write(ROOT / "Write" / "README.md", f"""---
type: reference
lane: write
tags:
  - write
  - reference
---

# Write Lane

## In Progress
| Title | Type | Started | Status |
|-------|------|---------|--------|
| | | | |

## Ideas Inbox


## Published / Shipped
| Title | Where | Date |
|-------|-------|------|
| | | |

## Voice & Style Notes

""", force)

    write(ROOT / "Self" / "README.md", f"""---
type: reference
lane: self
tags:
  - self
  - reference
---

# Self Lane

## Current Focus


## Health
- **Exercise:**
- **Sleep:**
- **Diet:**
- **Energy patterns:**

## Motivation


## Wins Log


## The Hard Stuff


## Anchors


""", force)

    write(ROOT / "Finance" / "README.md", f"""---
type: reference
lane: finance
tags:
  - finance
  - reference
---

# Finance Lane

## Current State
| | |
|-|-----|
| Monthly burn | |
| Monthly income | |
| Net gap | |
| Liquid savings | |
| Runway | |
| ETH | |

## Documents

```dataview
TABLE date, type
FROM "Finance"
WHERE type != "reference"
SORT date DESC
```

## Notes

""", force)


def init_agent_memories(name: str, force: bool):
    LANES = ["dispatch", "jobs", "build", "learn", "home", "write", "self", "finance"]
    LANE_DESCRIPTIONS = {
        "dispatch": "Cross-lane coordinator. Sees everything.",
        "jobs":     "Job search — applications, contacts, follow-ups.",
        "build":    "Projects, apps, makerspace, creative pipeline.",
        "learn":    "Courses, skills, staying current.",
        "home":     "House as a system — maintenance, vendors, property.",
        "write":    "Writing pipeline — ideas, drafts, publishing.",
        "self":     "The person running all of this.",
        "finance":  "Financial reality across all lanes. Burn rate, runway, offer math, crypto.",
    }
    today = datetime.now().strftime("%Y-%m-%d")
    for lane in LANES:
        if lane == "finance":
            write(ROOT / "Agents" / "finance" / "memory.md", f"""# Finance Officer — Memory Ledger

## Monthly Burn Rate
- Total: unknown

## Income
- unknown

## Savings & Runway
- Liquid savings: unknown
- Runway: unknown

## Crypto
- ETH held: unknown
- Price basis: unknown
- Current strategy: unknown

## Salary Floor
- Minimum acceptable gross: unknown

## Fixed Costs
- Housing: unknown
- Healthcare: unknown
- Kids: unknown
- Vehicles: unknown
- Other recurring: unknown

## Notes
""", force)
        else:
            write(ROOT / "Agents" / lane / "memory.md", f"""# {lane.capitalize()} Agent — Memory

*Private. Not shared with other agents.*
*{LANE_DESCRIPTIONS[lane]}*

---

## About {name}

> Fill this in as you learn about the person over time.
> What are their patterns? How do they communicate? What do they avoid?


## Patterns To Watch


## Conversation Log

| Date | Key Insight |
|------|------------|
| {today} | Vault initialized. |
""", force)


def init_today_note(force: bool):
    today     = datetime.now().strftime("%Y-%m-%d")
    day_name  = datetime.now().strftime("%A")
    note_path = ROOT / "Daily" / f"{today}.md"
    write(note_path, f"""---
date: {today}
type: daily
tags:
  - daily
---

# {today} — {day_name}

## Standup

### 🎯 Jobs
- [ ]

### 🔨 Build
- [ ]

### 📚 Learn
- [ ]

### 🏠 Home
- [ ]

### ✍️ Write
- [ ]

### 💪 Self
- [ ]

### 💰 Finance
- [ ]

---

## Brain Dump


---

## Carryover


---

## EOD Notes

""", force, "today's daily note")


def main():
    parser = argparse.ArgumentParser(description="Initialize a Dispatch vault")
    parser.add_argument("--name", default="User", help="Your name (used in agent memory files)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    print(f"\nDispatch — vault init")
    print(f"Name: {args.name}")
    print(f"Path: {ROOT}")
    print(f"Force: {args.force}\n")

    print("Creating folders...")
    init_folders()

    print("\nConfiguring environment...")
    init_env(args.force)

    print("\nConfiguring Obsidian...")
    init_obsidian(args.force)

    print("\nWriting lane READMEs...")
    init_lane_readmes(args.name, args.force)

    print("\nWriting agent memory stubs...")
    init_agent_memories(args.name, args.force)

    print("\nCreating today's daily note...")
    init_today_note(args.force)

    print(f"""
Done.

Next steps:
  1. Add your ANTHROPIC_API_KEY to .env
  2. Open this folder as a vault in Obsidian
  3. Install plugins: Templater, Dataview, Tasks
  4. Run: python assistant/server.py
  5. Open: http://127.0.0.1:5151

Fill in Self/README.md first. The agents read it as anchoring context.
""")


if __name__ == "__main__":
    main()
