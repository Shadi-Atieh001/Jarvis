"""Builds a ready-to-use Jarvis from settings. Shared by every interface."""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.core.actionlog import ActionLog
from jarvis.core.agent import Jarvis
from jarvis.core.config import Settings, load_settings
from jarvis.core.conversation import Conversation
from jarvis.core.killswitch import KillSwitch
from jarvis.core.tools import load_tools


def build(settings_path: Path | None = None, client=None) -> Jarvis:
    settings: Settings = load_settings(settings_path)
    log = ActionLog(settings.action_log_path)
    kill = KillSwitch(settings.stop_file)
    conversation = Conversation(settings.home / "conversation.json")  # survives a restart
    return Jarvis(settings, load_tools(), log, kill, client=client, conversation=conversation)


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
    from jarvis.core.brains import stored_key

    if os.environ.get("ANTHROPIC_API_KEY") or stored_key("anthropic.key"):
        return None
    return "No Anthropic API key has been entered yet."
