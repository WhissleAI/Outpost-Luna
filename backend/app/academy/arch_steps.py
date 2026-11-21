"""Archaeology step types (docs/COURSES.md §3.2): `layers`, `rings`, `hillshade` and `decide`.

Course-agnostic graders, written for the Archaeology course first. Every step works by voice alone, by keys alone and
by taps alone; the frontend draws them (frontend/src/academy/arch_steps.js) and the hands-free script answers them
(backend/tools/handsfree_run.answer_for).

  layers     {layers:[{id,label,say,h,finds?}] (drawn top to bottom), pit?:{id,label,say,from,to},
              order:[ids oldest -> youngest]}
             Order a trench's layers oldest to youngest. Builds up over turns like `sequence` (extra {got, next}).
             The trap: an intrusive pit (dug later, cut down through older layers) named before every layer it cuts is
             in the order; extra {trap: "pit", cuts: [...]} and the reply says why (whatever cuts a layer came after it).
  rings      {series, master:[y0, y1], beam:[b0, b1], tol?, start?}
             Slide an undated beam's ring pattern along the master chronology, then say the outer (cutting) year.
             `series` names a tree-ring file in the course (rings/<series>.json, years + index); the beam's widths are
             that series' own values for its years, so the match is real data. Input: the year as words or digits, or
             {choice: "1275"} from the slider's Lock in. Pass within `tol` years (default 1); extra {year, off}.
  hillshade  {image:{low, high, w, h, alt, credit, source}, targets:[{id,label,say,x,y,r}], need?}
             Find features on a pre-rendered lidar hillshade. A tap {tap:{x, y}} (0..1 image coordinates) inside a
             target's radius finds it; naming it by voice finds it too (hands-free, like `tap`). Builds up: extra {got,
             next}. Coordinates are image fractions only: no lat/lon is ever stored (docs/COURSES.md §1.5 rule 1).
  decide     {options:[{id,label,say,reply,best?}], law:{title,text,source}}
             An ethics call. Every option is a real decision: it passes with its own reply (never "wrong!"), the best
             call is marked `best`, and the law card goes on screen. Words that name no option are not a try.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

LAYER_TYPES = ("layers", "hillshade")       # build up over turns (the reply's `got` comes back), like grade.FIELD_TYPES
ONE_SHOT_TYPES = ("rings", "decide")
ARCH_TYPES = LAYER_TYPES + ONE_SHOT_TYPES
RINGS_TOL = 1
_SMALL = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def _n(text: str) -> str:
    from ..gazetteer import norm
    return norm(text or "")


def _has(t: str, w: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(_n(w))}(?![a-z0-9])", t) is not None


# ---- years ------------------------------------------------------------------------------------------------------------
def _two(ws: list[str]) -> tuple[int | None, int]:
    """A number 0..99 at the start of ws ("seventy five", "nineteen", "oh five") -> (value, words used)."""
    if not ws:
        return None, 0
    if ws[0] in _TENS:
        if len(ws) > 1 and ws[1] in _SMALL and 0 < _SMALL[ws[1]] < 10:
            return _TENS[ws[0]] + _SMALL[ws[1]], 2
        return _TENS[ws[0]], 1
    if ws[0] in _SMALL:
        if ws[0] == "oh" and len(ws) > 1 and ws[1] in _SMALL and _SMALL[ws[1]] < 10:
            return _SMALL[ws[1]], 2
        return _SMALL[ws[0]], 1
    return None, 0


def year_of(text: str) -> int | None:
    """A calendar year said or typed: "1275", "twelve seventy five", "twelve hundred seventy five",
    "one thousand two hundred seventy five", "AD 1275". The first one found; None when there is none."""
    t = _n(text)
    m = re.search(r"(?<!\d)(\d{3,4})(?!\d)", t)
    if m:
        return int(m.group(1))
    ws = t.replace("-", " ").split()
    for i in range(len(ws)):
        w = ws[i:]
        if w and w[0] == "one" and len(w) > 2 and w[1] == "thousand":        # one thousand two hundred seventy five
            h, k = _two(w[2:])
            if h and len(w) > 2 + k and w[2 + k] == "hundred":
                rest, _ = _two([x for x in w[3 + k:] if x != "and"])
                return 1000 + h * 100 + (rest or 0)
            continue
        hi, k = _two(w)
        if hi is None or not 10 <= hi <= 20:
            continue
        if len(w) > k and w[k] == "hundred":                                 # twelve hundred (and) seventy five
            lo, _ = _two([x for x in w[k + 1:] if x != "and"])
            return hi * 100 + (lo or 0)
        lo, k2 = _two(w[k:])
        if lo is not None and k2 and (lo >= 10 or w[k] == "oh"):            # twelve seventy five / twelve oh five
            return hi * 100 + lo
    return None


# ---- tree-ring series -------------------------------------------------------------------------------------------------
_SERIES_DIRS: list[Path] = []      # extra places to look (a course pack's folder); the course data folder by default


def series_dirs() -> list[Path]:
    from .content import DATA
    return [*_SERIES_DIRS, *sorted((DATA / "courses").glob("*/rings"))]


@lru_cache(maxsize=8)
def series(sid: str) -> dict | None:
    """A tree-ring series {id, years, index, source, ...} from a course's rings/<sid>.json; None if missing."""
    if not re.fullmatch(r"[a-z0-9_]{2,40}", sid or ""):
        return None
    for d in series_dirs():
        p = d / f"{sid}.json"
        if p.exists():
            s = json.loads(p.read_text())
            return s if len(s.get("years", [])) == len(s.get("index", [])) and s.get("years") else None
    return None


