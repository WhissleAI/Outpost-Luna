"""Louder and faster (docs/VOICE_STEERING.md §4d): BS.1770 loudness, the -1 dBTP look-ahead limiter, every /api/tts
render at -14 LUFS (+2 LU for alarms, + the volume setting), the faster delivery baseline at 1x, slow lines kept slow,
the gap cap with word timings remapped, and the crew-clip playback gains."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import loudness as L, steering, tts
from app.config import settings
from app.main import app

SR = 24000
CEIL = 10 ** (L.CEILING_DBTP / 20)


def speechlike(seconds=2.4, level=0.05, seed=1, gap_at=None, gap_s=0.0, sr=SR):
    """Harmonic 'syllables' (f0 110-220 Hz, 6 harmonics, 180 ms on / 70 ms off) with peaky glottal pulses: a crest
    factor like a quiet voice. Optional long silence (gap_at s, gap_s long)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    f0 = 110 + 110 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t))
    ph = 2 * np.pi * np.cumsum(f0) / sr
    x = sum(np.sin(k * ph) / k ** 0.7 for k in range(1, 7))
    x = x + 0.4 * (np.sin(ph) > 0.995) * rng.standard_normal(n)
    env = ((t % 0.25) < 0.18).astype(float)
    env = np.convolve(env, np.ones(120) / 120, "same")
    y = x * env * level / np.sqrt(np.mean((x * env) ** 2))
    if gap_at is not None:
        k = int(gap_at * sr)
        y = np.concatenate([y[:k], np.zeros(int(gap_s * sr)), y[k:]])
    return y


def test_lufs_matches_the_bs1770_reference_tone():
    for sr in (48000, 24000, 16000):
        t = np.arange(sr * 3) / sr
        assert L.lufs(np.sin(2 * np.pi * 997 * t), sr) == pytest.approx(-3.01, abs=0.1)   # 0 dBFS sine = -3.01 LUFS
    assert L.lufs(np.zeros(1000), SR) == float("-inf")


@pytest.mark.parametrize("level", [0.003, 0.02, 0.05, 0.3])
@pytest.mark.parametrize("seed", [1, 2])
def test_master_hits_the_target_under_the_ceiling(level, seed):
    x = speechlike(level=level, seed=seed)
    y, info = L.master(x, SR)
    assert abs(L.lufs(y, SR) - L.TARGET_LUFS) <= 1.0
    assert np.abs(y).max() <= CEIL + 1e-9 and L.true_peak_db(y) <= L.CEILING_DBTP + 0.05
    assert info["lufs"] == pytest.approx(L.lufs(y, SR), abs=0.01)


def test_limiter_never_hard_clips_and_ramps():
    x = speechlike(level=0.2) * 4.0              # far over the ceiling
    y = L.limit(x, SR)
    assert np.abs(y).max() <= CEIL + 1e-9
    ok = np.abs(x) > 1e-3
    g = np.divide(y, x, out=np.ones_like(x), where=ok)
    both = ok[1:] & ok[:-1]
    # the gain moves smoothly between adjacent samples (an L-sample ramp), never a step
    assert np.max(np.abs(np.diff(g))[both]) < 0.05
    flat = np.sum(np.isclose(np.abs(y), CEIL, atol=1e-6))
    assert flat < 0.002 * len(y)                 # no plateau of clipped samples


def test_volume_and_alarm_offsets():
    x = speechlike()
    base, _ = L.master(x, SR)
    hot, _ = L.master(x, SR, gain_db=3.0)
    alarm, _ = L.master(x, SR, target_lufs=L.TARGET_LUFS + L.ALARM_LUFS_OFFSET)
    assert L.lufs(hot, SR) > L.lufs(base, SR) + 1.5 and L.lufs(alarm, SR) == pytest.approx(-12.0, abs=1.0)
    assert np.abs(hot).max() <= CEIL + 1e-9 and np.abs(alarm).max() <= CEIL + 1e-9
    assert tts.gain_for_volume(1.0) == 0 and tts.gain_for_volume(2.0) == L.MAX_GAIN_DB
    assert tts.gain_for_volume(0.5) == pytest.approx(-6.02, abs=0.01) and tts.gain_for_volume(0) == L.MIN_GAIN_DB


def test_gap_cap_and_word_timings():
    x = speechlike(seconds=2.0, gap_at=1.0, gap_s=1.2)
    y, keep = L.cap_gaps(x, SR, max_gap_s=0.25, tail_s=0.05, with_mask=True)
    assert len(x) / SR - len(y) / SR == pytest.approx(1.2 - 0.25, abs=0.08)
    w = tts._remap_words("100-400,2400-2800", (SR, keep))
    (a1, b1), (a2, b2) = [map(int, p.split("-")) for p in w.split(",")]
    assert (a1, b1) == (100, 400) and a2 == pytest.approx(2400 - 950, abs=80) and b2 - a2 == 400


