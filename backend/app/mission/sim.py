"""Mission Trainer simulation: a lunar south-pole outpost over 10 days, in 6-hour shifts.

Pure and deterministic per (site, seed): no clock, no network, no global RNG. All inputs come from
backend/data/mission/*.json (built by pipeline/mission_data.py from JPL Horizons, NASA and NOAA sources).
Schema: docs/MISSION_CONTRACT.md.
"""
from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "mission"

SHIFT_H = 6
MISSION_H = 240
COMM_DELAY_S = 2.6
LOADS = ("shields", "life_support", "greenhouse", "science", "rover", "comms", "heaters")
DEFAULT_LOADS = {"shields": 20, "life_support": 30, "greenhouse": 15, "science": 15, "rover": 10, "comms": 5, "heaters": 5}

# --- Game tuning (all in % of battery / % of life-support need per hour). Documented in debrief data_used. ---
SOLAR_GEN = 6.0           # %/h battery gain with full Sun on healthy arrays
BACKUP_GEN = 1.0          # %/h from a small always-on backup generator (game stand-in for NASA's Fission Surface
                          # Power project, https://www.nasa.gov/missions/artemis/fission-surface-power/)
BASE_DRAW = 4.0           # %/h battery draw at the default split
LOAD_WEIGHT = {"shields": 1.4, "life_support": 1.0, "greenhouse": 1.2, "science": 0.8, "rover": 1.0, "comms": 0.6,
               "heaters": 1.0}
SHELTER_DRAW = 0.3        # in the shelter the outpost hibernates: only life support and heat really run
LS_USE = 1.0              # crew uses 0.8 %/h of life support
LS_FROM_RECYCLER = 0.6    # at a 30% share
LS_FROM_GREENHOUSE = 0.3  # at a 15% share
FREEZE_LOSS = 0.6         # %/h lost when heaters < 5% in darkness (water lines freeze)
SCIENCE_RATE = 1.0        # points/h at a 15% share
ICE_GAIN = 18.0           # life support % per ice delivery
ROVER_POWER = 6.0         # % battery to charge the rover per trip
EXPLORE_SCIENCE = 25.0
HOUSTON_POWER = 2.0
HOUSTON_SCIENCE = 2.0     # crew time on the call
DOSE_LIMIT = 50.0


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def sites() -> list[dict]:
    return _load("sites.json")["sites"]


def site(site_id: str) -> dict:
    for s in sites():
        if s["id"] == site_id:
            return s
    raise KeyError(site_id)


def ephemeris(site_id: str) -> dict:
    return _load(f"ephemeris_{site_id}.json")


def storms_catalog() -> dict:
    return _load("donki_events.json")


def radiation() -> dict:
    return _load("radiation.json")


def public_site(s: dict) -> dict:
    keys = ("id", "name", "lat", "lon", "sunlight_pct", "ice", "earth_visible_pct", "notes", "sources")
    out = {k: s.get(k) for k in keys}
    out["window_sunlit_pct"] = s.get("window_sunlit_pct")
    return out


@dataclass
class Storm:
    start_h: int
    dur_h: int
    event: dict

    def active(self, t: float) -> bool:
        return self.start_h <= t < self.start_h + self.dur_h


@dataclass
class Mission:
    id: str
    site_id: str
    seed: int
    roles: list[str] = field(default_factory=list)
    t_h: int = 0
    power: float = 85.0
    life: float = 80.0
    dose: float = 0.0
    science: float = 0.0
    science_sent: float = 0.0
    loads: dict = field(default_factory=lambda: dict(DEFAULT_LOADS))
    shelter: bool = False
    array_eff: float = 1.0
    rover: dict = field(default_factory=lambda: {"busy": False, "task": None, "eta_h": 0})
    storms: list[Storm] = field(default_factory=list)
    failure_h: int = 0
    zero_power_shifts: int = 0
    over: bool = False
    outcome: str | None = None
    lose_reason: str | None = None
    pending: dict | None = None
    log: list = field(default_factory=list)
    events: list = field(default_factory=list)   # every event ever (for debrief)
    storm_dose: dict = field(default_factory=dict)  # storm id -> mSv taken during it
    ice_runs: int = 0
    houston_calls: int = 0
    shifts: list = field(default_factory=list)    # per-shift snapshots for the debrief timeline
    level: str = "cadet"                          # Settings: cadet | commander (passed through; no effect here yet)

    # Convenience API for the Director / registry (contract: State and command result shapes).
    def state(self) -> dict:
        return to_state(self)

    def to_dict(self) -> dict:
        return to_state(self)

    def apply(self, cmd: dict) -> dict:
        result = apply_command(self, cmd)
        return {"state": to_state(self), "result": result}


