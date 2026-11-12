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


# ------------------------------------------------------------- wake word


class StubListener:
    fed = 0  # how many chunks the server has examined

    def __init__(self, settings):
        pass

    def feed(self, pcm):
        StubListener.fed += 1
        return pcm == b"hey jarvis"


def _wake(client, token="tok", origin="http://testserver"):
    return client.websocket_connect(f"/ws/wake?token={token}", headers={"origin": origin})


def _wait_until(condition, seconds=5):
    import time

    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_wake_socket_reports_detections_and_logs_them(make_jarvis, monkeypatch):
    from jarvis.voice import wake

    monkeypatch.setattr(wake, "WakeListener", StubListener)
    StubListener.fed = 0
    j, _ = make_jarvis()
    c = TestClient(server.create_app(j, token="tok"))
    with _wake(c) as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(b"background chatter")
        ws.send_bytes(b"hey jarvis")
        assert ws.receive_json() == {"type": "wake"}  # the chatter produced nothing
        # While the emergency stop is engaged, the wake word does nothing.
        j.kill.trip()
        ws.send_bytes(b"hey jarvis")
        ws.send_bytes(b"background chatter")
        # Chunks are handled one after another, so once the fourth has been
        # examined the third (heard while stopped) is completely finished.
        _wait_until(lambda: StubListener.fed == 4)
        j.kill.reset()
        ws.send_bytes(b"hey jarvis")
        assert ws.receive_json() == {"type": "wake"}
    assert [e["event"] for e in j.log.tail(5)].count("wake_word") == 2


def test_wake_socket_requires_token_and_own_origin(make_jarvis):
    from starlette.websockets import WebSocketDisconnect

    j, _ = make_jarvis()
    c = TestClient(server.create_app(j, token="tok"))
    for token, origin in [("wrong", "http://testserver"), ("tok", "http://evil.example")]:
        with pytest.raises(WebSocketDisconnect):
            with _wake(c, token, origin) as ws:
                ws.receive_json()


def test_wake_socket_says_when_unavailable(make_jarvis, monkeypatch):
    from jarvis.voice import wake

    def broken(settings):
        raise wake.WakeUnavailable("not installed")

    monkeypatch.setattr(wake, "WakeListener", broken)
    j, _ = make_jarvis()
    with _wake(TestClient(server.create_app(j, token="tok"))) as ws:
        assert ws.receive_json() == {"type": "unavailable", "detail": "not installed"}


def test_real_detector_ignores_silence_and_noise(settings):
    np = pytest.importorskip("numpy")
    pytest.importorskip("openwakeword")
    from jarvis.voice import wake

    if not wake.models_present():
        pytest.skip("wake-word model not downloaded")
    listener = wake.WakeListener(settings)
    assert listener.feed(np.zeros(32000, np.int16).tobytes()) is False
    noise = (np.random.default_rng(0).normal(0, 800, 32000)).astype(np.int16)
    assert listener.feed(noise.tobytes()) is False
    assert listener.feed(b"\x01") is False  # an odd-length scrap must not crash it
