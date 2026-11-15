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


def test_voice_pack_dir_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "voice_pack_dir", tmp_path)
    assert REAL_PACK_VERSION() == ""
    (tmp_path / "index.json").write_text("{}")
    assert REAL_PACK_VERSION()
