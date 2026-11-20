"""Course manifests (docs/COURSES.md §4, §6 spike): the Moon is course #1 with zero behaviour change."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import courses
from app.academy import content

ROOT = Path(__file__).resolve().parents[2]
MOON = json.loads((courses.DIR / "moon.json").read_text())
ARCH = json.loads((ROOT / "docs/courses/archaeology/course.manifest.json").read_text())


def test_the_moon_manifest_is_valid_and_points_at_real_files():
    errs, planned = courses.validate(MOON, known_assets=courses.asset_ids())
    assert errs == [] and planned == []


def test_the_moon_lessons_are_exactly_the_course_the_app_plays():
    # the manifest lists course.json's lessons, in order: loading it changes nothing (content.py is untouched)
    assert MOON["lessons"]["ids"] == [l["id"] for l in content.nasa_course()["lessons"]]


def test_the_moon_assets_are_the_desktop_manifest_assets():
    known = courses.asset_ids()
    assert set(MOON["assets"]["required"]) == {"ear", "tagger", "embedder", "voice"}
    assert set(MOON["assets"]["required"]) | set(MOON["assets"]["optional"]) == known


def test_the_moon_globe_is_the_globe_js_default():
    js = (ROOT / "frontend/src/globe.js").read_text()
    m = re.search(r'MOON_BODY = Object\.freeze\(\{ name: "(\w+)", map: "([^"]+)", km: MOON_KM \}\)', js)
    assert m and m.group(2) == MOON["globe"]["map"] and m.group(1) == MOON["globe"]["name"]
    assert f"MOON_KM = {MOON['globe']['km']}" in js


def test_the_archaeology_draft_has_the_right_shape_and_its_lessons_exist():
    # P3 (feat/archaeology-content): lessons, places, entities and ear vocab are written; the season and voice pack
    # are still planned (P4 / P5)
    errs, planned = courses.validate(ARCH)
    assert errs == []
    assert "courses/archaeology/course.json" not in planned and ARCH["globe"]["body"] == "earth"
    assert set(planned) <= {"courses/archaeology/concepts.json", "courses/archaeology/voice_pack/index.json",
                            "courses/archaeology/seasons.json"}


def test_a_published_course_must_have_its_files():
    m = copy.deepcopy(ARCH) | {"status": "pack", "missions": {"kind": "survey_season", "sites": "courses/archaeology/nope.json"}}
    errs, _ = courses.validate(m)
    assert any(e["at"] == "missions.sites" for e in errs)


def test_bad_manifests_say_where():
    def ats(**over):
        return {e["at"] for e in courses.validate(copy.deepcopy(MOON) | over)[0]}
    assert "id" in ats(id="Moon!")
    assert "globe.body" in ats(globe={"body": "mars"})
    assert "status" in ats(status="live")
    assert "gazetteer" in ats(gazetteer="../../etc/passwd")
    assert "assets.optional[0]" in {e["at"] for e in courses.validate(
        copy.deepcopy(MOON) | {"assets": {"required": [], "optional": ["nope"]}}, known_assets={"ear"})[0]}
    assert "lessons.ids" in ats(lessons={**MOON["lessons"], "ids": list(reversed(MOON["lessons"]["ids"]))})


def test_the_loader_skips_a_broken_file(tmp_path, monkeypatch):
    (tmp_path / "moon.json").write_text(json.dumps(MOON))
    (tmp_path / "zz.json").write_text("{not json")
    (tmp_path / "copy.json").write_text(json.dumps(MOON))
    monkeypatch.setattr(courses, "DIR", tmp_path)
    courses.courses.cache_clear()
    try:
        assert [c["id"] for c in courses.courses()] == ["moon"]
        assert len(courses.problems()) == 2
    finally:
        courses.courses.cache_clear()


def test_api_lists_the_moon_as_the_active_course():
    from app.main import app
    courses.courses.cache_clear()
    r = TestClient(app).get("/api/courses")
    assert r.status_code == 200
    d = r.json()
    assert d["active"] == "moon" and [c["id"] for c in d["courses"]] == ["moon"] and d["problems"] == []
    assert d["courses"][0]["lessons"] == 16 and d["courses"][0]["globe"]["body"] == "moon"
