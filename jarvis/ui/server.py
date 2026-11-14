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
from jarvis.integrations.browser import BrowserBridge
from jarvis.scheduler.runner import Scheduler
from jarvis.scheduler.store import describe_when
from jarvis.voice.engine import Voice, VoiceUnavailable

PREFERRED_PORT = 47821
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

    def on_notice(self, text: str) -> None:
        self._send({"type": "notice", "text": text})

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
                "offer_site": decision.offer_site,
            }
        )
        # Wait for the user, but give up at once on an emergency stop.
        while not answered.wait(timeout=0.1):
            if self.jarvis.kill.tripped:
                break
        self._pending.pop(request_id, None)
        if answer[0] and len(answer) > 1 and decision.offer_site:
            # "Yes, and always on this site."
            from jarvis.core.config import set_site_approval

            try:
                set_site_approval(self.jarvis.settings, decision.offer_site, True)
                self.jarvis.log.record("site", detail=f"{decision.offer_site} approved from a permission prompt")
            except ValueError:
                pass
        return answer[0]

    def resolve(self, request_id: int, approved: bool, approve_site: bool = False) -> None:
        pending = self._pending.get(request_id)
        if pending:
            pending[1][0] = approved
            if approved and approve_site:
                pending[1].append("site")
            pending[0].set()

    def cancel_all(self) -> None:
        """Refuse everything still waiting (window closed)."""
        for answered, _ in list(self._pending.values()):
            answered.set()


