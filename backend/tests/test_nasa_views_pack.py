"""The optional `nasa_views` asset (0.4 "Real NASA views"): its manifest entry and the builder's index.json contract.

Offline: the pack itself is built by scripts/nasa_views_build.py (`make nasa-views`); these tests read the manifests and
run the builder's validator / NOTICE / DBF reader on tiny fixtures.
"""
import copy
import json
import re
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import nasa_views_build as nv  # noqa: E402

MANIFESTS = [ROOT / "desktop/assets.manifest.json", ROOT / "site/assets/manifest.json"]
CREDIT = ("Uses NASA open data and 3D models (NASA 3D Resources; NASA/Astromaterials 3D, CC0; USGS Astrogeology); "
          "not endorsed by NASA.")


def entry(p):
    m = json.loads(p.read_text())
    got = [a for a in m["assets"] if a["id"] == "nasa_views"]
    assert len(got) == 1, f"{p.name}: one nasa_views entry"
    return got[0]


@pytest.mark.parametrize("p", MANIFESTS, ids=lambda p: p.parent.name)
def test_manifest_entry_shape(p):
    a = entry(p)
    assert a["env"] == "NASA_VIEWS_DIR" and a["subdir"] == ""
    assert a["required"] is False and a["licence"] == ["NOTICE"]
    assert re.fullmatch(r"[0-9a-f]{64}", a["sha256"])
    assert a["file"] == "outpost-luna-v2-nasa_views.tar"
    assert 0 < a["size"] <= 40 * 1024 * 1024
    assert a["min_app"] == "0.4.0" and a["version"]
    assert a["url"] is None or a["url"].startswith("https://")
    paths = {f["path"] for f in a["files"]}
    assert {"index.json", "NOTICE", "sky/starmap_4k.jpg", "names/moon_names.json"} <= paths
    for f in a["files"]:
        assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) and f["size"] > 0
        assert not f["path"].startswith("/") and ".." not in f["path"]
    assert a["n_files"] == len(a["files"]) and a["unpacked_size"] == sum(f["size"] for f in a["files"])
    # the contract's parts are all there
    assert sum(p.startswith("rocks/") for p in paths) == 6
    assert {f"models/{m[0]}.glb" for m in nv.MODELS} <= paths


def test_both_manifest_copies_agree():
    assert entry(MANIFESTS[0]) == entry(MANIFESTS[1])


def test_credit_sentence_is_the_agreed_one():
    assert nv.CREDIT == CREDIT


# ---------------------------------------------------------------------------------------------- index.json contract
def fixture(tmp_path):
    idx = {"schema": 1, "pack": "nasa_views", "version": "1", "credit": CREDIT,
           "sky": {**nv.SKY},
           "models": [{"id": "apollo_lm", "file": "models/apollo_lm.glb", "title": "Apollo Lunar Module",
                       "credit": "NASA 3D Resources", "source": "https://science.nasa.gov/3d-resources/apollo-lunar-module/",
                       "size": [6.4, 5.0, 6.4], "bytes": 3}],
           "rocks": [{"id": "15016", "file": "rocks/15016.glb", "name": "Seatbelt basalt", "mission": "Apollo 15",
                      "type": "Low-Ti Olivine Basalt", "mass_g": None, "story": "A short story.",
                      "credit": "NASA/Astromaterials 3D (CC0)", "source": "https://ares.jsc.nasa.gov/astromaterials3d/"}],
           "images": [{"id": "earthrise", "file": "images/earthrise.jpg", "title": "Earthrise", "caption": "Earth rising.",
                       "date": "1968-12-24", "nasa_id": "AS08-14-2383", "credit": "NASA",
                       "source": "https://images.nasa.gov/details/AS08-14-2383", "w": 2, "h": 2, "tags": ["earth"]}],
           "sdo": {**nv.SDO, "frames": [{"file": "sdo/00.jpg", "time": "2024-05-14T00:05:20Z"}]},
           "names": {"file": "names/moon_names.json", "count": 1, "credit": "IAU WGPSN / USGS", "source": "https://planetarynames.wr.usgs.gov/"}}
    for rel in ["sky/starmap_4k.jpg", "models/apollo_lm.glb", "rocks/15016.glb", "images/earthrise.jpg", "sdo/00.jpg",
                "names/moon_names.json"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    return idx


def test_validator_accepts_a_good_index(tmp_path):
    idx = fixture(tmp_path)
    assert nv.validate_index(idx, tmp_path) == []
    assert nv.validate_index(idx) == []   # without a folder: shape only


@pytest.mark.parametrize("break_it, want", [
    (lambda i: i.update(credit="NASA"), "credit"),
    (lambda i: i["sky"].update(ra0_u=2), "ra0_u"),
    (lambda i: i["sky"].update(ra_increases="up"), "ra_increases"),
    (lambda i: i["images"][0].update(nasa_id="com-axiom-123"), "Axiom"),
    (lambda i: i["rocks"][0].update(story="x" * 221), "220"),
    (lambda i: i["models"][0].update(file="../evil.glb"), "bad file"),
    (lambda i: i["models"][0].update(size=[1, 2]), "size"),
    (lambda i: i["models"].append(dict(i["models"][0])), "duplicate"),
    (lambda i: i.update(rocks=[]), "non-empty"),
    (lambda i: i["sdo"]["frames"].append({"file": "sdo/99.jpg", "time": "t"}), "not found"),
])
def test_validator_rejects(tmp_path, break_it, want):
    idx = copy.deepcopy(fixture(tmp_path))
    break_it(idx)
    errs = nv.validate_index(idx, tmp_path)
    assert any(want in e for e in errs), errs


def test_notice_credits_every_item(tmp_path):
    idx = fixture(tmp_path)
    text = nv.notice(idx)
    assert text.startswith(CREDIT)
    for needle in ("svs.gsfc.nasa.gov/4851", "apollo-lunar-module", "15016", "AS08-14-2383", "SDO", "USGS"):
        assert needle in text


def test_builder_never_lists_axiom_images():
    assert not any(nv.FORBIDDEN_IDS.search(i[1]) for i in nv.IMAGES)
    assert {r[0] for r in nv.ROCKS} == {"15016", "60025", "76535", "70017", "79115", "65035"}
    assert all(len(r[3]) <= 220 for r in nv.ROCKS)


def test_read_dbf_tiny_table():
    fields = [("name", "C", 10), ("center_lat", "N", 8)]
    hl, rl = 32 + 32 * len(fields) + 1, 1 + 10 + 8
    head = struct.pack("<BBBBIHH20x", 3, 26, 1, 1, 2, hl, rl)
    desc = b"".join(n.encode().ljust(11, b"\0") + t.encode() + b"\0" * 4 + bytes([ln]) + b"\0" * 15 for n, t, ln in fields)
    rows = b" " + b"Shackleton" + b"  -89.67" + b"*" + b"Gone".ljust(10) + b"    1.00"
    got = nv.read_dbf(head + desc + b"\x0d" + rows)
    assert got == [{"name": "Shackleton", "center_lat": -89.67}]
