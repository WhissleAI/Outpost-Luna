"""POST /v1/tts: Steer TTS Edge renders playable WAV, steering takes effect, the director plans. Skips without the model."""
import io
import wave

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tts_steer


@pytest.fixture(scope="module")
def client():
    tts_steer.load()
    if tts_steer.STATE["tts"] is None:
        pytest.skip(f"Steer TTS Edge not available: {tts_steer.STATE['error']}")
    app = FastAPI()
    app.include_router(tts_steer.router)
    with TestClient(app) as c:
        yield c


def _pcm(body: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(body)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767, w.getframerate()


def test_returns_playable_wav(client):
    r = client.post("/v1/tts", json={"text": "Copy, Commander. Shields to forty percent.", "voice": "voice_0213",
                                     "tag": "confidence", "controls": {"rate": 0.6}})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    pcm, sr = _pcm(r.content)
    assert sr == 24000 and 1.0 < len(pcm) / sr < 8 and np.abs(pcm).max() > 0.05
    assert r.headers["X-Steer-Tag"] == "confidence" and "rate=0.60" in r.headers["X-Steer-Ctrl"]


def test_markup_and_guidance(client):
    r = client.post("/v1/tts", json={"text": "Shields to *forty* percent at *Shackleton*.", "markup": True,
                                     "guidance": 1.5, "tag": "emphasis"})
    assert r.status_code == 200 and len(r.content) > 20000


def test_rate_control_shortens_audio(client):
    slow = client.post("/v1/tts", json={"text": "Take a deep breath, we have time.", "controls": {"rate": -1.5}})
    fast = client.post("/v1/tts", json={"text": "Take a deep breath, we have time.", "controls": {"rate": 1.5}})
    assert len(_pcm(fast.content)[0]) < 0.85 * len(_pcm(slow.content)[0])


def test_director_plans_fill_unnamed_controls(client):
    if tts_steer.STATE["director"] is None:
        pytest.skip("director.bin not available")
    r = client.post("/v1/tts", json={"text": "The rover rolled out.", "controls": {"rate": 0.5},
                                     "perform": {"genre": "children", "para_index": 0, "para_len": 2,
                                                 "next": "It found a crater."}})
    ctrl = dict(kv.split("=") for kv in r.headers["X-Steer-Ctrl"].split(","))
    assert ctrl["rate"] == "0.50"                         # explicit control wins
    assert "loud" in ctrl and "f0_end" in ctrl            # the plan filled the rest
    assert int(r.headers["X-Steer-Pause-Ms"]) > 0         # and left the gap before the next sentence


def test_rejects_unknown_voice_tag_control(client):
    assert client.post("/v1/tts", json={"text": "Hi.", "voice": "nobody"}).status_code == 400
    assert client.post("/v1/tts", json={"text": "Hi.", "tag": "grumpy"}).status_code == 400
    assert client.post("/v1/tts", json={"text": "Hi.", "controls": {"speed": 1}}).status_code == 400


def test_health_reports_rss():
    h = tts_steer.health()["steer_tts"]
    assert "rss_added_mb" in h and "error" in h
