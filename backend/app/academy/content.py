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
                "describe", "sequence", "rounds",   # Field School steps: grade.py FIELD_TYPES
                "video")   # a NASA video step (docs/MEDIA.md): predict → watch or skip → reveal; never blocks
PREP_MAX_STEPS = 3      # a mission-prep task: 3 spoken steps or fewer
PREP_END = "Tell me when it's ready."   # how a prep task's last line ends: never the trigger word "done" (the open mic
                                        # would hear our own "done" back, docs/COPY.md); the button still says Done
GLOBE_DO = ("fly", "side", "pole", "sun", "zoom", "pair", "earth", "route")   # step.globe.do (client directive)
NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


VIDEO_HINT = "Tap Watch, or say skip."
# A describe step's chips (tap / keyboard only kids): two words per descriptor kind; a chip sends its word as the answer
FIELD_CHIPS = {"size": ("Big", "Small"), "shape": ("Round", "Odd shape"), "tone": ("Bright", "Dark"),
               "texture": ("Smooth", "Bumpy"), "shadow": ("Long shadows", "No shadows")}
TRACKS = ("core", "explorer", "field")   # field: Field School, a second track that opens after the check ride
ROCK_IDS = ("15016", "60025", "76535", "70017", "79115", "65035")   # the nasa_views pack's Apollo samples
PHOTO_IDS = ("earthrise", "earthset", "art002e014211", "geology_iceland_2026", "geology_iceland_2024")


def _video_media() -> dict:
    """The catalog's videos by source (backend/data/video/catalog.json, the one list; app/video.py validates it).
    "cached": NASA files (and the video pack's own pack_files), kept locally so they play offline. "online": YouTube
    embeds, stream only. A step on an online video still passes offline: the reveal is said and the lesson goes on."""
    cat = json.loads((DATA / "video" / "catalog.json").read_text())
    return {"cached": tuple(v["id"] for v in cat if v.get("source") in ("nasa_file", "pack_file")),
            "online": tuple(v["id"] for v in cat if v.get("source") == "youtube")}


VIDEO_MEDIA = _video_media()
VIDEO_IDS = frozenset(VIDEO_MEDIA["cached"] + VIDEO_MEDIA["online"])


def video_step(s: dict) -> dict:
    """A video step as written in course.json, {"type": "video", "media": id, "say": predict prompt, "reveal": line},
    in the shape every other step has: prompt = say, accept = {type: video, media}, success = reveal. Watching or
    skipping both pass (never block a lesson on media); the reveal is said either way."""
    if s.get("type") != "video" or "accept" in s:
        return s
    acc = {"type": "video", "media": s.get("media"), **({"guess": s["guess"]} if s.get("guess") else {})}
    return {**s, "prompt": s.get("say", ""), "accept": acc,
            "success": s.get("reveal", ""), "hint": s.get("hint") or VIDEO_HINT, "fail": s.get("fail") or VIDEO_HINT}


def normalize(c: dict) -> dict:
    for l in c.get("lessons", []):
        l["steps"] = [video_step(s) for s in l.get("steps", [])]
    return c


@lru_cache(maxsize=1)
def nasa_course() -> dict:
    """The NASA course as written in course.json (check() and the copy tests read this)."""
    return normalize(json.loads(COURSE.read_text()))


@lru_cache(maxsize=1)
def course() -> dict:
    """The course the app plays: the NASA lessons, then the teacher-written Class lessons (classpacks.py,
    docs/CURRICULUM.md; `track: "class"`). A broken pack is skipped by the loader, never raised."""
    c = nasa_course()
    try:
        from . import classpacks
        extra = classpacks.lessons()
    except Exception:   # noqa: BLE001  (Class lessons never stop the NASA course)
        extra = []
    return {**c, "lessons": c["lessons"] + extra} if extra else c


