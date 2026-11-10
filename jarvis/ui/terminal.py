"""Plain terminal chat. Useful for testing and when the window is unavailable."""

from __future__ import annotations

from jarvis.core import commands
from jarvis.core.agent import Jarvis
from jarvis.core.permissions import Decision


class TerminalUI:
    def on_text(self, delta: str) -> None:
        print(delta, end="", flush=True)

    def on_tool(self, name: str, decision: str, summary: str) -> None:
        print(f"\n  [{decision}] {name}: {summary}", flush=True)

    def confirm(self, tool_name: str, decision: Decision) -> bool:
        print("\n" + "-" * 60)
        print(f"JARVIS wants to use {tool_name} ({decision.reason}):\n")
        print(decision.description)
        print("-" * 60)
        try:
            answer = input('Type "yes" to allow, anything else to refuse: ')
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() == "yes"


def run(jarvis: Jarvis) -> None:
    ui = TerminalUI()
    sir = jarvis.settings.address_as
    print(f"JARVIS at your service, {sir}. Type /help for commands; Ctrl+C interrupts a running task.")
    if jarvis.kill.tripped:
        print("Note: the emergency stop is engaged. Type /resume to clear it.")
    jarvis.log.record("session_start", detail="terminal")

    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        reply = commands.handle(text, jarvis)
        if reply == commands.QUIT:
            break
        if reply is not None:
            print(reply)
            continue

        if jarvis.kill.tripped:
            print("The emergency stop is engaged. Type /resume to clear it.")
            continue

        print("\nJARVIS: ", end="", flush=True)
        try:
            status = jarvis.send(text, ui)
        except KeyboardInterrupt:
            # Ctrl+C halts this task only; it does not leave the stop engaged.
            jarvis.kill.kill_processes()
            jarvis.log.record("kill_switch", detail="task interrupted with Ctrl+C")
            print("\n[Interrupted.]")
            continue
        except Exception as exc:
            jarvis.log.record("error", detail=f"{type(exc).__name__}: {exc}")
            print(f"\n[Something went wrong: {type(exc).__name__}: {exc}]")
            continue
        print()
        if status == "stopped":
            print("[Stopped. Type /resume to clear the emergency stop.]")