# ---------------------------------------------------------------- setup

def new_mission(mid: str, site_id: str, seed: int | None = None, roles: list[str] | None = None,
                level: str = "cadet") -> Mission:
    s = site(site_id)  # KeyError on unknown site
    seed = 0 if seed is None else int(seed)
    rng = random.Random(f"{site_id}:{seed}")
    m = Mission(id=mid, site_id=s["id"], seed=seed, roles=list(roles or []), level=level or "cadet")
    cat = storms_catalog()["events"]
    n = 2 + (rng.random() < 0.5)
    picks = rng.sample(cat, n)
    # One storm in each part of the mission so the kid meets one early-ish and one late.
    slots = [(18, 90), (96, 170), (150, 216)][:n]
    for ev, (lo, hi) in zip(picks, slots):
        start = rng.randrange(lo, hi) // 6 * 6 + rng.choice([0, 2, 4])
        dur = {1: 12, 2: 24, 3: 36}[ev["severity"]]
        m.storms.append(Storm(start, dur, ev))
    m.failure_h = rng.randrange(60, 180)
    m.log.append({"t_h": 0, "kind": "event", "text": f"Outpost online at {s['name']}. Ten days to go."})
    return m


# ---------------------------------------------------------------- environment

def _eph_at(site_id: str, key: str, t: float) -> float:
    arr = ephemeris(site_id)[key]
    t = max(0.0, min(t, len(arr) - 1))
    i = int(t)
    j = min(i + 1, len(arr) - 1)
    return arr[i] + (arr[j] - arr[i]) * (t - i)


def _power_site(s: dict) -> tuple[str, float]:
    pf = s.get("power_from")
    return (pf["site"], pf["efficiency"]) if pf else (s["id"], 1.0)


def _comm_site(s: dict) -> str:
    cf = s.get("comm_from")
    return cf["site"] if cf else s["id"]


def env_at(m: Mission, t: float) -> dict:
    s = site(m.site_id)
    psite, eff = _power_site(s)
    ps = site(psite)
    sun = _eph_at(m.site_id, "sun_elev_deg", t)
    psun = _eph_at(psite, "sun_elev_deg", t)
    sun_frac = max(0.0, min(1.0, (psun - ps["horizon_deg"]) / 0.5 + 0.5)) * eff
    in_sun = (sun > s["horizon_deg"]) if not s.get("power_from") else False
    cs = site(_comm_site(s))
    earth = _eph_at(m.site_id, "earth_elev_deg", t)
    cearth = _eph_at(cs["id"], "earth_elev_deg", t)
    earth_visible = cearth > min(cs["horizon_deg"], 0)
    storm = next((st for st in m.storms if st.active(t)), None)
    return {"sun_elev_deg": round(sun, 3), "in_sun": in_sun, "sun_frac": sun_frac,
            "earth_elev_deg": round(earth, 3), "earth_visible": earth_visible, "storm": storm}


def next_comm_window_h(m: Mission, t: float) -> int | None:
    for k in range(0, MISSION_H - int(t) + 1):
        if env_at(m, t + k)["earth_visible"]:
            return k
    return None


# ---------------------------------------------------------------- physics

def draw_per_h(m: Mission) -> float:
    w = sum(m.loads[k] * LOAD_WEIGHT[k] for k in LOADS) / sum(DEFAULT_LOADS[k] * LOAD_WEIGHT[k] for k in LOADS)
    d = BASE_DRAW * w
    return d * (SHELTER_DRAW if m.shelter else 1.0)


def dose_rate(m: Mission, t: float, env: dict | None = None) -> float:
    env = env or env_at(m, t)
    g = radiation()["game"]
    base = g["game_baseline_msv_per_h"]
    storm = env["storm"]
    mult = storm.event["dose_multiplier"] if storm else 1.0
    shield = g["shields_max_effect"] * min(1.0, m.loads["shields"] / 30.0)
    if m.shelter:
        shelter = g["shelter_factor_storm"] if storm else g["shelter_factor_quiet"]
    else:
        shelter = 1.0
    eva = 1.5 if (m.rover["busy"] and m.rover["task"] != "return_home") else 1.0  # crew out driving
    return base * mult * (1 - shield) * shelter * eva


