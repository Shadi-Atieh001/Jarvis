"""Spotify playback control, through Spotify's own interface (not by
clicking in the app). Connect once with:  python -m jarvis connect spotify

Needs a Spotify Premium account (Student counts as Premium for playback).
Spotify must be open on some device for there to be something to control.
"""

from __future__ import annotations

from jarvis.core.tools import AUTO, ToolContext, ToolResult, tool
from jarvis.integrations import oauth
from jarvis.integrations.oauth import SPOTIFY, ApiError, NotConnected

API = "https://api.spotify.com/v1"
TYPES = ("track", "album", "artist", "playlist")


def _guard(func):
    def wrapper(args: dict, ctx: ToolContext):
        try:
            return func(args, ctx)
        except NotConnected as exc:
            return ToolResult(str(exc), is_error=True)
        except ApiError as exc:
            if exc.status == 403:
                return ToolResult(
                    "Spotify refused: playback control needs a Premium account, and the account must be the one "
                    f"that owns the JARVIS app on Spotify's developer site. ({exc})",
                    is_error=True,
                )
            if exc.status == 429:
                return ToolResult("Spotify is rate-limiting requests. Try again in a minute.", is_error=True)
            return ToolResult(str(exc), is_error=True)

    wrapper.__name__ = func.__name__
    wrapper.__module__ = func.__module__
    return wrapper


def _player(method: str, path: str, params: dict | None = None, body: dict | None = None):
    """A player request. If nothing is playing anywhere, Spotify answers
    "no active device"; in that case wake the first available device and
    try once more."""
    try:
        return oauth.call(SPOTIFY, method, f"{API}/me/player{path}", params, body)
    except ApiError as exc:
        if exc.status != 404:
            raise
    devices = (oauth.call(SPOTIFY, "GET", f"{API}/me/player/devices") or {}).get("devices", [])
    if not devices:
        raise ApiError(404, "Spotify is not open on any device. Open the Spotify app first (open_app can do that), then try again.")
    device = next((d for d in devices if d.get("is_active")), devices[0])
    return oauth.call(SPOTIFY, method, f"{API}/me/player{path}", {**(params or {}), "device_id": device["id"]}, body)


def _find(query: str, kind: str) -> dict | None:
    data = oauth.call(SPOTIFY, "GET", f"{API}/search", {"q": query, "type": kind, "limit": 5}) or {}
    items = [i for i in data.get(f"{kind}s", {}).get("items", []) if i]
    return items[0] if items else None


def _label(item: dict) -> str:
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    return f"{item.get('name')} by {artists}" if artists else str(item.get("name"))


@tool(
    name="spotify_play",
    description=(
        "Play music on Spotify. Give a search 'query' (a song, album, artist or playlist name) and its 'type'. "
        "With no query, resumes whatever was paused."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to play, e.g. 'Bohemian Rhapsody Queen'."},
            "type": {"type": "string", "enum": list(TYPES), "description": "Default: track."},
        },
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="launch",
    describe=lambda a, c: f"Play {a['query']} on Spotify" if a.get("query") else "Resume Spotify",
)
@_guard
def spotify_play(args: dict, ctx: ToolContext) -> ToolResult:
    if not args.get("query"):
        _player("PUT", "/play")
        return ToolResult("Resumed.")
    kind = args.get("type", "track")
    item = _find(args["query"], kind)
    if item is None:
        return ToolResult(f"Spotify found no {kind} matching {args['query']!r}.", is_error=True)
    body = {"uris": [item["uri"]]} if kind == "track" else {"context_uri": item["uri"]}
    _player("PUT", "/play", body=body)
    return ToolResult(f"Playing {kind}: {_label(item)}.")


@tool(
    name="spotify_queue",
    description="Add a song to the end of the Spotify queue, without interrupting what is playing.",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The song, e.g. 'Yesterday Beatles'."}},
        "required": ["query"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="launch",
    describe=lambda a, c: f"Queue {a['query']} on Spotify",
)
@_guard
def spotify_queue(args: dict, ctx: ToolContext) -> ToolResult:
    item = _find(args["query"], "track")
    if item is None:
        return ToolResult(f"Spotify found no song matching {args['query']!r}.", is_error=True)
    _player("POST", "/queue", {"uri": item["uri"]})
    return ToolResult(f"Queued: {_label(item)}.")


@tool(
    name="spotify_control",
    description="Control Spotify playback: pause, resume, next, previous, or set the volume (0-100).",
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["pause", "resume", "next", "previous", "volume"]},
            "volume": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Required for the volume action."},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="launch",
    describe=lambda a, c: f"Spotify: {a['action']}" + (f" {a['volume']}" if a.get("volume") is not None else ""),
)
@_guard
def spotify_control(args: dict, ctx: ToolContext) -> ToolResult:
    action = args["action"]
    if action == "pause":
        _player("PUT", "/pause")
    elif action == "resume":
        _player("PUT", "/play")
    elif action == "next":
        _player("POST", "/next")
    elif action == "previous":
        _player("POST", "/previous")
    else:
        if args.get("volume") is None:
            return ToolResult("Give a volume from 0 to 100.", is_error=True)
        _player("PUT", "/volume", {"volume_percent": args["volume"]})
        return ToolResult(f"Volume set to {args['volume']}.")
    return ToolResult({"pause": "Paused.", "resume": "Resumed.", "next": "Skipped to the next track.", "previous": "Back to the previous track."}[action])


@tool(
    name="spotify_now_playing",
    description="Say what is currently playing on Spotify.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: "Check what is playing on Spotify",
)
@_guard
def spotify_now_playing(args: dict, ctx: ToolContext) -> ToolResult:
    data = oauth.call(SPOTIFY, "GET", f"{API}/me/player/currently-playing")
    if not data or not data.get("item"):
        return ToolResult("Nothing is playing.")
    state = "Playing" if data.get("is_playing") else "Paused"
    return ToolResult(f"{state}: {_label(data['item'])}.")
