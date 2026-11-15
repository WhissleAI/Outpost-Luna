"""CAPCOM: the voice of Mission Control in the Junior Astronaut Mission Trainer (docs/MISSION_CONTRACT.md).

Turns Commands and State into short radio lines (docs/COPY.md: one idea per sentence, 20 words max):
  readback(cmd, state)     "Copy. Radiation shields up 20 percent. Less for the greenhouse."
  status(what, state)      answers from State, real units explained the first time ("An mSv measures radiation dose.")
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
TASK_SAY = {"collect_ice": "for ice", "repair_array": "to fix the solar panels", "explore": "to explore",
            "return": "back to base"}
ROLE_OF = {"allocate": "power", "power_save": "power", "shelter": "life", "dispatch": "life", "call_houston": "comms"}
ROLE_NAME = {"power": "power officer", "life": "life support officer", "comms": "communications officer"}
COPY = "Copy."          # every readback opens with it; the Director keeps only the first one per turn

# Mission words a 7-year-old won't know. Explained once per mission (a short gloss), then used plainly.
TERMS = {
    "msv": "an mSv measures radiation dose",
    "solar storm": "a solar storm is a burst of fast particles from the Sun",
    "battery": "the battery stores solar power for the dark",
    "life support": "life support is the machines that make air and water",
    "comm window": "a comm window is when Earth is up and the radio works",
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


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _biggest_other(state: dict | None, *skip: str) -> str | None:
    loads = {k: v for k, v in ((state or {}).get("loads") or {}).items() if k not in skip and v}
    return max(loads, key=loads.get) if loads else None


def readback(cmd: dict, state: dict | None = None, mid: str | None = None) -> str:
    """CAPCOM's readback: "Copy." then the order in a few words, then its cost. Radio rhythm, one idea per sentence."""
    ty = cmd.get("type")
    if ty == "allocate":
        to, a, src = NAMES.get(cmd["to"], cmd["to"]), cmd["amount"], cmd.get("from")
        kind, v = a["kind"], a.get("value")
        if kind == "none":
            line = f"{_cap(to)} off."
            if cmd["to"] in ("heaters", "life_support"):
                line += " Careful, the crew needs those."
            return f"{COPY} {line}"
        if kind == "all":
            return f"{COPY} All power to the {to}. Everything else goes dark."
        if kind == "half":
            line = f"Half our power to the {to}."
        elif kind == "percent":
            line = f"{_cap(to)} at {_pct(v)}."
        elif kind == "little":
            line = f"A little {'more' if (v or 0) > 0 else 'less'} for the {to}."
        else:
            n = abs(v or 0)
            line = f"{_cap(to)} {'up' if (v or 0) > 0 else 'down'} {_pct(n)}."
        if src:
            line = line.rstrip(".") + f", from the {NAMES.get(src, src)}."
            cost = NAMES.get(src, src)
        else:
            other = _biggest_other(state, cmd["to"])
            cost = NAMES.get(other, other) if other else None
        if cost and (kind in ("half", "percent") or (v or 0) > 0):
            line += f" Less for the {cost}."
        elif (v or 0) < 0:
            line += " More for everything else."
        return f"{COPY} {line}"
    if ty == "dispatch":
        tgt = f" toward {cmd['target'].replace('_', ' ')}" if cmd.get("target") else ""
        if cmd["task"] == "return":
            return f"{COPY} Calling the rover home."
        return f"{COPY} Rover rolling out{tgt} {TASK_SAY[cmd['task']]}."
    if ty == "shelter":
        if cmd["on"]:
            return f"{COPY} Everyone into the shelter."
        return f"{COPY} Crew leaving the shelter."
    if ty == "power_save":
        return f"{COPY} Night mode on. Lab and greenhouse sleep." if cmd.get("on") else f"{COPY} Night mode off."
    if ty == "end_shift":
        return COPY      # the shift report that follows says the rest ("Day 1, shift 4. …")
    if ty == "confirm":
        return "Confirmed. Doing it now."
    if ty == "cancel":
        return "Cancelled. Nothing changed."
    if ty == "rule":
        return f"Standing order set: {rule_text(cmd)}"
    if ty == "call_houston":
        return "Calling Houston…"
    return COPY


WHEN_SAY = {"storm": "if a solar storm comes", "low_power": "if power gets low", "dark": "when it gets dark",
            "comm_closed": "when we lose the radio", "dose_high": "if the dose gets high",
            "low_oxygen": "if the air gets low"}


