"""How many tokens JARVIS has used, kept per day in <home>/usage.json.

A token is roughly three-quarters of a word. Model services meter and limit
use in tokens: both what is sent (the whole conversation, the instructions
and the tool list, on every request) and what comes back.

Days here follow UTC, because that is when hosted services reset their daily
allowances (the IFM service resets at 00:00 UTC, which is 04:00 in the UAE).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_locks: dict[str, threading.Lock] = {}  # one per file, shared by every agent in this process
_reported: dict[str, dict] = {}
KEEP_DAYS = 60


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class UsageLog:
    def __init__(self, path: Path):
        self.path = path
        self._lock = _locks.setdefault(str(path), threading.Lock())

    # What the service itself last reported about the daily allowance, if
    # it reports anything. Shared between every agent using the same file.
    def note_limits(self, limits: dict) -> None:
        if limits:
            _reported.setdefault(str(self.path), {}).update(limits, day=_today())

    def reported(self) -> dict:
        seen = _reported.get(str(self.path), {})
        return seen if seen.get("day") == _today() else {}

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def record(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            data = self._read()
            day = data.setdefault(_today(), {"input": 0, "output": 0, "requests": 0})
            day["input"] += int(input_tokens)
            day["output"] += int(output_tokens)
            day["requests"] += 1
            oldest = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
            data = {d: v for d, v in data.items() if d >= oldest}
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
            temporary.replace(self.path)

    def today(self) -> dict:
        with self._lock:
            day = self._read().get(_today(), {"input": 0, "output": 0, "requests": 0})
        return {**day, "total": day["input"] + day["output"]}

    def history(self, days: int = 7) -> list[dict]:
        with self._lock:
            data = self._read()
        out = []
        for offset in range(days - 1, -1, -1):
            date = (datetime.now(timezone.utc) - timedelta(days=offset)).strftime("%Y-%m-%d")
            day = data.get(date, {"input": 0, "output": 0, "requests": 0})
            out.append({"date": date, "total": day["input"] + day["output"], "requests": day["requests"]})
        return out


def estimate_tokens(text: str) -> int:
    """A rough count for when the service does not report one: about four
    characters per token in English."""
    return (len(text) + 3) // 4


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
