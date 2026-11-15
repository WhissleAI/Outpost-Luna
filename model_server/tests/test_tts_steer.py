"""POST /v1/tts/steer (the optional Steer engine): Steer TTS Edge renders playable WAV, steering takes effect, the director
plans, word timings come back. Skips without the model. Renders are bytes only: nothing is ever played."""
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
    r = client.post("/v1/tts/steer", json={"text": "Copy, Commander. Shields to forty percent.", "voice": "voice_0213",
                                     "tag": "confidence", "controls": {"rate": 0.6}})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    pcm, sr = _pcm(r.content)
    assert sr == 24000 and 1.0 < len(pcm) / sr < 8 and np.abs(pcm).max() > 0.05
    assert r.headers["X-Steer-Tag"] == "confidence" and "rate=0.60" in r.headers["X-Steer-Ctrl"]


def test_markup_and_guidance(client):
    r = client.post("/v1/tts/steer", json={"text": "Shields to *forty* percent at *Shackleton*.", "markup": True,
                                     "guidance": 1.5, "tag": "emphasis"})
    assert r.status_code == 200 and len(r.content) > 20000


def test_rate_control_shortens_audio(client):
    slow = client.post("/v1/tts/steer", json={"text": "Take a deep breath, we have time.", "controls": {"rate": -1.5}})
    fast = client.post("/v1/tts/steer", json={"text": "Take a deep breath, we have time.", "controls": {"rate": 1.5}})
    assert len(_pcm(fast.content)[0]) < 0.85 * len(_pcm(slow.content)[0])


def test_director_plans_fill_unnamed_controls(client):
    if tts_steer.STATE["director"] is None:
        pytest.skip("director.bin not available")
    r = client.post("/v1/tts/steer", json={"text": "The rover rolled out.", "controls": {"rate": 0.5},
                                     "perform": {"genre": "children", "para_index": 0, "para_len": 2,
                                                 "next": "It found a crater."}})
    ctrl = dict(kv.split("=") for kv in r.headers["X-Steer-Ctrl"].split(","))
    assert ctrl["rate"] == "0.50"                         # explicit control wins
    assert "loud" in ctrl and "f0_end" in ctrl            # the plan filled the rest
    assert int(r.headers["X-Steer-Pause-Ms"]) > 0         # and left the gap before the next sentence


def test_rejects_unknown_voice_tag_control(client):
    assert client.post("/v1/tts/steer", json={"text": "Hi.", "voice": "nobody"}).status_code == 400
    assert client.post("/v1/tts/steer", json={"text": "Hi.", "tag": "grumpy"}).status_code == 400
    assert client.post("/v1/tts/steer", json={"text": "Hi.", "controls": {"speed": 1}}).status_code == 400


def test_health_reports_rss():
    h = tts_steer.health()["steer_tts"]
    assert "rss_added_mb" in h and "error" in h


# ---- word timings + pace (docs/ACCESSIBILITY.md) ----------------------------------------------------------------------

def test_display_words_strip_markup():
    assert tts_steer.display_words("Shields to *40* percent at <emph>Shackleton</emph>.") == \
        ["Shields", "to", "40", "percent", "at", "Shackleton."]


def test_align_display_maps_and_falls_back():
    sp = [(0.0, 0.2), (0.2, 0.5), (0.5, 0.9)]
    assert tts_steer.align_display(["Hi", "there,", "cadet."], sp) == sp
    out = tts_steer.align_display(["Hello", "x"], sp)                     # count mismatch → proportional, anchored
    assert out[0][0] == 0.0 and abs(out[-1][1] - 0.9) < 1e-9 and out[0][1] < out[1][1]
    assert tts_steer.words_header([(0.0, 0.25), (0.3, 1.0)]) == "0-250,300-1000"


def test_word_timings_header_matches_display_words(client):
    text = "Copy, Commander. Shields to 40 percent at Shackleton."
    r = client.post("/v1/tts/steer", json={"text": text})
    spans = [tuple(map(int, x.split("-"))) for x in r.headers["X-Steer-Words"].split(",")]
    assert len(spans) == len(text.split())
    assert all(a <= b for a, b in spans) and all(spans[k][1] <= spans[k + 1][0] for k in range(len(spans) - 1))
    dur_ms = len(_pcm(r.content)[0]) / 24
    assert spans[-1][1] <= dur_ms + 1 and spans[-1][1] > 0.6 * dur_ms


def test_word_timings_with_markup(client):
    r = client.post("/v1/tts/steer", json={"text": "Shields to *40* percent at <emph>Shackleton</emph>.", "markup": True})
    assert len(r.headers["X-Steer-Words"].split(",")) == 6


def test_pace_speeds_up(client):
    t = "Albedo is how bright or dark a surface is in sunlight."
    a = client.post("/v1/tts/steer", json={"text": t})
    b = client.post("/v1/tts/steer", json={"text": t, "pace": 1.4})
    assert b.headers["X-Steer-Pace"] == "1.40"
    assert len(_pcm(b.content)[0]) < 0.85 * len(_pcm(a.content)[0])


def test_missing_model_is_503_then_loads_once_the_asset_arrives(tmp_path, monkeypatch):
    """The optional `steer` asset may install after the model server started: no model -> 503 + reason (the backend
    falls back to the OS voice); the folder appears -> the next request loads it."""
    settings = tts_steer.settings          # the module's own object (another test may reload app.config)
    real = settings.steer_model_dir()
    if real is None:
        pytest.skip("Steer TTS Edge model not on this machine")
    saved = {k: tts_steer.STATE[k] for k in ("tts", "director", "error")}
    monkeypatch.setattr(settings, "steer_tts_model", tmp_path / "steer-tts-edge")
    try:
        tts_steer.STATE["tts"] = None
        assert tts_steer.ensure() is False and "not installed" in tts_steer.STATE["error"]
        h = tts_steer.health()["steer_tts"]
        assert h["loaded"] is False and h["available"] is False
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            r = c.post("/v1/tts/steer", json={"text": "Hello."})
            assert r.status_code == 503
            monkeypatch.setattr(settings, "steer_tts_model", real)      # the download finished
            r = c.post("/v1/tts/steer", json={"text": "Hello."})
            assert r.status_code == 200 and r.headers["X-Steer-Words"]
    finally:
        tts_steer.STATE.update(saved)


def test_windows_path_runs_without_libm(monkeypatch):
    """Windows has no libm for ctypes: steertts_edge's director falls back to numpy (pure Python + ONNX Runtime, the
    same py3-none-any wheel on both OSes)."""
    import ctypes
    import importlib

    import steertts_edge.director as D

    def no_libm(*a, **k):
        raise OSError("no libm (Windows)")
    monkeypatch.setattr(ctypes, "CDLL", no_libm)
    monkeypatch.setattr("ctypes.util.find_library", lambda name: None)
    try:
        D2 = importlib.reload(D)
        assert D2._LIBM is None
        x = np.array([0.5, -1.0], np.float32)
        assert np.allclose(D2._tanh(x), np.tanh(x), atol=1e-6)
        p = tts_steer.settings.steer_director_path()
        if p is not None:
            d = D2.Director(str(p))
            assert d.plan(["The rover rolled out.", "Then it stopped."])
    finally:
        monkeypatch.undo()
        importlib.reload(D)
