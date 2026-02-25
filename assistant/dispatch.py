"""
Dispatch Assistant — main entry point.
A conversational CLI that reads your vault and routes your messages
to the right lane agent via Claude.

Usage:
    python dispatch.py                  # general dispatch mode
    python dispatch.py --lane jobs      # focus on a specific lane
    python dispatch.py --standup        # morning standup across all lanes
    python dispatch.py --draft          # write something to a vault note
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich import print as rprint

# Load from vault root .env
vault_root = Path(__file__).parent.parent
load_dotenv(vault_root / ".env")

from vault import Vault
from agents import AGENTS, get_agent, detect_lane

console = Console()

VAULT_PATH = os.getenv("VAULT_PATH", str(vault_root))
MODEL = os.getenv("DISPATCH_MODEL", "claude-opus-4-6")
API_KEY = os.getenv("ANTHROPIC_API_KEY")


def get_client() -> anthropic.Anthropic:
    if not API_KEY:
        console.print("[red]No ANTHROPIC_API_KEY found. Copy .env.example to .env and add your key.[/red]")
        sys.exit(1)
    return anthropic.Anthropic(api_key=API_KEY)


def stream_response(client: anthropic.Anthropic, system: str, messages: list, context: str, memory: str = "") -> str:
    """Stream a Claude response and return the full text."""
    memory_block = f"\n\n---\n\n# YOUR PRIVATE MEMORY\n\n{memory}" if memory else ""
    full_context_system = f"{system}{memory_block}\n\n---\n\n# VAULT CONTEXT\n\n{context}"

    full_text = ""
    console.print()

    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        system=full_context_system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full_text += text

    print()  # newline after stream
    return full_text


def run_standup(client: anthropic.Anthropic, vault: Vault):
    """Morning standup — brief from every lane, today's priorities."""
    console.print(Rule("[bold blue]DISPATCH STANDUP[/bold blue]"))
    console.print(f"[dim]{datetime.now().strftime('%A, %B %d %Y — %H:%M')}[/dim]\n")

    context = vault.build_context()
    agent = get_agent("dispatch")
    memory = vault.agent_memory("dispatch") or ""

    standup_prompt = """Run the morning standup. For each lane, give me:
- One sentence on current status
- The single most important thing right now

Then give me the top 3 priorities for today across all lanes, ranked.
Keep it tight. I can ask follow-up questions about any lane."""

    messages = [{"role": "user", "content": standup_prompt}]
    stream_response(client, agent["system"], messages, context, memory)


