"""Courses: one manifest per course (docs/COURSES.md §4). P1: the active course, the registry, cache reloads.

A course manifest (format `outpost-luna-course` v1) names everything a course is made of: its globe body, gazetteer,
entity registry (the ear's names lists), keyterms, lessons, missions, concepts, voice pack, the first-run assets it
needs, its standards, its reading level and its labels.

Where manifests come from (the registry, `courses()`):
  - built in: `backend/data/courses/<id>.json` (`status: "builtin"`; paths relative to backend/data). The Moon is
    course #1, always installed, never removable, and its manifest only POINTS at the files the app read before
    courses existed, so playing the Moon is byte-for-byte what it was.
  - downloaded packs (P2): `<packs>/course_<id>/course.manifest.json` (`status: "pack"`; paths relative to that folder), where
    <packs> is COURSE_PACKS_DIR, else the desktop app's assets folder (ASSETS_DIR / settings.assets_dir). A pack is the
    first-run asset `course_<id>` (desktop/assets.manifest.json, decision 6: the same Dropbox folder and catalog).
  - `status: "draft"` (a pack source left as draft) is shape-checked only, never loaded.

The active course is per computer on the backend (`<cache or data>/course_state/active.json`, or ACTIVE_COURSE_FILE)
and per call sign on the client (frontend/src/courses.js "outpost-course", a profile key): the client tells the backend
which course its cadet plays at launch (POST /api/courses/active). Switching drops every cache that holds course data
(`reload_all()`): the lessons, the gazetteer, the entity registry, the ear vocab, the keyterms, the session's tables.

What stays code (course-agnostic) and what is per course: docs/COURSES.md §4.3 and "P1: what stays per course".
"""
from __future__ import annotations

import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

DATA = Path(__file__).resolve().parents[1] / "data"
DIR = DATA / "courses"
def _assets_manifest() -> Path:
    """The first-run asset catalog. Packaged app: the desktop shell passes ASSETS_MANIFEST (its Resources copy); the
    bundle also has it at Resources/assets.manifest.json (app/backend/app/courses.py -> parents[3]). Dev checkout:
    desktop/assets.manifest.json. Before this, a packaged app looked for <Resources>/app/desktop/... (missing), so it
    listed no course packs and skipped the Moon's built-in manifest."""
    here = Path(__file__).resolve()
    env = os.environ.get("ASSETS_MANIFEST")
    for c in ([Path(env)] if env else []) + [here.parents[2] / "desktop" / "assets.manifest.json",
                                             here.parents[3] / "assets.manifest.json"]:
        if c.is_file():
            return c
    return here.parents[2] / "desktop" / "assets.manifest.json"


ASSETS_MANIFEST = _assets_manifest()
FORMAT, VERSION = "outpost-luna-course", 1
ID = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
BODIES = ("moon", "earth", "site")            # a globe (moon, earth) or a flat site map (later)
STATUSES = ("builtin", "pack", "draft")      # builtin: ships with the app; pack: an asset to download; draft: being written
FILE_KEYS = ("gazetteer", "entities", "concepts", "voice_pack", "library", "videos")   # top-level data-file pointers
# library: the course's Library screen (app/course_library.py); videos: its own NASA videos, merged into the video
# catalog while the course is active (app/video.py catalog())
DEFAULT = "moon"
REGISTERS = ("kid", "teen")
BUDGET_KEYS = ("prompt", "title", "hint", "success", "fail", "reveal")
# The Moon's reading level (docs/COPY.md): what a course without `reading_level` gets, and what moon.json states.
DEFAULT_LEVEL = {"grades": "3-8", "register": "kid",
                 "budgets": {"prompt": 20, "title": 6, "hint": 12, "success": 12, "fail": 8, "reveal": 20}}
DEFAULT_LABELS = {"course": "Moon", "school": "Flight School", "lessons": "Lessons", "patches": "NASA patches",
                  "patch": "patch"}
LABEL_KEYS = tuple(DEFAULT_LABELS)
PACK_FILE = "course.manifest.json"   # not course.json: a course folder keeps its lessons in that name

router = APIRouter()
_LOCK = threading.Lock()


