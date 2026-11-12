"""The "Hey Jarvis" wake word, using openWakeWord.

The window streams microphone audio to this machine's own JARVIS server,
which runs a small detector over it. Audio is examined in memory and thrown
away; nothing is stored or sent anywhere. Only a detection (yes/no) leaves
this module.
"""

from __future__ import annotations

import os
import time

from jarvis.core.config import Settings

FRAME = 1280  # samples per detector step: 80 ms at 16 kHz
WAKE_NAME = "hey_jarvis"


class WakeUnavailable(Exception):
    pass


def available() -> bool:
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        return False
    return True


def _models_dir() -> str:
    import openwakeword

    return os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")


def models_present() -> bool:
    return available() and os.path.exists(os.path.join(_models_dir(), f"{WAKE_NAME}_v0.1.onnx"))


def download_models(report=print) -> None:
    """Newer versions of the library fetch their models separately (a few MB)."""
    if models_present():
        return
    from openwakeword import utils

    if not hasattr(utils, "download_models"):
        raise WakeUnavailable("The wake-word model is missing from the openwakeword package.")
    report("Downloading the wake-word model ...")
    utils.download_models(model_names=[WAKE_NAME])


def _load_model():
    try:
        from openwakeword.model import Model
    except ImportError:
        raise WakeUnavailable('Install the voice libraries with:  pip install -e ".[voice]"') from None
    path = os.path.join(_models_dir(), f"{WAKE_NAME}_v0.1.onnx")
    if not os.path.exists(path):
        raise WakeUnavailable("The wake-word model is not downloaded. Run:  python -m jarvis voice-setup")
    try:  # newer versions of the library
        return Model(wakeword_models=[path], inference_framework="onnx")
    except TypeError:  # older versions, which take different argument names
        return Model(wakeword_model_paths=[path])


class WakeListener:
    """One per open window. Feed it raw audio; it says when it heard the phrase."""

    def __init__(self, settings: Settings):
        import numpy as np

        self._np = np
        self.threshold = settings.wake_threshold
        self.model = _load_model()
        self._pending = np.zeros(0, dtype=np.int16)
        self._quiet_until = 0.0

    def feed(self, pcm: bytes) -> bool:
        """pcm: 16-bit mono 16 kHz samples. Returns True on a detection."""
        np = self._np
        self._pending = np.concatenate([self._pending, np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)])
        heard = False
        while len(self._pending) >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            score = max(self.model.predict(frame).values())
            if score >= self.threshold and time.monotonic() >= self._quiet_until:
                heard = True
                # Ignore the echo of the same utterance for a moment.
                self._quiet_until = time.monotonic() + 2.0
                self.model.reset()
        return heard
