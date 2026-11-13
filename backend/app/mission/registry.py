"""In-memory missions, keyed by id. The Director and the routes both go through here."""
from __future__ import annotations

import secrets

from . import sim

MISSIONS: dict[str, sim.Mission] = {}
MAX_MISSIONS = 500


def create(site: str, seed: int | None = None, roles: list[str] | None = None) -> sim.Mission:
    if len(MISSIONS) >= MAX_MISSIONS:  # drop the oldest
        MISSIONS.pop(next(iter(MISSIONS)))
    mid = "m-" + secrets.token_hex(4)
    if seed is None:
        seed = secrets.randbelow(1_000_000)
    m = sim.new_mission(mid, site, seed, roles)
    MISSIONS[mid] = m
    return m


def get(mid: str) -> sim.Mission | None:
    return MISSIONS.get(mid)


def apply(mid: str, cmd: dict) -> dict:
    """{state, result:{ok, needs_confirm, say, readback, events}}; KeyError if no such mission."""
    m = MISSIONS[mid]
    out = m.apply(cmd)
    out["result"].setdefault("needs_confirm", False)
    return out


def advance(mid: str, shifts: int = 1) -> dict:
    m = MISSIONS[mid]
    evs = sim.advance(m, shifts)
    return {"state": sim.to_state(m), "events": evs, "say": sim._shift_say(m, evs)}