def asset_ids(manifest: Path = ASSETS_MANIFEST) -> set[str]:
    """The first-run asset ids the desktop manifest knows (empty when the file is missing, e.g. the iPad bundle)."""
    try:
        return {a["id"] for a in json.loads(manifest.read_text())["assets"]}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _files(m: dict) -> list[tuple[str, str]]:
    """(where, relative path) of every data file a manifest points at."""
    out = [(k, m[k]) for k in FILE_KEYS if isinstance(m.get(k), str)]
    if isinstance(m.get("ear"), dict) and isinstance(m["ear"].get("vocab"), str):
        out.append(("ear.vocab", m["ear"]["vocab"]))
    if isinstance(m.get("lessons"), dict) and isinstance(m["lessons"].get("source"), str):
        out.append(("lessons.source", m["lessons"]["source"]))
    if isinstance(m.get("missions"), dict) and isinstance(m["missions"].get("sites"), str):
        out.append(("missions.sites", m["missions"]["sites"]))
    return out


def _check_level(m: dict, err) -> None:
    rl = m.get("reading_level")
    if rl is None:
        return
    if not isinstance(rl, dict):
        return err("reading_level", "{grades, register, budgets}.")
    if rl.get("register") not in REGISTERS:
        err("reading_level.register", f"One of {', '.join(REGISTERS)}.")
    b = rl.get("budgets", {})
    if not isinstance(b, dict) or any(k not in BUDGET_KEYS or not isinstance(v, int) or not 1 <= v <= 60
                                      for k, v in b.items()):
        err("reading_level.budgets", f"Words per line, 1-60, for {', '.join(BUDGET_KEYS)}.")


