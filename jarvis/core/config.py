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

    home: Path = Path("~/.jarvis")
    workspace: Path = Path("~/.jarvis/workspace")

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
    for key in ("address_as", "model", "effort", "refusal_fallback", "max_steps", "location"):
        if key in assistant:
            setattr(s, key, assistant[key])

    s.home = _expand(paths.get("home", s.home))
    s.workspace = _expand(paths.get("workspace", s.workspace))

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
