"""Load and check the course (backend/data/academy/course.json)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
COURSE = DATA / "academy" / "course.json"
ACCEPT_TYPES = ("intent", "command", "tap", "keywords", "choice",
                "vocab_match", "vocab_say", "vocab_fill", "vocab_listen",   # vocab: app/academy/vocab.py
                "predict", "globe_side", "terminator", "compare", "route", "earth_view")   # globe steps: grade.py
GLOBE_DO = ("fly", "side", "pole", "sun", "zoom", "pair", "earth", "route")   # step.globe.do (client directive)
NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


@lru_cache(maxsize=1)
def course() -> dict:
    return json.loads(COURSE.read_text())


def lesson(lesson_id: str) -> dict | None:
    return next((l for l in course()["lessons"] if l["id"] == lesson_id), None)


def public() -> dict:
    """The course for the client: everything except the answer keys (choices keep their labels)."""
    def step(s: dict) -> dict:
        a = s["accept"]
        acc = {"type": a["type"]}
        if a["type"] == "choice":
            acc["options"] = [{"id": o["id"], "label": o["label"], **({"place": o["place"]} if o.get("place") else {})}
                              for o in a["options"]]
        if a["type"] in ("tap", "intent"):
            acc["place"] = a["place"]
        if a["type"] in ("predict", "compare"):
            acc["options"] = [{"id": o["id"], "label": o["label"]} for o in a["options"]]
            if a.get("metric"):
                acc["metric"] = a["metric"]
        if a["type"] == "globe_side":
            acc["want"] = a["want"]
        if a["type"] == "terminator":
            acc |= {"sun_lon": a["sun_lon"], "tol_deg": a.get("tol_deg", 10)}
        if a["type"] == "route":
            acc["stops"] = list(a["stops"])
        if a["type"] == "earth_view":
            acc["place"] = a["place"]
            acc["options"] = [{"id": k, "label": k.capitalize()} for k in ("yes", "no", "sometimes")]
        if a["type"].startswith("vocab_"):           # Space words: options without the answer key
            from .vocab import public_accept
            acc = public_accept(a)
        return {k: v for k, v in s.items() if k not in ("accept",)} | {"accept": acc}
    c = course()
    return {"title": c["title"], "pass_badge": c["pass_badge"],
            "lessons": [{k: v for k, v in l.items() if k != "steps"} | {"steps": [step(s) for s in l["steps"]]}
                        for l in c["lessons"]]}


def longest_dark_h(site_id: str) -> int:
    """Longest run of hours with the Sun below the site's effective horizon (JPL Horizons ephemeris)."""
    e = json.loads((DATA / "mission" / f"ephemeris_{site_id}.json").read_text())
    best = cur = 0
    for elev in e["sun_elev_deg"]:
        cur = 0 if elev > e["horizon_deg"] else cur + 1
        best = max(best, cur)
    return best


def _check_globe_step(s: dict, a: dict) -> list[str]:
    from .grade import gaz, where
    out = []
    t = a.get("type")
    if t in ("predict", "compare") and a.get("answer") not in {o["id"] for o in a.get("options", [])}:
        out.append("answer not among options")
    if t == "compare":
        out += [f"unknown place {o['id']}" for o in a.get("options", []) if where(o["id"]) is None]
    if t == "predict" and not s.get("reveal"):
        out.append("predict step needs a reveal line (said after any other guess)")
    if t == "globe_side" and a.get("want") not in ("near", "far"):
        out.append("globe_side.want must be near or far")
    if t == "terminator" and not isinstance(a.get("sun_lon"), (int, float)):
        out.append("terminator needs sun_lon")
    if t == "route":
        out += [f"unknown stop {x}" for x in a.get("stops", []) if x not in gaz().places]
        if len(a.get("stops", [])) < 2:
            out.append("route needs 2+ stops")
    if t == "earth_view" and where(a.get("place", "")) is None:
        out.append(f"unknown place {a.get('place')}")
    g = s.get("globe")
    if g and g.get("do") not in GLOBE_DO:
        out.append(f"bad globe.do {g.get('do')!r}")
    if g and g.get("place") and where(g["place"]) is None:
        out.append(f"globe.place unknown: {g['place']}")
    # guidance (docs/PLAYTEST.md): places the step shows and labels, rings, and the place labelled after the answer
    for k in ("show", "ring"):
        out += [f"{k}: unknown place {x}" for x in s.get(k, []) if where(x) is None]
    if s.get("after_place") and where(s["after_place"]) is None:
        out.append(f"after_place unknown: {s['after_place']}")
    if t == "route" and set(a.get("stops", [])) - set(s.get("show", [])):
        out.append("route: show every stop (a kid can't trace places nobody showed them)")
    if s.get("do") and len(str(s["do"]).split()) > 10:
        out.append("do line over 10 words")
    c = s.get("clip")
    if c and not (c.get("clip_id") and c.get("t1", 0) > c.get("t0", -1) and c.get("t1", 0) - c.get("t0", 0) <= 25.5):
        out.append("clip needs clip_id and 0 < t1 - t0 <= 25 s")
    return out


