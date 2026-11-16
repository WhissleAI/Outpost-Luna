"""NASA video (app/video.py, docs/MEDIA.md): the catalog contract, the downloader (resume, checksum, atomic rename),
the LRU cache with pinned files, the routes offline, and the lesson's video step (a fixture lesson, never course.json)."""
import copy
import hashlib
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import hotlist, turn_router as R, video
from app.academy import content, grade as g
from app.config import settings
from app.main import app

CONTRACT_IDS = {
    "nasa_file": {"phases_loop", "lunar_eclipse", "hammer_feather", "lunar_dust", "psr", "water_extraction",
                  "moon_weather", "moon_base_6mo"},
    "youtube": {"far_side_view": "jdkMHkF7BaA", "solar_eclipse_sp": "hyf5JF_VxwM", "south_pole_shadows": "0GCTOHu4OrQ",
                "artemis_south_pole": "AQAaAJW-uC0", "solar_eruptions": "bX0hv0EFKnI", "impact_flashes": "B9MoWCnmuqw",
                "meet_crew": "lPyl6d2FJGw", "ltv": "zTHJ9zb8J2s",
                # [diy videos] Mission prep "Watch how" (2 hand-picked non-NASA + 1 NASA)
                "diy_crater": "osdOQhRhVJg", "diy_oreo_phases": "XeBmuY2i2fg", "moon_phases_2025": "RROlja1ob_4"},
}


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", tmp_path)
    monkeypatch.setattr(settings, "video_offline", True)
    return video.cache()


# ---------------------------------------------------------------- catalog --------------------------------------------
def test_catalog_valid_and_matches_the_contract():
    cat = video.catalog()
    assert video.validate(cat) == []
    ids = [v["id"] for v in cat]
    assert len(ids) == len(set(ids)), "ids are unique"
    by = {v["id"]: v for v in cat}
    for vid in CONTRACT_IDS["nasa_file"]:
        v = by[vid]
        assert v["source"] == "nasa_file" and v["prefetch"] is True and v["music_credit"] is False
        assert v["file_url"].startswith("https://") and v["bytes"] > 0 and len(v["sha256"]) == 64
        assert v["credit"].startswith("NASA")
    for vid, yid in CONTRACT_IDS["youtube"].items():
        v = by[vid]
        assert v["source"] == "youtube" and v["youtube_id"] == yid and not v["prefetch"] and "file_url" not in v
    assert set(by) == CONTRACT_IDS["nasa_file"] | set(CONTRACT_IDS["youtube"])
    # about 200 MB pinned (the plan's "about 210 MB with captions and posters")
    assert 150e6 < sum(v.get("bytes", 0) for v in cat if v["prefetch"]) < 260e6


def test_catalog_validation_catches_mistakes():
    good = copy.deepcopy(video.catalog())
    assert video.validate(good) == []
    bad = copy.deepcopy(good)
    bad[1]["id"] = bad[0]["id"]                                  # duplicate
    bad[2]["source"] = "vimeo"                                   # bad source
    bad[3]["music_credit"] = True                                # music in a cached file
    bad[4].pop("bytes")                                          # prefetch without a size
    bad[5]["file_url"] = "https://example.com/x.mp4"             # not a NASA host
    bad[8]["fallback"] = "nope"                                  # unknown fallback
    bad[9]["fallback"] = "far_side_view"                         # fallback must play offline
    bad[10]["prefetch"] = True                                   # YouTube is never downloaded
    p = "\n".join(video.validate(bad))
    for frag in ("duplicate id", "source must be", "music-credited", "size in bytes", "NASA host",
                 "'nope' is not another", "must be a nasa_file", "never downloaded"):
        assert frag in p, (frag, p)
    assert video.validate([]) and video.validate({"x": 1})


def test_srt_to_vtt():
    srt = "﻿1\r\n00:00:01,500 --> 00:00:03,250\r\nHello Moon\r\n\r\n2\r\n00:01:02,000 --> 00:01:04,000\r\nBye\r\n"
    vtt = video.srt_to_vtt(srt)
    assert vtt.startswith("WEBVTT\n\n1\n00:00:01.500 --> 00:00:03.250\nHello Moon")
    assert "00:01:02.000 --> 00:01:04.000" in vtt and video.has_cues(vtt)
    assert not video.has_cues(video.srt_to_vtt("WEBVTT FILE\n\n"))   # NASA's empty caption files count as none


