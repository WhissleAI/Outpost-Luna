"""P1 courses (docs/COURSES.md §4, §5 P1): the registry with packs, the active course, switching drops every course
cache together, and the Moon (course #1) stays byte-for-byte what it was."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import courses, entities, hotlist, listen, names_list
from app.academy import classpacks, content, grade
from tests.course_fixture import make_pack


@pytest.fixture
def packs():
    d = Path(os.environ["COURSE_PACKS_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    yield d
    courses.set_active("moon") if courses.get("moon") else None


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_the_moon_is_the_default_and_only_course():
    assert courses.active() == "moon" and [c["id"] for c in courses.courses()] == ["moon"]
    assert courses.path("lessons.source") == content.COURSE
    assert courses.path("gazetteer") == courses.DATA / "places.json"
    assert courses.path("entities") == entities.APP_REGISTRY


def test_the_moon_reading_level_and_labels_are_todays():
    rl = courses.reading_level()
    assert rl["register"] == "kid" and rl["grades"] == "3-8" and rl["budgets"]["prompt"] == 20
    assert courses.labels()["patches"] == "NASA patches" and courses.labels()["school"] == "Flight School"
    assert courses.keyterms() is None               # the Moon keeps app/keyterms.py's lunar lists
    assert courses.line("guard", "X") == "X"         # and the Director's own lines


def test_a_pack_joins_the_registry(packs):
    make_pack(packs)
    courses.courses.cache_clear()
    assert [c["id"] for c in courses.courses()] == ["moon", "testland"]
    assert courses.root(courses.get("testland")) == packs / "course_testland"
    assert courses.active() == "moon"               # installing never switches


def test_a_broken_or_misplaced_pack_is_skipped_with_a_reason(packs):
    make_pack(packs, cid="ok")
    (packs / "course_bad").mkdir()
    (packs / "course_bad" / "course.json").write_text("{nope")
    d = make_pack(packs, cid="wrong")
    (d.parent / "course_elsewhere").mkdir()
    (d / "course.json").rename(d.parent / "course_elsewhere" / "course.json")
    make_pack(packs, cid="sneaky", gazetteer="../../../etc/passwd")
    make_pack(packs, cid="built", status="builtin")
    courses.courses.cache_clear()
    assert [c["id"] for c in courses.courses()] == ["moon", "ok"]
    probs = " ".join(courses.problems())
    assert "course_bad" in probs and "course_elsewhere" in probs and "course pack" in probs and "pack here" in probs


def test_switching_swaps_every_course_cache_together(packs):
    make_pack(packs)
    moon_ids = [l["id"] for l in content.course()["lessons"]]
    moon_reg = entities.registry()
    moon_terms = listen.keyterms()
    assert courses.set_active("testland") == "testland" and courses.active() == "testland"
    assert [l["id"] for l in content.nasa_course()["lessons"]] == ["moon", "phases"]
    assert entities.registry() is not moon_reg and entities.registry().get("mesa_verde") is not None
    assert any(e["name"] == "Mesa Verde" for e in names_list.screen_names({"screen": "map"}))
    assert listen.keyterms()[:3] == ("Mesa Verde", "dendrochronology", "kiva")
    assert courses.reading_level()["register"] == "teen" and courses.budget("prompt") == 30
    assert courses.budget("title") == 6             # unset budgets keep the Moon's
    assert courses.labels()["patches"] == "Field patches"
    from app import director
    assert "Testland" in director._course_line("guard", director.GUARD)
    # and back: the Moon is exactly the Moon again
    courses.set_active("moon")
    assert [l["id"] for l in content.course()["lessons"]] == moon_ids
    assert listen.keyterms() == moon_terms and entities.registry().get("mesa_verde") is None
    assert director._course_line("guard", director.GUARD) == director.GUARD


def test_the_switch_is_stored_per_computer_and_survives_a_restart(packs):
    make_pack(packs)
    courses.set_active("testland")
    assert json.loads(Path(os.environ["ACTIVE_COURSE_FILE"]).read_text()) == {"active": "testland"}
    courses.courses.cache_clear()
    assert courses.active() == "testland"


def test_a_removed_pack_falls_back_to_the_moon(packs):
    import shutil
    d = make_pack(packs)
    courses.set_active("testland")
    shutil.rmtree(d)
    courses.courses.cache_clear()
    assert courses.active() == "moon" and courses.current()["id"] == "moon"


def test_an_unknown_course_is_refused():
    with pytest.raises(KeyError):
        courses.set_active("atlantis")
    assert courses.active() == "moon"


def test_a_corrupt_state_file_means_the_moon():
    Path(os.environ["ACTIVE_COURSE_FILE"]).write_text("[[[")
    assert courses.active() == "moon"


def test_class_packs_belong_to_a_course(packs, tmp_path, monkeypatch):
    monkeypatch.setattr(classpacks, "DIR", tmp_path)
    classpacks.reload()
    from app.academy.classpacks import validate
    assert any(e["at"] == "course" for e in validate({"format": classpacks.FORMAT, "version": 1, "id": "x",
                                                       "title": "X", "course": "Not ok!", "lessons": []})[0])
    assert classpacks.pack_course({}) == "moon" and classpacks.pack_course({"course": "testland"}) == "testland"


def test_reading_level_budgets_are_checked_per_course():
    l = {"id": "x", "title": "One two three four five six seven", "steps": [{"prompt": " ".join(["w"] * 25)}]}
    moon = content.level_problems(l, courses.DEFAULT_LEVEL)
    assert any("title over 6" in p for p in moon) and any("prompt over 20" in p for p in moon)
    teen = {"budgets": {**courses.DEFAULT_LEVEL["budgets"], "prompt": 30, "title": 8}}
    assert content.level_problems(l, teen) == []


def test_the_moon_course_passes_its_own_reading_level():
    assert [p for p in content.check() if "reading level" in p] == []


def test_api_lists_and_switches(packs, client):
    make_pack(packs)
    r = client.get("/api/courses").json()
    assert r["active"] == "moon" and [c["id"] for c in r["courses"]] == ["moon", "testland"]
    moon = r["courses"][0]
    assert moon["removable"] is False and moon["labels"]["patches"] == "NASA patches"
    assert moon["big_ideas"]["phases"]["star"] == "Phases" and moon["standards"][0]["framework"] == "NGSS"
    assert client.post("/api/courses/active", json={"id": "nope"}).status_code == 404
    assert client.post("/api/courses/active", json={"id": "testland"}).json() == {"active": "testland"}
    assert [l["id"] for l in client.get("/api/academy/course").json()["lessons"]][:2] == ["moon", "phases"]
    assert client.get("/course/testland/earth.jpg").status_code == 200
    for bad in ("course.json", "../course_testland/course.json", "nothing.jpg"):
        assert client.get(f"/course/testland/{bad}").status_code == 404
    assert client.get("/course/moon/places.json").status_code == 404     # built-ins serve nothing here
    client.post("/api/courses/active", json={"id": "moon"})


def test_the_gazetteer_follows_the_course(packs, client):
    from app.main import S
    d = make_pack(packs)
    raw = json.loads((d / "places.json").read_text())
    raw["places"] = [p for p in raw["places"] if p["id"] == "tycho"] + [{"id": "mesa_verde", "name": "Mesa Verde",
                     "lat": 37.18, "lon": -108.49, "diameter_km": 20, "fact": "A park in Colorado."}]
    (d / "places.json").write_text(json.dumps(raw))
    (d / "artifacts.json").unlink()
    client.post("/api/courses/active", json={"id": "testland"})
    assert set(S["gaz"].places) == {"tycho", "mesa_verde"} and set(grade.gaz().places) == {"tycho", "mesa_verde"}
    client.post("/api/courses/active", json={"id": "moon"})
    assert "mesa_verde" not in S["gaz"].places and len(S["gaz"].places) > 50


def test_the_turn_log_names_the_course():
    from app import turnlog
    assert turnlog._course() == "moon"


def test_the_ear_vocab_is_the_moons_on_the_moon():
    hotlist.vocab.cache_clear()
    assert hotlist.vocab() == hotlist.moon_vocab()
