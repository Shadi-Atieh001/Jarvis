import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jarvis.__main__ import main
from jarvis.core import commands
from jarvis.ui.server import create_app

from .conftest import FakeUI, call, reply, text


def test_commands(make_jarvis):
    j, _ = make_jarvis(reply(call("list_dir", {})), reply(text("ok")))
    assert commands.handle("hello", j) is None
    assert "/log" in commands.handle("/help", j)
    tools = commands.handle("/tools", j)
    assert "run_command" in tools and "execute" in tools and "careful" in tools
    j.send("look", FakeUI())
    assert "list_dir" in commands.handle("/log", j)
    assert "engaged" in commands.handle("/stop", j) and j.kill.tripped
    assert "cleared" in commands.handle("/resume", j) and not j.kill.tripped
    commands.handle("/clear", j)
    assert j.messages == []
    assert commands.handle("/quit", j) == commands.QUIT
    assert "Unknown" in commands.handle("/nonsense", j)


def test_cli_stop_resume_log(settings, monkeypatch, capsys, tmp_path):
    cfg = tmp_path / "s.toml"
    cfg.write_text(f'[paths]\nhome = "{settings.home.as_posix()}"\nworkspace = "{settings.workspace.as_posix()}"\n')
    monkeypatch.setenv("JARVIS_SETTINGS", str(cfg))
    assert main(["stop"]) == 0 and settings.stop_file.exists()
    assert main(["resume"]) == 0 and not settings.stop_file.exists()
    assert main(["log"]) == 0
    assert "kill_switch" in capsys.readouterr().out


def test_cli_refuses_to_start_without_key(settings, monkeypatch, capsys, tmp_path):
    cfg = tmp_path / "s.toml"
    cfg.write_text(f'[assistant]\nprovider = "anthropic"\n[paths]\nhome = "{settings.home.as_posix()}"\n')
    monkeypatch.setenv("JARVIS_SETTINGS", str(cfg))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["chat"]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


def _connect(client, token, origin="http://testserver"):
    return client.websocket_connect(f"/ws?token={token}", headers={"origin": origin})


def test_page_is_served_with_token(make_jarvis):
    j, _ = make_jarvis()
    client = TestClient(create_app(j, token="tok"))
    html = client.get("/").text
    assert "tok" in html and "__JARVIS_TOKEN__" not in html and "Stop" in html


def test_websocket_rejects_wrong_token_and_foreign_origin(make_jarvis):
    j, _ = make_jarvis()
    client = TestClient(create_app(j, token="tok"))
    for token, origin in [("wrong", "http://testserver"), ("tok", "http://evil.example"), ("tok", "")]:
        with pytest.raises(WebSocketDisconnect):
            with _connect(client, token, origin) as ws:
                ws.receive_json()


def _until_done(ws):
    seen = []
    while True:
        m = ws.receive_json()
        seen.append(m)
        if m["type"] == "done":
            return seen


def test_websocket_chat_with_confirmation(make_jarvis):
    j, _ = make_jarvis(
        reply(text("Certainly. "), call("run_command", {"command": "echo from-window"})),
        reply(text("Done, Sir.")),
        reply(call("run_command", {"command": "echo second > never.txt"})),
        reply(text("As you wish.")),
    )
    client = TestClient(create_app(j, token="tok"))
    with _connect(client, "tok") as ws:
        ws.send_json({"type": "user", "text": "run it"})
        m = ws.receive_json()
        assert m == {"type": "text", "delta": "Certainly. "}
        m = ws.receive_json()
        assert m["type"] == "confirm" and "echo from-window" in m["description"]
        ws.send_json({"type": "confirm_reply", "id": m["id"], "approved": True})
        rest = _until_done(ws)
        assert {"type": "tool", "name": "run_command", "decision": "approved"}.items() <= rest[0].items()
        assert rest[-1] == {"type": "done", "status": "done"}

        # Refusing: the command must not run.
        ws.send_json({"type": "user", "text": "again"})
        m = ws.receive_json()
        ws.send_json({"type": "confirm_reply", "id": m["id"], "approved": False})
        rest = _until_done(ws)
        assert rest[0]["decision"] == "denied"
        assert not (j.settings.workspace / "never.txt").exists()

        ws.send_json({"type": "user", "text": "/log 5"})
        assert "run_command" in ws.receive_json()["text"]


def test_stop_button_cancels_pending_confirmation(make_jarvis):
    j, _ = make_jarvis(reply(call("run_command", {"command": "echo x > stopped.txt"})), reply(text("never")))
    client = TestClient(create_app(j, token="tok"))
    with _connect(client, "tok") as ws:
        ws.send_json({"type": "user", "text": "go"})
        assert ws.receive_json()["type"] == "confirm"
        ws.send_json({"type": "stop"})
        rest = _until_done(ws)
        assert rest[-1]["status"] == "stopped"
        assert j.kill.tripped and not (j.settings.workspace / "stopped.txt").exists()
        # Further requests are refused until /resume.
        ws.send_json({"type": "user", "text": "hello?"})
        assert "engaged" in ws.receive_json()["text"]
        assert ws.receive_json()["type"] == "done"
        ws.send_json({"type": "user", "text": "/resume"})
        assert "cleared" in ws.receive_json()["text"]
