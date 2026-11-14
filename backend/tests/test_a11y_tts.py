"""a11y: speed → Steer rate/pace, vocab steering, word-timing passthrough + cache (docs/ACCESSIBILITY.md)."""
import pytest
from fastapi.testclient import TestClient

from app import steering, tts
from app.config import settings
from app.main import app


@pytest.mark.parametrize("speed,rate_sign,pace_cmp", [(0.75, -1, -1), (1.0, 0, 0), (1.25, 1, 1), (1.5, 1, 1)])
def test_speed_maps_to_rate_and_pace(speed, rate_sign, pace_cmp):
    d, pace = steering.speed_steer(speed)
    assert (d > 0) - (d < 0) == rate_sign and (pace > 1) - (pace < 1) == pace_cmp


def test_speed_is_monotonic_and_clamped():
    r = [steering.speed_steer(s) for s in steering.SPEEDS]
    assert [x[0] for x in r] == sorted(x[0] for x in r) and [x[1] for x in r] == sorted(x[1] for x in r)
    assert steering.speed_steer(9) == steering.speed_steer(1.6) and steering.speed_steer("x") == (0.0, 1.0)
    c, pace = steering.with_speed({"rate": 2.0, "loud": 0.5}, 1.5)
    assert c["rate"] == steering.CONTROL_LIMIT and c["loud"] == 0.5 and pace > 1.2   # added on top, then clamped


def test_vocab_situation_is_slow_and_enunciated():
    st = steering.style_for("guide", "Albedo is how bright a surface is.", situation="vocab", vocab=["albedo", "crater"])
    assert st["tag"] == "enunciated" and st["controls"]["rate"] <= -1.0 and st["controls"]["pause"] > 0
    assert st["vocab"] == ["albedo"] and st["markup"]


def test_vocab_markup_wraps_the_word_once():
    out = steering.apply_markup("Albedo: albedo is 40 percent.", emph=["40", "albedo"], vocab=["albedo"])
    assert out == "<slow><emph>Albedo</emph></slow>: albedo is *40* percent."


@pytest.fixture
def steer(monkeypatch, tmp_path):
    calls = []

    async def fake(text, style, place):
        calls.append((text, style))
        return b"RIFFfake", "0-300,300-700"

    monkeypatch.setattr(tts, "_steer", fake)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "c")
    monkeypatch.setattr(settings, "tts_engine", "steer")
    return calls


def test_word_timings_pass_through_and_are_cached(steer):
    with TestClient(app) as c:
        a = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide"})
        b = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide"})
    assert a.headers["x-tts-words"] == b.headers["x-tts-words"] == "0-300,300-700"
    assert b.headers["x-tts-cache"] == "hit" and "X-TTS-Words" in a.headers["access-control-expose-headers"]
    assert len(steer) == 1


def test_speed_changes_the_request_and_the_cache_key(steer):
    with TestClient(app) as c:
        c.get("/api/tts", params={"text": "Hello cadet.", "voice": "capcom"})
        r = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "capcom", "speed": 1.5})
    assert r.headers["x-tts-cache"] == "miss" and "pace=" in r.headers["x-tts-speed"]
    (_, s1), (_, s2) = steer
    assert s2["controls"]["rate"] > s1["controls"]["rate"] and s2["pace"] > 1 and "pace" not in s1


def test_bad_word_header_is_dropped():
    assert tts.clean_words("0-1,2-3") == "0-1,2-3" and tts.clean_words("<script>") == "" and tts.clean_words(None) == ""
