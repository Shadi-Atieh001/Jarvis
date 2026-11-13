"""The first-run setup screen and connecting accounts from the window."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from jarvis.app import startup_problem
from jarvis.core import secrets
from jarvis.core.actionlog import ActionLog
from jarvis.core.agent import Jarvis
from jarvis.core.config import load_settings, overrides_path, save_profile
from jarvis.integrations import oauth
from jarvis.ui import server

from .conftest import FakeUI

HEADERS = {"x-jarvis-token": "tok", "origin": "http://testserver"}


@pytest.fixture
def keychain(monkeypatch):
    store = {}
    monkeypatch.setattr(secrets, "get", store.get)
    monkeypatch.setattr(secrets, "put", store.__setitem__)
    monkeypatch.setattr(secrets, "delete", lambda name: store.pop(name, None))
    monkeypatch.delenv("JARVIS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return store


@pytest.fixture
def service():
    """A stand-in model service that accepts one particular key."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.headers.get("Authorization"), body))
            if self.headers.get("Authorization") != "Bearer good-key":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Invalid API key"}}')
                return
            self.send_response(200)
            self.end_headers()
            if body.get("stream"):
                self.wfile.write(b'data: {"choices": [{"delta": {"content": "At your service."}, "finish_reason": "stop"}]}\n\ndata: [DONE]\n\n')
            else:
                self.wfile.write(b'{"choices": [{"message": {"content": "ready"}}]}')

    web = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    yield type("S", (), {"url": f"http://127.0.0.1:{web.server_port}/v1", "seen": seen})()
    web.shutdown()


@pytest.fixture
def fresh(settings, kill, registry, keychain):
    """JARVIS as a new user gets it: a hosted provider and no key."""
    settings.provider, settings.compat_base_url, settings.compat_model = "openai_compatible", "https://api.example.com/v1", "some-model"
    j = Jarvis(settings, registry, ActionLog(settings.action_log_path), kill)
    return j, TestClient(server.create_app(j, token="tok"))


def test_a_new_installation_asks_to_be_set_up(fresh):
    j, c = fresh
    assert c.get("/api/setup").status_code == 403
    state = c.get("/api/setup", headers=HEADERS).json()
    assert state["needed"] is True and "No key" in state["problem"]
    assert state["profile"]["provider"] == "openai_compatible" and state["profile"]["address_as"] == "Sir"
    assert "key" not in json.dumps(state["profile"]).lower().replace("api_key_env", "")  # a stored key is never sent back


def test_setup_saves_checks_and_takes_effect(fresh, service, keychain):
    j, c = fresh
    answers = {"address_as": "Layla", "location": "Dubai", "provider": "openai_compatible", "base_url": service.url,
               "model": "k2", "key": "good-key", "permission_mode": "careful"}
    state = c.post("/api/setup", headers=HEADERS, json=answers).json()
    assert state["needed"] is False and state["problem"] is None
    assert keychain == {"model.key": "good-key"}  # in the keychain...
    saved = overrides_path(j.settings).read_text()
    assert "good-key" not in saved and json.loads(saved)["address_as"] == "Layla"  # ...never in a file
    assert service.seen[0][1]["stream"] is False  # the check was a real request to the service

    assert j.settings.permission_mode == "careful" and j.settings.location == "Dubai"
    assert 'Address the user as "Layla"' in j.system_prompt and "Dubai" in j.system_prompt
    ui = FakeUI()
    assert j.send("hello", ui) == "done" and ui.text == "At your service."  # and JARVIS now works
    assert "good-key" not in j.settings.action_log_path.read_text()

    # After a restart the answers are still there.
    again = load_settings()
    again.home = j.settings.home
    from jarvis.core.config import apply_overrides

    apply_overrides(again)
    assert again.address_as == "Layla" and again.compat_base_url == service.url and again.compat_model == "k2"


def test_setup_reports_a_wrong_key_and_stays_open(fresh, service):
    j, c = fresh
    state = c.post("/api/setup", headers=HEADERS, json={"provider": "openai_compatible", "base_url": service.url, "model": "k2", "key": "wrong"}).json()
    assert state["needed"] is True and "key was rejected" in state["problem"]


def test_setup_ignores_nonsense(fresh):
    j, c = fresh
    c.post("/api/setup", headers=HEADERS, json={"provider": "skynet", "address_as": "", "location": "x" * 999, "home": "/", "permission_mode": "yolo"})
    assert j.settings.provider == "openai_compatible" and j.settings.address_as == "Sir" and j.settings.location != "x" * 999
    assert j.settings.permission_mode == "careful"  # unchanged from the test default


