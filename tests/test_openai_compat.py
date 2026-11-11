"""Tests for the OpenAI-compatible backend, against a small fake server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarvis.app import startup_problem
from jarvis.core.actionlog import ActionLog
from jarvis.core.agent import Jarvis
from jarvis.core.brains import BrainError

from .conftest import FakeUI

KEY = "IFM-test-key-0123456789"


class FakeService:
    def __init__(self):
        self.script, self.requests, self.auth = [], [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                outer.auth.append(self.headers.get("Authorization"))
                outer.requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                item = outer.script.pop(0)
                if isinstance(item, tuple):
                    self.send_response(item[0])
                    self.end_headers()
                    self.wfile.write(json.dumps(item[1]).encode())
                    return
                self.send_response(200)
                self.end_headers()
                for chunk in item:
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def delta(d, finish=None):
    return {"choices": [{"index": 0, "delta": d, "finish_reason": finish}]}


def says(*pieces):
    return [delta({"content": p}) for p in pieces] + [delta({}, "stop")]


def calls(name, arguments, call_id="call_1"):
    text = json.dumps(arguments)
    half = len(text) // 2
    return [  # arguments arrive split across chunks, as real services send them
        delta({"tool_calls": [{"index": 0, "id": call_id, "type": "function", "function": {"name": name, "arguments": text[:half]}}]}),
        delta({"tool_calls": [{"index": 0, "function": {"arguments": text[half:]}}]}),
        delta({}, "tool_calls"),
    ]


@pytest.fixture
def service(settings, monkeypatch):
    fake = FakeService()
    settings.provider = "openai_compatible"
    settings.compat_base_url = fake.url
    settings.compat_model = "some-model"
    monkeypatch.setenv("JARVIS_API_KEY", KEY)
    yield fake
    fake.server.shutdown()


@pytest.fixture
def jarvis(settings, kill, registry, service):
    return Jarvis(settings, registry, ActionLog(settings.action_log_path), kill)


def test_reply_and_request_shape(jarvis, service):
    service.script = [says("Good ", "evening, Sir.")]
    ui = FakeUI()
    assert jarvis.send("hello", ui) == "done" and ui.text == "Good evening, Sir."
    path, body = service.requests[0]
    assert path == "/v1/chat/completions" and body["model"] == "some-model" and body["stream"] is True
    assert service.auth[0] == f"Bearer {KEY}"
    assert body["messages"][0]["role"] == "system" and body["tools"][0]["type"] == "function"


def test_tool_loop_and_history_translation(jarvis, service):
    service.script = [calls("write_file", {"path": "n.txt", "content": "milk"}, "call_a"), says("Done.")]
    ui = FakeUI()
    assert jarvis.send("note", ui) == "done"
    assert (jarvis.settings.workspace / "n.txt").read_text() == "milk"
    sent = service.requests[1][1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool"]
    call = sent[2]["tool_calls"][0]
    assert call["id"] == "call_a" and json.loads(call["function"]["arguments"]) == {"path": "n.txt", "content": "milk"}
    assert sent[3]["tool_call_id"] == "call_a" and "Created" in sent[3]["content"]


def test_reasoning_is_hidden_but_replayed(jarvis, service):
    service.script = [
        [delta({"reasoning_content": "The user greets me. "}), delta({"reasoning_content": "Reply politely."}),
         delta({"content": "Good evening, Sir."}), delta({}, "stop")],
        [delta({"reasoning": "Need a file."}), *calls("write_file", {"path": "s.txt", "content": "milk"})],
        says("Done."),
    ]
    ui = FakeUI()
    jarvis.send("hello", ui)
    assert ui.text == "Good evening, Sir."  # reasoning is never shown
    jarvis.send("make s.txt", ui)
    sent = service.requests[2][1]["messages"]
    assistants = [m for m in sent if m["role"] == "assistant"]
    assert assistants[0]["reasoning_content"] == "The user greets me. Reply politely."
    assert assistants[1]["reasoning_content"] == "Need a file." and assistants[1]["content"] == ""
    assert assistants[1]["tool_calls"]


def test_every_assistant_turn_carries_the_field(jarvis, service):
    service.script = [says("One."), says("Two.")]
    jarvis.send("a", FakeUI())
    jarvis.send("b", FakeUI())
    assert service.requests[1][1]["messages"][2]["reasoning_content"] == ""


def test_gate_still_applies(jarvis, service):
    service.script = [calls("run_command", {"command": "Set-MpPreference -DisableRealtimeMonitoring $true"}), says("No.")]
    ui = FakeUI(approve=True)
    jarvis.send("go", ui)
    assert ui.tools == [("run_command", "blocked")] and ui.confirms == []


def test_errors_are_explained_and_key_never_logged(jarvis, service):
    service.script = [(401, {"error": {"message": f"bad key {KEY}"}})]
    with pytest.raises(BrainError, match="key was rejected"):
        jarvis.send(f"my key is {KEY}", FakeUI())
    jarvis.log.record("error", detail=f"leak {KEY}")
    assert KEY not in jarvis.settings.action_log_path.read_text()


def test_startup_checks(settings, service, monkeypatch):
    assert startup_problem(settings) is None
    monkeypatch.delenv("JARVIS_API_KEY")
    assert "setx JARVIS_API_KEY" in startup_problem(settings)
    monkeypatch.setenv("JARVIS_API_KEY", KEY)
    settings.compat_base_url = "http://example.com/v1"
    assert "https://" in startup_problem(settings)  # no keys over plain http
    settings.compat_base_url = ""
    assert "base_url" in startup_problem(settings)
