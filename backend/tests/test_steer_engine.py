"""Steer TTS, the optional second voice engine (Settings -> Voice; app/tts.py, app/voices.py, model_server/app/tts_steer.py).
No audio is ever played: every render is bytes, and the model server is faked."""
import asyncio
import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import session as sessions, steering, tts, voices
from app.config import settings


def wav(seconds=1.0, sr=24000) -> bytes:
    t = np.arange(int(sr * seconds)) / sr
    x = (0.2 * np.sin(2 * np.pi * 220 * t) * (t < seconds - 0.1)).astype(np.float32)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return b.getvalue()


@pytest.fixture
def engines(monkeypatch, tmp_path):
    """Fake model server: Steer and the OS voice each record what they were asked."""
    calls = {"steer": [], "os": [], "steer_up": True}

    async def steer(text, style, place):
        calls["steer"].append({"text": text, "style": dict(style)})
        if not calls["steer_up"]:
            raise RuntimeError("steer tts 503: Steer TTS not loaded")
        return wav(), "0-300,320-700"

    async def os_tts(text, style, place):
        calls["os"].append({"text": text, "style": dict(style)})
        return wav(), "0-400,420-800", "pack" if style.get("pack_on") else "say"
    monkeypatch.setattr(tts, "_steer", steer)
    monkeypatch.setattr(tts, "_os_tts", os_tts)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "tts")
    monkeypatch.setattr(settings, "tts_engine", "os")
    monkeypatch.setattr(tts, "pack_version", lambda: "v1")
    voices.set_catalog({"voices": [{"id": "com.apple.voice.premium.en-US.Zoe", "name": "Zoe"}],
                        "roles": {"guide": "com.apple.voice.premium.en-US.Zoe"}})
    return calls


def speak(text, voice="guide", style=None):
    return asyncio.run(tts.speak(text, voice, style))


def test_engine_switch_mid_session_system_to_steer_and_back():
    s = sessions.Session("steer-switch")
    d = {"t": "say", "voice": "guide", "text": "Hello, cadet."}
    s.prefs = sessions.clean_prefs({"engine": "steer"}, s.prefs)
    s._with_prefs(d)
    assert d["style"]["tts_engine"] == "steer" and d["style"]["steer_voice"] == "voice_1085"   # Aurora by default
    assert d["style"]["pack"] is False                                                          # Steer: all live
    s.prefs = sessions.clean_prefs({"engine": "steer", "steer_voice": "voice_0644"}, s.prefs)
    d2 = {"t": "say", "voice": "houston", "text": "Houston here."}
    s._with_prefs(d2)
    assert d2["style"]["steer_voice"] == steering.STEER_VOICES["houston"]   # Houston keeps its own radio voice
    d3 = {"t": "say", "voice": "guide", "text": "Next."}
    s._with_prefs(d3)
    assert d3["style"]["steer_voice"] == "voice_0644"
    s.prefs = sessions.clean_prefs({"engine": "os"}, s.prefs)
    d4 = {"t": "say", "voice": "guide", "text": "Back to the computer's voice."}
    s._with_prefs(d4)
    assert "tts_engine" not in (d4.get("style") or {}) and (d4.get("style") or {}).get("pack") is not False
    assert sessions.clean_prefs({"engine": "nope"}, s.prefs)["engine"] == "os"
    assert sessions.clean_prefs({"steer_voice": "voice_9999"})["steer_voice"] is None   # not a curated voice: ignored


def test_voice_pack_only_with_the_system_voice(engines):
    r = speak("Patch earned.", "guide", {"tts_engine": "steer"})
    assert r.headers["X-TTS-Engine"] == "steer" and not engines["os"]
    assert "pack_on" not in engines["steer"][0]["style"]
    r = speak("Patch earned.", "guide", None)                # the default engine: the pack may speak it
    assert r.headers["X-TTS-Engine"] == "pack" and engines["os"][0]["style"].get("pack_on")
    assert not steering.pack_allowed({"engine": "steer"}) and steering.pack_allowed({"engine": "os"})


def test_captions_exact_with_steer_word_timings(engines):
    r = speak("Hello cadet.", "guide", {"tts_engine": "steer", "steer_voice": "voice_1059"})
    assert r.status_code == 200 and r.headers["X-TTS-Engine"] == "steer"
    assert r.headers["X-TTS-Words"] == "0-300,320-700"         # the model's own timings, one per display word
    assert engines["steer"][0]["style"]["steer_voice"] == "voice_1059"
    hit = speak("Hello cadet.", "guide", {"tts_engine": "steer", "steer_voice": "voice_1059"})
    assert hit.headers["X-TTS-Cache"] == "hit" and hit.headers["X-TTS-Words"] == "0-300,320-700"


def test_steer_missing_falls_back_to_the_system_voice(engines):
    engines["steer_up"] = False
    r = speak("Shields to forty percent.", "capcom", {"tts_engine": "steer"})
    assert r.status_code == 200 and r.headers["X-TTS-Engine"] in ("os", "pack")
    assert "steer" in r.headers["X-TTS-Fallback"]
    assert engines["os"][0]["style"].get("tts_voice")           # a normal OS render, not a Steer voice id
    assert "steer_voice" not in engines["os"][0]["style"]


def test_engine_state_and_on_demand_download(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "assets_dir", tmp_path)
    health = {"loaded": False, "available": False, "error": "Steer TTS Edge model not found"}

    async def h():
        return dict(health)
    monkeypatch.setattr(voices, "_steer_health", h)
    monkeypatch.setattr(voices, "STATUS", {"at": -1e9, "steer": None})
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/tts/engines").json()["steer"]["state"] == "missing"
        st = c.post("/api/tts/engines/steer").json()           # the kid picked Steer: ask the desktop for it
        assert st["state"] == "downloading" and (tmp_path / ".want" / "steer").exists()
        health["loaded"] = True
        voices.STATUS["at"] = -1e9
        assert c.get("/api/tts/engines").json()["steer"]["state"] == "ready"
        vs = c.get("/api/voices", params={"engine": "steer"}).json()
        assert vs[0]["name"] == "Aurora" and len(vs) == 10
        assert c.get(vs[0]["preview_url"]).status_code == 200    # the offline preview clip
