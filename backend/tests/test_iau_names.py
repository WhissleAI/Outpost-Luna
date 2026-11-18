"""Official IAU crater names in the ear (docs/LEARNING_DESIGN.md §12.5, docs/MEDIA.md "IAU names").

The nasa_views pack carries 216 IAU names, but only when the optional pack is installed; the registry, the gazetteer
and the Director are built from versioned repo data. So a curated subset lives in places.json: the south-pole craters
a cadet can see from the outpost or hear about in Artemis news, with the IAU Gazetteer's coordinates, diameters and
feature page. "Scott" stays out: it is David Scott's name in the registry (Apollo 15), and an alias names one entry.
"""
import asyncio
import json
from pathlib import Path

import pytest

from app import director, models_client, nasa_views
from app.config import settings
from app.entities.registry import Registry
from app.gazetteer import Gazetteer
from app.hotlist import build_vocab, source_hash
from app.moments import MomentIndex
from app.names_list import screen_names

DATA = Path(__file__).resolve().parents[1] / "data"
GAZ = Gazetteer(DATA / "places.json")
REG = Registry.load(DATA / "entities" / "outpost_luna.json")
FACTS = json.loads((DATA / "facts.json").read_text())["places"]
# id -> (IAU name, IAU lat, lon, diameter km) as published (planetarynames.wr.usgs.gov, MOON_nomenclature_center_pts)
IAU = {
    "shackleton": ("Shackleton", -89.67, 129.78, 20.92),
    "de_gerlache": ("de Gerlache", -88.48, -88.34, 32.71),
    "haworth": ("Haworth", -87.45, -5.17, 51.42),
    "nobile": ("Nobile", -85.28, 53.27, 79.27),
    "malapert": ("Malapert", -85.0, 11.4, 72.38),
    "cabeus": ("Cabeus", -85.33, -42.13, 100.58),
    "faustini": ("Faustini", -87.18, 84.31, 42.48),
    "shoemaker": ("Shoemaker", -88.14, 45.91, 51.82),
    "sverdrup": ("Sverdrup", -88.32, -153.39, 32.83),
    "amundsen": ("Amundsen", -84.44, 83.07, 103.39),
    "schrodinger": ("Schrödinger", -74.73, 132.93, 316.39),
}
NEW = [k for k in IAU if k != "shackleton"]