# ---------------------------------------------------------------- downloader -----------------------------------------
BODY = bytes(range(256)) * 400   # 102,400 bytes
SHA = hashlib.sha256(BODY).hexdigest()


def server(log, *, ranges=True, body=BODY):
    def handle(req: httpx.Request) -> httpx.Response:
        rng = req.headers.get("range")
        log.append(rng)
        if rng and ranges:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(body):
                return httpx.Response(416)
            return httpx.Response(206, content=body[start:],
                                  headers={"content-range": f"bytes {start}-{len(body) - 1}/{len(body)}"})
        return httpx.Response(200, content=body)
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_download_resumes_checks_and_renames(tmp_path):
    c, log = video.Cache(tmp_path, 10**9), []
    (tmp_path / "a.mp4.part").write_bytes(BODY[:40000])           # a download cut off half way
    p = c.download("https://images-assets.nasa.gov/a.mp4", "a.mp4", size=len(BODY), sha256=SHA, client=server(log))
    assert log == ["bytes=40000-"], "resumed from the .part"
    assert p.read_bytes() == BODY and not (tmp_path / "a.mp4.part").exists() and c.has("a.mp4")
    # already cached: no request at all
    c.download("https://images-assets.nasa.gov/a.mp4", "a.mp4", size=len(BODY), client=server(log))
    assert log == ["bytes=40000-"]


def test_download_restarts_when_the_server_ignores_range(tmp_path):
    c, log = video.Cache(tmp_path, 10**9), []
    (tmp_path / "b.mp4.part").write_bytes(b"x" * 500)
    p = c.download("https://x.nasa.gov/b", "b.mp4", size=len(BODY), sha256=SHA, client=server(log, ranges=False))
    assert p.read_bytes() == BODY


def test_download_checksum_and_size_mismatch_never_land(tmp_path):
    c = video.Cache(tmp_path, 10**9)
    with pytest.raises(video.DownloadError, match="sha256"):
        c.download("https://x/c", "c.mp4", size=len(BODY), sha256="0" * 64, client=server([]))
    assert not (tmp_path / "c.mp4").exists() and not (tmp_path / "c.mp4.part").exists() and not c.has("c.mp4")
    with pytest.raises(video.DownloadError, match="expected"):
        c.download("https://x/d", "d.mp4", size=len(BODY) + 10, client=server([]))
    assert not (tmp_path / "d.mp4").exists(), "a short file stays a .part (resumable), never the real name"
    assert (tmp_path / "d.mp4.part").exists()


def test_lru_eviction_never_touches_pinned(tmp_path):
    c = video.Cache(tmp_path, 250)
    for n in ("p1.mp4", "o1.mp4", "o2.mp4"):
        (tmp_path / n).write_bytes(b"x" * 100)
    c.add("p1.mp4", pinned=True)
    time.sleep(0.01)
    c.add("o1.mp4")
    time.sleep(0.01)
    c.add("o2.mp4")                           # 300 > 250: the oldest unpinned goes
    assert c.has("p1.mp4") and not c.has("o1.mp4") and c.has("o2.mp4")
    time.sleep(0.01)
    c.touch("o2.mp4")
    (tmp_path / "o3.mp4").write_bytes(b"x" * 100)
    c.add("o3.mp4")                           # o2 is the least recently played now
    assert c.has("p1.mp4") and not c.has("o2.mp4") and c.has("o3.mp4")
    small = video.Cache(tmp_path / "s", 50)   # pinned files stay even over the cap
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "p.mp4").write_bytes(b"x" * 100)
    assert small.add("p.mp4", pinned=True) == [] and small.has("p.mp4")
    assert c.clear() > 0 and c.stats()["files"] == 0


def test_prefetch_downloads_only_pinned_and_pauses_for_a_mission(tmp_cache, monkeypatch):
    from app.mission import registry
    got = []

    def fake_fetch(v, pace=None, client=None):
        pace()
        got.append(v["id"])
    monkeypatch.setattr(video, "fetch_video", fake_fetch)
    waits = []
    monkeypatch.setattr(video.time, "sleep", lambda s: waits.append(s))
    registry.LAST_ACTIVE[0] = 0.0
    out = video.prefetch_all(pace=video._pace(sleep_s=0))
    assert set(got) == CONTRACT_IDS["nasa_file"] and out["state"] == "done"
    # a mission ticking: the pace hook waits (and says "paused") until it has been quiet
    ticks = iter([True, True, False])
    monkeypatch.setattr(video, "busy", lambda: next(ticks))
    video._pace(sleep_s=0)()
    assert waits.count(2.0) == 2


