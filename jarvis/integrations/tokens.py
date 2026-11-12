"""Accounts that are connected with a personal access token rather than a
browser sign-in: GitHub and Notion. You create the token on the service's
website and paste it once into `python -m jarvis connect github` (or
notion); it is stored in the OS keychain.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field

from jarvis.core import secrets
from jarvis.integrations import oauth
from jarvis.integrations.oauth import ApiError, NotConnected


@dataclass(frozen=True)
class TokenAccount:
    key: str
    label: str
    headers: dict = field(default_factory=dict)  # sent with every request


GITHUB = TokenAccount(
    "github", "GitHub",
    {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "jarvis-assistant"},
)
NOTION = TokenAccount("notion", "Notion", {"Notion-Version": "2022-06-28"})


def is_connected(account: TokenAccount) -> bool:
    return bool(secrets.get(f"{account.key}.token"))


def connect(account: TokenAccount, token: str) -> None:
    secrets.put(f"{account.key}.token", token.strip())


def disconnect(account: TokenAccount) -> None:
    secrets.delete(f"{account.key}.token")


def call(account: TokenAccount, method: str, url: str, params: dict | None = None, body: dict | None = None):
    """An authorised request; returns the decoded JSON reply (or None)."""
    token = secrets.get(f"{account.key}.token")
    if not token:
        raise NotConnected(account)
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    headers = {"Authorization": f"Bearer {token}", **account.headers}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    status, raw = oauth._http(method, url, headers, data)
    if 200 <= status < 300:
        try:
            return json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            return None
    try:
        message = json.loads(raw).get("message")
    except (json.JSONDecodeError, AttributeError):
        message = raw.decode("utf-8", errors="replace")[:200]
    if status == 401:
        raise NotConnected(account, f"{account.label} rejected the stored token (it may have expired or been revoked).")
    hint = ""
    if status in (403, 404):
        hint = " The token may not have permission for this, or the item may not be shared with it."
    raise ApiError(status, f"{account.label} refused the request ({status}): {message or 'no details given'}.{hint}")
