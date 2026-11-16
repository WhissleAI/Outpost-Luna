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
    return {l["id"]: k + 1 for k, l in enumerate(ls)}, {l["id"]: l["title"] for l in ls}


LESSON_NO, LESSON_TITLE = _lesson_order()
SAMPLE_SCIENCE = 2.0       # a sample or a logged sensor reading: small, and only when the kid does it
SCIENCE_TASKS = {"cadet": 4, "commander": 6}
SCIENCE_EVERY_H = 8
STEER_AFTER_H = 2          # the boulder field comes up this far into an ice drive
STEER_WAIT_H = 2           # ...and the rover picks its own way if nobody steers in time
SHELTER_LEAD_H = 6         # storm prep: the shelter step opens this many hours before a likely storm
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
    "comm_gap": ("On our own", "Earth is below the horizon. No radio until it rises. We're on our own.", "earthset",
                 "No radio for now. Keep the crew safe."),
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
                                        why="Shields cut the radiation the crew soaks up every day.")])


def _shelter_step():
    """Crew into the shelter: ready once the rover crew is home (the sim refuses it while they are outside)."""
    s = _order("shelter", "Crew into the shelter", "shelter", {"type": "shelter", "on": True},
               lambda m, t: m.shelter, "Crew sheltered. Good.", why="Thick walls block most of the storm's particles.")
    s["live"] = True   # stays honest: a crew that walks out mid-storm is asked back in
    s["ready_if"] = lambda m, t: not m.rover["busy"]
    s["wait_text"] = "Shelter opens when the rover crew is home."
    return s


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
             _shelter_step()]
    return dict(title="Storm! Shelter the crew", lesson="radiation", panel="radiation", level="warn", priority=100,
                deadline_h=st.start_h + st.dur_h, key=("storm", st.event["id"]), say=None, steps=steps)


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
        steps.append(sh)
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
    back = _wait("back", "Rover back with ice", lambda m, t: m.ice_runs > runs, "Ice delivered. Life support up.")
    back["latch"] = True
    return dict(title="Ice run", lesson="life", panel="rover", level="info", priority=40,
                say="No storm due. Time for an ice run.", steps=[first, steer, back], runs=runs)


def _repair(m):
    return dict(title="Fix the solar array", lesson="power", panel="rover", level="caution", priority=60,
                say="Arrays damaged. Three steps to fix them.",
                steps=[_press("check", "Check the array", "Array at half power. The rover can fix it.",
                              why="A micrometeorite hit it. Find out how bad."),
                       _order("send", "Send the rover to fix it", "task", ROVER("repair_array"),
                              lambda m, t: m.array_eff >= 1 or m.rover["task"] == "repair_array", "Rover on its way."),
                       _press("test", "Test the power", "Full power again. Nice repair.",
                              ready=lambda m, t: m.array_eff >= 1)])


def _science(m):
    n = _gp(m)["count"].get("science", 0)
    sub = SCIENCE_ROTATION[n % len(SCIENCE_ROTATION)]
    if sub == "sensor":
        return dict(title="Read the radiation sensor", lesson="radiation", panel="radiation", level="info", priority=10,
                    deadline_h=m.t_h + 4, sub="sensor", say=None,
                    steps=[_press("read", "Read the sensor", None, why="Every dose counts toward the crew's limit."),
                           _choice("log", "Log it: normal or high?",
                                   [{"id": "normal", "label": "Normal"}, {"id": "high", "label": "High"}],
                                   hint=f"Quiet Sun: under {QUIET_RATE:g} mSv/h")])
    title, panel, label, ack, why = SCIENCE_PRESS[sub]
    return dict(title=title, lesson="moon", panel=panel, level="info", priority=10, deadline_h=m.t_h + 4,
                sub=sub, say=None,
                steps=[_press("sample", label, f"{ack}. Science +{SAMPLE_SCIENCE:g}.", why=why)])


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
    ("ice_run", _ice_run, lambda m: not sim.objectives(m)["ice"]["met"] and not m.rover["busy"] and not m.shelter and
     _calm(m) and m.t_h >= 2 and m.power > 35),
    ("science", _science, lambda m: m.t_h >= 3 and not m.shelter and not m.power_save and _calm(m) and
     _gp(m)["count"].get("science", 0) < SCIENCE_TASKS[m.difficulty]),
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
        elif t["kind"] == "storm_hit" and m.shelter:
            _close(m, t, "done", out, "Crew sheltered through the storm.")
        elif t["kind"] == "first_power" and m.t_h > 0:
            _close(m, t, "missed", out)
    return done_now