def _step_hour(m: Mission, out_events: list):
    t = m.t_h
    env = env_at(m, t)
    gen = SOLAR_GEN * m.array_eff * env["sun_frac"] + BACKUP_GEN
    draw = draw_per_h(m)
    if m.power + gen - draw >= 0:
        p = 1.0
    else:
        p = max(0.0, min(1.0, (m.power + gen) / draw)) if draw > 0 else 1.0
    m.power = max(0.0, min(100.0, m.power + gen - draw * p))
    L = m.loads
    gain = LS_FROM_RECYCLER * (L["life_support"] / 30.0) * p + LS_FROM_GREENHOUSE * (L["greenhouse"] / 15.0) * p
    if L["heaters"] < 5 and not env["in_sun"]:
        gain -= FREEZE_LOSS
    if L["heaters"] * p < 3 and env["sun_frac"] == 0:
        gain -= FREEZE_LOSS / 2
    m.life = max(0.0, min(100.0, m.life + gain - LS_USE))
    if not m.shelter:
        m.science += SCIENCE_RATE * (L["science"] / 15.0) * p
    # downlink: unsent science goes home when Earth is up and comms are on
    if env["earth_visible"] and L["comms"] > 0 and p > 0:
        rate = 3.0 * (L["comms"] / 5.0)
        sent = min(m.science - m.science_sent, rate)
        m.science_sent += max(0.0, sent)
    r = dose_rate(m, t, env)
    m.dose += r
    if env["storm"]:
        sid = env["storm"].event["id"]
        m.storm_dose[sid] = m.storm_dose.get(sid, 0.0) + r
    m.t_h += 1
    _rover_tick(m, out_events)
    _hour_events(m, t, env, out_events)


def _rover_tick(m: Mission, out: list):
    rv = m.rover
    if not rv["busy"]:
        return
    rv["eta_h"] -= 1
    if rv["eta_h"] > 0:
        return
    task = rv["task"]
    text = "Rover is back at base."
    if task == "collect_ice":
        m.life = min(100.0, m.life + ICE_GAIN)
        m.ice_runs += 1
        text = f"Rover's back with ice. Life support up {ICE_GAIN:.0f}%."
    elif task == "repair_array":
        m.array_eff = 1.0
        text = "Rover fixed the solar arrays. Full power again."
    elif task == "explore":
        m.science += EXPLORE_SCIENCE
        text = f"Rover's back with samples. Science up {EXPLORE_SCIENCE:.0f}."
    rv.update(busy=False, task=None, eta_h=0)
    _emit(m, out, "rover_back", text)


def _emit(m: Mission, out: list, kind: str, text: str, source=None, real_date=None):
    ev = {"t_h": m.t_h, "kind": kind, "text": text, "source": source, "real_date": real_date}
    out.append(ev)
    m.events.append(ev)
    m.log.append({"t_h": m.t_h, "text": text, "kind": "event"})


def _hour_events(m: Mission, t: int, env_before: dict, out: list):
    env = env_at(m, m.t_h)
    s = site(m.site_id)
    if env_before["in_sun"] != env["in_sun"] and not s.get("power_from"):
        _emit(m, out, "sunrise" if env["in_sun"] else "sunset",
              "Sunrise. Solar arrays charging." if env["in_sun"] else
              "Sunset. Batteries only until the Sun returns.",
              {"title": "JPL Horizons", "url": "https://ssd-api.jpl.nasa.gov/doc/horizons.html"})
    if env_before["earth_visible"] != env["earth_visible"]:
        _emit(m, out, "comm_open" if env["earth_visible"] else "comm_closed",
              "Earth is up. You can call Houston." if env["earth_visible"] else
              "Earth has set. No radio until it rises.",
              {"title": "JPL Horizons", "url": "https://ssd-api.jpl.nasa.gov/doc/horizons.html"})
    for st in m.storms:
        ev = st.event
        if m.t_h == st.start_h - 6 and env["earth_visible"]:
            _emit(m, out, "solar_storm", f"Houston: solar flare. Storm in about "
                  f"6 hours.", ev["source"], ev["date"])
        if m.t_h == st.start_h:
            _emit(m, out, "solar_storm", f"Solar storm! The real {ev['date']} "
                  f"{'flare' if ev['type'] == 'flare' else 'storm'}. "
                  f"Radiation {ev['dose_multiplier']}x normal.", ev["source"], ev["date"])
        if m.t_h == st.start_h + st.dur_h:
            _emit(m, out, "storm_end", f"The storm has passed. Radiation is back to normal.",
                  ev["source"], ev["date"])
    if m.t_h == m.failure_h and not m.over:
        m.array_eff = 0.5
        _emit(m, out, "failure", "Micrometeorite! Arrays at half power. "
              "Rover can fix them.", None, None)


