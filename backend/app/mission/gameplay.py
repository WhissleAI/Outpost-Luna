"""The gameplay layer over the sim: live tasks, story beats and the mission log (docs/GAMEPLAY.md).

The sim (sim.py) is the physics; this module turns its state into console-game play on the live clock:

  * Tasks: short, NASA-grounded jobs that come from the sim state and the objectives, never at random. Each step is a
    real order (shields, shelter, night mode, rover, radio...), a choice (route, steer, shelter-or-wait) or a press
    (take a sample, read the sensor). Steps tick off from the STATE, so a voice order, a tap on the panel, a key or a
    gesture all count. A step that completes says so ("Shields up. Good.").
  * Story beats: arrival, settling in, the first dark or comm gap, the forecast, the storm, recovery, ice home, the last
    downlink. Each beat has a CAPCOM line (20 words or fewer), a visual moment for the window and an objective.
  * The mission log: one entry per beat, finished task and good call (the small rewards).

Deterministic per (site, seed, orders), like the sim. The tasks never read the hidden storm schedule: they react to
what the crew can see (warnings heard, storms on, the Sun and Earth from Horizons, the rover, the resources). Rewards
are small (a sample is +2 science) and only come from the kid's own presses, so a policy that never touches a task
plays exactly the old game (tests/test_strategy.py keeps the no-dominant-strategy guarantees).
"""
from __future__ import annotations

import random

from . import physics, sim



def _lesson_order() -> tuple[dict, dict]:
    """Lesson numbers and titles in Flight School order (backend/data/academy/course.json), for "Lesson 5 helps
    here". Read from the course, so a new lesson never leaves a stale number. Core lessons only, as the map numbers
    them (the check ride and the explorer lessons aren't numbered)."""
    import json
    from pathlib import Path
    c = json.loads((Path(__file__).resolve().parents[2] / "data" / "academy" / "course.json").read_text())
    ls = [l for l in c["lessons"] if not l.get("ride") and l.get("track", "core") == "core"]   # core lessons only
    # [0.5 field] Field School lessons (after the check ride) are named, not numbered: "Field School: Field kit"
    fs = [l for l in c["lessons"] if l.get("track") == "field"]
    return ({l["id"]: k + 1 for k, l in enumerate(ls)},
            {l["id"]: l["title"] for l in ls + fs})


LESSON_NO, LESSON_TITLE = _lesson_order()
FIELD_LESSONS = {"observe", "craters", "rocks", "fieldkit"}
SAMPLE_SCIENCE = 2.0       # a sample or a logged sensor reading: small, and only when the kid does it
SCIENCE_TASKS = {"cadet": 4, "commander": 6}
SCIENCE_EVERY_H = 8
EXPLORE_TASKS = 3          # [playtest 4] science drives per mission, offered once the ice is home (+EXPLORE_SCIENCE each)
EXPLORE_EVERY_H = 12
STEER_AFTER_H = 2          # the boulder field comes up this far into an ice drive
STEER_WAIT_H = 2           # ...and the rover picks its own way if nobody steers in time
SHELTER_LEAD_H = 6         # storm prep: the shelter step opens this many hours before a likely storm
# [0.5 field] mission tasks from Field School (docs/GAMEPLAY.md §13): the sample station, the low-Sun drive's navigator
# calls and the science team's replan. Rewards stay small (a station is worth 0.5 to 2.5 science; a nav call only
# avoids a cost) and come only from the kid's own presses, so tests/test_strategy.py's guarantees hold.
STATION_BAG = 0.5          # a bagged, called-in sample
STATION_TOOL = 0.5         # ...with the right tool
STATION_KIND = 0.5         # ...per descriptor kind in the one-line description (size, shape, bright or dark, texture)
STATION_KINDS = 3          # kinds that count (the Lunar Log Card's three); three ends the describe step by itself
TACK_AT_H = 1              # the low-Sun leg: an hour out, the route turns into the Sun (NTRS 20240011393)
DEAD_AHEAD = 2             # degrees: the Sun on the nose, where a tack either way clears it
GLARE_CONE = 60            # degrees either side of the nose where a 1-2 degree Sun blinds the drivers' cameras
LIGHTS_LEAD_H = 2          # the lights call opens this long before the rover reaches the crater's shadow
NAV_WAIT_H = 2             # a nav call nobody makes within this many hours costs the drive (never a fail state)
NAV_COST_H = 1             # a wrong or missed call: the rover slows (glare) or stops at the shadow's edge
LIGHTS_COST_PCT = 1.0      # ...and recharges after a stop in the dark
ROCK_AT_H = 4              # the science team's rock comes up this far into a drive
REPLAN_MIN = 15            # minutes the science room asks for (JETT5: more time at a stop costs time elsewhere)
REPLAN_MARGIN_H = 2        # Flight keeps at least this much light margin on a drive
REPLAN_MAX = 1             # once a mission
ROCK_SCIENCE = 2.0         # the bright rock, read back and bagged
STATION_DUE_H = 48         # [0.4.1] no sample station by the end of chapter 1: the rover crew stops for one on a drive
RECYCLER_MAX = 60          # the life check never offers the recycler past this (ice is the answer then)
LIFE_CHECK = 55            # air under this: the life support check (ice, or more recycler power)
QUIET_RATE = 0.1           # mSv/h: under this the sensor reads "normal" (the quiet-Sun baseline is ~0.06 game)
HEATERS_SAFE = 8           # the night checklist only asks for heaters when they're under this (10 is the order; a
                           # later power move can trim them to 8-9, which is still well clear of the 5% freeze line)
# [polish 1] science jobs rotate so no two in a row are the same (sub, title, panel, press label, ack, why)
SCIENCE_ROTATION = ("sample", "sensor", "quake", "core")
SCIENCE_PRESS = {
    "sample": ("Take a sample", "rover", "Take a sample", "Sample logged",
               "Moon soil keeps a record of how the Moon formed."),
    "quake": ("Read the seismometer", "habitat", "Read the seismometer", "Moonquake logged",
              "Apollo seismometers heard thousands of moonquakes. They show what's inside."),
    "core": ("Drill a core", "rover", "Drill a core", "Core logged: layers of lunar dust",
             "Deep layers hold a record of the Sun's past."),
}

# ---- the story arc ---------------------------------------------------------------------------------------------------
# id, title (on screen), CAPCOM line (spoken, <= 20 words), visual moment for the window, objective (<= 12 words)
BEATS = {
    "arrival": ("Arrival", "Outpost Luna is online. Set your power, then start the clock.", "arrival",
                "Set power, then start the clock."),
    "settle": ("Settling in", "Systems steady. The clock is running. Your jobs show on the Now card.", "site",
               "Watch the Now card for jobs."),
    "comm_gap": ("On our own", "Earth is below the horizon. No radio until it rises. Science waits on board.", "earthset",
                 "No radio for now. Science waits on board."),
    "first_dark": ("First sunset", "Sunset. The long dark starts. Night mode keeps the lights on.", "sunset",
                   "Power down for the night."),
    "forecast": ("Storm forecast", "Houston sees a storm coming. Get ready before it hits.", "storm_glow",
                 "Get ready: rover home, then shelter."),
    "crisis": ("Solar storm", "Storm's here! Particles are hitting the outpost. Keep the crew sheltered.", "storm_glow",
               "Ride out the storm in the shelter."),
    "recovery": ("All clear", "Storm's over. Crew out of the shelter. Back to work.", "calm",
                 "Crew out. Back to science."),
    "earthrise": ("Earthrise", "Earthrise! Houston can hear us again. Send the science home.", "earthrise",
                  "Send science home while Earth is up."),
    "ice_return": ("Ice home", "Rover's home with ice. Water and air for the crew.", "rover_lights",
                   "Ice goal done. Keep science going home."),
    "final_downlink": ("Last downlink", "Last days. Send every bit of science home.", "earthrise",
                       "Send the last science home."),
    "complete": ("Mission complete", "Day ten done. The crew made it. Time for your debrief.", "calm",
                 "Open your debrief."),
}
ARC = ["arrival", "settle", "comm_gap", "first_dark", "forecast", "crisis", "recovery", "earthrise", "ice_return",
       "final_downlink", "complete"]


def _gp(m) -> dict:
    g = m.gp
    if not g:
        g.update(tasks={}, order=[], beats=[], log=[], cool={}, count={}, seq=0, calls_seen=0, ack=None)
    return g


def _ev(m, out: list, kind: str, text: str, **extra):
    """A gameplay event: in `out` and m.events (the session's poll sees it), never in the sim's radio log."""
    ev = {"t_h": m.t_h, "kind": kind, "text": text, "source": None, "real_date": None, **extra}
    out.append(ev)
    m.events.append(ev)
    return ev