def _strip_copy(line: str) -> str:
    """The readback without its opening "Copy." (older forms too)."""
    return re.sub(r"^(Copy, commander\.|Copy[.!]|Confirmed\.)\s*", "", line.strip())


def rule_text(rule: dict) -> str:
    then = _strip_copy(readback(rule["then"]))
    then = then.split(". ")[0].rstrip(".!")
    return f"{WHEN_SAY.get(rule['when'], 'when that happens')}, {then[0].lower() + then[1:]}."


def status(what: str, state: dict | None, mid: str | None = None) -> str:
    """One short line per system. `all` gives the numbers only, so the whole report stays a breath long."""
    if not state:
        return "No mission yet. Pick a landing site first."
    r, env = _r(state), state.get("env") or {}
    full = what != "all"
    parts = []
    if what in ("power", "all"):
        p = r.get("power_pct")
        if p is not None:
            line = f"Battery at {_pct(p)}."
            if full:
                line += " Sun's up, panels charging." if env.get("lit", env.get("in_sun")) else " It's dark. We're on battery."
            parts.append(line)
    if what in ("oxygen", "life_support", "all"):
        o = r.get("life_support_pct")
        if o is not None:
            line = f"Air and water at {_pct(o)}."
            if full:
                line += " Plenty to breathe." if o >= 60 else " Keep an eye on it." if o >= 30 else " That's low, Commander."
            parts.append(line)
    if what in ("dose", "all"):
        d, lim = r.get("dose_msv"), r.get("dose_limit_msv")
        if d is not None:
            explain = full and term(mid, "msv", "") != ""
            line = f"Crew dose: {d:g} of {lim:g} mSv." if lim else f"Crew dose: {d:g} mSv."
            if explain:
                line += " An mSv measures radiation dose."
            rate = r.get("dose_rate_msv_h")
            if rate and full:
                line += f" Rising {rate:g} an hour."
            parts.append(line)
    if what in ("storm", "all"):
        st = env.get("storm") or {}
        if st.get("active"):
            line = "Solar storm hitting now."
            if full:
                line += f" It's the {st['name']}." if st.get("name") else ""
                line += " Shelter or shields."
            parts.append(line)
        elif what == "storm":
            parts.append("No storm. The Sun is calm.")
    if what in ("comms", "all"):
        if env.get("earth_visible"):
            if full:
                parts.append("Earth is up. Houston can hear us.")
        else:
            nxt = env.get("next_comm_window_h")
            when = f"Next window in about {nxt:g} hours." if isinstance(nxt, (int, float)) else "Next window later."
            if full:
                parts.append(f"Earth has set. {when}")
    return " ".join(parts) or "All systems steady, Commander."


def houston(text: str, state: dict | None, mid: str | None = None) -> tuple[str, int]:
    """'Houston, how much oxygen do we have?' -> Houston's answer and the delay before it is spoken."""
    from .nlu import parse
    env = (state or {}).get("env") or {}
    if state and env.get("earth_visible") is False:
        return "No answer. Earth has set, so Houston can't hear us. Your call, Commander.", 0
    q = parse(text)["commands"] if text else []
    qq = next((c for c in q if c["type"] == "query"), None)
    if qq:
        return f"Houston here. {status(qq['what'], state, mid)}", MOON_ROUND_TRIP_MS
    alerts = (state or {}).get("alerts") or []
    if (env.get("storm") or {}).get("active") or "dose_rate_high" in alerts:
        tip = "We see the storm too. Shelter or shields, now."
    elif (_r(state).get("power_pct") or 100) < 30:
        tip = "Battery's low. Turn down science. Save power for life support."
    else:
        tip = "Loud and clear, Commander. Keep the crew safe."
    return f"Houston here. {tip}", MOON_ROUND_TRIP_MS


def short(line: str) -> str:
    """Confused / frustrated kid: the first sentence only, calm."""
    body = _strip_copy(line)
    first = re.split(r"(?<=[.!?])\s+", body)[0].replace("!", ".") if body else ""
    return f"Copy. {first}".strip() if body != line.strip() else first


def excited(line: str) -> str:
    if line.endswith("!"):
        return line
    return line + " Great call!" if line.startswith(("Copy", "Confirmed")) else line


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