# ---------------------------------------------------------------- routes ---------------------------------------------
def test_routes_offline(tmp_cache):
    with TestClient(app) as c:
        cat = c.get("/api/video/catalog").json()
        assert [v["id"] for v in cat] == [v["id"] for v in video.catalog()]
        ph = next(v for v in cat if v["id"] == "phases_loop")
        assert ph["play_url"] == "/api/video/phases_loop/file" and ph["cached"] is False
        assert c.get("/api/video/phases_loop/available").json()["status"] == "offline"
        assert c.get("/api/video/far_side_view/available").json()["status"] == "offline"
        assert c.get("/api/video/phases_loop/file").status_code == 503
        assert c.get("/api/video/far_side_view/file").status_code == 404
        assert c.get("/api/video/nope/available").status_code == 404
        # now it is saved: it plays offline, with Range (seeking)
        v = video.item("phases_loop")
        body = b"\0" * 5000
        (tmp_cache.root).mkdir(parents=True, exist_ok=True)
        (tmp_cache.root / "phases_loop.mp4").write_bytes(body)
        tmp_cache.add("phases_loop.mp4", pinned=True)
        (tmp_cache.root / "phases_loop.jpg").write_bytes(b"jpg")
        tmp_cache.add("phases_loop.jpg", pinned=True)
        assert c.get("/api/video/phases_loop/available").json()["status"] == "cached"
        r = c.get("/api/video/phases_loop/file", headers={"Range": "bytes=100-199"})
        assert r.status_code == 206 and len(r.content) == 100 and r.headers["content-type"] == "video/mp4"
        assert c.get("/api/video/phases_loop/poster").content == b"jpg"
        assert c.get("/api/video/far_side_view/poster").content == b"jpg", "YouTube offline: its NASA fallback's still"
        assert c.get("/api/video/phases_loop/captions.vtt").status_code == 404   # silent loop: no captions
        tmp_cache.put_text("psr.vtt", "WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n")
        assert c.get("/api/video/psr/captions.vtt").text.startswith("WEBVTT")
        st = c.get("/api/video/cache").json()
        assert st["bytes"] == 5003 + len("WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n") and st["pinned_ready"] == 1
        assert st["pinned_total"] == 8 and st["cap_bytes"] == 1024 * 1024 * 1024
        assert c.delete("/api/video/cache").json()["bytes"] == 0
        assert c.get("/api/video/phases_loop/available").json()["status"] == "offline"
        assert v["bytes"] > 0


