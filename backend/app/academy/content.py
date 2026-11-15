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
                "predict", "globe_side", "terminator", "compare", "route", "earth_view",   # globe steps: grade.py
                "video")   # a NASA video step (docs/MEDIA.md): predict → watch or skip → reveal; never blocks
PREP_MAX_STEPS = 3      # a mission-prep task: 3 spoken steps or fewer
PREP_END = "Tell me when it's ready."   # how a prep task's last line ends: never the trigger word "done" (the open mic
                                        # would hear our own "done" back, docs/COPY.md); the button still says Done
GLOBE_DO = ("fly", "side", "pole", "sun", "zoom", "pair", "earth", "route")   # step.globe.do (client directive)
NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


VIDEO_HINT = "Tap Watch, or say skip."


def _video_media() -> dict:
    """The catalog's videos by source (backend/data/video/catalog.json, the one list; app/video.py validates it).
    "cached": NASA files kept after the first online launch, so they play offline. "online": NASA-channel YouTube
    embeds, stream only. A step on an online video still passes offline: the reveal is said and the lesson goes on."""
    cat = json.loads((DATA / "video" / "catalog.json").read_text())
    return {"cached": tuple(v["id"] for v in cat if v.get("source") == "nasa_file"),
            "online": tuple(v["id"] for v in cat if v.get("source") == "youtube")}


VIDEO_MEDIA = _video_media()
VIDEO_IDS = frozenset(VIDEO_MEDIA["cached"] + VIDEO_MEDIA["online"])


def video_step(s: dict) -> dict:
    """A video step as written in course.json, {"type": "video", "media": id, "say": predict prompt, "reveal": line},
    in the shape every other step has: prompt = say, accept = {type: video, media}, success = reveal. Watching or
    skipping both pass (never block a lesson on media); the reveal is said either way."""
    if s.get("type") != "video" or "accept" in s:
        return s
    return {**s, "prompt": s.get("say", ""), "accept": {"type": "video", "media": s.get("media")},
            "success": s.get("reveal", ""), "hint": s.get("hint") or VIDEO_HINT, "fail": s.get("fail") or VIDEO_HINT}


def normalize(c: dict) -> dict:
    for l in c.get("lessons", []):
        l["steps"] = [video_step(s) for s in l.get("steps", [])]
    return c


@lru_cache(maxsize=1)
def course() -> dict:
    return normalize(json.loads(COURSE.read_text()))


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
        if a["type"] == "video":
            acc["media"] = a.get("media")
        if a["type"].startswith("vocab_"):           # Space words: options without the answer key
            from .vocab import public_accept
            acc = public_accept(a)
        return {k: v for k, v in s.items() if k not in ("accept",)} | {"accept": acc}
    c = course()
    return {"title": c["title"], "pass_badge": c["pass_badge"],
            "lessons": [{k: v for k, v in l.items() if k != "steps"} | {"steps": [step(s) for s in l["steps"]]}
                        for l in c["lessons"]]}


def longest_dark_h(site_id: str) -> int:
    """Longest run of hours with the Sun below the site's horizon (JPL Horizons ephemeris; the LOLA terrain horizon
    at the Sun's azimuth when the ephemeris has it, as the sim uses, else the one effective angle)."""
    e = json.loads((DATA / "mission" / f"ephemeris_{site_id}.json").read_text())
    hz = e.get("sun_terrain_deg") or [e["horizon_deg"]] * len(e["sun_elev_deg"])
    best = cur = 0
    for elev, h in zip(e["sun_elev_deg"], hz):
        cur = 0 if elev > h else cur + 1
        best = max(best, cur)
    return best


def check_video_step(s: dict, ids: set[str] | None = None) -> list[str]:
    """A video step names a catalog video (backend/data/video/catalog.json) and has its predict line and its reveal."""
    if (s.get("accept") or {}).get("type") != "video" and s.get("type") != "video":
        return []
    if ids is None:
        from .. import video
        ids = {v["id"] for v in video.catalog()}
    out = []
    m = s.get("media") or (s.get("accept") or {}).get("media")
    if m not in ids:
        out.append(f"video step: media {m!r} is not in the video catalog")
    for k in ("say", "reveal"):
        if not str(s.get(k) or "").strip():
            out.append(f"video step needs {k}")
        elif len(str(s[k]).split()) > 20:
            out.append(f"video step {k} over 20 spoken words")
    return out


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