def _done_text(m, t) -> str:
    return {"ice_run": "Ice run complete. Life support up.", "storm_prep": "Ready before the storm.",
            "storm_hit": "Crew sheltered through the storm.", "night_prep": "Outpost powered down for the night.",
            "comm_window": "Science sent and Houston called.", "repair": "Solar array fixed. Full power.",
            "life_check": "Life support balanced.", "first_power": "Power set for day one.",
            "sunrise": "Outpost awake at sunrise.", "low_power": "Battery saved.",
            "science": "Science logged."}.get(t["kind"], f"{t['title']}: done.")


def _trigger(m, out):
    g = _gp(m)
    kinds = {t["kind"] for t in _active(m)}
    for kind, builder, when in TRIGGERS:
        if kind in kinds or g["cool"].get(kind, -1) > m.t_h:
            continue
        if kind == "science" and kinds:   # a sample is what you do when nothing else needs you
            continue
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
             "science": "Send science home whenever Earth is up."}


def _ch(m) -> dict:
    g = _gp(m)
    c = g.get("chapter")
    if c is None:
        c = g["chapter"] = {"n": 0, "dose0": m.dose, "sent0": m.science_sent, "min_power": m.power, "min_life": m.life}
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
             "science": m.science_sent - c["sent0"] >= STAR_SCIENCE}
    n = sum(stars.values())
    miss = next((k for k in ("safe", "powered", "science") if not stars[k]), None)
    line = ("Three stars. Textbook flying, Outpost Luna." if n == 3 else STAR_TIPS[miss])
    rec = {"n": c["n"] + 1, "of": len(CHAPTERS), "title": CHAPTERS[c["n"]], "days": [c["n"] * 2 + 1, c["n"] * 2 + 2],
           "stars": stars, "count": n, "capcom": line, "t_h": m.t_h, "last": c["n"] + 1 >= len(CHAPTERS) or m.over}
    _gp(m)["chapters"].append(rec)
    _ev(m, out, "chapter", f"Chapter {rec['n']} done: {n} of 3 stars. {line}", chapter=rec)
    _gp(m)["chapter"] = {"n": c["n"] + 1, "dose0": m.dose, "sent0": m.science_sent, "min_power": m.power,
                         "min_life": m.life}


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


def _not_ready(m, t, s) -> str:
    if s["id"] == "steer":
        return "No boulders yet. The rover is still driving."
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
    return {"id": lid, "n": LESSON_NO.get(lid), "title": LESSON_TITLE.get(lid)} if lid else None


def _wait_text(m, t, s):
    w = s.get("wait_text")
    return w(m, t) if callable(w) else w


def _step_view(m, t, s) -> dict:
    ready = (not s.get("ready_if") or bool(s["ready_if"](m, t))) and s["kind"] != "wait"
    v = {"id": s["id"], "kind": s["kind"], "label": s["label"], "done": s["done"], "ready": ready and not s["done"],
         "target": s.get("target"), "result": s.get("result"),
         "wait": _wait_text(m, t, s) if not ready and not s["done"] else None, "why": s.get("why")}
    if s["kind"] == "order":
        v["cmd"] = s["cmd"]
    if s["kind"] == "choice":
        v["options"] = [{k: o[k] for k in ("id", "label", "hint") if k in o} for o in s["options"]]
        if s.get("hint"):
            v["hint"] = s["hint"]
    return v


def _readouts(m, t) -> list[dict]:
    r = []
    if t["kind"] in ("ice_run", "repair") and m.rover["busy"]:
        r.append({"k": "Rover back in", "v": f"{m.rover['eta_h']} h"})
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
    return {"id": t["id"], "kind": t["kind"], "title": t["title"], "lesson": _lesson(t.get("lesson")),
            "panel": t["panel"], "level": t["level"], "urgent": t["level"] == "warn", "say": t.get("say"),
            "steps": steps, "step": cur, "done_count": sum(s["done"] for s in steps), "total": len(steps),
            "time_left_h": left, "started_h": t["started_h"], "readouts": _readouts(m, t),
            "decision": bool(cur and cur["kind"] == "choice" and cur["ready"])}


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
                         "science_goal": sim.SCIENCE_GOAL, "ice": m.ice_runs, "ice_goal": sim.ICE_GOAL}}
