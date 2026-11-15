"""The recorded voice pack (docs/VOICE_PACK.md): the manifest, clip completeness, and when /api/tts asks for a clip."""
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import steering, tts, voices
from app.config import settings
from app.main import app
from tools import voice_pack_check

ROOT = Path(__file__).resolve().parents[2]
PACK = settings.data_dir / "voice_pack"


def _os_voices():
    spec = importlib.util.spec_from_file_location("os_voices_t", ROOT / "model_server/app/os_voices.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def manifest():
    return json.loads((PACK / "lines.json").read_text())


def test_manifest_is_keyed_with_the_model_servers_pack_key():
    ov = _os_voices()
    lines = manifest()["lines"]
    assert len(lines) > 500
    keys = [l["key"] for l in lines]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    for l in lines:
        assert l["key"] == ov.pack_key(l["text"]) and l["role"] in tts.PACK_PERSONAS and l["source"]


def test_manifest_holds_the_fixed_lines_and_not_the_live_ones():
    keys = {l["key"] for l in manifest()["lines"]}
    ov = _os_voices()
    for t in ("Each pin on the Moon is a lesson.", "Ready for lesson one?", "Comm window open. Houston can hear us.",
              "Switch views: Orbit, Site, Rover, Earth.", "Here we go, Nova."):
        assert ov.pack_key(t) in keys, t
    assert not any("houston here" in k for k in keys)          # Houston keeps its own voice: live
    live = (PACK / "lines_live.md").read_text()
    assert "Houston" in live and "vocab" in live.lower()


def test_every_manifest_line_has_a_clip():
    """Fails when a fixed line has no clip; skips while the pack is not recorded at all (a fresh manifest)."""
    missing, bad, n, _ = voice_pack_check.problems(PACK)
    if n == 0:
        pytest.skip("voice pack not recorded yet: make voice-pack (macOS, System voice = Siri Voice 1)")
    assert not bad, bad[:5]
    assert not missing, f"{len(missing)} lines without a clip (make voice-pack), e.g. {missing[:5]}"


def test_check_script_lists_missing_clips(tmp_path, capsys):
    (tmp_path / "lines.json").write_text(json.dumps({"lines": [{"key": "a b", "text": "A b."}]}))
    missing, bad, n, _ = voice_pack_check.problems(tmp_path)
    assert missing == ["A b."] and n == 0


# ---- /api/tts: when a clip is asked for ----------------------------------------------------------------------------
@pytest.fixture
def os_calls(monkeypatch, tmp_path):
    calls = []

    async def fake(text, style, place):
        calls.append(dict(style))
        from app import loudness as L
        import numpy as np
        x = (np.sin(np.arange(12000) / 5) * 0.2)
        return L.write_wav(x, 24000), "0-200,250-480", "pack" if style.get("pack_on") else "say"
    monkeypatch.setattr(tts, "_os_tts", fake)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "c")
    monkeypatch.setattr(settings, "tts_engine", "os")
    monkeypatch.setattr(tts, "pack_version", lambda: "v1")
    return calls


@pytest.mark.voice_pack
def test_guide_and_capcom_lines_ask_for_the_pack_in_the_guide_voice(os_calls):
    with TestClient(app) as c:
        g = c.get("/api/tts", params={"text": "Ready for lesson one?", "voice": "guide"})
        k = c.get("/api/tts", params={"text": "Ready for lesson one?", "voice": "capcom"})
        again = c.get("/api/tts", params={"text": "Ready for lesson one?", "voice": "capcom"})
    guide = voices.roles()["guide"]
    assert [bool(s.get("pack_on")) for s in os_calls] == [True, True]
    assert all(s["tts_voice"] == guide for s in os_calls)          # CAPCOM speaks in the guide voice with the pack
    assert g.headers["x-tts-engine"] == k.headers["x-tts-engine"] == "pack"
    assert again.headers["x-tts-cache"] == "hit" and again.headers["x-tts-engine"] == "pack"


@pytest.mark.voice_pack
@pytest.mark.parametrize("voice,style,speed", [
    ("houston", None, None),                                              # Houston: its own voice, live
    ("story", None, None),                                                # the hardware's story voice, live
    ("capcom", None, 1.25),                                               # the kid's pace is not 1x: live
    ("guide", {"pack": False}, None),                                     # Settings toggle off
    ("guide", {"tts_voice": "com.apple.voice.Aman.premium"}, None),       # another voice picked
    ("guide", {"situation": "explain"}, None),                            # slow on purpose
])
def test_the_pack_is_not_asked_for(os_calls, voice, style, speed):
    params = {"text": "Ready for lesson one?", "voice": voice}
    if style:
        params["style"] = json.dumps(style)
    if speed:
        params["speed"] = speed
    with TestClient(app) as c:
        r = c.get("/api/tts", params=params)
    assert r.status_code == 200 and not os_calls[-1].get("pack_on") and r.headers["x-tts-engine"] == "os"
    if voice in ("houston", "story"):
        assert os_calls[-1]["tts_voice"] == voices.roles()[voice]


@pytest.mark.voice_pack
def test_no_pack_recorded_means_live(os_calls, monkeypatch):
    monkeypatch.setattr(tts, "pack_version", lambda: "")
    with TestClient(app) as c:
        c.get("/api/tts", params={"text": "Ready for lesson one?", "voice": "capcom"})
    assert not os_calls[-1].get("pack_on") and os_calls[-1]["tts_voice"] == voices.roles()["capcom"]


def test_settings_pref_turns_the_pack_off():
    roles = voices.roles()
    assert steering.pack_allowed({}) and steering.pack_allowed({"voice": roles["guide"]})
    assert not steering.pack_allowed({"pack": False})
    assert not steering.pack_allowed({"voice": "com.apple.voice.Aman.premium"})
    st = steering.apply_prefs({"voice": "capcom"}, "capcom", {"pack": False})
    assert st["pack"] is False