def widths(sid: str, y0: int, y1: int) -> list[float] | None:
    """The series' index for years y0..y1 inclusive (None if the series doesn't cover them)."""
    s = series(sid)
    if not s:
        return None
    by = dict(zip(s["years"], s["index"]))
    out = [by.get(y) for y in range(int(y0), int(y1) + 1)]
    return None if any(v is None for v in out) else [round(float(v), 3) for v in out]


# ---- graders ----------------------------------------------------------------------------------------------------------
def _seq_items(acc: dict) -> list[dict]:
    """The layers step's items in the answer order (oldest -> youngest), the pit among them."""
    by = {l["id"]: l for l in acc.get("layers", [])}
    if acc.get("pit"):
        by[acc["pit"]["id"]] = acc["pit"]
    return [by[i] for i in acc.get("order", []) if i in by]


def _valid_prefix(got, ids: list[str]) -> list[str]:
    out: list[str] = []
    for g in got or []:
        if len(out) < len(ids) and g == ids[len(out)]:
            out.append(g)
        else:
            break
    return out


def _named(text: str, it: dict) -> list[int]:
    t = f" {_n(text)} "
    return [m.start() for w in [it["label"], *it.get("say", [])] if len(_n(w)) > 1
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(_n(w))}(?![a-z0-9])", t)]


def pit_cuts(acc: dict) -> list[str]:
    """The layers the pit cuts through: from `from` (the layer it is dug from, exclusive) down to `to` (inclusive),
    in the drawn top-to-bottom order."""
    p = acc.get("pit") or {}
    ids = [l["id"] for l in acc.get("layers", [])]
    if p.get("from") not in ids or p.get("to") not in ids:
        return []
    a, b = ids.index(p["from"]), ids.index(p["to"])
    return ids[a + 1:b + 1]


def _layers(acc: dict, inp: dict, text: str):
    items = _seq_items(acc)
    ids = [i["id"] for i in items]
    got = _valid_prefix(inp.get("got"), ids)
    pit = (acc.get("pit") or {}).get("id")
    cuts = pit_cuts(acc)

    def trap_now(g: list[str]) -> bool:      # naming the pit while a layer it cuts is still missing
        return bool(pit) and any(c not in g for c in cuts)
    nxt = ids[len(got)] if len(got) < len(ids) else None
    if inp.get("choice") and nxt:
        c = inp["choice"]
        if c == nxt:
            got.append(c)
        elif c == pit and trap_now(got):
            return False, {"got": got, "next": nxt, "trap": "pit", "cuts": [x for x in cuts if x not in got]}
        else:
            return False, {"got": got, "next": nxt, "wrong": c if c in ids else None}
    elif text and nxt:
        pos = 0
        pit_item = next((x for x in items if x["id"] == pit), None)
        for it in items[len(got):]:
            hits = [h for h in _named(text, it) if h >= pos]
            if pit_item and it["id"] != pit and trap_now(got):
                # the pit said here, before a layer it cuts: the classic trap (ordering by depth)
                ph = [h for h in _named(text, pit_item) if h >= pos]
                if ph and (not hits or min(ph) < min(hits)):
                    return False, {"got": got, "next": it["id"], "trap": "pit",
                                   "cuts": [x for x in cuts if x not in got]}
            if not hits:
                break
            pos = min(hits) + 1
            got.append(it["id"])
    done = len(got) == len(ids)
    return done, {"got": got, "next": None if done else ids[len(got)]}


