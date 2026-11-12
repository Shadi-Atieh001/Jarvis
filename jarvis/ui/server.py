"""Local web server behind the desktop window.

The window (ui/web/index.html) talks to this server over one WebSocket.
The server only listens on 127.0.0.1, and two checks stop anything else on
your machine, such as a web page open in your browser, from driving JARVIS:
  * the WebSocket must present a random token that only our page is given
  * its Origin header must be this server

Messages (JSON), window -> server:
  {"type": "user", "text": "..."}            a chat message or /command
  {"type": "confirm_reply", "id": 1, "approved": true}
  {"type": "stop"}                           emergency stop
server -> window:
  {"type": "text", "delta": "..."}           part of the reply
  {"type": "tool", "name", "decision", "summary"}
  {"type": "confirm", "id", "tool", "reason", "description"}
  {"type": "info", "text": "..."}            command output and notices
  {"type": "done", "status": "..."}          the request finished
"""

from __future__ import annotations

import asyncio
import secrets
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response

from jarvis.core import commands
from jarvis.core.agent import Jarvis
from jarvis.core.permissions import Decision
from jarvis.voice.engine import Voice, VoiceUnavailable

MAX_AUDIO_BYTES = 20_000_000  # about ten minutes of speech
MAX_SPEAK_CHARS = 2000

WEB_DIR = Path(__file__).parent / "web"


class WebUI:
    """Bridges the agent (running on a worker thread) to one WebSocket."""

    def __init__(self, ws: WebSocket, loop: asyncio.AbstractEventLoop, jarvis: Jarvis):
        self.ws, self.loop, self.jarvis = ws, loop, jarvis
        self._next_id = 0
        self._pending: dict[int, tuple[threading.Event, list[bool]]] = {}

    def _send(self, message: dict) -> None:
        asyncio.run_coroutine_threadsafe(self.ws.send_json(message), self.loop)

    def on_text(self, delta: str) -> None:
        self._send({"type": "text", "delta": delta})

    def on_tool(self, name: str, decision: str, summary: str) -> None:
        self._send({"type": "tool", "name": name, "decision": decision, "summary": summary})

    def confirm(self, tool_name: str, decision: Decision) -> bool:
        self._next_id += 1
        request_id = self._next_id
        answered, answer = threading.Event(), [False]
        self._pending[request_id] = (answered, answer)
        self._send(
            {
                "type": "confirm",
                "id": request_id,
                "tool": tool_name,
                "reason": decision.reason,
                "description": decision.description,
            }
        )
        # Wait for the user, but give up at once on an emergency stop.
        while not answered.wait(timeout=0.1):
            if self.jarvis.kill.tripped:
                break
        self._pending.pop(request_id, None)
        return answer[0]

    def resolve(self, request_id: int, approved: bool) -> None:
        pending = self._pending.get(request_id)
        if pending:
            pending[1][0] = approved
            pending[0].set()

    def cancel_all(self) -> None:
        """Refuse everything still waiting (window closed)."""
        for answered, _ in list(self._pending.values()):
            answered.set()


