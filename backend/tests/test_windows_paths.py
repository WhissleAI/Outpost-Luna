"""Windows behaviour of the backend, exercised on any OS (docs/BUILD_WINDOWS.md).

Windows differs from macOS in two ways that matter here: a file another handle has open cannot be deleted or replaced
(PermissionError, WinError 32: the video FileResponse is streaming, an antivirus is scanning), and the per-user folders
are %APPDATA%\\Outpost Luna\\... with backslashes and spaces. Both are simulated: a fake "locked" set makes unlink and
os.replace raise as Windows would, and the cache paths are Windows-shaped strings.
"""
from __future__ import annotations

import ntpath
import os
from pathlib import Path, PureWindowsPath

import pytest

from app import reset as R
from app import video
from app.config import settings


@pytest.fixture
def locked(monkeypatch):
    """Paths in this set behave like files another process holds open on Windows."""
    held: set[str] = set()
    real_unlink = Path.unlink

    def unlink(self, missing_ok=False):
        if str(self) in held:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process", str(self))
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    return held


def _fill(c: video.Cache, root: Path, names: dict[str, int]) -> None:
    for n, size in names.items():
        (root / n).write_bytes(b"x" * size)
        c.add(n)


def test_eviction_skips_a_video_that_is_playing_and_keeps_its_index_entry(tmp_path, locked):
    c = video.Cache(tmp_path, 10**9)
    _fill(c, tmp_path, {"old.mp4": 100, "mid.mp4": 100})
    locked.add(str(tmp_path / "old.mp4"))           # the oldest is on screen right now
    c.cap = 150
    (tmp_path / "new.mp4").write_bytes(b"x" * 100)
    gone = c.add("new.mp4")                          # must not raise (it used to: PermissionError out of add/download)
    assert gone == ["mid.mp4"]
    assert c.has("old.mp4") and c.has("new.mp4") and not c.has("mid.mp4")
    locked.clear()                                   # the player let go: the next eviction takes it
    assert "old.mp4" in c.evict()


def test_clear_deletes_what_it_can_and_keeps_the_open_file_indexed(tmp_path, locked):
    c = video.Cache(tmp_path, 10**9)
    _fill(c, tmp_path, {"a.mp4": 100, "b.mp4": 50, "b.vtt": 10})
    locked.add(str(tmp_path / "a.mp4"))
    freed = c.clear()                                # Settings → Videos → Clear while a video plays
    assert freed == 60
    assert c.has("a.mp4") and not c.has("b.mp4") and c.stats()["files"] == 1
    locked.clear()
    assert c.clear() == 100 and c.stats()["files"] == 0


def test_replace_retries_a_moment_then_succeeds(tmp_path, monkeypatch):
    calls = []
    real = os.replace

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")   # antivirus holds the new file for a moment
        real(src, dst)

    monkeypatch.setattr(video.os, "replace", flaky)
    monkeypatch.setattr(video.time, "sleep", lambda s: None)
    (tmp_path / "x.tmp").write_text("hi")
    video._replace(tmp_path / "x.tmp", tmp_path / "x.vtt")
    assert (tmp_path / "x.vtt").read_text() == "hi" and len(calls) == 3


def test_replace_gives_up_with_the_real_error(tmp_path, monkeypatch):
    monkeypatch.setattr(video.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "Access is denied")))
    monkeypatch.setattr(video.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        video._replace(tmp_path / "a", tmp_path / "b", tries=3)


def test_reset_everything_survives_a_locked_video(tmp_path, monkeypatch, locked):
    """The backend empties what it can; the desktop shell (reset.js) deletes the folder after stopping the children."""
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setenv("TURNLOG_DIR", "")
    vd = tmp_path / "cache" / "video"
    vd.mkdir(parents=True)
    (vd / "psr.mp4").write_bytes(b"x" * 10)
    (vd / "tli.mp4").write_bytes(b"x" * 10)
    locked.add(str(vd / "psr.mp4"))
    out = R.reset("all")
    assert out["level"] == "all"
    assert not (vd / "tli.mp4").exists() and (vd / "psr.mp4").exists()


def test_per_user_cache_folders_follow_cache_dir_with_windows_paths(monkeypatch):
    """CACHE_DIR is %APPDATA%\\Outpost Luna\\cache on Windows (desktop/main/main.js envFor): every cache is joined under
    it with the platform's own path rules, never a hard-coded "/" (a Windows Path joins with backslashes)."""
    appdata = r"C:\Users\Cadet One\AppData\Roaming\Outpost Luna\cache"
    monkeypatch.setattr(settings, "cache_dir", PureWindowsPath(appdata))
    monkeypatch.delenv("LEARN_DIR", raising=False)
    monkeypatch.delenv("BRAIN_DIR", raising=False)
    for p in (settings.tts_cache(), settings.video_cache(), settings.vector_cache()):
        assert isinstance(p, PureWindowsPath) and ntpath.dirname(str(p)) == appdata, p
    for p in R.targets("all")["all"][1:]:            # [0] is the turn log (TURNLOG_DIR or CACHE_DIR\turnlog)
        assert str(p).startswith(appdata + "\\"), p