def run_chat(client: anthropic.Anthropic, vault: Vault, lane: str = "dispatch"):
    """Interactive chat loop with the specified lane agent."""
    agent = get_agent(lane)

    console.print(Panel(
        f"[bold]{agent['emoji']} {agent['name']}[/bold]\n[dim]{agent['description']}[/dim]",
        border_style="blue"
    ))
    console.print("[dim]Type your message. 'exit' to quit. '/lane <name>' to switch agents. '/refresh' to reload vault.[/dim]\n")

    conversation_history = []
    current_lane = lane
    current_agent = agent

    # Load context once at start, refresh on demand
    focus = [current_lane.capitalize()] if current_lane != "dispatch" else None
    context = vault.build_context(focus_lanes=focus)
    memory = vault.agent_memory(current_lane) or ""

    while True:
        try:
            user_input = Prompt.ask("[bold blue]You[/bold blue]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Dispatch out.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            console.print("[dim]Dispatch out.[/dim]")
            break

        if user_input.lower() == "/refresh":
            vault.refresh()
            context = vault.build_context(focus_lanes=focus)
            console.print("[dim]Vault refreshed.[/dim]")
            continue

        if user_input.lower().startswith("/lane "):
            new_lane = user_input[6:].strip().lower()
            if new_lane in AGENTS:
                current_lane = new_lane
                current_agent = get_agent(new_lane)
                focus = [current_lane.capitalize()] if current_lane != "dispatch" else None
                context = vault.build_context(focus_lanes=focus)
                memory = vault.agent_memory(current_lane) or ""
                conversation_history = []  # fresh context for new lane
                console.print(f"\n[dim]Switched to {current_agent['emoji']} {current_agent['name']}[/dim]\n")
            else:
                console.print(f"[yellow]Unknown lane. Options: {', '.join(AGENTS.keys())}[/yellow]")
            continue

        if user_input.lower() == "/standup":
            run_standup(client, vault)
            continue

        if user_input.lower() == "/lanes":
            for key, ag in AGENTS.items():
                console.print(f"  [bold]{ag['emoji']} {key}[/bold] — {ag['description']}")
            continue

        if user_input.lower().startswith("/remember "):
            note = user_input[10:].strip()
            if note:
                existing = vault.agent_memory(current_lane) or ""
                from datetime import datetime as dt
                entry = f"\n| {dt.now().strftime('%Y-%m-%d')} | {note} |"
                # Append to conversation log if it exists, otherwise just append
                if "## Conversation Log" in existing:
                    updated = existing.rstrip() + entry + "\n"
                else:
                    updated = existing.rstrip() + f"\n\n## Conversation Log\n| Date | Key Insight |\n|------|------------|\n{entry}\n"
                vault.update_agent_memory(current_lane, updated)
                memory = updated
                console.print(f"[dim]{current_agent['emoji']} Memory updated.[/dim]")
            continue

        # Auto-detect lane if in dispatch mode and user hasn't locked one
        if current_lane == "dispatch" and lane == "dispatch":
            detected = detect_lane(user_input)
            if detected != "dispatch":
                # Silently add relevant lane context
                focus = [detected.capitalize()]
                context = vault.build_context(focus_lanes=focus)

        conversation_history.append({"role": "user", "content": user_input})

        console.print(f"\n[bold]{current_agent['emoji']} {current_agent['name']}[/bold]", end="")

        response = stream_response(client, current_agent["system"], conversation_history, context, memory)
        conversation_history.append({"role": "assistant", "content": response})
        console.print()


def write_to_vault(client: anthropic.Anthropic, vault: Vault):
    """
    Draft mode — have the assistant write something directly to the vault.
    Useful for creating new notes, job applications, project specs, etc.
    """
    console.print(Rule("[bold blue]DRAFT MODE[/bold blue]"))
    console.print("[dim]Tell me what to write. I'll draft it and you confirm before it saves.[/dim]\n")

    user_input = Prompt.ask("[bold blue]What do you need[/bold blue]").strip()
    if not user_input:
        return

    context = vault.build_context()
    agent = get_agent("dispatch")
    memory = vault.agent_memory("dispatch") or ""

    draft_prompt = f"""The user wants to create a new vault note. Their request: "{user_input}"

Draft the complete markdown content for this note. Use the established templates and conventions
from the vault. Include all relevant frontmatter, sections, and placeholder text.

After the note content, on a new line write exactly:
SAVE_AS: <suggested relative path within vault, e.g. Jobs/Acme-Corp-Sr-Dev.md>"""

    messages = [{"role": "user", "content": draft_prompt}]
    response = stream_response(client, agent["system"], messages, context, memory)

    # Parse save path
    save_path = None
    if "SAVE_AS:" in response:
        lines = response.strip().splitlines()
        for line in lines:
            if line.startswith("SAVE_AS:"):
                save_path = line.replace("SAVE_AS:", "").strip()
                break

    if save_path:
        full_path = vault.root / save_path
        confirm = Prompt.ask(f"\n[yellow]Save to[/yellow] [bold]{save_path}[/bold]? [y/n]")
        if confirm.lower() == "y":
            full_path.parent.mkdir(parents=True, exist_ok=True)
            # Strip the SAVE_AS line from content
            clean_content = "\n".join(
                line for line in response.splitlines()
                if not line.startswith("SAVE_AS:")
            ).strip()
            full_path.write_text(clean_content, encoding="utf-8")
            console.print(f"[green]Saved to {save_path}[/green]")
        else:
            console.print("[dim]Discarded.[/dim]")


def main():
    parser = argparse.ArgumentParser(description="Dispatch — your personal command assistant")
    parser.add_argument("--lane", "-l", default="dispatch",
                        choices=list(AGENTS.keys()),
                        help="Which lane agent to talk to")
    parser.add_argument("--standup", "-s", action="store_true",
                        help="Run morning standup across all lanes")
    parser.add_argument("--draft", "-d", action="store_true",
                        help="Draft a new vault note")
    parser.add_argument("--query", "-q", type=str,
                        help="Single question, non-interactive")
    args = parser.parse_args()

    client = get_client()
    vault = Vault(VAULT_PATH)

    console.print(Panel(
        "[bold blue]DISPATCH[/bold blue]\n[dim]Personal command center. Six lanes. One standup.[/dim]",
        border_style="dim"
    ))
    console.print(f"[dim]Vault: {len(vault.notes)} notes loaded from {VAULT_PATH}[/dim]\n")

    if args.standup:
        run_standup(client, vault)

    elif args.draft:
        write_to_vault(client, vault)

    elif args.query:
        agent = get_agent(args.lane)
        focus = [args.lane.capitalize()] if args.lane != "dispatch" else None
        context = vault.build_context(focus_lanes=focus)
        memory = vault.agent_memory(args.lane) or ""
        messages = [{"role": "user", "content": args.query}]
        stream_response(client, agent["system"], messages, context, memory)

    else:
        run_chat(client, vault, lane=args.lane)


if __name__ == "__main__":
    main()