@pytest.fixture(autouse=True)
def offline_arc(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", none)


def test_the_curated_south_pole_names_carry_iau_numbers_and_a_source():
    for pid, (name, lat, lon, km) in IAU.items():
        p = GAZ.places[pid]
        assert p.kind == "feature" and not p.estimated, pid
        assert p.name == name or (pid == "shackleton" and p.name.startswith("Shackleton")), pid
        assert abs(p.lat - lat) <= 0.01 and abs(p.lon - lon) <= 0.01, (pid, p.lat, p.lon)
        if pid != "shackleton":   # Shackleton keeps its rounded 21 km (the lessons and the sim say 21)
            assert abs(p.diameter_km - km) <= 0.01, (pid, p.diameter_km)
        assert p.source.startswith("https://planetarynames.wr.usgs.gov/Feature/"), pid
        assert p.lat <= -74.5, f"{pid} is not a south-pole name"
    assert "scott" not in GAZ.places and REG.resolve("Scott").id == "david_scott", "Scott stays David Scott's name"


def test_copernicus_uses_the_iau_width():
    c = GAZ.places["copernicus"]
    assert abs(c.diameter_km - 96.07) < 0.01 and c.source.endswith("/Feature/1296")
    f = FACTS["copernicus"]
    assert f["diameter_km"] == 96 and "96 km" in f["facts"][0]["text"] and 96 in f["facts"][0]["numbers"]
    assert "93" not in json.dumps(f)


def test_every_new_name_has_a_sourced_fact_sheet_with_its_size():
    for pid in NEW:
        f = FACTS[pid]
        assert f["diameter_km"] == round(GAZ.places[pid].diameter_km), pid
        assert len(f["facts"]) >= 2 and all(x["source"] for x in f["facts"]), pid
        size = f["facts"][0]
        assert f"{round(GAZ.places[pid].diameter_km)} km" in size["text"] and round(GAZ.places[pid].diameter_km) in size["numbers"], pid
        assert "IAU Gazetteer" in size["source"], pid
        assert "named for" in " ".join(x["text"] for x in f["facts"]), f"{pid}: who the crater honours"


def test_every_new_name_is_an_entity_on_the_ear_lists():
    for pid in IAU:
        e = REG.get(pid)
        assert e is not None and e.ref == {"source": "places.json", "id": pid}, pid
        assert director.place_of(pid, GAZ) is GAZ.places[pid], pid
    assert REG.resolve("Schrodinger").id == "schrodinger" and REG.resolve("Haworth crater").id == "haworth"
    pole = [pid for pid in NEW if REG.get(pid).group == "pole"]
    assert len(pole) >= 7, "the new craters are their own group, last in every profile"
    lesson = [n["name"] for n in screen_names({"screen": "lesson"})]
    for pid in pole:
        assert REG.get(pid).name in lesson, pid   # free slots: on the list as is
    for pid in pole:   # full lists (map at its cap of 80): in as soon as it is the place on screen, near the top
        names = [n["name"] for n in screen_names({"screen": "map"}, last_place=pid)]
        assert len(names) <= 80 and REG.get(pid).name in names[:5], (pid, names[:5])
    # nothing shipped is pushed off a full list
    for screen in ("map", "library", "cabin"):
        names = [n["name"] for n in screen_names({"screen": screen})]
        assert not {REG.get(p).name for p in pole} & set(names), screen
        assert "Neil Armstrong" in names or screen == "cabin", screen


def test_the_ear_vocabulary_file_is_regenerated():
    v = json.loads((DATA / "ear_vocab.json").read_text())
    assert v["v"] == source_hash(), "run `python -m app.hotlist build` (backend/)"
    assert v == json.loads(json.dumps(build_vocab()))
    for pid in NEW:
        assert GAZ.places[pid].name in v["places"], pid


@pytest.mark.parametrize("text,pid", [
    ("show me Haworth", "haworth"), ("where is Shoemaker crater", "shoemaker"), ("fly to Amundsen", "amundsen"),
    ("show me schrodinger", "schrodinger"), ("take me to Nobile", "nobile"), ("show me Faustini crater", "faustini"),
    ("show me Sverdrup", "sverdrup"), ("show me Cabeus", "cabeus"),
])
def test_naming_a_crater_flies_there(text, pid):
    r = asyncio.run(director.direct(text, {"available": False}, GAZ, MomentIndex(settings.data_dir / "index/clips.json"), None))
    assert r["place"] == pid and r["action"] in ("fly", "play"), r


def test_the_south_pole_still_means_shackleton():
    place, how, _ = director._link("show me the south pole", {"available": False}, GAZ)
    assert place is not None and place.id == "shackleton", (place, how)


def test_matches_the_installed_pack_when_present():
    """When the nasa_views pack is installed, every curated name inside its filter (south of 75 S) is in it, with the
    same numbers (Schrödinger, at 74.7 S, is just outside the pack's filter: it comes from the same IAU table)."""
    f = nasa_views.views_dir() / "names" / "moon_names.json"
    if not f.exists():
        pytest.skip("nasa_views pack not installed")
    pack = {n["name"]: n for n in json.loads(f.read_text(encoding="utf-8"))}
    for pid, (name, lat, lon, km) in IAU.items():
        if lat > -75:
            continue
        n = pack[name]
        assert abs(n["lat"] - lat) <= 0.01 and abs(n["lon"] - lon) <= 0.01 and abs(n["km"] - km) <= 0.01, name