def check_prep(p: dict) -> list[str]:
    """A mission-prep task (lesson.prep): a hands-on job before the lesson, adapted from a NASA activity.
    {id, title, steps: [<= 3 spoken lines], grown_up: bool, source: {title, url}}. The last line ends PREP_END and no
    line says "done" (the kid answers Done by voice, a thumbs-up or a tap; Skip always works). The source is credited
    in data only."""
    out = []
    for k in ("id", "title", "steps", "source"):
        if not p.get(k):
            out.append(f"prep missing {k}")
    if len(str(p.get("title", "")).split()) > 6:
        out.append("prep title over 6 words")
    steps = p.get("steps") or []
    if not 1 <= len(steps) <= PREP_MAX_STEPS:
        out.append(f"prep needs 1 to {PREP_MAX_STEPS} spoken steps")
    for t in steps:
        if len(str(t).split()) > 20:
            out.append(f"prep step over 20 words: {t!r}")
    if steps and not str(steps[-1]).rstrip().endswith(PREP_END):
        out.append(f"prep's last step must end with {PREP_END!r}")
    if any(re.search(r"\bdone\b", str(t), re.I) for t in steps):
        out.append("prep never speaks the trigger word 'done'")
    if not isinstance(p.get("grown_up"), bool):
        out.append("prep.grown_up must be true or false")
    src = p.get("source") or {}
    if not (src.get("title") and str(src.get("url", "")).startswith("https://")):
        out.append("prep source needs {title, https url}")
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
        if l.get("prep") is not None:
            probs += [f"{lid}: {p}" for p in check_prep(l["prep"])]
        if l.get("track", "core") not in ("core", "explorer"):
            probs.append(f"{lid}: track must be core or explorer")
        if l.get("track") == "explorer" and not (isinstance(l.get("unlock_after_missions"), int)
                                                 and l["unlock_after_missions"] >= 1):
            probs.append(f"{lid}: an explorer lesson needs unlock_after_missions >= 1")
        if l.get("track") == "explorer" and l.get("ride"):
            probs.append(f"{lid}: the check ride is core")
        pv = l.get("patch_video")
        if pv is not None and not (pv.get("media") in VIDEO_IDS and pv.get("line") and len(pv["line"].split()) <= 12):
            probs.append(f"{lid}: patch_video needs a known media id and a line of 12 words or fewer")
        cl = l.get("clip") or {}
        if cl.get("note") and len(cl["note"].split()) > 12:
            probs.append(f"{lid}: clip note over 12 words")
        steps = l.get("steps", [])
        graded = [s for s in steps if (s.get("accept") or {}).get("type") != "video"]
        if steps and not graded:
            probs.append(f"{lid}: a lesson needs at least one step that isn't a video")
        for i, s in enumerate(steps):
            for k in ("prompt", "accept", "hint", "success", "fail"):
                if not s.get(k):
                    probs.append(f"{lid}[{i}]: missing {k}")
            a = s.get("accept") or {}
            if a.get("type") == "video" or s.get("type") == "video":
                probs += [f"{lid}[{i}]: {p}" for p in check_video_step(s)]
                if l.get("ride"):
                    probs.append(f"{lid}[{i}]: no videos in the check ride (it runs on the live sim)")
                continue
            if a.get("type") not in ACCEPT_TYPES:
                probs.append(f"{lid}[{i}]: bad accept type {a.get('type')!r}")
            if a.get("type") == "choice" and a.get("answer") not in {o["id"] for o in a.get("options", [])}:
                probs.append(f"{lid}[{i}]: answer not among options")
            if str(a.get("type", "")).startswith("vocab_"):
                from .vocab import check_step
                probs += [f"{lid}[{i}]: {p}" for p in check_step(a)]
            probs += [f"{lid}[{i}]: {p}" for p in _check_globe_step(s, a)]
            probs += [f"{lid}[{i}]: {p}" for p in check_video_step(s)]
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
