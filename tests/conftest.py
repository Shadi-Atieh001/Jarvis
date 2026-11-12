"""Shared test fixtures. No test talks to the real API: FakeClient plays
back scripted model responses."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.core.actionlog import ActionLog
from jarvis.core.agent import Jarvis
from jarvis.core.config import REPO_ROOT, load_settings
from jarvis.core.killswitch import KillSwitch
from jarvis.core.tools import ToolContext, load_tools


def text(t):
    return SimpleNamespace(type="text", text=t)


def call(name, input, id=None):
    call.n += 1
    return SimpleNamespace(type="tool_use", name=name, input=input, id=id or f"toolu_{call.n}")


call.n = 0


def reply(*blocks, stop_reason=None):
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class _Stream:
    def __init__(self, response):
        self.response = response
        self.text_stream = [b.text for b in response.content if b.type == "text"]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


class FakeClient:
    """Stands in for anthropic.Anthropic(). Records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **request):
        # Snapshot the history as it was when the request was made.
        self.requests.append({**request, "messages": list(request["messages"])})
        if not self.responses:
            raise AssertionError("The model was called more times than the test scripted.")
        return _Stream(self.responses.pop(0))


class FakeUI:
    def __init__(self, approve=True):
        self.approve = approve
        self.text = ""
        self.tools = []      # (name, decision)
        self.confirms = []   # (name, Decision)

    def on_text(self, delta):
        self.text += delta

    def on_tool(self, name, decision, summary):
        self.tools.append((name, decision))

    def confirm(self, tool_name, decision):
        self.confirms.append((tool_name, decision))
        return self.approve(tool_name, decision) if callable(self.approve) else self.approve


@pytest.fixture
def settings(tmp_path):
    s = load_settings(REPO_ROOT / "settings.toml")  # the real, shipped settings
    s.provider = "anthropic"  # tests script the model through FakeClient
    s.permission_mode = "careful"  # the strictest mode; other modes are tested explicitly
    s.home = tmp_path / "home"
    s.workspace = (tmp_path / "home" / "workspace").resolve()
    s.workspace.mkdir(parents=True)
    return s


@pytest.fixture
def kill(settings):
    return KillSwitch(settings.stop_file)


@pytest.fixture
def ctx(settings, kill):
    return ToolContext(settings=settings, kill=kill)


@pytest.fixture
def registry():
    return load_tools()


@pytest.fixture
def make_jarvis(settings, kill, registry):
    def make(*responses):
        client = FakeClient(responses)
        j = Jarvis(settings, registry, ActionLog(settings.action_log_path), kill, client=client)
        return j, client

    return make


def tool_results(client, request_index=-1):
    """The tool_result blocks sent to the model in a given request."""
    msg = client.requests[request_index]["messages"][-1]
    assert msg["role"] == "user"
    return msg["content"]
