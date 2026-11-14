"""In-memory missions, keyed by id. The Director and the routes both go through here."""
from __future__ import annotations

import secrets
import threading

from . import sim

LOCK = threading.RLock()   # the live clock (POST /step), the session's orders and the routes touch one mission at once

MISSIONS: dict[str, sim.Mission] = {}
MAX_MISSIONS = 500


def create(site: str, seed: int | None = None, roles: list[str] | None = None, level: str = "cadet") -> sim.Mission:
    """level (Settings / session prefs.level): cadet | commander, the difficulty band (docs/LEARNING_DESIGN.md §6.5)."""
    if len(MISSIONS) >= MAX_MISSIONS:  # drop the oldest
        MISSIONS.pop(next(iter(MISSIONS)))
    mid = "m-" + secrets.token_hex(4)
    if seed is None:
        seed = secrets.randbelow(1_000_000)
    m = sim.new_mission(mid, site, seed, roles, level=level)
    MISSIONS[mid] = m
    return m


def get(mid: str) -> sim.Mission | None:
    return MISSIONS.get(mid)


def apply(mid: str, cmd: dict) -> dict:
    """{state, result:{ok, needs_confirm, say, readback, events}}; KeyError if no such mission."""
    m = MISSIONS[mid]
    with LOCK:
        out = m.apply(cmd)
    out["result"].setdefault("needs_confirm", False)
    return out


def advance(mid: str, shifts: int = 1) -> dict:
    """End the shift (early): the clock runs to the next shift boundary."""
    m = MISSIONS[mid]
    with LOCK:
        evs = sim.advance(m, shifts)
        return {"state": sim.to_state(m), "events": evs, "say": sim._shift_say(m, evs)}


def step(mid: str, dt_h: float) -> dict:
    """The live clock: `dt_h` mission hours pass (the client sends them while time runs). `live` is the frame at the
    fractional time, so the Sun, Earth and bars move smoothly between whole hours."""
    m = MISSIONS[mid]
    with LOCK:
        evs = sim.step(m, dt_h)
        return {"state": sim.to_state(m), "events": evs, "live": sim.telemetry(m, m.frac, live=True)}


def skip(mid: str) -> dict:
    """Skip to the next event."""
    m = MISSIONS[mid]
    with LOCK:
        evs = sim.skip_to_event(m)
        return {"state": sim.to_state(m), "events": evs, "say": sim._skip_say(m, evs)}
