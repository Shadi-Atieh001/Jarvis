"""Builds a ready-to-use Jarvis from settings. Shared by every interface."""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.core.actionlog import ActionLog
from jarvis.core.agent import Jarvis
from jarvis.core.config import Settings, load_settings
from jarvis.core.killswitch import KillSwitch
from jarvis.core.tools import load_tools


def build(settings_path: Path | None = None, client=None) -> Jarvis:
    settings: Settings = load_settings(settings_path)
    log = ActionLog(settings.action_log_path)
    kill = KillSwitch(settings.stop_file)
    return Jarvis(settings, load_tools(), log, kill, client=client)


def startup_problem(settings: Settings | None = None) -> str | None:
    """Returns a message if the chosen brain cannot run, else None."""
    settings = settings or load_settings()
    if settings.provider == "ollama":
        from jarvis.core.brains import OllamaBrain

        return OllamaBrain(settings).check()
    if settings.provider == "openai_compatible":
        from jarvis.core.brains import OpenAICompatBrain

        return OpenAICompatBrain(settings).check()
    if settings.provider != "anthropic":
        return f'Unknown provider {settings.provider!r} in settings.toml. Use "ollama", "openai_compatible" or "anthropic".'
    if os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return (
        "ANTHROPIC_API_KEY is not set. In Command Prompt or PowerShell, set it once with:\n"
        '  setx ANTHROPIC_API_KEY "your-key-here"\n'
        "then open a new terminal and start JARVIS again.\n"
        'To run free on a local model instead, set provider = "ollama" in settings.toml.'
    )