def _rings(acc: dict, inp: dict, text: str):
    want = int(acc["beam"][1])
    y = None
    if inp.get("choice") and re.fullmatch(r"\d{3,4}", str(inp["choice"])):
        y = int(inp["choice"])
    elif text:
        y = year_of(text)
    if y is None:
        return False, {}
    off = y - want
    return abs(off) <= int(acc.get("tol", RINGS_TOL)), {"year": y, "off": off}


def _hit(tap: dict, t: dict, asp: float = 1.0) -> bool:
    """A tap inside a target. x, y are fractions of the image's width and height; r is a fraction of its width, so the
    y distance is scaled by the image's aspect (h / w) to measure in width units (a round ring stays round)."""
    try:
        return math.hypot(float(tap["x"]) - t["x"], (float(tap["y"]) - t["y"]) * asp) <= t.get("r", 0.05)
    except (KeyError, TypeError, ValueError):
        return False


def _aspect(acc: dict) -> float:
    im = acc.get("image") or {}
    try:
        return float(im["h"]) / float(im["w"]) if im.get("w") and im.get("h") else 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0


def _hillshade(acc: dict, inp: dict, text: str):
    ts = acc.get("targets", [])
    ids = [t["id"] for t in ts]
    got = [g for g in dict.fromkeys(inp.get("got") or []) if g in ids]
    need = min(int(acc.get("need") or len(ts)), len(ts))
    new: list[str] = []
    tap, asp = inp.get("tap"), _aspect(acc)
    if isinstance(tap, dict) and tap.get("x") is not None:
        hit = next((t["id"] for t in ts if _hit(tap, t, asp) and t["id"] not in got), None)
        if hit is None and any(_hit(tap, t, asp) for t in ts):
            return False, {"got": got, "next": _next_target(ts, got), "again": True}   # found already
        new = [hit] if hit else []
    elif inp.get("choice") in ids:
        new = [inp["choice"]] if inp["choice"] not in got else []
    elif text:
        t = _n(text)
        new = [x["id"] for x in ts if x["id"] not in got and any(_has(t, w) for w in [x["label"], *x.get("say", [])])]
    got = got + new
    done = len(got) >= need
    return done, {"got": got, "new": new, "next": None if done else _next_target(ts, got)}


def _next_target(ts: list[dict], got: list[str]) -> str | None:
    return next((t["id"] for t in ts if t["id"] not in got), None)


def _decide(acc: dict, inp: dict, text: str):
    from .grade import _option_of
    c = _option_of(inp, acc["options"], fuzzy=False)
    if c is None:
        return False, {}
    o = next(o for o in acc["options"] if o["id"] == c)
    best = next((x["id"] for x in acc["options"] if x.get("best")), None)
    return True, {"choice": c, "best": bool(o.get("best")), "law": acc.get("law"),
                  **({"better": best} if best and best != c else {})}


GRADERS = {"layers": _layers, "rings": _rings, "hillshade": _hillshade, "decide": _decide}


# ---- what the client sees (content.public) ----------------------------------------------------------------------------
def media_url(course: str | None, name: str) -> str:
    """A course media file's URL (app/courses.py course_media)."""
    return f"/api/courses/{course or 'moon'}/media/{name}"


def public_accept(a: dict, course: str | None = None) -> dict:
    """The step for the client, without the answer key. `course`: the course id (media URLs)."""
    t = a["type"]
    acc: dict = {"type": t}
    if t == "layers":
        acc["layers"] = [{k: l[k] for k in ("id", "label", "h", "finds", "tone") if k in l} for l in a["layers"]]
        if a.get("pit"):
            acc["pit"] = {k: a["pit"][k] for k in ("id", "label", "from", "to") if k in a["pit"]}
    elif t == "rings":
        m0, m1 = a["master"]
        b0, b1 = a["beam"]
        s = series(a["series"]) or {}
        acc |= {"master": {"from": m0, "to": m1, "w": widths(a["series"], m0, m1) or []},
                "beam": {"n": b1 - b0 + 1, "w": widths(a["series"], b0, b1) or []},
                "start": int(a.get("start", m0 + b1 - b0)), "tol": int(a.get("tol", RINGS_TOL)),
                "source": s.get("source"), "series_title": s.get("title")}
    elif t == "hillshade":
        acc["image"] = dict(a["image"]) | {k + "_url": media_url(course, a["image"][k]) for k in ("low", "high")
                                           if a["image"].get(k)}
        acc["targets"] = [{k: x[k] for k in ("id", "label", "x", "y", "r") if k in x} for x in a["targets"]]
        acc["need"] = min(int(a.get("need") or len(a["targets"])), len(a["targets"]))
    elif t == "decide":
        acc["options"] = [{"id": o["id"], "label": o["label"]} for o in a["options"]]
    return acc


