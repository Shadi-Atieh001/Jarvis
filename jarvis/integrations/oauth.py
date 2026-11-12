"""Signing in to online accounts with OAuth, the standard "Allow this app?"
flow, and making authorised requests afterwards.

How connecting works (python -m jarvis connect google):
  1. JARVIS opens the provider's sign-in page in your browser.
  2. You approve. The provider sends your browser back to a tiny web server
     JARVIS runs for a moment on this computer (127.0.0.1:8899).
  3. JARVIS swaps the one-time code it receives for a "refresh token" and
     stores it in the OS keychain. Your password never reaches JARVIS.
Afterwards JARVIS uses the refresh token to get short-lived access tokens
as needed. Disconnecting deletes everything from the keychain.

Only the standard library is used for the web requests.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets as random_secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer

from jarvis.core import secrets

REDIRECT_PORT = 8899
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"


@dataclass(frozen=True)
class Provider:
    key: str  # used in keychain entry names and on the command line
    label: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    needs_secret: bool  # whether a client secret is required as well as an ID
    extra_auth: dict = field(default_factory=dict)


GOOGLE = Provider(
    key="google",
    label="Google",
    auth_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=(
        "https://www.googleapis.com/auth/gmail.readonly",  # read and search mail
        "https://www.googleapis.com/auth/gmail.send",      # send mail
        "https://www.googleapis.com/auth/gmail.compose",   # create drafts
        "https://www.googleapis.com/auth/calendar.events", # read and change events
    ),
    needs_secret=True,
    # "offline" asks for a refresh token; "consent" makes Google issue one
    # even if you have approved before.
    extra_auth={"access_type": "offline", "prompt": "consent"},
)

SPOTIFY = Provider(
    key="spotify",
    label="Spotify",
    auth_url="https://accounts.spotify.com/authorize",
    token_url="https://accounts.spotify.com/api/token",
    scopes=("user-modify-playback-state", "user-read-playback-state", "user-read-currently-playing"),
    needs_secret=False,
)

PROVIDERS = {p.key: p for p in (GOOGLE, SPOTIFY)}


class NotConnected(Exception):
    def __init__(self, provider: Provider, detail: str = ""):
        self.provider = provider
        message = f"{provider.label} is not connected. In a terminal, run:  python -m jarvis connect {provider.key}"
        super().__init__(f"{detail} {message}".strip())


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


# In-memory cache of access tokens: provider key -> (token, expires_at).
_access: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _http(method: str, url: str, headers: dict | None = None, data: bytes | None = None) -> tuple[int, bytes]:
    """One web request. Returns (status, body) for any HTTP status.
    Kept separate so tests can replace it."""
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(0, f"Could not reach {urllib.parse.urlsplit(url).hostname}: {getattr(exc, 'reason', exc)}") from None


def _token_request(provider: Provider, fields: dict) -> dict:
    status, body = _http(
        "POST",
        provider.token_url,
        {"Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode(fields).encode(),
    )
    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        data = {}
    if status != 200:
        raise ApiError(status, str(data.get("error_description") or data.get("error") or f"sign-in failed ({status})"))
    return data


# ------------------------------------------------------------ connecting


def is_connected(provider: Provider) -> bool:
    return bool(secrets.get(f"{provider.key}.refresh_token"))


def disconnect(provider: Provider) -> None:
    for item in ("refresh_token", "client_id", "client_secret"):
        secrets.delete(f"{provider.key}.{item}")
    _access.pop(provider.key, None)


def connect(provider: Provider, client_id: str, client_secret: str | None = None, open_browser=webbrowser.open, timeout: float = 300) -> None:
    """Run the browser sign-in and store the result in the keychain."""
    verifier = random_secrets.token_urlsafe(64)  # PKCE: proves the code exchange comes from us
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = random_secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if not self.path.startswith("/callback"):
                self.send_response(404)
                self.end_headers()
                return
            if query.get("state", [""])[0] != state:
                result["error"] = "The reply did not match this sign-in attempt."
            elif "error" in query:
                result["error"] = query["error"][0]
            else:
                result["code"] = query.get("code", [""])[0]
            page = "You can close this tab and return to JARVIS." if "code" in result else f"Sign-in failed: {result.get('error')}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body style='font-family:sans-serif;margin:3em'><h2>JARVIS</h2><p>{page}</p></body></html>".encode())

    try:
        server = HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    except OSError:
        raise ApiError(0, f"Port {REDIRECT_PORT} is in use by another program. Close it (or another sign-in window) and try again.") from None
    server.timeout = 1
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(provider.scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **provider.extra_auth,
    }
    url = f"{provider.auth_url}?{urllib.parse.urlencode(params)}"
    try:
        open_browser(url)
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in result:
        raise ApiError(0, result.get("error") or "No reply arrived from the browser in time.")

    fields = {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if provider.needs_secret:
        fields["client_secret"] = client_secret or ""
    tokens = _token_request(provider, fields)
    if not tokens.get("refresh_token"):
        raise ApiError(0, f"{provider.label} did not issue a long-lived token. Remove JARVIS's access in your {provider.label} account settings and connect again.")

    secrets.put(f"{provider.key}.client_id", client_id)
    if provider.needs_secret:
        secrets.put(f"{provider.key}.client_secret", client_secret or "")
    secrets.put(f"{provider.key}.refresh_token", tokens["refresh_token"])
    with _lock:
        _access[provider.key] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)) - 60)


# -------------------------------------------------------------- requests


def access_token(provider: Provider, force_refresh: bool = False) -> str:
    with _lock:
        cached = _access.get(provider.key)
        if cached and not force_refresh and cached[1] > time.time():
            return cached[0]
        refresh = secrets.get(f"{provider.key}.refresh_token")
        client_id = secrets.get(f"{provider.key}.client_id")
        if not refresh or not client_id:
            raise NotConnected(provider)
        fields = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id}
        if provider.needs_secret:
            fields["client_secret"] = secrets.get(f"{provider.key}.client_secret") or ""
        try:
            tokens = _token_request(provider, fields)
        except ApiError as exc:
            if exc.status in (400, 401):  # the refresh token has expired or been revoked
                raise NotConnected(provider, f"The {provider.label} sign-in has expired.") from None
            raise
        if tokens.get("refresh_token"):  # some providers rotate it
            secrets.put(f"{provider.key}.refresh_token", tokens["refresh_token"])
        _access[provider.key] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)) - 60)
        return tokens["access_token"]


def call(provider: Provider, method: str, url: str, params: dict | None = None, body: dict | None = None):
    """An authorised request. Returns the decoded JSON reply (or None when
    the reply is empty). Raises ApiError with a readable message otherwise."""
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
    data = json.dumps(body).encode() if body is not None else (b"" if method in ("POST", "PUT") else None)
    for attempt in (1, 2):
        headers = {"Authorization": f"Bearer {access_token(provider, force_refresh=attempt == 2)}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, raw = _http(method, url, headers, data)
        if status != 401 or attempt == 2:
            break
    if 200 <= status < 300:
        try:
            return json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            return None
    try:
        error = json.loads(raw).get("error", {})
        message = error.get("message") if isinstance(error, dict) else str(error)
        reason = error.get("reason") if isinstance(error, dict) else None
    except (json.JSONDecodeError, AttributeError):
        message, reason = raw.decode("utf-8", errors="replace")[:200], None
    exc = ApiError(status, f"{provider.label} refused the request ({status}): {message or 'no details given'}")
    exc.reason = reason
    raise exc
