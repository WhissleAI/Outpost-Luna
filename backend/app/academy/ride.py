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
    # The ride starts `start_h` into the April 2026 window, when Earth is up at the site (Horizons), so Houston can
    # really warn the cadet. At hour 0 Earth is below Shackleton Rim's horizon: no radio without a relay.
    t0 = int(cfg.get("start_h", 0))
    m.t_h = t0
    ev = next(e for e in sim.storms_catalog()["events"] if e["id"] == cfg["storm_event"])
    m.storms = [sim.Storm(t0 + cfg["storm_start_h"], sim.storm_duration_h(ev), ev)]
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
        n = math.ceil(max(0, int(cfg.get("start_h", 0)) + cfg["mission_h"] - m.t_h) / sim.SHIFT_H)
    else:
        n = int(how)
    return sim.advance(m, n) if n > 0 else []


def hud(ride: dict) -> dict:
    """The few numbers the Academy HUD shows (a subset of the mission State). [0.3.12] `site` names the ride's site on
    the cabin's clock ("Shift 1 · Shackleton Crater Rim", not "Shift 1 ·"), and `ride` counts the ride's own days
    ("Day 1 of 2"): the ride starts `start_h` into the mission window, so the sim's own day would read "Day 8"."""
    s = sim.to_state(ride["m"])
    out = {k: s[k] for k in ("day", "shift", "mission_time_h", "resources", "loads", "env", "rover", "shelter", "over",
                             "outcome", "alerts", "site")}
    cfg = ride["cfg"]
    days = max(1, math.ceil(cfg["mission_h"] / 24))
    out["ride"] = {"day": min(days, (ride["m"].t_h - int(cfg.get("start_h", 0))) // 24 + 1), "days": days}
    return out
