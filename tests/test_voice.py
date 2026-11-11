"""Voice tests. The speech models are not needed: the server tests swap in
a stand-in, and the rest covers the pure-Python parts."""

import io
import wave

import pytest
from fastapi.testclient import TestClient

from jarvis.ui import server
from jarvis.voice.engine import Voice, VoiceUnavailable, speakable

from .conftest import reply, text

HEADERS = {"x-jarvis-token": "tok", "origin": "http://testserver"}


def test_speakable_strips_what_should_not_be_read():
    assert speakable("**Done**, Sir. See `notes.txt`.") == "Done , Sir. See notes.txt."
    assert speakable("Here:\n```python\nprint(1)\n```\nThat is all.") == "Here: That is all."
    assert speakable("Read [the docs](https://example.com/x) or https://example.com") == "Read the docs or a link"
    assert speakable("```\nonly code\n```") == ""


def test_status_when_switched_off(settings):
    settings.voice_enabled = False
    status = Voice(settings).status()
    assert status["listen"] is False and status["speak"] is False
    with pytest.raises(VoiceUnavailable):
        Voice(settings).transcribe(b"x")


def test_status_reports_missing_voice_download(settings):
    status = Voice(settings).status()
    assert status["speak"] is False and status["problems"]  # nothing downloaded in the test folder


def test_wav_decoding():
    np = pytest.importorskip("numpy")
    from jarvis.voice.engine import wav_to_samples

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(32000)
        w.writeframes(np.array([[16384, 16384]] * 3200, dtype=np.int16).tobytes())
    samples = wav_to_samples(buffer.getvalue())
    assert samples.dtype == np.float32 and len(samples) == 1600  # stereo 32 kHz -> mono 16 kHz
    assert abs(float(samples.mean()) - 0.5) < 0.01
    with pytest.raises(VoiceUnavailable):
        wav_to_samples(b"this is not audio")


class StubVoice:
    def __init__(self, settings):
        self.fail = False

    def status(self):
        return {"listen": True, "speak": True, "problems": []}

    def transcribe(self, audio):
        if self.fail:
            raise VoiceUnavailable("not installed")
        return f"heard {len(audio)} bytes"

    def speak(self, text_):
        return b"RIFF" + text_.encode()


@pytest.fixture
def client(make_jarvis, monkeypatch):
    monkeypatch.setattr(server, "Voice", StubVoice)
    j, _ = make_jarvis(reply(text("hi")))
    return TestClient(server.create_app(j, token="tok"))


def test_info(client):
    data = client.get("/api/info", headers=HEADERS).json()
    assert data["address"] == "Sir" and data["voice"]["listen"] and data["speak_replies"] == "when_spoken"
    assert data["model"] == "claude-fable-5-2"


def test_voice_endpoints_require_token_and_own_origin(client):
    for headers in [{}, {"x-jarvis-token": "wrong"}, {"x-jarvis-token": "tok", "origin": "http://evil.example"}]:
        assert client.get("/api/info", headers=headers).status_code == 403
        assert client.post("/api/transcribe", content=b"abc", headers=headers).status_code == 403
        assert client.post("/api/speak", json={"text": "hi"}, headers=headers).status_code == 403


def test_transcribe_and_speak(client):
    assert client.post("/api/transcribe", content=b"12345", headers=HEADERS).json() == {"text": "heard 5 bytes"}
    assert client.post("/api/transcribe", content=b"", headers=HEADERS).status_code == 400
    r = client.post("/api/speak", json={"text": "Good evening"}, headers=HEADERS)
    assert r.headers["content-type"] == "audio/wav" and r.content == b"RIFFGood evening"


def test_unavailable_voice_is_reported(make_jarvis, monkeypatch):
    class Broken(StubVoice):
        def transcribe(self, audio):
            raise VoiceUnavailable("Install the voice libraries")

    monkeypatch.setattr(server, "Voice", Broken)
    j, _ = make_jarvis()
    c = TestClient(server.create_app(j, token="tok"))
    r = c.post("/api/transcribe", content=b"abc", headers=HEADERS)
    assert r.status_code == 503 and "Install" in r.json()["detail"]
