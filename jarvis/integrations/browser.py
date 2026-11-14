"""The link between JARVIS and its browser extension.

The extension (the extension/ folder, loaded into Chrome or Edge) opens a
connection to JARVIS on this computer and waits for commands. This module is
JARVIS's end of that connection: tools call BrowserBridge.call("read", ...)
and get the extension's answer back.

Pairing: the extension must present a code that only this computer's JARVIS
knows. The code is made once and kept in <home>/browser_pairing. You copy it
from CONTROL > Accounts > Browser into the extension's popup, once.
"""

from __future__ import annotations

import asyncio
import re
import secrets as random_secrets
import threading
from urllib.parse import urlsplit

from jarvis.core.config import Settings


class BrowserError(Exception):
    pass


class BrowserBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._next_id = 0
        self._pending: dict[int, tuple[threading.Event, list]] = {}
        self._lock = threading.Lock()
        # What JARVIS last saw in each tab: {"url", "title", "elements": {ref: item}}.
        # The permission rules use this to know which site a click is on.
        self.pages: dict[int, dict] = {}
        self.working_tab: int | None = None  # the tab JARVIS last opened or read

    # ------------------------------------------------------------- pairing

    @property
    def code(self) -> str:
        path = self.settings.home / "browser_pairing"
        try:
            code = path.read_text(encoding="utf-8").strip()
            if len(code) >= 20:
                return code
        except OSError:
            pass
        code = random_secrets.token_urlsafe(24)
        path.write_text(code, encoding="utf-8")
        return code

    def new_code(self) -> str:
        """Make a fresh code; the extension must be paired again."""
        (self.settings.home / "browser_pairing").unlink(missing_ok=True)
        return self.code

    # ---------------------------------------------------------- connection

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def attach(self, ws, loop: asyncio.AbstractEventLoop) -> None:
        self._ws, self._loop = ws, loop
        self.pages.clear()

    def detach(self, ws) -> None:
        if self._ws is ws:
            self._ws = None
            for done, _ in list(self._pending.values()):
                done.set()  # wake anything waiting; it will see no answer

    def on_message(self, message: dict) -> None:
        pending = self._pending.get(message.get("id"))
        if pending:
            pending[1].append(message)
            pending[0].set()

    def call(self, action: str, args: dict | None = None, timeout: float = 40):
        """Ask the extension to do something; returns its result."""
        if not self.connected:
            raise BrowserError(
                "The JARVIS browser extension is not connected. The user needs Chrome or Edge open with the "
                "extension installed and paired (CONTROL > Accounts > Browser shows how)."
            )
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        done, answer = threading.Event(), []
        self._pending[request_id] = (done, answer)
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send_json({"id": request_id, "action": action, "args": args or {}}), self._loop
            )
            if not done.wait(timeout) or not answer:
                raise BrowserError("The browser did not answer in time." if self.connected else "The browser extension disconnected.")
        finally:
            self._pending.pop(request_id, None)
        reply = answer[0]
        if not reply.get("ok"):
            raise BrowserError(str(reply.get("error") or "The browser could not do that."))
        return reply.get("result")

    # ------------------------------------------------------- what was seen

    def remember(self, tab: dict, elements: list[dict] | None = None) -> None:
        page = self.pages.setdefault(tab["id"], {"elements": {}})
        if elements is not None or page.get("url") != tab.get("url"):
            # A different page: the old element numbers no longer mean anything.
            page["elements"] = {e["ref"]: e for e in (elements or [])}
        page.update(url=tab.get("url", ""), title=tab.get("title", ""))
        self.working_tab = tab["id"]

    def page(self, tab_id: int | None) -> dict | None:
        return self.pages.get(tab_id if tab_id is not None else self.working_tab)


# ------------------------------------------------------------ site rules


def site_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_approved(settings: Settings, url: str) -> bool:
    host = site_of(url)
    return bool(host) and any(host == site or host.endswith("." + site) for site in settings.approved_sites)


def always_asks(settings: Settings, url: str) -> bool:
    """Banking, payment and similar sites: JARVIS asks every time."""
    for pattern in settings.always_ask_sites:
        try:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False
