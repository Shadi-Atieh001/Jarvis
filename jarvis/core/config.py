"""Loads settings.toml into a plain Settings object.

Settings are looked up in this order:
  1. the path in the JARVIS_SETTINGS environment variable, if set
  2. settings.toml in the current directory
  3. settings.toml next to the jarvis package (the repository root)
Anything missing from the file falls back to the defaults below.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    address_as: str = "Sir"
    model: str = "claude-fable-5-2"
    effort: str = "medium"
    refusal_fallback: bool = True
    max_steps: int = 40
    location: str = "Sharjah"

    provider: str = "anthropic"  # "anthropic" or "ollama"
    ollama_model: str = "qwen3:8b"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_context_window: int = 8192
    ollama_think: bool = False

    memory_enabled: bool = True
    voice_enabled: bool = True
    whisper_model: str = "base.en"
    piper_voice: str = "en_GB-alan-medium"
    speak_replies: str = "when_spoken"  # when_spoken | always | never
    wake_word: bool = True
    wake_threshold: float = 0.5

    compat_base_url: str = ""
    compat_model: str = ""
    compat_api_key_env: str = "JARVIS_API_KEY"
    ollama_keep_alive: str = "30m"

    home: Path = Path("~/.jarvis")
    workspace: Path = Path("~/.jarvis/workspace")

    permission_mode: str = "careful"  # careful | trusted | unrestricted
    default_tier: str = "confirm"
    confirm_after_untrusted: bool = True
    tool_tiers: dict[str, str] = field(default_factory=dict)
    sensitive_paths: list[str] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)

    @property
    def action_log_path(self) -> Path:
        return self.home / "actions.jsonl"

    @property
    def stop_file(self) -> Path:
        return self.home / "STOP"


def find_settings_file() -> Path | None:
    candidates = []
    if os.environ.get("JARVIS_SETTINGS"):
        candidates.append(Path(os.environ["JARVIS_SETTINGS"]))
    candidates += [Path.cwd() / "settings.toml", REPO_ROOT / "settings.toml"]
    return next((p for p in candidates if p.is_file()), None)


def load_settings(path: Path | None = None) -> Settings:
    path = path or find_settings_file()
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path else {}

    assistant = data.get("assistant", {})
    paths = data.get("paths", {})
    perms = data.get("permissions", {})

    s = Settings()
    for key in ("address_as", "provider", "model", "effort", "refusal_fallback", "max_steps", "location"):
        if key in assistant:
            setattr(s, key, assistant[key])

    ollama = data.get("ollama", {})
    s.ollama_model = ollama.get("model", s.ollama_model)
    s.ollama_host = ollama.get("host", s.ollama_host)
    s.ollama_context_window = ollama.get("context_window", s.ollama_context_window)
    s.ollama_think = ollama.get("think", s.ollama_think)
    s.ollama_keep_alive = ollama.get("keep_alive", s.ollama_keep_alive)

    s.memory_enabled = data.get("memory", {}).get("enabled", s.memory_enabled)
    voice = data.get("voice", {})
    s.voice_enabled = voice.get("enabled", s.voice_enabled)
    s.whisper_model = voice.get("whisper_model", s.whisper_model)
    s.piper_voice = voice.get("piper_voice", s.piper_voice)
    s.speak_replies = voice.get("speak_replies", s.speak_replies)
    s.wake_word = voice.get("wake_word", s.wake_word)
    s.wake_threshold = voice.get("wake_threshold", s.wake_threshold)

    compat = data.get("openai_compatible", {})
    s.compat_base_url = compat.get("base_url", s.compat_base_url)
    s.compat_model = compat.get("model", s.compat_model)
    s.compat_api_key_env = compat.get("api_key_env", s.compat_api_key_env)

    s.home = _expand(paths.get("home", s.home))
    s.workspace = _expand(paths.get("workspace", s.workspace))

    s.permission_mode = perms.get("mode", s.permission_mode)
    s.default_tier = perms.get("default", s.default_tier)
    s.confirm_after_untrusted = perms.get("confirm_after_untrusted", s.confirm_after_untrusted)
    s.tool_tiers = dict(perms.get("tools", {}))
    s.sensitive_paths = list(perms.get("sensitive", {}).get("paths", []))
    s.blocked_patterns = list(perms.get("blocked", {}).get("patterns", []))

    s.home.mkdir(parents=True, exist_ok=True)
    s.workspace.mkdir(parents=True, exist_ok=True)
    return s


def _expand(p: str | Path) -> Path:
    return Path(os.path.expandvars(str(p))).expanduser().resolve()
