"""Open data in a course Library (docs/MEDIA.md "Open data", docs/COURSES.md §2): the new item kinds (chart, model,
layer), the licence gate on media/credits.json (licence_class pd | cc0 | by | by-sa; never nc, nd or unknown), chart
parsing, the media route's data types, and the Archaeology data itself (drought timeline, tree rings, radiocarbon
counts, Sentinel-2, Natural Earth layer)."""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import course_library as cl, courses
from app.academy import content

D = content.DATA / "courses" / "archaeology"
LIB = json.loads((D / "library.json").read_text())
CRED = json.loads((D / "media" / "credits.json").read_text())
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv(content.DEV_COURSE_ENV, "archaeology")
    courses.reload_all(); content.reload()
    yield
    monkeypatch.delenv(content.DEV_COURSE_ENV, raising=False)
    courses.reload_all(); content.reload()


def _files():
    return cl._course_files(courses.get("archaeology"))


def _item(iid):
    return next(i for s in LIB["shelves"] for i in s["items"] if i["id"] == iid)


# ------------------------------------------------------------------------------------------------ the licence gate
GOOD = {"file": "x.jpg", "credit": "A", "licence": "CC BY 4.0", "source_url": "https://e.org", "alt": "x"}


@pytest.mark.parametrize("lc", ["pd", "cc0", "by", "PD"])
def test_open_licence_classes_ship(lc):
    assert cl.licence_problem({**GOOD, "licence_class": lc}) is None


@pytest.mark.parametrize("c, why", [
    ({**GOOD}, "missing"),
    ({**GOOD, "licence_class": "by-nc"}, "cannot ship"),
    ({**GOOD, "licence_class": "nc"}, "cannot ship"),
    ({**GOOD, "licence_class": "nd"}, "cannot ship"),
    ({**GOOD, "licence_class": "unknown"}, "cannot ship"),
    ({**GOOD, "licence_class": "odbl"}, "cannot ship"),
    ({**GOOD, "licence_class": "by", "licence": "CC BY-NC 4.0"}, "non-commercial"),
    ({**GOOD, "licence_class": "by", "licence": "Creative Commons Attribution-NoDerivatives"}, "no-derivatives"),
    ({**GOOD, "licence_class": "by-sa"}, "unmodified"),
    ({**GOOD, "licence_class": "by-sa", "modified": True}, "unmodified"),
])
def test_nc_nd_unknown_and_modified_by_sa_are_rejected(c, why):
    assert why in (cl.licence_problem(c) or "")


def test_by_sa_ships_only_unmodified():
    assert cl.licence_problem({**GOOD, "licence_class": "by-sa", "licence": "CC BY-SA 4.0", "modified": False}) is None


def test_every_archaeology_credit_passes_the_gate_and_says_where_its_licence_is():
    assert cl.licence_problems(CRED) == []
    for c in CRED:
        assert c["licence_class"] in cl.LICENCE_CLASSES, c["file"]
        if c["licence_class"] != "pd" or c["file"].endswith((".json", ".csv", ".glb")) or c["file"].startswith(("s2_", "layer_")):
            assert c.get("licence_evidence"), f"{c['file']}: record where the licence was checked"


def test_a_library_naming_an_nc_file_is_invalid(dev):
    f = _files()
    f["credits"] = copy.deepcopy(f["credits"])
    f["credits"]["s2_mesa_verde.jpg"]["licence_class"] = "by-nc"
    assert any("s2_mesa_verde.jpg" in e and "cannot ship" in e for e in cl.validate(LIB, f))


def test_the_pack_build_refuses_an_nc_credit(tmp_path, monkeypatch):
    """scripts/asset_pack.py src_course: the same gate at build time."""
    import shutil
    sys.path.insert(0, str(ROOT / "scripts"))
    import asset_pack
    src = tmp_path / "backend/data/courses"
    shutil.copytree(D, src / "archaeology", ignore=shutil.ignore_patterns("video"))
    shutil.copy(D.parent / "archaeology.json", src / "archaeology.json")
    monkeypatch.setattr(asset_pack, "ROOT", tmp_path)
    assert any(r == "media/drought_mesa_verde.json" for r, _ in asset_pack.src_course(src / "archaeology.json"))
    cred = json.loads((src / "archaeology/media/credits.json").read_text())
    cred[0]["licence_class"] = "nc"
    (src / "archaeology/media/credits.json").write_text(json.dumps(cred))
    with pytest.raises(SystemExit) as e:
        asset_pack.src_course(src / "archaeology.json")
    assert "cannot ship" in str(e.value)