# ---- voice ------------------------------------------------------------------------------------------------------------
def step_options(acc: dict) -> list[tuple[str, list[str]]]:
    """[(id, [label, *say])] in the order the client numbers them (grade.step_options)."""
    t = acc["type"]
    if t == "decide":
        return [(o["id"], [o["label"], *o.get("say", [])]) for o in acc.get("options", [])]
    if t == "layers":
        items = list(acc.get("layers", [])) + ([acc["pit"]] if acc.get("pit") else [])
        return [(o["id"], [o["label"], *o.get("say", [])]) for o in items]
    if t == "hillshade":
        return [(o["id"], [o["label"], *o.get("say", [])]) for o in acc.get("targets", [])]
    return []


def answer_for(step: dict, got: list | None = None) -> str:
    """What a voice-only student says (the hands-free script and the lesson tests)."""
    acc = step["accept"]
    t = acc["type"]
    if t == "layers":
        items = _seq_items(acc)
        return "oldest first: " + ", then ".join(i["label"].lower() for i in items[len(got or []):])
    if t == "rings":
        return f"the outer ring is {acc['beam'][1]}"
    if t == "hillshade":
        left = [x for x in acc["targets"] if x["id"] not in (got or [])]
        return " and ".join(x["label"] for x in left[: max(1, int(acc.get("need") or len(left)))])
    if t == "decide":
        o = next((o for o in acc["options"] if o.get("best")), acc["options"][0])
        return o["label"]
    return "next"


def plausible(acc: dict, text: str) -> bool:
    """A real try at a rings step: a year (anything else is room talk)."""
    return acc.get("type") == "rings" and year_of(text) is not None


# ---- hints ------------------------------------------------------------------------------------------------------------
def hint(st: dict, rung: int, got: list | None, extra: dict | None = None, lead: str = "") -> dict:
    """The hint ladder for these steps (guide.help_rung / guide.ladder call this). Every line says what to do next."""
    acc, t = st["accept"], st["accept"]["type"]
    extra = extra or {}
    out: dict = {"rung": rung, "hint": st.get("hint", "")}
    h = _end(st.get("hint", ""))
    if t == "layers":
        items = _seq_items(acc)
        nxt = next((i for i in items if i["id"] not in (got or [])), None)
        if extra.get("trap") == "pit":
            lab = {i["id"]: i["label"].lower() for i in items}
            cut = [lab[c] for c in pit_cuts(acc) if c in extra.get("cuts", [])]   # top to bottom, as drawn
            out["say"] = f"Careful: the pit cuts through the {_join(cut)}. It came after them."
            out["trap"] = "pit"
            return out
        out["say"] = lead + h
        if rung >= 2 and nxt:
            # [arch QA] the next layer glows (its chip and its band in the trench); its name is NOT handed over in a
            # "Say: …" box at this rung (that gave the answer away). "help" a third time shows it.
            out |= {"answer": nxt["id"]}
            out["say"] = lead + "The next layer glows on the card."
        return out
    if t == "rings":
        off = extra.get("off")
        if isinstance(off, int) and off:
            way = "later: slide the beam right" if off < 0 else "earlier: slide the beam left"
            out["say"] = f"Not {extra.get('year')}. Try {way}."
        else:
            out["say"] = lead + h
        if rung >= 2:
            out["cue"] = {"rings": "align"}
            out["say"] += " Match the three narrow rings first."
        return out
    if t == "hillshade":
        nxt = _next_target(acc.get("targets", []), got or [])
        out["say"] = lead + h
        if rung >= 2 and nxt:
            out["focus"] = [nxt]
            out["say"] = lead + "Look inside the glowing ring."
        if rung >= 3 and nxt:
            out["answer"] = nxt
            out["say"] = f"Here it is: {next(x['label'] for x in acc['targets'] if x['id'] == nxt)}. Tap it."
        return out
    if t == "decide":
        return {**out, "rung": 1, "say": "There's no trick here. Pick what you would do."}
    out["say"] = lead + h
    return out


def _end(t: str) -> str:
    t = str(t or "").strip()
    return t if not t or t[-1] in ".!?" else t + "."


def _join(ws: list[str]) -> str:
    return ws[0] if len(ws) == 1 else ", ".join(ws[:-1]) + " and " + ws[-1] if ws else "layers below it"


