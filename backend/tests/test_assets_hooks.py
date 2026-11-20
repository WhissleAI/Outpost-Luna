"""First-run assets on the backend side (docs/DESKTOP.md "First run: assets"): the crew-audio asset served from its own
folder, trim.json picked up once it installs, the pinned videos copied from the installed video pack (no network), and
the voice pack found in its asset folder."""
import asyncio
import hashlib
import threading
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main as M, tts, video
from app.config import settings

REAL_PACK_VERSION = tts.pack_version   # conftest stubs it per test (no_voice_pack)


def test_media_served_from_the_asset_folder_first(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "media/img").mkdir(parents=True)
    (data / "media/img/moon.jpg").write_bytes(b"jpg")
    crew = tmp_path / "assets/crew"
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "media_audio_dir", crew)
    a = FastAPI()
    a.mount("/media", M.MediaFiles(settings.media_dirs()))
    c = TestClient(a)
    assert c.get("/media/img/moon.jpg").content == b"jpg"           # bundled media still served
    assert c.get("/media/audio/x.mp3").status_code == 404           # crew asset not installed yet: no crash
    (crew / "audio").mkdir(parents=True)
    (crew / "audio/x.mp3").write_bytes(b"0123456789")
    r = c.get("/media/audio/x.mp3", headers={"Range": "bytes=2-5"})
    assert r.status_code == 206 and r.content == b"2345"            # installed later: served, with Range


def test_clip_segs_reads_trim_json_once_it_appears(tmp_path, monkeypatch):
    crew = tmp_path / "crew"
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "media_audio_dir", crew)
    monkeypatch.setitem(M.S, "clip_segs", {})
    assert M.clip_segs("/media/audio/a.mp3") is None
    crew.mkdir()
    (crew / "trim.json").write_text(json.dumps({"clips": {"a.mp3": {"segs": [[0, 0, 5]]}}}))
    assert M.clip_segs("/media/audio/a.mp3") == [[0, 0, 5]]


def test_pinned_video_comes_from_the_pack_offline(tmp_path, monkeypatch):
    body = b"fake mp4 bytes"
    v = {"id": "demo_vid", "source": "nasa_file", "prefetch": True, "file_url": "https://images-assets.nasa.gov/x.mp4",
         "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "demo_vid.mp4").write_bytes(body)
    (pack / "demo_vid.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n")
    (pack / "demo_vid.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "video_pack_dir", pack)
    monkeypatch.setattr(settings, "video_prefetch", False)          # the desktop with a pack: no nasa.gov prefetch
    monkeypatch.setattr(video, "catalog", lambda: [v])
    monkeypatch.setattr(video, "online", lambda kind="nasa": False)

    def no_net(*a, **k):
        raise AssertionError("must not touch the network")
    monkeypatch.setattr(video.Cache, "download", no_net)
    monkeypatch.setattr(video, "_stop", threading.Event())   # an earlier TestClient's shutdown set the module's stop flag
    asyncio.run(video.prefetch_task(delay_s=0, retry_s=0.01))
    c = video.cache()
    assert video.is_cached(v) and c.has("demo_vid.vtt") and c.has("demo_vid.jpg")
    assert c._load()["demo_vid.mp4"]["pinned"] is True
    # a pack file that does not match the catalog is never used
    (pack / "bad_vid.mp4").write_bytes(b"other")
    assert video.from_pack({**v, "id": "bad_vid"}, "video") is False


def test_pack_copy_of_a_nasa_file_is_accepted(tmp_path, monkeypatch):
    """Video pack v3 carries a lighter re-encode of each NASA file (catalog `pack`): it is copied like the original,
    the original (pack v2, still installed on older setups) still is, and anything else is not."""
    orig, lite = b"the NASA original bytes", b"lighter"
    v = {"id": "lite_vid", "source": "nasa_file", "prefetch": True, "file_url": "https://images-assets.nasa.gov/x.mp4",
         "bytes": len(orig), "sha256": hashlib.sha256(orig).hexdigest(),
         "pack": {"derive": "-c:v libx264", "bytes": len(lite), "sha256": hashlib.sha256(lite).hexdigest()}}
    pack = tmp_path / "pack"
    pack.mkdir()
    monkeypatch.setattr(settings, "video_pack_dir", pack)
    for i, (body, ok) in enumerate(((lite, True), (orig, True), (b"lightex", False), (b"x" * len(lite), False))):
        monkeypatch.setattr(settings, "cache_dir", tmp_path / f"cache{i}")
        (pack / "lite_vid.mp4").write_bytes(body)
        assert video.from_pack(v, "video") is ok, body
        assert video.pack_copy_ok(v, pack / "lite_vid.mp4") is ok
    assert not any("pack" in p for p in video.validate([v]))
    bad = {**v, "pack": {"derive": "-c:v libx264", "bytes": 3}}
    assert any("pack needs its bytes and sha256" in p for p in video.validate([bad]))
    assert any("only a pinned nasa_file" in p for p in video.validate([{**v, "prefetch": False}]))


def test_voice_pack_dir_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "voice_pack_dir", tmp_path)
    assert REAL_PACK_VERSION() == ""
    (tmp_path / "index.json").write_text("{}")
    assert REAL_PACK_VERSION()
