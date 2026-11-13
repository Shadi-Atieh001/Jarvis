"""Conversation persistence, condensing, usage tracking and the updater."""

import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jarvis.core import commands, updater
from jarvis.core.actionlog import ActionLog
from jarvis.core.agent import Jarvis
from jarvis.core.config import load_settings
from jarvis.core.conversation import Conversation
from jarvis.core.usage import UsageLog, estimate_tokens, format_tokens
from jarvis.ui import server

from .conftest import FakeClient, FakeUI, call, reply, text

HEADERS = {"x-jarvis-token": "tok", "origin": "http://testserver"}


class NoticeUI(FakeUI):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.notices = []

    def on_notice(self, text_):
        self.notices.append(text_)


def make(settings, kill, registry, *responses, path=True):
    client = FakeClient(responses)
    conversation = Conversation(settings.home / "conversation.json") if path else None
    return Jarvis(settings, registry, ActionLog(settings.action_log_path), kill, client=client, conversation=conversation), client


# -------------------------------------------------- surviving a restart


def test_conversation_is_saved_and_shown_again(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(text("Certainly. "), call("list_dir", {})), reply(text("Your workspace is empty.")))
    j.send("what is in my workspace?", FakeUI(), spoken=True)
    saved = json.loads((settings.home / "conversation.json").read_text())
    assert [i["type"] for i in saved] == ["user", "reply", "tool", "reply"]

    # "Restart": a brand-new assistant reading the same file.
    again, client = make(settings, kill, registry, reply(text("As I said, it is empty.")))
    view = again.conversation.view()
    assert view[0]["text"] == "what is in my workspace?" and view[0]["spoken"] is True
    assert view[2] == {"type": "tool", "name": "list_dir", "decision": "auto", "summary": view[2]["summary"], "time": view[2]["time"]}
    assert again.messages == []  # the model's own history is not restored...
    again.send("what did you just tell me?", FakeUI())
    first = client.requests[0]["messages"][0]["content"]  # ...it gets a written recap instead
    assert "<earlier_conversation>" in first and "what is in my workspace?" in first and "Your workspace is empty." in first
    assert first.index("</earlier_conversation>") < first.index("what did you just tell me?")
    assert first.count("what did you just tell me?") == 1  # the new message is not in its own recap


def test_recap_is_not_repeated_within_a_session(settings, kill, registry):
    j, client = make(settings, kill, registry, reply(text("One.")), reply(text("Two.")), reply(text("Three.")))
    for message in ("first", "second", "third"):
        j.send(message, FakeUI())
    assert "<earlier_conversation>" not in client.requests[0]["messages"][0]["content"]  # nothing earlier to recap
    assert all("<earlier_conversation>" not in m["content"] for m in client.requests[2]["messages"] if isinstance(m["content"], str))
    assert len(client.requests[2]["messages"]) == 5  # the real history is still being sent


def test_recap_shape():
    c = Conversation(None)
    for n in range(10):
        c.add({"type": "user", "text": f"question {n}"})
        c.add({"type": "reply", "text": f"answer {n} " + "x" * 3000})
    c.add({"type": "scheduled", "title": "Briefing", "text": "Good morning."})
    recap = c.recap()
    assert "Earlier, briefly:" in recap and "Most recently:" in recap
    assert "- User: question 0 |" in recap            # old ones: one line each
    assert "User: question 9\nYou: answer 9" in recap  # recent ones: in order, nearly in full
    assert "(scheduled: Briefing)" in recap and len(recap) < 14000
    assert Conversation(None).recap() == ""


def test_clear_forgets_the_conversation(settings, kill, registry):
    j, client = make(settings, kill, registry, reply(text("Hello.")), reply(text("Fresh start.")))
    j.send("hi", FakeUI())
    assert "cleared" in commands.handle("/clear", j)
    assert j.conversation.view() == [] and json.loads((settings.home / "conversation.json").read_text()) == []
    j.send("hello again", FakeUI())
    assert "<earlier_conversation>" not in client.requests[1]["messages"][0]["content"]


