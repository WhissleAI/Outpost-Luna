"""The hint ladder (docs/PLAYTEST.md §Guidance). Every miss says what to do next, never just "Not that one".

  rung 0  the step opens: the prompt and one "do this" line (client)
  rung 1  first real miss: the hint, plus a visual one on the client (the place glows, the globe turns to it). A tap
          on a named place starts with what it was: "That's Copernicus. Orientale is the big bullseye, on the left."
  rung 2  second miss: the answer gets a label (a place's name on the Moon), one wrong card is crossed out, the order
          button glows, or the words to say appear on the card
  rung 3  third miss: CAPCOM shows it and moves on (academy/routes.py SHOW_AFTER)

`ladder()` returns the reply fields for a miss: say (spoken and shown), hint, rung, and what the client draws:
focus (place ids to glow), label (place ids to name), eliminate (an option id), cue (an order), phrase (words to show).
Spoken lines never carry an example command (the open mic would hear it back, docs/HANDSFREE.md); phrases are on
screen only.
"""
from __future__ import annotations

import re

from .grade import _ang, gaz

PLACE_TYPES = ("tap", "intent")
OPTION_TYPES = ("choice", "compare", "earth_view", "vocab_match", "vocab_fill", "vocab_listen")


def _plain(name: str) -> str:
    """"Mare Orientale" -> "Orientale", "Shackleton (south pole)" -> "Shackleton": the name the prompts use."""
    return re.sub(r"^Mare | Basin$", "", re.sub(r"\s*\(.*?\)", "", name))


def short(pid: str) -> str:
    p = gaz().places.get(pid)
    return _plain(p.name) if p else pid.replace("_", " ").title()


REACH_DEG = 5.0   # a named place within this many degrees of its rim counts as what the tap hit


def tapped_name(tap) -> str | None:
    """The named place a tap landed on, else None: inside its rim (or within 3 degrees of a small one), or within
    REACH_DEG of the rim (a mare's edge is ragged; "That's Mare Imbrium" beats "Not there")."""
    if not isinstance(tap, dict) or tap.get("lat") is None or tap.get("lon") is None:
        return None
    best, bd = None, 1e9
    for p in gaz().places.values():
        if getattr(p, "kind", "feature") == "artifact" or getattr(p, "estimated", False):
            continue
        r = max((p.diameter_km or 0) / 2 / 30.3, 3.0)
        d = _ang((tap["lat"], tap["lon"]), (p.lat, p.lon)) - r
        if d <= REACH_DEG and d < bd:
            best, bd = p, d
    if best is None and tap.get("place"):   # the client's nearest named place (globe.nearest, within ~12 degrees)
        p = gaz().places.get(tap["place"])
        if p is not None and getattr(p, "kind", "feature") != "artifact" and not getattr(p, "estimated", False):
            best = p
    return _plain(best.name) if best else None


def wrong_option(acc: dict) -> str | None:
    """One wrong option to cross out at rung 2 (the last wrong one, so the right one is never hinted by position)."""
    if acc["type"].startswith("vocab_"):
        from .vocab import options
        opts = options(acc)
        right = next((o["id"] for o in opts if o["term"] == acc["term"]), None)
    elif acc["type"] == "earth_view":
        from .grade import earth_answer
        opts, right = [{"id": k} for k in ("yes", "no", "sometimes")], earth_answer(acc["place"])
    else:
        opts, right = acc.get("options", []), acc.get("answer")
    wrong = [o["id"] for o in opts if o["id"] != right]
    return wrong[-1] if wrong else None


def phrase_of(st: dict) -> str:
    """The words a readback or radio step wants, for the card (rung 2)."""
    acc = st["accept"]
    q = re.findall(r'"([^"]+)"', st.get("prompt", ""))
    if q and acc.get("all"):
        return q[0].replace("Commander, ", "")
    if acc.get("any"):
        return acc["any"][0][0]
    return ""


def terminator_lon(acc: dict) -> float:
    return float(acc["sun_lon"]) - 90.0


def ladder(st: dict, misses: int, inp: dict, extra: dict) -> dict:
    """Reply fields for miss number misses+1 (rung 1 or 2)."""
    acc, kind = st["accept"], st["accept"]["type"]
    rung = 1 if misses <= 0 else 2
    hint, fail = st["hint"], st["fail"]
    out: dict = {"rung": rung, "hint": hint}
    tap = inp.get("tap") or ((inp.get("taps") or [None])[-1] if inp.get("taps") else None)
    name = tapped_name(tap) if kind in (*PLACE_TYPES, "route", "terminator") else None
    target = None
    if kind in PLACE_TYPES:
        target = acc["place"]
    elif kind == "route":
        got = extra.get("got") or []
        target = acc["stops"][min(len(got), len(acc["stops"]) - 1)]
    if name and target and name == short(target):
        name = None
    lead = f"That's {name}. " if name else fail + " "
    if rung == 1:
        out["say"] = lead + hint
        if target:
            out["focus"] = [target]
        if kind == "terminator":
            out["line_lon"] = terminator_lon(acc)
        return out
    # rung 2: the answer gets a label / one card goes / the order lights / the words appear
    if target:
        out |= {"focus": [target], "label": [target]}
        k = acc["stops"].index(target) + 1 if kind == "route" else 0
        out["say"] = lead + (f"Tap {k}: {short(target)}. It has a label now." if k else
                             f"Look for the label: {short(target)}.")
    elif kind == "terminator":
        out |= {"line_lon": terminator_lon(acc), "label_line": True}
        out["say"] = lead + "Tap the glowing line."
    elif kind in OPTION_TYPES:
        w = wrong_option(acc)
        if w:
            out["eliminate"] = w
        out["say"] = lead + hint + (" I crossed one out." if w else "")
    elif kind == "globe_side":
        out["cue"] = {"side": acc["want"]}
        out["say"] = lead + f"Tap the {acc['want'].title()} side button."
    elif kind == "command":
        out["cue"] = acc["expect"]
        out["say"] = lead + "Tap the glowing order."
    elif kind in ("keywords", "vocab_say"):
        ph = phrase_of(st) if kind == "keywords" else acc.get("term", "")
        if ph:
            out["phrase"] = ph
        out["say"] = lead + "The words are on the card now."
    else:
        out["say"] = lead + hint
    return out
