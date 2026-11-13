"""One list of every account JARVIS can connect to, whichever way it signs in."""

from __future__ import annotations

from jarvis.integrations import oauth, tokens

GEMINI = tokens.TokenAccount("gemini", "Gemini")  # JARVIS's eyes; see tools/sight.py
ACCOUNTS = {a.key: a for a in (oauth.GOOGLE, oauth.SPOTIFY, tokens.GITHUB, tokens.NOTION, GEMINI)}


def is_connected(account) -> bool:
    module = tokens if isinstance(account, tokens.TokenAccount) else oauth
    return module.is_connected(account)


def disconnect(account) -> None:
    module = tokens if isinstance(account, tokens.TokenAccount) else oauth
    module.disconnect(account)
