"""Signal helpers: the start chirp, delay recovery by matched filter, level normalisation, resampling.

numpy only (no scipy), so the kit runs with `uv run --with sounddevice --with soundfile --with numpy`.
"""
from __future__ import annotations

import math

import numpy as np


# ---- chirp ------------------------------------------------------------------------------------------------------------
def chirp(sr: int, dur: float = 0.5, f0: float = 300.0, f1: float = 8000.0, level_db: float = -12.0) -> np.ndarray:
    """A logarithmic sweep f0 -> f1 with 10 ms raised-cosine fades. Broadband, so its autocorrelation is one sharp peak:
    the matched filter finds it to well under a millisecond, even quiet and coloured by a laptop speaker."""
    f1 = min(f1, 0.45 * sr)
    n = int(round(dur * sr))
    t = np.arange(n) / sr
    k = math.log(f1 / f0)
    phase = 2 * math.pi * f0 * dur / k * (np.exp(t * k / dur) - 1)
    x = np.sin(phase)
    fade = int(0.01 * sr)
    if fade:
        w = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, fade))
        x[:fade] *= w
        x[-fade:] *= w[::-1]
    return (x * 10 ** (level_db / 20)).astype(np.float32)


def _xcorr(sig: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Cross-correlation c[k] = sum sig[k + i] * ref[i], for k = 0 .. len(sig) - len(ref), via FFT."""
    n = len(sig) + len(ref)
    nfft = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(sig, nfft) * np.conj(np.fft.rfft(ref, nfft)), nfft)
    return c[: len(sig) - len(ref) + 1]


def find_delay(mic: np.ndarray, ref: np.ndarray, at: int, sr: int, max_delay_s: float = 1.0) -> dict:
    """Where `ref` (played starting at sample `at` of the shared clock) shows up in `mic`.

    Returns {delay_s, delay_samples, peak_ratio, reliable}: delay_samples is fractional (parabolic interpolation of the
    matched-filter peak), peak_ratio the peak over the median |correlation| (a clean chirp gives > 20). With
    peak_ratio < 8 the measurement is marked unreliable (the mic did not hear the speakers)."""
    ref = np.asarray(ref, np.float64)
    seg = np.asarray(mic[at: at + len(ref) + int(max_delay_s * sr)], np.float64)
    if len(seg) < len(ref) + 2:
        return {"delay_s": None, "delay_samples": None, "peak_ratio": 0.0, "reliable": False}
    c = np.abs(_xcorr(seg, ref))
    k = int(np.argmax(c))
    frac = 0.0
    if 0 < k < len(c) - 1:
        a, b, d = c[k - 1], c[k], c[k + 1]
        den = a - 2 * b + d
        if den != 0:
            frac = float(0.5 * (a - d) / den)
    ratio = float(c[k] / (np.median(c) + 1e-12))
    ds = k + frac
    return {"delay_s": round(ds / sr, 6), "delay_samples": round(ds, 2), "peak_ratio": round(ratio, 1),
            "reliable": bool(ratio >= 8.0)}


# ---- levels -----------------------------------------------------------------------------------------------------------
def active_rms(x: np.ndarray, sr: int, frame_s: float = 0.02) -> float:
    """RMS over the loud frames (within 30 dB of the loudest), so pauses don't drag the level down."""
    x = np.asarray(x, np.float64)
    n = max(1, int(frame_s * sr))
    m = len(x) // n
    if m == 0:
        return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    e = np.mean(x[: m * n].reshape(m, n) ** 2, axis=1)
    top = e.max()
    if top <= 0:
        return 0.0
    return float(np.sqrt(np.mean(e[e >= top * 1e-3])))


def master(x: np.ndarray, sr: int, rms_db: float = -18.0, peak_db: float = -1.0) -> np.ndarray:
    """Gain only: speech RMS to rms_db, then pulled down if a peak would pass peak_db (roughly the app's mastering:
    the voice pack is -20 dBFS RMS and the backend limits at -1 dBTP)."""
    x = np.asarray(x, np.float32)
    r = active_rms(x, sr)
    if r <= 0:
        return x
    g = 10 ** (rms_db / 20) / r
    pk = float(np.max(np.abs(x))) * g
    lim = 10 ** (peak_db / 20)
    if pk > lim:
        g *= lim / pk
    return (x * g).astype(np.float32)


# ---- resampling -------------------------------------------------------------------------------------------------------
def lowpass_fir(sr: int, cutoff: float, taps: int = 255) -> np.ndarray:
    """Windowed-sinc (Blackman) low-pass, odd length, unity DC gain. Linear phase: group delay (taps - 1) / 2."""
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff / sr * n) * np.blackman(taps)
    return (h / h.sum()).astype(np.float64)


