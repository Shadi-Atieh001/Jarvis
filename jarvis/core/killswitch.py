"""Emergency stop.

The switch is "tripped" when either:
  * something in this process calls trip() (the Stop button, /stop, Ctrl+C), or
  * the STOP file exists in JARVIS's home folder. `python -m jarvis stop`
    creates that file, so you can halt JARVIS from any other terminal even
    if its window has frozen.

While tripped, the agent loop refuses to call the model or run any tool, and
every child process JARVIS started is killed. It stays tripped until
reset() (/resume or `python -m jarvis resume`).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path


class Stopped(Exception):
    """Raised inside the agent loop when the kill switch is tripped."""


class KillSwitch:
    def __init__(self, stop_file: Path):
        self.stop_file = stop_file
        self._event = threading.Event()
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    @property
    def tripped(self) -> bool:
        return self._event.is_set() or self.stop_file.exists()

    def check(self) -> None:
        if self.tripped:
            self.kill_processes()
            raise Stopped()

    def trip(self, persist: bool = True) -> None:
        """Stop everything. With persist, also write the STOP file so the
        stop survives a restart and reaches other JARVIS processes."""
        self._event.set()
        if persist:
            self.stop_file.parent.mkdir(parents=True, exist_ok=True)
            self.stop_file.write_text("stopped\n", encoding="utf-8")
        self.kill_processes()

    def reset(self) -> None:
        self._event.clear()
        self.stop_file.unlink(missing_ok=True)

    # Child processes register here so a stop can kill them.
    def register(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.add(proc)

    def unregister(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(proc)

    def kill_processes(self) -> None:
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            kill_tree(proc)


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill a process and everything it spawned."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
