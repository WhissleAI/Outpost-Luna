"""Settings → Reset Outpost Luna (app/reset.py, docs/RESET.md): what each level clears, and who may ask."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import reset as R
from app.config import settings


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setenv("TURNLOG_DIR", "")
    for sub, files in {"tts": ["a.mp3", "a.words"], "turnlog": ["2026-11-15.jsonl"], "video": ["psr.mp4", "index.json"],
                       "vectors": ["card_vectors_x.npy"]}.items():
        d = tmp_path / "cache" / sub
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_text("x")
    return tmp_path / "cache"


def _left(c: Path) -> dict:
    return {d.name: sorted(p.name for p in d.iterdir()) for d in sorted(c.iterdir())}


def test_targets_come_from_settings_not_hard_coded(tmp_cache):
    t = R.targets("all")
    assert all(str(p).startswith(str(tmp_cache)) for p in t["all"])
    assert set(t["start"]) < set(t["all"])


def test_start_over_clears_the_turn_log_and_spoken_lines_but_keeps_videos_and_vectors(tmp_cache):
    from app.mission import registry
    from app import session
    registry.MISSIONS["m1"] = object()
    session.SESSIONS["s1"] = object()
    out = R.reset("start")
    left = _left(tmp_cache)
    assert left["tts"] == [] and left["turnlog"] == []
    assert left["video"] == ["index.json", "psr.mp4"] and left["vectors"] == ["card_vectors_x.npy"]
    assert out["memory"]["missions"] >= 1 and not registry.MISSIONS and not session.SESSIONS


def test_reset_everything_also_clears_the_video_and_vector_caches(tmp_cache):
    R.reset("all")
    left = _left(tmp_cache)
    assert all(v == [] for k, v in left.items() if k != "video")
    assert [n for n in left["video"] if n.endswith(".mp4")] == []


def test_the_downloaded_assets_hook_exists_for_first_run_downloads():
    assert R.reset_downloaded_assets() == []   # TODO(feat/arc-space): deletes the first-run downloads


def test_only_our_own_page_may_ask_and_the_desktop_token_is_one_use(tmp_cache):
    from app.main import app
    c = TestClient(app)
    host = "testserver"
    assert c.post("/api/reset?level=start").status_code == 403                                     # no origin, no header
    assert c.post("/api/reset?level=start", headers={"X-Outpost-Reset": "1", "Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/reset?level=start", headers={"Origin": f"http://{host}"}).status_code == 403   # no header
    assert c.post("/api/reset?level=nope", headers={"X-Outpost-Reset": "1", "Origin": f"http://{host}"}).status_code == 400
    r = c.post("/api/reset?level=all", headers={"X-Outpost-Reset": "1", "Origin": f"http://{host}"})
    assert r.status_code == 200 and r.json()["level"] == "all"
    tok = r.json()["token"]
    assert c.get(f"/api/reset/confirm?token={tok}").json() == {"level": "all"}
    assert c.get(f"/api/reset/confirm?token={tok}").status_code == 404   # one use
    assert c.get("/api/reset/confirm?token=made-up").status_code == 404


def test_voice_reset_is_routed_to_the_client_a11y_handler_which_only_opens_the_confirm():
    from app import turn_router as T
    pats = [p for n, p in T.NAV if n == "a11y"]
    for t in ["reset", "reset the app", "reset everything", "erase my progress", "start the whole game over"]:
        assert any(p.match(t) for p in pats), t
    assert not any(p.match("reset the voice bar") for p in pats[-1:])