def _check_end(m: Mission, out: list):
    if m.over:
        return
    if m.life <= 0:
        m.over, m.outcome, m.lose_reason = True, "life_support_out", "life_support"
        _emit(m, out, "failure", "Life support ran out. Mission over. The crew heads home.")
    elif m.dose > DOSE_LIMIT:
        m.over, m.outcome, m.lose_reason = True, "dose_limit", "dose"
        _emit(m, out, "failure", f"The crew passed the {DOSE_LIMIT:.0f} mSv limit. Mission over.")
    elif m.zero_power_shifts >= 2:
        m.over, m.outcome, m.lose_reason = True, "power_out", "power"
        _emit(m, out, "failure", "Batteries empty for two shifts. Mission over.")
    elif m.t_h >= MISSION_H:
        m.over, m.outcome = True, "survived"
        _emit(m, out, "mission_complete", "Day 10 done. The outpost made it. Welcome home, Commander.")


def advance(m: Mission, shifts: int = 1) -> list:
    out: list = []
    for _ in range(max(1, int(shifts))):
        if m.over:
            break
        was_low = m.power < 20
        for _h in range(SHIFT_H):
            _step_hour(m, out)
            if m.life <= 0 or m.dose > DOSE_LIMIT:
                break
        m.zero_power_shifts = m.zero_power_shifts + 1 if m.power <= 0.01 else 0
        if m.power < 20 and not was_low and not m.over:
            _emit(m, out, "low_power", f"Battery low: {m.power:.0f}%. Cut some loads.")
        if dose_rate(m, m.t_h) > 0.3 and not any(e["kind"] == "dose_alert" and e["t_h"] == m.t_h for e in out):
            _emit(m, out, "dose_alert", f"Radiation high: {dose_rate(m, m.t_h):.2f} mSv an hour.")
        m.pending = None
        _check_end(m, out)
        m.shifts.append({"t_h": m.t_h, "power": round(m.power, 1), "life_support": round(m.life, 1),
                         "dose_msv": round(m.dose, 2), "events": [e["kind"] for e in out if e["t_h"] > m.t_h - SHIFT_H]})
    return out


# ---------------------------------------------------------------- commands

def _amount(cur: int, amount: dict | None) -> int:
    amount = amount or {"kind": "percent", "value": cur}
    kind, v = amount.get("kind", "percent"), amount.get("value")
    if kind == "percent":
        return int(v if v is not None else cur)
    if kind == "delta":
        return cur + int(v or 0)
    if kind == "all":
        return 100
    if kind == "half":
        return 50
    if kind == "little":
        return cur + (-5 if (v is not None and v < 0) else 5)
    if kind == "none":
        return 0
    raise ValueError(f"unknown amount kind {kind}")


def reallocate(loads: dict, to: str, target: int, frm: str | None = None) -> dict:
    target = max(0, min(100, target))
    new = dict(loads)
    diff = target - new[to]
    if frm and frm in new and frm != to:
        take = min(diff, new[frm]) if diff > 0 else diff
        new[frm] -= take
        new[to] += take
        return new
    new[to] = target
    others = [k for k in LOADS if k != to]
    rest = 100 - target
    tot = sum(loads[k] for k in others)
    if tot == 0:
        for k in others:
            new[k] = rest // len(others)
    else:
        for k in others:
            new[k] = int(loads[k] * rest / tot)
    # fix rounding onto the biggest other load
    gap = 100 - sum(new.values())
    if gap:
        k = max(others, key=lambda k: new[k]) if gap < 0 else max(others, key=lambda k: loads[k])
        new[k] += gap
    return new


def _risky(m: Mission, cmd: dict) -> str | None:
    t = cmd.get("type")
    if t == "allocate":
        to = cmd.get("to")
        target = _amount(m.loads[to], cmd.get("amount"))
        if target >= 90:
            return f"That puts {target}% into {to.replace('_', ' ')}, almost nothing else. Are you sure?"
        if to in ("heaters", "life_support") and target <= 0:
            return f"Turning off {to.replace('_', ' ')} can hurt the crew. Are you sure?"
    if t == "dispatch" and cmd.get("task") != "return":
        env = env_at(m, m.t_h)
        soon = any(st.start_h - 6 <= m.t_h < st.start_h + st.dur_h for st in m.storms)
        if env["storm"] or (soon and env["earth_visible"]):
            return "Storm's on. Driving now means extra radiation. Send the rover anyway?"
    if t == "shelter" and not cmd.get("on") and env_at(m, m.t_h)["storm"]:
        return "The storm is still going. Leave the shelter anyway?"
    return None