def check() -> list[str]:
    """Problems with the course: missing fields, unsourced facts, numbers not found in the cited data."""
    probs: list[str] = []
    c = course()
    data_text = {p: p.read_text() for p in DATA.rglob("*.json") if "academy" not in p.parts}
    every = "\n".join(data_text.values())
    for l in c["lessons"]:
        lid = l.get("id", "?")
        for k in ("id", "title", "brief", "steps", "badge", "facts"):
            if not l.get(k):
                probs.append(f"{lid}: missing {k}")
        if len(re.findall(r"[.!?](?:\s|$)", l.get("brief", ""))) > 3:
            probs.append(f"{lid}: brief longer than 3 sentences")
        for f in l.get("facts", []):
            src = f.get("source") or {}
            if not (src.get("title") and str(src.get("url", "")).startswith("http")):
                probs.append(f"{lid}: fact without a {{title,url}} source: {f.get('text')!r}")
            url = str(src.get("url") or "")
            host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
            if url and url not in every and host not in every:
                probs.append(f"{lid}: source url not in repo data: {src.get('url')}")
            files = [DATA / p for p in f.get("from", [])]
            if not files or not all(p.exists() for p in files):
                probs.append(f"{lid}: fact has no data file: {f.get('text')!r}")
                continue
            text = "\n".join(p.read_text() for p in files)
            calc = f.get("calc")
            calc_vals = {str(longest_dark_h(calc["site"]))} if calc and calc.get("kind") == "longest_dark_h" else set()
            for n in NUM.findall(f["text"]):
                plain = n.replace(",", "")
                if n in text or plain in text or plain in calc_vals:
                    continue
                if calc_vals and any(float(plain) < float(v) / 24 for v in calc_vals):  # "more than 6 days"
                    continue
                probs.append(f"{lid}: number {n} not in {f.get('from')}: {f['text']!r}")
        for i, s in enumerate(l.get("steps", [])):
            for k in ("prompt", "accept", "hint", "success", "fail"):
                if not s.get(k):
                    probs.append(f"{lid}[{i}]: missing {k}")
            a = s.get("accept") or {}
            if a.get("type") not in ACCEPT_TYPES:
                probs.append(f"{lid}[{i}]: bad accept type {a.get('type')!r}")
            if a.get("type") == "choice" and a.get("answer") not in {o["id"] for o in a.get("options", [])}:
                probs.append(f"{lid}[{i}]: answer not among options")
            if str(a.get("type", "")).startswith("vocab_"):
                from .vocab import check_step
                probs += [f"{lid}[{i}]: {p}" for p in check_step(a)]
            probs += [f"{lid}[{i}]: {p}" for p in _check_globe_step(s, a)]
        pl = l.get("place")   # the Moon-map pin for this lesson (UX: data-driven map)
        if isinstance(pl, str):
            from .grade import where
            if where(pl) is None:
                probs.append(f"{lid}: place {pl!r} is not in places.json or mission/sites.json")
        elif isinstance(pl, dict) and not (pl.get("name") and isinstance(pl.get("lat"), (int, float))
                                           and isinstance(pl.get("lon"), (int, float))):
            probs.append(f"{lid}: place needs name, lat, lon")
        if i_types := [s.get("accept", {}).get("type") for s in l.get("steps", [])]:
            for k in range(1, len(i_types)):
                if i_types[k] == i_types[k - 1] and not l.get("ride"):
                    probs.append(f"{lid}[{k}]: two {i_types[k]} steps in a row")
    return probs
