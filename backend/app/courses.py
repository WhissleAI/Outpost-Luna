"""Courses: one manifest per course (docs/COURSES.md §4). Spike / P0: read-only, zero behaviour change.

A course manifest (`backend/data/courses/<id>.json`, format `outpost-luna-course` v1) names everything a course is made
of: its globe body, gazetteer, entity registry (the ear's names lists), lessons, missions, concepts, voice pack, the
first-run assets it needs, and its standards. Today the Moon is the only course and its manifest only POINTS at the
files the app already reads (academy/content.py, gazetteer.py, entities/, mission/), so nothing changes when it loads.
`GET /api/courses` lists the courses; no client calls it yet (P1 adds the switcher).

A course that is still being written (`status: "draft"`, e.g. docs/courses/archaeology/course.manifest.json) is checked
for shape only: its data files may not exist yet, and they are listed as `planned`.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

DATA = Path(__file__).resolve().parents[1] / "data"
DIR = DATA / "courses"
ASSETS_MANIFEST = Path(__file__).resolve().parents[2] / "desktop" / "assets.manifest.json"
FORMAT, VERSION = "outpost-luna-course", 1
ID = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
BODIES = ("moon", "earth", "site")            # a globe (moon, earth) or a flat site map (later)
STATUSES = ("builtin", "pack", "draft")      # builtin: ships with the app; pack: an asset to download; draft: being written
FILE_KEYS = ("gazetteer", "entities", "concepts", "voice_pack")   # top-level data-file pointers
DEFAULT = "moon"

router = APIRouter()


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
    planned = []
    for at, rel in _files(m):
        p = (data / rel).resolve()
        if data.resolve() not in p.parents:
            err(at, "A path inside backend/data.")
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


@lru_cache(maxsize=1)
def courses() -> tuple[dict, ...]:
    """Every valid course manifest in backend/data/courses, by id. A broken one is skipped (problems()), never raised."""
    out: list[dict] = []
    _PROBLEMS.clear()
    known = asset_ids()
    for f in sorted(DIR.glob("*.json")) if DIR.is_dir() else []:
        try:
            m = json.loads(f.read_text())
        except (OSError, ValueError) as e:
            _PROBLEMS.append(f"{f.name}: skipped. {e}")
            continue
        errs, _ = validate(m, known_assets=known or None)
        if errs:
            _PROBLEMS.append(f"{f.name}: skipped. {errs[0]['at']}: {errs[0]['msg']}")
        elif any(c["id"] == m["id"] for c in out):
            _PROBLEMS.append(f"{f.name}: skipped. {m['id']}: another course has this id.")
        else:
            out.append(m)
    return tuple(out)


_PROBLEMS: list[str] = []


def problems() -> list[str]:
    courses()
    return list(_PROBLEMS)


def get(course_id: str) -> dict | None:
    return next((c for c in courses() if c["id"] == course_id), None)


def active() -> str:
    """The course the app plays. Spike: always the Moon (P1 stores the choice per computer)."""
    return DEFAULT


def summary(m: dict) -> dict:
    return {k: m.get(k) for k in ("id", "title", "program", "status", "subject", "grades")} | {
        "globe": {k: m["globe"].get(k) for k in ("body", "name", "km", "map")},
        "lessons": len(m["lessons"]["ids"]), "assets": m["assets"]}


@router.get("/api/courses")
def list_courses():
    return {"active": active(), "courses": [summary(c) for c in courses()], "problems": problems()}