# ------------------------------------------------------------------------------------------------ charts
def test_parse_chart_json_and_csv():
    d = cl.parse_chart(json.dumps({"format": "outpost-luna-chart", "series": [{"label": "a", "points": [[1, 2], [2, 3]]}]}), "c.json")
    assert d["series"][0]["points"] == [[1, 2], [2, 3]]
    c = cl.parse_chart("year,wet,dry\n# a comment\n1276,1,NA\n1277,2,3\n1278,,4\n", "c.csv")
    assert [s["label"] for s in c["series"]] == ["wet", "dry"] and c["series"][1]["points"] == [[1277, 3], [1278, 4]]
    assert c["x_label"] == "year"


@pytest.mark.parametrize("text, name, why", [
    ('{"series": []}', "c.json", "format"),
    ('{"format": "outpost-luna-chart", "series": [{"label": "a", "points": [[1, "x"]]}]}', "c.json", "numbers"),
    ('{"format": "outpost-luna-chart", "series": [{"label": "a", "points": [[2, 1], [1, 1]]}]}', "c.json", "increase"),
    ('{"format": "outpost-luna-chart", "series": [{"points": [[1, 1], [2, 1]]}]}', "c.json", "label"),
    ('{"format": "outpost-luna-chart", "series": []}', "c.json", "1 to 6"),
    ("x,y\n1,2\n", "c.csv", "two rows"),
    ("x,y\n1,2\nabc,3\n", "c.csv", "not a number"),
    ("x,y\n1,2\n2,oops\n", "c.csv", "not a number"),
])
def test_parse_chart_rejects_bad_data(text, name, why):
    with pytest.raises(ValueError, match=why):
        cl.parse_chart(text, name)


def test_validate_checks_the_new_kinds(dev):
    f = _files()
    bad = copy.deepcopy(LIB)
    data = next(s for s in bad["shelves"] if s["id"] == "data")["items"]
    data[0].pop("summary")
    data[1]["bands"] = [{"from": 1300, "to": 1200, "label": "x"}]
    data[2]["file"] = "s2_mesa_verde.jpg"                    # a chart that names a picture
    data[3]["legend"] = [{"color": "red", "label": "x"}]
    data.append({"id": "mod", "kind": "model", "title": "M", "file": "x.json"})
    data.append({"id": "l2", "kind": "layer", "title": "L", "file": "layer_rivers_states.png", "legend": [{"color": "#ffffff", "label": "x"}],
                 "bounds": {"west": 10, "south": 0, "east": 0, "north": 1}, "opacity": 0})
    errs = " | ".join(cl.validate(bad, f))
    for s in ("needs a summary", "bands must be", "a chart names a .json / .csv file", "a layer needs a legend",
              "a model names a .glb file", "a layer needs bounds", "opacity"):
        assert s in errs, s


