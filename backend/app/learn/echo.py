"""Echo, per computer: this laptop's speaker -> microphone delay and its drift, and a per-device playback threshold,
learned from the ear's own numbers during normal use (docs/ON_DEVICE_LEARNING.md "Echo, per laptop").

Inputs (numbers only):
  - observe_delay(ms, peak): one per line we played, from the model server's DelayMeter (model_server/app/echo_delay.py:
    GCC-PHAT of the reference against the microphone, in memory);
  - observe_leak(leak, kind): the ear's playback_leak of a turn, labelled WITHOUT the leak itself so the threshold does not
    learn from its own decisions: "echo" = the router's text echo check matched one of our lines (turn_router.echo);
    "kid" = a turn the kid made over our playback that the app acted on (a barge-in, not a text echo).

Outputs:
  - delay_ms / drift (the median, the p10-p90 spread, and the change per hour of use) for the "What the app has learned"
    view and the diagnostics file;
  - ref_shift_s(): the reference stamp offset sent to the ear at session start (EarStream.tune): the measured delay
    minus a margin, so the canceller's 512 ms window holds the room, not the latency. Bounded to [0, SHIFT_MAX_S];
    off unless USE_SHIFT (docs/ARC_ABI2.md section 8 has the measurement that sets it);
  - threshold(): the playback-leak threshold for this computer, within [THR_MIN, THR_MAX], the shipped default until
    there is enough evidence on both sides and they separate.
"""
from __future__ import annotations

import time

import numpy as np

DELAY_MIN_MS, DELAY_MAX_MS = 10.0, 480.0
MIN_PEAK = 20.0                # = model_server echo_delay.MIN_PEAK
MIN_DELAYS = 6                 # estimates before the delay is "known"
SHIFT_MARGIN_MS = 25.0         # the reference stays this much ahead of the measured echo (jitter, drift)
SHIFT_MAX_S = 0.25
USE_SHIFT = False              # measured: the shift raises every leak, kid turns too; no gain (docs/ARC_ABI2.md 8)
THR_DEFAULT = 0.85             # as shipped (backend session.PLAYBACK_THRESHOLD)
THR_MIN, THR_MAX = 0.75, 0.95  # the per-device threshold never leaves this range
MIN_ECHO, MIN_KID = 20, 5


class DeviceEcho:
    def __init__(self, state: dict | None = None, clock=time.time, default_thr: float = THR_DEFAULT):
        st = state if isinstance(state, dict) else {}
        self.clock = clock
        self.default_thr = default_thr
        self.created = float(st.get("created") or clock())
        e = st.get("echo") or {}
        self.delays: list[float] = [float(x) for x in e.get("delays") or []][-64:]
        self.delay_at: list[float] = [float(x) for x in e.get("delay_at") or []][-64:]
        if len(self.delay_at) != len(self.delays):
            self.delay_at = [0.0] * len(self.delays)
        self.leak_echo: list[float] = [float(x) for x in e.get("leak_echo") or []][-128:]
        self.leak_kid: list[float] = [float(x) for x in e.get("leak_kid") or []][-128:]
        self.lines = int(e.get("lines", 0))

    def state(self) -> dict:
        return {"created": self.created, "echo": {"delays": self.delays, "delay_at": self.delay_at, "lines": self.lines,
                                                  "leak_echo": self.leak_echo, "leak_kid": self.leak_kid}}

    # ---- evidence ----
    def observe_delay(self, ms, peak) -> bool:
        try:
            ms, peak = float(ms), float(peak)
        except (TypeError, ValueError):
            return False
        if not (DELAY_MIN_MS <= ms <= DELAY_MAX_MS) or peak < MIN_PEAK:
            return False
        self.delays = (self.delays + [round(ms, 1)])[-64:]
        self.delay_at = (self.delay_at + [round((self.clock() - self.created) / 60.0, 2)])[-64:]
        self.lines += 1
        return True

    def observe_leak(self, leak, kind: str) -> bool:
        try:
            leak = float(leak)
        except (TypeError, ValueError):
            return False
        if not 0.0 <= leak <= 1.0:
            return False
        if kind == "echo":
            self.leak_echo = (self.leak_echo + [round(leak, 3)])[-128:]
        elif kind == "kid":
            self.leak_kid = (self.leak_kid + [round(leak, 3)])[-128:]
        else:
            return False
        return True

    # ---- what was learned ----
    def known(self) -> bool:
        return len(self.delays) >= MIN_DELAYS

    def delay_ms(self) -> float | None:
        return round(float(np.median(self.delays)), 1) if self.known() else None

    def spread_ms(self) -> tuple[float, float] | None:
        if not self.known():
            return None
        p10, p90 = np.percentile(self.delays, [10, 90])
        return round(float(p10), 1), round(float(p90), 1)

    def drift_ms_per_h(self) -> float | None:
        """The delay's trend over the time it was measured (ms per hour of wall time); None until known."""
        if not self.known() or len(set(self.delay_at)) < 3:
            return None
        x, y = np.array(self.delay_at, float), np.array(self.delays, float)
        if x.max() - x.min() < 1.0:          # under a minute of history: no trend
            return None
        a = np.polyfit(x, y, 1)[0]
        return round(float(a * 60.0), 1)

    def ref_shift_s(self) -> float:
        if not USE_SHIFT or not self.known():
            return 0.0
        lo = float(np.percentile(self.delays, 10))
        return round(min(SHIFT_MAX_S, max(0.0, (lo - SHIFT_MARGIN_MS) / 1000.0)), 3)

    def threshold(self) -> float:
        """Between this computer's echo leaks (low end) and its kid-over-playback leaks (high end), when both are known
        and separate; else the shipped default. Always within [THR_MIN, THR_MAX]."""
        if len(self.leak_echo) < MIN_ECHO or len(self.leak_kid) < MIN_KID:
            return self.default_thr
        e10 = float(np.percentile(self.leak_echo, 10))
        k90 = float(np.percentile(self.leak_kid, 90))
        if k90 >= e10:
            return self.default_thr
        return round(min(THR_MAX, max(THR_MIN, (e10 + k90) / 2.0)), 3)

    def summary(self) -> dict:
        sp = self.spread_ms()
        return {"lines_measured": self.lines, "delay_ms": self.delay_ms(),
                "delay_p10_ms": sp[0] if sp else None, "delay_p90_ms": sp[1] if sp else None,
                "drift_ms_per_h": self.drift_ms_per_h(), "ref_shift_ms": round(1000 * self.ref_shift_s()),
                "playback_threshold": self.threshold(), "echo_turns_seen": len(self.leak_echo),
                "kid_over_playback_seen": len(self.leak_kid)}
