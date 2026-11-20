"""scripts/asset_pack.py build(): a re-packed asset gets a NEW file name and the previous published pack as its fallback
(the upload must never overwrite the tar older apps download); an unchanged one keeps its name and url.

    uv run --no-project --with pytest python -m pytest -q desktop/tests
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("asset_pack", ROOT / "scripts/asset_pack.py")
AP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AP)


def run(tmp_path, monkeypatch, content: bytes, prev: dict) -> dict:
    monkeypatch.setattr(AP, "OUT", tmp_path)
    monkeypatch.setattr(AP, "ASSETS", [("crew", "Crew", False, lambda: [("audio/a.mp3", content)], ["NOTICE"],
                                        "MEDIA_AUDIO_DIR", "")])
    monkeypatch.setattr(AP.asset_manifest, "read", lambda: {"assets": [prev]})
    return AP.build(None)["assets"][0]


def published(tmp_path, monkeypatch) -> dict:
    a = run(tmp_path, monkeypatch, b"old bytes", {"id": "crew", "version": "1"})
    return {**a, "url": "https://www.dropbox.com/scl/fi/x/outpost-luna-v2-crew.tar?dl=1", "version": "1",
            "file": "outpost-luna-v2-crew.tar"}


def test_unchanged_asset_keeps_its_published_name_and_url(tmp_path, monkeypatch):
    prev = published(tmp_path, monkeypatch)
    a = run(tmp_path, monkeypatch, b"old bytes", prev)
    assert (a["file"], a["url"], a["sha256"]) == (prev["file"], prev["url"], prev["sha256"])
    assert (tmp_path / prev["file"]).exists()


def test_repacked_asset_gets_a_new_name_and_the_previous_pack_as_fallback(tmp_path, monkeypatch):
    prev = published(tmp_path, monkeypatch)
    a = run(tmp_path, monkeypatch, b"new lighter bytes", prev)
    assert a["file"] == "outpost-luna-v2-crew-2.tar" and a["url"] is None and a["sha256"] != prev["sha256"]
    assert (tmp_path / a["file"]).exists()
    fb = a["fallback"]
    assert (fb["kind"], fb["version"], fb["file"], fb["url"], fb["sha256"]) == \
        ("pack", "1", prev["file"], prev["url"], prev["sha256"])
    # rebuilt again before the upload: the next name, and still the last PUBLISHED pack as fallback
    b = run(tmp_path, monkeypatch, b"newer bytes", {**a, "version": "2"})
    assert b["file"] == "outpost-luna-v2-crew-3.tar" and b["fallback"]["file"] == prev["file"]


GH = "https://github.com/WhissleAI/Outpost-Luna/releases/download/assets-v2/outpost-luna-v2-crew.tar"


def test_mirrors_stay_with_the_same_bytes_and_ride_into_the_previous_pack(tmp_path, monkeypatch):
    prev = {**published(tmp_path, monkeypatch), "mirrors": [GH]}
    assert run(tmp_path, monkeypatch, b"old bytes", prev)["mirrors"] == [GH]
    a = run(tmp_path, monkeypatch, b"new bytes", prev)
    assert "mirrors" not in a and a["url"] is None          # new bytes: no link and no mirror until uploaded again
    assert a["fallback"]["kind"] == "pack" and a["fallback"]["mirrors"] == [GH]


def test_upload_assets_github_set_mirror_replaces_only_its_own_release_links():
    spec = importlib.util.spec_from_file_location("upload_assets_github", ROOT / "scripts/upload_assets_github.py")
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    e = {"mirrors": ["https://github.com/WhissleAI/Outpost-Luna/releases/download/assets-v1/x.tar", "https://example.org/x.tar"]}
    G.set_mirror(e, G.mirror_url(G.REPO, "assets-v2", "x.tar"), G.REPO)
    assert e["mirrors"] == [G.mirror_url(G.REPO, "assets-v2", "x.tar"), "https://example.org/x.tar"]
