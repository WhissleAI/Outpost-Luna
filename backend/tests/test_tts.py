"""GET /api/tts: cache by hash, 3 distinct voices, 503 without a key (client falls back), 600-char cap."""
import pytest
from fastapi.testclient import TestClient

from app import tts
from app.config import settings
from app.main import app


@pytest.fixture
def fake_dg(monkeypatch, tmp_path):
    calls = []

    async def synth(model, text):
        calls.append((model, text))
        return b"ID3fake-mp3:" + model.encode()

    monkeypatch.setattr(tts, "_synth", synth)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "tts_cache")
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")
    return calls


def test_tts_renders_then_serves_from_cache(fake_dg, tmp_path):
    with TestClient(app) as c:
        r1 = c.get("/api/tts", params={"text": "Hello  cadet.", "voice": "guide"})
        r2 = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide"})
    assert r1.status_code == r2.status_code == 200
    assert r1.headers["content-type"] == "audio/mpeg"
    assert r1.headers["x-tts-cache"] == "miss" and r2.headers["x-tts-cache"] == "hit"
    assert r1.content == r2.content
    assert fake_dg == [(tts.VOICES["guide"], "Hello cadet.")]          # whitespace-normalized, rendered once
    assert list((tmp_path / "tts_cache").glob("*.mp3"))


def test_tts_voices_are_distinct(fake_dg):
    with TestClient(app) as c:
        for v in ("guide", "capcom", "story"):
            assert c.get("/api/tts", params={"text": "Copy that.", "voice": v}).status_code == 200
        assert c.get("/api/tts", params={"text": "Copy that.", "voice": "pirate"}).status_code == 422
    assert len({m for m, _ in fake_dg}) == 3


def test_tts_without_key_is_503_json(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "tts_cache")
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Hi."})
    assert r.status_code == 503 and r.json()["fallback"] == "browser"


def test_tts_caps_text_length(fake_dg):
    with TestClient(app) as c:
        assert c.get("/api/tts", params={"text": "a" * 601}).status_code == 422
        assert c.get("/api/tts", params={"text": "a" * 600}).status_code == 200


def test_tts_upstream_failure_is_502(monkeypatch, tmp_path):
    async def boom(model, text):
        raise RuntimeError("deepgram speak 401")
    monkeypatch.setattr(tts, "_synth", boom)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "tts_cache")
    monkeypatch.setattr(settings, "deepgram_api_key", "k")
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Hi."})
    assert r.status_code == 502 and r.json()["fallback"] == "browser"
