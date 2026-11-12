"""python -m jarvis connect|disconnect|connections"""

from __future__ import annotations

import getpass

from jarvis.core import secrets
from jarvis.integrations import oauth
from jarvis.integrations.oauth import GOOGLE, PROVIDERS, SPOTIFY, ApiError, NotConnected

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
}


def _whoami(provider) -> str:
    if provider is GOOGLE:
        profile = oauth.call(GOOGLE, "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")
        return profile.get("emailAddress", "your Google account")
    # Spotify no longer reports account details to personal apps, so check a player call instead.
    oauth.call(SPOTIFY, "GET", "https://api.spotify.com/v1/me/player/devices")
    return "your Spotify account"


def run(command: str, args: list[str], ask=input, ask_secret=getpass.getpass, out=print) -> int:
    try:
        if command == "connections":
            for provider in PROVIDERS.values():
                out(f"  {provider.label:<8} {'connected' if oauth.is_connected(provider) else 'not connected'}")
            return 0

        provider = PROVIDERS.get(args[0].lower()) if args else None
        if provider is None:
            out(f"Usage: python -m jarvis {command} {'|'.join(PROVIDERS)}")
            return 2

        if command == "disconnect":
            oauth.disconnect(provider)
            out(f"{provider.label} disconnected; its tokens have been deleted from the keychain.")
            return 0

        out(HELP[provider.key])
        client_id = ask("Client ID: ").strip()
        client_secret = ask_secret("Client secret (typing is hidden): ").strip() if provider.needs_secret else None
        if not client_id or (provider.needs_secret and not client_secret):
            out("Nothing entered; cancelled.")
            return 1
        out(f"Opening {provider.label}'s sign-in page in your browser. Approve the request there ...")
        oauth.connect(provider, client_id, client_secret)
        out(f"Connected to {provider.label} as {_whoami(provider)}. Restart JARVIS if it is running.")
        return 0
    except secrets.SecretsUnavailable as exc:
        out(str(exc))
    except (ApiError, NotConnected) as exc:
        out(f"That did not work: {exc}")
    return 1