def answer_of(st: dict) -> dict:
    """What the client highlights when the answer is shown (routes._answer_of)."""
    a = st["accept"]
    if a["type"] == "layers":
        items = _seq_items(a)
        return {"order": [i["id"] for i in items], "say": ", ".join(i["label"] for i in items)}
    if a["type"] == "rings":
        return {"year": a["beam"][1]}
    if a["type"] == "hillshade":
        return {"targets": [t["id"] for t in a["targets"]]}
    if a["type"] == "decide":
        return {"choice": next((o["id"] for o in a["options"] if o.get("best")), None)}
    return {}


# ---- content checks ---------------------------------------------------------------------------------------------------
def check_step(s: dict) -> list[str]:
    """Shape and copy checks (content.check / the course tests)."""
    a, out = s.get("accept") or {}, []
    t = a.get("type")
    words = lambda x: len(str(x or "").split())   # noqa: E731
    if t == "layers":
        ls = a.get("layers") or []
        ids = [l.get("id") for l in ls] + ([a["pit"].get("id")] if a.get("pit") else [])
        if not 3 <= len(ls) <= 6 or len(set(ids)) != len(ids):
            out.append("layers: 3 to 6 layers with unique ids")
        if sorted(a.get("order") or []) != sorted(ids):
            out.append("layers: order must list every layer (and the pit) once")
        if any(not l.get("label") or words(l["label"]) > 3 for l in ls):
            out.append("layers: every layer needs a label of 3 words or fewer")
        if a.get("pit"):
            cuts = pit_cuts(a)
            o = a.get("order") or []
            if not cuts:
                out.append("layers: pit.from / pit.to must be layers (from above to)")
            elif a["pit"]["id"] in o and any(o.index(c) > o.index(a["pit"]["id"]) for c in cuts if c in o):
                out.append("layers: the pit must be younger than every layer it cuts")
        o, drawn = a.get("order") or [], [l.get("id") for l in ls]
        lay = [x for x in o if x in drawn]
        if lay != list(reversed(drawn)):
            out.append("layers: undisturbed layers go oldest at the bottom (order = drawn order reversed)")
    if t == "rings":
        m, b = a.get("master") or [0, 0], a.get("beam") or [0, 0]
        if not (m[0] < b[0] < b[1] <= m[1]):
            out.append("rings: the beam's years must sit inside the master's")
        if widths(a.get("series", ""), m[0], m[1]) is None:
            out.append(f"rings: series {a.get('series')!r} does not cover {m[0]}-{m[1]}")
        if b[1] - b[0] + 1 < 20:
            out.append("rings: a beam needs at least 20 rings to match")
        st = a.get("start")
        if st is not None and (abs(st - b[1]) < 8 or not m[0] + b[1] - b[0] <= st <= m[1]):
            out.append("rings: start (the beam's first outer-ring position) on the strip, at least 8 years off the answer")
    if t == "hillshade":
        ts, im = a.get("targets") or [], a.get("image") or {}
        if not 1 <= len(ts) <= 5:
            out.append("hillshade: 1 to 5 targets")
        for x in ts:
            if not (0 <= x.get("x", -1) <= 1 and 0 <= x.get("y", -1) <= 1 and 0 < x.get("r", 0) <= 0.2):
                out.append(f"hillshade: {x.get('id')} needs x, y in 0..1 and 0 < r <= 0.2")
            if any(k in x for k in ("lat", "lon", "latitude", "longitude")):
                out.append(f"hillshade: {x.get('id')} has coordinates (park-level only: image fractions)")
        if not (im.get("low") and im.get("alt") and im.get("credit") and str((im.get("source") or {}).get("url", "")).startswith("https://")):
            out.append("hillshade: image needs low, alt, credit and a source")
    if t == "decide":
        os_ = a.get("options") or []
        if not 2 <= len(os_) <= 3:
            out.append("decide: 2 or 3 options")
        if sum(bool(o.get("best")) for o in os_) != 1:
            out.append("decide: exactly one best option")
        for o in os_:
            if not o.get("reply") or words(o["reply"]) > 20:
                out.append(f"decide: option {o.get('id')} needs its own reply of 20 words or fewer")
            if re.search(r"\b(wrong|no!|incorrect|bad)\b", str(o.get("reply", "")), re.I):
                out.append(f"decide: option {o.get('id')} reply must never say wrong")
        law = a.get("law") or {}
        if not (law.get("title") and law.get("text") and str((law.get("source") or {}).get("url", "")).startswith("https://")):
            out.append("decide: a law card needs title, text and a https source")
    return out
