"""On-device learning, the ear's side (docs/ON_DEVICE_LEARNING.md): the per-line speaker -> mic delay (app/echo_delay.py,
numbers only) and the bounded per-stream tuning ({"t":"tune"}, arc_ear.TUNE_BOUNDS)."""
import numpy as np

from app import arc_ear
from app.echo_delay import DelayMeter, SR


def _run(delay_s, gain=0.3, noise=0.003, seed=0):
    rng = np.random.default_rng(seed)
    ref = (rng.standard_normal(int(1.5 * SR)) * 0.2).astype(np.float32)
    mic = (rng.standard_normal(4 * SR) * noise).astype(np.float32)
    d = int(delay_s * SR)
    mic[int(0.5 * SR) + d: int(0.5 * SR) + d + len(ref)] += gain * ref
    dm = DelayMeter()
    dm.feed_ref(ref, 0.5)
    out = []
    for i in range(0, len(mic), 1280):
        out += dm.feed_mic(mic[i:i + 1280], (i + 1280) / SR)
    return out


def test_the_delay_of_a_line_is_measured():
    for d in (0.05, 0.141, 0.159, 0.3):
        out = _run(d)
        assert len(out) == 1 and abs(out[0]["ms"] - 1000 * d) <= 1.0 and out[0]["peak"] > 20
        assert set(out[0]) == {"t", "ms", "peak", "at"}       # numbers only: no audio leaves the meter


def test_no_echo_no_estimate():
    assert _run(0.15, gain=0.0) == []


def test_short_or_overlapping_lines_are_skipped():
    dm = DelayMeter()
    dm.feed_ref(np.ones(SR // 4, np.float32) * 0.1, 0.0)        # too short
    dm.feed_ref(np.ones(SR, np.float32) * 0.1, 1.0)
    dm.feed_ref(np.ones(SR, np.float32) * 0.1, 1.5)            # overlaps the previous line
    assert len(dm.pending) == 1


def test_tune_is_bounded():
    assert arc_ear.tune_values({"end_silence_s": 5, "ref_shift_s": -1, "other": 3}) == {"end_silence_s": 0.8,
                                                                                         "ref_shift_s": 0.0}
    assert arc_ear.tune_values({"end_silence_s": "x"}) == {}
    assert arc_ear.tune_values({"end_silence_s": 0.6, "ref_shift_s": 0.12}) == {"end_silence_s": 0.6, "ref_shift_s": 0.12}
