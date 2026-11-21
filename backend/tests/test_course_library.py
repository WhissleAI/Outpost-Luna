"""A course's own Library and videos (app/course_library.py, app/video.py catalog(); docs/COURSES.md "Course library").

Archaeology: real NASA Earth views (Landsat, ISS astronaut photos, Blue Marble), NPS site photos, USGS lidar and
orthoimagery, and NASA videos about remote sensing, lidar, tree rings and the Moon. Every file credited, every id known.
The Moon has no shelves (only map layers, tests/test_open_data.py) and its video catalog is exactly what it was."""
from __future__ import annotations

import copy
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import course_library as cl, courses, video
from app.academy import content

D = content.DATA / "courses" / "archaeology"
LIB = json.loads((D / "library.json").read_text())
VIDS = json.loads((D / "videos.json").read_text())
BASE = json.loads((content.DATA / "video" / "catalog.json").read_text())


def _drop():
    courses.reload_all()
    content.reload()


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv(content.DEV_COURSE_ENV, "archaeology")
    _drop()
    yield
    monkeypatch.delenv(content.DEV_COURSE_ENV, raising=False)
    _drop()


def _files():
    return cl._course_files(courses.get("archaeology"))


def test_the_archaeology_library_is_valid(dev):
    assert cl.validate(LIB, _files()) == []


def test_the_course_videos_are_valid_nasa_files_and_never_clash_with_the_moons():
    assert video.validate(VIDS) == []
    assert not {v["id"] for v in VIDS} & {v["id"] for v in BASE}
    for v in VIDS:
        assert v["source"] == "nasa_file" and v["file_url"].startswith("https://images-assets.nasa.gov/video/")
        assert v["music_credit"] is False and v["credit"].startswith("NASA")
        assert v["nasa_id"] in v["file_url"] and v["source_page"] == f"https://images.nasa.gov/details/{v['nasa_id']}"
        assert v["file_url"].endswith("~small.mp4") and v["bytes"] < 50_000_000, "modest renditions (640x360)"
    assert sum(v["bytes"] for v in VIDS) < 160_000_000


def test_every_library_video_and_overlay_is_the_courses_own():
    ids = {v["id"] for v in VIDS}
    used = {it["video"] for sh in LIB["shelves"] for it in sh["items"] if it["kind"] == "video"}
    assert used <= ids and len(used) == len(ids), "every course video is on a shelf"
    assert [o["file"] for o in LIB["overlays"]] == ["four_corners_region.jpg"]


def test_new_media_is_credited_real_and_small():
    cred = {c["file"]: c for c in json.loads((D / "media" / "credits.json").read_text())}
    for f, src in (("iss_wupatki.jpg", "https://images.nasa.gov/details/iss073e0886930"),
                   ("iss_pastora_san_juan.jpg", "https://images.nasa.gov/details/iss073e1199153"),
                   ("four_corners_region.jpg", "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer")):
        c = cred[f]
        p = D / "media" / f
        assert p.is_file() and p.stat().st_size == c["bytes"] < 1_000_000, f
        assert c["source_url"] == src and c["licence"].startswith("Public domain") and c["alt"], f
        assert re.fullmatch(r"[0-9a-f]{64}", c["sha256"]), f


def test_validate_catches_what_would_break_the_screen(dev):
    f = _files()
    bad = copy.deepcopy(LIB)
    bad["shelves"][0]["items"][0]["file"] = "nope.jpg"
    next(sh for sh in bad["shelves"] if sh["id"] == "watch")["items"][0]["video"] = "psr"              # a Moon video is not the course's
    bad["shelves"][1]["items"][0]["source"] = "made_up"
    bad["overlays"][0]["bounds"] = {"west": -110.2, "south": 35.7, "east": -100, "north": 38.0}   # wrong shape
    bad["tour"]["stops"].append("atlantis")
    bad["chips"].append({"label": "x", "do": "item:ghost"})
    errs = " | ".join(cl.validate(bad, f))
    for s in ("nope.jpg", "'psr'", "'made_up'", "does not match its bounds", "tour.stops", "'ghost'"):
        assert s in errs, s
    assert cl.validate({"format": "x"}, f)


