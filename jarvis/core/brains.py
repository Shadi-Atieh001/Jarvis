"""The model backends ("brains"). The agent loop talks to one of these and
does not care which.

  AnthropicBrain   Claude through the Anthropic API (paid, most capable)
  OllamaBrain      a model running on this machine through Ollama (free)

Both take the same conversation history and return a Reply: a list of
content blocks (text and tool calls) plus a stop reason. The history is kept
in Anthropic's message format; OllamaBrain translates it on each request.

Choose one with `provider` in settings.toml.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from .config import Settings
from .killswitch import KillSwitch

MAX_TOKENS = 32000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Reply:
    content: list  # blocks with .type == "text" (.text) or "tool_use" (.id, .name, .input)
    stop_reason: str  # end_turn | tool_use | max_tokens | refusal | pause_turn


class BrainError(Exception):
    """A problem the user can act on (model missing, server not running)."""


# ---------------------------------------------------------------- Anthropic


class AnthropicBrain:
    name = "anthropic"

    def __init__(self, settings: Settings, client: Any = None):
        self.settings = settings
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            # Reads ANTHROPIC_API_KEY from the environment. The key is never
            # passed around, stored or logged by JARVIS.
            self._client = anthropic.Anthropic()
        return self._client

    def respond(self, system: str, tools: list[dict], messages: list[dict], on_text: Callable[[str], None], kill: KillSwitch):
        request: dict[str, Any] = dict(
            model=self.settings.model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": self.settings.effort},
            cache_control={"type": "ephemeral"},  # reuse the unchanged prefix
        )
        if self.settings.refusal_fallback:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"

        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                with self.client.beta.messages.stream(**request) as stream:
                    for delta in stream.text_stream:
                        kill.check()
                        on_text(delta)
                    return stream.get_final_message()
            except ValueError as exc:
                # The SDK raises ValueError when a streamed tool input is not
                # valid JSON. Ask again once; API errors are not caught here.
                last_error = exc
        raise RuntimeError(f"The model sent malformed tool input twice: {last_error}")


# ------------------------------------------------------------------- Ollama


class OllamaBrain:
    """Talks to a local Ollama server (https://ollama.com) over its HTTP API.
    Uses only the Python standard library."""

    name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.host = settings.ollama_host.rstrip("/")

    def respond(self, system: str, tools: list[dict], messages: list[dict], on_text: Callable[[str], None], kill: KillSwitch):
        body = {
            "model": self.settings.ollama_model,
            "messages": [{"role": "system", "content": system}, *to_ollama_messages(messages)],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
                }
                for t in tools
            ],
            "stream": True,
            # Ollama's default context window is small; the system prompt and
            # tool list alone would nearly fill it.
            "options": {"num_ctx": self.settings.ollama_context_window},
        }
        text_parts: list[str] = []
        calls: list[SimpleNamespace] = []
        done_reason = "stop"

        with self._post("/api/chat", body) as response:
            for line in response:  # one JSON object per line
                kill.check()
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise BrainError(self._explain(str(chunk["error"])))
                message = chunk.get("message") or {}
                if message.get("content"):
                    text_parts.append(message["content"])
                    on_text(message["content"])
                for tc in message.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):  # some models send JSON text
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"_unparseable": args}  # fails validation, model is told
                    calls.append(
                        SimpleNamespace(
                            type="tool_use",
                            id=f"local_{uuid.uuid4().hex[:12]}",  # Ollama gives calls no id
                            name=str(fn.get("name", "")),
                            input=args if args is not None else {},
                        )
                    )
                if chunk.get("done"):
                    done_reason = chunk.get("done_reason") or "stop"

        content: list = []
        if text_parts:
            content.append(SimpleNamespace(type="text", text="".join(text_parts)))
        content.extend(calls)
        if done_reason == "length":
            stop = "max_tokens"
        else:
            stop = "tool_use" if calls else "end_turn"
        return Reply(content, stop)

    # -- helpers

    def _post(self, path: str, body: dict):
        request = urllib.request.Request(
            self.host + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            # Generous timeout: the first request loads the model into memory.
            return urllib.request.urlopen(request, timeout=600)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except json.JSONDecodeError:
                pass
            raise BrainError(self._explain(str(detail))) from None
        except urllib.error.URLError as exc:
            raise BrainError(
                f"Cannot reach Ollama at {self.host} ({exc.reason}). Is Ollama running? "
                "Start it from the Start menu, or run 'ollama serve'."
            ) from None

    def _explain(self, error: str) -> str:
        model = self.settings.ollama_model
        lowered = error.lower()
        if "not found" in lowered:
            return f"Ollama does not have the model {model!r}. Download it with:  ollama pull {model}"
        if "does not support tools" in lowered:
            return (
                f"The model {model!r} cannot call tools, which JARVIS needs. "
                "Pick one from https://ollama.com/search?c=tool and set it in settings.toml."
            )
        return f"Ollama reported an error: {error}"

    def check(self) -> str | None:
        """Returns a message if Ollama is not ready, else None."""
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=5) as response:
                installed = [m.get("name", "") for m in json.load(response).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return (
                f"Cannot reach Ollama at {self.host}.\n"
                "Install it from https://ollama.com/download, make sure it is running, then try again."
            )
        model = self.settings.ollama_model
        wanted = model if ":" in model else model + ":latest"
        if wanted not in installed:
            return f"Ollama is running but does not have the model {model!r}. Download it with:\n  ollama pull {model}"
        return None


def to_ollama_messages(messages: list[dict]) -> list[dict]:
    """Translate the Anthropic-format history into Ollama's chat format."""
    out: list[dict] = []
    names: dict[str, str] = {}  # tool call id -> tool name, for the results
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": msg["role"], "content": content})
            continue
        if msg["role"] == "assistant":
            text = "".join(b.text for b in content if getattr(b, "type", None) == "text")
            calls = [b for b in content if getattr(b, "type", None) == "tool_use"]
            entry: dict = {"role": "assistant", "content": text}
            if calls:
                entry["tool_calls"] = [{"function": {"name": c.name, "arguments": c.input}} for c in calls]
                names.update({c.id: c.name for c in calls})
            out.append(entry)
        else:  # a user message carrying tool results
            for block in content:
                if block.get("type") == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "content": str(block.get("content", "")),
                            "tool_name": names.get(block.get("tool_use_id"), ""),
                        }
                    )
    return out


def make_brain(settings: Settings, client: Any = None):
    if client is not None or settings.provider == "anthropic":
        return AnthropicBrain(settings, client)
    if settings.provider == "ollama":
        return OllamaBrain(settings)
    raise BrainError(f"Unknown provider {settings.provider!r} in settings.toml. Use \"anthropic\" or \"ollama\".")
