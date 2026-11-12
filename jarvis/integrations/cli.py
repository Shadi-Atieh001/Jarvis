"""python -m jarvis connect|disconnect|connections"""

from __future__ import annotations

import getpass

from jarvis.core import secrets
from jarvis.integrations import oauth, tokens
from jarvis.integrations.accounts import ACCOUNTS, disconnect, is_connected
from jarvis.integrations.oauth import GOOGLE, SPOTIFY, ApiError, NotConnected
from jarvis.integrations.tokens import GITHUB, NOTION

HELP = {
    "google": (
        "You need a Google \"OAuth client\" of type \"Desktop app\" (see the README, 'Connecting Google').\n"
        "Have its Client ID and Client secret ready."
    ),
    "spotify": (
        "You need a Spotify developer app (see the README, 'Connecting Spotify') whose Redirect URI is exactly:\n"
        f"  {oauth.REDIRECT_URI}\n"
        "Have its Client ID ready."
    ),
    "github": "You need a GitHub personal access token (see the README, 'Connecting GitHub').",
    "notion": "You need a Notion internal integration secret (see the README, 'Connecting Notion').",
}


def _whoami(account) -> str:
    if account is GOOGLE:
        profile = oauth.call(GOOGLE, "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")
        return profile.get("emailAddress", "your Google account")
    if account is SPOTIFY:
        # Spotify no longer reports account details to personal apps, so check a player call instead.
        oauth.call(SPOTIFY, "GET", "https://api.spotify.com/v1/me/player/devices")
        return "your Spotify account"
    if account is GITHUB:
        return tokens.call(GITHUB, "GET", "https://api.github.com/user").get("login", "your GitHub account")
    bot = tokens.call(NOTION, "GET", "https://api.notion.com/v1/users/me")
    return f"the integration '{bot.get('name') or 'unnamed'}'"


def run(command: str, args: list[str], ask=input, ask_secret=getpass.getpass, out=print) -> int:
    try:
        if command == "connections":
            for account in ACCOUNTS.values():
                out(f"  {account.label:<8} {'connected' if is_connected(account) else 'not connected'}")
            return 0

        account = ACCOUNTS.get(args[0].lower()) if args else None
        if account is None:
            out(f"Usage: python -m jarvis {command} {'|'.join(ACCOUNTS)}")
            return 2

        if command == "disconnect":
            disconnect(account)
            out(f"{account.label} disconnected; its tokens have been deleted from the keychain.")
            return 0

        out(HELP[account.key])
        if isinstance(account, tokens.TokenAccount):
            token = ask_secret("Token (typing is hidden; paste and press Enter): ").strip()
            if not token:
                out("Nothing entered; cancelled.")
                return 1
            tokens.connect(account, token)
            try:
                who = _whoami(account)
            except (ApiError, NotConnected):
                tokens.disconnect(account)  # do not keep a token that does not work
                raise
            out(f"Connected to {account.label} as {who}. Restart JARVIS if it is running.")
            return 0

        client_id = ask("Client ID: ").strip()
        client_secret = ask_secret("Client secret (typing is hidden): ").strip() if account.needs_secret else None
        if not client_id or (account.needs_secret and not client_secret):
            out("Nothing entered; cancelled.")
            return 1
        out(f"Opening {account.label}'s sign-in page in your browser. Approve the request there ...")
        oauth.connect(account, client_id, client_secret)
        out(f"Connected to {account.label} as {_whoami(account)}. Restart JARVIS if it is running.")
        return 0
    except secrets.SecretsUnavailable as exc:
        out(str(exc))
    except (ApiError, NotConnected) as exc:
        out(f"That did not work: {exc}")
    return 1
