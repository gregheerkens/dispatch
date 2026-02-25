"""
Vault reader — loads and indexes all markdown files in the Dispatch vault.
This is the RAG layer. Every note becomes context the assistant can reason over.
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional


LANE_ORDER = ["Jobs", "Build", "Learn", "Home", "Write", "Self", "Daily"]

IGNORE_DIRS = {".obsidian", ".git", "Assets", "Templates", "__pycache__", "Agents"}


class VaultNote:
    def __init__(self, path: Path, vault_root: Path):
        self.path = path
        self.relative = path.relative_to(vault_root)
        self.lane = self._detect_lane()
        self.modified = datetime.fromtimestamp(path.stat().st_mtime)
        self._content: Optional[str] = None

    def _detect_lane(self) -> str:
        parts = self.relative.parts
        if len(parts) > 1 and parts[0] in LANE_ORDER:
            return parts[0]
        return "Root"

    @property
    def content(self) -> str:
        if self._content is None:
            self._content = self.path.read_text(encoding="utf-8", errors="ignore")
        return self._content

    @property
    def title(self) -> str:
        # First H1 heading, or filename
        for line in self.content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return self.path.stem

    def summary(self) -> str:
        """First 400 chars of content, for context packing."""
        return self.content[:400].strip()

    def __repr__(self):
        return f"<VaultNote {self.relative} [{self.lane}]>"


class Vault:
    def __init__(self, vault_path: str):
        self.root = Path(vault_path)
        self.notes: list[VaultNote] = []
        self._load()

    def _load(self):
        self.notes = []
        for md_file in self.root.rglob("*.md"):
            # Skip ignored directories
            if any(part in IGNORE_DIRS for part in md_file.parts):
                continue
            self.notes.append(VaultNote(md_file, self.root))

    def refresh(self):
        """Reload vault from disk."""
        self._load()

    def by_lane(self, lane: str) -> list[VaultNote]:
        return [n for n in self.notes if n.lane == lane]

    def recent_daily_notes(self, days: int = 7) -> list[VaultNote]:
        cutoff = datetime.now() - timedelta(days=days)
        daily = [n for n in self.notes if n.lane == "Daily"]
        recent = [n for n in daily if n.modified >= cutoff]
        return sorted(recent, key=lambda n: n.modified, reverse=True)

    def today_note(self) -> Optional[VaultNote]:
        today = datetime.now().strftime("%Y-%m-%d")
        for note in self.notes:
            if note.lane == "Daily" and today in note.path.name:
                return note
        return None

    def write_standup_note(self, reports: dict[str, str], synthesis: str) -> str:
        """
        Save standup minutes to Daily/YYYY-MM-DD-standup.md.
        Returns the relative path of the saved note.
        """
        now = datetime.now()
        date_str  = now.strftime("%Y-%m-%d")
        date_long = now.strftime("%A, %B %d %Y")
        filename  = f"{date_str}-standup.md"
        path      = self.root / "Daily" / filename

        LANE_META = {
            "jobs":  ("💼", "Jobs",  "info"),
            "build": ("🔨", "Build", "warning"),
            "learn": ("📚", "Learn", "success"),
            "home":  ("🏠", "Home",  "question"),
            "write": ("✍️", "Write", "abstract"),
            "self":  ("💪", "Self",  "danger"),
        }

        lane_blocks = []
        for lane_id, report in reports.items():
            emoji, name, callout = LANE_META.get(lane_id, ("·", lane_id.upper(), "note"))
            # Indent report lines for callout block
            indented = "\n".join(f"> {line}" for line in report.strip().splitlines())
            lane_blocks.append(f"> [!{callout}]+ {emoji} {name}\n{indented}")

        lanes_section = "\n\n".join(lane_blocks)

        content = f"""---
date: {date_str}
type: standup
tags:
  - standup
  - daily
---

# Standup — {date_long}

## Lane Reports

{lanes_section}

---

## Dispatch Synthesis

{synthesis.strip()}

---

## Action Items
> Add tasks here during or after standup. Tag with lane + priority.

- [ ]

