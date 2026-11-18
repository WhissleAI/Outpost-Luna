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


def label_of(st: dict, pid: str) -> str:
    """The name a step's mark carries: the step's own `label` for its target (the word the prompt uses: "Cabeus
    crater", not the hardware's "LCROSS Centaur rocket impact site"), else the place's short name."""
    acc = st.get("accept") or {}
    if acc.get("label") and pid in {acc.get("place"), *acc.get("also", [])}:
        return acc["label"]
    return short(pid)


# The order buttons a command step shows (frontend/src/academy/ui.js ORDERS), by what the order does.
ORDER_LABEL = {"heaters": "Heaters up", "shields": "Shields up", "shelter_in": "Into the shelter",
               "shelter_out": "Leave the shelter", "rover_ice": "Rover: get ice", "houston": "Call Houston"}


def order_key(cmd: dict | None) -> str | None:
    """A parsed mission order (or a step's `expect`) as one of ORDER_LABEL's keys, else None."""
    if not cmd:
        return None
    t = cmd.get("type")
    if t == "allocate" and cmd.get("to") in ("heaters", "shields"):
        return cmd["to"]
    if t == "shelter":
        return "shelter_in" if cmd.get("on") else "shelter_out"
    if t == "dispatch" and cmd.get("task") == "collect_ice":
        return "rover_ice"
    if t == "call_houston":
        return "houston"
    return None


def order_label(expect: dict) -> str:
    return ORDER_LABEL.get(order_key(expect) or "", "the glowing order")


def option_label(acc: dict, oid: str) -> str:
    """The label on an option's button (what "Here's the answer" names)."""
    if acc["type"].startswith("vocab_"):
        from .vocab import options
        o = next((o for o in options(acc) if o["id"] == oid), None)
        return (o or {}).get("label", oid)
    if acc["type"] == "earth_view":
        return oid.capitalize()
    o = next((o for o in acc.get("options", []) if o["id"] == oid), None)
    return (o or {}).get("label", oid)


def right_option(acc: dict) -> str | None:
    if acc["type"].startswith("vocab_"):
        from .vocab import options
        return next((o["id"] for o in options(acc) if o["term"] == acc["term"]), None)
    if acc["type"] == "earth_view":
        from .grade import earth_answer
        return earth_answer(acc["place"])
    return acc.get("answer")


# Field School (grade.FIELD_TYPES). A describe step asks for the first kind still missing, as a question.
DESCRIBE_ASK = {"size": "how big is it?", "shape": "what shape is it?", "tone": "is it bright or dark?",
                "texture": "is it smooth or bumpy?", "shadow": "where are the shadows?"}


def describe_ask(missing: list[str]) -> str:
    return DESCRIBE_ASK.get((missing or ["tone"])[0], "what else do you see?")


def field_now(acc: dict, got: list | None) -> dict | None:
    """The part of a Field step the kid is on: the round (rounds) or the next item (sequence)."""
    got = got or []
    if acc["type"] == "rounds":
        rs = acc["rounds"]
        return rs[min(len(got), len(rs) - 1)]
    if acc["type"] == "sequence":
        its = acc["items"]
        return its[min(len(got), len(its) - 1)]
    return None


