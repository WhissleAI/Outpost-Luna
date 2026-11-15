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
from .. import soundalike
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
                p = gaz().places.get(pid)   # a tap anywhere on a big place counts (a kid taps the patch, not its centre)
                if p and _ang((tap["lat"], tap["lon"]), (p.lat, p.lon)) <= max(r, (p.diameter_km or 0) / 2 / 30.3 * 0.9):
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
    """(passed, extra). extra may hold the matched `command` or the `choice`.

    A spoken / typed answer that fails on the heard words is graded once more on the words it SOUNDS like, against the
    step's own short vocabulary (round 7, app/soundalike.py: "rover go get eyes" -> ice, "four side" -> far side,
    "malapart" -> Malapert). extra["heard_as"] then says what it was read as."""
    ok, extra = _grade(step, inp, loads)
    if ok or not text_only(inp or {}):
        return ok, extra
    fixed, edits = soundalike.repair(inp["text"], step_vocab(step))
    if not edits:
        return ok, extra
    ok2, extra2 = _grade(step, {**inp, "text": fixed}, loads)
    return (True, {**extra2, "heard_as": fixed}) if ok2 else (ok, extra)


COMMAND_VOCAB = ["shields", "life support", "greenhouse", "science", "rover", "comms", "radio", "heaters", "ice",
                 "water", "shelter", "houston", "solar panels", "power"]


def step_vocab(step: dict | None, options: list[str] | None = None, aliases: bool = True) -> list[str]:
    """What this step expects to hear (the sound-alike targets): its options and their say words, its keywords, the
    places it names, the side / day-night words, the base parts of a command step, the space word."""
    if not step:
        return [o for o in options or [] if o]
    acc = step.get("accept") or {}
    kind = acc.get("type") or ""
    out: list[str] = []
    for _, say in step_options(acc):
        out += [w for w in say if w]
    for grp in [*acc.get("all", []), *acc.get("any", [])]:
        out += list(grp)
    for pid in [acc.get("place"), *acc.get("also", []), *acc.get("stops", []),
                *(o.get("id") for o in acc.get("options", []) or [])]:
        p = gaz().places.get(pid) if pid else None
        if p:
            out += [p.name, *(p.aliases if aliases else [])]   # aliases hold kid words and misspellings
    if kind == "terminator":
        out += ["terminator", "shadow line", "day", "night"]
    if kind == "command":
        out += COMMAND_VOCAB
    if kind.startswith("vocab_") and acc.get("term"):
        out.append(acc["term"])
    return [re.sub(r"\s*\(.*?\)", "", str(w)).strip() for w in out if w]


def _grade(step: dict, inp: dict, loads: dict | None = None) -> tuple[bool, dict]:
    acc, inp = step["accept"], inp or {}
    kind, text = acc["type"], inp.get("text") or ""
    if text and not inp.get("choice") and kind in INDEXED:   # "one", "the second one", "b": the option by its key
        ids = [i for i, _ in step_options(acc)]
        k = option_index(text, len(ids))
        if k is not None:
            inp = {**inp, "choice": ids[k]}
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
    if kind == "video":   # pass-through: watched or skipped (or offline), the lesson goes on and the reveal is said
        vid = inp.get("video") if isinstance(inp.get("video"), dict) else None
        if vid is None and not inp.get("choice"):     # words alone: only "watch" / "skip" (the client plays it)
            t = _norm(text)
            hit = next((k for k, ws in VIDEO_WORDS.items() if any(_has(t, w) for w in ws)), None)
            return hit is not None, {"watched": False, "seconds": 0.0, **({"choice": hit} if hit else {})}
        vid = vid or {}
        try:
            secs = max(0.0, float(vid.get("seconds") or 0))
        except (TypeError, ValueError):
            secs = 0.0
        return True, {"watched": bool(vid.get("watched")), "seconds": round(secs, 1)}
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
    if not hits:            # the ear's near-miss of a name ("malapart" for "malapert"): one option, clearly closest
        hits = [o["id"] for o in options if near_name(t, [o["label"], *o.get("say", [])])]
    return hits[0] if len(hits) == 1 else None


NEAR = 0.8          # difflib ratio for a heard word to count as a misheard option name (>= 5 letters)


