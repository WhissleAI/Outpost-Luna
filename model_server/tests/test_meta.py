"""Arc Transcriber Space metadata: POST /v1/meta and WS /v1/stream (metadata-only). Skips when the model, libarc or the
crew clips are missing (real crew audio: the model ignores TTS on purpose)."""
import io
import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import arcmeta
from app.main import app

DATA = Path(__file__).resolve().parents[2] / "backend/data"
STEM = "art002a000015-omg-stop-it"     # "Earthrise": exclamations, the awe clip
CLIP_S = 30


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        if not c.get("/health").json()["models"]["arc_meta"]["loaded"]:
            pytest.skip(f"Arc Transcriber Space not loaded: {arcmeta.STATE['error']}")
        yield c


@pytest.fixture(scope="module")
def clip():
    audio = DATA / f"media/audio/{STEM}.mp3"
    tr = DATA / f"transcripts/{STEM}.json"
    if not (audio.exists() and tr.exists()):
        pytest.skip("crew clip not on this machine")
    import soundfile as sf
    from scipy.signal import resample_poly
    x, sr = sf.read(str(audio), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != 16000:
        x = resample_poly(x, 16000, sr).astype(np.float32)
    x = x[: CLIP_S * 16000]
    words = [{"w": w["word"].strip(), "t0": w["start"], "t1": w["end"]}
             for s in json.loads(tr.read_text())["segments"] for w in s.get("words", [])
             if w["end"] <= CLIP_S and w["word"].strip()]
    return x, words


def test_health_lists_models_and_rss(client):
    h = client.get("/health").json()
    assert h["models"]["arc_meta"]["model"] == arcmeta.MODEL and h["models"]["arc_ear"]["backend"].startswith("onnxruntime")
    assert h["models"]["emotion"]["enabled"] is False and h["models"]["emotion"]["reason"]
    assert h["rss_mb"]["now"] > 0


def test_awe_heuristic():
    assert arcmeta.awe_score([], [{"w": "Wow!"}, {"w": "amazing"}]) == pytest.approx(0.455, abs=0.01)
    assert arcmeta.awe_score([{"label": "scene.laughter", "p": 0.9}], []) == 0.32
    assert arcmeta.awe_score([{"label": "scene.laughter", "p": 0.9}], [], {"scene.laughter": 0.9}) == 0.0


def test_meta_whole_clip(client, clip):
    x, words = clip
    buf = io.BytesIO()
    import soundfile as sf
    sf.write(buf, x, 16000, format="WAV", subtype="PCM_16")
    r = client.post("/v1/meta", files={"audio": ("c.wav", buf.getvalue(), "audio/wav")},
                    data={"words": json.dumps(words), "domain": "assistant", "events": "all"})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["rtf"] < 0.5
    us = m["utterances"]
    assert len(us) >= 3
    for u in us:
        assert {"t0", "t1", "speaker", "act", "intent", "device_directed", "audio_events", "bio_events", "awe"} <= set(u)
        assert u["t0"] <= u["t1"] and 0 <= u["awe"] <= 1
    assert all(u["device_directed"] is not None for u in us)
    assert sum(bool(u["transcript"]) for u in us) >= 3              # the model's own words, per utterance
    assert max(u["device_directed"] for u in us) < 0.5              # the crew talk to each other, not to a device
    assert max(u["awe"] for u in us) >= 0.5         # "that looks cool!", "There's some lofted dust!"


def test_meta_bad_words(client):
    r = client.post("/v1/meta", files={"audio": ("c.raw", b"\0" * 32000)}, data={"words": "{"})
    assert r.status_code == 400


def test_stream(client, clip):
    x, words = clip
    pcm = (np.clip(x[: 12 * 16000], -1, 1) * 32767).astype("<i2").tobytes()
    got = []
    with client.websocket_connect("/v1/stream") as ws:
        assert ws.receive_json() == {"t": "emotion", "available": False, "reason": arcmeta.EMOTION_REASON}
        assert ws.receive_json()["available"] is True
        ws.send_text(json.dumps({"t": "words", "words": [w for w in words if w["t1"] <= 12]}))
        t = time.perf_counter()
        for i in range(0, len(pcm), 2560):              # 80 ms frames
            ws.send_bytes(pcm[i:i + 2560])
        ws.send_text(json.dumps({"t": "end_turn"}))
        ws.send_text(json.dumps({"t": "stop"}))
        while True:
            m = ws.receive_json()
            got.append(m)
            if m.get("final"):
                break
        wall = time.perf_counter() - t
    arc = [m for m in got if m["t"] == "arc"]
    assert arc and wall < 12
    assert any(m["device_directed"] is not None for m in arc) and any(m["speech"] for m in arc)
    assert not [m for m in got if m["t"] in ("words", "turn")]      # metadata only
    assert arc[-1]["final"] is True
    assert {"command_complete", "device_directed", "speaker", "audio_events", "bio_events", "names"} <= set(arc[0])


def test_stream_admission_cap(client, monkeypatch):
    monkeypatch.setattr(arcmeta.meta_settings, "meta_max_sessions", 0)
    with client.websocket_connect("/v1/stream") as ws:
        assert ws.receive_json()["t"] == "emotion"
        assert ws.receive_json() == {"t": "arc", "available": False, "reason": "META_MAX_SESSIONS reached"}
        ws.send_text(json.dumps({"t": "stop"}))