def test_a_damaged_file_does_not_stop_jarvis(settings, kill, registry):
    (settings.home / "conversation.json").write_text("{ this is not json")
    j, _ = make(settings, kill, registry, reply(text("Hello.")))
    assert j.conversation.view() == [] and j.send("hi", FakeUI()) == "done"


def test_scheduled_runs_do_not_write_to_the_conversation_file(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(text("Briefing.")), path=False)
    j.send("go", FakeUI())
    assert not (settings.home / "conversation.json").exists()


# ----------------------------------------------------------- condensing


def test_long_conversation_is_condensed(settings, kill, registry):
    settings.context_budget = 100_000
    j, client = make(settings, kill, registry, reply(text("A long answer. " + "word " * 300)), reply(text("Short.")), reply(text("Continuing.")))
    ui = NoticeUI()
    j.send("tell me a long story", ui)
    j.send("thanks", ui)
    assert ui.notices == [] and len(client.requests[1]["messages"]) == 3

    settings.context_budget = j._size() - 1  # the conversation is now over budget
    j.send("and then?", ui)
    assert len(ui.notices) == 1 and "condensed" in ui.notices[0]
    sent = client.requests[2]["messages"]
    assert len(sent) == 1  # a fresh history: just the recap and the new message
    assert "<earlier_conversation>" in sent[0]["content"] and "tell me a long story" in sent[0]["content"] and "and then?" in sent[0]["content"]
    assert any(i["type"] == "notice" for i in j.conversation.view())  # the user can see it happened
    assert any(e["event"] == "condensed" for e in j.log.tail(10))
    assert len({r["system"] for r in client.requests}) == 1  # the cached instructions never change


def test_size_uses_the_service_count_when_given(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(text("Hi.")))
    j.brain.last_usage = {"input": 23_000, "output": 500}
    j.send("hello", FakeUI())
    assert j.context_tokens == 23_500 and j._size() == 23_500


# ---------------------------------------------------------------- usage


def test_usage_is_counted_per_day(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(call("list_dir", {})), reply(text("Done.")))
    j.brain.last_usage = {"input": 9000, "output": 100}
    j.send("look", FakeUI())
    today = j.usage.today()
    assert today == {"input": 18000, "output": 200, "requests": 2, "total": 18200}  # two model calls
    assert UsageLog(settings.home / "usage.json").today()["total"] == 18200  # on disk, so it survives a restart
    assert j.usage.history(7)[-1]["total"] == 18200 and len(j.usage.history(7)) == 7


def test_usage_is_estimated_when_the_service_says_nothing(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(text("A reply of some length.")))
    j.send("hello there", FakeUI())
    today = j.usage.today()
    assert today["requests"] == 1 and today["input"] > 1000 and 0 < today["output"] < 50  # the tool list alone is thousands
    assert estimate_tokens("abcd" * 100) == 100
    assert [format_tokens(n) for n in (950, 1500, 23_400, 1_250_000)] == ["950", "1.5k", "23k", "1.25M"]


def test_allowance_prefers_what_the_service_reports(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(text("Hi.")))
    settings.daily_token_limit = 10_000_000
    j.brain.last_usage = {"input": 1000, "output": 10}
    j.send("hi", FakeUI())
    assert j.allowance() == {"used": 1010, "limit": 10_000_000, "requests": 1, "counted_here": 1010}
    # The service says more has been used than JARVIS counted (other apps share the key).
    j.usage.note_limits({"daily_limit": 10_000_000, "daily_remaining": 4_000_000})
    assert j.allowance()["used"] == 6_000_000
    report = commands.handle("/usage", j)
    assert "Today: 6.00M of 10.00M tokens" in report and "condensed at 40k" in report and "Last 7 days" in report