def near_name(text: str, names: list[str]) -> bool:
    """A heard word is a near-miss of a long word of one of `names` (Arc hears "Malapart must be" for "Malapert
    Massif", "Shackle ton" for "Shackleton"). Only words of >= 5 letters, so "rock" never matches "rocks"."""
    from difflib import SequenceMatcher
    hw = [w for w in _gnorm(text).split() if len(w) >= 4]
    joined = "".join(_gnorm(text).split())
    for n in names:
        for w in _gnorm(n).split():
            if len(w) < 5:
                continue
            if any(SequenceMatcher(None, w, h).ratio() >= NEAR for h in hw) or w in joined:
                return True
    return False


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
    if text and len(got) < len(stops):   # the words name the rest, in order (after any stops already tapped)
        t = f" {gaz_norm(text)} "
        pos = 0
        for sid in stops[len(got):]:
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


# ---- what counts as a try (docs/HANDSFREE.md, "Only plausible answers count") ------------------------------------------
# The mic is always open: "Oh, it's", "okay", "alright", a hum or the app's own voice must never cost the kid a try, and
# CAPCOM must never show the answer before the kid had a real go. The router (turn_router.route) and the attempt API
# (routes.py) share these rules: a turn the router passes as an answer is graded, one the grader would not count as a
# try is never sent, and if one gets through anyway the grader answers "ignored" (no miss).
REVEAL_AFTER = 3        # real misses before CAPCOM shows the answer and moves on
REVEAL_MIN_S = 20.0     # ... and never in the first 20 s of a step
DD_MIN = 0.5            # the normal listening filter (turn_router.DD_MIN); the router passes the kid's own level


def reveal_due(misses: int, step_s: float | None = None) -> bool:
    """CAPCOM shows the answer: `misses` real misses (this one included) AND the step has been open >= REVEAL_MIN_S.
    `step_s` None: the caller doesn't track time (API tools); only the misses count. This is the one rule for the
    reveal; hint stages hang off the same miss counter."""
    return misses >= REVEAL_AFTER and (step_s is None or float(step_s) >= REVEAL_MIN_S)


# Words that carry no answer: function words, fillers, acknowledgements, question words.
NOT_CONTENT = frozenset("""
a an the of and or but nor so if then than to too for from by with without in on at into onto off out up down over
is are was were be been being am it its this that these those there here they them their we us our you your i me
my mine he she him her his hers do does did done doing don dont doesn isn wasn can could would should will shall
might must may have has had having not no yes yeah yep yup nope okay ok alright right well like just really very
oh ohh ooh ah ahh uh uhh um umm hmm mm mmm huh wow whoa hey hi hello sure thing things stuff gonna wanna got get
gets let lets what whats when where who whom why how which wait sorry please thanks thank maybe guess think mean know
""".split())
INDEXED = ("choice", "predict", "compare", "earth_view", "vocab_match", "vocab_fill", "vocab_listen")
_KEYS = {"one": 0, "1": 0, "first": 0, "a": 0, "two": 1, "2": 1, "second": 1, "b": 1, "bee": 1, "three": 2, "3": 2,
         "third": 2, "c": 2, "sea": 2, "see": 2, "four": 3, "4": 3, "fourth": 3, "d": 3}
_KEY_RE = re.compile(r"^(?:(?:it s|its|it is|i think|i pick|i choose|i say|my answer is|the|option|answer|number|"
                     r"choice|letter)\s+)*(\w+)(?:\s+one)?$")


def _gnorm(text: str) -> str:
    from ..gazetteer import norm as gnorm
    return gnorm(text or "")


def content_words(text: str) -> list[str]:
    return [w for w in _gnorm(text).split() if len(w) > 2 and w not in NOT_CONTENT]


def option_index(text: str, n: int) -> int | None:
    """The option a kid names by its number or letter ("one", "the second one", "option 3", "b"), 0-based; else None.
    The whole turn must be the key: "Oh, it's a" is not option A."""
    m = _KEY_RE.match(_gnorm(text))
    k = _KEYS.get(m.group(1)) if m else None
    return k if k is not None and k < n else None


VIDEO_WORDS = {"watch": ["Watch", "watch it", "play", "play it", "show me", "yes"],
               "skip": ["Skip", "skip it", "no thanks", "not now"]}


