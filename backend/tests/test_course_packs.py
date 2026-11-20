"""Course packs (docs/COURSES.md §4.2, P2): install from the catalog, remove, switch back to the Moon, School network
mode, disk space, the desktop's flag files, and the pack builder's manifest rewrite."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import course_packs, courses
from tests.course_fixture import make_pack


def build_tar(src: Path, dst: Path) -> tuple[str, int, list[dict]]:
    """A deterministic ustar tar of a pack folder's contents (what scripts/asset_pack.py writes)."""
    files = sorted(p for p in src.rglob("*") if p.is_file())
    with tarfile.open(dst, "w", format=tarfile.USTAR_FORMAT) as t:
        for p in files:
            ti = tarfile.TarInfo(p.relative_to(src).as_posix())
            ti.size, ti.mtime = p.stat().st_size, 0
            t.addfile(ti, io.BytesIO(p.read_bytes()))
    return (hashlib.sha256(dst.read_bytes()).hexdigest(), dst.stat().st_size,
            [{"path": p.relative_to(src).as_posix(), "size": p.stat().st_size} for p in files])


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A catalog with the Moon's assets plus course_testland, and its tar in a local source folder (no desktop)."""
    work = tmp_path / "work"
    src = make_pack(work)
    srcdir = tmp_path / "src"
    srcdir.mkdir()
    sha, size, files = build_tar(src, srcdir / "outpost-luna-v2-course_testland.tar")
    m = json.loads(courses.ASSETS_MANIFEST.read_text())
    m["assets"].append({"id": "course_testland", "title": "Course: Testland", "required": False, "on_demand": True,
                        "file": "outpost-luna-v2-course_testland.tar", "url": "https://www.dropbox.com/x/t.tar?dl=1",
                        "sha256": sha, "size": size, "unpacked_size": sum(f["size"] for f in files), "version": "1",
                        "files": files})
    man = tmp_path / "assets.manifest.json"
    man.write_text(json.dumps(m))
    monkeypatch.setattr(courses, "ASSETS_MANIFEST", man)
    monkeypatch.setenv("COURSE_PACK_SRC", str(srcdir))
    courses.courses.cache_clear()
    yield srcdir
    courses.set_active("moon")


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_the_catalog_lists_course_packs_only(catalog):
    assert "testland" in [e["id"] for e in course_packs.catalog()]
    assert course_packs.entry("testland")["asset"] == "course_testland"


def tl(r):
    return next(p for p in r["packs"] if p["id"] == "testland")


def test_install_switch_remove_and_back_to_the_moon(catalog, client):
    r = client.get("/api/courses/packs").json()
    assert tl(r)["state"] == "missing" and r["managed"] is False
    assert client.post("/api/courses/packs/testland/get").json() == {"state": "installed"}
    assert [c["id"] for c in client.get("/api/courses").json()["courses"]] == ["moon", "testland"]
    assert client.post("/api/courses/active", json={"id": "testland"}).json()["active"] == "testland"
    assert client.get("/api/courses/testland/media/earth.jpg").status_code == 200
    # removing the course being played: back to the Moon first, then it is gone
    r = client.post("/api/courses/packs/testland/remove").json()
    assert r == {"state": "missing", "active": "moon"}
    assert courses.active() == "moon" and courses.get("testland") is None
    assert not (Path(os.environ["COURSE_PACKS_DIR"]) / "course_testland").exists()
    assert [l["id"] for l in client.get("/api/academy/course").json()["lessons"]][0] == "moon"


def test_the_moon_is_never_removed(client):
    assert client.post("/api/courses/packs/moon/remove").status_code == 400
    assert courses.get("moon") is not None


def test_a_damaged_tar_never_installs(catalog, client):
    f = catalog / "outpost-luna-v2-course_testland.tar"
    f.write_bytes(f.read_bytes()[:-10] + b"0123456789")
    r = client.post("/api/courses/packs/testland/get")
    assert r.status_code == 422 and "damaged" in r.json()["detail"]
    assert courses.get("testland") is None


def test_an_unsafe_tar_is_refused(catalog):
    bad = catalog / "evil.tar"
    with tarfile.open(bad, "w") as t:
        ti = tarfile.TarInfo("../escape.txt"); ti.size = 1
        t.addfile(ti, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="unsafe"):
        course_packs.install_local({"asset": "course_evil", "sha256": None, "files": []}, bad)


def test_no_local_file_says_not_ready(catalog, client):
    shutil.rmtree(catalog)
    r = client.post("/api/courses/packs/testland/get")
    assert r.status_code == 404 and r.json()["detail"] == course_packs.NO_SOURCE_MSG


def test_school_network_mode_blocks_and_says_so(catalog, client, monkeypatch):
    from app import netgate
    monkeypatch.setattr(netgate, "policy", lambda: {"school_network": True, "allow_hosts": []})
    r = client.post("/api/courses/packs/testland/get")
    assert r.status_code == 403 and "School network mode is on" in r.json()["detail"]
    assert tl(client.get("/api/courses/packs").json())["blocked"] is True
    # a host the school allows downloads as usual
    monkeypatch.setattr(netgate, "policy", lambda: {"school_network": True, "allow_hosts": ["www.dropbox.com"]})
    assert client.post("/api/courses/packs/testland/get").json()["state"] == "installed"


def test_not_enough_disk_space_says_how_much(catalog, client, monkeypatch):
    monkeypatch.setattr(course_packs, "free_bytes", lambda: 10)
    r = client.post("/api/courses/packs/testland/get")
    assert r.status_code == 507 and "MB free" in r.json()["detail"]


