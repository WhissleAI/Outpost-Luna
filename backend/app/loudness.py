"""Loudness for every TTS output (docs/VOICE_STEERING.md §4d): ITU-R BS.1770-4 integrated loudness (LUFS), true peak
(4x oversampled, dBTP), a short look-ahead peak limiter, and a cap on long silences. numpy only (no scipy).

    y, info = master(x, sr, target_lufs=-14.0, gain_db=0.0)

TTS voices render at roughly -17 to -25 LUFS with several dB of spread between voices. `master` brings every line to the
same integrated loudness (the target, plus the kid's volume gain and the alarm offset), then a look-ahead limiter
holds the true peak under -1 dBTP without hard clipping. The limiter only moves gain on the few peaks the make-up gain
pushes over the ceiling; its gain ramps over the look-ahead window (no step = no click / distortion).
"""
from __future__ import annotations

import io
import math
import wave

import numpy as np

TARGET_LUFS = -14.0          # every voice line, every persona (UI master volume 100%)
ALARM_LUFS_OFFSET = 2.0      # storm / failure lines sit 2 LU hotter
CEILING_DBTP = -1.0          # true-peak ceiling after the limiter
MAX_GAIN_DB = 6.0            # the kid's volume above 100%: gain into the limiter, at most +6 dB
MIN_GAIN_DB = -30.0
LOOKAHEAD_S = 0.005          # limiter look-ahead = attack ramp (the gain is down before the peak arrives)
HOLD_S = 0.01                # limiter hold after a peak, then an 8 ms ramp back up (no low-frequency gain wobble)
SILENCE_DB = -42.0           # a frame this far under the line's loudest frame is silence (for the gap cap)