def field_help(st: dict, rung: int, got: list | None, lead: str = "") -> dict:
    """Hint ladder for the Field steps. Rung 1: the hint (this round's own, or the missing descriptor as a question);
    rung 2: a wrong tool crossed out / the next item named on the card / an example on the card; rung 3 (help only):
    the answer lights up for the kid to tap."""
    acc, kind = st["accept"], st["accept"]["type"]
    out: dict = {"rung": rung, "hint": st.get("hint", "")}
    if kind == "describe":
        from .grade import describe_cats, describe_label
        missing = [c for c in describe_cats(acc) if c not in (got or [])]
        have = [c for c in describe_cats(acc) if c in (got or [])]
        praise = f"You have {describe_label(have)}. " if have else ""
        ask = describe_ask(missing)
        out["say"] = lead + praise + ask[:1].upper() + ask[1:]
        out["ask"] = missing[:1]
        if rung >= 2:
            out["phrase"] = st.get("example", "")
            out["say"] = lead + praise + "Try the words on the card."
        return out
    now = field_now(acc, got) or {}
    if kind == "rounds":
        out["hint"] = now.get("hint", "")
        out["say"] = lead + _end(now.get("hint", ""))
        if rung >= 2:
            wrong = [o["id"] for o in acc["options"] if o["id"] != now.get("answer")]
            if wrong:
                out["eliminate"] = wrong[-1]
            out["say"] += " I crossed one out." if wrong else ""
        if rung >= 3:
            out["answer"] = now.get("answer")
            out["say"] = f"Here's the answer: {option_label(acc, now.get('answer')).split(':')[0]}. Tap it."
        return out
    if kind == "sequence":
        out["say"] = lead + _end(st.get("hint", ""))
        if rung >= 2:
            out["phrase"] = now.get("label", "")
            out["answer"] = now.get("id")
            out["say"] = lead + "The next one glows on the card."
        return out
    out["say"] = lead + _end(st.get("hint", ""))
    return out


def _end(t: str) -> str:
    t = str(t or "").strip()
    return t if not t or t[-1] in ".!?" else t + "."


def help_rung(st: dict, rung: int, got: list | None = None) -> dict:
    """The kid ASKED for help ("help", "I don't know", "where is it?"): the next rung of the same ladder, with no miss
    counted. Rung 1 = highlight (the place glows, the camera turns), 2 = label (its name on the Moon, a wrong card
    crossed out, the order glows, the words on the card), 3 = show (CAPCOM points at the answer; the kid still taps
    it, so the step is theirs). Every line says what to do next (docs/PLAYTEST.md)."""
    acc, kind = st["accept"], st["accept"]["type"]
    rung = max(1, min(3, int(rung or 1)))
    hint = _end(st.get("hint", ""))
    out: dict = {"rung": rung, "hint": st.get("hint", "")}
    if kind == "predict":
        return {**out, "rung": 1, "say": "Any guess is fine. Tap one."}
    if kind == "video":
        return {**out, "rung": 1, "say": "Tap Watch to see it, or Skip."}
    if kind in ("describe", "sequence", "rounds"):
        return field_help(st, rung, got)
    target = None
    if kind in PLACE_TYPES:
        target = acc["place"]
    elif kind == "route":
        got = got or []
        target = acc["stops"][min(len(got), len(acc["stops"]) - 1)]
    if target:
        name = label_of(st, target)
        out["focus"] = [target]
        if rung >= 2:
            out["label"] = [target]
        if kind == "route":
            k = acc["stops"].index(target) + 1
            out["say"] = (f"Tap {k}: {name}. It's glowing." if rung == 1 else
                          f"Tap {k}: {name}. It has a label now." if rung == 2 else f"Here it is. Tap {k}: {name}.")
        else:
            out["say"] = (f"Look for the glowing ring. {hint}" if rung == 1 else
                          f"Look for the label: {name}. Tap it." if rung == 2 else f"Here it is: {name}. Tap it.")
        if rung == 3:
            out["show"] = True
        return out
    if kind == "terminator":
        out["line_lon"] = terminator_lon(acc)
        out["label_line"] = rung >= 2
        out["say"] = ("Look for the glowing line. Tap on it." if rung == 1 else
                      "Tap the line marked Day meets night." if rung == 2 else
                      "Here it is: where day meets night. Tap the line.")
        if rung == 3:
            out["show"] = True
        return out
    if kind == "globe_side":
        w = acc["want"]
        if rung >= 2:
            out["cue"] = {"side": w}
        out["say"] = (f"Drag the Moon to turn it. Or tap {w.title()} side." if rung == 1 else
                      f"Tap the glowing {w.title()} side button.")
        return out
    if kind == "command":
        if rung >= 2:
            out["cue"] = acc["expect"]
        out["say"] = hint if rung == 1 else "Tap the glowing order." if rung == 2 else \
            f"Here it is: tap {order_label(acc['expect'])}."
        return out
    if kind in ("keywords", "vocab_say"):
        ph = phrase_of(st) if kind == "keywords" else acc.get("term", "")
        if rung >= 2 and ph:
            out["phrase"] = ph
        out["say"] = hint if rung == 1 or not ph else "The words are on the card now. Say them."
        return out
    if kind in OPTION_TYPES:
        if rung == 2:
            w = wrong_option(acc)
            if w:
                out["eliminate"] = w
            out["say"] = hint + (" I crossed one out." if w else "")
        elif rung == 3:
            r = right_option(acc)
            if r:
                out["answer"] = r
                out["eliminate"] = wrong_option(acc)
                out["say"] = f"Here's the answer: {option_label(acc, r)}. Tap it."
            else:
                out["say"] = hint
        else:
            out["say"] = hint
        return out
    out["say"] = hint
    return out