def test_warns_once_when_most_of_the_allowance_is_gone(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(text("One.")), reply(text("Two.")))
    settings.daily_token_limit = 1000
    j.brain.last_usage = {"input": 850, "output": 10}
    ui = NoticeUI()
    j.send("hi", ui)
    j.send("again", ui)
    assert len(ui.notices) == 1 and "allowance" in ui.notices[0]


def test_openai_compatible_usage_and_limits(settings, kill, registry, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            if "stream_options" in body and len(seen) == 1:  # a service that does not know the option
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Unknown parameter: stream_options"}}')
                return
            self.send_response(200)
            self.send_header("x-ratelimit-limit-tokens-daily", "10000000")
            self.send_header("x-ratelimit-remaining-tokens-daily", "9400000")
            self.end_headers()
            for chunk in [{"choices": [{"delta": {"content": "Hi."}, "finish_reason": "stop"}]}, {"choices": [], "usage": {"prompt_tokens": 12000, "completion_tokens": 40}}]:
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

    web = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    settings.provider, settings.compat_model = "openai_compatible", "m"
    settings.compat_base_url = f"http://127.0.0.1:{web.server_port}/v1"
    monkeypatch.setenv("JARVIS_API_KEY", "k" * 12)
    j = Jarvis(settings, registry, ActionLog(settings.action_log_path), kill)
    assert j.send("hi", FakeUI()) == "done"
    assert "stream_options" in seen[0] and "stream_options" not in seen[1]  # retried without, and remembered
    j.brain._ask_usage = True  # (a service that does report)
    j.send("again", FakeUI())
    assert j.brain.last_usage == {"input": 12000, "output": 40} and j.context_tokens == 12040
    assert j.allowance()["limit"] == 10_000_000 and j.allowance()["used"] == 600_000
    web.shutdown()


# -------------------------------------------------- personal settings file


def test_settings_local_file_is_layered_on_top(tmp_path):
    (tmp_path / "settings.toml").write_text(f'[assistant]\nlocation = "Sharjah"\nmax_steps = 40\n[paths]\nhome = "{(tmp_path / "h").as_posix()}"\n[voice]\nwake_word = true\nwake_threshold = 0.5\n')
    assert load_settings(tmp_path / "settings.toml").location == "Sharjah"
    (tmp_path / "settings.local.toml").write_text('[assistant]\nlocation = "Dubai"\n[voice]\nwake_threshold = 0.7\n')
    s = load_settings(tmp_path / "settings.toml")
    assert s.location == "Dubai" and s.wake_threshold == 0.7
    assert s.max_steps == 40 and s.wake_word is True  # everything else is untouched


def test_settings_local_is_ignored_by_git():
    from jarvis.core.config import REPO_ROOT

    assert "settings.local.toml" in (REPO_ROOT / ".gitignore").read_text().split()


# -------------------------------------------------------------- updating


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """A 'GitHub' repository and a clone of it standing in for the Jarvis folder."""
    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout

    origin, clone = tmp_path / "origin", tmp_path / "clone"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    git(origin, "config", "user.email", "t@example.com"), git(origin, "config", "user.name", "T")
    (origin / "settings.toml").write_text("a = 1\n")
    git(origin, "add", "-A"), git(origin, "commit", "-q", "-m", "first")
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    monkeypatch.setattr(updater, "REPO_ROOT", clone)
    installs = []
    real_run = updater._run
    monkeypatch.setattr(updater, "_run", lambda args, timeout: installs.append(args) or "" if "pip" in args else real_run(args, timeout))

    def publish(message, **files):
        for name, content in files.items():
            (origin / name).write_text(content)
        git(origin, "add", "-A"), git(origin, "commit", "-q", "-m", message)

    return SimpleNamespace(origin=origin, clone=clone, publish=publish, installs=installs)


def test_update_check_and_apply(repos):
    assert updater.check()["behind"] == 0
    repos.publish("Add a new feature", **{"feature.py": "x = 1\n"})
    repos.publish("Fix a bug", **{"feature.py": "x = 2\n"})
    info = updater.check()
    assert info["behind"] == 2 and info["changes"] == ["Fix a bug", "Add a new feature"] and info["local_changes"] == []
    assert not (repos.clone / "feature.py").exists()  # checking changes nothing

    result = updater.apply()
    assert result["changed"] and result["from"] != result["to"]
    assert (repos.clone / "feature.py").read_text() == "x = 2\n"
    install = repos.installs[0]
    assert install[1:4] == ["-m", "pip", "install"] and install[-2] == "-e" and install[-1].startswith(".")
    assert "dev" in result["extras"]  # pytest is installed here, so the dev extra is kept
    assert updater.check()["behind"] == 0 and updater.apply()["changed"] is False


def test_update_refuses_rather_than_overwrite_your_edits(repos):
    (repos.clone / "settings.toml").write_text("a = 1\nmine = true\n")
    repos.publish("Change the settings file", **{"settings.toml": "a = 2\n"})
    assert updater.check()["local_changes"] == ["settings.toml"]
    with pytest.raises(updater.UpdateError, match="settings.local.toml"):
        updater.apply()
    assert (repos.clone / "settings.toml").read_text() == "a = 1\nmine = true\n"  # untouched
    assert repos.installs == []


def test_update_explains_a_folder_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "REPO_ROOT", tmp_path)
    with pytest.raises(updater.UpdateError, match="not installed with git"):
        updater.check()