def _k_weight_mag(n: int, sr: int) -> np.ndarray:
    """|H(f)| of the BS.1770 K-weighting (pre-filter shelf + RLB high-pass), evaluated on the rfft grid of n samples.
    The 48 kHz reference biquads are evaluated at the same physical frequencies, so any sample rate gets the same curve."""
    b1, a1 = (1.53512485958697, -2.69169618940638, 1.19839281085285), (1.0, -1.69065929318241, 0.73248077421585)
    b2, a2 = (1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    z = np.exp(-1j * 2 * np.pi * np.minimum(f, 23999.0) / 48000.0)

    def h(b, a):
        return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return np.abs(h(b1, a1) * h(b2, a2))


def lufs(x: np.ndarray, sr: int) -> float:
    """Integrated loudness, BS.1770-4: K-weighted mean square over 400 ms blocks (75 % overlap), gated at -70 LUFS
    absolute and -10 LU relative. Mono. -inf for silence."""
    x = np.asarray(x, np.float64)
    if not len(x) or not np.any(x):
        return float("-inf")
    y = np.fft.irfft(np.fft.rfft(x) * _k_weight_mag(len(x), sr), len(x))
    blk, hop = int(0.4 * sr), int(0.1 * sr)
    if len(y) < blk:
        ms = np.array([np.mean(y ** 2)])
    else:
        c = np.concatenate([[0.0], np.cumsum(y ** 2)])
        starts = np.arange(0, len(y) - blk + 1, hop)
        ms = (c[starts + blk] - c[starts]) / blk
    ld = -0.691 + 10 * np.log10(ms + 1e-20)
    g = ms[ld > -70]
    if not len(g):
        return float("-inf")
    rel = -0.691 + 10 * np.log10(np.mean(g)) - 10
    g = ms[(ld > -70) & (ld > rel)]
    return float(-0.691 + 10 * np.log10(np.mean(g)))


def true_peak_db(x: np.ndarray, os: int = 4) -> float:
    """True peak (dBTP): the sample peak of a 4x band-limited (FFT) oversampling."""
    x = np.asarray(x, np.float64)
    if not len(x):
        return float("-inf")
    n = len(x)
    X = np.fft.rfft(x)
    up = np.fft.irfft(np.concatenate([X, np.zeros(n * os // 2 + 1 - len(X))]) * os, n * os)
    return float(20 * np.log10(max(np.abs(up).max(), np.abs(x).max(), 1e-12)))


def _sliding_min(g: np.ndarray, back: int, ahead: int) -> np.ndarray:
    """min over the window [i - back, i + ahead) (hold + look-ahead), edge-padded."""
    w = back + ahead
    if w <= 1:
        return g
    p = np.concatenate([np.full(back, g[0]), g, np.full(ahead - 1, g[-1])])
    return np.lib.stride_tricks.sliding_window_view(p, w).min(axis=1)


def _box(g: np.ndarray, w: int) -> np.ndarray:
    """Centered-left moving average over [i - w + 1, i] (causal smoothing of the gain)."""
    if w <= 1:
        return g
    p = np.concatenate([np.full(w - 1, g[0]), g])
    c = np.concatenate([[0.0], np.cumsum(p)])
    return (c[w:] - c[:-w]) / w


def limit(x: np.ndarray, sr: int, ceiling_db: float = CEILING_DBTP) -> np.ndarray:
    """Look-ahead peak limiter. Gain needed per sample -> min over [i - hold, i + L) -> averaged over the last L samples,
    so the gain is already down when the peak arrives (an L-long ramp), is held for HOLD_S, and ramps back up over L:
    never a step. Each averaged value covers windows that contain the sample itself, so the gain is <= what that
    sample needs: nothing passes the sample ceiling (0.5 dB under the true-peak ceiling, for inter-sample overs);
    `master` re-checks the true peak."""
    x = np.asarray(x, np.float64)
    ceil = 10 ** ((ceiling_db - 0.5) / 20)
    a = np.abs(x)
    if not len(x) or a.max() <= ceil:
        return x
    need = np.minimum(1.0, ceil / np.maximum(a, 1e-12))
    L = max(2, int(LOOKAHEAD_S * sr))
    g = _box(_sliding_min(need, int(HOLD_S * sr), L), L)
    y = x * np.minimum(g, need)        # float residue only
    return np.clip(y, -ceil, ceil)


def cap_gaps(x: np.ndarray, sr: int, max_gap_s: float = 0.28, lead_s: float = 0.03, tail_s: float = 0.22,
             with_mask: bool = False):
    """Shorten silences: inner gaps longer than max_gap_s are cut to max_gap_s (the middle goes; edges keep their decay),
    the leading silence to lead_s and the trailing silence (the director's gap before the next sentence) to tail_s."""
    x = np.asarray(x, np.float64)
    fr = max(1, int(0.01 * sr))
    n = len(x) // fr
    if n < 3:
        return (x, np.ones(len(x), bool)) if with_mask else x
    e = np.sqrt(np.mean(x[: n * fr].reshape(n, fr) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(e)
    voiced = db > db.max() + SILENCE_DB
    if not voiced.any():
        return (x, np.ones(len(x), bool)) if with_mask else x
    first, last = int(np.argmax(voiced)), int(n - 1 - np.argmax(voiced[::-1]))
    keep = np.zeros(len(x), bool)
    a0 = max(0, first * fr - int(lead_s * sr))
    b0 = min(len(x), (last + 1) * fr + int(tail_s * sr))
    keep[a0:b0] = True
    mg = int(max_gap_s / 0.01)
    i = first
    while i <= last:
        if not voiced[i]:
            j = i
            while j <= last and not voiced[j]:
                j += 1
            run = j - i
            if run > mg:
                cut_a, cut_b = (i + mg // 2) * fr, (j - (mg - mg // 2)) * fr
                keep[cut_a:cut_b] = False
            i = j
        else:
            i += 1
    return (x[keep], keep) if with_mask else x[keep]


def master(x: np.ndarray, sr: int, target_lufs: float = TARGET_LUFS, gain_db: float = 0.0,
           ceiling_db: float = CEILING_DBTP) -> tuple[np.ndarray, dict]:
    """Loudness-normalise to target_lufs + gain_db, then limit to ceiling_db true peak."""
    x = np.asarray(x, np.float64)
    before = lufs(x, sr)
    if not math.isfinite(before):
        return x, {"lufs_in": None, "lufs": None, "tp": None, "gain_db": 0.0}
    gain_db = max(MIN_GAIN_DB, min(MAX_GAIN_DB, float(gain_db)))
    want = target_lufs + gain_db
    g = want - before
    for _ in range(4):                    # limiting costs a little loudness: re-measure and make it up
        y = limit(x * 10 ** (g / 20), sr, ceiling_db)
        got = lufs(y, sr)
        if abs(got - want) <= 0.2 or g >= 24:
            break
        g += want - got
    tp = true_peak_db(y)
    if tp > ceiling_db:                   # a rare inter-sample over the limiter's sample ceiling missed
        y = y * 10 ** ((ceiling_db - tp - 0.05) / 20)
        tp = true_peak_db(y)
    return y, {"lufs_in": round(before, 2), "lufs": round(lufs(y, sr), 2), "tp": round(tp, 2), "gain_db": round(g, 2)}


# ---- wav I/O --------------------------------------------------------------------------------------------------------
def read_wav(b: bytes) -> tuple[np.ndarray, int]:
    w = wave.open(io.BytesIO(b))
    if w.getsampwidth() != 2:
        raise ValueError("16-bit PCM only")
    sr, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav(x: np.ndarray, sr: int) -> bytes:
    pcm = np.clip(np.round(np.asarray(x) * 32767.0), -32768, 32767).astype("<i2").tobytes()
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return b.getvalue()