def test_the_route_serves_the_active_courses_library(dev):
    from app.main import app
    d = TestClient(app).get("/api/course/library").json()
    assert d["course"] == "archaeology" and "problems" not in d
    assert [s["id"] for s in d["shelves"]] == ["orbit", "sentinel", "sites", "lidar", "climate", "watch", "moon", "data"]
    it = next(i for s in d["shelves"] for i in s["items"] if i["id"] == "iss_san_juan")
    assert it["url"] == "/api/courses/archaeology/media/iss_pastora_san_juan.jpg" and it["image_credit"].startswith("NASA")
    v = next(i for s in d["shelves"] for i in s["items"] if i["id"] == "v_lidar")
    assert v["poster"] == "/api/video/arch_lidar_space/poster" and v["duration_s"] == 223
    assert d["overlays"][0]["url"].endswith("/four_corners_region.jpg")
    assert TestClient(app).get(it["url"]).status_code == 200


def test_course_videos_join_the_catalog_only_while_the_course_is_active(dev, monkeypatch):
    from app.main import app
    ids = [v["id"] for v in TestClient(app).get("/api/video/catalog").json()]
    assert ids[: len(BASE)] == [v["id"] for v in BASE] and ids[len(BASE):] == [v["id"] for v in VIDS]
    assert video.item("arch_lidar_space")["course"] == "archaeology"
    monkeypatch.delenv(content.DEV_COURSE_ENV)
    _drop()
    assert [v["id"] for v in video.catalog()] == [v["id"] for v in BASE]
    moon = cl.current()   # the Moon: no shelves (its Library is code), only its open-data map layers (docs/OPEN_DATA.md)
    assert moon["course"] == "moon" and moon["shelves"] == [] and [l["id"] for l in moon["layers"]] == ["age", "height"]


def test_a_course_pack_can_carry_its_videos(dev, tmp_path, monkeypatch):
    v = video.item("arch_landsat_pushbroom")
    assert video.course_video_dir(v) == D / "video"
    assert video.course_video_dir(video.item("psr")) is None, "a Moon video never looks in a course pack"
    monkeypatch.setattr(video, "course_video_dir", lambda x: tmp_path if x.get("course") else None)
    assert not video.pack_has(v)
    (tmp_path / "arch_landsat_pushbroom.mp4").write_bytes(b"x")
    assert video.pack_has(v) and video.availability(v) == "cached"


def test_the_course_pack_carries_lighter_copies_the_backend_accepts(dev, tmp_path):
    """Pack v2 ships re-encodes (videos.json `pack`, tools/video_catalog.py --pack --catalog): pack_copy_ok takes the
    file by pack.bytes + pack.sha256 (or the NASA original), and nothing else."""
    for v in VIDS:
        pk = v["pack"]
        assert "libx264" in pk["derive"] and "+faststart" in pk["derive"] and "yuv420p" in pk["derive"]
        assert 0 < pk["bytes"] < v["bytes"] / 2, f"{v['id']}: the pack copy is the lighter one"
    assert sum(v["pack"]["bytes"] for v in VIDS) < 40_000_000
    blob = b"pretend re-encode"
    v = {**video.item("arch_landsat_pushbroom"),
         "pack": {"derive": "x", "bytes": len(blob), "sha256": __import__("hashlib").sha256(blob).hexdigest()}}
    f = tmp_path / "arch_landsat_pushbroom.mp4"
    f.write_bytes(blob)
    assert video.pack_copy_ok(v, f)
    f.write_bytes(b"pretend re-encodf")
    assert not video.pack_copy_ok(v, f), "same size, other bytes: refused"