# ------------------------------------------------------- window endpoints


def test_window_endpoints(settings, kill, registry, monkeypatch):
    j, _ = make(settings, kill, registry, reply(text("Hello, Sir.")))
    j.brain.last_usage = {"input": 5000, "output": 20}
    j.send("hi", FakeUI())
    app = server.create_app(j, token="tok")
    c = TestClient(app)
    for path in ("/api/conversation", "/api/update"):
        assert c.get(path).status_code == 403
    assert c.post("/api/update").status_code == 403 and c.post("/api/restart").status_code == 403

    items = c.get("/api/conversation", headers=HEADERS).json()["items"]
    assert [(i["type"], i["text"]) for i in items] == [("user", "hi"), ("reply", "Hello, Sir.")]
    usage = c.get("/api/status", headers=HEADERS).json()["usage"]
    assert usage["used"] == 5020 and usage["limit"] == 10_000_000 and usage["context"] == 5020 and usage["context_budget"] == 40000

    monkeypatch.setattr(updater, "check", lambda: {"version": "1.0", "behind": 1, "changes": ["New"], "local_changes": []})
    assert c.get("/api/update", headers=HEADERS).json() == {"version": "1.0", "behind": 1, "changes": ["New"], "local_changes": [], "can_restart": False}
    monkeypatch.setattr(updater, "apply", lambda: (_ for _ in ()).throw(updater.UpdateError("edited files")))
    r = c.post("/api/update", headers=HEADERS)
    assert r.status_code == 400 and "edited files" in r.json()["detail"]
    assert c.post("/api/restart", headers=HEADERS).status_code == 400  # no window to restart in a browser

    restarted = []
    app.state.restart = lambda: restarted.append(True)
    assert c.post("/api/restart", headers=HEADERS).status_code == 200
    import time

    time.sleep(0.6)
    assert restarted == [True]


def test_spoken_flag_and_notices_travel_through_the_window(settings, kill, registry):
    j, _ = make(settings, kill, registry, reply(text("One.")), reply(text("Two.")))
    j.brain.last_usage = {"input": 50_000, "output": 10}  # over the 40k budget after the first reply
    c = TestClient(server.create_app(j, token="tok"))
    with c.websocket_connect("/ws?token=tok", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"type": "user", "text": "hello", "spoken": True})
        while ws.receive_json()["type"] != "done":
            pass
        ws.send_json({"type": "user", "text": "more"})
        kinds = []
        while True:
            m = ws.receive_json()
            kinds.append(m["type"])
            if m["type"] == "done":
                break
        assert kinds[0] == "notice"  # the window is told the conversation was condensed
    assert j.conversation.view()[0]["spoken"] is True