def readback(cmd: dict) -> str:
    t = cmd.get("type")
    if t == "allocate":
        a = cmd.get("amount") or {}
        return f"Set {cmd.get('to', '').replace('_', ' ')} power: {a.get('kind')} {a.get('value') if a.get('value') is not None else ''}".strip()
    if t == "dispatch":
        return f"Send the rover to {str(cmd.get('task', '')).replace('_', ' ')}"
    if t == "shelter":
        return "Crew into the storm shelter" if cmd.get("on") else "Crew out of the shelter"
    if t == "call_houston":
        return "Calling Houston"
    return t or ""


def apply_command(m: Mission, cmd: dict) -> dict:
    """Returns {ok, needs_confirm?, say, readback, events}. Mutates m."""
    t = cmd.get("type")
    if m.over and t not in ("query",):
        return {"ok": False, "say": "The mission is over. Open your debrief.", "readback": "", "events": []}
    if t == "confirm":
        if not m.pending:
            return {"ok": False, "say": "Nothing to confirm.", "readback": "", "events": []}
        pend, m.pending = m.pending, None
        return _execute(m, pend)
    if t == "cancel":
        had = m.pending is not None
        m.pending = None
        return {"ok": True, "say": "Cancelled. Nothing changed." if had else "Nothing to cancel.", "readback": "",
                "events": []}
    if t == "end_shift":
        evs = advance(m, 1)
        return {"ok": True, "say": _shift_say(m, evs), "readback": "End shift", "events": evs}
    if t == "rule":  # standing rules live in the voice layer; never reach the sim
        return {"ok": True, "say": "", "readback": "", "events": []}
    if t == "query":
        return {"ok": True, "say": status_say(m, cmd.get("what", "all")), "readback": "", "events": []}
    if t not in ("allocate", "dispatch", "shelter", "call_houston"):
        return {"ok": False, "say": f"I don't know that order: {t!r}.", "readback": "", "events": []}
    try:
        warn = _risky(m, cmd)
    except (KeyError, ValueError) as e:
        return {"ok": False, "say": f"I couldn't do that: {e}", "readback": "", "events": []}
    if warn:
        m.pending = cmd
        return {"ok": True, "needs_confirm": True, "say": warn,
                "readback": readback(cmd), "events": []}
    return _execute(m, cmd)


