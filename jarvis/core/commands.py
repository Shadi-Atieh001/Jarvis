"""Slash commands, shared by every interface.

handle() returns the text to show, or None if the input is not a command
and should go to the model instead.
"""

from __future__ import annotations

from .actionlog import format_entries
from .agent import Jarvis

HELP = """Commands:
  /help            show this list
  /tools           list the tools JARVIS has and their permission tiers
  /log [n]         show the last n actions (default 20)
  /stop            emergency stop: halt everything and refuse further actions
  /resume          clear the emergency stop
  /clear           start a fresh conversation
  /quit            exit
Anything else is sent to JARVIS."""

QUIT = "__quit__"


def handle(text: str, jarvis: Jarvis) -> str | None:
    if not text.startswith("/"):
        return None
    parts = text.strip().split()
    cmd, args = parts[0].lower(), parts[1:]

    if cmd == "/help":
        return HELP
    if cmd == "/tools":
        rows = []
        for name in sorted(jarvis.registry.tools):
            t = jarvis.registry.tools[name]
            tier = jarvis.settings.tool_tiers.get(name) or t.tier or jarvis.settings.default_tier
            note = " (may ask for riskier calls)" if t.escalate and tier == "auto" else ""
            rows.append(f"  {name:<14} {tier}{note}")
        return "Tools and their tiers:\n" + "\n".join(rows)
    if cmd == "/log":
        n = int(args[0]) if args and args[0].isdigit() else 20
        return format_entries(jarvis.log.tail(n))
    if cmd == "/stop":
        jarvis.kill.trip()
        jarvis.log.record("kill_switch", detail="tripped by /stop")
        return "Emergency stop engaged. Nothing further will run until you type /resume."
    if cmd == "/resume":
        jarvis.kill.reset()
        jarvis.log.record("kill_switch", detail="reset by /resume")
        return "Emergency stop cleared."
    if cmd == "/clear":
        jarvis.clear()
        return "Conversation cleared."
    if cmd in ("/quit", "/exit"):
        return QUIT
    return f"Unknown command {cmd}. Type /help for the list."
