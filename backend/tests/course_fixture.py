"""A tiny downloaded course pack for tests (docs/COURSES.md §4.2): `<packs>/course_<id>/course.json` + its data files.

It borrows two Moon lessons and the Moon's places so the lesson engine has real steps to grade, but it is its own
course: an Earth globe, its own lesson file, its own entity registry and keyterms, and a teen reading level.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app import courses

DATA = courses.DATA


def make_pack(packs: Path, cid: str = "testland", title: str = "Testland", lessons: tuple[str, ...] = ("moon", "phases"),
              **over) -> Path:
    d = packs / f"course_{cid}"
    d.mkdir(parents=True, exist_ok=True)
    moon = json.loads((DATA / "academy" / "course.json").read_text())
    les = [l for l in moon["lessons"] if l["id"] in lessons]
    (d / "lessons.json").write_text(json.dumps({**{k: v for k, v in moon.items() if k != "lessons"}, "lessons": les}))
    shutil.copy(DATA / "places.json", d / "places.json")
    shutil.copy(DATA / "artifacts.json", d / "artifacts.json")
    reg = json.loads((DATA / "entities" / "outpost_luna.json").read_text())
    reg["entities"] = [{"id": "mesa_verde", "type": "place", "group": "place", "name": "Mesa Verde", "kind": "site",
                        "aliases": ["Mesa Verde National Park"]}] + reg["entities"][:5]
    (d / "entities.json").write_text(json.dumps(reg))
    (d / "media").mkdir(exist_ok=True)
    (d / "media" / "earth.jpg").write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    m = {"format": courses.FORMAT, "version": courses.VERSION, "id": cid, "title": title, "program": "Test program",
         "status": "pack", "subject": "Testing", "grades": "9-12",
         "reading_level": {"grades": "9-12", "register": "teen", "budgets": {"prompt": 30, "hint": 16}},
         "labels": {"course": title, "school": "Field School", "patches": "Field patches"},
         "globe": {"body": "earth", "name": "Earth", "km": 6371.0, "map": f"/api/courses/{cid}/media/earth.jpg"},
         "gazetteer": "places.json", "entities": "entities.json",
         "ear": {"names": "entities", "keyterms": ["Mesa Verde", "dendrochronology", "kiva"]},
         "lessons": {"source": "lessons.json", "tracks": ["core"], "ids": [l["id"] for l in les]},
         "assets": {"required": [f"course_{cid}"], "optional": []},
         "standards": [{"framework": "Test framework", "codes": ["T.1"]}],
         "lines": {"guard": f"Let's keep names and addresses private. Ask me about {title}."},
         "class_packs": True} | over
    (d / courses.PACK_FILE).write_text(json.dumps(m))
    return d