def validate(m: dict, data: Path = DATA, known_assets: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """-> (errors [{at, msg}], planned files). A draft's missing files are `planned`, not errors."""
    errs: list[dict] = []
    err = lambda at, msg: errs.append({"at": at, "msg": msg})   # noqa: E731
    if not isinstance(m, dict):
        return [{"at": "", "msg": "A course manifest is a JSON object."}], []
    if m.get("format") != FORMAT or m.get("version") != VERSION:
        err("format", f'Expected format "{FORMAT}", version {VERSION}.')
    if not isinstance(m.get("id"), str) or not ID.match(m["id"]):
        err("id", "2-24 characters: a-z, 0-9 and -, starting with a letter.")
    if not isinstance(m.get("title"), str) or not (0 < len(m["title"]) <= 32):
        err("title", "1-32 characters.")
    status = m.get("status")
    if status not in STATUSES:
        err("status", f"One of {', '.join(STATUSES)}.")
    g = m.get("globe")
    if not isinstance(g, dict) or g.get("body") not in BODIES:
        err("globe.body", f"One of {', '.join(BODIES)}.")
    elif g.get("body") != "site" and not (isinstance(g.get("km"), (int, float)) and g["km"] > 0):
        err("globe.km", "The body's radius in km.")
    les = m.get("lessons")
    if not isinstance(les, dict) or not isinstance(les.get("source"), str):
        err("lessons.source", "The lesson file, relative to backend/data.")
    elif not isinstance(les.get("ids"), list) or len(set(les["ids"])) != len(les["ids"]):
        err("lessons.ids", "The lesson ids in order, each once.")
    a = m.get("assets")
    if not isinstance(a, dict) or not all(isinstance(a.get(k, []), list) for k in ("required", "optional")):
        err("assets", "{required: [asset ids], optional: [asset ids]}.")
    elif known_assets is not None and status != "draft":
        for k in ("required", "optional"):
            for i, x in enumerate(a.get(k, [])):
                if x not in known_assets:
                    err(f"assets.{k}[{i}]", f"{x}: not in desktop/assets.manifest.json.")
    _check_level(m, err)
    if "labels" in m and not (isinstance(m["labels"], dict) and all(
            k in LABEL_KEYS and isinstance(v, str) and 0 < len(v) <= 24 for k, v in m["labels"].items())):
        err("labels", f"Short words (1-24 characters) for {', '.join(LABEL_KEYS)}.")
    ear = m.get("ear")
    if isinstance(ear, dict) and "keyterms" in ear and not (
            isinstance(ear["keyterms"], list) and all(isinstance(t, str) and 0 < len(t) <= 40 for t in ear["keyterms"])
            and len(ear["keyterms"]) <= 100):
        err("ear.keyterms", "Up to 100 names, each 1-40 characters.")
    planned = []
    for at, rel in _files(m):
        p = (data / rel).resolve()
        if data.resolve() not in p.parents:
            err(at, "A path inside backend/data." if data == DATA else "A path inside the course pack.")
        elif at == "voice_pack" and data == DATA:
            pass   # the built-in voice pack is a first-run asset (VOICE_PACK_DIR), not shipped in backend/data
        elif not p.exists():
            (planned.append(rel) if status == "draft" else err(at, f"{rel}: no such file."))
    if not errs and status != "draft" and isinstance(les, dict) and les["source"].endswith(".json"):
        try:
            have = [l["id"] for l in json.loads((data / les["source"]).read_text())["lessons"]]
        except (OSError, ValueError, KeyError, TypeError):
            have = None
        if have is not None and have != les["ids"]:
            err("lessons.ids", f"Must match {les['source']} in order: {have}.")
    return errs, planned


def to_pack(m: dict) -> tuple[dict, str]:
    """A pack's source manifest (paths relative to backend/data, all under courses/<id>/) -> (the manifest the pack
    carries, paths relative to the pack folder; the source folder "courses/<id>"). Pure; scripts/asset_pack.py uses it.
    Raises ValueError for a path outside the course's own folder."""
    base = f"courses/{m['id']}/"

    def rel(at: str, p: str) -> str:
        if not p.startswith(base) or ".." in p.split("/"):
            raise ValueError(f"{at}: {p} is outside {base}")
        return p[len(base):]
    out = json.loads(json.dumps({k: v for k, v in m.items() if not k.startswith("_")}))
    out["status"] = "pack"
    for k in FILE_KEYS:
        if isinstance(out.get(k), str):
            out[k] = rel(k, out[k])
    for k, sub in (("ear", "vocab"), ("lessons", "source"), ("missions", "sites")):
        if isinstance(out.get(k), dict) and isinstance(out[k].get(sub), str):
            out[k][sub] = rel(f"{k}.{sub}", out[k][sub])
    return out, base.rstrip("/")


# ------------------------------------------------------------------------------------------- where things live
def packs_dir() -> Path | None:
    """Where downloaded course packs are installed (`<dir>/course_<id>/course.manifest.json`), or None (a dev checkout)."""
    env = os.environ.get("COURSE_PACKS_DIR") or os.environ.get("ASSETS_DIR")
    if env:
        return Path(env)
    try:
        from .config import settings
        return settings.assets_dir
    except Exception:   # noqa: BLE001
        return None


def state_file() -> Path:
    """The per-computer active-course file (next to the class packs and the auto-save)."""
    env = os.environ.get("ACTIVE_COURSE_FILE")
    if env:
        return Path(env)
    from .config import settings
    return (settings.cache_dir or settings.data_dir) / "course_state" / "active.json"


def root(m: dict) -> Path:
    """The folder a manifest's relative paths start from: backend/data for built-ins, the pack folder for packs."""
    return Path(m["_root"]) if m.get("_root") else DATA


# ------------------------------------------------------------------------------------------- the registry
@lru_cache(maxsize=1)
def courses() -> tuple[dict, ...]:
    """Every valid course, built-ins first, then installed packs. A broken one is skipped (problems()), never raised."""
    out: list[dict] = []
    _PROBLEMS.clear()
    known = asset_ids()

    def add(m: dict, where: str, data: Path, want_status: tuple[str, ...]) -> None:
        # built-ins name only assets the catalog has; a pack (or a pack's source) names its own, which the catalog
        # gets when the pack is built and uploaded
        builtin = data == DATA and m.get("status") == "builtin"
        errs, _ = validate(m, data=data, known_assets=(known or None) if builtin else None)
        if not errs and m.get("status") not in want_status:
            errs = [{"at": "status", "msg": f"Expected {' or '.join(want_status)} here."}]
        if errs:
            _PROBLEMS.append(f"{where}: skipped. {errs[0]['at']}: {errs[0]['msg']}")
        elif any(c["id"] == m["id"] for c in out):
            _PROBLEMS.append(f"{where}: skipped. {m['id']}: another course has this id.")
        else:
            out.append(m if data == DATA else {**m, "_root": str(data)})

    dev = os.environ.get("OUTPOST_DEV_COURSE", "")
    for f in sorted(DIR.glob("*.json")) if DIR.is_dir() else []:
        try:
            m = json.loads(f.read_text())
        except (OSError, ValueError) as e:
            _PROBLEMS.append(f"{f.name}: skipped. {e}")
            continue
        if isinstance(m, dict) and m.get("status") == "pack":
            # a pack's SOURCE in the repo (backend/data/courses/<id>.json + courses/<id>/): what scripts/asset_pack.py
            # builds the course_<id> asset from. Not installed in the app; played from source only with
            # OUTPOST_DEV_COURSE=<id> (the content author's dev loop).
            if m.get("id") == dev:
                add(m, f.name, DATA, ("pack",))
            continue
        add(m, f.name, DATA, ("builtin",))
    pd = packs_dir()
    for f in sorted(pd.glob(f"course_*/{PACK_FILE}")) if pd and pd.is_dir() else []:
        where = f"{f.parent.name}/{PACK_FILE}"
        try:
            m = json.loads(f.read_text())
        except (OSError, ValueError) as e:
            _PROBLEMS.append(f"{where}: skipped. {e}")
            continue
        if isinstance(m, dict) and f.parent.name != f"course_{m.get('id')}":
            _PROBLEMS.append(f"{where}: skipped. id: the folder must be course_{m.get('id')}.")
            continue
        add(m, where, f.parent, ("pack",))
    return tuple(out)


_PROBLEMS: list[str] = []


def problems() -> list[str]:
    courses()
    return list(_PROBLEMS)


def get(course_id: str) -> dict | None:
    return next((c for c in courses() if c["id"] == course_id), None)


def _read_state() -> str:
    try:
        v = json.loads(state_file().read_text()).get("active")
        return v if isinstance(v, str) else DEFAULT
    except (OSError, ValueError, AttributeError):
        return DEFAULT


def active() -> str:
    """The course the app plays on this computer: the stored choice while it is installed, else the Moon."""
    dev = os.environ.get("OUTPOST_DEV_COURSE", "")
    if dev and dev != DEFAULT and get(dev) is not None:
        return dev                                   # the author's dev loop plays its course from source
    c = _read_state()
    return c if get(c) is not None else DEFAULT


def current() -> dict:
    """The active course's manifest (the Moon's if anything is off: the Moon always loads)."""
    return get(active()) or get(DEFAULT) or json.loads((DIR / f"{DEFAULT}.json").read_text())


def path(key: str, m: dict | None = None) -> Path | None:
    """The active (or given) course's data file for a manifest key: gazetteer, entities, concepts, voice_pack, library,
    videos, ear.vocab, lessons.source, missions.sites. None when the course has none."""
    m = m or current()
    rel = dict(_files(m)).get(key)
    if key == "voice_pack" and rel and root(m) == DATA:   # the built-in pack lives where the app installed it
        from .config import settings
        return settings.voice_pack() / Path(rel).name
    return root(m) / rel if rel else None


def reading_level(m: dict | None = None) -> dict:
    """{grades, register, budgets}: the course's copy budgets and voice register (decision 2). Defaults: the Moon's."""
    rl = (m or current()).get("reading_level") or {}
    return {"grades": rl.get("grades", DEFAULT_LEVEL["grades"]), "register": rl.get("register", DEFAULT_LEVEL["register"]),
            "budgets": {**DEFAULT_LEVEL["budgets"], **(rl.get("budgets") or {})}}


def budget(field: str, m: dict | None = None) -> int:
    return reading_level(m)["budgets"][field]


def labels(m: dict | None = None) -> dict:
    return {**DEFAULT_LABELS, **((m or current()).get("labels") or {})}


def keyterms(m: dict | None = None) -> list[str] | None:
    """The course's own Deepgram / ear keyterms, or None: the Moon keeps app/keyterms.py's lunar lists."""
    ear = (m or current()).get("ear") or {}
    return list(ear["keyterms"]) if isinstance(ear.get("keyterms"), list) else None


def line(key: str, default: str) -> str:
    """A per-course content line for the rules Director (manifest `lines`): the Moon has none, so its lines are the
    ones in code (app/director.py), unchanged."""
    v = ((current().get("lines") or {}).get(key))
    return v if isinstance(v, str) and v.strip() else default


def is_moon() -> bool:
    return active() == DEFAULT


# ------------------------------------------------------------------------------------------- switching
_HOOKS: list = []


def on_change(fn) -> None:
    """Run fn() after every course switch (main.py rebuilds its gazetteer this way: no import cycle)."""
    if fn not in _HOOKS:
        _HOOKS.append(fn)


def reload_all() -> None:
    """Drop every cache that holds course data, together (docs/COURSES.md §6 risk 2)."""
    courses.cache_clear()
    from . import entities, hotlist, listen, session
    from .academy import content, grade
    content.nasa_course.cache_clear()
    content.reload()                     # course(), hotlist lesson titles, the session's lesson table
    entities.registry.cache_clear()
    hotlist.vocab.cache_clear()
    listen.keyterms.cache_clear()
    grade.gaz.cache_clear()
    grade._sites.cache_clear()
    session._CACHE.clear()
    try:
        from .academy import classpacks
        classpacks.reload()
    except Exception:   # noqa: BLE001
        pass
    for fn in list(_HOOKS):
        try:
            fn()
        except Exception:   # noqa: BLE001  (a hook never blocks a switch)
            pass


def set_active(course_id: str) -> str:
    """Make an installed course the active one (atomic write), then reload. Raises KeyError for an unknown course."""
    courses.cache_clear()
    if get(course_id) is None:
        raise KeyError(course_id)
    with _LOCK:
        changed = _read_state() != course_id or active() != course_id
        f = state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"active": course_id}))
        os.replace(tmp, f)
    if changed:
        reload_all()
    return course_id


