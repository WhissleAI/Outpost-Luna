"""Trimmed desktop crew audio (pipeline/trim_media.py): every span the app can play stays inside one kept stretch, and
GET /api/clips/<id> carries the clip->file time map when the bundle has one (media/trim.json)."""
import json

from fastapi.testclient import TestClient

from app import main
from app.main import app
from pipeline.trim_media import MARGIN, keep_ranges, playable_spans


def test_keep_ranges_pads_merges_and_clips():
    assert keep_ranges([(5, 10), (11, 12), (30, 40)], dur=40.5) == [(5 - MARGIN, 12 + MARGIN), (30 - MARGIN, 40.5)]
    assert keep_ranges([(0.2, 3)])[0][0] == 0.0
    assert keep_ranges([]) == []


def test_every_playable_span_fits_in_one_kept_stretch():
    spans = playable_spans()
    clips = {c["id"]: c for c in json.loads((main.settings.data_dir / "index/clips.json").read_text())["clips"]}
    assert set(spans) <= set(clips)
    assert {"liftoff", "lovell", "duke", "hansen"} <= set(spans)       # sounds, lessons and artifact voices
    for cid, sp in spans.items():
        kept = keep_ranges(sp)
        for a, b in sp:
            assert any(k0 <= max(0.0, a) and b + 0.25 <= k1 for k0, k1 in kept), (cid, a, b)   # + the player's fade


def test_clip_route_adds_segs_only_with_a_trim_map(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setitem(main.S, "clip_segs", {})
        assert "segs" not in c.get("/api/clips/liftoff").json()
        f = c.get("/api/clips/liftoff").json()["file"].rsplit("/", 1)[-1]
        monkeypatch.setitem(main.S, "clip_segs", {f: [[0.0, 0.0, 26.1]]})
        assert c.get("/api/clips/liftoff").json()["segs"] == [[0.0, 0.0, 26.1]]
