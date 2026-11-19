"""The campaign (docs/GAMEPLAY.md §16): Mission 1, then five missions, each at another real south-pole site with its own
goal and twist, unlocked in order on the mission hub. Same hub, briefing, chapter cards and debrief as Mission 1.

A campaign mission is data. `new_mission(..., campaign=id)` applies its twist once (the storm list, the starting
conditions, the radio relay, the backup generator), and the sim and the gameplay layer read the rest from here (the
goals, the rescue job). The sim stays deterministic per (campaign mission, site, seed, inputs): the autosave and
Restart shift carry the campaign id and replay the same mission.

Goals (two per mission; each is {id, label, short, goal, got, met, kind}):
  science / science80  science sent home (120 / 80)          ice         an ice run home
  warm                 the battery never runs empty           low_dose    the crew's dose stays under 25 mSv
  rescue               the stranded rover is home by day 3    relay_calls three calls to Houston through the relay
  budget               the battery never under 15%
A "keep" goal (warm, low_dose, budget) is met while it holds and judged at the end; the others count up.
"""
from __future__ import annotations

FIRST = "first_light"
RESCUE_BY_H = 72            # rescue goal: the rover home by the end of day 3
RELAY_EVERY_H = 12          # far-side relay: a pass every 12 hours ...
RELAY_PASS_H = 4            # ... 4 hours long (a game schedule; the idea is China's Queqiao relay for Chang'e 4)
LOW_DOSE = 25.0             # mSv: half the mission limit
BUDGET_MIN = 15.0           # % battery
LIFE_MIN = 25.0             # % air and water

# Four real particle storms from the 2024 solar maximum (NASA CCMC DONKI), two back-to-back pairs. Each pair leaves the
# crew its 12-hour rest between shelter stays (sim.SHELTER_REST_H) before the next one hits.
STORM_SEASON = (("2024-03-23T09:55:00-SEP-001", 20), ("2024-05-09T14:25:00-SEP-001", 60),
                ("2024-09-17T15:43:00-SEP-001", 140), ("2024-10-09T08:55:00-SEP-001", 180))

MISSIONS = (
    {"n": 1, "id": FIRST, "title": "First light", "site": None,
     "line": "Run a real Moon outpost for ten days. Keep the crew safe through storms and long nights.",
     "danger": "Solar storms and long nights.", "goals": ("science", "ice"),
     "say": "Keep the crew safe for ten days. Watch for storms and long nights. Bonus: ice and science."},
    {"n": 2, "id": "long_night", "title": "The long night", "site": "malapert_massif",
     "line": "Malapert starts in a three-day night. Keep the heat and lights on.",
     "danger": "A three-day night, then another.", "goals": ("warm", "life"), "start": {"life": 100.0},
     "say": "Malapert starts in a three-day night. Keep the battery and the air from running low."},
    {"n": 3, "id": "storm_season", "title": "Storm season", "site": "shackleton_floor",
     "line": "Four real storms from 2024's solar maximum. Keep the crew's dose low.",
     "danger": "Four real storms, two back to back.", "goals": ("low_dose", "ice"), "storms": STORM_SEASON,
     "start": {"life": 100.0},
     "say": "Four real storms are coming, two back to back. Keep the dose under 25."},
    {"n": 4, "id": "rover_rescue", "title": "Rover rescue", "site": "de_gerlache_rim",
     "line": "Your rover is stuck on the plain, battery flat. Bring it home.",
     "danger": "No rover until you rescue it.", "goals": ("rescue", "ice"), "start": {"stranded": True},
     "say": "Our rover is stuck out on the plain. Bring it home by day three."},
    {"n": 5, "id": "far_relay", "title": "Far-side relay", "site": "connecting_ridge",
     "line": "Earth hides behind the ridge. A relay satellite carries your radio.",
     "danger": "Radio only when the relay passes.", "goals": ("relay_calls", "science80"), "comm": "relay",
     "say": "Earth hides behind the ridge. Call Houston through the relay three times."},
    {"n": 6, "id": "power_budget", "title": "Power budget", "site": "shackleton_rim",
     "line": "No backup generator this time. Every watt counts through the long night.",
     "danger": "No backup power. A two-day night.", "goals": ("budget", "science80"), "start": {"backup_gen": 0.0},
     "say": "No backup generator this time. Keep the battery above 15 percent."},
)
BY_ID = {x["id"]: x for x in MISSIONS}

