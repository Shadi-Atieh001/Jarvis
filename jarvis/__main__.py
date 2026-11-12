"""Command-line entry point:  python -m jarvis <command>

  app      open the desktop window (default)
  web      same interface, in your browser
  chat     chat in this terminal
  stop     EMERGENCY STOP: halt a running JARVIS from any terminal
  resume   clear the emergency stop
  log [n]  show the last n actions
  setup    download and test the memory and speech models (run once)
  connect google|spotify      sign in to an online account
  disconnect google|spotify   sign out and delete the stored tokens
  connections                 show which accounts are connected
  install-shortcut            add JARVIS to the desktop and Start menu
  autostart on|off            start JARVIS in the tray when you sign in to Windows
Add --tray to "app" to start hidden in the tray.
"""

from __future__ import annotations

import sys

from jarvis.app import build, startup_problem
from jarvis.core.actionlog import ActionLog, format_entries
from jarvis.core.config import load_settings
from jarvis.core.killswitch import KillSwitch


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    start_hidden = "--tray" in argv
    argv = [a for a in argv if a != "--tray"]
    command = argv[0] if argv else "app"

    # These three must work even when JARVIS itself is broken or busy,
    # so they touch nothing but the settings and two files.
    if command in ("stop", "resume", "log"):
        settings = load_settings()
        log = ActionLog(settings.action_log_path)
        if command == "stop":
            KillSwitch(settings.stop_file).trip()
            log.record("kill_switch", detail="tripped from the command line")
            print("Emergency stop engaged. Run 'python -m jarvis resume' to clear it.")
        elif command == "resume":
            KillSwitch(settings.stop_file).reset()
            log.record("kill_switch", detail="reset from the command line")
            print("Emergency stop cleared.")
        else:
            n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 20
            print(format_entries(log.tail(n)))
        return 0

    if command == "autostart":
        from jarvis.ui.shortcut import autostart

        if len(argv) < 2 or argv[1] not in ("on", "off"):
            print("Usage: python -m jarvis autostart on|off")
            return 2
        return autostart(argv[1] == "on")

    if command == "install-shortcut":
        from jarvis.ui.shortcut import install

        return install()

    if command in ("connect", "disconnect", "connections"):
        from jarvis.integrations.cli import run

        return run(command, argv[1:])

    if command in ("setup", "voice-setup"):
        settings = load_settings()
        result = 0
        if command == "setup" and settings.memory_enabled:
            from jarvis.memory.store import MemoryStore

            print("Loading the memory model (first run downloads about 65 MB) ...")
            store = MemoryStore(settings)
            if store.semantic:
                print("Memory is ready (search by meaning).")
            else:
                print('Memory will search by matching words. For search by meaning run:  pip install -e ".[memory]"')
                result = 1
        from jarvis.voice.engine import setup

        return setup(settings) or result

    if command not in ("app", "web", "chat"):
        print(__doc__)
        return 0 if command in ("help", "-h", "--help") else 2

    windowless = sys.stdout is None  # started from the shortcut: there is no terminal
    if windowless:
        # Nothing can be printed, so keep a log file instead.
        log_file = open(load_settings().home / "jarvis.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log_file

    problem = startup_problem()
    if problem:
        print(problem)
        if windowless:
            _message_box(problem)
        return 1

    jarvis = build()
    if command == "chat":
        from jarvis.ui.terminal import run

        run(jarvis)
    elif command == "web":
        from jarvis.ui.desktop import run_browser

        run_browser(jarvis)
    else:
        from jarvis.ui.desktop import run_window

        run_window(jarvis, start_hidden=start_hidden)
    return 0


def _message_box(text: str) -> None:
    """Show a problem when there is no terminal to print it in."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "JARVIS", 0x30)  # 0x30: warning icon


if __name__ == "__main__":
    raise SystemExit(main())
