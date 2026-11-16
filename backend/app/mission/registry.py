"""In-memory missions, keyed by id. The Director and the routes both go through here."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

from . import gameplay, sim

LOCK = threading.RLock()   # the live clock (POST /step), the session's orders and the routes touch one mission at once

MISSIONS: dict[str, sim.Mission] = {}
MAX_MISSIONS = 500
LAST_ACTIVE = [0.0]   # time.monotonic() of the last mission call: the video prefetch waits while a mission runs


def _touch() -> None:
    LAST_ACTIVE[0] = time.monotonic()


def create(site: str, seed: int | None = None, roles: list[str] | None = None, level: str = "cadet",
           save: bool = True) -> sim.Mission:
    """level (Settings / session prefs.level): cadet | commander, the difficulty band (docs/LEARNING_DESIGN.md §6.5)."""
    _touch()
    if len(MISSIONS) >= MAX_MISSIONS:  # drop the oldest
        MISSIONS.pop(next(iter(MISSIONS)))
    mid = "m-" + secrets.token_hex(4)
    if seed is None:
        seed = secrets.randbelow(1_000_000)
    m = sim.new_mission(mid, site, seed, roles, level=level)
    m.gp["level0"] = m.level   # a saved game and Restart shift replay from this level (later changes are journaled)
    if not save:
        m.gp["nosave"] = True  # a practice run never overwrites the player's saved mission
    MISSIONS[mid] = m
    return m


def get(mid: str) -> sim.Mission | None:
    return MISSIONS.get(mid)


def apply(mid: str, cmd: dict) -> dict:
    """{state, result:{ok, needs_confirm, say, readback, events}}; KeyError if no such mission."""
    _touch()
    m = MISSIONS[mid]
    with LOCK:
        out = m.apply(cmd)   # journaled by Mission.apply
        _autosave(m)
    out["result"].setdefault("needs_confirm", False)
    return out


def advance(mid: str, shifts: int = 1) -> dict:
    """End the shift (early): the clock runs to the next shift boundary."""
    _touch()
    m = MISSIONS[mid]
    with LOCK:
        evs = sim.advance(m, shifts)
        sim.record(m, ("advance", shifts))
        _autosave(m)
        return {"state": sim.to_state(m), "events": evs, "say": sim._shift_say(m, evs)}


def step(mid: str, dt_h: float) -> dict:
    """The live clock: `dt_h` mission hours pass (the client sends them while time runs). `live` is the frame at the
    fractional time, so the Sun, Earth and bars move smoothly between whole hours."""
    _touch()
    m = MISSIONS[mid]
    with LOCK:
        evs = sim.step(m, dt_h)
        if dt_h:
            sim.record(m, ("step", dt_h))
        _autosave(m)
        return {"state": sim.to_state(m), "events": evs, "live": sim.telemetry(m, m.frac, live=True)}


def skip(mid: str) -> dict:
    """Skip to the next event."""
    _touch()
    m = MISSIONS[mid]
    with LOCK:
        evs = sim.skip_to_event(m)
        sim.record(m, ("skip",))
        _autosave(m)
        return {"state": sim.to_state(m), "events": evs, "say": sim._skip_say(m, evs)}


# ---- [polish 2] Restart shift, chapter auto-save, Continue -------------------------------------------------------------
def _rebuild(m: sim.Mission, upto: int) -> sim.Mission:
    """A fresh mission with m's id, site, seed and level, with the first `upto` journaled inputs replayed."""
    level0 = m.gp.get("level0") or m.level
    n = sim.new_mission(m.id, m.site_id, m.seed, m.roles, level=level0)
    n.gp["level0"] = level0
    for e in m.journal[:upto]:
        sim.replay(n, e)
    n.gp["saved_chapters"] = len(n.gp.get("chapters", []))
    return n


def restart_shift(mid: str) -> dict:
    """Back to the start of this shift (the first input seen in it): the same storms, the same tasks."""
    _touch()
    m = MISSIONS[mid]
    with LOCK:
        idx = m.t_h // sim.SHIFT_H
        n = _rebuild(m, m.marks.get(idx, len(m.journal)))
        MISSIONS[mid] = n
        return {"state": sim.to_state(n), "events": [], "say": f"Back to the start of shift {n.t_h % 24 // sim.SHIFT_H + 1}, day {n.t_h // 24 + 1}."}


def save_dir() -> Path:
    from ..config import settings
    env = os.environ.get("MISSION_SAVE_DIR")
    return Path(env) if env else (settings.cache_dir or settings.data_dir) / "saves"


SAVE_V = 1


def _autosave(m: sim.Mission, force: bool = False) -> None:
    """The game saves itself after every meaningful change: an order, a skip, a shift end, and each whole mission hour
    the live clock passes (not every 1 s clock slice). It saves the inputs, not the state (the sim replays them), with
    an atomic write (temp file + rename), so a hard quit loses at most the last game hour and never leaves a half
    file. Practice missions (the academy) don't go through here."""
    if m.gp.get("nosave"):
        return
    key = (len(m.journal), m.t_h) if force else (m.t_h, sum(1 for e in m.journal if e[0] != "step"), m.over)
    if key == m.gp.get("saved_key"):
        return
    m.gp["saved_key"] = key
    m.gp["saved_chapters"] = len(m.gp.get("chapters", []))
    done = m.gp["saved_chapters"]
    try:
        d = save_dir()
        d.mkdir(parents=True, exist_ok=True)
        body = {"v": SAVE_V, "id": m.id, "site": m.site_id, "seed": m.seed, "roles": m.roles,
                "level0": m.gp.get("level0", m.level), "journal": m.journal, "chapter": done, "t_h": m.t_h,
                "over": m.over, "saved_at": time.time()}
        tmp = d / "mission.json.tmp"
        tmp.write_text(json.dumps(body))
        tmp.replace(d / "mission.json")
    except OSError:
        pass   # a read-only disk never stops the game


def saved() -> dict | None:
    """The auto-save, if there is one worth continuing: {site, chapter, day, level}."""
    try:
        b = json.loads((save_dir() / "mission.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(b, dict) or b.get("over") or b.get("v") != SAVE_V or not isinstance(b.get("journal"), list):
        return None
    try:
        name = sim.site(b["site"])["name"]
        int(b["t_h"]), int(b["chapter"]), int(b["seed"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"site": b["site"], "site_name": name, "chapter": b["chapter"], "day": b["t_h"] // 24 + 1,
            "level": b.get("level0"), "t_h": b["t_h"]}


def resume() -> sim.Mission | None:
    """Rebuild the auto-saved mission (a new id) at the chapter where it saved."""
    try:
        b = json.loads((save_dir() / "mission.json").read_text())
        _touch()
        mid = "m-" + secrets.token_hex(4)
        m = sim.new_mission(mid, b["site"], b["seed"], b.get("roles"), level=b.get("level0") or "cadet")
        m.gp["level0"] = b.get("level0") or m.level
        with LOCK:
            for e in b["journal"]:
                sim.replay(m, e)
        m.gp["saved_chapters"] = len(m.gp.get("chapters", []))
        if m.t_h != int(b["t_h"]):   # the replay didn't land where the save said (an older sim): not this game
            raise ValueError("save does not replay")
    except Exception:   # a corrupt, old or foreign save: never crash; set it aside and offer a new mission
        _discard()
        return None
    MISSIONS[mid] = m
    return m


def _discard() -> None:
    try:
        p = save_dir() / "mission.json"
        if p.exists():
            p.replace(p.with_suffix(".bad.json"))
    except OSError:
        pass
