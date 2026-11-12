"""Command-line entry point:  python -m jarvis <command>

  app      open the desktop window (default)
  web      same interface, in your browser
  chat     chat in this terminal
  stop     EMERGENCY STOP: halt a running JARVIS from any terminal
  resume   clear the emergency stop
  log [n]  show the last n actions
  setup    download and test the memory and speech models (run once)
"""

from __future__ import annotations

import sys

from jarvis.app import build, startup_problem
from jarvis.core.actionlog import ActionLog, format_entries
from jarvis.core.config import load_settings
from jarvis.core.killswitch import KillSwitch


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
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

    problem = startup_problem()
    if problem:
        print(problem)
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

        run_window(jarvis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
