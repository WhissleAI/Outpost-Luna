"""Grade one answer against a step's `accept` rule. Voice and taps both count.

accept types:
  intent    {place}                 the kid named the place ("show me the south pole"), or tapped it
  tap       {place, also?, radius_deg?}   a tap on that place (id from the globe, or lat/lon within radius_deg)
  command   {expect:{type, ...}}    the mission NLU turns the words into a Command that matches `expect`;
                                    `more: true` means an allocate that raises the load's share
  keywords  {all?:[[syn,...],...], any?:[[syn,...]]}   every `all` group has a word heard; at least one `any` group
  choice    {answer, options:[{id,label,say:[...]}]}   a tapped option id, or words that name exactly one option
  vocab_match / vocab_say / vocab_fill / vocab_listen   Space words (app/academy/vocab.py, docs/VOCABULARY.md)
Globe steps (docs/LEARNING_DESIGN.md §3, client contract in §9.2):
  predict     {answer, options:[{id,label,say}]}   a guess before the reveal: any named option passes;
                                                   extra {guess, correct}
  globe_side  {want: near|far}                      {choice}, {view:{lat,lon}} (the camera's centre) or words
  terminator  {sun_lon, tol_deg?}                   a tap within tol_deg of the day/night line, "terminator", or a
                                                    place on the line
  compare     {answer, options:[{id,label,say}], metric?}   one of two places/sites: {choice}, {tap} or its name;
                                                   extra {choice, data}
  route       {stops:[place ids], radius_deg?}      the stops in order: {taps:[...]} or the names in order in the
                                                    words; extra {got, next}
  earth_view  {place}                               yes / no / sometimes, computed from where the place is
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache

from ..gazetteer import Gazetteer
from ..mission import nlu, sim
from .content import DATA


@lru_cache(maxsize=1)
def gaz() -> Gazetteer:
    return Gazetteer(DATA / "places.json")


def _norm(text: str) -> str:
    return nlu._words_to_digits(nlu.norm(text or ""))


def _has(t: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(_norm(word))}(?![a-z0-9])", t) is not None


def _ang(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    c = math.sin(la1) * math.sin(la2) + math.cos(la1) * math.cos(la2) * math.cos(lo1 - lo2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _tap_ok(tap, acc: dict) -> bool:
    ids = {acc["place"], *acc.get("also", [])}
    if isinstance(tap, str):
        return tap in ids
    if isinstance(tap, dict):
        if tap.get("place") in ids:
            return True
        if tap.get("lat") is not None and tap.get("lon") is not None:
            r = acc.get("radius_deg", 6)
            for pid in ids:
                p = gaz().places.get(pid)
                if p and _ang((tap["lat"], tap["lon"]), (p.lat, p.lon)) <= r:
                    return True
    return False


def _more(cmd: dict, loads: dict) -> bool:
    a = cmd.get("amount") or {}
    kind, v = a.get("kind"), a.get("value")
    if kind in ("delta", "little"):
        return (v or 0) > 0
    if kind in ("all", "half"):
        return kind == "all" or loads.get(cmd.get("to"), 0) < 50
    if kind == "percent":
        return (v or 0) > loads.get(cmd.get("to"), 0)
    return False


def matching_command(text: str, expect: dict, loads: dict | None = None) -> dict | None:
    """The first Command the NLU reads from `text` that matches `expect`, else None."""
    loads = loads or dict(sim.DEFAULT_LOADS)
    for cmd in nlu.parse(text or "").get("commands", []):
        if any(k != "more" and cmd.get(k) != v for k, v in expect.items()):
            continue
        if expect.get("more") and not _more(cmd, loads):
            continue
        return cmd
    return None


def choice_of(inp: dict, acc: dict) -> str | None:
    if inp.get("choice"):
        return inp["choice"]
    t = _norm(inp.get("text", ""))
    if not t:
        return None
    hits = [o["id"] for o in acc["options"] if any(_has(t, w) for w in [o["label"], *o.get("say", [])])]
    return hits[0] if len(hits) == 1 else None


def grade(step: dict, inp: dict, loads: dict | None = None) -> tuple[bool, dict]:
    """(passed, extra). extra may hold the matched `command` or the `choice`."""
    acc, inp = step["accept"], inp or {}
    kind, text = acc["type"], inp.get("text") or ""
    if kind == "tap":
        if inp.get("tap") is None and text:   # hands-free (and for kids who can't tap): naming the place counts
            p = gaz().match_text(text)
            return bool(p and p.id in {acc["place"], *acc.get("also", [])}), {}
        return _tap_ok(inp.get("tap"), acc), {}
    if kind == "intent":
        if inp.get("tap") is not None and _tap_ok(inp["tap"], {**acc, "radius_deg": acc.get("radius_deg", 10)}):
            return True, {}
        p = gaz().match_text(text) if text else None
        return bool(p and p.id in {acc["place"], *acc.get("also", [])}), {}
    if kind == "command":
        cmd = matching_command(text, acc["expect"], loads)
        return cmd is not None, {"command": cmd} if cmd else {}
    if kind == "keywords":
        t = _norm(text)
        ok_all = all(any(_has(t, w) for w in grp) for grp in acc.get("all", []))
        ok_any = not acc.get("any") or any(any(_has(t, w) for w in grp) for grp in acc["any"])
        return bool(t) and ok_all and ok_any, {}
    if kind == "choice":
        c = choice_of(inp, acc)
        return c == acc["answer"], {"choice": c}
    if kind in GLOBE_TYPES:
        return GLOBE_TYPES[kind](acc, inp, text)
    # ---- vocab steps (a11y / learning design) ----
    if kind.startswith("vocab_"):
        from . import vocab
        return vocab.grade(acc, inp)
    return False, {}


# ---- globe steps (docs/LEARNING_DESIGN.md §3) -------------------------------------------------------------------------
def _option_of(inp: dict, options: list[dict]) -> str | None:
    if inp.get("choice"):
        return inp["choice"] if any(o["id"] == inp["choice"] for o in options) else None
    t = _norm(inp.get("text", ""))
    if not t:
        return None
    m = re.match(r"(?:option|number|answer)\s+(\d)\b", t)
    if m and 1 <= int(m.group(1)) <= len(options):
        return options[int(m.group(1)) - 1]["id"]
    hits = [o["id"] for o in options if any(_has(t, w) for w in [o["label"], *o.get("say", [])])]
    return hits[0] if len(hits) == 1 else None


def _predict(acc, inp, text):
    g = _option_of(inp, acc["options"])
    return g is not None, ({"guess": g, "correct": g == acc["answer"]} if g else {})


SIDE_WORDS = {"far": ["far side", "far", "back", "other side", "back side", "turn it around", "turn around", "spin it",
                      "hidden side", "dark side"],
              "near": ["near side", "near", "front", "side we see", "earth side", "facing earth", "front side"]}


def _side(acc, inp, text):
    want = acc["want"]
    if inp.get("choice"):
        return inp["choice"] == want, {"side": inp["choice"]}
    v = inp.get("view") or {}
    if v.get("lon") is not None:
        lon = abs(((float(v["lon"]) + 180) % 360) - 180)
        side = "far" if lon > 110 else "near" if lon < 70 else "limb"
        return side == want, {"side": side}
    t = _norm(text)
    other = "near" if want == "far" else "far"
    if any(_has(t, w) for w in SIDE_WORDS[want]) and not any(_has(t, w) for w in SIDE_WORDS[other][:2]):
        return True, {"side": want}
    return False, {}


def _terminator(acc, inp, text):
    sub = (0.0, float(acc["sun_lon"]))
    tol = acc.get("tol_deg", 10)
    tap = inp.get("tap")
    if isinstance(tap, dict) and tap.get("lat") is not None:
        off = abs(_ang((tap["lat"], tap["lon"]), sub) - 90)
        return off <= tol, {"off_deg": round(off, 1)}
    t = _norm(text)
    if _has(t, "terminator") or (re.search(r"\bday\b", t) and re.search(r"\bnight\b", t)) or _has(t, "shadow line"):
        return True, {}
    p = gaz().match_text(text) if t else None
    if p:
        off = abs(_ang((p.lat, p.lon), sub) - 90)
        return off <= tol + (p.diameter_km or 0) / 2 / 30.3, {"off_deg": round(off, 1)}   # 30.3 km per degree
    return False, {}


@lru_cache(maxsize=1)
def _sites() -> dict:
    return {s["id"]: s for s in sim.sites()}


def where(pid: str) -> tuple[float, float] | None:
    """lat/lon of a gazetteer place or a mission site."""
    p = gaz().places.get(pid)
    if p:
        return p.lat, p.lon
    s = _sites().get(pid)
    return (s["lat"], s["lon"]) if s else None


def compare_data(acc: dict) -> dict:
    """The numbers the globe shows on each card after the answer (mission sites: days of the April 2026 window)."""
    out = {}
    for o in acc["options"]:
        s = _sites().get(o["id"])
        if s:
            ps = sim.public_site(s)
            ll = where("shackleton")
            out[o["id"]] = {"sun_days": ps["window_sun_days"], "earth_days": ps["window_earth_days"],
                            "sun_year_pct": s.get("sunlight_pct"),
                            "ice_km": round(_ang((s["lat"], s["lon"]), ll) * 30.32) if ll else None}
    return out


def _compare(acc, inp, text):
    c = _option_of(inp, acc["options"])
    tap = inp.get("tap")
    if c is None and tap is not None:
        if isinstance(tap, str):
            c = tap if any(o["id"] == tap for o in acc["options"]) else None
        elif isinstance(tap, dict):
            if any(o["id"] == tap.get("place") for o in acc["options"]):
                c = tap["place"]
            elif tap.get("lat") is not None:
                d = {o["id"]: _ang((tap["lat"], tap["lon"]), where(o["id"])) for o in acc["options"] if where(o["id"])}
                c = min(d, key=d.get) if d and min(d.values()) <= acc.get("radius_deg", 6) else None
    return c == acc["answer"], {"choice": c, "data": compare_data(acc)} if c else {}


def _route(acc, inp, text):
    stops, r = acc["stops"], acc.get("radius_deg", 8)
    got: list[str] = []
    taps = inp.get("taps") or ([inp["tap"]] if inp.get("tap") is not None else [])
    if taps:
        for tp in taps:
            if len(got) == len(stops):
                break
            want = stops[len(got)]
            if _tap_ok(tp, {"place": want, "radius_deg": r}):
                got.append(want)
    elif text:
        t = f" {gaz_norm(text)} "
        pos = 0
        for sid in stops:
            p = gaz().places[sid]
            hits = [m.start() for a in {p.name, *p.aliases} if len(gaz_norm(a)) > 2
                    for m in re.finditer(rf"(?<![a-z0-9]){re.escape(gaz_norm(a))}(?![a-z0-9])", t) if m.start() >= pos]
            if not hits:
                break
            pos = min(hits) + 1
            got.append(sid)
    done = got == stops
    return done, {"got": got, "next": None if done else stops[len(got)]}


def gaz_norm(s: str) -> str:
    from ..gazetteer import norm as gnorm
    return gnorm(s)


EARTH_WORDS = {"yes": ["yes", "yeah", "yep", "always", "sure", "it does", "you can", "i can"],
               "no": ["no", "nope", "never", "can t", "cannot", "not"],
               "sometimes": ["sometimes", "some of the time", "now and then", "half", "on and off"]}


def earth_answer(pid: str) -> str:
    """Can you see Earth from here? Near side yes, far side no, the edges and poles sometimes (libration)."""
    lat, lon = where(pid)
    lon = abs(((lon + 180) % 360) - 180)
    if abs(lat) >= 80 or 80 < lon < 100:
        return "sometimes"
    return "yes" if lon <= 80 else "no"


def _earth(acc, inp, text):
    ans = earth_answer(acc["place"])
    g = inp.get("choice")
    if not g:
        t = _norm(text)
        found = [k for k in ("sometimes", "no", "yes") if any(_has(t, w) for w in EARTH_WORDS[k])]
        g = found[0] if found else None   # "sometimes" wins over the yes/no words inside it
    return g == ans, ({"answer": ans, "guess": g} if g else {})


GLOBE_TYPES = {"predict": _predict, "globe_side": _side, "terminator": _terminator, "compare": _compare,
               "route": _route, "earth_view": _earth}


# ---- paraphrase fallback (local embedder) ------------------------------------------------------------------------------
SIMILAR = 0.72   # cosine (all-MiniLM-L6-v2) between the answer and the step's reference line


def references(step: dict) -> list[str]:
    """What a right answer sounds like: the quoted order in the prompt (a readback), else the `any` synonyms."""
    q = re.findall(r'"([^"]+)"', step.get("prompt", ""))
    return q or [w for grp in step["accept"].get("any", []) for w in grp]


PROTOCOL = {"roger", "copy", "wilco", "say again", "repeat"}   # radio words the lesson is teaching: never paraphrased away


async def similar(step: dict, text: str) -> bool:
    """Keyword steps only, after the keyword rules failed. A readback passes when the mission NLU (rules + the local
    command bank) reads the same Command from it as from the quoted order; other steps pass on embedder similarity to
    the reference. Groups holding a number or a radio protocol word must still be heard exactly."""
    acc = step["accept"]
    if acc["type"] != "keywords" or not (text or "").strip():
        return False
    t = _norm(text)
    for grp in acc.get("all", []):
        strict = any(re.search(r"\d", w) for w in grp) or any(w in PROTOCOL for w in grp)
        if strict and not any(_has(t, w) for w in grp):
            return False
    refs = references(step)
    if re.findall(r'"([^"]+)"', step.get("prompt", "")):
        want = [nlu._shape(c) + (json.dumps(c.get("amount")),) for r in refs for c in nlu.parse(r)["commands"]]
        if want:
            got = (await nlu.understand(text))["commands"]
            return any(nlu._shape(c) + (json.dumps(c.get("amount")),) in want for c in got)
    from .. import models_client
    v = await models_client.embed([text, *refs], "query")
    if not v or len(v) < 2:
        return False
    return max(sum(a * b for a, b in zip(v[0], r)) for r in v[1:]) >= SIMILAR
