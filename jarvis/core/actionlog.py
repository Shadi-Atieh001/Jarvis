"""Append-only record of everything JARVIS does.

One JSON object per line in <home>/actions.jsonl, so the file can be read
with any text editor. Secrets are scrubbed before anything is written.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_FIELD = 2000  # characters kept per logged value

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)(\"?\s*[:=]\s*\"?)([^\s\"',}]{6,})"),
]


def redact(text: str) -> str:
    """Remove anything that looks like a credential."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key and len(key) >= 8:
        text = text.replace(key, "[REDACTED]")
    text = _SECRET_PATTERNS[0].sub("[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    return text


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        value = redact(value)
        if len(value) > MAX_FIELD:
            value = value[:MAX_FIELD] + f"... [{len(value) - MAX_FIELD} more characters]"
    return value


class ActionLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: str, **fields: Any) -> None:
        """event is e.g. 'tool', 'user_message', 'kill_switch', 'session_start'."""
        entry = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "event": event}
        entry.update(_clean(fields))
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def tail(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


def format_entries(entries: list[dict]) -> str:
    """Human-readable rendering for the /log command."""
    if not entries:
        return "The action log is empty."
    rows = []
    for e in entries:
        when = e.get("time", "")[:19].replace("T", " ")
        if e.get("event") == "tool":
            args = json.dumps(e.get("args", {}), ensure_ascii=False)
            if len(args) > 110:
                args = args[:110] + "..."
            rows.append(f"{when}  {e.get('decision', '?'):<13} {e.get('tool')}  {args}")
        else:
            detail = e.get("detail") or e.get("text") or ""
            detail = str(detail).replace("\n", " ")
            if len(detail) > 110:
                detail = detail[:110] + "..."
            rows.append(f"{when}  {e.get('event'):<13} {detail}")
    return "\n".join(rows)