# ---------------------------------------------------------------- the lesson's video step ----------------------------
def fixture_course():
    """A fixture lesson with a video step (tests only; course.json belongs to the learning content)."""
    return content.normalize({
        "title": "T", "pass_badge": "b2", "lessons": [{
            "id": "fx", "title": "Fixture", "brief": "A test.", "badge": {"id": "b1", "name": "B"}, "facts": [],
            "steps": [
                {"type": "video", "media": "hammer_feather", "say": "Hammer or feather: which lands first?",
                 "reveal": "Both at once. No air on the Moon."},
                {"prompt": "Pick one.", "accept": {"type": "choice", "answer": "a",
                                                   "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
                 "hint": "h", "success": "s", "fail": "f"},
            ]}]})


@pytest.fixture
def fx(monkeypatch):
    c = fixture_course()
    monkeypatch.setattr(content, "course", lambda: c)
    return c


def test_video_step_shape_and_check(fx):
    st = fx["lessons"][0]["steps"][0]
    assert st["accept"] == {"type": "video", "media": "hammer_feather"} and st["prompt"].startswith("Hammer")
    assert st["success"] == st["reveal"]
    pub = content.public()["lessons"][0]["steps"][0]
    assert pub["type"] == "video" and pub["media"] == "hammer_feather" and pub["accept"]["media"] == "hammer_feather"
    assert pub["say"] and pub["reveal"]
    assert content.check_video_step(st) == []
    assert "not in the video catalog" in content.check_video_step({**st, "media": "nope"})[0]
    assert any("needs reveal" in p for p in content.check_video_step({**st, "reveal": ""}))


@pytest.mark.parametrize("inp,watched", [({"video": {"watched": True, "seconds": 47.9}}, True),
                                         ({"video": {"watched": False, "skipped": True, "seconds": 0}}, False),
                                         ({"video": {"watched": False, "offline": True}}, False),
                                         ({"text": "skip it"}, False)])
def test_video_step_always_continues_with_the_reveal(fx, inp, watched):
    with TestClient(app) as c:
        r = c.post("/api/academy/attempt", json={"lesson_id": "fx", "step": 0, "input": inp}).json()
    assert r["status"] == "passed" and r["say"] == "Both at once. No air on the Moon." and r["next_step"] == 1
    assert r["watched"] is watched
    assert any(d["t"] == "say" and d["text"] == r["say"] for d in r["decisions"])


def test_video_step_room_talk_is_not_a_try(fx):
    with TestClient(app) as c:
        r = c.post("/api/academy/attempt", json={"lesson_id": "fx", "step": 0,
                                                  "input": {"text": "my sister has the remote"}}).json()
    assert r["status"] == "ignored" and r.get("next_step") is None
    st = fx["lessons"][0]["steps"][0]
    assert g.plausible(st, "skip") and g.plausible(st, "watch it") and g.plausible(st, "two")


def test_router_video_screen_takes_only_its_controls():
    ctx = R.Ctx(screen="video", source="voice")
    for text, want in [("pause", "video_pause"), ("play it", "video_play"), ("skip", "video_skip"),
                       ("stop the video", "video_stop"), ("okay pause please", "video_pause")]:
        out = R.route(text, ctx)
        assert out["outcome"] == "navigate" and out["intent"] == want, (text, out)
    for text in ("where did apollo 11 land", "next lesson please now", "go to the mission"):
        assert R.route(text, ctx)["outcome"] == "ignore", text
    assert hotlist.hot_lists({"screen": "video"})["step"][:4] == ["pause", "play", "skip", "stop"]


def test_catalog_is_valid_json_file():
    json.loads(video.catalog_path().read_text(encoding="utf-8"))


# ---------------------------------------------------------------- [diy videos] Mission prep "Watch how" ------------
def test_prep_videos_are_labelled_allow_listed_and_belong_to_real_prep_tasks():
    from app.academy import content
    preps = {l["prep"]["id"] for l in content.course()["lessons"] if l.get("prep")}
    vids = [v for v in video.catalog() if v.get("prep")]
    assert {v["prep"] for v in vids} >= {"crater_drop", "oreo_phases"}
    assert any(v.get("nasa") is not False for v in vids), "at least one NASA-made Watch-how video"
    for v in vids:
        assert v["prep"] in preps, v["id"]
        assert v["source"] == "youtube" and not v["prefetch"] and v.get("channel"), v["id"]
        if v.get("nasa") is False:
            assert video.NON_NASA_YOUTUBE[v["youtube_id"]] == v["channel"]
            assert "not from NASA" in v["credit"]
        else:
            assert v["credit"].startswith("NASA") and v["youtube_id"] not in video.NON_NASA_YOUTUBE
    # every allow-listed non-NASA id is in the catalog (no stale allow-list entries)
    assert set(video.NON_NASA_YOUTUBE) == {v["youtube_id"] for v in video.catalog() if v.get("nasa") is False}


def test_non_nasa_videos_need_the_allow_list_and_a_label():
    good = copy.deepcopy(video.catalog())
    k = next(i for i, v in enumerate(good) if v["id"] == "diy_crater")
    for mutate, frag in [
        (lambda v: v.update(youtube_id="AAAAAAAAAAA"), "NON_NASA_YOUTUBE"),            # not hand-picked
        (lambda v: v.update(channel="Someone else"), "channel must be"),
        (lambda v: v.update(credit="Astronomy in Action"), "not from NASA"),
        (lambda v: v.pop("prep"), "Mission prep task"),
        (lambda v: v.update(nasa=True), "credit must start with NASA"),                 # can't pass as NASA
    ]:
        bad = copy.deepcopy(good); mutate(bad[k])
        assert any(frag in p for p in video.validate(bad)), (frag, video.validate(bad))
