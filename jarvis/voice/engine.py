"""Speech in and speech out, both local.

  Listening  faster-whisper turns recorded audio into text.
  Speaking   Piper turns text into a WAV using a British voice.

The window records from the microphone and plays the audio; this module only
converts between audio and text. Nothing is sent over the internet except
the one-time model downloads (python -m jarvis voice-setup).

Both libraries are optional. If they are missing, JARVIS still works by
typing, and status() says what to install.
"""

from __future__ import annotations

import io
import re
import sys
import threading
import urllib.request
import wave
from pathlib import Path

from jarvis.core.config import Settings

PIPER_VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


class VoiceUnavailable(Exception):
    """Voice cannot run; the message says what to do about it."""


def _install_hint() -> str:
    hint = 'Install the voice libraries with:  pip install -e ".[voice]"'
    if sys.version_info >= (3, 15):
        hint += (
            "\nNote: this is Python %d.%d, which the speech libraries do not support yet. "
            "Recreate the environment with Python 3.14 (see the README, 'Voice')." % sys.version_info[:2]
        )
    return hint


class Voice:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.models_dir = settings.home / "models"
        self._whisper = None
        self._piper = None
        self._listen_lock = threading.Lock()
        self._speak_lock = threading.Lock()

    # ----------------------------------------------------------- readiness

    @property
    def voice_files(self) -> tuple[Path, Path]:
        name = self.settings.piper_voice
        folder = self.models_dir / "piper"
        return folder / f"{name}.onnx", folder / f"{name}.onnx.json"

    def status(self) -> dict:
        """What works, and what is missing. Loads nothing heavy."""
        problems = []
        listen = speak = self.settings.voice_enabled
        if not self.settings.voice_enabled:
            problems.append("Voice is switched off in settings.toml.")
        else:
            try:
                import faster_whisper  # noqa: F401
            except ImportError:
                listen = False
            try:
                import piper  # noqa: F401
            except ImportError:
                speak = False
            if not (listen and speak):
                problems.append(_install_hint())
            if speak and not all(f.exists() for f in self.voice_files):
                speak = False
                problems.append("The voice has not been downloaded. Run:  python -m jarvis voice-setup")
        return {"listen": listen, "speak": speak, "problems": problems}

    # ----------------------------------------------------------- listening

    def _load_whisper(self):
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise VoiceUnavailable(_install_hint()) from None
            # CPU with 8-bit weights: fast enough for short commands and
            # leaves the graphics card free. Downloads the model on first use.
            self._whisper = WhisperModel(
                self.settings.whisper_model,
                device="cpu",
                compute_type="int8",
                download_root=str(self.models_dir / "whisper"),
            )
        return self._whisper

    def transcribe(self, audio: bytes) -> str:
        """A WAV recording -> text."""
        if not self.settings.voice_enabled:
            raise VoiceUnavailable("Voice is switched off in settings.toml.")
        with self._listen_lock:
            model = self._load_whisper()
            segments, _info = model.transcribe(
                wav_to_samples(audio),
                language="en",
                beam_size=3,
                vad_filter=True,  # drop silence, which otherwise causes invented words
                initial_prompt="Jarvis,",  # helps it spell the name
            )
            return " ".join(s.text.strip() for s in segments).strip()

    # ------------------------------------------------------------ speaking

    def _load_piper(self):
        if self._piper is None:
            try:
                from piper import PiperVoice
            except ImportError:
                raise VoiceUnavailable(_install_hint()) from None
            model, config = self.voice_files
            if not (model.exists() and config.exists()):
                raise VoiceUnavailable("The voice has not been downloaded. Run:  python -m jarvis voice-setup")
            self._piper = PiperVoice.load(str(model), config_path=str(config))
        return self._piper

    def speak(self, text: str) -> bytes:
        """Text -> WAV file bytes. Returns b'' if there is nothing to say."""
        if not self.settings.voice_enabled:
            raise VoiceUnavailable("Voice is switched off in settings.toml.")
        text = speakable(text)
        if not text:
            return b""
        with self._speak_lock:
            voice = self._load_piper()
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                voice.synthesize_wav(text, wav)
            return buffer.getvalue()

    # --------------------------------------------------------------- setup

    def download_voice(self, report=print) -> None:
        name = self.settings.piper_voice  # e.g. en_GB-alan-medium
        match = re.fullmatch(r"([a-z]{2})_([A-Z]{2})-(.+)-(x_low|low|medium|high)", name)
        if not match:
            raise VoiceUnavailable(f"{name!r} is not a Piper voice name such as en_GB-alan-medium.")
        lang, region, speaker, quality = match.groups()
        base = f"{PIPER_VOICES_URL}/{lang}/{lang}_{region}/{speaker}/{quality}"
        for target in self.voice_files:
            if target.exists() and target.stat().st_size > 0:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            report(f"Downloading {target.name} ...")
            partial = target.with_suffix(target.suffix + ".part")
            urllib.request.urlretrieve(f"{base}/{target.name}", partial)
            partial.replace(target)


def wav_to_samples(data: bytes):
    """Decode a 16-bit WAV into the mono 16 kHz float array Whisper expects.
    Done here with numpy so no audio-decoding library is involved."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise VoiceUnavailable(f"The recording was not a readable WAV file ({exc}).") from None
    if width != 2:
        raise VoiceUnavailable("The recording must be 16-bit audio.")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != 16000 and len(samples):
        positions = np.linspace(0, len(samples) - 1, int(len(samples) * 16000 / rate))
        samples = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)
    return samples


def speakable(text: str) -> str:
    """Strip what should not be read aloud: code, markup, links, paths."""
    text = re.sub(r"```.*?(```|$)", " ", text, flags=re.DOTALL)  # code blocks
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_#>|]+", " ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def setup(settings: Settings, report=print) -> int:
    """python -m jarvis voice-setup: download the models and prove they work."""
    voice = Voice(settings)
    if not settings.voice_enabled:
        report("Voice is switched off in settings.toml ([voice] enabled = false).")
        return 1
    try:
        import faster_whisper  # noqa: F401
        import piper  # noqa: F401
    except ImportError as exc:
        report(f"A voice library is missing ({exc.name}).\n{_install_hint()}")
        return 1
    try:
        voice.download_voice(report)
        report("Loading the voice ...")
        sample = voice.speak("Good evening, Sir. All systems are operational.")
        report(f"Loading speech recognition ({settings.whisper_model}; first run downloads about 150 MB) ...")
        heard = voice.transcribe(sample)
    except VoiceUnavailable as exc:
        report(str(exc))
        return 1
    except Exception as exc:
        report(f"Voice setup failed: {type(exc).__name__}: {exc}")
        return 1
    report(f'Self-test: JARVIS said a sentence and heard back: "{heard}"')
    if "operational" not in heard.lower():
        report("That does not match what was said, so recognition may be unreliable.")
        return 1
    report("Voice is ready. Start JARVIS and click the microphone.")
    return 0
