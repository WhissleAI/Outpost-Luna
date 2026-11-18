"""Radio readback: the cadet repeats Houston's order back, the real CAPCOM protocol (docs/GAMEPLAY.md §14.1).

A task's order step on the Now card is Houston's order ("Shields up to 30"). On the radio a crew answers an order by
reading it back: "Copy, shields to thirty." This module grades such a turn against `sim.readback(cmd)`, the order in
plain words, by keyword overlap:

  keys(cmd)          the groups a readback must name: the load / vehicle / place and the number ("shields", "30")
  grade(text, cmd)   {radio, bare, hit, of, good}: radio = the turn opens like a radio call ("copy", "roger", "wilco");
                     good = radio and every group heard (numbers either way: "forty" or "40")
  phrase(cmd)        the words to read back when the card's label isn't known ("shields 30")
  line(level, g, cmd, label)  what CAPCOM adds: "Good readback." on a good one (both levels); on Commander only, a
                     short "Read back: Shields to 40." (the card's own words) for a radio turn that missed a part;
                     nothing on Cadet otherwise

A readback never blocks, never costs and never scores: the order still runs from the panel, a tap or a plain "shields
to thirty", and the sim never hears about readbacks (tests/test_strategy.py: no new rewards).
"""
from __future__ import annotations

import re

from . import nlu, sim

# The turn reads like a radio answer. "read back" covers "reading back", "readback".
RADIO = re.compile(r"\b(?:copy|copied|copy that|roger|wilco|affirmative|read ?back|reading back)\b")
# Only the acknowledgement, nothing read back ("copy", "roger that", "copy, over").
BARE = re.compile(r"^(?:(?:copy|copied|roger|wilco|affirmative)(?: (?:that|houston|capcom|commander|over|sir))*"
                  r"(?: (?:copy|roger|wilco|over))*)$")

# Readback words that carry no part of the order (sim.readback's frame: "Set ... power: percent 40").
STOP = {"set", "power", "percent", "delta", "half", "little", "all", "none", "send", "the", "a", "to", "of", "crew",
        "into", "in", "storm", "mode", "on", "calling", "collect", "for", "at", "up", "down", "s"}
# key -> (shown word, words that count for it). A key not listed counts only as itself (singular or plural).
ALIASES: dict[str, tuple[str, set[str]]] = {
    "shields": ("shields", {"shield", "shields"}),
    "life": ("life support", {"life", "air", "oxygen"}),
    "support": ("", set()),                       # folded into "life"
    "comms": ("radio", {"comms", "comm", "radio", "radios"}),
    "science": ("science", {"science", "lab"}),
    "heaters": ("heaters", {"heater", "heaters", "heat", "heating"}),
    "rover": ("rover", {"rover", "buggy"}),
    "return": ("home", {"return", "home", "back", "returning"}),
    "explore": ("explore", {"explore", "exploring", "exploration"}),
    "repair": ("repair", {"repair", "fix", "fixing", "repairing"}),
    "array": ("array", {"array", "panel", "panels", "solar"}),
    "out": ("out", {"out", "leave", "leaving", "exit"}),
    "night": ("night", {"night"}),
    "off": ("off", {"off"}),
    "houston": ("Houston", {"houston"}),
}


def _toks(text: str) -> list[str]:
    return nlu._words_to_digits(nlu.norm(text or "")).replace("-", " ").split()


def keys(cmd: dict | None) -> list[tuple[str, set[str]]]:
    """The groups a readback of `cmd` must name, in order: [(shown word, accepted words)]."""
    if not cmd:
        return []
    out: list[tuple[str, set[str]]] = []
    for w in _toks(sim.readback(cmd)):
        if w in STOP:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", w):
            n = w.rstrip("0").rstrip(".") if "." in w else w
            out.append((n, {n}))
            continue
        shown, ok = ALIASES.get(w, (w, {w, w + "s", w.rstrip("s")}))
        if shown:
            out.append((shown, ok))
    return out


def phrase(cmd: dict | None) -> str:
    """The words to read back when the card's label isn't at hand: "shields 30", "rover home", "life support 45"."""
    if (cmd or {}).get("type") == "shelter" and not cmd.get("on"):
        return "crew out"
    return " ".join(s for s, _ in keys(cmd))


def grade(text: str, cmd: dict | None) -> dict:
    t = " ".join(_toks(text))
    words = set(t.split())
    groups = keys(cmd)
    hit = sum(1 for _, ok in groups if ok & words)
    radio = bool(RADIO.search(t))
    return {"radio": radio, "bare": bool(BARE.fullmatch(t)), "hit": hit, "of": len(groups),
            "good": radio and bool(groups) and hit == len(groups)}


GOOD = "Good readback."


def line(level: str, g: dict, cmd: dict | None, label: str | None = None) -> str | None:
    """CAPCOM's word on a readback: praise on a good one; on Commander a short nudge for a radio turn that missed a
    part, in the card's own words. Cadet hears praise only. Never "wrong", never a cost."""
    if g.get("good"):
        return GOOD
    words = (label or "").strip().rstrip(".") or phrase(cmd)
    if level != "cadet" and g.get("radio") and words:
        return f"Read back: {words}."
    return None


def open_order(state: dict | None) -> dict | None:
    """Houston's order waiting on the Now card: the current task's step when it is an order the kid can do now, else
    None. -> {"key": "<task>:<step>", "cmd", "label"}."""
    t = (state or {}).get("task") or {}
    s = t.get("step") or {}
    if s.get("kind") != "order" or not s.get("ready") or not s.get("cmd") or (state or {}).get("over"):
        return None
    return {"key": f"{t.get('id')}:{s.get('id')}", "cmd": s["cmd"], "label": s.get("label")}