def test_with_the_desktop_app_it_asks_through_flag_files(catalog, client, monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    monkeypatch.delenv("COURSE_PACK_SRC")
    monkeypatch.setenv("ASSETS_DIR", str(assets))
    monkeypatch.setenv("COURSE_PACKS_DIR", str(assets))
    courses.courses.cache_clear()
    assert client.post("/api/courses/packs/testland/get").json() == {"state": "queued"}
    assert (assets / ".want" / "course_testland").exists()
    assert tl(client.get("/api/courses/packs").json())["state"] == "queued"
    (assets / ".active").mkdir(); (assets / ".active" / "course_testland").write_text("")
    assert tl(client.get("/api/courses/packs").json())["state"] == "downloading"
    # the desktop app failed it (assets.js store.failed): said plainly, and a new ask clears it
    (assets / ".active" / "course_testland").unlink(); (assets / ".want" / "course_testland").unlink()
    (assets / ".failed").mkdir(); (assets / ".failed" / "course_testland").write_text("You're offline.")
    p = tl(client.get("/api/courses/packs").json())
    assert p["state"] == "failed" and p["reason"] == "You're offline."
    client.post("/api/courses/packs/testland/get")
    assert not (assets / ".failed" / "course_testland").exists()
    # installed by the desktop app, played, then removed: moved aside at once, the desktop deletes it
    shutil.copytree(make_pack(tmp_path / "w2"), assets / "course_testland")
    (assets / ".want" / "course_testland").unlink()
    client.post("/api/courses/active", json={"id": "testland"})
    assert client.post("/api/courses/packs/testland/remove").json()["active"] == "moon"
    assert (assets / ".remove" / "course_testland").exists() and (assets / ".old-course_testland").exists()
    assert courses.get("testland") is None


def test_the_pack_builder_rewrites_paths_into_the_pack():
    src = {"id": "arch", "status": "pack", "gazetteer": "courses/arch/places.json", "entities": "courses/arch/entities.json",
           "ear": {"vocab": "courses/arch/ear_vocab.json"}, "lessons": {"source": "courses/arch/course.json", "ids": []},
           "missions": {"kind": "survey_season", "sites": "courses/arch/seasons.json"}, "_root": "x"}
    pack, base = courses.to_pack(src)
    assert base == "courses/arch" and pack["gazetteer"] == "places.json" and pack["lessons"]["source"] == "course.json"
    assert pack["ear"]["vocab"] == "ear_vocab.json" and pack["missions"]["sites"] == "seasons.json" and "_root" not in pack
    with pytest.raises(ValueError):
        courses.to_pack(src | {"gazetteer": "places.json"})     # the Moon's file: not part of this pack
    with pytest.raises(ValueError):
        courses.to_pack(src | {"gazetteer": "courses/arch/../../places.json"})


def test_reset_everything_returns_to_the_moon_start_over_keeps_the_course(catalog, client):
    from app import reset
    client.post("/api/courses/packs/testland/get")
    courses.set_active("testland")
    reset.reset("start")
    assert courses.active() == "testland"          # Start over: downloads (and the course) stay
    reset.reset("all")
    assert courses._read_state() == "moon" and courses.active() == "moon"


def test_the_listing_carries_each_course_card_and_whether_it_can_download(catalog, client, monkeypatch):
    """The first-run course pick (frontend/src/course_pick.js) shows each course's one line and reading level before it
    is downloaded: the catalog's `course` card, else the source manifest in a dev checkout."""
    d = client.get("/api/courses/packs").json()
    assert d["downloadable"] is True                     # a local source folder (COURSE_PACK_SRC)
    assert tl(d).get("grades") is None                   # testland has no card and no source manifest
    m = json.loads(courses.ASSETS_MANIFEST.read_text())
    next(a for a in m["assets"] if a["id"] == "course_testland")["course"] = {"program": "Field Testing", "grades": "9-12", "x": 1}
    courses.ASSETS_MANIFEST.write_text(json.dumps(m))
    p = tl(client.get("/api/courses/packs").json())
    assert p["program"] == "Field Testing" and p["grades"] == "9-12" and "x" not in p
    # the real catalog's Archaeology card (scripts/asset_pack.py course_card, the same fields as its source)
    src = json.loads((courses.DIR / "archaeology.json").read_text())
    assert course_packs.card("archaeology") == {k: src[k] for k in ("program", "subject", "grades")}
    real = json.loads((Path(course_packs.__file__).resolve().parents[2] / "desktop" / "assets.manifest.json").read_text())
    assert next(a for a in real["assets"] if a["id"] == "course_archaeology")["course"] == course_packs.card("archaeology")
    # no desktop downloader and no local source (the iPad shell): nothing is offered
    monkeypatch.delenv("COURSE_PACK_SRC")
    monkeypatch.delenv("ASSETS_DIR", raising=False)
    from app.config import settings
    monkeypatch.setattr(settings, "assets_dir", None)
    assert client.get("/api/courses/packs").json()["downloadable"] is False


def test_a_running_download_reports_its_progress(catalog, client, monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    monkeypatch.delenv("COURSE_PACK_SRC")
    monkeypatch.setenv("ASSETS_DIR", str(assets))
    monkeypatch.setenv("COURSE_PACKS_DIR", str(assets))
    courses.courses.cache_clear()
    client.post("/api/courses/packs/testland/get")
    (assets / ".active").mkdir()
    f = assets / ".active" / "course_testland"
    f.write_text("")                                     # just started: no bytes yet
    assert "progress" not in tl(client.get("/api/courses/packs").json())
    f.write_text("2304000 4608000")                      # assets.js writes "<done> <total>"
    p = tl(client.get("/api/courses/packs").json())
    assert p["state"] == "downloading" and p["progress"] == 0.5
    f.write_text("junk")
    assert "progress" not in tl(client.get("/api/courses/packs").json())
