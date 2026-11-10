"""Tests for the local-model backend, against a small fake Ollama server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarvis.app import startup_problem
from jarvis.core.actionlog import ActionLog
from jarvis.core.agent import Jarvis
from jarvis.core.brains import BrainError, OllamaBrain, to_ollama_messages

from .conftest import FakeUI


class FakeOllama:
    """Replays scripted /api/chat responses and records what it was sent."""

    def __init__(self):
        self.script = []      # each item: list of chunk dicts, or (status, body)
        self.requests = []
        self.models = ["qwen3:8b"]
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"models": [{"name": m} for m in outer.models]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                outer.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                item = outer.script.pop(0)
                if isinstance(item, tuple):
                    self.send_response(item[0])
                    self.end_headers()
                    self.wfile.write(json.dumps(item[1]).encode())
                    return
                self.send_response(200)
                self.end_headers()
                for chunk in item:
                    self.wfile.write(json.dumps(chunk).encode() + b"\n")

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def says(*pieces):
    chunks = [{"message": {"role": "assistant", "content": p}, "done": False} for p in pieces]
    return chunks + [{"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}]


def calls(name, arguments):
    return [
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    ]


@pytest.fixture
def ollama(settings):
    fake = FakeOllama()
    settings.provider = "ollama"
    settings.ollama_host = fake.url
    yield fake
    fake.server.shutdown()


@pytest.fixture
def jarvis(settings, kill, registry, ollama):
    return Jarvis(settings, registry, ActionLog(settings.action_log_path), kill)


def test_plain_reply_streams(jarvis, ollama):
    ollama.script = [says("Good ", "evening, ", "Sir.")]
    ui = FakeUI()
    assert jarvis.send("hello", ui) == "done"
    assert ui.text == "Good evening, Sir."
    req = ollama.requests[0]
    assert req["model"] == "qwen3:8b" and req["options"]["num_ctx"] == 8192
    assert req["think"] is False and req["keep_alive"] == "30m"
    assert req["messages"][0]["role"] == "system" and "JARVIS" in req["messages"][0]["content"]
    assert req["tools"][0]["type"] == "function" and "parameters" in req["tools"][0]["function"]


def test_tool_loop_and_history_translation(jarvis, ollama):
    ollama.script = [
        calls("write_file", {"path": "n.txt", "content": "milk"}),
        calls("read_file", {"path": "n.txt"}),
        says("Done."),
    ]
    ui = FakeUI()
    assert jarvis.send("make a note", ui) == "done"
    assert ui.tools == [("write_file", "auto"), ("read_file", "auto")]
    assert (jarvis.settings.workspace / "n.txt").read_text() == "milk"

    sent = ollama.requests[2]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert sent[2]["tool_calls"][0]["function"] == {"name": "write_file", "arguments": {"path": "n.txt", "content": "milk"}}
    assert sent[3]["tool_name"] == "write_file" and "Created" in sent[3]["content"]
    assert sent[5]["tool_name"] == "read_file" and "<untrusted_data" in sent[5]["content"]


def test_permission_gate_applies_to_local_model(jarvis, ollama):
    ollama.script = [
        calls("run_command", {"command": "netsh advfirewall set allprofiles state off"}),
        calls("run_command", {"command": "echo hi > f.txt"}),
        says("Understood."),
    ]
    ui = FakeUI(approve=False)
    jarvis.send("go", ui)
    assert ui.tools == [("run_command", "blocked"), ("run_command", "denied")]
    assert not (jarvis.settings.workspace / "f.txt").exists()


def test_sloppy_arguments_are_rejected_not_run(jarvis, ollama):
    ollama.script = [
        calls("write_file", '{"path": "a.txt", "content": "from a JSON string"}'),  # string form is accepted
        calls("write_file", "not json at all"),
        calls("write_file", {"path": "b.txt"}),  # missing content
        says("Sorry."),
    ]
    ui = FakeUI()
    jarvis.send("go", ui)
    assert (jarvis.settings.workspace / "a.txt").read_text() == "from a JSON string"
    assert ui.tools == [("write_file", "auto")]
    assert not (jarvis.settings.workspace / "b.txt").exists()
    assert "Invalid input" in ollama.requests[3]["messages"][-1]["content"]


def test_model_without_thinking_mode_is_retried(jarvis, ollama):
    ollama.script = [(400, {"error": '"llama3.1" does not support thinking'}), says("Hello.")]
    ui = FakeUI()
    assert jarvis.send("hi", ui) == "done" and ui.text == "Hello."
    assert "think" not in ollama.requests[1]


def test_timings_are_logged(jarvis, ollama):
    done = {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
            "total_duration": 31_000_000_000, "load_duration": 9_000_000_000, "prompt_eval_count": 2100,
            "prompt_eval_duration": 4_000_000_000, "eval_count": 360, "eval_duration": 18_000_000_000}
    ollama.script = [[{"message": {"role": "assistant", "content": "Hi."}, "done": False}, done]]
    jarvis.send("hi", FakeUI())
    entry = [e for e in jarvis.log.tail(5) if e["event"] == "model"][0]
    assert "total 31.0s" in entry["detail"] and "20 tokens/s" in entry["detail"] and "2100 tokens" in entry["detail"]


def test_length_cutoff(jarvis, ollama):
    ollama.script = [[{"message": {"role": "assistant", "content": "A very long"}, "done": True, "done_reason": "length"}]]
    assert jarvis.send("go", FakeUI()) == "truncated"


def test_helpful_errors(jarvis, ollama, settings):
    ollama.script = [(404, {"error": "model 'qwen3:8b' not found"})]
    with pytest.raises(BrainError, match="ollama pull qwen3:8b"):
        jarvis.send("hi", FakeUI())
    ollama.script = [(400, {"error": "registry.ollama.ai/library/gemma:2b does not support tools"})]
    with pytest.raises(BrainError, match="cannot call tools"):
        jarvis.send("hi", FakeUI())
    # The history is still usable afterwards.
    ollama.script = [says("Back.")]
    assert jarvis.send("hi", FakeUI()) == "done"


def test_startup_check(settings, ollama):
    assert startup_problem(settings) is None
    settings.ollama_model = "llama3.1"
    assert "ollama pull llama3.1" in startup_problem(settings)
    ollama.models.append("llama3.1:latest")
    assert startup_problem(settings) is None
    settings.ollama_host = "http://127.0.0.1:1"
    assert "Cannot reach Ollama" in startup_problem(settings)
    with pytest.raises(BrainError, match="Is Ollama running"):
        OllamaBrain(settings).respond("s", [], [{"role": "user", "content": "x"}], lambda t: None, None)


def test_kill_switch_stops_local_generation(jarvis, ollama):
    ollama.script = [says(*["word "] * 50)]
    ui = FakeUI()
    ui.on_text = lambda delta: jarvis.kill.trip()
    assert jarvis.send("talk", ui) == "stopped"


def test_translation_of_plain_messages():
    assert to_ollama_messages([{"role": "user", "content": "hi"}]) == [{"role": "user", "content": "hi"}]
