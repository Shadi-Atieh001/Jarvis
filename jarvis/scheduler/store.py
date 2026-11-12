"""The list of scheduled items, kept in <home>/schedule.json.

Each item is either
  a reminder  JARVIS says (and shows) a fixed message at the time, or
  a task      JARVIS carries out a request at the time, as if you had just
              asked it (the morning briefing is one of these).
and runs either once, at a date and time, or repeatedly, at a time of day on
chosen days of the week.

All times are this computer's local time. The file is plain JSON, so you can
read or edit it by hand while JARVIS is closed.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from jarvis.core.config import Settings

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# A one-off item missed because JARVIS was closed still runs if found within
# this long; a repeating one waits for its next turn unless it is this late or less.
LATE_ONCE = timedelta(hours=12)
LATE_REPEATING = timedelta(hours=3)

BRIEFING_TITLE = "Morning briefing"


def briefing_prompt(settings: Settings) -> str:
    return (
        f"Give me my morning briefing. Cover, in this order: today's weather in {settings.location} "
        "(use the weather tool); what is on my calendar today (calendar_events); and a short summary "
        "of my unread email from the last day (gmail_search with 'is:unread newer_than:1d'), naming who "
        "wrote and what they want, without reading every message in full. If a service is not connected, "
        "say so in one short sentence and carry on. Keep it brief enough to listen to in under a minute, "
        "in plain sentences with no lists or headings. Do not change, send or delete anything."
    )


def parse_time_of_day(value: str) -> tuple[int, int]:
    try:
        moment = datetime.strptime(value.strip(), "%H:%M")
    except ValueError:
        raise ValueError(f"{value!r} is not a time of day like 08:00 or 17:30.") from None
    return moment.hour, moment.minute


def next_run(item: dict, after: datetime) -> datetime | None:
    """When the item should next run, strictly after `after`. None if never."""
    if item.get("at"):
        at = datetime.fromisoformat(item["at"])
        return at if at > after else None
    hour, minute = parse_time_of_day(item["daily_at"])
    days = item.get("days") or list(DAYS)
    for offset in range(8):
        candidate = (after + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > after and DAYS[candidate.weekday()] in days:
            return candidate
    return None


def describe_when(item: dict) -> str:
    if item.get("at"):
        return datetime.fromisoformat(item["at"]).strftime("once, %a %d %b %Y at %H:%M")
    days = item.get("days") or list(DAYS)
    if len(days) == 7:
        which = "every day"
    elif days == list(DAYS[:5]):
        which = "weekdays"
    else:
        which = "every " + ", ".join(d.capitalize() for d in DAYS if d in days)
    return f"{which} at {item['daily_at']}"


class Schedule:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path: Path = settings.home / "schedule.json"
        self._lock = threading.RLock()
        self._data = self._load()
        if not self._data.get("briefing_created"):
            # Offered once. If you delete it, it stays deleted.
            self._data["briefing_created"] = True
            self.add(BRIEFING_TITLE, kind="task", text=briefing_prompt(settings), daily_at="08:00", now=datetime.now())

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"next_id": 1, "items": []}

    def _save(self) -> None:
        # Write to a temporary file first so a crash cannot leave half a file.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    # ------------------------------------------------------------- editing

    def add(self, title: str, kind: str, text: str, at: str | None = None, daily_at: str | None = None,
            days: list[str] | None = None, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        title, text = " ".join(title.split())[:120], text.strip()[:4000]
        if kind not in ("reminder", "task"):
            raise ValueError("kind must be 'reminder' or 'task'.")
        if not title or not text:
            raise ValueError("A scheduled item needs a title and something to say or do.")
        if bool(at) == bool(daily_at):
            raise ValueError("Give either 'at' (one date and time) or 'daily_at' (a time of day), not both.")
        item: dict = {"title": title, "kind": kind, "text": text, "enabled": True, "created": now.isoformat(timespec="seconds")}
        if at:
            try:
                moment = datetime.fromisoformat(at.strip()).replace(tzinfo=None)
            except ValueError:
                raise ValueError(f"{at!r} is not a date and time like 2026-11-13T18:00.") from None
            if moment <= now:
                raise ValueError(f"{moment:%d %b %Y %H:%M} is in the past.")
            item["at"] = moment.isoformat(timespec="minutes")
        else:
            hour, minute = parse_time_of_day(daily_at)
            item["daily_at"] = f"{hour:02d}:{minute:02d}"
            chosen = [d.strip().lower()[:3] for d in (days or [])]
            if any(d not in DAYS for d in chosen):
                raise ValueError("Days must be from: " + ", ".join(DAYS) + ".")
            if chosen and len(set(chosen)) < 7:
                item["days"] = [d for d in DAYS if d in chosen]
        item["next"] = next_run(item, now).isoformat(timespec="minutes")
        with self._lock:
            item["id"] = self._data["next_id"]
            self._data["next_id"] += 1
            self._data["items"].append(item)
            self._save()
        return item

    def remove(self, item_id: int) -> bool:
        with self._lock:
            before = len(self._data["items"])
            self._data["items"] = [i for i in self._data["items"] if i["id"] != item_id]
            self._save()
            return len(self._data["items"]) < before

    def items(self) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._data["items"]]

    def get(self, item_id: int) -> dict | None:
        return next((i for i in self.items() if i["id"] == item_id), None)

    # ------------------------------------------------------------- running

    def take_due(self, now: datetime | None = None) -> list[dict]:
        """Items whose time has come. Each is moved on to its next time (or
        removed, if it was a one-off) before being returned, so it cannot
        run twice."""
        now = now or datetime.now()
        due = []
        with self._lock:
            keep = []
            for item in self._data["items"]:
                when = datetime.fromisoformat(item["next"]) if item.get("next") else None
                if not item.get("enabled", True) or when is None or when > now:
                    keep.append(item)
                    continue
                late = now - when
                repeating = "daily_at" in item
                if late <= (LATE_REPEATING if repeating else LATE_ONCE):
                    due.append({**item, "late_minutes": int(late.total_seconds() // 60)})
                if repeating:
                    item["next"] = next_run(item, now).isoformat(timespec="minutes")
                    item["last"] = now.isoformat(timespec="minutes")
                    keep.append(item)
                # one-off items are dropped once their time has passed
            if len(keep) != len(self._data["items"]) or due:
                self._data["items"] = keep
                self._save()
        return due


def format_items(items: list[dict]) -> str:
    if not items:
        return "Nothing is scheduled."
    rows = []
    for i in sorted(items, key=lambda i: i.get("next") or ""):
        upcoming = datetime.fromisoformat(i["next"]).strftime("%a %d %b %H:%M") if i.get("next") else "-"
        rows.append(f"  #{i['id']:<3} {i['title']}  ({i['kind']}; {describe_when(i)}; next {upcoming})")
    return "\n".join(rows)