def create_app(jarvis: Jarvis, token: str | None = None, make_agent=None) -> FastAPI:
    token = token or secrets.token_urlsafe(24)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.windows = []  # the WebUI of each open window, newest last
    app.state.notify = None  # set by the tray icon: notify(title, text)
    app.state.restart = None  # set by the desktop window: restart()

    # ---- the browser extension

    bridge = BrowserBridge(jarvis.settings)
    jarvis.ctx.browser = bridge
    app.state.browser = bridge

    @app.websocket("/ws/browser")
    async def browser_endpoint(ws: WebSocket) -> None:
        """The extension connects here. It must present the pairing code,
        and must really be a browser extension (not a web page)."""
        import hmac

        origin = ws.headers.get("origin", "")
        paired = hmac.compare_digest(ws.query_params.get("token", ""), bridge.code)
        if not paired or not origin.startswith(("chrome-extension://", "moz-extension://")):
            await ws.close(code=1008)
            return
        await ws.accept()
        bridge.attach(ws, asyncio.get_running_loop())
        jarvis.log.record("browser", detail="extension connected")

        async def keep_awake() -> None:  # browsers put idle extensions to sleep
            while True:
                await asyncio.sleep(20)
                await ws.send_json({"type": "ping"})

        pinger = asyncio.create_task(keep_awake())
        try:
            while True:
                message = await ws.receive_json()
                if message.get("type") != "pong":
                    bridge.on_message(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pinger.cancel()
            bridge.detach(ws)
            jarvis.log.record("browser", detail="extension disconnected")

    @app.get("/api/browser")
    def browser_state(request: Request) -> dict:
        authorise(request)
        from jarvis.core.config import REPO_ROOT

        return {
            "connected": bridge.connected,
            "code": bridge.code,
            "approved_sites": sorted(jarvis.settings.approved_sites),
            "extension_folder": str(REPO_ROOT / "extension"),
        }

    @app.post("/api/browser/sites")
    async def browser_site(request: Request) -> dict:
        authorise(request)
        from jarvis.core.config import set_site_approval

        data = await request.json()
        try:
            set_site_approval(jarvis.settings, str(data.get("site", "")), data.get("approved") is not False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        jarvis.log.record("site", detail=f"{data.get('site')} {'approved' if data.get('approved') is not False else 'removed'} in the control panel")
        return {"approved_sites": sorted(jarvis.settings.approved_sites)}

    # ---- scheduling: results go to the open window (and the tray, if any)

    def deliver(item: dict, text: str) -> None:
        # Part of the conversation: shown again after a restart, and the
        # model is told about it in its recap.
        jarvis.conversation.add({"type": "scheduled", "title": item["title"], "text": text})
        jarvis.conversation.save()
        for ui in list(app.state.windows):
            ui._send({"type": "scheduled", "title": item["title"], "text": text})
        if app.state.notify is not None:
            app.state.notify(item["title"], text if len(text) <= 220 else text[:217] + "...")

    def ask(tool_name: str, decision: Decision) -> bool:
        if not app.state.windows:
            return False
        if app.state.notify is not None:
            app.state.notify("JARVIS needs your approval", f"A scheduled task wants to use {tool_name}. Open JARVIS to answer.")
        return app.state.windows[-1].confirm(tool_name, decision)

    def scheduled_agent() -> Jarvis:
        agent = make_agent() if make_agent else Jarvis(jarvis.settings, jarvis.registry, jarvis.log, jarvis.kill)
        agent.ctx.schedule = scheduler.schedule
        agent.ctx.browser = app.state.browser
        return agent

    scheduler = Scheduler(jarvis, deliver, ask, scheduled_agent)
    jarvis.ctx.schedule = scheduler.schedule
    app.state.scheduler = scheduler

    # ---- the widgets around the dial

    @app.get("/api/status")
    def status(request: Request) -> dict:
        authorise(request)
        import shutil

        from jarvis.integrations import accounts
        from jarvis.tools.weather import glance

        usage = shutil.disk_usage(jarvis.settings.home.anchor or "/")
        result: dict = {
            "disk": {"total_gb": round(usage.total / 1e9), "free_gb": round(usage.free / 1e9), "used": round(usage.used / usage.total, 3)},
            "cpu": None, "memory": None, "battery": None,
        }
        try:
            import psutil

            result["cpu"] = round(psutil.cpu_percent(interval=None))
            result["memory"] = round(psutil.virtual_memory().percent)
            battery = psutil.sensors_battery()
            if battery is not None:
                result["battery"] = {"percent": round(battery.percent), "plugged": bool(battery.power_plugged)}
        except Exception:
            pass  # the gauges simply stay empty
        connected = []
        for account in accounts.ACCOUNTS.values():
            try:
                connected.append({"label": account.label, "connected": accounts.is_connected(account)})
            except Exception:
                connected.append({"label": account.label, "connected": False})
        connected.append({"label": "Browser", "connected": bridge.connected})
        upcoming = sorted((i for i in scheduler.schedule.items() if i.get("next")), key=lambda i: i["next"])
        allowance = jarvis.allowance()
        result.update(
            usage={
                **allowance,
                "context": jarvis._size() if jarvis.messages else 0,
                "context_budget": jarvis.settings.context_budget,
                "week": jarvis.usage.history(),
            },
            accounts=connected,
            next=({"title": upcoming[0]["title"], "at": upcoming[0]["next"]} if upcoming else None),
            weather=glance(jarvis.settings.location),
            launcher=[i["label"] for i in jarvis.settings.launcher],
            memories=jarvis.memory.counts()[0] if jarvis.memory is not None else 0,
        )
        return result

    @app.post("/api/launch/{index}")
    def launch(index: int, request: Request) -> dict:
        """Open one of the quick-launch entries from settings.toml. Only
        those entries can be opened this way, never an arbitrary name."""
        authorise(request)
        import webbrowser

        from jarvis.tools import desktop

        if not 0 <= index < len(jarvis.settings.launcher):
            raise HTTPException(status_code=404)
        entry = jarvis.settings.launcher[index]
        target = entry["open"]
        if target.lower().startswith(("http://", "https://")):
            ok, detail = bool(webbrowser.open(target)), ""
        else:
            outcome = desktop.open_app({"name": target}, jarvis.ctx)
            ok, detail = not outcome.is_error, outcome.text
        jarvis.log.record("launch", detail=f"{entry['label']} ({target}) from the window" + ("" if ok else f": failed: {detail}"))
        if not ok:
            raise HTTPException(status_code=400, detail=detail or "Could not open it.")
        return {"ok": True}

    # ---- first-run setup: who you are and which model to use

    def setup_state() -> dict:
        from jarvis.app import startup_problem

        s = jarvis.settings
        try:
            problem = startup_problem(s)
        except Exception as exc:
            problem = str(exc)
        return {
            "needed": problem is not None,
            "problem": problem,
            "profile": {
                "address_as": s.address_as, "location": s.location, "provider": s.provider,
                "base_url": s.compat_base_url, "model": s.compat_model,
                "ollama_model": s.ollama_model, "claude_model": s.model,
                "permission_mode": s.permission_mode,
            },
        }

    @app.get("/api/setup")
    def setup_get(request: Request) -> dict:
        authorise(request)
        return setup_state()

    @app.post("/api/setup")
    async def setup_post(request: Request) -> dict:
        """Save the setup screen's answers, then check that the model answers."""
        authorise(request)
        from jarvis.core import secrets as keychain
        from jarvis.core.brains import BrainError
        from jarvis.core.config import ADJUSTABLE, PROFILE, save_override, save_profile

        data = await request.json()
        profile = {k: v for k, v in data.items() if k in PROFILE}
        save_profile(jarvis.settings, profile)
        if data.get("permission_mode") in ADJUSTABLE["permission_mode"]:
            save_override(jarvis.settings, "permission_mode", data["permission_mode"])
        key = str(data.get("key") or "").strip()
        if key:
            # Keys go to the OS keychain, never into a file.
            name = "anthropic.key" if jarvis.settings.provider == "anthropic" else "model.key"
            try:
                keychain.put(name, key)
            except keychain.SecretsUnavailable as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
        jarvis.reconfigure()
        jarvis.log.record("setup", detail=f"provider {jarvis.settings.provider}; fields: {', '.join(sorted(profile)) or 'none'}" + ("; key stored" if key else ""))

        state = setup_state()
        if not state["needed"] and hasattr(jarvis.brain, "ping"):
            try:
                await run_in_threadpool(jarvis.brain.ping)
            except BrainError as exc:
                state.update(needed=True, problem=str(exc))
        return state

    # ---- connecting accounts from the window

    @app.post("/api/connections/{key}/connect")
    async def connect(key: str, request: Request) -> dict:
        authorise(request)
        from jarvis.core import secrets as keychain
        from jarvis.integrations import accounts, cli, oauth, tokens

        account = accounts.ACCOUNTS.get(key)
        if account is None:
            raise HTTPException(status_code=404)
        data = await request.json()

        def work() -> str:
            if isinstance(account, tokens.TokenAccount):
                token_value = str(data.get("token") or "").strip()
                if not token_value:
                    raise oauth.ApiError(0, "Paste the token first.")
                tokens.connect(account, token_value)
                try:
                    return cli._whoami(account)
                except Exception:
                    tokens.disconnect(account)  # do not keep a token that does not work
                    raise
            client_id = str(data.get("client_id") or "").strip()
            client_secret = str(data.get("client_secret") or "").strip()
            if not client_id or (account.needs_secret and not client_secret):
                raise oauth.ApiError(0, "Fill in the Client ID" + (" and Client secret" if account.needs_secret else "") + " first.")
            oauth.connect(account, client_id, client_secret or None)  # opens the browser and waits for approval
            return cli._whoami(account)

        try:
            who = await run_in_threadpool(work)
        except (oauth.ApiError, oauth.NotConnected, keychain.SecretsUnavailable) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        jarvis.log.record("connection", detail=f"{account.label} connected from the control panel")
        return {"ok": True, "as": who}

    # ---- the conversation so far, for redrawing after a restart

    @app.get("/api/conversation")
    def conversation(request: Request) -> dict:
        authorise(request)
        return {"items": jarvis.conversation.view()}

    # ---- updating

    @app.get("/api/update")
    def update_check(request: Request) -> dict:
        authorise(request)
        from jarvis.core import updater

        try:
            return {**updater.check(), "can_restart": app.state.restart is not None}
        except updater.UpdateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.post("/api/update")
    def update_apply(request: Request) -> dict:
        authorise(request)
        from jarvis.core import updater

        try:
            result = updater.apply()
        except updater.UpdateError as exc:
            jarvis.log.record("update", detail=f"failed: {str(exc)[:300]}")
            raise HTTPException(status_code=400, detail=str(exc)) from None
        jarvis.log.record("update", detail=f"{result['from']} -> {result['to']}")
        return {**result, "can_restart": app.state.restart is not None}

    @app.post("/api/restart")
    def restart(request: Request) -> dict:
        authorise(request)
        if app.state.restart is None:
            raise HTTPException(status_code=400, detail="Close JARVIS and open it again to finish.")
        jarvis.log.record("update", detail="restarting")
        threading.Timer(0.3, app.state.restart).start()  # let this reply go out first
        return {"ok": True}

    @app.get("/api/schedule")
    def schedule_list(request: Request) -> dict:
        authorise(request)
        items = sorted(scheduler.schedule.items(), key=lambda i: i.get("next") or "")
        return {"items": [{**i, "when": describe_when(i)} for i in items]}

    @app.delete("/api/schedule/{item_id}")
    def schedule_remove(item_id: int, request: Request) -> dict:
        authorise(request)
        if not scheduler.schedule.remove(item_id):
            raise HTTPException(status_code=404)
        jarvis.log.record("scheduled", detail=f"item #{item_id} cancelled from the control panel")
        return {"ok": True}

    @app.post("/api/schedule/{item_id}/run")
    def schedule_run(item_id: int, request: Request) -> dict:
        authorise(request)
        item = scheduler.schedule.get(item_id)
        if item is None:
            raise HTTPException(status_code=404)
        threading.Thread(target=scheduler.run, args=(item,), daemon=True).start()
        return {"ok": True}

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
            "sight": s.sight,
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
        from jarvis.integrations import accounts

        result = []
        for account in accounts.ACCOUNTS.values():
            try:
                connected = accounts.is_connected(account)
            except Exception:
                connected = False
            result.append({"key": account.key, "label": account.label, "connected": connected})
        return {"connections": result}

    @app.post("/api/connections/{key}/disconnect")
    def disconnect(key: str, request: Request) -> dict:
        authorise(request)
        from jarvis.integrations import accounts

        account = accounts.ACCOUNTS.get(key)
        if account is None:
            raise HTTPException(status_code=404)
        accounts.disconnect(account)
        jarvis.log.record("connection", detail=f"{account.label} disconnected from the control panel")
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
        app.state.windows.append(ui)
        busy = threading.Lock()
        jarvis.log.record("session_start", detail="window")
        if jarvis.kill.tripped:
            await ws.send_json({"type": "info", "text": "The emergency stop is engaged. Type /resume to clear it."})

        def work(text: str, spoken: bool) -> None:
            try:
                status = jarvis.send(text, ui, spoken=spoken)
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
                    ui.resolve(int(msg.get("id", 0)), msg.get("approved") is True, msg.get("approve_site") is True)

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
                    threading.Thread(target=work, args=(text, msg.get("spoken") is True), daemon=True).start()
        except WebSocketDisconnect:
            ui.cancel_all()
        finally:
            if ui in app.state.windows:
                app.state.windows.remove(ui)

    return app


def serve(jarvis: Jarvis, port: int = 0) -> tuple[threading.Thread, str, FastAPI]:
    """Start the server (and the scheduler) on background threads.
    Returns (thread, url, app)."""
    import socket

    import uvicorn

    if port == 0:
        # Use the same port every time if we can. The window remembers
        # permissions (such as the microphone) per address, so a port that
        # changed on every start would mean being asked on every start.
        for candidate in (PREFERRED_PORT, 0):  # 0 asks the OS for any free port
            try:
                with socket.socket() as s:
                    s.bind(("127.0.0.1", candidate))
                    port = s.getsockname()[1]
                break
            except OSError:
                continue
    app = create_app(jarvis)
    app.state.scheduler.start()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread, f"http://127.0.0.1:{port}/", app