def test_choosing_ollama_or_claude(fresh, keychain, monkeypatch):
    j, c = fresh
    state = c.post("/api/setup", headers=HEADERS, json={"provider": "ollama", "ollama_model": "qwen3:4b"}).json()
    assert j.settings.provider == "ollama" and j.settings.ollama_model == "qwen3:4b"
    assert state["needed"] is True and "Ollama" in state["problem"]  # nothing is running here
    state = c.post("/api/setup", headers=HEADERS, json={"provider": "anthropic", "key": "sk-ant-test-0123456789"}).json()
    assert state["needed"] is False and keychain["anthropic.key"] == "sk-ant-test-0123456789"
    assert type(j.brain).__name__ == "AnthropicBrain"


def test_key_from_the_environment_still_works(settings, keychain, monkeypatch):
    settings.provider, settings.compat_base_url, settings.compat_model = "openai_compatible", "https://api.example.com/v1", "m"
    assert "No key" in startup_problem(settings)
    monkeypatch.setenv("JARVIS_API_KEY", "from-the-environment")
    assert startup_problem(settings) is None
    monkeypatch.delenv("JARVIS_API_KEY")
    keychain["model.key"] = "from-the-keychain"
    assert startup_problem(settings) is None


def test_profile_file_is_validated_on_load(settings):
    save_profile(settings, {"address_as": "Omar", "provider": "ollama"})
    path = overrides_path(settings)
    data = json.loads(path.read_text())
    data.update(provider="skynet", location=42, model="line\nbreak")
    path.write_text(json.dumps(data))
    from jarvis.core.config import apply_overrides

    settings.provider, settings.location = "anthropic", "Sharjah"
    apply_overrides(settings)
    assert settings.address_as == "Omar" and settings.provider == "anthropic" and settings.location == "Sharjah"


# ---------------------------------------------- connecting from the window


def test_connect_with_a_token_from_the_window(fresh, keychain, monkeypatch):
    j, c = fresh
    calls = []

    def fake_http(method, url, headers=None, data=None):
        calls.append(url)
        if "api.github.com/user" in url:
            return (200, b'{"login": "layla"}') if headers["Authorization"] == "Bearer ghp_good" else (401, b'{"message": "Bad credentials"}')
        return 200, b'{"candidates": [{"content": {"parts": [{"text": "ready"}]}}]}'

    monkeypatch.setattr(oauth, "_http", fake_http)
    assert c.post("/api/connections/github/connect", json={"token": "ghp_good"}).status_code == 403
    r = c.post("/api/connections/github/connect", headers=HEADERS, json={"token": "ghp_good"})
    assert r.json() == {"ok": True, "as": "layla"} and keychain["github.token"] == "ghp_good"
    r = c.post("/api/connections/notion/connect", headers=HEADERS, json={"token": ""})
    assert r.status_code == 400 and "Paste the token" in r.json()["detail"]
    keychain.pop("github.token")
    r = c.post("/api/connections/github/connect", headers=HEADERS, json={"token": "ghp_bad"})
    assert r.status_code == 400 and "github.token" not in keychain  # a token that fails is not kept
    r = c.post("/api/connections/gemini/connect", headers=HEADERS, json={"token": "AIza-key"})
    assert r.status_code == 200 and keychain["gemini.token"] == "AIza-key"
    assert c.post("/api/connections/myspace/connect", headers=HEADERS, json={}).status_code == 404
    assert "ghp_good" not in j.settings.action_log_path.read_text()


def test_connect_google_from_the_window(fresh, keychain, monkeypatch):
    j, c = fresh
    started = []
    monkeypatch.setattr(oauth, "connect", lambda account, client_id, client_secret=None: started.append((account.key, client_id, client_secret)))
    monkeypatch.setattr(oauth, "call", lambda *a, **k: {"emailAddress": "layla@example.com"})
    r = c.post("/api/connections/google/connect", headers=HEADERS, json={"client_id": "id.apps", "client_secret": "s3cret"})
    assert r.json() == {"ok": True, "as": "layla@example.com"} and started == [("google", "id.apps", "s3cret")]
    r = c.post("/api/connections/google/connect", headers=HEADERS, json={"client_id": "id.apps"})
    assert r.status_code == 400 and "Client secret" in r.json()["detail"]
    r = c.post("/api/connections/spotify/connect", headers=HEADERS, json={"client_id": "spot"})
    assert r.status_code == 200 and started[-1] == ("spotify", "spot", None)
