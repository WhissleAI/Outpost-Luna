"""Open data beyond NASA in both courses' Library (docs/OPEN_DATA.md; scripts/open_data_build.py).

Moon: two whole-globe map layers, the USGS Unified Geologic Map (CC0) coloured by period, and USGS's LOLA colour relief
(public domain), served by GET /api/course/library as `layers` and shipped inside the app (backend/data/courses/moon).
Archaeology: Copernicus Sentinel-2 (ESA) true and near-infrared colour views and a chart of NOAA's ITRDB CO652 tree-ring
record, on its shelves, every file credited with its licence and the Copernicus notice."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import course_library as cl, courses
from app.academy import content

MOON = content.DATA / "courses" / "moon"
ARCH = content.DATA / "courses" / "archaeology"
ROOT = content.DATA.parents[1]


def _cred(d: Path) -> dict:
    return {c["file"]: c for c in json.loads((d / "media" / "credits.json").read_text())}


@pytest.fixture
def moon(monkeypatch):
    monkeypatch.delenv(content.DEV_COURSE_ENV, raising=False)
    courses.reload_all(); content.reload()
    yield
    courses.reload_all(); content.reload()


@pytest.fixture
def arch(monkeypatch):
    monkeypatch.setenv(content.DEV_COURSE_ENV, "archaeology")
    courses.reload_all(); content.reload()
    yield
    monkeypatch.delenv(content.DEV_COURSE_ENV, raising=False)
    courses.reload_all(); content.reload()


def test_the_moon_manifest_names_its_layers_library_and_still_validates():
    m = json.loads((content.DATA / "courses" / "moon.json").read_text())
    assert m["library"] == "courses/moon/library.json"
    errs, _ = courses.validate(m)
    assert errs == []


def test_the_moon_layers_are_valid_credited_and_true_to_their_files(moon):
    lib = json.loads((MOON / "library.json").read_text())
    files = cl._course_files(courses.get("moon"))
    assert cl.validate(lib, files) == []
    assert "shelves" not in lib, "the Moon's Library is code: it gets layers, not shelves"
    cred = _cred(MOON)
    for ly, licence, host in (("age", "CC0", "astrogeology.usgs.gov"), ("height", "Public domain", "astrogeology.usgs.gov")):
        f = next(x for x in lib["layers"] if x["id"] == ly)["file"]
        c, p = cred[f], MOON / "media" / f
        assert c["licence"].startswith(licence) and host in c["source_url"] and c["credit"].startswith("USGS")
        assert (c["width"], c["height"]) == (4096, 2048), "the globe's own map size, -180..180 equirectangular"
        assert p.stat().st_size == c["bytes"] < 3_500_000 and hashlib.sha256(p.read_bytes()).hexdigest() == c["sha256"]


def test_the_age_legend_matches_the_build_scripts_colours():
    spec = importlib.util.spec_from_file_location("odb", ROOT / "scripts" / "open_data_build.py")
    odb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(odb)
    lib = json.loads((MOON / "library.json").read_text())
    leg = next(x for x in lib["layers"] if x["id"] == "age")["legend"]
    assert [x["label"] for x in leg] == [p for p, _ in odb.PERIODS], "oldest first, the five lunar periods"
    assert [x["color"].lower() for x in leg] == ["#%02x%02x%02x" % c for _, c in odb.PERIODS]


def test_the_route_serves_the_moons_layers_and_their_files(moon):
    from app.main import app
    c = TestClient(app)
    d = c.get("/api/course/library").json()
    assert d["course"] == "moon" and d["shelves"] == [] and "problems" not in d
    age = d["layers"][0]
    assert age["id"] == "age" and age["url"] == "/api/courses/moon/media/moon_age.jpg"
    assert [l["title"] for l in d["layers"]] == ["Age", "Height"], "the layer's short title, never the file's long one"
    assert age["map_title"].startswith("Unified Geologic Map of the Moon")
    assert age["licence"].startswith("CC0") and age["source"]["url"].startswith("https://astrogeology.usgs.gov/")
    assert len(age["legend"]) == 5 and age["say"]
    r = c.get(age["url"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/jpeg")


def test_layer_validation_catches_what_would_break_the_maps_panel(moon):
    files = cl._course_files(courses.get("moon"))
    lib = json.loads((MOON / "library.json").read_text())
    bad = copy.deepcopy(lib)
    bad["layers"][0]["legend"][0]["color"] = "purple"
    bad["layers"][1]["source"] = "made_up"
    bad["layers"].append({"id": "photo", "title": "Photo", "file": "moon_age.jpg", "say": "x", "legend": [], "source": "x"})
    errs = " | ".join(cl.validate(bad, files))
    for s in ("legend", "'made_up'", "not 'photo'"):
        assert s in errs, s
    assert cl.validate({**lib, "layers": []}, files), "no layers and no shelves: nothing to show"
    wrong = copy.deepcopy(files)
    wrong["credits"] = {**files["credits"], "moon_age.jpg": {**files["credits"]["moon_age.jpg"], "height": 1500}}
    assert any("twice as wide" in e for e in cl.validate(lib, wrong))


def test_the_moon_layers_ship_in_the_app_bundle():
    spec = importlib.util.spec_from_file_location("bp", ROOT / "desktop" / "scripts" / "build_python.py")
    src = spec.origin and Path(spec.origin).read_text()
    assert 'Path(d).name == "moon" and Path(d).parent.name == "courses"' in src and 'out.discard("media")' in src


def test_archaeology_gets_esa_and_noaa_views_with_their_notices(arch):
    lib = json.loads((ARCH / "library.json").read_text())
    assert cl.validate(lib, cl._course_files(courses.get("archaeology"))) == []
    items = {it["id"]: it for sh in lib["shelves"] for it in sh["items"]}
    cred = _cred(ARCH)
    for iid in ("s2_true", "s2_nir"):
        c = cred[items[iid]["file"]]
        assert c["credit"].startswith("Contains modified Copernicus Sentinel data 2024"), "the EU legal notice's wording"
        assert c["licence"].startswith("Free, full and open") and c["scene"].startswith("S2A_")
        assert items[iid]["place"] == "mesa_verde", "park level: no site coordinates"
    c = cred["co652_chart.png"]
    assert "NOAA NCEI" in c["credit"] and c["source_url"] == "https://www.ncei.noaa.gov/access/paleo-search/study/19080"
    assert next(s for s in lib["shelves"] if s["id"] == "climate")["by"] == "NOAA"
    for f in ("s2_mesa_verde_true.jpg", "s2_mesa_verde_nir.jpg", "co652_chart.png"):
        p = ARCH / "media" / f
        assert p.stat().st_size == cred[f]["bytes"] < 1_000_000 and hashlib.sha256(p.read_bytes()).hexdigest() == cred[f]["sha256"]
    srcs = {s["id"]: s for s in json.loads((ARCH / "sources.json").read_text())["sources"]}
    for sid in ("copernicus_licence", "mv_fire_history", "post_fire_survey", "great_drought"):
        assert srcs[sid]["status"] == "supported" and srcs[sid]["url"].startswith("https://") and srcs[sid]["quote"]