"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.refresh()
        return f"Daily/{filename}"

    def agent_memory(self, agent_name: str) -> Optional[str]:
        """
        Load a specific agent's private memory file.
        Only the agent itself should call this — memory is not cross-shared.
        """
        memory_path = self.root / "Agents" / agent_name.lower() / "memory.md"
        if memory_path.exists():
            return memory_path.read_text(encoding="utf-8", errors="ignore")
        return None

    def update_agent_memory(self, agent_name: str, new_content: str):
        """Overwrite an agent's memory file."""
        memory_path = self.root / "Agents" / agent_name.lower() / "memory.md"
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(new_content, encoding="utf-8")

    def load_history(self, lane: str) -> list[dict]:
        """Load persisted chat history for a lane. Returns [] if none."""
        path = self.root / "Agents" / lane.lower() / "history.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("messages", [])
        except Exception:
            return []

    def save_history(self, lane: str, messages: list[dict]):
        """Persist chat history for a lane, capped at 100 messages."""
        path = self.root / "Agents" / lane.lower() / "history.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        trimmed = messages[-100:]
        path.write_text(
            json.dumps({"version": 1, "messages": trimmed}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_note(self, lane: str, title: str, content: str) -> Path:
        """Create a new note in the vault. Returns the created path."""
        slug = re.sub(r"[^\w\s-]", "", title).strip()
        slug = re.sub(r"[-\s]+", "-", slug).lower()
        path = self.root / lane / f"{slug}.md"
        if path.exists():
            ts = datetime.now().strftime("%H%M%S")
            path = self.root / lane / f"{slug}-{ts}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.refresh()
        return path

    def update_note(self, path_str: str, content: str) -> Path:
        """Update an existing note by relative path from vault root."""
        path = self.root / path_str
        if not path.exists():
            raise FileNotFoundError(f"Note not found: {path_str}")
        path.write_text(content, encoding="utf-8")
        self.refresh()
        return path

    def list_notes(self, lane: str) -> list[dict]:
        """Return [{title, path}] for all notes in a lane."""
        return [{"title": n.title, "path": str(n.relative)} for n in self.by_lane(lane)]

    def search(self, query: str) -> list[VaultNote]:
        """Simple case-insensitive full-text search."""
        query_lower = query.lower()
        results = []
        for note in self.notes:
            if query_lower in note.content.lower():
                results.append(note)
        return results

    def build_context(self, focus_lanes: Optional[list[str]] = None, max_chars: int = 60000) -> str:
        """
        Build a context string for the Claude API.
        Pulls full content for focused lanes, summaries for others.
        Respects a character budget to stay within token limits.
        """
        self.refresh()
        sections = []
        chars_used = 0

        lanes_to_use = focus_lanes or LANE_ORDER

        # Always include Self/README for anchoring context
        self_notes = self.by_lane("Self")
        for note in self_notes:
            if "README" in note.path.name:
                block = f"## [{note.lane}] {note.title}\n{note.content}\n"
                sections.append(block)
                chars_used += len(block)

        # Today's daily note — always full
        today = self.today_note()
        if today:
            block = f"## [Daily — Today] {today.title}\n{today.content}\n"
            sections.append(block)
            chars_used += len(block)

        # Recent daily notes — summaries only
        for note in self.recent_daily_notes(days=7):
            if today and note.path == today.path:
                continue
            block = f"## [Daily — Recent] {note.title}\n{note.summary()}\n"
            if chars_used + len(block) < max_chars:
                sections.append(block)
                chars_used += len(block)

        # Lane notes
        for lane in lanes_to_use:
            if lane in ("Self", "Daily"):
                continue
            for note in self.by_lane(lane):
                use_full = focus_lanes and lane in focus_lanes
                content = note.content if use_full else note.summary()
                block = f"## [{lane}] {note.title}\n{content}\n"
                if chars_used + len(block) < max_chars:
                    sections.append(block)
                    chars_used += len(block)

        header = (
            f"# Dispatch Vault Context\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Notes loaded: {len(self.notes)} | Characters: {chars_used}\n\n"
        )

        return header + "\n---\n\n".join(sections)
