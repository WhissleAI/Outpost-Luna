"""The course Library (docs/COURSES.md "Course library"): what a non-Moon course shows on its Library screen.

The Moon's Library is built from code and its own assets (hardware, crew audio, the nasa_views pack). Another course
names a library file in its manifest (`library`, e.g. courses/archaeology/library.json) and its own videos (`videos`,
merged into the video catalog by app/video.py while the course is active). The library is shelves of items:

  image  a picture in the course's media/ folder, credited in media/credits.json (credit, licence, source_url, alt)
  video  an id in the course's videos.json (played by the app's NASA video player, frontend/src/media/video.js)
  place  a gazetteer place (places.json): the globe flies there

Any item may name a `place` (gazetteer id) or its own `lat`/`lon` (a marker on the globe), and a `source` (an id in
the course's sources.json, the checked quotes). `overlays` drape a media picture over the globe between its bounds
(an equirectangular lat/lon image), `tour` lists gazetteer stops, `chips` are the askbar's shortcuts, `featured` the item ids the Field School map's
"Real views" ribbon shows, `home` where the Library's camera starts, `moon` the context Moon in Earth's sky (its line,
a place and an item to go to; no `moon`, no Moon in the sky).

Routes
  GET /api/course/library   the active course's library, every item resolved (url, credit, video, place), or
                            {"course": id, "shelves": []} for a course without one (the Moon)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter

from . import courses

router = APIRouter()
FORMAT, VERSION = "outpost-luna-library", 1
KINDS = ("image", "video", "place")
ID = re.compile(r"^[a-z0-9_]{2,40}$")
CHIP_DO = re.compile(r"^(tour|item:[a-z0-9_]{2,40})$")


def _read(p: Path | None):
    if p is None:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _course_files(m: dict) -> dict:
    """The data a library is checked and resolved against, all from the course's own folder (source or pack): media/
    and its credits, the gazetteer, sources.json (next to the library file) and the course's videos."""
    lp = courses.path("library", m)
    media = courses.media_dir(m["id"]) or (lp.parent / "media" if lp else Path("."))
    places = _read(courses.path("gazetteer", m)) or {}
    srcs = _read(lp.parent / "sources.json") if lp is not None else None
    return {
        "media": media,
        "credits": {c["file"]: c for c in (_read(media / "credits.json") or []) if isinstance(c, dict) and "file" in c},
        "places": {p["id"]: p for p in (places.get("places") if isinstance(places, dict) else places) or []
                   if isinstance(p, dict) and "id" in p},
        "sources": {s["id"]: s for s in ((srcs or {}).get("sources") or []) if isinstance(s, dict) and "id" in s},
        "videos": {v["id"]: v for v in (_read(courses.path("videos", m)) or []) if isinstance(v, dict) and "id" in v},
    }


def _ll_ok(lat, lon) -> bool:
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180