GOALS = {   # id -> (label on the debrief and the hub, short label on the progress strip, target, kind)
    "science": ("Send 120 science home", "Science home", 120.0, "count"),
    "science80": ("Send 80 science home", "Science home", 80.0, "count"),
    "ice": ("Bring ice home", "Ice", 1, "count"),
    "warm": ("Never let the battery run empty", "Battery never empty", 0, "keep"),
    "low_dose": ("Keep the dose under 25 mSv", "Dose under 25", LOW_DOSE, "keep"),
    "rescue": ("Rover home by day 3", "Rover home", 1, "count"),
    "relay_calls": ("Call Houston 3 times", "Houston calls", 3, "count"),
    "budget": ("Battery never under 15%", "Battery over 15%", BUDGET_MIN, "keep"),
    "life": ("Air and water never under 25%", "Air over 25%", LIFE_MIN, "keep"),
}
TRY = {   # the debrief's "try" line when that goal was missed
    "warm": "Night mode before sunset. Heaters on, lab off.",
    "low_dose": "Shelter when the warning comes, not when the storm hits.",
    "rescue": "Find the beacon, wait for sunlight, then drive it home.",
    "relay_calls": "Call Houston on every relay pass.",
    "budget": "Night mode before the long night. Science can wait.",
    "life": "Send the rover for ice early, before the long night.",
}


def spec(m) -> dict:
    return BY_ID.get(getattr(m, "campaign", "") or "") or BY_ID[FIRST]


def is_campaign(m) -> bool:
    """A mission past Mission 1 (Mission 1 is the classic: any site, the default goals)."""
    return (getattr(m, "campaign", "") or FIRST) != FIRST


def public(mid: str | None = None) -> list[dict] | dict:
    """GET /api/mission/campaign: the list for the hub (no internals)."""
    def one(x):
        return {"n": x["n"], "id": x["id"], "title": x["title"], "site": x["site"], "line": x["line"],
                "danger": x["danger"], "say": x["say"], "goals": [GOALS[g][0] for g in x["goals"]]}
    if mid is not None:
        return one(BY_ID[mid])
    return [one(x) for x in MISSIONS]


# ---- applied once, at new_mission ----------------------------------------------------------------------------------
def apply_start(m) -> None:
    s = spec(m)
    st = s.get("start") or {}
    if "life" in st:
        m.life = float(st["life"])
    if "backup_gen" in st:
        m.backup_gen = float(st["backup_gen"])
    if st.get("stranded"):
        m.rover.update(busy=True, task="stranded", eta_h=0)   # no ETA: it is going nowhere until rescued
    if s.get("comm"):
        m.comm = s["comm"]
    m.gp.setdefault("campaign", {"rescued_h": None, "empty_h": 0, "min_power": m.power, "max_dose": m.dose})


def storms(m) -> list[tuple[str, int]] | None:
    return spec(m).get("storms")


def relay_up(t: float) -> bool:
    return int(t) % RELAY_EVERY_H < RELAY_PASS_H


def stranded(m) -> bool:
    return m.rover.get("task") == "stranded"


# ---- every hour (gameplay.update) ----------------------------------------------------------------------------------
def track(m) -> None:
    c = m.gp.setdefault("campaign", {"rescued_h": None, "empty_h": 0, "min_power": m.power, "max_dose": m.dose})
    if c.get("_h") != m.t_h:   # once per mission hour (this also runs after an order, with no time passing)
        c["_h"] = m.t_h
        if m.t_h > 0 and m.power <= 0.5:
            c["empty_h"] += 1
    c["min_power"] = min(c["min_power"], m.power)
    c["min_life"] = min(c.get("min_life", m.life), m.life)
    c["max_dose"] = max(c["max_dose"], m.dose)
    if spec(m).get("start", {}).get("stranded") and c["rescued_h"] is None and not m.rover["busy"]:
        c["rescued_h"] = m.t_h


def goal(m, gid: str) -> dict:
    label, short, target, kind = GOALS[gid]
    c = m.gp.get("campaign") or {"rescued_h": None, "empty_h": 0, "min_power": m.power, "max_dose": m.dose}
    if gid in ("science", "science80"):
        got, met = round(m.science_sent, 1), m.science_sent >= target
    elif gid == "ice":
        got, met = m.ice_runs, m.ice_runs >= target
    elif gid == "warm":
        got, met = c["empty_h"], c["empty_h"] == 0
    elif gid == "low_dose":
        got, met = round(m.dose, 1), m.dose <= target
    elif gid == "rescue":
        h = c["rescued_h"]
        got, met = int(h is not None and h <= RESCUE_BY_H), h is not None and h <= RESCUE_BY_H
    elif gid == "relay_calls":
        got, met = m.houston_calls, m.houston_calls >= target
    elif gid == "life":
        got, met = round(c["min_life"], 1), c["min_life"] >= target
    else:   # budget
        got, met = round(c["min_power"], 1), c["min_power"] >= target
    if kind == "keep" and m.outcome not in (None, "survived"):
        met = False
    return {"id": gid, "label": label, "short": short, "goal": target, "got": got, "met": bool(met), "kind": kind}


def goals(m) -> list[dict]:
    return [goal(m, g) for g in spec(m)["goals"]]