def _execute(m: Mission, cmd: dict) -> dict:
    t = cmd["type"]
    rb = readback(cmd)
    evs: list = []
    if t == "allocate":
        to = cmd.get("to")
        if to not in LOADS:
            return {"ok": False, "say": f"There is no load called {to}.", "readback": rb, "events": []}
        target = _amount(m.loads[to], cmd.get("amount"))
        m.loads = reallocate(m.loads, to, target, cmd.get("from"))
        say = f"Copy. {to.replace('_', ' ').capitalize()} now at {m.loads[to]}%."
        m.log.append({"t_h": m.t_h, "kind": "command", "text": say})
        return {"ok": True, "say": say, "readback": rb, "events": evs}
    if t == "dispatch":
        task = cmd.get("task")
        rv = m.rover
        if task == "return":
            if not rv["busy"]:
                return {"ok": False, "say": "The rover is already home.", "readback": rb, "events": []}
            rv.update(task="return_home", eta_h=max(1, rv["eta_h"] // 2))
            say = f"Rover turning around. Home in {rv['eta_h']} hours."
            m.log.append({"t_h": m.t_h, "kind": "command", "text": say})
            return {"ok": True, "say": say, "readback": rb, "events": []}
        if rv["busy"]:
            return {"ok": False, "say": f"The rover is busy. Back in {rv['eta_h']} hours.",
                    "readback": rb, "events": []}
        if m.shelter:
            return {"ok": False, "say": "The crew is in the shelter. Come out first.",
                    "readback": rb, "events": []}
        if task not in ("collect_ice", "repair_array", "explore"):
            return {"ok": False, "say": f"The rover can't do {task!r}.", "readback": rb, "events": []}
        s = site(m.site_id)
        eta = {"collect_ice": max(4, 2 * s.get("rover_to_ice_h", 8) + 2), "repair_array": 6, "explore": 12}[task]
        if m.power < ROVER_POWER:
            return {"ok": False, "say": "Not enough battery to charge the rover.", "readback": rb, "events": []}
        m.power -= ROVER_POWER
        m.science = max(0.0, m.science - 1.0)  # crew time driving instead of experiments
        rv.update(busy=True, task=task, eta_h=eta)
        say = (f"Rover back in about {eta} hours. "
               f"It used {ROVER_POWER:.0f}% battery.")
        m.log.append({"t_h": m.t_h, "kind": "command", "text": say})
        return {"ok": True, "say": say, "readback": rb, "events": []}
    if t == "shelter":
        on = bool(cmd.get("on", True))
        if on and m.rover["busy"]:
            return {"ok": False, "say": "The rover crew is still outside. Call them home first.", "readback": rb,
                    "events": []}
        m.shelter = on
        say = ("Crew in the shelter. Much less radiation, but science stops."
               if on else "Crew is out. Science can start again.")
        m.log.append({"t_h": m.t_h, "kind": "command", "text": say})
        return {"ok": True, "say": say, "readback": rb, "events": []}
    if t == "call_houston":
        env = env_at(m, m.t_h)
        if not env["earth_visible"]:
            n = next_comm_window_h(m, m.t_h)
            return {"ok": False, "say": "Earth has set, so Houston can't hear us. " +
                    (f"Next window in about {n} hours." if n is not None else "No window left this mission."),
                    "readback": rb, "events": []}
        if m.power < HOUSTON_POWER:
            return {"ok": False, "say": "Not enough battery for the big antenna.", "readback": rb, "events": []}
        m.power -= HOUSTON_POWER
        m.science = max(0.0, m.science - HOUSTON_SCIENCE)
        m.houston_calls += 1
        nxt = next((st for st in m.storms if st.start_h > m.t_h), None)
        tip = (f"Active region on the Sun. Storm likely in about {nxt.start_h - m.t_h} hours."
               if nxt and nxt.start_h - m.t_h <= 48 else "Space weather looks quiet for two days.")
        say = f"Houston here. Your words took {COMM_DELAY_S/2:.1f} seconds to reach us. {tip}"
        m.log.append({"t_h": m.t_h, "kind": "houston", "text": say})
        return {"ok": True, "say": say, "readback": rb, "events": [], "delay_ms": int(COMM_DELAY_S * 1000)}
    return {"ok": False, "say": "?", "readback": rb, "events": []}


def _shift_say(m: Mission, evs: list) -> str:
    if m.over:
        return evs[-1]["text"] if evs else "Mission over."
    bits = [f"Day {m.t_h // 24 + 1}, shift {(m.t_h % 24) // SHIFT_H + 1}."]
    bits += [e["text"] for e in evs[-1:]]   # the latest news only: the spoken line stays a breath long
    bits.append(f"Power {m.power:.0f}%, air {m.life:.0f}%, dose {m.dose:.1f} mSv.")
    return " ".join(bits)


def status_say(m: Mission, what: str = "all") -> str:
    env = env_at(m, m.t_h)
    parts = {
        "power": f"Battery at {m.power:.0f}%." + (" The Sun is up." if env["in_sun"] else " It's dark."),
        "life_support": f"Life support at {m.life:.0f}%.",
        "dose": f"Crew dose: {m.dose:.1f} of {DOSE_LIMIT:.0f} mSv.",
        "storm": (f"A real solar storm from {env['storm'].event['date']} is hitting now." if env["storm"]
                  else "No storm."),
        "comms": ("Earth is up. Houston can hear us." if env["earth_visible"] else
                  f"Earth has set. Next window in about {next_comm_window_h(m, m.t_h)} hours."),
    }
    parts["oxygen"] = parts["life_support"]
    if what in parts:
        return parts[what]
    return " ".join(parts[k] for k in ("power", "life_support", "dose", "storm", "comms"))


# ---------------------------------------------------------------- views

def alerts(m: Mission, t: float | None = None) -> list[str]:
    t = m.t_h if t is None else t
    a = []
    if m.power < 20:
        a.append("low_power")
    if m.life < 25:
        a.append("life_support_low")
    if dose_rate(m, t) > 0.3:
        a.append("dose_rate_high")
    if m.dose > 0.8 * DOSE_LIMIT:
        a.append("dose_near_limit")
    if env_at(m, t)["storm"]:
        a.append("solar_storm")
    if m.array_eff < 1:
        a.append("array_damaged")
    return a


def score(m: Mission) -> int:
    survival = 500 if m.outcome == "survived" else int(400 * m.t_h / MISSION_H)
    sci = 1.5 * m.science_sent + 0.5 * (m.science - m.science_sent)
    return max(0, int(round(survival + sci - 8 * m.dose)))


def to_state(m: Mission) -> dict:
    env = env_at(m, m.t_h)
    st = env["storm"]
    return {
        "id": m.id, "site": public_site(site(m.site_id)), "seed": m.seed,
        "day": min(m.t_h // 24 + 1, 10), "shift": (m.t_h % 24) // SHIFT_H + 1, "mission_time_h": m.t_h,
        "over": m.over, "outcome": m.outcome,
        "resources": {"power_pct": round(m.power, 1), "life_support_pct": round(m.life, 1),
                      "dose_msv": round(m.dose, 2), "dose_limit_msv": DOSE_LIMIT,
                      "dose_rate_msv_h": round(dose_rate(m, m.t_h, env), 3)},
        "loads": dict(m.loads),
        "env": {"sun_elev_deg": env["sun_elev_deg"], "in_sun": env["in_sun"], "earth_elev_deg": env["earth_elev_deg"],
                "earth_visible": env["earth_visible"], "next_comm_window_h": next_comm_window_h(m, m.t_h),
                "comm_delay_s": COMM_DELAY_S,
                "storm": ({"active": True, "name": st.event["name"], "source": st.event["source"]["title"],
                           "url": st.event["link"], "severity": st.event["severity"], "real_date": st.event["date"]}
                          if st else {"active": False})},
        "rover": dict(m.rover), "shelter": m.shelter,
        "science": {"collected": round(m.science, 1), "sent_home": round(m.science_sent, 1)},
        "pending": m.pending,
        "alerts": alerts(m), "log": m.log[-30:], "score": score(m),
    }


def telemetry(m: Mission, offset_h: float) -> dict:
    """A live frame `offset_h` hours into the current shift (0..6), from a forecast of the shift."""
    offset_h = max(0.0, min(float(SHIFT_H), offset_h))
    f = copy.deepcopy(m)
    lo = copy.deepcopy(m)
    whole = int(offset_h)
    for _ in range(whole):
        if f.t_h >= MISSION_H:
            break
        _step_hour(f, [])
        if _ < whole - 1:
            _step_hour(lo, [])
    if whole == 0:
        lo = m
    frac = offset_h - whole
    nxt = copy.deepcopy(f)
    if frac > 0 and nxt.t_h < MISSION_H:
        _step_hour(nxt, [])
    base = f

    def lerp(a, b):
        return a + (b - a) * frac
    t = base.t_h + frac
    env = env_at(m, t)
    return {"t": "telemetry", "mission_time_h": round(t, 2), "forecast": offset_h > 0,
            "power": round(lerp(base.power, nxt.power), 1), "life_support": round(lerp(base.life, nxt.life), 1),
            "dose_msv": round(lerp(base.dose, nxt.dose), 3), "dose_rate": round(dose_rate(m, t, env), 3),
            "sun_elev_deg": round(env["sun_elev_deg"], 3), "earth_elev_deg": round(env["earth_elev_deg"], 3),
            "comm": "open" if env["earth_visible"] else "closed", "loads": dict(m.loads), "alerts": alerts(m, t),
            "over": m.over}


# ---------------------------------------------------------------- debrief

def debrief(m: Mission) -> dict:
    rad = radiation()
    s = site(m.site_id)
    eph = ephemeris(s["id"])
    sc = score(m)
    grade = "A" if sc >= 650 else "B" if sc >= 550 else "C" if sc >= 450 else "D" if sc >= 300 else "F"
    lessons = []
    for st in m.storms:
        if st.start_h > m.t_h:
            continue
        ev = st.event
        got = m.storm_dose.get(ev["id"], 0.0)
        mult = ev["dose_multiplier"]
        lessons.append({"text": (f"On {ev['date']} the Sun really produced an {ev['class']} "
                                 f"{'flare' if ev['type'] == 'flare' else 'storm'}. In your mission it raised radiation "
                                 f"{mult}x for {st.dur_h} hours, and your crew took {got:.1f} mSv during it. "
                                 "On the Moon there is no magnetic field or thick air to stop solar particles, so a "
                                 "regolith shelter is the plan."),
                        "source": ev["source"]})
        if len(lessons) >= 2:
            break
    base = rad["baseline"]
    lessons.append({"text": (f"Chang'e 4 measured {base['dose_equivalent_usv_per_day']} microsieverts per day on the "
                             f"Moon's surface: about 2.6 times the cosmic-ray dose inside the Space Station. Your crew's "
                             f"{m.dose:.1f} game-mSv is about {m.dose / rad['game']['dose_scale_factor']:.1f} real mSv "
                             f"(the game doubles doses). NASA's career limit is {rad['limits']['career_msv']} mSv."),
                    "source": base["source"]})
    lit = s.get("window_sunlit_pct")
    if s.get("power_from"):
        sun_text = (f"The floor of {s['name'].replace(' Floor', '')} never sees the Sun, which is why ice can survive "
                    "there, and why your power had to come down a cable from the rim.")
    else:
        sun_text = (f"At {s['name']} the Sun was up {lit}% of these 10 days (JPL Horizons, April 2026) but it never "
                    f"climbed more than a few degrees: at the pole the Sun skims the horizon. Earth was above the "
                    f"horizon {s['earth_visible_pct']}% of the time, so radio contact came and went. (Horizons treats "
                    "the ground as smooth; real mountains and craters change this.)")
    lessons.append({"text": sun_text, "source": {"title": "JPL Horizons API", "url": eph["source"]["url"]}})
    timeline = list(m.shifts)
    why = {
        "survived": f"Your crew made it through all 10 days at {s['name']} with {m.dose:.0f} of {DOSE_LIMIT:.0f} mSv.",
        "life_support_out": "Life support ran out: the crew needed more power for recycling, the greenhouse, or ice.",
        "power_out": "The batteries stayed empty for two shifts, so nothing could run.",
        "dose_limit": "The crew got too much radiation: a solar storm hit while they were not sheltered enough.",
    }.get(m.outcome or "", f"The mission is still going: {m.t_h} of {MISSION_H} hours done.")
    data_used = [
        {"name": "JPL Horizons ephemerides (Sun and Earth elevation, hourly, 2026-04-08 to 04-18)",
         "url": "https://ssd-api.jpl.nasa.gov/doc/horizons.html",
         "how": "Sun elevation sets solar power and day/night; Earth elevation sets comm windows. Topocentric "
                "observer at the site; terrain ignored except for one calibrated horizon angle per site."},
        {"name": "Outpost sites (IAU Gazetteer + NASA Artemis III candidate regions + illumination studies)",
         "url": "https://planetarynames.wr.usgs.gov/",
         "how": "Site coordinates, ice, and the long-term sunlight % that calibrates each site's horizon."},
        {"name": "Real solar events (NASA Solar Cycle 25 blog, NASA Science, NOAA SWPC)",
         "url": storms_catalog()["source"]["url"],
         "how": "Each mission replays 2-3 real events, moved into the mission. Severity and dose multiplier from "
                "flare class / storm level: " + storms_catalog()["mapping"]["rule"]},
        {"name": "Lunar surface radiation (Chang'e 4 LND, Zhang et al. 2020)", "url": base["source"]["url"],
         "how": f"Baseline dose rate {base['dose_rate_msv_per_h']} mSv/h, x{rad['game']['dose_scale_factor']} for "
                "gameplay."},
        {"name": "NASA career radiation limit (NTRS 20230012405)", "url": rad["limits"]["source"]["url"],
         "how": "Context for the 50 mSv game mission limit (1/12 of 600 mSv)."},
        {"name": "Regolith shielding (NASA NTRS 19890004839)", "url": rad["shielding"]["sources"][0]["url"],
         "how": "Why the shelter cuts storm dose much more than cosmic-ray dose (factors are game assumptions)."},
    ]
    return {"score": sc, "grade": grade, "outcome": m.outcome, "why": why, "lose_reason": m.lose_reason,
            "log": [e for e in m.log if e["kind"] in ("event", "command", "houston")],
            "site": public_site(s), "seed": m.seed, "mission_time_h": m.t_h,
            "final": {"power_pct": round(m.power, 1), "life_support_pct": round(m.life, 1), "dose_msv": round(m.dose, 2),
                      "science": round(m.science, 1), "science_sent": round(m.science_sent, 1)},
            "timeline": timeline, "lessons": lessons[:4], "data_used": data_used}
