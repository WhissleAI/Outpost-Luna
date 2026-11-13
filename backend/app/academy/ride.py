"""The check ride: a short mission on the real simulator (fixed site and seed, one real DONKI storm, 2 days)."""
from __future__ import annotations

import math
import secrets

from ..mission import sim

RIDES: dict[str, dict] = {}
MAX_RIDES = 300
MISS_LIMIT = 3   # misses on one step before the ride moves on without that order


def start(cfg: dict) -> dict:
    if len(RIDES) >= MAX_RIDES:
        RIDES.pop(next(iter(RIDES)))
    rid = "r-" + secrets.token_hex(4)
    m = sim.new_mission(rid, cfg["site"], cfg.get("seed", 0))
    ev = next(e for e in sim.storms_catalog()["events"] if e["id"] == cfg["storm_event"])
    m.storms = [sim.Storm(cfg["storm_start_h"], {1: 12, 2: 24, 3: 36}[ev["severity"]], ev)]
    m.failure_h = 10 ** 6   # no array failure inside a 2-day ride
    RIDES[rid] = {"m": m, "cfg": cfg, "step": 0, "misses": 0, "missed": [], "done": False}
    return RIDES[rid]


def get(rid: str | None) -> dict | None:
    return RIDES.get(rid or "")


def advance(ride: dict, how) -> list:
    m, cfg = ride["m"], ride["cfg"]
    if how in (None, 0):
        return []
    if how == "storm":
        st = m.storms[0]
        n = math.ceil(max(0, st.start_h + st.dur_h - m.t_h) / sim.SHIFT_H)
    elif how == "end":
        n = math.ceil(max(0, cfg["mission_h"] - m.t_h) / sim.SHIFT_H)
    else:
        n = int(how)
    return sim.advance(m, n) if n > 0 else []


def hud(ride: dict) -> dict:
    """The few numbers the Academy HUD shows (a subset of the mission State)."""
    s = sim.to_state(ride["m"])
    return {k: s[k] for k in ("day", "shift", "mission_time_h", "resources", "loads", "env", "rover", "shelter", "over",
                              "outcome", "alerts")}
