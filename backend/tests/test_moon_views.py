"""Open Moon data (app/moon_views.py, scripts/moon_views_build.py, the optional moon_views asset): the API and its
path / licence checks, the build's contract (validate_index), and the asset manifest entries for moon_views and the
Archaeology pack v3."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import moon_views as mv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import moon_views_build as mb  # noqa: E402
import nasa_views_build as nb  # noqa: E402


def _index(**over):
    idx = {"schema": 1, "pack": "moon_views", "version": "1", "credit": mb.CREDIT,
           "photos": [{"id": "apollo11", "file": "photos/apollo11.jpg", "site": "apollo11", "title": "T", "caption": "C",
                       "nasa_id": "as11-40-5903", "credit": "NASA", "source": "https://images.nasa.gov/details/as11-40-5903",
                       "licence_class": "pd", "alt": "A"}],
           "layers": [{"id": "rock_ages", "file": "layers/rock_ages.png", "title": "Rock ages", "credit": "USGS",
                       "source": "https://astrogeology.usgs.gov/x", "licence_class": "cc0", "alt": "A",
                       "bounds": {"west": -180, "south": -90, "east": 180, "north": 90}, "legend": [{"color": "#cde2fb", "label": "C"}]}],
           "models": [{"id": "columbia", "file": "models/columbia.glb", "title": "Columbia", "credit": "Smithsonian",
                       "source": "https://airandspace.si.edu/x", "licence_class": "cc0", "size": [3.6, 3.1, 3.9]}],
           "rock_facts": {"15016": {"facts": ["It weighs 923.7 grams."], "licence_class": "pd"}}}
    idx.update(over)
    return idx


@pytest.fixture
def pack(tmp_path, monkeypatch):
    for rel in ("photos/apollo11.jpg", "layers/rock_ages.png", "models/columbia.glb"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    (tmp_path / "index.json").write_text(json.dumps(_index()))
    (tmp_path / "NOTICE").write_text("n")
    monkeypatch.setenv("MOON_VIEWS_DIR", str(tmp_path))
    monkeypatch.delenv("ASSETS_DIR", raising=False)
    return tmp_path


def _client():
    from app.main import app
    return TestClient(app)


def test_missing_then_ready(tmp_path, monkeypatch, pack):
    d = _client().get("/api/moon-views").json()
    assert d["state"] == "ready" and [p["id"] for p in d["photos"]] == ["apollo11"] and d["rock_facts"]["15016"]["facts"]
    monkeypatch.setenv("MOON_VIEWS_DIR", str(tmp_path / "nowhere"))
    assert _client().get("/api/moon-views").json() == {"state": "missing", "managed": False}


def test_entries_with_a_licence_we_do_not_ship_or_a_missing_file_are_dropped(pack):
    idx = _index()
    idx["photos"].append({**idx["photos"][0], "id": "apollo12", "file": "photos/apollo12.jpg", "licence_class": "by-nc"})
    idx["models"][0]["licence_class"] = "unknown"
    idx["layers"][0]["file"] = "layers/missing.png"
    (pack / "photos/apollo12.jpg").write_bytes(b"x")
    (pack / "index.json").write_text(json.dumps(idx))
    d = _client().get("/api/moon-views").json()
    assert [p["id"] for p in d["photos"]] == ["apollo11"] and d["models"] == [] and d["layers"] == []


def test_files_are_served_with_their_types_and_nothing_outside_the_pack(pack):
    c = _client()
    assert c.get("/api/moon-views/file/models/columbia.glb").headers["content-type"] == "model/gltf-binary"
    assert c.get("/api/moon-views/file/photos/apollo11.jpg").headers["content-type"] == "image/jpeg"
    for bad in ("photos/..%2Findex.json", "sky/x.jpg", "photos/a.b.jpg", "photos/x.svg", "photos/.x.jpg", "../NOTICE"):
        assert c.get(f"/api/moon-views/file/{bad}").status_code == 404, bad


def test_want_asks_the_desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSETS_DIR", str(tmp_path))
    assert _client().post("/api/moon-views/want").json() == {"ok": True, "managed": True}
    assert (tmp_path / ".want" / "moon_views").exists()


def test_validate_index_accepts_the_contract_and_rejects_nc_nd_unknown(pack):
    assert mb.validate_index(_index(), pack) == []
    for lc in ("by-nc", "nd", "unknown", None):
        idx = _index()
        idx["models"][0]["licence_class"] = lc
        assert any("licence_class" in e for e in mb.validate_index(idx)), lc
    idx = _index()
    idx["photos"][0]["file"] = "photos/../x.jpg"
    assert any("bad file" in e for e in mb.validate_index(idx))
    idx = _index(credit="something else")
    assert mb.validate_index(idx)


def test_the_build_covers_every_apollo_landing_and_the_trays_rocks():
    assert sorted(s for s, *_ in mb.PHOTOS) == ["apollo11", "apollo12", "apollo14", "apollo15", "apollo16", "apollo17"]
    arts = json.loads((ROOT / "backend/data/artifacts.json").read_text())
    arts = arts if isinstance(arts, list) else arts.get("artifacts", [])
    ids = {a["id"] for a in arts}
    for site, *_ in mb.PHOTOS:
        assert any(i.startswith(site + "_") and not i.endswith("_sivb_impact") for i in ids), f"{site}: a hardware marker to hang the photo on"
    rocks = {r[0] for r in nb.ROCKS}
    assert set(mb.ROCK_FACTS) <= rocks and all(len(f) <= 140 for v in mb.ROCK_FACTS.values() for f in v)
    assert [a for a, *_ in mb.AGES] == ["Copernican", "Eratosthenian", "Imbrian", "Nectarian", "Pre-Nectarian"]
    assert "LROC" in mb.__doc__ and "JAXA" in mb.__doc__, "what was skipped is written down"


def test_manifest_entries_for_moon_views_and_the_archaeology_pack():
    m = json.loads((ROOT / "desktop/assets.manifest.json").read_text())
    by = {a["id"]: a for a in m["assets"]}
    mv_ = by["moon_views"]
    assert mv_["required"] is False and mv_["env"] == "MOON_VIEWS_DIR" and mv_["min_app"] == "0.5.3" and mv_["licence"] == ["NOTICE"]
    assert {f["path"] for f in mv_["files"]} >= {"index.json", "NOTICE", "models/columbia.glb", "layers/rock_ages.png"}
    assert mv_["size"] < 30_000_000
    arch = by["course_archaeology"]
    # [0.5.6] v7: v6 plus the NPS rack card (library docs) and the seamless region overlay; v6 is the pack fallback
    assert arch["version"] == "7" and arch["min_version"] == "7" and arch["min_app"] == "0.5.3"
    assert arch["fallback"]["kind"] == "pack" and arch["fallback"]["version"] == "6", "the fallback is the published v6"
    assert {f["path"] for f in arch["files"]} >= {"media/drought_mesa_verde.json", "media/s2_mesa_verde.jpg", "video/arch_lidar_space.mp4",
                                                  "media/nps_rack_artifacts_p1.jpg", "media/nps_rack_artifacts.pdf"}
    assert arch["size"] - arch["fallback"]["size"] < 25_000_000
    assert (ROOT / "site/assets/manifest.json").read_text() == (ROOT / "desktop/assets.manifest.json").read_text()
    main_js = (ROOT / "desktop/main/main.js").read_text()
    assert "MOON_VIEWS_DIR: a.MOON_VIEWS_DIR" in main_js