def test_the_route_resolves_charts_and_layers_and_serves_their_files(dev):
    from app.main import app
    c = TestClient(app)
    d = c.get("/api/course/library").json()
    data = next(s for s in d["shelves"] if s["id"] == "data")
    by = {i["id"]: i for i in data["items"]}
    ch = by["drought_timeline"]
    assert ch["url"] == "/api/courses/archaeology/media/drought_mesa_verde.json" and ch["summary"] and ch["bands"]
    assert ch["image_licence"] and ch["image_source_url"].startswith("https://www.ncei.noaa.gov/")
    r = c.get(ch["url"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    ly = by["rivers_layer"]
    assert ly["legend"] and ly["bounds"]["west"] == -110.2
    assert c.get(ly["url"]).headers["content-type"] == "image/png"


@pytest.mark.parametrize("name", ["a..json", "x.tar.glb", ".hidden.json", "a.svg", "A.csv", "a.json.png", "a/b.json"])
def test_media_names_are_one_flat_segment_with_one_dot(dev, name):
    from app.main import app
    assert TestClient(app).get(f"/api/courses/archaeology/media/{name}").status_code == 404


def test_media_route_types_for_data_files(dev, tmp_path, monkeypatch):
    from app.main import app
    (tmp_path / "a.csv").write_text("x,y\n1,2\n2,3\n")
    (tmp_path / "m.glb").write_bytes(b"glTF")
    monkeypatch.setattr(courses, "media_dir", lambda cid: tmp_path)
    c = TestClient(app)
    assert c.get("/api/courses/archaeology/media/a.csv").headers["content-type"].startswith("text/csv")
    assert c.get("/api/courses/archaeology/media/m.glb").headers["content-type"] == "model/gltf-binary"


# ------------------------------------------------------------------------------------------------ the Archaeology data
def test_drought_timeline_is_the_ncei_reconstruction_with_the_great_drought_band():
    d = json.loads((D / "media/drought_mesa_verde.json").read_text())
    yearly = next(s for s in d["series"] if s.get("faint"))
    assert yearly["points"][0][0] == 722 and yearly["points"][-1][0] == 2011 and len(yearly["points"]) == 1290
    it = _item("drought_timeline")
    assert it["bands"] == [{"from": 1276, "to": 1299, "label": "Great Drought 1276–1299"}]
    assert "722–2011" in it["title"]
    # the Great Drought's smoothed values sit below its century's mean
    sm = dict(map(tuple, next(s for s in d["series"] if not s.get("faint"))["points"]))
    drought = sum(sm[y] for y in range(1276, 1300)) / 24
    assert drought < sum(sm[y] for y in range(1200, 1276)) / 76


def test_copy_says_moved_or_migrated_never_abandoned_or_vanished():
    words = re.compile(r"\b(abandon\w*|vanish\w*|disappear\w*|mysterious\w*)\b", re.I)
    data = next(s for s in LIB["shelves"] if s["id"] == "data")
    text = json.dumps(data) + json.dumps([c for c in CRED if not c["file"].startswith(("photo_", "far_view"))])
    assert not words.search(text), words.search(text)
    assert re.search(r"\b(moved|migrated)\b", _item("drought_timeline")["caption"])


def test_tree_ring_chart_compares_co652_with_three_more_four_corners_chronologies():
    d = json.loads((D / "media/tree_rings_1200_1320.json").read_text())
    labels = " ".join(s["label"] for s in d["series"])
    for code in ("CO652", "NM597", "NM589", "CO067"):
        assert code in labels
    for s in d["series"]:
        xs = [p[0] for p in s["points"]]
        assert 1200 <= xs[0] and xs[-1] <= 1320 and 0.4 < sum(p[1] for p in s["points"]) / len(xs) < 1.6
        assert any(1276 <= x <= 1299 for x in xs), "every record covers the Great Drought"


def test_radiocarbon_counts_are_region_level_with_no_locations_and_no_human_remains():
    raw = (D / "media/radiocarbon_four_corners.json").read_text()
    d = json.loads(raw)
    assert set(d) <= {"format", "version", "type", "x_format", "x_label", "y_label", "series", "kept", "older", "excluded", "method"}
    assert not re.search(r"lat|lon|long|site|labid|coord", json.dumps(d["series"]), re.I)
    assert sum(p[1] for p in d["series"][0]["points"]) + d["older"] <= d["kept"] and d["excluded"] > 0
    assert all(isinstance(p[1], int) and p[1] >= 0 for p in d["series"][0]["points"])
    c = next(c for c in CRED if c["file"] == "radiocarbon_four_corners.json")
    assert c["licence_class"] == "cc0" and "no coordinates" in c["sensitivity"]
    sys.path.insert(0, str(ROOT / "scripts"))
    import arch_open_data_build as b
    for text in ("human bone", "BONE", "collagen", "tooth", "Homo sapiens", "FECES", "coprolite", "TEXTILE", "basketry",
                 "Yucca sandal", "burial fill", "cremated"):
        assert b.RC_DROP.search(text), text
    for mat in ("CHARCOAL", "SEEDS", "WOOD", "SEDIMENT"):
        assert b.RC_KEEP.match(mat) and not b.RC_DROP.search(mat), mat
    for mat in ("BONE", "OTHER", "UNKNOWN", "SHELL", "ANIMAL", "TEXTILE", "LEATHER", "FECES"):
        assert not b.RC_KEEP.match(mat), "whitelist only: " + mat


def test_sentinel_picture_carries_the_mandatory_copernicus_credit():
    c = next(c for c in CRED if c["file"] == "s2_mesa_verde.jpg")
    assert re.fullmatch(r"Contains modified Copernicus Sentinel data 20\d\d", c["credit"])
    assert c["credit"].endswith(c["acquired"][:4]) and c["licence_class"] == "by"
    assert (D / "media/s2_mesa_verde.jpg").stat().st_size < 4_000_000


def test_natural_earth_layer_lines_up_with_the_overlay_box():
    c = next(c for c in CRED if c["file"] == "layer_rivers_states.png")
    it = _item("rivers_layer")
    b = it["bounds"]
    assert b == LIB["overlays"][0]["bounds"]
    assert abs((b["east"] - b["west"]) / (b["north"] - b["south"]) - c["width"] / c["height"]) < 0.01
    assert c["licence_class"] == "pd" and "San Juan" in c["rivers"]


def test_every_new_file_is_credited_hashed_and_the_pack_stays_modest():
    new = [c for c in CRED if c["file"].endswith((".json", ".csv", ".glb")) or c["file"].startswith(("s2_", "layer_"))]
    assert len(new) == 5
    for c in new:
        p = D / "media" / c["file"]
        import hashlib
        assert p.stat().st_size == c["bytes"] and hashlib.sha256(p.read_bytes()).hexdigest() == c["sha256"], c["file"]
    assert sum(c["bytes"] for c in new) < 25_000_000
    pins = json.loads((ROOT / "scripts/arch_open_data.pins.json").read_text())
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in pins.values()) and {"mv_ppe", "p3k14c", "ne_states"} <= set(pins)
