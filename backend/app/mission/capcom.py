"""CAPCOM: the voice of Mission Control in the Junior Astronaut Mission Trainer (docs/MISSION_CONTRACT.md).

Turns Commands and State into short kid-friendly lines:
  readback(cmd, state)     "Copy, commander. Moving 20 percent of power to the shields. That leaves less for the greenhouse."
  status(what, state)      answers from State, real units explained the first time ("mSv, a unit for radiation dose")
  houston(text, state)     a call to Houston -> (say, delay_ms). The reply waits for the real radio round trip.
Hard words use the app's glossary (data/glossary.json via MomentIndex.glossary) plus the mission terms below.
"""
from __future__ import annotations

import re

# Light takes ~1.28 s each way between the Earth and the Moon, so a question and its answer need ~2.6 s.
MOON_ROUND_TRIP_MS = 2600
# Mars: 3 to 22 minutes each way depending on where the planets are (6-44 min round trip): a real Mars crew can't
# have a conversation with Houston at all and has to act alone. MARS_ROUND_TRIP_MS = 6 * 60_000 .. 44 * 60_000.

NAMES = {"shields": "radiation shields", "life_support": "life support", "greenhouse": "greenhouse",
         "science": "science lab", "rover": "rover", "comms": "radio", "heaters": "heaters"}
TASK_SAY = {"collect_ice": "to dig up ice. Ice can become water and oxygen",
            "repair_array": "to fix the solar panels", "explore": "to explore", "return": "back to base"}
ROLE_OF = {"allocate": "power", "shelter": "life", "dispatch": "life", "call_houston": "comms"}
ROLE_NAME = {"power": "power officer", "life": "life support officer", "comms": "communications officer"}

# Mission words a 7-year-old won't know. Explained once per mission, then used plainly.
TERMS = {
    "msv": "mSv, a unit for radiation dose",
    "solar storm": "a solar storm, a burst of fast particles from the Sun",
    "battery": "the battery, which stores the solar panels' power for the dark",
    "life support": "life support, the machines that make air and clean water",
    "comm window": "a comm window, when Earth is above our horizon so the radio can reach it",
}
_explained: dict[str, set[str]] = {}


def term(mid: str | None, key: str, plain: str) -> str:
    """The long form the first time a mission meets a word, the short form after."""
    seen = _explained.setdefault(mid or "-", set())
    if key in seen:
        return plain
    seen.add(key)
    return TERMS.get(key, plain)


def glossary_line(text: str, glossary: dict | None) -> str | None:
    """If the kid asks what a word means, answer from the app glossary or the mission terms."""
    t = text.lower()
    for k, v in TERMS.items():
        if k in t or (k == "msv" and re.search(r"\b(millisievert|sievert)s?\b", t)):
            return v[0].upper() + v[1:] + "."
    for form, (word, explain) in (glossary or {}).items():
        if re.search(rf"\b{re.escape(form)}\b", t):
            return f"{word.capitalize()}: {explain}"
    return None


def _r(state: dict | None) -> dict:
    return (state or {}).get("resources") or {}


def _pct(v) -> str:
    return f"{round(float(v))} percent"


def _biggest_other(state: dict | None, *skip: str) -> str | None:
    loads = {k: v for k, v in ((state or {}).get("loads") or {}).items() if k not in skip and v}
    return max(loads, key=loads.get) if loads else None


def readback(cmd: dict, state: dict | None = None, mid: str | None = None) -> str:
    ty = cmd.get("type")
    if ty == "allocate":
        to, a, src = NAMES.get(cmd["to"], cmd["to"]), cmd["amount"], cmd.get("from")
        kind, v = a["kind"], a.get("value")
        if kind == "none":
            line = f"Turning off power to the {to}."
            if cmd["to"] in ("heaters", "life_support"):
                line += " Careful, the crew needs that one!"
            return f"Copy, commander. {line}"
        if kind == "all":
            return f"Copy, commander. All the power goes to the {to}. Everything else goes dark!"
        if kind == "half":
            line = f"Giving half of our power to the {to}."
        elif kind == "percent":
            line = f"Setting the {to} to {_pct(v)} of our power."
        elif kind == "little":
            line = f"A little {'more' if (v or 0) > 0 else 'less'} power for the {to}."
        else:
            n = abs(v or 0)
            line = (f"Moving {_pct(n)} of power to the {to}." if (v or 0) > 0
                    else f"Taking {_pct(n)} of power away from the {to}.")
        if src:
            line = line.rstrip(".") + f", from the {NAMES.get(src, src)}."
            cost = NAMES.get(src, src)
        else:
            other = _biggest_other(state, cmd["to"])
            cost = NAMES.get(other, other) if other else None
        if cost and (kind in ("half", "percent") or (v or 0) > 0):
            line += f" That leaves less for the {cost}."
        elif (v or 0) < 0:
            line += " That saves power for everything else."
        return f"Copy, commander. {line}"
    if ty == "dispatch":
        tgt = f" toward {cmd['target'].replace('_', ' ')}" if cmd.get("target") else ""
        if cmd["task"] == "return":
            return "Copy, commander. Calling the rover back to base."
        return f"Copy, commander. Sending the rover{tgt} {TASK_SAY[cmd['task']]}."
    if ty == "shelter":
        if cmd["on"]:
            return "Copy! Everyone into the shelter. Its thick walls block most of the radiation."
        return "Copy. The crew is leaving the shelter and getting back to work."
    if ty == "end_shift":
        return "Copy. Ending this shift. Six hours pass on the Moon."
    if ty == "confirm":
        return "Confirmed. Doing it now."
    if ty == "cancel":
        return "Cancelled. Nothing changed."
    if ty == "rule":
        return f"Standing order set: {rule_text(cmd)}"
    if ty == "call_houston":
        return "Calling Houston..."
    return "Copy, commander."


