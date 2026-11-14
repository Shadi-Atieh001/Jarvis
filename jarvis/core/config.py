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
    context_budget: int = 40000  # tokens; beyond this the conversation is condensed
    daily_token_limit: int = 0  # the service's daily allowance, if known (0 = unknown)
    location: str = "Sharjah"

    provider: str = "anthropic"  # "anthropic" or "ollama"
    ollama_model: str = "qwen3:8b"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_context_window: int = 8192
    ollama_think: bool = False

    approved_sites: list = field(default_factory=list)  # websites where JARVIS may act without asking
    always_ask_sites: list = field(default_factory=list)  # patterns for sites that always ask (banking, payment)
    launcher: list = field(default_factory=list)  # quick-launch buttons: {"label", "open"}
    memory_enabled: bool = True
    voice_enabled: bool = True
    whisper_model: str = "base.en"
    piper_voice: str = "en_GB-alan-medium"
    speak_replies: str = "when_spoken"  # when_spoken | always | never
    sight: bool = True  # may JARVIS look at the screen when asked?
    sight_model: str = "gemini-3.5-flash-lite"
    follow_up: bool = True
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
    # Your own settings go in settings.local.toml, beside settings.toml. It
    # is layered on top, and git ignores it, so updates never clash with it.
    local = path.with_name("settings.local.toml") if path else None
    if local is not None and local.is_file():
        _merge(data, tomllib.loads(local.read_text(encoding="utf-8")))

    assistant = data.get("assistant", {})
    paths = data.get("paths", {})
    perms = data.get("permissions", {})

    s = Settings()
    for key in ("address_as", "provider", "model", "effort", "refusal_fallback", "max_steps", "location",
                "context_budget", "daily_token_limit"):
        if key in assistant:
            setattr(s, key, assistant[key])

    ollama = data.get("ollama", {})
    s.ollama_model = ollama.get("model", s.ollama_model)
    s.ollama_host = ollama.get("host", s.ollama_host)
    s.ollama_context_window = ollama.get("context_window", s.ollama_context_window)
    s.ollama_think = ollama.get("think", s.ollama_think)
    s.ollama_keep_alive = ollama.get("keep_alive", s.ollama_keep_alive)

    s.memory_enabled = data.get("memory", {}).get("enabled", s.memory_enabled)
    browser = data.get("browser", {})
    s.approved_sites = [str(x).lower() for x in browser.get("approved_sites", [])]
    s.always_ask_sites = [str(x) for x in browser.get("always_ask", [])]
    s.launcher = [
        {"label": str(i["label"]), "open": str(i["open"])}
        for i in data.get("launcher", {}).get("items", [])
        if isinstance(i, dict) and i.get("label") and i.get("open")
    ][:16]
    voice = data.get("voice", {})
    s.voice_enabled = voice.get("enabled", s.voice_enabled)
    s.whisper_model = voice.get("whisper_model", s.whisper_model)
    s.piper_voice = voice.get("piper_voice", s.piper_voice)
    s.speak_replies = voice.get("speak_replies", s.speak_replies)
    sight = data.get("sight", {})
    s.sight = sight.get("enabled", s.sight)
    s.sight_model = sight.get("model", s.sight_model)
    s.follow_up = voice.get("follow_up", s.follow_up)
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
    apply_overrides(s)
    return s


# Settings that can be changed from the control panel in the window. They
# are saved to <home>/overrides.json and take priority over settings.toml,
# which is never rewritten (so your comments and layout there are safe).
ADJUSTABLE = {
    "permission_mode": ("careful", "trusted", "unrestricted"),
    "speak_replies": ("when_spoken", "always", "never"),
    "wake_word": (True, False),
    "follow_up": (True, False),
    "sight": (True, False),
}


# What the setup screen can change: who you are and which model to use.
# Maps the name used in overrides.json to the Settings field.
PROFILE = {
    "address_as": "address_as",
    "location": "location",
    "provider": "provider",
    "base_url": "compat_base_url",
    "model": "compat_model",
    "ollama_model": "ollama_model",
    "claude_model": "model",
}
PROVIDERS = ("openai_compatible", "ollama", "anthropic")


def _valid_profile_value(key: str, value) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > 300 or "\n" in value:
        return False
    return value in PROVIDERS if key == "provider" else True


def save_profile(s: Settings, values: dict) -> None:
    """Apply and remember the setup screen's answers."""
    import json

    clean = {k: v.strip() for k, v in values.items() if k in PROFILE and _valid_profile_value(k, v)}
    path = overrides_path(s)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            saved = {}
    except (OSError, ValueError):
        saved = {}
    saved.update(clean)
    path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    for key, value in clean.items():
        setattr(s, PROFILE[key], value)


def _valid_site(site) -> bool:
    import re

    return isinstance(site, str) and bool(re.fullmatch(r"[a-z0-9.-]{3,200}", site)) and "." in site


def set_site_approval(s: Settings, site: str, approved: bool) -> None:
    """Add or remove a website from the approved list, now and for next time."""
    import json

    site = site.strip().lower()
    if not _valid_site(site):
        raise ValueError(f"{site!r} is not a website name.")
    path = overrides_path(s)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            saved = {}
    except (OSError, ValueError):
        saved = {}
    sites = [x for x in saved.get("approved_sites", []) if _valid_site(x) and x != site]
    s.approved_sites = [x for x in s.approved_sites if x != site]
    if approved:
        sites.append(site)
        s.approved_sites.append(site)
    saved["approved_sites"] = sites
    path.write_text(json.dumps(saved, indent=2), encoding="utf-8")


def overrides_path(s: Settings) -> Path:
    return s.home / "overrides.json"


def apply_overrides(s: Settings) -> None:
    import json

    try:
        saved = json.loads(overrides_path(s).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for key, value in saved.items() if isinstance(saved, dict) else []:
        if key in ADJUSTABLE and value in ADJUSTABLE[key]:
            setattr(s, key, value)
        elif key in PROFILE and _valid_profile_value(key, value):
            setattr(s, PROFILE[key], value.strip())
        elif key == "approved_sites" and isinstance(value, list):
            for site in value:
                if _valid_site(site) and site not in s.approved_sites:
                    s.approved_sites.append(site)


def save_override(s: Settings, key: str, value) -> None:
    """Change one adjustable setting now and remember it for next time."""
    import json

    if key not in ADJUSTABLE or value not in ADJUSTABLE[key]:
        raise ValueError(f"{key} cannot be set to {value!r}.")
    path = overrides_path(s)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            saved = {}
    except (OSError, ValueError):
        saved = {}
    saved[key] = value
    path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    setattr(s, key, value)


def _merge(base: dict, extra: dict) -> None:
    """Lay `extra` over `base`: tables are merged, anything else replaced."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def _expand(p: str | Path) -> Path:
    return Path(os.path.expandvars(str(p))).expanduser().resolve()