@pytest.fixture
def os_calls(monkeypatch, tmp_path):
    calls = []

    async def fake(text, style, place):
        calls.append({"text": text, **style})
        quiet = speechlike(level=0.01, seed=len(calls), gap_at=0.6, gap_s=0.9)   # a quiet voice with long gaps
        return L.write_wav(quiet, SR), "0-200,300-500,1700-2000"

    monkeypatch.setattr(tts, "_os_tts", fake)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "c")
    monkeypatch.setattr(settings, "tts_engine", "os")
    return calls


def out_audio(r):
    x, sr = L.read_wav(r.content)
    return x, sr


@pytest.mark.parametrize("voice", ["guide", "capcom", "houston", "story"])
def test_every_persona_lands_at_the_target(os_calls, voice):
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Shields to forty percent. Then check the battery.", "voice": voice})
        hit = c.get("/api/tts", params={"text": "Shields to forty percent. Then check the battery.", "voice": voice})
    x, sr = out_audio(r)
    assert abs(L.lufs(x, sr) - L.TARGET_LUFS) <= 1.0
    assert np.abs(x).max() <= CEIL + 1e-4 and L.true_peak_db(x) <= L.CEILING_DBTP + 0.05
    assert "LUFS" in r.headers["x-tts-loudness"] and "X-TTS-Loudness" in r.headers["access-control-expose-headers"]
    assert hit.headers["x-tts-cache"] == "hit" and hit.content == r.content and len(os_calls) == 1   # cached mastered
    assert len(x) / sr < 2.4 + 0.9 - 0.5                     # the 0.9 s gap was capped


def test_alarm_lines_sit_two_lu_hotter(os_calls):
    st = steering.style_for("capcom", "Storm is here! Into the shelter.", situation="storm_alert")
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Storm is here! Into the shelter.", "voice": "capcom",
                                      "style": json.dumps(st)})
    x, sr = out_audio(r)
    assert abs(L.lufs(x, sr) - (L.TARGET_LUFS + L.ALARM_LUFS_OFFSET)) <= 1.0 and np.abs(x).max() <= CEIL + 1e-4


def test_volume_setting_reaches_the_master(os_calls):
    with TestClient(app) as c:
        a = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide"})
        b = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide", "style": json.dumps({"volume": 0.5})})
    xa, sr = out_audio(a)
    xb, _ = out_audio(b)
    assert L.lufs(xb, sr) == pytest.approx(L.lufs(xa, sr) - 6.0, abs=1.0)


def test_cache_key_carries_the_master_version(os_calls):
    st = tts.clean_style("guide", "Hi.", None)
    k1 = tts.cache_path("v", "Hi.", {**st, "master": tts.MASTER_VERSION}, "os")
    k2 = tts.cache_path("v", "Hi.", st, "os")
    assert k1 != k2


def test_default_rate_is_the_faster_baseline(os_calls):
    with TestClient(app) as c:
        c.get("/api/tts", params={"text": "The rover found ice.", "voice": "guide"})
        c.get("/api/tts", params={"text": "Albedo is how bright a surface is.", "voice": "guide",
                                  "style": json.dumps(steering.style_for("guide", "Albedo is how bright a surface is.",
                                                                         situation="vocab", vocab=["albedo"]))})
        c.get("/api/tts", params={"text": "A crater is a hole.", "voice": "guide",
                                  "style": json.dumps({"situation": "explain"})})
    normal, vocab, explain = os_calls
    assert normal["controls"]["rate"] == steering.BASE_CONTROLS["rate"]          # 1x is faster than before (0)
    assert normal["controls"]["pause"] == steering.BASE_CONTROLS["pause"]        # shorter phrase pauses
    assert normal["controls"]["loud"] == steering.BASE_CONTROLS["loud"]
    assert normal.get("pace", 1.0) == 1.0
    assert vocab["controls"]["rate"] == steering.SITUATIONS["vocab"]["controls"]["rate"]       # slow on purpose
    assert explain["controls"]["rate"] == steering.SITUATIONS["explain"]["controls"]["rate"]
    assert "pause" not in explain["controls"] or explain["controls"]["pause"] >= 0


def test_speed_setting_is_centred_on_the_new_default():
    rates = [steering.delivery({}, s)[0]["rate"] for s in steering.SPEEDS]
    assert rates == sorted(rates)
    assert steering.delivery({}, 1.0)[0]["rate"] == steering.BASE_CONTROLS["rate"]
    slow, _, gap = steering.delivery({}, 0.75)
    assert slow["rate"] < 0 and slow["pause"] > 0 and gap > steering.GAP_FAST_S   # 0.75x: slower than the old 1x
    assert steering.delivery({}, 1.5)[0]["rate"] == steering.CONTROL_LIMIT


def test_crew_clips_carry_a_playback_gain():
    data = json.loads((settings.data_dir / "clip_loudness.json").read_text())
    assert data["target_lufs"] == L.TARGET_LUFS and len(data["clips"]) >= 70
    for v in data["clips"].values():
        assert v["gain_db"] == pytest.approx(L.TARGET_LUFS - v["lufs"], abs=0.11)
    with TestClient(app) as c:
        clips = c.get("/api/clips").json()["clips"]
    known = [cl for cl in clips if cl["file"].rsplit("/", 1)[-1] in data["clips"]]
    assert known and all(isinstance(cl["gain_db"], float) for cl in clips)
