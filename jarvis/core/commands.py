"""Slash commands, shared by every interface.

handle() returns the text to show, or None if the input is not a command
and should go to the model instead.
"""

from __future__ import annotations

from .actionlog import format_entries
from .agent import Jarvis
from jarvis.memory.store import format_memories
from jarvis.scheduler.store import format_items

HELP = """Commands:
  /help            show this list
  /tools           list the tools JARVIS has and their permission tiers
  /log [n]         show the last n actions (default 20)
  /schedule        show reminders and scheduled tasks;  /unschedule <number>  cancels one
  /memories [text] show what JARVIS remembers (optionally: about text)
  /forget <number> delete one memory;  /forget all  deletes everything
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
            override = jarvis.settings.tool_tiers.get(name)
            detail = f'set to "{override}" in settings.toml' if override else (t.kind or "follows its own tier")
            rows.append(f"  {name:<15} {detail}")
        return (
            f'Permission mode: {jarvis.settings.permission_mode}\n'
            "Tools and the kind of action each performs:\n" + "\n".join(rows)
        )
    if cmd == "/log":
        n = int(args[0]) if args and args[0].isdigit() else 20
        return format_entries(jarvis.log.tail(n))
    if cmd in ("/schedule", "/unschedule"):
        schedule = jarvis.ctx.schedule
        if schedule is None:
            return "Scheduling is only available in the JARVIS window."
        if cmd == "/schedule":
            return "Scheduled:\n" + format_items(schedule.items())
        if not args or not args[0].lstrip("#").isdigit():
            return "Usage: /unschedule <number>   (see /schedule for the numbers)"
        number = int(args[0].lstrip("#"))
        return f"Cancelled #{number}." if schedule.remove(number) else f"There is no scheduled item #{number}."
    if cmd in ("/memories", "/memory"):
        if jarvis.memory is None:
            return "Memory is switched off in settings.toml."
        facts, past = jarvis.memory.counts()
        if args:
            found = jarvis.memory.search(" ".join(args), limit=20)
            return f"Memories about {' '.join(args)!r}:\n" + format_memories(found)
        note = "" if jarvis.memory.semantic else "\n(Searching by matching words; install the memory extra for search by meaning.)"
        return (
            f"{facts} saved memories, {past} past exchanges on record.\n"
            + format_memories(jarvis.memory.all())
            + "\nDelete one with /forget <number>, or everything with /forget all."
            + note
        )
    if cmd == "/forget":
        if jarvis.memory is None:
            return "Memory is switched off in settings.toml."
        if args and args[0].lower() == "all":
            if len(args) < 2 or args[1].lower() != "yes":
                facts, past = jarvis.memory.counts()
                return f"This deletes all {facts} memories and {past} past exchanges for good. Type  /forget all yes  to confirm."
            count = jarvis.memory.forget_everything()
            jarvis.log.record("memory", detail=f"all memory deleted by command ({count} memories)")
            return "Everything has been forgotten."
        if not args or not args[0].lstrip("#").isdigit():
            return "Usage: /forget <number>   (see /memories for the numbers)"
        number = int(args[0].lstrip("#"))
        if jarvis.memory.forget(number):
            jarvis.log.record("memory", detail=f"memory #{number} deleted by command")
            return f"Forgot memory #{number}."
        return f"There is no memory #{number}."
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
