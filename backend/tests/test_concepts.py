"""Concepts below the lesson (D5: app/academy/concepts.py, data/learning/step_concepts.json, docs/BRAIN.md §11)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.academy import concepts as C, content
from app.config import settings

UNGRADED = {"video", "predict"}
COURSE_FILES = {"moon": settings.data_dir / "academy" / "course.json",
                "archaeology": settings.data_dir / "courses" / "archaeology" / "course.json"}


def _lessons(course):
    return {l["id"]: l for l in json.loads(COURSE_FILES[course].read_text())["lessons"]}


def _type(step):
    return (step.get("accept") or {}).get("type") or step.get("type")


@pytest.mark.parametrize("course", ["moon", "archaeology"])
def test_every_mapped_step_exists_and_is_graded(course):
    t = C.table()["courses"][course]
    ls = _lessons(course)
    for lid, steps in t["steps"].items():
        assert lid in ls, (course, lid)
        for s, cid in steps.items():
            st = ls[lid]["steps"][int(s)]
            assert _type(st) not in UNGRADED, (course, lid, s)
            assert cid in t["concepts"], (course, cid)


@pytest.mark.parametrize("course", ["moon", "archaeology"])
def test_every_concept_is_practised_and_labelled(course):
    t = C.table()["courses"][course]
    used = {cid for steps in t["steps"].values() for cid in steps.values()}
    assert used == set(t["concepts"])
    assert all(m["label"] and len(m["label"]) <= 40 for m in t["concepts"].values())


def test_every_graded_moon_step_has_a_concept():
    t = C.table()["courses"]["moon"]["steps"]
    missing = [(lid, i) for lid, l in _lessons("moon").items() for i, s in enumerate(l["steps"])
               if _type(s) not in UNGRADED and str(i) not in t.get(lid, {})]
    assert not missing


def test_ids_follow_the_client_lesson_rule():
    assert C.concept_of("comms", 0) == "radio_words"
    assert C.concept_of("archaeology:layers", 1) == "archaeology:stratigraphy"
    assert C.concept_of("phases", 0) is None                      # a predict guess: no concept
    assert C.concept_of("c-room5-tides", 0) is None and C.concept_of("comms", None) is None
    p = C.public("archaeology")["concepts"]["archaeology:stratigraphy"]
    assert p == {"label": "Layers (stratigraphy)", "lesson": "archaeology:layers", "step": 1, "mission": False}
    m = C.public("moon")["concepts"]
    assert m["storm_shelter"]["lesson"] == "radiation" and m["storm_shelter"]["step"] == 2 and m["storm_shelter"]["mission"]


def test_attempt_reply_carries_the_concept_and_the_endpoint_lists_them():
    from app.main import app
    c = TestClient(app)
    content.reload()
    r = c.post("/api/academy/attempt", json={"lesson_id": "comms", "step": 0, "input": {"choice": "understood"}}).json()
    assert r.get("concept") == "radio_words", r
    body = c.get("/api/academy/concepts").json()
    assert body["course"] == "moon" and body["concepts"]["regolith"]["lesson"] == "gravity"