def validate(lib, files: dict) -> list[str]:
    """Problems with a library (empty = fine): every file credited and present, every id known, bounds sane."""
    if not isinstance(lib, dict) or lib.get("format") != FORMAT or lib.get("version") != VERSION:
        return [f'library: expected format "{FORMAT}", version {VERSION}']
    out, seen = [], set()
    cred, places, sources, videos = files["credits"], files["places"], files["sources"], files["videos"]

    def need_file(at, f):
        if not isinstance(f, str) or f not in cred:
            out.append(f"{at}: {f!r} has no entry in media/credits.json")
        elif not (files["media"] / f).is_file():
            out.append(f"{at}: media/{f} is missing")
        elif not (cred[f].get("credit") and cred[f].get("licence") and str(cred[f].get("source_url", "")).startswith("https://")
                  and cred[f].get("alt")):
            out.append(f"{at}: {f}'s credit needs credit, licence, an https source_url and alt")
    shelves = lib.get("shelves")
    if not isinstance(shelves, list) or not shelves:
        return out + ["library: shelves must be a non-empty list"]
    for si, sh in enumerate(shelves):
        if not isinstance(sh, dict) or not ID.match(str(sh.get("id", ""))) or not sh.get("title"):
            out.append(f"shelves[{si}]: needs an id and a title")
            continue
        for k, it in enumerate(sh.get("items") or []):
            at = f"{sh['id']}[{k}]"
            iid = it.get("id") if isinstance(it, dict) else None
            if not ID.match(str(iid or "")):
                out.append(f"{at}: id must be lower_snake_case")
                continue
            at = f"{sh['id']}.{iid}"
            if iid in seen:
                out.append(f"{at}: duplicate id")
            seen.add(iid)
            kind = it.get("kind")
            if kind not in KINDS:
                out.append(f"{at}: kind must be one of {KINDS}")
            if kind == "image":
                need_file(at, it.get("file"))
            if kind == "video" and it.get("video") not in videos:
                out.append(f"{at}: video {it.get('video')!r} is not in the course's videos.json")
            if kind == "place" and it.get("place") not in places:
                out.append(f"{at}: place {it.get('place')!r} is not in the gazetteer")
            if kind != "video" and not it.get("title"):
                out.append(f"{at}: needs a title")
            if "place" in it and it["place"] not in places:
                out.append(f"{at}: place {it['place']!r} is not in the gazetteer")
            if ("lat" in it or "lon" in it) and not _ll_ok(it.get("lat"), it.get("lon")):
                out.append(f"{at}: lat/lon out of range")
            if "source" in it and it["source"] not in sources:
                out.append(f"{at}: source {it['source']!r} is not in sources.json")
    for k, o in enumerate(lib.get("overlays") or []):
        at = f"overlays[{k}]"
        need_file(at, o.get("file") if isinstance(o, dict) else None)
        b = (o or {}).get("bounds") if isinstance(o, dict) else None
        if not (isinstance(b, dict) and _ll_ok(b.get("south"), b.get("west")) and _ll_ok(b.get("north"), b.get("east"))
                and b["south"] < b["north"] and b["west"] < b["east"] and b["east"] - b["west"] <= 20
                and b["north"] - b["south"] <= 20):
            out.append(f"{at}: bounds must be {{west, south, east, north}} degrees, at most 20 across")
        else:
            cr = cred.get(o.get("file")) or {}
            w, h = cr.get("width"), cr.get("height")
            if w and h and abs((b["east"] - b["west"]) / (b["north"] - b["south"]) - w / h) > 0.02:
                out.append(f"{at}: the picture's shape ({w}x{h}) does not match its bounds (an equirectangular image)")
    tour = lib.get("tour")
    if tour is not None:
        stops = tour.get("stops") if isinstance(tour, dict) else None
        if not isinstance(stops, list) or not stops or any(s not in places for s in stops):
            out.append("tour.stops: gazetteer place ids")
    for k, c in enumerate(lib.get("chips") or []):
        if not (isinstance(c, dict) and c.get("label") and CHIP_DO.match(str(c.get("do", "")))):
            out.append(f"chips[{k}]: {{label, do: 'tour' | 'item:<id>'}}")
        elif str(c["do"]).startswith("item:") and c["do"][5:] not in seen:
            out.append(f"chips[{k}]: no item {c['do'][5:]!r}")
    if any(x not in seen for x in lib.get("featured") or []):
        out.append("featured: item ids (the map's Real views ribbon)")
    mo = lib.get("moon")
    if mo is not None and not (isinstance(mo, dict) and mo.get("say") and mo.get("place") in (None, *places)
                               and mo.get("item") in (None, *seen)):
        out.append("moon: {say, place?: gazetteer id, place_label?, item?: library item id}")
    h = lib.get("home")
    if h is not None and not (isinstance(h, dict) and _ll_ok(h.get("lat"), h.get("lon"))):
        out.append("home: {lat, lon, dist?}")
    return out


def resolve(lib: dict, files: dict, course_id: str) -> dict:
    """The library as the client gets it: urls, credits, video titles, place names filled in."""
    url = lambda f: f"/api/courses/{course_id}/media/{f}"   # noqa: E731
    cred, places, sources, videos = files["credits"], files["places"], files["sources"], files["videos"]

    def credit(f):
        c = cred.get(f) or {}
        return {k: c.get(k) for k in ("credit", "licence", "source_url", "alt", "title")}

    def item(it):
        o = {k: it[k] for k in ("id", "kind", "title", "caption", "place", "lat", "lon") if k in it}
        if it.get("file"):
            o |= {"url": url(it["file"]), **{f"image_{k}": v for k, v in credit(it["file"]).items()}}
        if it.get("kind") == "video":
            v = videos.get(it["video"]) or {}
            o |= {"video": it["video"], "title": it.get("title") or v.get("title"), "credit": v.get("credit"),
                  "duration_s": v.get("duration_s"), "poster": f"/api/video/{it['video']}/poster"}
        p = places.get(it.get("place"))
        if p:
            o |= {"place_name": p.get("name")}
            o.setdefault("lat", p.get("lat"))
            o.setdefault("lon", p.get("lon"))
        s = sources.get(it.get("source"))
        if s:
            o["source"] = {"title": s.get("title"), "url": s.get("url")}
        return o
    return {
        "course": course_id, "title": lib.get("title") or "Library", "intro": lib.get("intro") or "",
        "home": lib.get("home"), "tour": lib.get("tour"), "chips": lib.get("chips") or [],
        "featured": lib.get("featured") or [], "moon": lib.get("moon"),
        "overlays": [{**o, "url": url(o["file"]), **credit(o["file"])} for o in lib.get("overlays") or []],
        "shelves": [{"id": sh["id"], "title": sh["title"], "by": sh.get("by") or "",
                     "items": [item(it) for it in sh.get("items") or []]} for sh in lib["shelves"]],
    }


def current() -> dict:
    """The active course's library, resolved; problems mean an empty library (the screen keeps today's look)."""
    m = courses.current()
    cid = m.get("id") or courses.DEFAULT
    lib = _read(courses.path("library", m))
    if not isinstance(lib, dict):
        return {"course": cid, "shelves": []}
    files = _course_files(m)
    errs = validate(lib, files)
    if errs:
        return {"course": cid, "shelves": [], "problems": errs[:5]}
    return resolve(lib, files, cid)


@router.get("/api/course/library")
def course_library():
    return current()