WHEN_SAY = {"storm": "if a solar storm comes", "low_power": "if power gets low", "dark": "when it gets dark",
            "comm_closed": "when we lose the radio link", "dose_high": "if the radiation dose gets high",
            "low_oxygen": "if the air gets low"}


def rule_text(rule: dict) -> str:
    then = readback(rule["then"]).replace("Copy, commander. ", "").replace("Copy! ", "").replace("Copy. ", "")
    then = then.split(". ")[0].rstrip(".!")
    return f"{WHEN_SAY.get(rule['when'], 'when that happens')}, {then[0].lower() + then[1:]}."


def status(what: str, state: dict | None, mid: str | None = None) -> str:
    if not state:
        return "The mission hasn't started yet. Pick a landing site to begin!"
    r, env = _r(state), state.get("env") or {}
    parts = []
    if what in ("power", "all"):
        p = r.get("power_pct")
        if p is not None:
            sun = "The Sun is up, so the solar panels are charging." if env.get("in_sun") else \
                "It's dark, so we're living on the battery."
            parts.append(f"The battery is at {_pct(p)}. {sun}")
    if what in ("oxygen", "life_support", "all"):
        o = r.get("life_support_pct")
        if o is not None:
            mood = "Plenty to breathe." if o >= 60 else "We should watch it." if o >= 30 else "That's low, commander!"
            parts.append(f"Air and water are at {_pct(o)} of what the mission needs. {mood}")
    if what in ("dose", "all"):
        d, lim = r.get("dose_msv"), r.get("dose_limit_msv")
        if d is not None:
            unit = term(mid, "msv", "mSv")
            line = f"The crew has had {d:g} {unit} so far"
            line += f", out of a safe limit of {lim:g}." if lim else "."
            rate = r.get("dose_rate_msv_h")
            if rate:
                line += f" Right now it goes up by {rate:g} every hour."
            parts.append(line)
    if what in ("storm", "all"):
        st = env.get("storm") or {}
        if st.get("active"):
            src = f" This is based on the {st['name']}." if st.get("name") else ""
            parts.append(f"A solar storm is hitting us now!{src} The shelter or the shields keep the crew safe.")
        elif what == "storm":
            parts.append("No solar storm right now. The Sun is calm.")
    if what in ("comms", "all"):
        if env.get("earth_visible"):
            parts.append("Earth is in the sky, so the radio can reach Houston.")
        else:
            nxt = env.get("next_comm_window_h")
            when = f" in about {nxt:g} hours" if isinstance(nxt, (int, float)) else " later"
            parts.append(f"Earth is below our horizon, so the radio can't reach Houston. Next chance{when}.")
    return " ".join(parts) or "All systems are steady, commander."


def houston(text: str, state: dict | None, mid: str | None = None) -> tuple[str, int]:
    """'Houston, how much oxygen do we have?' -> Houston's answer and the delay before it is spoken."""
    from .nlu import parse
    env = (state or {}).get("env") or {}
    if state and env.get("earth_visible") is False:
        return ("No answer. Earth is below the horizon, so the radio can't reach Houston right now. "
                "We have to decide on our own!"), 0
    q = parse(text)["commands"] if text else []
    qq = next((c for c in q if c["type"] == "query"), None)
    if qq:
        return f"Houston here. {status(qq['what'], state, mid)}", MOON_ROUND_TRIP_MS
    alerts = (state or {}).get("alerts") or []
    if (env.get("storm") or {}).get("active") or "dose_rate_high" in alerts:
        tip = "We see the solar storm too. Get the crew into the shelter or boost the shields."
    elif (_r(state).get("power_pct") or 100) < 30:
        tip = "Your battery is low. Turn down the science lab and save power for life support."
    else:
        tip = "We hear you loud and clear, commander. You're doing great. Keep the crew safe."
    return f"Houston here. {tip}", MOON_ROUND_TRIP_MS


def short(line: str) -> str:
    """Confused / frustrated kid: the first sentence only, calm."""
    first = re.split(r"(?<=[.!?])\s+", line.strip())[0]
    return first.replace("!", ".")


def excited(line: str) -> str:
    if line.endswith("!"):
        return line
    return line.rstrip(".") + "! Great call!" if line.startswith(("Copy", "Confirmed")) else line


def role_check(cmd: dict, role: str | None) -> str | None:
    """A command outside the speaker's team role -> the line asking the right officer to agree. None = allowed."""
    if not role:
        return None
    need = ROLE_OF.get(cmd.get("type"))
    if cmd.get("type") == "rule":
        need = ROLE_OF.get((cmd.get("then") or {}).get("type"))
    if need is None or need == role:
        return None
    who = ROLE_NAME.get(need, need)
    return f"That's the {who}'s job. {who[0].upper() + who[1:]}, do you agree?"
