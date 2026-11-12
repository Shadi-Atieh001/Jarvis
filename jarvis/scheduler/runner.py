"""Runs scheduled items when their time comes.

A background thread checks the schedule every 20 seconds while JARVIS is
running (in the window or in the tray). Nothing runs while JARVIS is closed;
items missed by a few hours run when it next starts.

A scheduled task runs in its own fresh conversation, with the same tools and
the same permission rules as a request you type. If it needs your approval
and you do not answer within two minutes, the answer is no.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

from jarvis.core.agent import Jarvis
from jarvis.core.permissions import Decision
from jarvis.scheduler.store import Schedule

CHECK_EVERY = 20  # seconds
APPROVAL_WAIT = 120  # seconds


class _Collector:
    """The 'interface' for an unattended run: gathers the reply text and
    passes approval requests to whoever is listening, with a time limit."""

    def __init__(self, ask: Callable[[str, Decision], bool] | None):
        self.text = ""
        self._ask = ask

    def on_text(self, delta: str) -> None:
        self.text += delta

    def on_tool(self, name: str, decision: str, summary: str) -> None:
        pass  # it is all in the action log

    def confirm(self, tool_name: str, decision: Decision) -> bool:
        if self._ask is None:
            return False  # nobody is there to ask
        answer: list[bool] = []
        worker = threading.Thread(target=lambda: answer.append(self._ask(tool_name, decision)), daemon=True)
        worker.start()
        worker.join(APPROVAL_WAIT)
        return bool(answer and answer[0])


class Scheduler:
    def __init__(self, jarvis: Jarvis, deliver: Callable[[dict, str], None],
                 ask: Callable[[str, Decision], bool] | None = None, make_agent: Callable[[], Jarvis] | None = None):
        """deliver(item, text) shows and speaks a result; ask() requests approval."""
        self.jarvis = jarvis
        self.schedule = Schedule(jarvis.settings)
        self.deliver = deliver
        self.ask = ask
        # Each task gets its own conversation, so it neither sees nor
        # disturbs what you are in the middle of.
        self.make_agent = make_agent or (lambda: Jarvis(jarvis.settings, jarvis.registry, jarvis.log, jarvis.kill))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = threading.Lock()  # one scheduled item at a time

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # the scheduler must outlive any one failure
                self.jarvis.log.record("error", detail=f"scheduler: {type(exc).__name__}: {exc}")
            self._stop.wait(CHECK_EVERY)

    def tick(self, now: datetime | None = None) -> int:
        """Run everything that is due. Returns how many items ran."""
        if self.jarvis.kill.tripped:
            return 0  # emergency stop: nothing runs, and nothing is skipped either
        due = self.schedule.take_due(now)
        for item in due:
            self.run(item)
        return len(due)

    def run(self, item: dict) -> str:
        """Carry out one item now and deliver the result."""
        with self._running:
            late = item.get("late_minutes", 0)
            self.jarvis.log.record("scheduled", detail=f"#{item['id']} {item['title']} ({item['kind']})" + (f", {late} min late" if late > 5 else ""))
            if item["kind"] == "reminder":
                text = f"A reminder, {self.jarvis.settings.address_as}: {item['text']}"
                if late > 5:
                    text += f" (This was due {late} minutes ago, while I was not running.)"
            else:
                collector = _Collector(self.ask)
                try:
                    status = self.make_agent().send(item["text"], collector)
                    text = collector.text.strip() or f"The task finished ({status}) but produced nothing to say."
                except Exception as exc:
                    self.jarvis.log.record("error", detail=f"scheduled task #{item['id']}: {type(exc).__name__}: {exc}")
                    text = f"I could not complete the scheduled task '{item['title']}': {exc}"
            try:
                self.deliver(item, text)
            except Exception as exc:
                self.jarvis.log.record("error", detail=f"could not deliver scheduled result: {exc}")
            return text