def _fftconv(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    n = len(x) + len(h) - 1
    nfft = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[:n]


def resample(x: np.ndarray, sr: int, to: int) -> np.ndarray:
    """Whole-array resample (short clips): anti-alias FIR when going down, then linear interpolation. Sample 0 stays
    sample 0 (the filter's group delay is removed), so alignment is preserved."""
    x = np.asarray(x, np.float64)
    if sr == to or not len(x):
        return x.astype(np.float32)
    if to < sr:
        h = lowpass_fir(sr, 0.45 * to)
        d = (len(h) - 1) // 2
        x = _fftconv(x, h)[d: d + len(x)]
    n_out = int(math.floor((len(x) - 1) * to / sr)) + 1
    pos = np.arange(n_out) * (sr / to)
    return np.interp(pos, np.arange(len(x)), x).astype(np.float32)


def resample_file(src: str, dst: str, to: int = 16000, block: int = 1 << 20) -> int:
    """Stream a (long) WAV to a 16-bit mono WAV at `to` Hz, block by block (bounded memory). Same timing as `resample`:
    output sample k is input time k / to, so the 16 kHz mic and reference stay sample-aligned. Returns frames written."""
    import soundfile as sf

    with sf.SoundFile(src) as f:
        sr, total = f.samplerate, f.frames
        h = lowpass_fir(sr, 0.45 * to) if to < sr else np.array([1.0])
        d = (len(h) - 1) // 2
        step = sr / to
        hist = np.zeros(len(h) - 1)          # the filter's input history (zeros before the start)
        produced = 0                         # filter outputs produced so far (output i = compensated index i - d)
        carry, carry0 = np.zeros(0), 0       # compensated filtered samples not yet used, and carry[0]'s index
        k, written = 0, 0
        with sf.SoundFile(dst, "w", samplerate=to, channels=1, subtype="PCM_16") as out:
            eof = False
            while not eof:
                x = f.read(block, dtype="float64", always_2d=True)
                if len(x) == 0:
                    x, eof = np.zeros((d + 1, 1)), True        # flush the filter's group delay
                x = x.mean(axis=1)
                buf = np.concatenate([hist, x])
                y = np.convolve(buf, h, mode="valid") if len(h) > 1 else x
                if len(h) > 1:
                    hist = buf[-(len(h) - 1):]
                skip = max(0, d - produced)
                produced += len(y)
                carry = np.concatenate([carry, y[skip:]])
                avail = min(total, carry0 + len(carry))
                if avail >= total:
                    k_max = int(math.floor((total - 1) / step)) + 1 if total else 0
                else:
                    k_max = int(math.ceil((avail - 1) / step))
                if k_max > k:
                    p = np.arange(k, k_max) * step
                    i = np.floor(p).astype(np.int64)
                    fr = p - i
                    a = carry[i - carry0]
                    b = carry[np.minimum(i + 1 - carry0, len(carry) - 1)]
                    o = np.clip(a + (b - a) * fr, -1, 1)
                    out.write(o)
                    written += len(o)
                    k = k_max
                drop = max(0, int(k * step) - carry0 - 1)
                carry, carry0 = carry[drop:], carry0 + drop
        return written