def create_app(jarvis: Jarvis, token: str | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(24)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        return html.replace("__JARVIS_TOKEN__", token).replace("__ADDRESS__", jarvis.settings.address_as)

    voice = Voice(jarvis.settings)

    def authorise(request: Request) -> None:
        """Same two checks as the WebSocket: our token, and our own page."""
        origin = request.headers.get("origin")
        if request.headers.get("x-jarvis-token") != token:
            raise HTTPException(status_code=403)
        if origin is not None and urlparse(origin).netloc != request.headers.get("host", ""):
            raise HTTPException(status_code=403)

    @app.get("/api/info")
    def info(request: Request) -> dict:
        authorise(request)
        s = jarvis.settings
        model = {"anthropic": s.model, "ollama": s.ollama_model, "openai_compatible": s.compat_model}.get(s.provider, "")
        return {
            "address": s.address_as,
            "provider": s.provider,
            "model": model,
            "voice": voice.status(),
            "speak_replies": s.speak_replies,
            "wake_word": s.wake_word,
            "follow_up": s.follow_up,
            "permission_mode": s.permission_mode,
        }

    # ---- control panel: memory, activity, accounts, settings

    @app.get("/api/memories")
    def memories(request: Request) -> dict:
        authorise(request)
        if jarvis.memory is None:
            return {"enabled": False, "memories": [], "exchanges": 0}
        facts, exchanges = jarvis.memory.counts()
        return {"enabled": True, "memories": jarvis.memory.all(), "exchanges": exchanges}

    @app.delete("/api/memories/{memory_id}")
    def forget_memory(memory_id: int, request: Request) -> dict:
        authorise(request)
        if jarvis.memory is None or not jarvis.memory.forget(memory_id):
            raise HTTPException(status_code=404)
        jarvis.log.record("memory", detail=f"memory #{memory_id} deleted from the control panel")
        return {"ok": True}

    @app.delete("/api/memories")
    def forget_all(request: Request) -> dict:
        authorise(request)
        if jarvis.memory is None:
            raise HTTPException(status_code=404)
        count = jarvis.memory.forget_everything()
        jarvis.log.record("memory", detail=f"all memory deleted from the control panel ({count} memories)")
        return {"ok": True}

    @app.get("/api/log")
    def activity(request: Request, n: int = 100) -> dict:
        authorise(request)
        return {"entries": jarvis.log.tail(max(1, min(n, 500)))}

    @app.get("/api/connections")
    def connections(request: Request) -> dict:
        authorise(request)
        from jarvis.integrations import oauth

        result = []
        for provider in oauth.PROVIDERS.values():
            try:
                connected = oauth.is_connected(provider)
            except Exception:
                connected = False
            result.append({"key": provider.key, "label": provider.label, "connected": connected})
        return {"connections": result}

    @app.post("/api/connections/{key}/disconnect")
    def disconnect(key: str, request: Request) -> dict:
        authorise(request)
        from jarvis.integrations import oauth

        provider = oauth.PROVIDERS.get(key)
        if provider is None:
            raise HTTPException(status_code=404)
        oauth.disconnect(provider)
        jarvis.log.record("connection", detail=f"{provider.label} disconnected from the control panel")
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings(request: Request) -> dict:
        authorise(request)
        from jarvis.core.config import ADJUSTABLE

        return {key: getattr(jarvis.settings, key) for key in ADJUSTABLE}

    @app.post("/api/settings")
    async def change_setting(request: Request) -> dict:
        authorise(request)
        from jarvis.core.config import save_override

        data = await request.json()
        try:
            save_override(jarvis.settings, str(data.get("key")), data.get("value"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        jarvis.log.record("setting", detail=f"{data.get('key')} set to {data.get('value')!r} from the control panel")
        return {"ok": True}

    @app.post("/api/transcribe")
    async def transcribe(request: Request) -> dict:
        authorise(request)
        audio = await request.body()
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=400, detail="No audio, or too much of it.")
        try:
            text = await run_in_threadpool(voice.transcribe, audio)
        except VoiceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return {"text": text}

    @app.post("/api/speak")
    async def speak(request: Request) -> Response:
        authorise(request)
        text = str((await request.json()).get("text", ""))[:MAX_SPEAK_CHARS]
        try:
            wav = await run_in_threadpool(voice.speak, text)
        except VoiceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return Response(content=wav, media_type="audio/wav")

    @app.websocket("/ws/wake")
    async def wake_endpoint(ws: WebSocket) -> None:
        """The window streams microphone audio here while it waits for
        "Hey Jarvis". Audio is checked and dropped; only detections go back."""
        origin = urlparse(ws.headers.get("origin", ""))
        if ws.query_params.get("token") != token or origin.netloc != ws.headers.get("host", ""):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            from jarvis.voice.wake import WakeListener

            listener = await run_in_threadpool(WakeListener, jarvis.settings)
        except Exception as exc:
            await ws.send_json({"type": "unavailable", "detail": str(exc)})
            await ws.close()
            return
        await ws.send_json({"type": "ready"})
        try:
            while True:
                pcm = await ws.receive_bytes()
                if len(pcm) > 200_000:  # far more than one audio chunk
                    continue
                if await run_in_threadpool(listener.feed, pcm) and not jarvis.kill.tripped:
                    jarvis.log.record("wake_word", detail="Hey Jarvis heard")
                    await ws.send_json({"type": "wake"})
        except WebSocketDisconnect:
            pass

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        origin = urlparse(ws.headers.get("origin", ""))
        host = ws.headers.get("host", "")
        if ws.query_params.get("token") != token or origin.netloc != host:
            await ws.close(code=1008)
            return
        await ws.accept()

        loop = asyncio.get_running_loop()
        ui = WebUI(ws, loop, jarvis)
        busy = threading.Lock()
        jarvis.log.record("session_start", detail="window")
        if jarvis.kill.tripped:
            await ws.send_json({"type": "info", "text": "The emergency stop is engaged. Type /resume to clear it."})

        def work(text: str) -> None:
            try:
                status = jarvis.send(text, ui)
            except Exception as exc:
                jarvis.log.record("error", detail=f"{type(exc).__name__}: {exc}")
                ui._send({"type": "info", "text": f"Something went wrong: {type(exc).__name__}: {exc}"})
                status = "error"
            finally:
                busy.release()
            ui._send({"type": "done", "status": status})

        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")

                if kind == "stop":
                    jarvis.kill.trip()
                    jarvis.log.record("kill_switch", detail="tripped by Stop button")
                    await ws.send_json({"type": "info", "text": "Emergency stop engaged. Type /resume to clear it."})

                elif kind == "confirm_reply":
                    ui.resolve(int(msg.get("id", 0)), msg.get("approved") is True)

                elif kind == "user":
                    text = str(msg.get("text", "")).strip()
                    if not text:
                        continue
                    reply = commands.handle(text, jarvis)
                    if reply == commands.QUIT:
                        reply = "Close the window to exit."
                    if reply is not None:
                        await ws.send_json({"type": "info", "text": reply})
                        continue
                    if jarvis.kill.tripped:
                        await ws.send_json({"type": "info", "text": "The emergency stop is engaged. Type /resume to clear it."})
                        await ws.send_json({"type": "done", "status": "stopped"})
                        continue
                    if not busy.acquire(blocking=False):
                        await ws.send_json({"type": "info", "text": "One moment: still working on the previous request."})
                        continue
                    threading.Thread(target=work, args=(text,), daemon=True).start()
        except WebSocketDisconnect:
            ui.cancel_all()

    return app


def serve(jarvis: Jarvis, port: int = 0) -> tuple[threading.Thread, str]:
    """Start the server on a background thread. Returns (thread, url)."""
    import socket

    import uvicorn

    if port == 0:  # ask the OS for a free port
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    app = create_app(jarvis)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread, f"http://127.0.0.1:{port}/"
