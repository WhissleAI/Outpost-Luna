"""0.4 "Real NASA views": the optional nasa_views asset as the backend serves it (app/nasa_views.py).
Missing / downloading / ready states, only files that are on disk listed, and a file route that serves nothing else."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import nasa_views as nv
from app.main import app

client = TestClient(app)
INDEX = {"schema": 1, "pack": "nasa_views", "version": "1", "credit": "Uses NASA open data and 3D models; not endorsed by NASA.",
         "sky": {"file": "sky/starmap_4k.jpg", "ra0_u": 0.5, "ra_increases": "left"},
         "models": [{"id": "apollo_lm", "file": "models/apollo_lm.glb"}, {"id": "lro", "file": "models/lro.glb"}],
         "rocks": [{"id": "15016", "file": "rocks/15016.glb", "name": "Basalt"}],
         "images": [{"id": "earthrise", "file": "images/earthrise.jpg"}, {"id": "evil", "file": "../secret.jpg"}],
         "sdo": {"frames": [{"file": "sdo/00.jpg"}, {"file": "sdo/01.jpg"}]},
         "names": {"file": "names/moon_names.json"}}


def pack(tmp_path, monkeypatch, files=("sky/starmap_4k.jpg", "models/apollo_lm.glb", "rocks/15016.glb", "images/earthrise.jpg", "sdo/00.jpg")):
    d = tmp_path / "nasa_views"
    for f in files:
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_bytes(b"x" * 10)
    (d / "index.json").write_text(json.dumps(INDEX))
    (tmp_path / "secret.jpg").write_bytes(b"secret")
    monkeypatch.setenv("NASA_VIEWS_DIR", str(d))
    return d


def test_missing_then_downloading_without_the_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("NASA_VIEWS_DIR", str(tmp_path / "none"))
    monkeypatch.delenv("ASSETS_DIR", raising=False)
    assert client.get("/api/views").json() == {"state": "missing", "managed": False}
    assets = tmp_path / "assets"
    (assets / ".active").mkdir(parents=True)
    monkeypatch.setenv("ASSETS_DIR", str(assets))
    assert client.get("/api/views").json()["state"] == "missing"
    (assets / ".active" / "nasa_views").write_text("")
    assert client.get("/api/views").json() == {"state": "downloading", "managed": True}
    assert client.get("/api/views/file/sky/starmap_4k.jpg").status_code == 404


def test_want_asks_the_desktop_for_the_asset(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSETS_DIR", raising=False)
    assert client.post("/api/views/want").json() == {"ok": False, "managed": False}
    monkeypatch.setenv("ASSETS_DIR", str(tmp_path))
    assert client.post("/api/views/want").json()["ok"] is True
    assert (tmp_path / ".want" / "nasa_views").exists()


def test_ready_lists_only_files_on_disk(tmp_path, monkeypatch):
    pack(tmp_path, monkeypatch)
    r = client.get("/api/views").json()
    assert r["state"] == "ready" and r["pack"] == "nasa_views"
    assert [m["id"] for m in r["models"]] == ["apollo_lm"]          # lro.glb is not on disk
    assert [i["id"] for i in r["images"]] == ["earthrise"]          # a path outside the pack is never listed
    assert [f["file"] for f in r["sdo"]["frames"]] == ["sdo/00.jpg"]
    assert r["names"] is None and r["sky"]["file"] == "sky/starmap_4k.jpg"


def test_file_route_types_and_no_escape(tmp_path, monkeypatch):
    pack(tmp_path, monkeypatch)
    r = client.get("/api/views/file/models/apollo_lm.glb")
    assert r.status_code == 200 and r.headers["content-type"] == "model/gltf-binary"
    assert client.get("/api/views/file/sky/starmap_4k.jpg").headers["content-type"] == "image/jpeg"
    for bad in ("/api/views/file/images/..%2Fsecret.jpg", "/api/views/file/secret/x.jpg", "/api/views/file/images/x.exe",
                "/api/views/file/images/.hidden.jpg", "/api/views/file/index.json/x"):
        assert client.get(bad).status_code == 404, bad


def test_a_broken_index_is_missing_not_an_error(tmp_path, monkeypatch):
    d = pack(tmp_path, monkeypatch)
    (d / "index.json").write_text("{not json")
    assert nv.load_index() is None
    assert client.get("/api/views").json()["state"] == "missing"
