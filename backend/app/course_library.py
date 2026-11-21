"""The course Library (docs/COURSES.md "Course library"): what a non-Moon course shows on its Library screen.

The Moon's Library is built from code and its own assets (hardware, crew audio, the nasa_views pack). Another course
names a library file in its manifest (`library`, e.g. courses/archaeology/library.json) and its own videos (`videos`,
merged into the video catalog by app/video.py while the course is active). The library is shelves of items:

  image  a picture in the course's media/ folder, credited in media/credits.json (credit, licence, source_url, alt)
  video  an id in the course's videos.json (played by the app's NASA video player, frontend/src/media/video.js)
  place  a gazetteer place (places.json): the globe flies there
  chart  a small time series in media/ (`file`: an outpost-luna-chart .json, or a .csv whose first column is x), drawn
         by the client as an accessible SVG line or bar chart (frontend/src/media/chart.js) with optional annotated
         `bands` [{from, to, label}], `x_label` / `y_label`, `chart_type` (line | bar) and a `summary` (its text
         alternative; required)
  model  a .glb in media/, shown in the app's three.js turntable (frontend/src/media/turntable.js)
  layer  a .png in media/ draped on the globe between `bounds` (an equirectangular picture, toggled from its card),
         with a `legend` [{color: "#rrggbb", label}] and an optional `opacity`

Every file an item or overlay names is credited in media/credits.json: credit, licence, an https source_url, alt and a
`licence_class` (licence_problem: pd | cc0 | by | by-sa, and by-sa only unmodified, `modified: false`). Anything else
(nc, nd, unknown, missing) is rejected here and when the pack is built (scripts/asset_pack.py src_course).

Any item may name a `place` (gazetteer id) or its own `lat`/`lon` (a marker on the globe), and a `source` (an id in
the course's sources.json, the checked quotes). `overlays` drape a media picture over the globe between its bounds
(an equirectangular lat/lon image), `tour` lists gazetteer stops, `chips` are the askbar's shortcuts, `featured` the item ids the Field School map's
"Real views" ribbon shows, `home` where the Library's camera starts, `moon` the context Moon in Earth's sky (its line,
a place and an item to go to; no `moon`, no Moon in the sky).

`docs` ([0.5.6], the owner's playtest of 0.5.5: the NPS rack card was a dead link) are documents a lesson cites, kept in
the pack so they open in the app, offline: {id, url (the web address the course's sources cite), title, by, pdf (the
original file, kept as it was), pages: [{file, alt}] (each page rendered to a picture, shown in the app's picture
viewer)}. Every file credited like any other media (licence_class pd | cc0 | by | by-sa). A link to `url` anywhere in the
app opens the pages (frontend/src/links.js); the rest of the web opens in the system browser.

`layers` (docs/OPEN_DATA.md) are whole-globe maps the Library can show in place of the body's own: each a media picture
(equirectangular, -180..180, 2:1) with a title, a line to say, a legend ([{color: "#rrggbb", label, note?}]) and a
`source`. The Moon has layers and no shelves (its Library is built from code); a library needs shelves or layers.

Routes
  GET /api/course/library   the active course's library, every item resolved (url, credit, video, place, layers), or
                            {"course": id, "shelves": []} for a course without one. The Moon's has layers only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter

from . import courses

router = APIRouter()
FORMAT, VERSION = "outpost-luna-library", 1
KINDS = ("image", "video", "place", "chart", "model", "layer")
# which media files each kind may name (course media: one flat folder, app/courses.py MEDIA_NAME)
FILE_EXT = {"image": (".jpg", ".png"), "chart": (".json", ".csv"), "model": (".glb",), "layer": (".png",)}
# licences a possibly-commercial app may ship: public domain, CC0, attribution, share-alike (unmodified only)
LICENCE_CLASSES = ("pd", "cc0", "by", "by-sa")
NC_ND = re.compile(r"non-?commercial|no-?deriv|\bby-nc\b|\bby-nd\b|\bnc-|-nc\b|-nd\b", re.I)
CHART_FORMAT = "outpost-luna-chart"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
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


def licence_problem(c) -> str | None:
    """Why a credits.json entry may not ship (None = fine): its licence_class must be one we can use commercially."""
    if not isinstance(c, dict):
        return "not an object"
    lc = str(c.get("licence_class") or "").strip().lower()
    if not lc:
        return "licence_class missing (pd | cc0 | by | by-sa)"
    if lc not in LICENCE_CLASSES:
        return f"licence_class {lc!r} cannot ship (only {', '.join(LICENCE_CLASSES)}; never nc, nd or unknown)"
    if NC_ND.search(str(c.get("licence") or "")):
        return "the licence text names a non-commercial or no-derivatives term"
    if lc == "by-sa" and c.get("modified") is not False:
        return "by-sa media ships only unmodified (modified: false)"
    return None


def licence_problems(credits) -> list[str]:
    """Every entry of a credits.json list checked (the build-time gate: scripts/asset_pack.py src_course)."""
    if not isinstance(credits, list):
        return ["media/credits.json must be a list"]
    out = []
    for c in credits:
        why = licence_problem(c)
        if why:
            out.append(f"media/credits.json {c.get('file') if isinstance(c, dict) else c!r}: {why}")
    return out


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def parse_chart(text: str, name: str) -> dict:
    """A chart file -> {series: [{label, points: [[x, y], ...]}], ...}. Raises ValueError. The client reads the same
    two shapes (frontend/src/media/chart.js parseChart): an outpost-luna-chart JSON, or a CSV (header: x, then one
    column per series; empty or NA cells skipped; # lines are comments)."""
    if name.endswith(".csv"):
        rows = [r.split(",") for r in text.strip().splitlines() if r.strip() and not r.startswith("#")]
        if len(rows) < 3 or len(rows[0]) < 2:
            raise ValueError("a chart CSV needs a header (x, then one column per series) and at least two rows")
        head = [h.strip() for h in rows[0]]
        series = [{"label": h, "points": []} for h in head[1:]]
        for r in rows[1:]:
            x = _num(r[0])
            if x is None:
                raise ValueError(f"x {r[0]!r} is not a number")
            for k, s in enumerate(series):
                cell = r[k + 1].strip() if k + 1 < len(r) else ""
                if cell in ("", "NA"):
                    continue
                y = _num(cell)
                if y is None:
                    raise ValueError(f"{cell!r} is not a number")
                s["points"].append([x, y])
        d = {"series": series, "x_label": head[0]}
    else:
        d = json.loads(text)
        if not isinstance(d, dict) or d.get("format") != CHART_FORMAT:
            raise ValueError(f'a chart JSON must say "format": "{CHART_FORMAT}"')
        series = d.get("series")
        if not isinstance(series, list):
            raise ValueError("series must be a list")
        for s in series:
            pts = s.get("points") if isinstance(s, dict) else None
            if not isinstance(pts, list) or not all(isinstance(p, list) and len(p) == 2 and _num(p[0]) is not None
                                                    and _num(p[1]) is not None for p in pts):
                raise ValueError("every series needs points [[x, y], ...] of numbers")
    if not 1 <= len(series) <= 6:
        raise ValueError("a chart has 1 to 6 series")
    for s in series:
        if not s.get("label"):
            raise ValueError("every series needs a label")
        xs = [p[0] for p in s["points"]]
        if not 2 <= len(xs) <= 5000:
            raise ValueError(f"series {s['label']!r}: 2 to 5000 points")
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise ValueError(f"series {s['label']!r}: x must increase")
    return d


def _bands_ok(bands) -> bool:
    return bands is None or (isinstance(bands, list) and len(bands) <= 4 and all(
        isinstance(b, dict) and _num(b.get("from")) is not None and _num(b.get("to")) is not None
        and b["from"] < b["to"] and isinstance(b.get("label"), str) and 0 < len(b["label"]) <= 60 for b in bands))


def _bounds_ok(b, most: float) -> bool:
    return (isinstance(b, dict) and _ll_ok(b.get("south"), b.get("west")) and _ll_ok(b.get("north"), b.get("east"))
            and b["south"] < b["north"] and b["west"] < b["east"] and b["east"] - b["west"] <= most * 2
            and b["north"] - b["south"] <= most)


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
        elif licence_problem(cred[f]):
            out.append(f"{at}: {f}: {licence_problem(cred[f])}")
    docs = lib.get("docs")
    if docs is not None and not isinstance(docs, list):
        out.append("docs: a list")
    dseen, durls = set(), set()
    for k, d in enumerate(docs if isinstance(docs, list) else []):
        at = f"docs[{k}]"
        if not isinstance(d, dict) or not ID.match(str(d.get("id", ""))) or d["id"] in dseen:
            out.append(f"{at}: needs a unique lower_snake_case id")
            continue
        dseen.add(d["id"])
        u = str(d.get("url") or "")
        if not u.startswith("https://") or u in durls:
            out.append(f"{at}: needs the https url its sources cite (once)")
        durls.add(u)
        if not d.get("title"):
            out.append(f"{at}: needs a title")
        pages = d.get("pages")
        if not isinstance(pages, list) or not pages or len(pages) > 40:
            out.append(f"{at}: pages: 1-40 pictures [{{file, alt}}]")
            pages = []
        for j, pg in enumerate(pages):
            f = pg.get("file") if isinstance(pg, dict) else None
            if not isinstance(f, str) or not f.endswith((".jpg", ".png")):
                out.append(f"{at}.pages[{j}]: a .jpg or .png")
            else:
                need_file(f"{at}.pages[{j}]", f)
        if d.get("pdf") is not None:
            if not str(d["pdf"]).endswith(".pdf"):
                out.append(f"{at}: pdf: the original .pdf")
            else:
                need_file(f"{at}.pdf", d["pdf"])
    layers = lib.get("layers")
    if layers is not None and (not isinstance(layers, list) or not layers):
        out.append("layers: a non-empty list")
    lseen = set()
    for k, ly in enumerate(layers if isinstance(layers, list) else []):
        at = f"layers[{k}]"
        if not isinstance(ly, dict) or not ID.match(str(ly.get("id", ""))) or ly["id"] in lseen or ly["id"] == "photo":
            out.append(f"{at}: needs a unique lower_snake_case id (not 'photo', the body's own map)")
            continue
        lseen.add(ly["id"])
        if not ly.get("title") or not ly.get("say"):
            out.append(f"{at}: needs a title and a line to say")
        need_file(at, ly.get("file"))
        cr = cred.get(ly.get("file")) or {}
        if cr.get("width") and cr.get("height") and cr["width"] != 2 * cr["height"]:
            out.append(f"{at}: a whole-globe map is twice as wide as it is tall (equirectangular)")
        leg = ly.get("legend")
        if not isinstance(leg, list) or not leg or not all(
                isinstance(x, dict) and HEX.match(str(x.get("color", ""))) and x.get("label") for x in leg):
            out.append(f"{at}: legend is a list of {{color: '#rrggbb', label, note?}}")
        if ly.get("source") not in sources:
            out.append(f"{at}: source {ly.get('source')!r} is not in sources.json")
    has_layers = isinstance(layers, list) and bool(layers)
    shelves = lib.get("shelves")
    if shelves is None and has_layers:
        shelves = []
    if not isinstance(shelves, list) or (not shelves and not has_layers):
        return out + ["library: shelves must be a non-empty list (or give layers)"]
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
            if kind in FILE_EXT:
                f = it.get("file")
                if not (isinstance(f, str) and f.endswith(FILE_EXT[kind])):
                    out.append(f"{at}: a {kind} names a {' / '.join(FILE_EXT[kind])} file")
                else:
                    need_file(at, f)
            if kind == "chart":
                if not (isinstance(it.get("summary"), str) and 20 <= len(it["summary"]) <= 400):
                    out.append(f"{at}: a chart needs a summary (its text alternative, 20-400 characters)")
                if not _bands_ok(it.get("bands")):
                    out.append(f"{at}: bands must be [{{from, to, label}}] (from < to, at most 4)")
                if it.get("chart_type", "line") not in ("line", "bar"):
                    out.append(f"{at}: chart_type must be line or bar")
                p = files["media"] / str(it.get("file"))
                if isinstance(it.get("file"), str) and p.is_file():
                    try:
                        parse_chart(p.read_text(encoding="utf-8"), p.name)
                    except (ValueError, OSError) as e:
                        out.append(f"{at}: media/{p.name}: {e}")
            if kind == "layer":
                if not _bounds_ok(it.get("bounds"), 180):
                    out.append(f"{at}: a layer needs bounds {{west, south, east, north}} (degrees)")
                lg = it.get("legend")
                if not (isinstance(lg, list) and 1 <= len(lg) <= 8 and all(
                        isinstance(x, dict) and HEX.match(str(x.get("color", ""))) and x.get("label") for x in lg)):
                    out.append(f"{at}: a layer needs a legend [{{color: '#rrggbb', label}}] (1-8 entries)")
                op = it.get("opacity", 1)
                if not (isinstance(op, (int, float)) and not isinstance(op, bool) and 0.2 <= op <= 1):
                    out.append(f"{at}: opacity must be 0.2-1")
            if kind == "video" and it.get("video") not in videos:
                out.append(f"{at}: video {it.get('video')!r} is not in the course's videos.json")
            if kind == "place" and it.get("place") not in places:
                out.append(f"{at}: place {it.get('place')!r} is not in the gazetteer")
            if "label" in it and not (isinstance(it["label"], str) and 0 < len(it["label"]) <= 20):
                out.append(f"{at}: label is a short word for what the picture is (a chart), at most 20 characters")
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
        o = {k: it[k] for k in ("id", "kind", "title", "caption", "label", "place", "lat", "lon", "summary", "bands", "x_label",
                                "y_label", "chart_type", "note", "bounds", "legend", "opacity") if k in it}
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
    def layer(ly):
        o = {"url": url(ly["file"]), **{("map_title" if k == "title" else k): v for k, v in credit(ly["file"]).items()}}
        o |= {k: ly[k] for k in ("id", "title", "say", "legend") if k in ly}   # the layer's short title, not the file's
        s = sources.get(ly.get("source"))
        if s:
            o["source"] = {"title": s.get("title"), "url": s.get("url")}
        return o

    def doc(d):
        first = credit(d["pages"][0]["file"])
        return {"id": d["id"], "url": d["url"], "title": d["title"], "by": d.get("by") or "",
                "credit": first.get("credit"), "licence": first.get("licence"),
                "pages": [{"url": url(pg["file"]), "alt": pg.get("alt") or credit(pg["file"]).get("alt") or ""} for pg in d["pages"]]}

    return {
        "course": course_id, "title": lib.get("title") or "Library", "intro": lib.get("intro") or "",
        "home": lib.get("home"), "tour": lib.get("tour"), "chips": lib.get("chips") or [],
        "featured": lib.get("featured") or [], "moon": lib.get("moon"),
        "overlays": [{**o, "url": url(o["file"]), **credit(o["file"])} for o in lib.get("overlays") or []],
        "shelves": [{"id": sh["id"], "title": sh["title"], "by": sh.get("by") or "",
                     "items": [item(it) for it in sh.get("items") or []]} for sh in lib.get("shelves") or []],
        "layers": [layer(ly) for ly in lib.get("layers") or []],
        "docs": [doc(d) for d in lib.get("docs") or []],
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
