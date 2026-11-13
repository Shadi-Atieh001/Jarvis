"""The current conversation, kept on disk so it survives a restart.

Two different things are remembered about a conversation:

  what was SAID   every message, reply and tool line, as shown in the
                  window. This is what this module stores, in
                  <home>/conversation.json, and what the window redraws
                  when JARVIS starts.

  what the MODEL  the exact request history sent to the model, including
  was SENT        tool results and its private reasoning. This is NOT
                  stored: it is large, tied to one model, and costs tokens
                  to resend. Instead, after a restart, or when a
                  conversation has grown too long, the model is given a
                  short written recap of what was said so far and carries
                  on from there.

So the conversation looks continuous to you, while the model works from a
recap rather than the full back-and-forth. Details it has lost (the contents
of a file it read an hour ago, say) it can simply fetch again. Everything
ever said also remains searchable through memory (the recall tool).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

MAX_ITEMS = 400  # display items kept; older ones fall off the top
RECENT_EXCHANGES = 6  # given to the model nearly in full
OLDER_EXCHANGES = 30  # given to the model as one line each
RECENT_CHARS = 1500
OLDER_CHARS = 280


class Conversation:
    """Display items are small dicts:
      {"type": "user", "text", "spoken"}
      {"type": "reply", "text"}
      {"type": "tool", "name", "decision", "summary"}
      {"type": "scheduled", "title", "text"}
      {"type": "notice", "text"}
    """

    def __init__(self, path: Path | None):
        self.path = path  # None: keep in memory only (tests, scheduled runs)
        self._lock = threading.Lock()
        self.items: list[dict] = []
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.items = [i for i in data if isinstance(i, dict) and "type" in i][-MAX_ITEMS:]
            except (OSError, ValueError):
                pass

    def add(self, item: dict) -> None:
        with self._lock:
            # Consecutive pieces of one reply are stored as one item.
            if item["type"] == "reply" and self.items and self.items[-1]["type"] == "reply" and not self.items[-1].get("closed"):
                self.items[-1]["text"] += item["text"]
            else:
                if self.items and self.items[-1]["type"] == "reply":
                    self.items[-1]["closed"] = True
                self.items.append({**item, "time": datetime.now().isoformat(timespec="seconds")})
            del self.items[:-MAX_ITEMS]

    def save(self) -> None:
        if self.path is None:
            return
        with self._lock:
            if self.items and self.items[-1]["type"] == "reply":
                self.items[-1]["closed"] = True
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)

    def clear(self) -> None:
        with self._lock:
            self.items = []
        self.save()

    def view(self) -> list[dict]:
        """What the window needs to redraw the conversation."""
        with self._lock:
            return [{k: v for k, v in i.items() if k != "closed"} for i in self.items if i.get("text") or i["type"] == "tool"]

    # ---------------------------------------------------------------- recap

    def exchanges(self) -> list[tuple[str, str]]:
        """(what the user said, what JARVIS replied) pairs, oldest first."""
        pairs: list[list[str]] = []
        with self._lock:
            for item in self.items:
                if item["type"] == "user":
                    pairs.append([item["text"], ""])
                elif item["type"] == "reply" and pairs:
                    pairs[-1][1] = (pairs[-1][1] + "\n" + item["text"]).strip()
                elif item["type"] == "scheduled":
                    pairs.append([f"(scheduled: {item.get('title', '')})", item["text"]])
        return [(u, r) for u, r in pairs if u.strip()]

    def recap(self) -> str:
        """A written summary of the conversation so far, for the model."""
        pairs = self.exchanges()
        if not pairs:
            return ""
        recent, older = pairs[-RECENT_EXCHANGES:], pairs[:-RECENT_EXCHANGES][-OLDER_EXCHANGES:]

        def cut(text: str, limit: int) -> str:
            text = " ".join(text.split())
            return text if len(text) <= limit else text[:limit] + " ..."

        lines = []
        if older:
            lines.append("Earlier, briefly:")
            lines += [f"- User: {cut(u, OLDER_CHARS)} | You: {cut(r, OLDER_CHARS) or '(no reply)'}" for u, r in older]
            lines.append("")
            lines.append("Most recently:")
        for u, r in recent:
            lines.append(f"User: {cut(u, RECENT_CHARS)}")
            lines.append(f"You: {cut(r, RECENT_CHARS) or '(no reply)'}")
        return "\n".join(lines)
