"""Updating JARVIS from inside the window.

JARVIS is installed as a copy of its GitHub repository, so updating means:
  1. git pull    fetch the newer code
  2. pip install install any libraries the newer code needs
Both are run here exactly as you would type them in a terminal. Only the
person at the window can start an update; the model has no tool for it.

An update only fast-forwards: if the folder has changes git cannot combine
automatically, nothing is changed and the reason is reported. Keep your own
settings in settings.local.toml (which git ignores) to avoid that.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

from jarvis import __version__
from jarvis.core.config import REPO_ROOT

# Each optional extra, and a module that is present only if it is installed.
EXTRAS = {"desktop": "webview", "memory": "fastembed", "voice": "faster_whisper", "dev": "pytest"}


class UpdateError(Exception):
    pass


def _run(args: list[str], timeout: int) -> str:
    """Run a command in the JARVIS folder; return its output or raise."""
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        result = subprocess.run(
            args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, **flags,
        )
    except FileNotFoundError:
        raise UpdateError(f"'{args[0]}' was not found. Updating needs Git installed (https://git-scm.com).") from None
    except subprocess.TimeoutExpired:
        raise UpdateError(f"'{' '.join(args[:3])}' took too long and was stopped.") from None
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise UpdateError(output or f"'{' '.join(args[:3])}' failed.")
    return output


def _git(*args: str, timeout: int = 60) -> str:
    return _run(["git", *args], timeout)


def check() -> dict:
    """Is there a newer version on GitHub? Changes nothing on disk except
    git's own record of what the remote holds."""
    if not (REPO_ROOT / ".git").exists():
        raise UpdateError("This copy of JARVIS was not installed with git, so it cannot update itself.")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    _git("fetch", "--quiet", "origin", branch)
    behind = int(_git("rev-list", "--count", f"HEAD..origin/{branch}") or 0)
    changes = _git("log", "--format=%s", f"HEAD..origin/{branch}").splitlines() if behind else []
    return {
        "version": __version__,
        "behind": behind,
        "changes": changes[:30],
        # Each line is a two-letter status and then the file name.
        "local_changes": [line.split(maxsplit=1)[-1] for line in _git("status", "--porcelain", "--untracked-files=no").splitlines()],
    }


def installed_extras() -> list[str]:
    return [name for name, module in EXTRAS.items() if importlib.util.find_spec(module) is not None]


def apply() -> dict:
    """Fetch the new code and install what it needs. Returns what happened."""
    before = _git("rev-parse", "--short", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    try:
        pulled = _git("pull", "--ff-only", "origin", branch, timeout=180)
    except UpdateError as exc:
        text = str(exc)
        if "would be overwritten" in text or "local changes" in text:
            raise UpdateError(
                "The update was not applied, because files in the Jarvis folder have been edited and git cannot "
                "combine the changes by itself. Move your own settings into settings.local.toml, undo the edit "
                "(git restore <file>), and try again.\n\n" + text
            ) from None
        raise
    after = _git("rev-parse", "--short", "HEAD")
    extras = installed_extras()
    target = f".[{','.join(extras)}]" if extras else "."
    installed = _run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-e", target], timeout=900)
    return {"from": before, "to": after, "changed": before != after, "extras": extras, "output": (pulled + "\n" + installed).strip()[-2000:]}