def summary(m: dict) -> dict:
    return {k: m.get(k) for k in ("id", "title", "program", "status", "subject", "grades")} | {
        "globe": {k: m["globe"].get(k) for k in ("body", "name", "km", "map")},
        "lessons": len(m["lessons"]["ids"]), "assets": m["assets"],
        "reading_level": reading_level(m), "labels": labels(m), "standards": m.get("standards") or [],
        "big_ideas": m.get("big_ideas") or {}, "missions": (m.get("missions") or {}).get("kind"),
        "removable": m.get("status") == "pack"}


@router.get("/api/courses")
def list_courses():
    courses.cache_clear()     # a pack may have been installed or removed since (the desktop app writes the folder)
    return {"active": active(), "courses": [summary(c) for c in courses()], "problems": problems()}


class Pick(BaseModel):
    id: str


@router.post("/api/courses/active")
def pick_course(p: Pick):
    try:
        set_active(p.id)
    except KeyError:
        raise HTTPException(404, "That course is not on this computer.")
    return {"active": active()}


MEDIA_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,80}\.(?:jpg|png|json)$")
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "json": "application/json"}


def media_dir(course_id: str) -> Path | None:
    """A course's media folder (its Earth map, hillshades, photos): `<pack>/media` for an installed pack, and
    backend/data/courses/<id>/media for a pack's source in the repo (the content author's dev loop)."""
    m = get(course_id)
    if m is not None and m.get("_root"):
        return Path(m["_root"]) / "media"
    return DIR / course_id / "media" if ID.match(course_id) else None


@router.get("/api/courses/{course_id}/media/{name}")
def course_media(course_id: str, name: str):
    """A course's pictures and data files: one flat folder, names checked, read-only."""
    d = media_dir(course_id) if ID.match(course_id) else None
    if d is None or not MEDIA_NAME.match(name):
        raise HTTPException(404, "no such file")
    p = d / name
    if not p.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(p, media_type=MEDIA_TYPES[name.rsplit(".", 1)[1]],
                        headers={"Cache-Control": "public, max-age=86400"})