def test_the_pack_manifest_points_at_the_library_and_videos():
    m = json.loads((content.DATA / "courses" / "archaeology.json").read_text())
    pack, _ = courses.to_pack(m)
    assert pack["library"] == "library.json" and pack["videos"] == "videos.json"
    errs, _ = courses.validate(m)
    assert errs == []


# [0.5.6] owner playtest 0.5.5: Lesson 1's NPS rack card ("What If I Find an Artifact?") was a dead link (the shell
# refused nps.gov, and the app is offline-first). The pack keeps the card (the PDF as it was, plus a picture per page)
# and the library names it as a document, so any link to its address opens the pages in the app.
RACK = "https://www.nps.gov/subjects/archeology/upload/RackArtifactsVisitors_508.pdf"


def test_the_nps_rack_card_ships_in_the_pack_public_domain_and_credited():
    cred = {c["file"]: c for c in json.loads((D / "media" / "credits.json").read_text())}
    (doc,) = LIB["docs"]
    assert doc["id"] == "nps_rack_artifacts" and doc["url"] == RACK and doc["pdf"] == "nps_rack_artifacts.pdf"
    assert [p["file"] for p in doc["pages"]] == ["nps_rack_artifacts_p1.jpg", "nps_rack_artifacts_p2.jpg"]
    for f in [doc["pdf"]] + [p["file"] for p in doc["pages"]]:
        c, p = cred[f], D / "media" / f
        assert p.is_file() and p.stat().st_size == c["bytes"] < 400_000, f
        assert c["licence_class"] == "pd" and c["licence"].startswith("Public domain") and "17 U.S.C. 105" in c["licence"], f
        assert c["source_url"] == RACK and c["alt"] and cl.licence_problem(c) is None, f
    assert (D / "media" / doc["pdf"]).read_bytes()[:5] == b"%PDF-"
    # every lesson that cites the card cites the same address the library maps
    course = (D / "course.json").read_text()
    assert course.count(RACK) == 3


def test_the_route_serves_the_document_pages_and_validate_guards_them(dev):
    from app.main import app
    d = TestClient(app).get("/api/course/library").json()
    (doc,) = d["docs"]
    assert doc["url"] == RACK and doc["title"] == "What If I Find an Artifact?" and doc["credit"].startswith("National Park Service")
    assert [p["url"] for p in doc["pages"]] == [f"/api/courses/archaeology/media/nps_rack_artifacts_p{n}.jpg" for n in (1, 2)]
    for p in doc["pages"]:
        r = TestClient(app).get(p["url"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and p["alt"]
    f = _files()
    bad = copy.deepcopy(LIB)
    bad["docs"][0]["pages"].append({"file": "nope_p3.jpg"})
    bad["docs"].append({**copy.deepcopy(LIB["docs"][0]), "id": "again"})   # the same url twice
    bad["docs"].append({"id": "Bad Id", "url": "http://x", "pages": []})
    errs = " | ".join(cl.validate(bad, f))
    for s in ("nope_p3.jpg", "docs[1]: needs the https url", "docs[2]: needs a unique"):
        assert s in errs, s


def test_the_regional_picture_is_the_seamless_rebuild():
    """[0.5.6] four_corners_region.jpg was four USGS tiles of different years and colour (a seam at 37 N and 109.05 W:
    "two mismatched squares" on the globe). scripts/arch_region_overlay.py rebuilt it (seam score 31 -> 1.8, its
    --check); the credit says how, and the file is the one it describes."""
    import hashlib
    c = {x["file"]: x for x in json.loads((D / "media" / "credits.json").read_text())}["four_corners_region.jpg"]
    b = (D / "media" / "four_corners_region.jpg").read_bytes()
    assert hashlib.sha256(b).hexdigest() == c["sha256"] and len(b) == c["bytes"]
    assert "arch_region_overlay.py" in c["note"] and c["licence_class"] == "pd"
    assert c["sha256"] != "095b1c73281ba1cff35bd8c1064ffb55cf6c1525a9e9724fa17af17b5d27d660"   # the seamed 0.5.5 picture