def _log(m, kind: str, title: str, text: str):
    _gp(m)["log"].append({"t_h": m.t_h, "day": m.t_h // 24 + 1, "kind": kind, "title": title, "text": text})


# ---- step helpers ----------------------------------------------------------------------------------------------------
def _order(sid, label, target, cmd, done, ack, why=None):
    return {"id": sid, "kind": "order", "label": label, "target": target, "cmd": cmd, "done_if": done, "ack": ack,
            "why": why}


def _press(sid, label, ack, ready=None, why=None):
    return {"id": sid, "kind": "press", "label": label, "target": "task", "ready_if": ready, "ack": ack, "why": why}


def _choice(sid, label, options, ready=None, hint=None, why=None):
    return {"id": sid, "kind": "choice", "label": label, "target": "task", "options": options, "ready_if": ready,
            "hint": hint, "why": why}


def _wait(sid, label, done, ack=None):
    return {"id": sid, "kind": "wait", "label": label, "target": None, "done_if": done, "ack": ack}


ALLOC = lambda k, v: {"type": "allocate", "to": k, "amount": {"kind": "percent", "value": v}, "from": None}  # noqa: E731
ROVER = lambda task: {"type": "dispatch", "vehicle": "rover", "task": task, "target": None}  # noqa: E731
HOME = ROVER("return")


def _rover_home(m) -> bool:
    return not m.rover["busy"] or m.rover["task"] == "return_home"


def _warning(m):
    return sim._warning(m)


def _storm(m):
    return sim.env_at(m, m.t_h)["storm"]


def _night_len(m, from_h: int) -> int:
    """Hours the coming night lasts (Horizons): what the Sun strip shows. 0 if the Sun doesn't set."""
    tbl = sim.sky_table(m.site_id)[0]
    k, n = from_h, 0
    while k < len(tbl) and tbl[k]:
        k += 1
    while k < len(tbl) and not tbl[k]:
        k, n = k + 1, n + 1
    return n


# ---- task kinds --------------------------------------------------------------------------------------------------------
# Each builder returns a task dict (title, lesson, panel, level, priority, deadline_h, say, steps) or None.
def _first_power(m):
    a0 = m.acted.get("allocate", 0)
    return dict(title="Set your power", lesson="power", panel="radiation", level="info", priority=95,
                say=None, steps=[_order("power", "Shields up to 30", "shields", ALLOC("shields", 30),
                                        lambda m, t: m.acted.get("allocate", 0) > a0, "Power set. Good.",
                                        why="Shields cut the everyday radiation. In a big storm, the shelter is safer.")])


def _shelter_step():
    """Crew into the shelter: ready once the rover crew is home (the sim refuses it while they are outside)."""
    s = _order("shelter", "Crew into the shelter", "shelter", {"type": "shelter", "on": True},
               lambda m, t: m.shelter, "Crew sheltered. Good.", why="Thick walls block most of the storm's particles.")
    s["live"] = True   # stays honest: a crew that walks out mid-storm is asked back in
    s["ready_if"] = lambda m, t: not m.rover["busy"]
    s["wait_text"] = "Shelter opens when the rover crew is home."
    return s


# [0.4.1] the storm procedure, as flight controllers run it: Houston calls the order, the crew reads it back, acts, and
# confirms. The readback and the confirm are words (voice) or one tap; an order given straight away still counts (the
# crew is safe first): the readback is then marked skipped, and the confirm settles itself after CONFIRM_WAIT_H.
HOUSTON_SHELTER = "Houston: all crew into the shelter. Read it back."
CONFIRM_WAIT_H = 1


def _readback_step():
    s = {"id": "readback", "kind": "sequence", "label": HOUSTON_SHELTER, "target": "task", "button": "Read it back",
         "items": [{"id": "crew", "label": "All crew", "say": ["all crew", "crew", "everyone", "everybody", "all of us"]},
                   {"id": "shelter", "label": "into the shelter", "say": ["shelter", "inside", "under cover"]}],
         "why": "A readback proves the order was heard right."}
    s["ready_if"] = lambda m, t: not m.rover["busy"]
    s["wait_text"] = "Shelter opens when the rover crew is home."
    return s


def _confirm_step():
    return {"id": "confirm", "kind": "sequence", "label": "Crew inside? Tell Houston.", "target": "task",
            "button": "In the shelter, copy", "ready_if": lambda m, t: m.shelter,
            "items": [{"id": "in", "label": "In the shelter", "say": ["in the shelter", "inside", "sheltered", "in"]},
                      {"id": "copy", "label": "copy", "say": ["copy", "copied", "roger"]}],
            "why": "Houston can't see inside. Say when the crew is safe."}


def _storm_auto(m, t, s):
    """The storm procedure's words never block safety: a crew sheltered without a readback skips it; the confirm
    settles itself an hour in (or when the storm arrives on a prep)."""
    if t["kind"] not in ("storm_hit", "storm_prep") or s["done"] or s["id"] not in ("readback", "confirm") \
            or not m.shelter:
        return
    if s["id"] == "readback":
        s["done"], s["result"] = True, "Sheltered. No readback this time."
    elif m.shelter_h >= CONFIRM_WAIT_H or (t["kind"] == "storm_prep" and _storm(m)):
        s["done"], s["result"] = True, "Houston saw the crew go in."


def _all_clear(m):
    return dict(title="All clear: crew out", lesson="radiation", panel="radiation", level="info", priority=85,
                key=("clear", m.t_h // 6), say=None,
                steps=[_order("out", "Crew out of the shelter", "shelter", {"type": "shelter", "on": False},
                              lambda m, t: not m.shelter, "Crew out. Science is back on.",
                              why="No science gets done in the shelter.")])


def _storm_hit(m):
    st = _storm(m)
    steps = [_order("rover", "Rover home", "rover:return", HOME, lambda m, t: _rover_home(m), "Rover turning home.",
                    why="Outside, the crew has no shelter from the particles."),
             _readback_step(), _shelter_step(), _confirm_step()]
    return dict(title="Storm! Shelter the crew", lesson="radiation", panel="radiation", level="warn", priority=100,
                deadline_h=st.start_h + st.dur_h, key=("storm", st.event["id"]), say=HOUSTON_SHELTER, steps=steps)


def _storm_prep(m):
    w = _warning(m)
    steps = [_order("rover", "Rover home", "rover:return", HOME, lambda m, t: _rover_home(m),
                    "Rover heading home. Good.", why="The crew must be inside before the storm hits.")]
    if m.difficulty == "commander":
        steps.append(_order("shields", "Shields to 40", "shields", ALLOC("shields", 40),
                            lambda m, t: m.loads["shields"] >= 40, "Shields up. Good.",
                            why="More shield power, less dose while you get ready."))
    if w["confidence"] == "likely":
        # shelter early, not too early: the shelter is good for about a day (Orion), and science stops inside
        sh = _shelter_step()
        sh["ready_if"] = lambda m, t: not m.rover["busy"] and (_warning(m) or {}).get("eta_h", 0) <= SHELTER_LEAD_H
        # a kid can't do "6 hours before" sums: the card counts down to the moment the shelter opens, and that moment
        # stops a skip (a "task" event, phase "ready")
        sh["wait_text"] = lambda m, t: ("Shelter opens when the rover crew is home." if m.rover["busy"] else
                                        f"Shelter opens in {max(1, int((_warning(m) or {}).get('eta_h', SHELTER_LEAD_H)) - SHELTER_LEAD_H)} h. "
                                        "Keep working, or skip ahead.")
        rb = _readback_step()   # [0.4.1] Houston calls it when the shelter opens: read back, act, confirm
        rb["ready_if"], rb["wait_text"] = sh["ready_if"], sh["wait_text"]
        steps += [rb, sh, _confirm_step()]
    else:   # a "possible" storm: a real call to make, with no right answer known yet
        decide = _choice("decide", "Possible storm. Shelter now, or wait?",
                         [{"id": "shelter", "label": "Shelter now"}, {"id": "wait", "label": "Wait and watch"}],
                         why="Not every flare sends particles. Sheltering costs a day of science.")
        decide["gate"] = "rover_home"   # the shelter can't open with the rover crew outside
        steps.append(decide)
    sid = next((st.event["id"] for st in m.storms if m.warned.get(st.event["id"]) and m.t_h < st.start_h), None)
    return dict(title="Storm prep", lesson="radiation", panel="radiation", level="caution", priority=90,
                deadline_h=m.t_h + int(w["eta_h"]), key=("prep", sid), say=None, steps=steps)


# ---- Engineer (docs/PHYSICS.md): the same tasks, with the power budget and the heaters' duty cycle as real choices ----
DUTIES = (25, 50, 75)      # heater duty cycle options, % of the time on (physics.heater_duty: 20% share = 100% duty)


def _budget(m) -> dict:
    """The night's power budget in kW and how long the battery lasts on each choice (physics.py outpost model)."""
    full = sim.draw_per_h(m) / (sim.POWER_SAVE_DRAW if m.power_save else 1.0)
    out = {}
    for k, d in (("night", full * sim.POWER_SAVE_DRAW), ("full", full)):
        net = d - sim.BACKUP_GEN
        out[k] = {"kw": physics.kw(d), "lasts_h": (int(m.power / net) if net > 0 else None)}
    return out


def _lasts(b) -> str:
    return f"lasts {b['lasts_h']} h" if b["lasts_h"] is not None else "lasts all night"


def _engineer_night_steps(m) -> list:
    b, dark = _budget(m), _night_len(m, m.t_h)
    budget = _choice("budget", f"Night budget: dark for {dark} h. Which load?" if dark else "Night budget: which load?",
                     [{"id": "night", "label": "Night mode", "hint": f"{b['night']['kw']:.1f} kW, {_lasts(b['night'])}"},
                      {"id": "full", "label": "Full power", "hint": f"{b['full']['kw']:.1f} kW, {_lasts(b['full'])}"}],
                     hint="Energy = power × time")
    rated = physics.heater_rated_kw()
    names = {25: "Low", 50: "Half", 75: "High"}
    duty = _choice("duty", "Heater duty cycle?",
                   [{"id": str(d), "label": f"{names[d]} {d}%", "hint": f"{rated * d / 100:.2f} kW average"} for d in DUTIES],
                   hint=f"Heater {rated:.1f} kW when on")
    return [budget, duty]


def _night_prep(m):
    sun_h = sim.next_sun_change_h(m, m.t_h)
    env = sim.env_at(m, m.t_h)
    deadline = m.t_h + sun_h if env["lit"] and sun_h else m.t_h + 6
    if m.engineer:
        steps = _engineer_night_steps(m)
    else:
        steps = [_order("night", "Night mode on", "night", {"type": "power_save", "on": True},
                        lambda m, t: m.power_save, "Night mode on. Good.",
                        why="Solar arrays make nothing in the dark. The battery has to last.")]
        # below 5% in the dark the water lines freeze: asked only while the heaters are low (never re-asked once up)
        if m.loads["heaters"] < HEATERS_SAFE:
            steps.append(_order("heaters", "Heaters to 10", "load:heaters", ALLOC("heaters", 10),
                                lambda m, t: m.loads["heaters"] >= 10, "Heaters on. The water lines stay warm.",
                                why="Below 5% the water lines freeze in the dark."))
        else:   # [polish 1] a different job each night: read the battery, or log the sunset from JPL Horizons
            n = _gp(m)["count"].get("night_prep", 0)
            steps.append(_press("battery", "Check the battery", None, why="Will the battery last until sunrise?")
                         if n % 2 else
                         _press("sunset", "Log the sunset", None, why="JPL Horizons tells us when the Sun sets here."))
    if _night_len(m, m.t_h) >= 48:   # a long night (Malapert): the recycler needs the spare power
        steps.append(_order("air", "Air system to 45", "load:life_support", ALLOC("life_support", 45),
                            lambda m, t: m.loads["life_support"] >= 45, "Air system up. Ready for the long dark."))
    if m.rover["busy"]:
        steps.append(_order("rover", "Rover home before dark", "rover:return", HOME, lambda m, t: _rover_home(m),
                            "Rover heading home before dark."))
    sun_key = m.t_h + (sun_h or 0) if env["lit"] else ("dark", m.t_h // 24)
    return dict(title="Night power-down", lesson="power", panel="power", level="caution", priority=80,
                deadline_h=deadline, key=("night", sun_key), say="Sunset is coming. Time for the night checklist.",
                steps=steps)


def _sunrise(m):
    return dict(title="Sunrise: wake the outpost", lesson="power", panel="power", level="info", priority=45,
                key=("sunrise", m.t_h // 12), say="Sunrise. Wake the outpost: night mode off.",
                steps=[_order("wake", "Night mode off", "night", {"type": "power_save", "on": False},
                              lambda m, t: not m.power_save, "Outpost awake. Science is back on.",
                              why="The arrays are making power again. The lab can wake up.")])


def _low_power(m):
    if m.engineer:   # a power-budget call: what each cut saves, in kW
        full = sim.draw_per_h(m)
        sci = physics.kw(full * physics.load_share(m, "science") * (1 - 5 / max(5, m.loads["science"])))
        night = physics.kw(full * (1 - sim.POWER_SAVE_DRAW))
        return dict(title="Save power", lesson="power", panel="power", level="caution", priority=75, cool_h=12,
                    say="Battery low. Pick a cut.",
                    steps=[_choice("cut", f"Battery {m.power:.0f}%. Which cut?",
                                   [{"id": "science", "label": "Science down", "hint": f"saves {sci:.1f} kW"},
                                    {"id": "night", "label": "Night mode", "hint": f"saves {night:.1f} kW"}],
                                   hint="Cut the biggest load first")])
    return dict(title="Save power", lesson="power", panel="power", level="caution", priority=75, cool_h=12,
                say="Battery low. Cut science, or turn on night mode.",
                steps=[_order("cut", "Science down to 5", "load:science", ALLOC("science", 5),
                              lambda m, t: m.power_save or m.loads["science"] <= 5, "Science trimmed. Battery saved.")])


def _life_check(m):
    if m.difficulty == "cadet" and m.loads["life_support"] < 40:
        steps = [_order("air", "Air system to 40", "load:life_support", ALLOC("life_support", 40),
                        lambda m, t: m.loads["life_support"] >= 40 or m.rover["task"] == "collect_ice",
                        "Air system up. Good.")]
    elif m.difficulty == "cadet":   # the recycler is already up: water has to come from ice
        steps = [_order("ice", "Send the rover for ice", "rover:collect_ice", ROVER("collect_ice"),
                        lambda m, t: m.rover["task"] == "collect_ice", "Rover off for ice. Good.")]
    else:
        # a real raise every time (a "recycler up" to where it already is did nothing, and the check came back)
        up = min(RECYCLER_MAX, max(40, m.loads["life_support"] + 10))
        opts = [{"id": "ice", "label": "Ice run", "hint": "Rover, crew outside"}]
        if m.loads["life_support"] < RECYCLER_MAX:
            opts.insert(0, {"id": "recycler", "label": f"Recycler to {up}%", "hint": "Costs power"})
        steps = [_choice("air", "Air is dropping. Recycler up, or an ice run?" if len(opts) > 1 else
                         "Air is dropping. The recycler is maxed: ice run?", opts)]
        steps[0]["up"] = up
        steps[0]["why"] = "The recycler makes air but costs power. Ice makes water and air."
        if len(opts) == 1:
            steps[0]["gate"] = "rover"   # only the ice run is left: it waits for a free rover and an open shelter
    return dict(title="Life support check", lesson="life", panel="habitat", level="caution", priority=70, cool_h=12,
                say="Life support check. The air is dropping.", steps=steps)


def _comm_window(m):
    calls = m.houston_calls
    closes = sim.comm_closes_in_h(m, m.t_h)
    steps = [_order("radio", "Radio to 10: send science", "load:comms", ALLOC("comms", 10),
                    lambda m, t: m.loads["comms"] >= 10, "Downlink running. Science is going home.",
                    why="Science only counts once it reaches Earth."),
             _order("houston", "Call Houston", "houston", {"type": "call_houston", "text": "Outpost Luna, check in."},
                    lambda m, t: m.houston_calls > calls, "Houston has the news. Good.",
                    why="Earth is only up for a while. Talk while you can.")]
    return dict(title="Comm window", lesson="comms", panel="comm", level="info", priority=50, cool_h=24,
                deadline_h=m.t_h + (closes if closes else 12), say=None, steps=steps)


def _explore(m):
    """[playtest 4] A science drive: the rover brings back samples (sim EXPLORE_SCIENCE). Without it a kid who follows
    the Now card gathers about 80 science in 10 days, so the mission's 120 was out of reach on a first mission."""
    first = _order("send", "Send the rover to explore", "rover:explore", ROVER("explore"),
                   lambda m, t: m.rover["busy"] and m.rover["task"] == "explore", "Rover exploring. Good.",
                   why="New rocks are new science. The rover brings samples home.")
    first["latch"] = True
    first["ready_if"] = lambda m, t: _calm(m) and not m.shelter and not m.rover["busy"]
    first["wait_text"] = "The drive waits until the storm passes."
    back = _wait("back", "Rover back with samples",
                 lambda m, t: t["steps"][0]["done"] and not m.rover["busy"], "Samples home. Science is up.")
    back["latch"] = True
    return dict(title="Science drive", lesson="moon", panel="rover", level="info", priority=30, cool_h=EXPLORE_EVERY_H,
                say="Ice is home. Time for a science drive.", steps=[first, back])


def _ice_run(m):
    runs = m.ice_runs
    rng = random.Random(f"{m.site_id}:{m.seed}:steer:{runs}")
    good = rng.choice(["left", "right"])
    if m.difficulty == "commander":
        sl = (physics.site_phys(m.site_id).get("slope") or {})   # LRO LOLA slopes at this site (physics.json)
        flat, steep = (sl.get("median_deg") or {}).get("value"), (sl.get("p90_deg") or {}).get("value")
        first = _choice("route", "Pick a route on the slope map",
                        [{"id": "ridge", "label": "Ridge route",
                          "hint": (f"Flatter, about {flat:.0f}°. " if flat else "Flat. ") + "2 h longer, less battery"},
                         {"id": "slope", "label": "Crater slope",
                          "hint": (f"Steep, about {steep:.0f}°. " if steep else "Steep. ") + "2 h faster, more battery"}],
                        hint="LOLA slope map")
    else:
        first = _order("send", "Send the rover for ice", "rover:collect_ice", ROVER("collect_ice"),
                       lambda m, t: m.rover["busy"] and m.rover["task"] == "collect_ice", "Rover rolling. Good.",
                       why="Ice from the shadowed craters becomes water and air.")
        first["latch"] = True
    # the drive waits out a storm or a warning (and the crew must be out of the shelter): never "send it" mid-storm
    first["ready_if"] = lambda m, t: _calm(m) and not m.shelter and not m.rover["busy"]
    first["wait_text"] = "Ice run waits until the storm passes."
    out_for = lambda m: m.t_h - m.rover_left_h if m.rover["busy"] and m.rover["task"] == "collect_ice" else -1  # noqa: E731
    steer = _choice("steer", "Boulders ahead. Steer left or right?",
                    [{"id": "left", "label": "Steer left"}, {"id": "right", "label": "Steer right"}],
                    ready=lambda m, t: out_for(m) >= STEER_AFTER_H,
                    hint=f"LOLA slope map: the {good} side is flatter.")
    steer["good"] = good
    # [0.5 field] the low-Sun drive (NASA south-pole lighting study, NTRS 20240011393): the cadet is the navigator.
    # The Sun sits 1-2 degrees up; where the route turns into it, the drivers tack 20-30 degrees off the sunline, and
    # they turn the lights on BEFORE the crater's shadow, where hazards hide. A wrong or missed call costs an hour.
    # The glare comes on the leg that faces the Sun: out to the crater, or back home (the opposite heading). With the
    # Sun to the side or below the skyline there is no glare call (and no step for it).
    leg = _glare_leg(m)
    tack_at = TACK_AT_H if leg == "out" else _shadow_h(m) + 1
    tack = _choice("tack", "Glare: low Sun ahead. Tack left or right?",
                   [{"id": "left", "label": "Tack left"}, {"id": "right", "label": "Tack right"}],
                   ready=lambda m, t: out_for(m) >= tack_at, hint="Tack 20 to 30 degrees away from the Sun.",
                   why="A low Sun in the cameras hides rocks. Turn it off the nose.")
    tack["leg"] = leg
    lights = _choice("lights", "Shadow ahead. Lights on before we enter.", [{"id": "on", "label": "Lights on"}],
                     ready=lambda m, t: out_for(m) >= _lights_open_h(m),
                     why="In the shadow, rocks hide. Drivers need lights first.")
    for x in (tack, lights):
        x["lesson"] = "observe"
    back = _wait("back", "Rover back with ice", lambda m, t: m.ice_runs > runs, "Ice delivered. Life support up.")
    back["latch"] = True
    steps = ([first, tack, steer, lights, back] if leg == "out" else [first, steer, lights, back] if leg is None
             else [first, steer, lights, tack, back])   # the glare on the way home
    return dict(title="Ice run", lesson="life", panel="rover", level="info", priority=40,
                say="No storm due. Time for an ice run.", steps=steps, runs=runs)


# ---- [0.5 field] the low-Sun drive: where the Sun is from the rover's seat ----------------------------------------------
ICE_TARGET = (-89.67, 129.78)   # Shackleton's floor, where the ice drive heads (frontend terrain.js TARGETS.collect_ice)
SUN_AZ0, LUNAR_DAY_H = 140.0, 708.7   # the window's Sun azimuth (terrain.js sunLon): 140 deg + one turn per lunar day


def _polar(lat: float, lon: float) -> tuple[float, float]:
    """South polar stereographic (as the window's terrain): map x, y with longitude 0 toward +y."""
    import math
    t = 2 * 1737.4 * math.tan(math.pi / 4 + math.radians(lat) / 2)
    return t * math.sin(math.radians(lon)), t * math.cos(math.radians(lon))


def sun_view(m, t_h: float | None = None, leg: str = "out") -> dict:
    """The Sun from the rover on the ice drive: elevation (JPL Horizons, this site), whether it clears the real LOLA
    skyline, and its bearing off the nose on this leg (out to the crater, or home: the opposite heading; negative:
    left). The bearing uses the window's own convention, so the card agrees with what the cabin shows."""
    import math
    t = m.t_h if t_h is None else t_h
    sp = (sim.ephemeris(m.site_id).get("terrain") or {}).get("spot") or sim.site(m.site_id)
    (sx, sy), (tx, ty) = _polar(sp["lat"], sp["lon"]), _polar(*ICE_TARGET)
    hdg = math.degrees(math.atan2(tx - sx, ty - sy)) + (0 if leg == "out" else 180)
    sun_lon = -(SUN_AZ0 + t * 360 / LUNAR_DAY_H)
    rel = (sun_lon - hdg + 180) % 360 - 180
    elev = sim._eph_at(m.site_id, "sun_elev_deg", t)
    up = elev > sim._horizon(m.site_id, "sun", t)
    side = "ahead" if abs(rel) < DEAD_AHEAD else "left" if rel < 0 else "right"   # dead ahead: either tack works
    return {"rel": round(rel, 1), "side": side, "elev": round(elev, 2), "up": up,
            "glare": up and abs(rel) <= GLARE_CONE}


def _glare_leg(m) -> str | None:
    """Which leg of the coming ice drive faces the low Sun ("out" or "home"), or None (Sun to the side or down)."""
    if sun_view(m, m.t_h + TACK_AT_H)["glare"]:
        return "out"
    if sun_view(m, m.t_h + _shadow_h(m) + 1, "home")["glare"]:
        return "home"
    return None


def _shadow_h(m) -> int:
    """Hours from the outpost to the crater's shadow (the ice is in permanent shadow): the drive's first leg."""
    return max(STEER_AFTER_H + 1, int(sim.site(m.site_id).get("rover_to_ice_h", 0)))


def _lights_open_h(m) -> int:
    return max(TACK_AT_H, _shadow_h(m) - LIGHTS_LEAD_H)


def _ice_out(m) -> int:
    rv = m.rover
    return m.t_h - m.rover_left_h if rv["busy"] and rv["task"] == "collect_ice" else -1


def _slow(m, h=NAV_COST_H, pct=0.0):
    """A wrong or missed nav call: the rover is late (more time outside) and, after a stop in the dark, recharges."""
    if m.rover["busy"]:
        m.rover["eta_h"] += h
    if pct:
        m.power = max(0.0, m.power - pct)


def _nav_auto(m, t, s):
    """The ice drive's nav calls settle themselves when nobody makes them: no glare (the Sun is down or behind), the
    drive is over, or the call went unmade for NAV_WAIT_H hours once it was the card's step (that costs an hour)."""
    if t["kind"] != "ice_run" or s["done"] or s["id"] not in ("tack", "lights") or not t["steps"][0]["done"]:
        return
    out = _ice_out(m)
    if out < 0:
        s["done"], s["result"] = True, "Drive over."
        return
    if s["id"] == "tack" and s["ready_if"](m, t):
        sv = sun_view(m, leg=s.get("leg") or "out")
        if not sv["glare"]:
            s["done"], s["result"] = True, ("No glare: the Sun is down." if not sv["up"] else
                                            "No glare: the Sun is off the nose.")
            return
    i = t["steps"].index(s)
    if not all(x["done"] for x in t["steps"][:i]) or not s["ready_if"](m, t):
        return
    s.setdefault("open_h", m.t_h)
    if m.t_h - s["open_h"] < NAV_WAIT_H:
        return
    if s["id"] == "tack":
        _slow(m)
        s["done"], s["result"] = True, "No call. The driver slowed in the glare: 1 h lost."
    else:
        _slow(m, pct=LIGHTS_COST_PCT)
        s["done"], s["result"] = True, "No lights. The rover stopped at the shadow: 1 h lost."


# ---- [0.5 field] the sample station (Artemis sampling, Naids et al. 2021; Field School: Field kit) ---------------------
STATION = {   # what is in front of the crew -> (card line, right tool, one chip word per descriptor kind)
    "rock": ("A fist-size rock", "tongs", {"size": "Fist-size", "shape": "Rounded", "tone": "Bright", "texture": "Rough"}),
    "pebbles": ("Loose pebbles", "rake", {"size": "Tiny", "shape": "Round", "tone": "Gray", "texture": "Bumpy"}),
    "chip": ("A big boulder", "hammer", {"size": "Huge", "shape": "Jagged", "tone": "Dark", "texture": "Cracked"}),
    "soil": ("Fine soil", "scoop", {"size": "Small", "shape": "Flat", "tone": "Dark", "texture": "Dusty"}),
    "layers": ("Soil in layers", "tube", {"size": "Deep", "shape": "Flat", "tone": "Gray", "texture": "Grainy"}),
}
TOOLS = {"rake": "Rake", "tongs": "Tongs", "hammer": "Hammer", "scoop": "Scoop", "tube": "Drive tube"}
TOOL_USE = {"rake": "The rake gathers small rocks.", "tongs": "Tongs grab one rock.",
            "hammer": "The hammer chips a piece off.", "scoop": "The scoop takes fine soil.",
            "tube": "The drive tube keeps the layers."}
ASK = {"size": "How big is it?", "shape": "What shape is it?", "tone": "Bright or dark?",
       "texture": "Smooth or rough?", "shadow": "Any shadows?"}
_ONES = "zero one two three four five six seven eight nine".split()
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}
_TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()


def _num_words(n: int) -> str:
    return _TEENS[n - 10] if 10 <= n < 20 else (_TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10]))


def _station(m):
    """Take a sample, the way Artemis crews will: pick the tool, describe it in one line, read the bag number in."""
    k = _gp(m)["count"].get("station", 0)
    _gp(m)["count"]["station"] = k + 1
    rng = random.Random(f"{m.site_id}:{m.seed}:station:{k}")
    target = rng.choice(sorted(STATION))
    line, tool, look = STATION[target]
    others = [x for x in sorted(TOOLS) if x != tool]
    rng.shuffle(others)
    tools = others[:2 if m.difficulty == "cadet" else 3] + [tool]
    rng.shuffle(tools)
    bag = 10 * (k + 1) + rng.randrange(1, 10)
    pick = _choice("tool", f"{line}. Which tool?", [{"id": x, "label": TOOLS[x]} for x in tools],
                   why="The right tool keeps the sample whole.")
    desc = {"id": "describe", "kind": "describe", "label": "Describe it in one line.", "target": "task",
            "ready_if": None, "look": look, "need": STATION_KINDS, "got": [],
            "why": "Size, shape, bright or dark, texture: what a geologist notes."}
    call = {"id": "bag", "kind": "sequence", "label": f"Call it in: bag {bag}.", "target": "task", "ready_if": None,
            "items": [{"id": "bag", "label": f"Bag {bag}", "say": [f"bag {bag}", str(bag), _num_words(bag)]}],
            "button": f"Bag {bag}", "why": "Numbered bags tell Houston where each sample came from."}
    for x in (pick, desc, call):
        x["lesson"] = "fieldkit"
    return dict(title="Sample station", lesson="fieldkit", panel="rover", level="info", priority=10,
                deadline_h=m.t_h + 4, sub="sample", say=None, steps=[pick, desc, call], tool=tool, bag=bag,
                target_line=line)


def _station_points(t) -> float:
    got = (t["steps"][1].get("got") or [])
    right = t["steps"][0].get("picked") == t["tool"]
    return STATION_BAG + (STATION_TOOL if right else 0) + STATION_KIND * min(STATION_KINDS, len(got))


# ---- [0.5 field] the science team's replan (JETT5 science ops: one CAPCOM voice; Flight approves) -----------------------
def _rover_calls_done(m) -> bool:
    """The drive's own calls are made (route, tack, boulders, lights): the replan never interrupts one."""
    return all(all(s["done"] for s in t["steps"] if s["id"] != "back")
               for t in _active(m) if t["kind"] in ("ice_run", "explore"))


def _margin(m) -> dict:
    """The drive's light margin from the sim: hours of Sun (JPL Horizons on the LOLA skyline) left after the rover's
    ETA. None when the Sun stays up for the rest of the mission."""
    eta = m.rover["eta_h"]
    lit = sim.env_at(m, m.t_h)["lit"]
    sun_h = sim.next_sun_change_h(m, m.t_h) if lit else 0
    margin = None if lit and sun_h is None else max(0, (sun_h or 0) - eta)
    return {"eta_h": eta, "sun_h": sun_h, "lit": lit, "margin_h": margin,
            "tight": margin is not None and margin < REPLAN_MARGIN_H}


def _samples_left(m) -> int:
    return max(0, SCIENCE_TASKS[m.difficulty] - _gp(m)["count"].get("science", 0))


def _replan(m):
    mg, left = _margin(m), _samples_left(m)
    if mg["margin_h"] is None:
        mtxt = "Sun stays up all day."
    elif not mg["lit"]:
        mtxt = "Sun is down: no margin."
    else:
        mtxt = f"Light margin {mg['margin_h']} h."
    stxt = f"−{SAMPLE_SCIENCE:g} science later." if left else "No samples left. Free."
    pick = _choice("trade", f"{REPLAN_MIN} min at the bright rock. What do we give up?",
                   [{"id": "margin", "label": "Use the margin", "hint": mtxt},
                    {"id": "sample", "label": "Drop a sample", "hint": stxt}],
                   hint="Adding time here costs time somewhere else.",
                   why="Flight keeps a light margin on every drive.")
    rb = {"id": "readback", "kind": "sequence", "label": f"Flight approves. Read back: {REPLAN_MIN} minutes at the rock, copy.",
          "target": "task", "ready_if": None, "button": "Read it back",
          "items": [{"id": "time", "label": f"{REPLAN_MIN} minutes", "say": [f"{REPLAN_MIN} minutes", f"{REPLAN_MIN} min",
                                                                         f"{REPLAN_MIN}"]},
                    {"id": "rock", "label": "at the rock", "say": ["rock"]},
                    {"id": "copy", "label": "copy", "say": ["copy", "copied", "roger"]}],
          "why": "A readback proves the call was heard right."}
    for x in (pick, rb):
        x["lesson"] = "rocks"
    return dict(title="Science stop", lesson="rocks", panel="rover", level="info", priority=45,
                deadline_h=m.t_h + 2, say="Science Officer: unusual bright rock. The science room asks for 15 minutes.",
                steps=[pick, rb], margin=mg)


def _repair(m):
    return dict(title="Fix the solar array", lesson="power", panel="rover", level="caution", priority=60,
                say="Arrays damaged. Three steps to fix them.",
                steps=[_press("check", "Check the array", "Array at half power. The rover can fix it.",
                              why="A micrometeorite hit it. Find out how bad."),
                       _order("send", "Send the rover to fix it", "task", ROVER("repair_array"),
                              lambda m, t: m.array_eff >= 1 or m.rover["task"] == "repair_array", "Rover on its way."),
                       _press("test", "Test the power", "Full power again. Nice repair.",
                              ready=lambda m, t: m.array_eff >= 1)])


def _station_due(m) -> bool:
    """[0.4.1] Every mission gets at least one sample station (Field School: Field kit)."""
    return not _gp(m)["count"].get("station")


def _station_stop(m) -> bool:
    """[0.4.1] The guaranteed station when the lab never gets a quiet hour (Malapert's long drives and nights): past
    STATION_DUE_H with no station yet, the rover crew stops for one on a drive whose calls are made. Rewards as usual."""
    rv = m.rover
    return (_station_due(m) and m.t_h >= STATION_DUE_H and rv["busy"] and rv["task"] in ("collect_ice", "explore")
            and rv["eta_h"] >= 2 and _calm(m) and not m.shelter and _rover_calls_done(m))


def _science(m):
    n = _gp(m)["count"].get("science", 0)
    # the first science job is always the station (a replan's dropped sample used to rotate it away)
    sub = "sample" if _station_due(m) else SCIENCE_ROTATION[n % len(SCIENCE_ROTATION)]
    if sub == "sensor":
        return dict(title="Read the radiation sensor", lesson="radiation", panel="radiation", level="info", priority=10,
                    deadline_h=m.t_h + 4, sub="sensor", say=None,
                    steps=[_press("read", "Read the sensor", None, why="Every dose counts toward the crew's limit."),
                           _choice("log", "Log it: normal or high?",
                                   [{"id": "normal", "label": "Normal"}, {"id": "high", "label": "High"}],
                                   hint=f"Quiet Sun: under {QUIET_RATE:g} mSv/h")])
    if sub == "sample":   # [0.5 field] the sample is a station: tool, describe, bag number
        t = _station(m)
        if m.rover["busy"]:   # [0.4.1] the guaranteed stop on a drive: above the drive's own card, below a replan
            t.update(priority=44, say="Rover crew: a quick sample stop on the way.")
        return t
    title, panel, label, ack, why = SCIENCE_PRESS[sub]
    return dict(title=title, lesson="moon", panel=panel, level="info", priority=10, deadline_h=m.t_h + 4,
                sub=sub, say=None,
                steps=[_press("sample", label, f"{ack}. Science +{SAMPLE_SCIENCE:g}." if sim.env_at(m, m.t_h)["earth_visible"]
                              else f"{ack}. Science +{SAMPLE_SCIENCE:g}, saved for Earthrise.", why=why)])


# ---- triggers: (kind, builder, when) in priority order -----------------------------------------------------------------
def _calm(m) -> bool:
    return not _storm(m) and _warning(m) is None


def _has_sun_cycle(m) -> bool:
    """The outpost's arrays have nights in this mission (a cabled site: its rim arrays, on the real skyline)."""
    return not all(sim.sky_table(m.site_id)[0])


TRIGGERS = [
    ("storm_hit", _storm_hit, lambda m: (lambda st: bool(st and st.event.get("sep")) and not m.shelter)(_storm(m))),
    ("first_power", _first_power, lambda m: m.t_h == 0 and not m.acted.get("allocate")),
    ("storm_prep", _storm_prep, lambda m: _warning(m) is not None and not _storm(m)),
    ("night_prep", _night_prep, lambda m: _has_sun_cycle(m) and not m.power_save and (
        (lambda e, h: (e["lit"] and h is not None and h <= sim.SUNSET_NOTICE_H) or not e["lit"])(
            sim.env_at(m, m.t_h), sim.next_sun_change_h(m, m.t_h)))),
    ("low_power", _low_power, lambda m: m.difficulty == "commander" and m.power < 20 and not m.power_save),
    ("all_clear", _all_clear, lambda m: m.shelter and not _storm(m) and _warning(m) is None),
    ("life_check", _life_check, lambda m: m.life < LIFE_CHECK and not m.rover["busy"] and not m.shelter and
     not _storm(m)),
    ("repair", _repair, lambda m: m.array_eff < 1),
    ("comm_window", _comm_window, lambda m: sim.env_at(m, m.t_h)["earth_visible"] and m.t_h > 0 and
     (m.science - m.science_sent >= 3 or m.houston_calls == 0)),
    ("sunrise", _sunrise, lambda m: _has_sun_cycle(m) and m.power_save and sim.env_at(m, m.t_h)["lit"] and
     (sim.next_sun_change_h(m, m.t_h) or 99) > sim.SUNSET_NOTICE_H),
    ("replan", _replan, lambda m: m.rover["busy"] and m.rover["task"] in ("collect_ice", "explore") and
     m.t_h - m.rover_left_h >= ROCK_AT_H and m.rover["eta_h"] >= 2 and sim.env_at(m, m.t_h)["earth_visible"] and
     _calm(m) and _gp(m)["count"].get("replan", 0) < REPLAN_MAX and _rover_calls_done(m)),
    ("ice_run", _ice_run, lambda m: not sim.objectives(m)["ice"]["met"] and not m.rover["busy"] and not m.shelter and
     _calm(m) and m.t_h >= 2 and m.power > 35),
    ("explore", _explore, lambda m: sim.objectives(m)["ice"]["met"] and not m.rover["busy"] and not m.shelter and
     _calm(m) and m.power > 50 and sim.env_at(m, m.t_h)["lit"] and m.t_h <= sim.MISSION_H - 24 and
     _gp(m)["count"].get("explore", 0) < EXPLORE_TASKS),
    ("science", _science, lambda m: (m.t_h >= 3 and not m.shelter and not m.power_save and _calm(m) and
     _gp(m)["count"].get("science", 0) < SCIENCE_TASKS[m.difficulty]) or _station_stop(m)),
]
PRIORITY = {k: i for i, (k, _, _) in enumerate(TRIGGERS)}


def _active(m) -> list[dict]:
    g = _gp(m)
    return [g["tasks"][i] for i in g["order"] if g["tasks"][i]["status"] == "active"]


def _start(m, kind, builder, out):
    g = _gp(m)
    spec = builder(m)
    if not spec:
        return None
    g["seq"] += 1
    tid = f"{kind}-{g['seq']}"
    t = {"id": tid, "kind": kind, "status": "active", "started_h": m.t_h, "deadline_h": None, "key": None, "cool_h": 0,
         **spec}
    for s in t["steps"]:
        s.setdefault("done", False)
        s.setdefault("result", None)
        if s["kind"] == "order":
            # [polish 1] never re-ask a satisfied step: once done it stays done (a later power move that trims the
            # heaters to 9% doesn't bring "Heaters to 10" back). Steps marked live (the shelter) keep showing the truth.
            s.setdefault("latch", not s.get("live"))
            c = s.get("cmd") or {}
            if c.get("type") == "dispatch" and c.get("task") != "return":
                _gate_rover(s)
        elif s.get("gate"):
            _gate_rover(s, home_only=s["gate"] == "rover_home")
    g["tasks"][tid] = t
    g["order"].append(tid)
    g["count"][kind] = g["count"].get(kind, 0) + 1
    if t.get("key") is not None:
        g.setdefault("keys", []).append(t["key"])
    _ev(m, out, "task", f"New task: {t['title']}.", phase="start", task=tid, task_kind=kind)
    return t


def _rover_charge(m) -> float:
    """The battery a rover trip takes (sim.py dispatch: the base charge plus the site's LOLA slope)."""
    return sim.ROVER_POWER + sim.site(m.site_id).get("rover_slope_power", 0)


def _rover_free(m) -> bool:
    return not m.rover["busy"] and not m.shelter and m.power >= _rover_charge(m)


def _gate_rover(s, home_only=False):
    """A step that sends the rover is only ready when the sim would take it: the rover is home and the crew is out of
    the shelter. Before, the card offered "Send the rover" while the rover was out, the sim said no, and a player who
    pressed the card's button again and again never moved the clock (the Commander stall)."""
    rdy = s.get("ready_if")
    free = (lambda m: not m.rover["busy"]) if home_only else _rover_free
    s["ready_if"] = (lambda m, t: free(m) and rdy(m, t)) if rdy else (lambda m, t: free(m))
    wt = s.get("wait_text")
    s["wait_text"] = lambda m, t: (f"The rover is out. Back in about {m.rover['eta_h']} h." if m.rover["busy"] else
                                   None if home_only else
                                   "Waits until the crew is out of the shelter." if m.shelter else
                                   "Battery too low for the rover. It waits for the Sun." if m.power < _rover_charge(m) else
                                   (wt(m, t) if callable(wt) else wt))


def _close(m, t, status, out, text=None):
    t["status"] = status
    t["closed_h"] = m.t_h
    g = _gp(m)
    if t.get("cool_h"):
        g["cool"][t["kind"]] = m.t_h + t["cool_h"]
    if t["kind"] == "science":
        g["cool"]["science"] = m.t_h + SCIENCE_EVERY_H
    if status == "done":
        _log(m, "task", t["title"], text or f"{t['title']}: done.")
    elif status == "missed" and t["kind"] not in ("science", "first_power"):
        _log(m, "missed", t["title"], text or f"{t['title']}: ran out of time.")
    _ev(m, out, "task", text or f"{t['title']}: {status}.", phase=status, task=t["id"], task_kind=t["kind"])


def _check(m, out) -> list[dict]:
    """Latch the steps the state now satisfies; close finished or expired tasks. Returns the steps just completed."""
    done_now = []
    for t in _active(m):
        for s in t["steps"]:
            _nav_auto(m, t, s)   # [0.5 field] the low-Sun drive's calls: no glare, drive over, or unmade (a cost)
            _storm_auto(m, t, s)   # [0.4.1] the storm's readback and confirm never block a sheltered crew
            if s.get("ready_if") and not s["done"]:   # a step that becomes doable is news: it stops a skip and the warp
                r = bool(s["ready_if"](m, t))
                if r and s.get("was_ready") is False:
                    _ev(m, out, "task", f"{t['title']}: {s['label']}.", phase="ready", task=t["id"], task_kind=t["kind"], step=s["id"])
                s["was_ready"] = r
            f = s.get("done_if")
            if f and not (s.get("latch") and s["done"]):
                # an order step shows the truth: done while the state says so (the rover can leave again)
                now = bool(f(m, t))
                if now and not s["done"]:
                    done_now.append(s)
                s["done"] = now
                continue
            if s["done"]:
                continue
            if s["kind"] == "choice" and s["id"] == "steer" and t["steps"][0]["done"] and \
                    (not m.rover["busy"] or m.t_h - m.rover_left_h >= STEER_AFTER_H + STEER_WAIT_H):
                s["done"], s["result"] = True, "The rover found its own way."
        if t["kind"] == "ice_run" and not m.rover["busy"] and m.ice_runs == t["runs"] and t["steps"][0]["done"]:
            _close(m, t, "cancelled", out, "Rover home without ice.")
            continue
        if all(s["done"] for s in t["steps"]):
            _close(m, t, "done", out, _done_text(m, t))
        elif t.get("deadline_h") is not None and m.t_h >= t["deadline_h"]:
            _close(m, t, "missed", out)
        elif t["kind"] in ("storm_prep",) and _storm(m):
            _close(m, t, "missed", out, "The storm arrived before the prep was done.")
        elif t["kind"] == "first_power" and m.t_h > 0:
            _close(m, t, "missed", out)
    return done_now


def _done_text(m, t) -> str:
    return {"ice_run": "Ice run complete. Life support up.", "storm_prep": "Ready before the storm.",
            "storm_hit": "Crew sheltered through the storm.", "night_prep": "Outpost powered down for the night.",
            "comm_window": "Science sent and Houston called.", "repair": "Solar array fixed. Full power.",
            "life_check": "Life support balanced.", "first_power": "Power set for day one.",
            "sunrise": "Outpost awake at sunrise.", "low_power": "Battery saved.",
            "science": "Science logged.", "explore": "Science drive done. Samples home.",
            "replan": "Rock sampled. Flight's call read back."}.get(t["kind"], f"{t['title']}: done.")


def _trigger(m, out):
    g = _gp(m)
    kinds = {t["kind"] for t in _active(m)}
    for kind, builder, when in TRIGGERS:
        if kind in kinds or g["cool"].get(kind, -1) > m.t_h:
            continue
        if kind == "science" and kinds and not (_station_stop(m) and kinds <= {"ice_run", "explore"}):
            continue   # a sample is what you do when nothing else needs you (or the guaranteed stop on a drive)
        try:
            if not when(m):
                continue
        except (KeyError, TypeError):
            continue
        key = _key_of(m, kind)
        if key is not None and key in g.get("keys", []):
            continue
        _start(m, kind, builder, out)
        kinds.add(kind)


def _key_of(m, kind):
    """Once-per-thing tasks: one prep and one shelter task per storm, one night checklist per sunset."""
    if kind == "storm_hit":
        st = _storm(m)
        return ("storm", st.event["id"]) if st else None
    if kind == "storm_prep":
        sid = next((st.event["id"] for st in m.storms if m.warned.get(st.event["id"]) and m.t_h < st.start_h), None)
        return ("prep", sid)
    if kind == "night_prep":
        e, h = sim.env_at(m, m.t_h), sim.next_sun_change_h(m, m.t_h)
        return ("night", m.t_h + (h or 0)) if e["lit"] else ("dark", m.t_h // 24)
    if kind == "sunrise":
        return ("sunrise", m.t_h // 12)
    if kind == "first_power":
        return ("first_power",)
    return None


# ---- story beats -----------------------------------------------------------------------------------------------------
def _beat(m, bid, out):
    g = _gp(m)
    if bid in {b["id"] for b in g["beats"]}:
        return
    title, say, visual, objective = BEATS[bid]
    g["beats"].append({"id": bid, "t_h": m.t_h})
    _log(m, "beat", title, say)
    _ev(m, out, "beat", say, beat=bid, title=title, visual=visual, objective=objective)


def _beats(m, out):
    g = _gp(m)
    seen = {b["id"] for b in g["beats"]}
    kinds = [e["kind"] for e in out]
    if "arrival" not in seen:
        _beat(m, "arrival", out)
    if "settle" not in seen and m.t_h >= 2:
        _beat(m, "settle", out)
    env = sim.env_at(m, m.t_h)
    if "comm_gap" not in seen and m.t_h >= 3 and not env["earth_visible"] and \
            (sim.next_comm_window_h(m, m.t_h) or 999) >= 12:
        _beat(m, "comm_gap", out)
    if "sunset" in kinds:
        _beat(m, "first_dark", out)
    if "storm_warning" in kinds:
        _beat(m, "forecast", out)
    if any(e["kind"] == "solar_storm" and e.get("sep") for e in out):
        _beat(m, "crisis", out)
    if "storm_end" in kinds and "crisis" in {b["id"] for b in g["beats"]}:
        _beat(m, "recovery", out)
    if "comm_open" in kinds and "comm_gap" in {b["id"] for b in g["beats"]}:
        _beat(m, "earthrise", out)
    if any(e["kind"] == "rover_back" and "ice" in e["text"] for e in out):
        _beat(m, "ice_return", out)
    if m.t_h >= 192 and env["earth_visible"] and (m.science - m.science_sent) >= 1:
        _beat(m, "final_downlink", out)
    if m.over and m.outcome == "survived":
        _beat(m, "complete", out)


def _good_calls(m):
    g = _gp(m)
    for c in m.good_calls[g["calls_seen"]:]:
        _log(m, "good_call", "Good call", c["text"])
    g["calls_seen"] = len(m.good_calls)


# ---- chapters (docs/MISSION_POLISH_SPEC.md): five ~2-day chapters, each ends on a card with three stars -----------------
CHAPTER_H = 48
CHAPTERS = ("First light", "Settling in", "Holding steady", "The long haul", "Homeward")
STAR_SAFE_DOSE = sim.DOSE_LIMIT / 5          # mSv: the crew stays under its share of the 10-day limit
STAR_SAFE_LIFE = 40                          # % air and water never dips under this
STAR_POWER_MIN = 20                          # % battery never dips under this
STAR_SCIENCE = sim.SCIENCE_GOAL / 10         # science sent home in the chapter (half the even pace: a fair bar)
STAR_TIPS = {"safe": "Shelter early next time. The crew's dose climbed.",
             "powered": "The battery dipped low. Night mode sooner saves it.",
             "science": "Send science home whenever Earth is up.",
             # [playtest 4] a chapter with no Earth window: the star is for science gathered and kept on board
             "science_stored": "Do the science jobs. They wait on board for Earthrise."}
def gp_sample() -> float:
    return SAMPLE_SCIENCE


DOWNLINK_H = 4                               # Earth-up hours a chapter needs to send STAR_SCIENCE (3 per hour, comms 5)


def lab_hours(m, n: int) -> int:
    """Hours the lab can run in chapter n: the arrays lit (Horizons + LOLA) and no particle storm on (the shelter)."""
    lit = sim.sky_table(m.site_id)[0]
    return sum(1 for h in range(n * CHAPTER_H, min((n + 1) * CHAPTER_H, len(lit)))
               if lit[h] and not any(st.active(h) and st.event.get("sep") for st in m.storms))


def earth_hours(m, n: int) -> int:
    """Hours Earth is above the outpost's horizon in chapter n (Horizons + the LOLA skyline, sim.sky_table)."""
    earth = sim.sky_table(m.site_id)[1]
    return sum(earth[n * CHAPTER_H:(n + 1) * CHAPTER_H])


def _ch(m) -> dict:
    g = _gp(m)
    c = g.get("chapter")
    if c is None:
        c = g["chapter"] = {"n": 0, "dose0": m.dose, "sent0": m.science_sent, "sci0": m.science, "min_power": m.power,
                            "min_life": m.life}
        g["chapters"] = []
    return c


def chapter_of(t_h: int) -> int:
    return min(len(CHAPTERS) - 1, t_h // CHAPTER_H)


def _chapters(m, out):
    """Track the chapter's lows; when its two days end (or the mission does), score it and say so (a "chapter" event,
    which stops a skip: the cabin shows the chapter card and the game auto-saves, registry.py)."""
    c = _ch(m)
    c["min_power"], c["min_life"] = min(c["min_power"], m.power), min(c["min_life"], m.life)
    end = (c["n"] + 1) * CHAPTER_H
    if m.t_h < end and not m.over:
        return
    done = _gp(m)["chapters"]
    if c["n"] >= len(CHAPTERS) or (done and done[-1]["last"]):
        return
    stars = {"safe": m.dose - c["dose0"] <= STAR_SAFE_DOSE and c["min_life"] >= STAR_SAFE_LIFE and
             m.outcome in (None, "survived"),
             "powered": c["min_power"] >= STAR_POWER_MIN,
             "science": False}
    # [playtest 4] Earth sets the science star. A chapter with a real downlink window (Horizons + LOLA) scores the
    # science SENT home; one with no window (Shackleton Rim until Day 6) scores the science GATHERED, which waits on
    # board (store and forward) and goes home at Earthrise. Either way a kid who does the jobs can earn it.
    # The bar follows the chapter's sky too: a chapter that is mostly night or storm (the lab sleeps in night mode and
    # in the shelter) asks for half a point per lab hour, at least one science job's worth.
    stored = earth_hours(m, c["n"]) < DOWNLINK_H
    sent, got = m.science_sent - c["sent0"], m.science - c.get("sci0", m.science)
    lab = lab_hours(m, c["n"])
    goal = STAR_SCIENCE if not stored else min(STAR_SCIENCE, max(gp_sample(), round(lab * 0.5)))
    stars["science"] = (got >= goal) if stored else (sent >= goal)
    n = sum(stars.values())
    miss = next((k for k in ("safe", "powered", "science") if not stars[k]), None)
    line = ("Three stars. Textbook flying, Outpost Luna." if n == 3 else
            STAR_TIPS["science_stored" if miss == "science" and stored else miss])
    rec = {"n": c["n"] + 1, "of": len(CHAPTERS), "title": CHAPTERS[c["n"]], "days": [c["n"] * 2 + 1, c["n"] * 2 + 2],
           "stars": stars, "count": n, "capcom": line, "t_h": m.t_h, "last": c["n"] + 1 >= len(CHAPTERS) or m.over,
           "science": {"mode": "stored" if stored else "sent", "sent": round(sent, 1), "got": round(got, 1),
                       "goal": goal}}
    _gp(m)["chapters"].append(rec)
    _ev(m, out, "chapter", f"Chapter {rec['n']} done: {n} of 3 stars. {line}", chapter=rec)
    _gp(m)["chapter"] = {"n": c["n"] + 1, "dose0": m.dose, "sent0": m.science_sent, "sci0": m.science,
                         "min_power": m.power, "min_life": m.life}


# ---- the sim's hooks -------------------------------------------------------------------------------------------------
def update(m, out: list):
    """Called by sim._tick after every mission hour (and after each order, with no time passing)."""
    _gp(m)
    _chapters(m, out)
    _beats(m, out)
    _check(m, out)
    if not m.over:
        _trigger(m, out)
        _check(m, out)   # a task whose steps the state already meets closes at once (no stale "do this")
    _good_calls(m)


def after_command(m, cmd: dict, r: dict) -> str | None:
    """An order went through: tick off task steps; return the first acknowledgement ("Shields up. Good.")."""
    g = _gp(m)
    out: list = []
    done = _check(m, out)
    if not m.over:
        _trigger(m, out)
    _good_calls(m)
    r.setdefault("events", [])
    r["events"] = list(r["events"]) + [e for e in out if e not in r["events"]]
    ack = next((s["ack"] for s in done if s.get("ack")), None)
    if ack:
        g["ack"] = {"t_h": m.t_h, "text": ack, "n": g.get("ack_n", 0) + 1}
        g["ack_n"] = g["ack"]["n"]
    return ack


def task_command(m, cmd: dict) -> dict:
    """{"type": "task", "task": id, "step": step_id, "choice": option_id?}: a press or a choice on the task card."""
    g = _gp(m)
    t = g["tasks"].get(cmd.get("task") or "") or next(iter(_active(m)), None)
    if t is None or t["status"] != "active":
        return {"ok": False, "say": "No task waiting. All steady.", "readback": "", "events": []}
    s = next((x for x in t["steps"] if x["id"] == cmd.get("step")), None) or next((x for x in t["steps"] if not x["done"]), None)
    if s is None or s["done"]:
        return {"ok": False, "say": "That step is done.", "readback": "", "events": []}
    if s.get("ready_if") and not s["ready_if"](m, t):
        return {"ok": False, "say": _not_ready(m, t, s), "readback": "", "events": []}
    rb = s["label"]
    if s["kind"] in ("describe", "sequence"):   # [0.5 field] words over turns, or the card's buttons
        return _free_step(m, t, s, cmd)
    if s["kind"] == "order":   # the card's button runs the real order (the sim's own checks and confirms apply)
        r = sim.apply_command(m, s["cmd"])
        return r
    if s["kind"] == "wait":
        return {"ok": False, "say": _not_ready(m, t, s), "readback": "", "events": []}
    choice = cmd.get("choice")
    if s["kind"] == "choice":
        ids = [o["id"] for o in s["options"]]
        if choice not in ids:
            return {"ok": False, "say": "Pick one: " + " or ".join(o["label"] for o in s["options"]) + ".",
                    "readback": rb, "events": []}
    say, extra = _resolve(m, t, s, choice)
    if say is None:   # the resolution was an order that the sim refused or wants confirmed
        return extra
    s["done"], s["result"] = True, say
    g["ack"] = {"t_h": m.t_h, "text": say, "n": g.get("ack_n", 0) + 1}
    g["ack_n"] = g["ack"]["n"]
    out: list = []
    _check(m, out)
    if not m.over:
        _trigger(m, out)
    m.acted["task"] = m.acted.get("task", 0) + 1
    return {"ok": True, "say": say, "readback": rb, "ack": say, "events": list(extra.get("events", [])) + out}


def _done_step(m, t, s, say, events=None) -> dict:
    """A task step the kid finished: tick it, say so (the ack), and let the tasks move on."""
    g = _gp(m)
    s["done"], s["result"] = True, say
    g["ack"] = {"t_h": m.t_h, "text": say, "n": g.get("ack_n", 0) + 1}
    g["ack_n"] = g["ack"]["n"]
    out: list = []
    _check(m, out)
    if not m.over:
        _trigger(m, out)
    m.acted["task"] = m.acted.get("task", 0) + 1
    return {"ok": True, "say": say, "readback": s["label"], "ack": say, "events": list(events or []) + out}


def _progress(m, s, say) -> dict:
    """A turn that added something but didn't finish the step: never a miss (Field School's rule)."""
    g = _gp(m)
    g["ack"] = {"t_h": m.t_h, "text": say, "n": g.get("ack_n", 0) + 1}
    g["ack_n"] = g["ack"]["n"]
    m.acted["task"] = m.acted.get("task", 0) + 1
    return {"ok": True, "say": say, "readback": s["label"], "ack": say, "progress": True, "events": []}


def _free_step(m, t, s, cmd) -> dict:
    """[0.5 field] describe (descriptor kinds, Field School's grader) and sequence (a readback in order) steps. The
    words come from the voice (the router's task_choice with the text) or the voice bar; a chip adds its kind; the
    card's last button ("Bag it", "Bag 14", "Read it back") finishes the step with what it has."""
    from ..academy import grade   # lazy: grade imports this package's sim
    text, choice = (cmd.get("text") or "").strip(), cmd.get("choice")
    if s["kind"] == "describe":
        got = list(s.get("got") or [])
        heard = [choice] if choice in grade.DESCRIBE else grade._describe_heard(text, grade.DESCRIBE_ORDER) if text else []
        new = [k for k in heard if k not in got]
        got = [k for k in grade.DESCRIBE_ORDER if k in set(got) | set(heard)]
        s["got"] = got
        if len(got) >= s.get("need", STATION_KINDS) or choice == "bag" or (not text and choice is None):
            say = f"You noted {grade.describe_label(got)}. Now bag it." if got else "Bagged as it is. Next time, describe it."
            return _done_step(m, t, s, say)
        missing = [k for k in s["look"] if k not in got]
        ask = ASK[missing[0]] if missing else "Anything else?"
        say = f"Good: {grade.describe_label(new)}. {ask}" if new else f"Tell me one thing. {ask}"
        return _progress(m, s, say)
    # sequence: the readback
    items = s["items"]
    if text and choice is None:
        ok, ex = grade._sequence({"items": items}, {"got": s.get("got")}, text)
        s["got"] = ex["got"]
        if not ok:
            full = ", ".join(i["label"] for i in items)
            nxt = next(i["label"] for i in items if i["id"] == ex["next"])
            say = (f"Copy {', '.join(i['label'] for i in items if i['id'] in ex['got'])}. Then: {nxt}." if ex["got"] else
                   f"Say it back: {full}.")
            return _progress(m, s, say)
    return _done_step(m, t, s, _sequence_done(m, t, s))


def _sequence_done(m, t, s) -> str:
    """What finishing a readback does: the station's sample counts; the science stop's rock is bagged."""
    if t["kind"] == "science" and s["id"] == "bag":
        from ..academy import grade
        pts = _station_points(t)
        m.science += pts
        got = t["steps"][1].get("got") or []
        noted = f", {grade.describe_label(got)}" if got else ""
        tool = TOOLS[t["steps"][0].get("picked") or t["tool"]].lower()
        if sim.env_at(m, m.t_h)["earth_visible"]:
            return f"Copy, bag {t['bag']}: {tool}{noted}. Science +{pts:g}."
        return f"Logged: bag {t['bag']}, {tool}. Science +{pts:g}, saved for Earthrise."
    if t["kind"] == "replan":
        m.science += ROCK_SCIENCE
        return f"Readback correct. Bright rock bagged: maybe anorthosite. Science +{ROCK_SCIENCE:g}."
    if s["id"] == "readback":
        return "Readback correct. Get them in."
    if s["id"] == "confirm":
        return "Houston copies. Ride it out in there."
    return "Copy."


def _not_ready(m, t, s) -> str:
    if s["id"] in ("steer", "tack", "lights"):
        return {"steer": "No boulders yet. The rover is still driving.", "tack": "No glare yet. The rover is still driving.",
                "lights": "No shadow yet. The rover is still driving."}[s["id"]]
    if s["id"] == "test":
        return "Not yet. The rover is still fixing the array."
    if s["id"] == "back":
        return f"The rover is out. Back in about {m.rover['eta_h']} hours."
    return "Not yet."


def _resolve(m, t, s, choice) -> tuple[str | None, dict]:
    """What a press or a choice does. Small, real effects only (sim orders, a few science points)."""
    def order(cmd, ok_say):
        r = sim.apply_command(m, cmd)
        if not r.get("ok") or r.get("needs_confirm"):
            return None, r
        return ok_say or r.get("say"), r
    k, sid = t["kind"], s["id"]
    if k == "science" and sid == "sample":
        if m.shelter or m.power_save:
            return None, {"ok": False, "say": "The lab is asleep. Wake the outpost first.", "readback": "", "events": []}
        m.science += SAMPLE_SCIENCE
        return s.get("ack") or f"Sample logged. Science +{SAMPLE_SCIENCE:g}.", {}
    if k == "science" and sid == "read":
        rate = sim.dose_rate(m, m.t_h)
        t["reading"] = round(rate, 3)
        return f"The sensor reads {rate:.2f} millisieverts an hour.", {}
    if k == "science" and sid == "log":
        rate = t.get("reading", sim.dose_rate(m, m.t_h))
        right = "normal" if rate <= QUIET_RATE else "high"
        if choice == right:
            m.science += SAMPLE_SCIENCE
            return f"Logged: {right}. Right call. Science +{SAMPLE_SCIENCE:g}.", {}
        return f"Logged. It was {right}: quiet Sun is under {QUIET_RATE:g}.", {}
    if k == "repair" and sid in ("check", "test"):
        return s["ack"], {}
    if k == "night_prep" and sid == "battery":
        b, dark = _budget(m), _night_len(m, m.t_h)
        lasts = b["night"]["lasts_h"]
        verdict = ("Enough for the night." if lasts is None or not dark or lasts >= dark else
                   "Tight. Keep the loads low tonight.")
        return (f"Battery {m.power:.0f}%. In night mode it {_lasts(b['night'])}"
                f"{f'; the dark lasts {dark} h' if dark else ''}. {verdict}"), {}
    if k == "night_prep" and sid == "sunset":
        dark = _night_len(m, m.t_h)
        return (f"Sunset logged. Dark for about {dark} hours, from JPL Horizons." if dark else
                "Sunset logged, from JPL Horizons."), {}
    if k == "night_prep" and sid == "budget":
        b = _budget(m)
        if choice == "night":
            return order({"type": "power_save", "on": True}, f"Night mode: {b['night']['kw']:.1f} kW. {_lasts(b['night']).capitalize()}.")
        return f"Full power: {b['full']['kw']:.1f} kW. {_lasts(b['full']).capitalize()}. Watch the battery.", {}
    if k == "night_prep" and sid == "duty":
        d = int(choice)
        share = round(physics.model()["heater_full_duty_share_pct"]["value"] * d / 100)
        return order(ALLOC("heaters", share), f"Heaters at {d}% duty: {physics.heater_rated_kw() * d / 100:.2f} kW.")
    if k == "low_power" and sid == "cut":
        if choice == "night":
            return order({"type": "power_save", "on": True}, "Night mode on. Battery saved.")
        return order(ALLOC("science", 5), "Science trimmed. Battery saved.")
    if k == "storm_prep" and sid == "decide":
        if choice == "shelter":
            return order({"type": "shelter", "on": True}, "Crew sheltered. Better safe.")
        return "Okay, we wait and watch the sensor.", {}
    if k == "life_check" and sid == "air":
        if choice == "recycler":
            return order(ALLOC("life_support", s.get("up", 40)), f"Recycler at {s.get('up', 40)}%. Air will climb.")
        return order(ROVER("collect_ice"), "Rover off for ice.")
    if k == "ice_run" and sid == "route":
        return order({**ROVER("collect_ice"), "route": choice},
                     "Ridge route. Slow and steady." if choice == "ridge" else "Crater slope. Fast, but hungry.")
    if k == "science" and sid == "tool":   # [0.5 field] the station's tool: a wrong pick teaches, never stops the job
        s["picked"] = choice
        if choice == t["tool"]:
            return f"{TOOLS[choice]}. Good pick.", {}
        return f"{TOOLS[choice]}? {TOOL_USE[t['tool']]}", {}
    if k == "ice_run" and sid == "tack":
        if _ice_out(m) < 0:
            return "Drive over.", {}
        sv = sun_view(m, leg=s.get("leg") or "out")
        if choice != sv["side"]:   # away from the Sun: the Sun on the left -> tack right
            return "Sun off the nose. The drivers can see.", {}
        _slow(m)
        return "Into the glare! That cost an hour. Tack away from the Sun.", {}
    if k == "ice_run" and sid == "lights":
        return "Lights on. Rolling into the shadow.", {}
    if k == "replan" and sid == "trade":
        mg = _margin(m)
        if choice == "margin" and not mg["tight"]:
            rv = m.rover
            rv["late_min"] = rv.get("late_min", 0) + REPLAN_MIN
            if rv["late_min"] >= 60 and rv["busy"]:
                rv["eta_h"] += 1
                rv["late_min"] -= 60
            return f"Flight approves, {REPLAN_MIN} minutes at the rock.", {}
        g = _gp(m)
        g["count"]["science"] = g["count"].get("science", 0) + 1   # the next sample stop is the time we spend here
        if choice == "margin":
            why = f"sunset in {mg['sun_h']} h" if mg["lit"] else "no light left"
            return f"Flight: negative, {why}. We skip one sample instead.", {}
        return f"Flight approves, {REPLAN_MIN} minutes at the rock. One sample skipped.", {}
    if k == "ice_run" and sid == "steer":
        rv = m.rover
        if not (rv["busy"] and rv["task"] == "collect_ice"):
            return "The rover is already off the boulder field.", {}
        if choice == s.get("good"):
            rv["eta_h"] = max(1, rv["eta_h"] - 1)
            return "Nice driving. That saved an hour.", {}
        rv["eta_h"] += 1
        return "Bumpy! That cost an hour. The flat side was faster.", {}
    return s.get("ack") or "Done.", {}


# ---- the view (State fields) -----------------------------------------------------------------------------------------
def _lesson(lid):
    if not lid:
        return None
    v = {"id": lid, "n": LESSON_NO.get(lid), "title": LESSON_TITLE.get(lid)}
    if lid in FIELD_LESSONS:
        v["track"] = "field"
    return v


def _wait_text(m, t, s):
    w = s.get("wait_text")
    return w(m, t) if callable(w) else w


def _step_view(m, t, s) -> dict:
    ready = (not s.get("ready_if") or bool(s["ready_if"](m, t))) and s["kind"] != "wait"
    label = s["label"]
    if t["kind"] == "ice_run" and s["id"] == "tack" and ready and not s["done"]:
        # the data the call needs is in the line itself (a small window drops the card's readouts first)
        sv = sun_view(m, leg=s.get("leg") or "out")
        label = ("Glare: Sun dead ahead. Tack left or right?" if sv["side"] == "ahead" else
                 f"Glare: Sun {abs(sv['rel']):.0f}° {sv['side']}. Tack left or right?")
    v = {"id": s["id"], "kind": s["kind"], "label": label, "done": s["done"], "ready": ready and not s["done"],
         "target": s.get("target"), "result": s.get("result"),
         "wait": _wait_text(m, t, s) if not ready and not s["done"] else None, "why": s.get("why")}
    if s["kind"] == "order":
        v["cmd"] = s["cmd"]
    if s["kind"] == "choice":
        v["options"] = [{k: o[k] for k in ("id", "label", "hint") if k in o} for o in s["options"]]
        if s.get("hint"):
            v["hint"] = s["hint"]
    if s["kind"] == "describe":   # chips for the kinds still missing (the look's own words), then "Bag it"
        got = s.get("got") or []
        chips = [{"id": k, "label": w} for k, w in s["look"].items() if k not in got][:3]
        v.update(options=chips + [{"id": "bag", "label": "Bag it"}], got=list(got), need=s.get("need", STATION_KINDS))
    if s["kind"] == "sequence":
        v.update(options=[{"id": "say", "label": s.get("button") or s["items"][-1]["label"]}],
                 items=[{"id": i["id"], "label": i["label"]} for i in s["items"]], got=list(s.get("got") or []))
    if s.get("lesson"):
        v["lesson"] = s["lesson"]
    return v


def _readouts(m, t) -> list[dict]:
    r = []
    if t["kind"] in ("ice_run", "repair", "replan") and m.rover["busy"]:
        r.append({"k": "Rover back in", "v": f"{m.rover['eta_h']} h"})
    cur = next((s for s in t["steps"] if not s["done"]), None)
    if t["kind"] == "ice_run" and cur and cur["id"] == "tack" and _ice_out(m) >= 0:   # [0.5 field] read the Sun
        sv = sun_view(m, leg=cur.get("leg") or "out")
        up = "on the horizon" if sv["elev"] < 0.5 else f"{sv['elev']:.1f}° up"
        where = "dead ahead" if sv["side"] == "ahead" else f"{abs(sv['rel']):.0f}° {sv['side']}"
        r.append({"k": "Sun", "v": f"{where}, {up}"})
    if t["kind"] == "ice_run" and cur and cur["id"] == "lights" and _ice_out(m) >= 0:
        r.append({"k": "Shadow in", "v": f"{max(0, _shadow_h(m) - _ice_out(m))} h"})
    if t["kind"] == "replan":
        mg = t["margin"]
        r.append({"k": "Light margin", "v": "all day" if mg["margin_h"] is None else f"{mg['margin_h']} h"})
        r.append({"k": "Samples left", "v": str(_samples_left(m))})
    if t["kind"] == "science" and t.get("sub") == "sample":
        r.append({"k": "Science", "v": f"+{_station_points(t):g} so far"})
    if t["kind"] in ("ice_run", "repair", "storm_prep", "storm_hit"):
        r.append({"k": "Battery", "v": f"{m.power:.0f}%"})
        r.append({"k": "Dose rate", "v": f"{sim.dose_rate(m, m.t_h):.2f} mSv/h"})
    if t["kind"] == "comm_window":
        r.append({"k": "Science to send", "v": f"{max(0.0, m.science - m.science_sent):.0f}"})
        r.append({"k": "Sent home", "v": f"{m.science_sent:.0f} / {sim.SCIENCE_GOAL:.0f}"})
    if t["kind"] == "science" and t.get("reading") is not None:
        r.append({"k": "Sensor", "v": f"{t['reading']:.2f} mSv/h"})
    if t["kind"] in ("night_prep", "low_power", "sunrise"):
        r.append({"k": "Battery", "v": f"{m.power:.0f}%"})
    if t["kind"] == "life_check":
        r.append({"k": "Life support", "v": f"{m.life:.0f}%"})
    return r


def task_view(m, t) -> dict:
    steps = [_step_view(m, t, s) for s in t["steps"]]
    cur = next((s for s in steps if not s["done"]), None)
    left = None
    if t.get("deadline_h") is not None:
        left = round(max(0.0, t["deadline_h"] - m.t_h - m.frac), 2)
    return {"id": t["id"], "kind": t["kind"], "title": t["title"],
            "lesson": _lesson((cur or {}).get("lesson") or t.get("lesson")),
            "panel": t["panel"], "level": t["level"], "urgent": t["level"] == "warn", "say": t.get("say"),
            "steps": steps, "step": cur, "done_count": sum(s["done"] for s in steps), "total": len(steps),
            "time_left_h": left, "started_h": t["started_h"], "readouts": _readouts(m, t),
            "decision": bool(cur and cur["kind"] in ("choice", "describe", "sequence") and cur["ready"])}


def view(m) -> dict:
    """The State fields this layer adds: task, tasks_waiting, story, mission_log, progress."""
    g = _gp(m)
    act = sorted(_active(m), key=lambda t: -t["priority"])
    cur = task_view(m, act[0]) if act and not m.over else None
    beats = g["beats"]
    last = beats[-1] if beats else None
    story = None
    if last:
        title, say, visual, objective = BEATS[last["id"]]
        story = {"beat": last["id"], "t_h": last["t_h"], "title": title, "say": say, "visual": visual,
                 "objective": objective, "reached": [b["id"] for b in beats],
                 "arc": [{"id": b, "title": BEATS[b][0]} for b in ARC]}
    return {"task": cur, "tasks_waiting": max(0, len(act) - 1), "story": story, "mission_log": g["log"][-30:],
            "ack": g.get("ack"),
            "chapter": {"n": min(_ch(m)["n"], len(CHAPTERS) - 1) + 1, "of": len(CHAPTERS),
                        "title": CHAPTERS[min(_ch(m)["n"], len(CHAPTERS) - 1)], "done": g.get("chapters", [])},
            "progress": {"day": min(m.t_h // 24 + 1, 10), "days_done": round(min(m.t_h, sim.MISSION_H) / 24, 1),
                         "days_total": sim.MISSION_H // 24, "science_sent": round(m.science_sent, 1),
                         "science_goal": sim.SCIENCE_GOAL, "ice": m.ice_runs, "ice_goal": sim.ICE_GOAL,
                         # [playtest 4] gathered but not home yet: stored on board until Earth is up (the counter
                         # shows it, so a "Science +2" visibly counts while Earth is down)
                         "science_stored": round(max(0.0, m.science - m.science_sent), 1),
                         "earth_up": bool(sim.env_at(m, m.t_h)["earth_visible"]),
                         "earth_in_h": sim.next_comm_window_h(m, m.t_h)}}