def ladder(st: dict, misses: int, inp: dict, extra: dict, seen: int = 0) -> dict:
    """Reply fields for miss number misses+1 (rung 1 or 2). `seen`: the rung the card already shows (a find step opens
    at rung 1, and help climbs without a miss), so a miss always adds something new."""
    acc, kind = st["accept"], st["accept"]["type"]
    rung = 1 if misses <= 0 else 2
    if seen >= 1:
        rung = 2
    hint, fail = st["hint"], st["fail"]
    if kind in ("describe", "sequence", "rounds"):
        return field_help(st, rung, extra.get("got"), lead=fail + " ")
    out: dict = {"rung": rung, "hint": hint}
    tap = inp.get("tap") or ((inp.get("taps") or [None])[-1] if inp.get("taps") else None)
    name = tapped_name(tap) if kind in (*PLACE_TYPES, "route", "terminator") else None
    target = None
    if kind in PLACE_TYPES:
        target = acc["place"]
    elif kind == "route":
        got = extra.get("got") or []
        target = acc["stops"][min(len(got), len(acc["stops"]) - 1)]
    if name and target and name in (short(target), label_of(st, target)):
        name = None
    lead = f"That's {name}. " if name else fail + " "
    if kind == "command":   # a real order, the wrong one: say why it's not the one, never "Say again?" (docs/PLAYTEST.md)
        lead = (st.get("wrong") or {}).get(extra.get("heard_order") or "", fail) + " "
    if kind == "globe_side":
        # [owner bug] "Tap the Far side button" right after they pressed it. State-aware and the same on both rungs:
        # what to do with the Moon first, the button second (≤ 20 spoken words, docs/COPY.md)
        w = acc["want"]
        out["say"] = f"Not yet. Turn the Moon until the {w} side faces you. Or press {w.title()} side."
        if rung == 2:
            out["cue"] = {"side": w}
        return out
    if kind == "route" and name and target and name in [short(x) for x in acc["stops"][acc["stops"].index(target) + 1:]]:
        k = acc["stops"].index(target) + 1   # a later stop first: say which comes first (novice playtest #22)
        out |= {"focus": [target], **({"label": [target]} if rung == 2 else {})}
        out["say"] = f"That's {name}. Start with {k}: {short(target)}."
        return out
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
                             f"Look for the label: {label_of(st, target)}.")
    elif kind == "terminator":
        out |= {"line_lon": terminator_lon(acc), "label_line": True}
        out["say"] = lead + "Tap the glowing line."
    elif kind in OPTION_TYPES:
        w = wrong_option(acc)
        if w:
            out["eliminate"] = w
        out["say"] = lead + hint + (" I crossed one out." if w else "")
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
