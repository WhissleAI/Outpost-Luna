"""A course switch starts getting what the new course still needs (app/video.py kick, app/course_packs.py ensure_active).

Before: the course's own videos only downloaded at backend startup, so after a switch they streamed on first play (and
needed the internet). Now a switch (courses.on_change) copies the videos the course pack carries, or downloads them with
the same rules as the launch prefetch, and a course video on its way says "downloading" instead of streaming. An outdated
pack (older than the catalog's min_version) is asked for again through the desktop's .want flag. The Moon: unchanged."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import course_packs, courses, video
from app.config import settings
from tests.course_fixture import make_pack

VIDS = ("tl_one", "tl_two")


def _video_entry(vid: str, data: bytes) -> dict:
    return {"id": vid, "title": vid, "concept": "test", "source": "nasa_file", "duration_s": 30, "credit": "NASA",
            "music_credit": False, "prefetch": True, "age": "all", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "file_url": f"https://images-assets.nasa.gov/video/{vid}.mp4"}


def make_video_pack(packs: Path, bundled: bool = True) -> Path:
    """Testland with two videos of its own; bundled: the pack carries them in video/ (pack v2's way)."""
    d = make_pack(packs, videos="videos.json")
    items = []
    (d / "video").mkdir(exist_ok=True)
    for vid in VIDS:
        data = (vid * 4000).encode()
        items.append(_video_entry(vid, data))
        if bundled:
            (d / "video" / f"{vid}.mp4").write_bytes(data)
    (d / "videos.json").write_text(json.dumps(items))
    return d


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The video cache in a temp folder, no network, a clean download state."""
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "video_offline", True)
    monkeypatch.setattr(settings, "video_prefetch", False)
    monkeypatch.setattr(courses, "_HOOKS", [])   # an earlier app lifespan registered the real ones: tests call kick()
    video._stop.clear()
    video._WANT.clear()
    video._front.clear()
    video.STATE.update(state="idle", done=0, total=0, error=None)
    yield tmp_path
    video._WANT.clear()
    video._front.clear()
    courses.set_active(courses.DEFAULT)


def _switch(cid="testland"):
    courses.courses.cache_clear()
    courses.set_active(cid)


def test_the_moon_needs_nothing_and_is_unchanged(env):
    assert video.course_todo() == []
    assert video.kick(wait=True) is False
    assert video.course_progress()["state"] == "none"
    assert all(video.availability(v) != "downloading" for v in video.catalog())
    p = course_packs.active_progress()
    assert p["course"] == "moon" and p["pack"] is None and p["busy"] is False
    from app.main import app
    assert TestClient(app).get("/api/courses/active/progress").json()["busy"] is False


def test_a_switch_copies_the_videos_the_pack_carries(env):
    make_video_pack(courses.packs_dir())
    _switch()
    assert [v["id"] for v in video.course_todo()] == list(VIDS)
    pr = video.course_progress()
    assert pr["state"] == "waiting" and pr["ready"] == 0 and pr["total"] == 2
    assert video.kick(wait=True) is True        # no network needed: the course pack's own copies
    assert video.course_todo() == []
    pr = video.course_progress()
    assert pr["state"] == "done" and pr["ready"] == 2 and pr["progress"] == 1.0
    assert all(video.is_cached(video.item(v)) for v in VIDS)
    assert video.cache().stats()["pinned_bytes"] > 0, "pinned: never evicted"


def test_the_switch_hook_kicks_it(env, monkeypatch):
    make_video_pack(courses.packs_dir())
    calls = []
    monkeypatch.setattr(video, "kick", lambda wait=False: calls.append(courses.active()) or True)
    monkeypatch.setattr(courses, "_HOOKS", [video.on_course_change])
    _switch()
    assert calls == ["testland"]


def test_main_registers_the_hooks(env, monkeypatch):
    monkeypatch.setattr(courses, "_HOOKS", [])
    from app.main import app
    try:
        with TestClient(app):
            assert video.on_course_change in courses._HOOKS and course_packs.on_course_change in courses._HOOKS
    finally:
        video._stop.clear()


def test_without_a_pack_copy_or_network_nothing_starts(env):
    make_video_pack(courses.packs_dir(), bundled=False)
    _switch()
    assert video.kick(wait=True) is False       # VIDEO_PREFETCH off: never a download
    pr = video.course_progress()
    assert pr["state"] == "waiting" and pr["reason"] == "off"
    assert video.availability(video.item("tl_one")) == "offline"


def test_a_video_on_its_way_says_downloading_not_stream(env, monkeypatch):
    make_video_pack(courses.packs_dir(), bundled=False)
    _switch()
    v = video.item("tl_one")
    video._WANT.add("tl_one")
    assert video.availability(v) == "downloading"
    assert TestClient(__import__("app.main", fromlist=["app"]).app).get("/api/video/tl_one/available").json()["status"] == "downloading"
    video.STATE["state"] = "running"
    assert video.course_progress()["state"] == "downloading"
    video.STATE["state"] = "paused"
    assert video.course_progress()["state"] == "paused"
    psr = video.item("psr")
    video._WANT.add("psr")
    assert video.availability(psr) != "downloading", "a Moon video never waits: the Moon is unchanged"


def test_network_download_with_the_same_rules(env, monkeypatch):
    make_video_pack(courses.packs_dir(), bundled=False)
    _switch()
    monkeypatch.setattr(settings, "video_prefetch", True)
    monkeypatch.setattr(settings, "video_offline", False)
    monkeypatch.setattr(video, "online", lambda kind="nasa": True)
    got = []

    def fake_download(self, url, name, *, size=None, sha256=None, pinned=False, pace=None, client=None, chunk=0):
        got.append((url, name, size, sha256, pinned))
        vid = name[:-4]
        p = self.path(name)
        self.root.mkdir(parents=True, exist_ok=True)
        p.write_bytes((vid * 4000).encode())
        self.add(name, pinned)
        return p
    monkeypatch.setattr(video.Cache, "download", fake_download)
    monkeypatch.setattr(video, "fetch_captions", lambda *a, **k: False)
    monkeypatch.setattr(video, "fetch_poster", lambda *a, **k: False)
    assert video.kick(wait=True) is True
    assert [g[1] for g in got] == ["tl_one.mp4", "tl_two.mp4"]
    assert all(g[0].startswith("https://images-assets.nasa.gov/") and g[2] and g[3] and g[4] for g in got), \
        "the catalog's size + sha256, pinned"
    assert video.course_progress()["state"] == "done"


def test_offline_or_school_network_drops_the_ask(env, monkeypatch):
    make_video_pack(courses.packs_dir(), bundled=False)
    _switch()
    monkeypatch.setattr(settings, "video_prefetch", True)
    monkeypatch.setattr(settings, "video_offline", False)
    monkeypatch.setattr(video, "online", lambda kind="nasa": False)   # School network mode answers no here too
    assert video.kick(wait=True) is True
    assert not video._WANT and video.STATE["state"] == "offline"
    assert video.availability(video.item("tl_one")) == "offline"
    from app import netgate
    monkeypatch.setattr(netgate, "policy", lambda: {"school_network": True, "allow_hosts": []})
    assert video.course_progress()["reason"] == "school"


def test_a_running_download_takes_the_switch_items_next(env, monkeypatch):
    make_video_pack(courses.packs_dir(), bundled=False)
    _switch()
    order = []
    monkeypatch.setattr(video, "fetch_video", lambda v, pace=None, client=None: order.append(v["id"]))
    one, two = video.item("tl_one"), video.item("tl_two")
    assert video._run.acquire(blocking=False)
    try:
        assert video.prefetch_all(items=[two])["state"] == "busy"
        assert [v["id"] for v in video._front] == ["tl_two"]
    finally:
        video._run.release()
    out = video.prefetch_all(items=[one])
    assert order == ["tl_two", "tl_one"], "the switch's videos first"
    assert out["state"] == "done" and not video._front


def test_a_running_run_picks_up_front_items_mid_way(env, monkeypatch):
    make_video_pack(courses.packs_dir(), bundled=False)
    _switch()
    order, gate = [], threading.Event()
    one, two = video.item("tl_one"), video.item("tl_two")

    def fv(v, pace=None, client=None):
        order.append(v["id"])
        if v["id"] == "tl_one":
            with video._q_lock:
                video._front.append(two)
    monkeypatch.setattr(video, "fetch_video", fv)
    out = video.prefetch_all(items=[one])
    assert order == ["tl_one", "tl_two"] and out["total"] == 2 and out["done"] == 2


# ---------------------------------------------------------------- the pack itself --------------------------------------
@pytest.fixture
def desktop(tmp_path, monkeypatch, env):
    """The desktop app's assets folder (it runs downloads through the .want flag) and a catalog with min_version."""
    assets = tmp_path / "assets"
    assets.mkdir()
    monkeypatch.delenv("COURSE_PACK_SRC", raising=False)
    monkeypatch.setenv("ASSETS_DIR", str(assets))
    m = json.loads(courses.ASSETS_MANIFEST.read_text())
    m["assets"].append({"id": "course_testland", "title": "Course: Testland", "required": False, "on_demand": True,
                        "file": "t.tar", "url": "https://www.dropbox.com/x/t.tar?dl=1", "sha256": "0" * 64,
                        "size": 1000, "unpacked_size": 1000, "version": "2", "min_version": "2", "files": []})
    man = tmp_path / "assets.manifest.json"
    man.write_text(json.dumps(m))
    monkeypatch.setattr(courses, "ASSETS_MANIFEST", man)
    make_video_pack(courses.packs_dir())
    return assets


def _installed(assets: Path, version: str):
    (assets / "state.json").write_text(json.dumps({"course_testland": {"version": version, "files": []}}))


def test_an_outdated_pack_is_asked_for_on_the_switch(desktop):
    _installed(desktop, "1")
    _switch()
    e = course_packs.entry("testland")
    assert course_packs.state(e) == {"state": "installed", "outdated": True}
    st = course_packs.ensure_active()
    assert st["updating"] and (desktop / ".want" / "course_testland").exists()
    # the desktop app downloads it: progress in .active, the course still plays meanwhile
    (desktop / ".active").mkdir()
    (desktop / ".active" / "course_testland").write_text("250 1000")
    assert course_packs.state(e) == {"state": "installed", "updating": True, "progress": 0.25}
    p = course_packs.active_progress()
    assert p["busy"] and p["progress"] == 0.25 and p["course"] == "testland"
    row = next(r for r in course_packs.listing()["packs"] if r["id"] == "testland")
    assert row["active"] and row["updating"] and row["videos"]["total"] == 2


def test_an_up_to_date_pack_is_left_alone(desktop):
    _installed(desktop, "2")
    _switch()
    assert course_packs.ensure_active() == {"state": "installed"}
    assert not (desktop / ".want" / "course_testland").exists()


def test_school_network_never_asks_for_the_pack(desktop, monkeypatch):
    _installed(desktop, "1")
    _switch()
    monkeypatch.setattr(course_packs, "school_blocks", lambda urls: True)
    assert course_packs.ensure_active()["outdated"]
    assert not (desktop / ".want" / "course_testland").exists()
