"""Concepts below the lesson (D5, docs/BRAIN.md §11): which concept each graded step practises, per course.

The map is data (backend/data/learning/step_concepts.json), so a course edit never needs code. Every graded attempt's
reply carries the step's concept id (academy/routes.py `_out`), and the client counts it per cadet and schedules its
spaced review (frontend/src/brain_store.js). Ids follow the client's lesson-id rule: bare on the Moon ("maria"),
"<course>:<id>" elsewhere ("archaeology:stratigraphy"), so two courses never share a concept.

    GET /api/academy/concepts   the active course's concepts: {course, concepts: {id: {label, lesson, step, mission}}}
                                (`lesson` and `step`: where its review opens, the first step that practises it)
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import settings

MOON = "moon"


@lru_cache(maxsize=1)
def table() -> dict:
    try:
        return json.loads((settings.data_dir / "learning" / "step_concepts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"courses": {}}


def _split(lesson_id: str) -> tuple[str, str]:
    """'archaeology:layers' -> ('archaeology', 'layers'); 'phases' -> ('moon', 'phases')."""
    c, sep, rest = str(lesson_id or "").partition(":")
    return (c, rest) if sep else (MOON, c)


def key(course: str, concept: str) -> str:
    return concept if course == MOON else f"{course}:{concept}"


def concept_of(lesson_id: str, step: int | None) -> str | None:
    """The concept a graded step practises, as the client's id, or None (an ungraded step, a Class lesson, a course
    with no map)."""
    course, lid = _split(lesson_id)
    c = (table().get("courses") or {}).get(course) or {}
    cid = ((c.get("steps") or {}).get(lid) or {}).get(str(step)) if step is not None else None
    return key(course, cid) if cid and cid in (c.get("concepts") or {}) else None


def public(course: str = MOON) -> dict:
    """One course's concepts for the client: label, the lesson (client id) and step its review opens, mission flag."""
    c = (table().get("courses") or {}).get(course) or {}
    first: dict[str, tuple[str, int]] = {}
    for lid, steps in (c.get("steps") or {}).items():
        for s, cid in sorted(steps.items(), key=lambda kv: int(kv[0])):
            first.setdefault(cid, (lid, int(s)))
    out = {}
    for cid, meta in (c.get("concepts") or {}).items():
        lid, s = first.get(cid, (meta.get("lesson"), 0))
        out[key(course, cid)] = {"label": meta.get("label") or cid, "lesson": lid if course == MOON else f"{course}:{lid}",
                                 "step": s, "mission": bool(meta.get("mission"))}
    return {"course": course, "concepts": out}
