"""This computer's speaker -> microphone delay, measured from the app's own lines as they play (on-device learning,
docs/ON_DEVICE_LEARNING.md "Echo, per laptop").

For each reference the app feeds (a guide sentence, a crew clip) the ear keeps the last few seconds of microphone audio
in memory; once the line has played, GCC-PHAT between the reference and the microphone gives the delay at which the
line came back, and how clearly (the peak over the rest of the correlation). Only those two numbers leave this file:
no audio is kept past the ring buffer and none is written anywhere. The backend's learner (backend/app/learn/echo.py)
keeps a robust median and the drift per computer.

Measured on a real MacBook Pro recording (docs/ARC_ABI2.md section 8): the per-line estimate matches the kit's chirp
measurement (141-159 ms, drifting) on lines played at any of the four levels.
"""
from __future__ import annotations

import collections

import numpy as np

SR = 16000
MIN_REF_S = 0.6          # a line shorter than this is too short to measure
USE_REF_S = 2.0          # the first 2 s of a line are enough
MAX_DELAY_S = 0.5        # the canceller's own window (arc_echo: 512 ms); a longer delay is not an echo it can learn
SETTLE_S = 0.15          # extra mic audio after the window, before measuring
MIN_PEAK = 20.0          # peak / median |correlation| below this: no clear echo (no echo reads ~5-7; the real laptop lines 78-1600)
RING_S = 8.0


def gcc_phat(ref: np.ndarray, mic: np.ndarray, max_lag: int) -> tuple[int, float]:
    """-> (lag in samples of mic behind ref, peak ratio). ref and mic start at the same instant."""
    n = 1 << int(np.ceil(np.log2(len(ref) + len(mic))))
    R = np.fft.rfft(ref, n)
    M = np.fft.rfft(mic, n)
    X = M * np.conj(R)
    X /= np.abs(X) + 1e-9
    cc = np.fft.irfft(X, n)[: max_lag + 1]
    k = int(np.argmax(np.abs(cc)))
    floor = float(np.median(np.abs(cc))) + 1e-12
    return k, float(np.abs(cc[k]) / floor)


class DelayMeter:
    """Mic ring buffer + pending references -> per-line delay estimates {"ms", "peak"}."""

    def __init__(self):
        self.mic: collections.deque = collections.deque()
        self.mic_t0 = 0.0          # ear time of the ring's first sample
        self.mic_n = 0
        self.pending: list[tuple[float, np.ndarray]] = []
        self.last_ref_end = -1e9

    def feed_ref(self, x: np.ndarray, t: float) -> None:
        if len(x) < MIN_REF_S * SR:
            self.last_ref_end = max(self.last_ref_end, t + len(x) / SR)
            return
        if t < self.last_ref_end - 0.05:     # overlaps the previous line's audio: ambiguous, skip
            self.last_ref_end = max(self.last_ref_end, t + len(x) / SR)
            return
        self.pending.append((t, np.asarray(x[: int(USE_REF_S * SR)], np.float32)))
        del self.pending[:-4]
        self.last_ref_end = max(self.last_ref_end, t + len(x) / SR)

    def feed_mic(self, x: np.ndarray, t_end: float) -> list[dict]:
        self.mic.append(x)
        self.mic_n += len(x)
        while self.mic and self.mic_n - len(self.mic[0]) >= RING_S * SR:
            self.mic_n -= len(self.mic.popleft())
        self.mic_t0 = t_end - self.mic_n / SR
        out = []
        keep = []
        for t, ref in self.pending:
            need = t + len(ref) / SR + MAX_DELAY_S + SETTLE_S
            if t_end < need:
                keep.append((t, ref))
                continue
            if t < self.mic_t0:
                continue                      # the ring no longer holds its start
            buf = np.concatenate(list(self.mic))
            a = int(round((t - self.mic_t0) * SR))
            seg = buf[a: a + len(ref) + int(MAX_DELAY_S * SR)]
            if len(seg) < len(ref):
                continue
            if float(np.sqrt(np.mean(ref ** 2))) < 1e-3:
                continue
            k, peak = gcc_phat(ref, seg, int(MAX_DELAY_S * SR))
            if peak >= MIN_PEAK:
                out.append({"t": "echo_delay", "ms": round(1000.0 * k / SR, 1), "peak": round(peak, 1),
                            "at": round(t, 2)})
        self.pending = keep
        return out