def reload() -> None:
    """Class packs changed: drop every cached lesson list (the course, the voice titles, the session's lesson table)."""
    course.cache_clear()
    try:
        from .. import hotlist, session
        hotlist._lesson_titles.cache_clear()
        session._CACHE.pop("lessons", None)
    except Exception:   # noqa: BLE001
        pass


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
            if a.get("label"):                       # the name the prompt uses ("Cabeus crater"), for the label
                acc["label"] = a["label"]
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
        if a["type"] == "describe":
            from .grade import DESCRIBE, describe_cats
            cats = describe_cats(a)
            acc |= {"need": min(int(a.get("need") or 3), len(cats)),
                    "cats": [{"id": c, "label": DESCRIBE[c][0], "chips": list(FIELD_CHIPS[c])} for c in cats]}
        if a["type"] == "sequence":   # the chips in a fixed shuffled order (by label): the order is the answer
            acc["items"] = sorted(({"id": o["id"], "label": o["label"]} for o in a["items"]), key=lambda o: o["label"])
            if a.get("readback"):     # [0.4.1] a readback repeats Houston's words: the chips in the order heard
                acc["items"], acc["readback"] = [{"id": o["id"], "label": o["label"]} for o in a["items"]], True
        if a["type"] == "rounds":
            acc["options"] = [{"id": o["id"], "label": o["label"]} for o in a["options"]]
            acc["rounds"] = [{k: r[k] for k in ("id", "prompt", "clue", "rock") if r.get(k)} for r in a["rounds"]]
        if a["type"] == "video":
            acc["media"] = a.get("media")
            if (a.get("guess") or {}).get("options"):   # "Guess first": the chips, not the answer (the reply has it)
                acc["guess"] = {"options": [{"id": o["id"], "label": o["label"]} for o in a["guess"]["options"]]}
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
    g = s.get("guess") or (s.get("accept") or {}).get("guess")
    if g and (g.get("answer") not in {o.get("id") for o in g.get("options", [])} or not 2 <= len(g["options"]) <= 3):
        out.append("video step guess: 2 or 3 options, and the answer among them")
    if not g and re.search(r"\bguess\b", str(s.get("say") or s.get("prompt") or ""), re.I):
        out.append("video step says 'guess' but has no guess chips")
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


def check_field_step(s: dict, a: dict) -> list[str]:
    """Field School steps (grade.FIELD_TYPES): their parts, and spoken lines that fit docs/COPY.md."""
    from .grade import DESCRIBE
    t, out = a.get("type"), []
    if t == "describe":
        cats = a.get("descriptors") or list(DESCRIBE)
        if any(c not in DESCRIBE for c in cats):
            out.append("describe: unknown descriptor kind")
        if not 1 <= int(a.get("need") or 3) <= len(cats):
            out.append("describe: need must be 1..number of descriptor kinds")
        if not s.get("example") or len(str(s["example"]).split()) > 20:
            out.append("describe needs an example description (said when CAPCOM shows it), 20 words or fewer")
    if t == "sequence":
        items = a.get("items") or []
        if not 2 <= len(items) <= 6 or len({i.get("id") for i in items}) != len(items):
            out.append("sequence: 2 to 6 items with unique ids")
        if any(not i.get("label") or len(i["label"].split()) > 4 for i in items):
            out.append("sequence: every item needs a label of 4 words or fewer")
    if t == "rounds":
        opts, rs = {o["id"] for o in a.get("options") or []}, a.get("rounds") or []
        if not 2 <= len(opts) <= 5:
            out.append("rounds: 2 to 5 options")
        if not 2 <= len(rs) <= 5 or len({r.get("id") for r in rs}) != len(rs):
            out.append("rounds: 2 to 5 rounds with unique ids")
        for r in rs:
            if r.get("answer") not in opts:
                out.append(f"rounds: {r.get('id')} answer not among options")
            for k in ("prompt", "hint"):
                if not r.get(k) or len(str(r[k]).split()) > 12:
                    out.append(f"rounds: {r.get('id')} needs a {k} of 12 words or fewer")
            if r.get("rock") and r["rock"] not in ROCK_IDS:
                out.append(f"rounds: {r.get('id')} rock {r['rock']} is not in the nasa_views pack")
            if r.get("rock") and not r.get("clue"):
                out.append(f"rounds: {r.get('id')} shows a rock, so it needs a text clue (no pack: the clue alone)")
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
    c = nasa_course()
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
        if l.get("track", "core") not in TRACKS:
            probs.append(f"{lid}: track must be one of {TRACKS}")
        if l.get("track") == "field" and (l.get("unlock_after") != "checkride" or l.get("ride")):
            probs.append(f"{lid}: a Field School lesson opens after the check ride (unlock_after checkride)")
        ph = l.get("photo")
        if ph is not None and not (ph.get("id") in PHOTO_IDS and ph.get("alt") and len(str(ph["alt"]).split()) <= 20
                                   and (ph.get("source") or {}).get("url", "").startswith("https://")):
            probs.append(f"{lid}: photo needs a nasa_views image id, an alt line (<= 20 words) and a source")
        # an explorer lesson opens after n missions, or (unlock_after: "checkride") once the cadet is qualified
        if l.get("track") == "explorer" and not ((isinstance(l.get("unlock_after_missions"), int)
                                                  and l["unlock_after_missions"] >= 1)
                                                 or l.get("unlock_after") == "checkride"):
            probs.append(f"{lid}: an explorer lesson needs unlock_after_missions >= 1 or unlock_after checkride")
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
            probs += [f"{lid}[{i}]: {p}" for p in check_field_step(s, a)]
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