def step_options(acc: dict) -> list[tuple[str, list[str]]]:
    """[(option id, [label, *say words])] in the order the client shows them (its numbers / letters)."""
    kind = acc["type"]
    if kind in ("choice", "predict", "compare"):
        return [(o["id"], [o["label"], *o.get("say", [])]) for o in acc.get("options", [])]
    if kind == "earth_view":
        return [(k, [k.capitalize(), *EARTH_WORDS[k]]) for k in ("yes", "no", "sometimes")]
    if kind in ("vocab_match", "vocab_fill", "vocab_listen"):
        from . import vocab
        return [(o["id"], [o["label"]] + ([o["term"]] if kind != "vocab_match" else [])) for o in vocab.options(acc)]
    if kind == "globe_side":
        return [(k, ["", *SIDE_WORDS[k]]) for k in ("near", "far")]
    if kind == "video":
        return [(k, w) for k, w in VIDEO_WORDS.items()]
    return []


def _stem(ws) -> set[str]:
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in ws}


def plausible(step: dict | None, text: str, dd: float | None = None, dd_min: float = DD_MIN, *,
              step_type: str | None = None, options: list[str] | None = None, strict: bool = False) -> bool:
    """Is this turn a real try at the step (a miss when wrong), or room talk / filler (ignored, never a miss)?

    A try: it names an option (a word of it, or its number / letter); it overlaps what the step expects (the keywords,
    a place name, a mission order, the space word); or it has >= 3 content words and Arc says it was device-directed
    (>= the kid's filter; unknown counts). `step` is the course step; without it (an old client's screen frame) the
    option labels and the step type are all we know."""
    acc = (step or {}).get("accept") or {"type": step_type or ""}
    kind = acc.get("type") or ""
    t = _norm(text)
    if not t.strip():
        return False
    cw = content_words(text)
    opts = step_options(acc) if step else [(str(k), [o]) for k, o in enumerate(options or [])]
    if opts and kind != "globe_side" and option_index(text, len(opts)) is not None:
        return True
    mine = _stem(cw)
    for _, say in opts:
        if any(_has(t, w) for w in say if w) or mine & _stem(content_words(say[0])):   # the whole label, a say word
            return True
    if opts and kind != "globe_side" and any(near_name(text, [w for w in say if w]) for _, say in opts):
        return True       # a misheard option name is still a try (never an endless silent ignore)
    if kind == "keywords":
        if any(_has(t, w) for grp in [*acc.get("all", []), *acc.get("any", [])] for w in grp):
            return True
        if step and mine & _stem(content_words(" ".join(references(step)))):
            return True
    if kind == "command" and any(c.get("type") not in ("confirm", "cancel", "deny")
                                 for c in nlu.parse(text).get("commands", [])):
        return True
    if kind in ("tap", "intent", "route", "terminator", "compare") and gaz().match_text(text):
        return True
    if kind == "terminator" and re.search(r"\b(terminator|day|night|line|shadow)\b", t):
        return True
    if kind in ("vocab_say", "vocab_fill", "vocab_listen") and len(cw) == 1 and len(_gnorm(text).split()) <= 3:
        return True       # the answer is one word: one content word ("rocks" for the blank) is a real try
    if kind.startswith("vocab_") and acc.get("term"):
        from . import vocab
        if kind == "vocab_say" and vocab.said_score(text, acc["term"]) >= 0.5:
            return True
        if kind in ("vocab_fill", "vocab_listen") and \
                any(vocab.said_score(text, o["term"]) >= 0.6 for o in vocab.options(acc)):
            return True
    if sounds_like_answer(step, text, options):
        return True       # a mishear of what the step expects ("rover go get eyes", "four side"): a real try
    if strict:
        return False      # strict: the step's own words only (the router's fuzzy navigation check)
    return len(cw) >= 3 and (dd is None or float(dd) >= dd_min)


def sounds_like_answer(step: dict | None, text: str, options: list[str] | None = None) -> bool:
    """The turn is mostly a sound-alike of the step's vocabulary: after the repair, more than half of its content words
    are the step's own words. "rover go get eyes" yes (rover, ice); "my eyes hurt today" no (1 of 3)."""
    voc = step_vocab(step, options)
    fixed, edits = soundalike.repair(text, voc)
    if not edits:
        return False
    vw = {w for v in voc for w in _gnorm(v).split()}
    cw = content_words(fixed)
    return bool(cw) and 2 * sum(w in vw for w in cw) > len(cw)


def text_only(inp: dict) -> bool:
    """A spoken / typed attempt (no tap, choice, view or taps): the only kind that can be room talk."""
    inp = inp or {}
    return bool((inp.get("text") or "").strip()) and \
        not any(inp.get(k) is not None for k in ("tap", "choice", "view", "taps", "video"))
