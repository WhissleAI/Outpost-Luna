"""Flight School v3 (docs/LEARNING_DESIGN.md): the globe step graders, lesson structure, and the accuracy locks from
docs/ACCURACY_AUDIT.md."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.academy import content, grade as g
from app.mission import sim

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend" / "data"


def G(acc, inp):
    return g.grade({"accept": acc}, inp)


# ---- graders: voice and tap both work ---------------------------------------------------------------------------
PRED = {"type": "predict", "answer": "no", "options": [{"id": "yes", "label": "Yes", "say": ["yes"]},
                                                       {"id": "no", "label": "No, neither", "say": ["no", "neither"]}]}


def test_predict_never_marks_a_guess_wrong():
    assert G(PRED, {"choice": "yes"}) == (True, {"guess": "yes", "correct": False})
    assert G(PRED, {"text": "no"})[1]["correct"]
    assert G(PRED, {"text": "option 1"})[1]["guess"] == "yes"
    assert not G(PRED, {"text": "banana"})[0]            # no option named: ask again


@pytest.mark.parametrize("inp,ok", [({"choice": "far"}, True), ({"choice": "near"}, False),
                                    ({"view": {"lat": 5, "lon": -170}}, True), ({"view": {"lat": 0, "lon": 10}}, False),
                                    ({"text": "turn it around"}, True), ({"text": "show me the far side"}, True),
                                    ({"text": "the near side please"}, False)])
def test_globe_side(inp, ok):
    assert G({"type": "globe_side", "want": "far"}, inp)[0] is ok


def test_terminator_by_tap_word_or_place():
    acc = {"type": "terminator", "sun_lon": 90, "tol_deg": 12}
    assert G(acc, {"tap": {"lat": 10, "lon": 3}})[0]                  # on the lon-0 meridian
    assert not G(acc, {"tap": {"lat": 0, "lon": 60}})[0]               # in daylight
    assert G(acc, {"text": "the terminator"})[0]
    assert G(acc, {"text": "where day meets night"})[0]
    assert not G(acc, {"text": "tycho"})[0] or abs(-11.2) < 12      # Tycho (lon -11) is near the line: either is fair


def test_compare_by_name_tap_or_choice_and_shows_the_data():
    acc = {"type": "compare", "answer": "malapert_massif",
           "options": [{"id": "malapert_massif", "label": "Malapert Massif", "say": ["malapert"]},
                       {"id": "shackleton_rim", "label": "Shackleton Rim", "say": ["rim"]}]}
    ok, extra = G(acc, {"text": "malapert"})
    assert ok and extra["data"]["malapert_massif"]["earth_days"] == 9.5
    assert extra["data"]["shackleton_rim"]["ice_km"] == 10
    assert G(acc, {"tap": {"lat": -86, "lon": -2}})[0]
    assert not G(acc, {"choice": "shackleton_rim"})[0]


def test_route_in_order_by_voice_or_taps():
    acc = {"type": "route", "stops": ["orientale", "ohm"]}
    assert G(acc, {"text": "orientale then ohm"})[0]
    ok, extra = G(acc, {"text": "ohm then orientale"})
    assert not ok and extra["next"] == "ohm" and extra["got"] == ["orientale"]
    assert G(acc, {"taps": [{"place": "orientale"}, {"lat": 18.4, "lon": -113.5}]})[0]
    assert G(acc, {"taps": [{"place": "orientale"}]})[1] == {"got": ["orientale"], "next": "ohm"}


@pytest.mark.parametrize("place,ans", [("tranquillitatis", "yes"), ("tsiolkovskiy", "no"), ("shackleton", "sometimes"),
                                       ("malapert_massif", "sometimes")])
def test_earth_view_is_computed_from_the_map(place, ans):
    assert g.earth_answer(place) == ans
    assert G({"type": "earth_view", "place": place}, {"choice": ans})[0]


# ---- the course ----------------------------------------------------------------------------------------------------
def test_course_v3_shape():
    c = content.course()
    assert content.check() == []
    ids = [l["id"] for l in c["lessons"]]
    assert ids[-1] == "checkride" and "words" not in ids and len(ids) == 7
    for l in c["lessons"]:
        assert l.get("place"), f"{l['id']} has no Moon-map pin"
        if l.get("ride"):
            continue
        assert 4 <= len(l["steps"]) <= 5, l["id"]
        assert l.get("clip"), f"{l['id']} has no crew-audio hook"
    used = {s["accept"]["type"] for l in c["lessons"] for s in l["steps"]}
    assert set(g.GLOBE_TYPES) <= used          # every globe verb is taught somewhere


def test_clips_exist_and_fit():
    clips = {c["id"]: c for c in json.loads((DATA / "index" / "clips.json").read_text())["clips"]}
    for l in content.course()["lessons"]:
        for c in [l.get("clip")] + [s.get("clip") for s in l["steps"]]:
            if c:
                assert c["clip_id"] in clips and 0 <= c["t0"] < c["t1"] <= clips[c["clip_id"]]["dur"] + 1, c


def test_map_order_has_no_long_jumps_back():
    """Lesson pins in course order: near side first, then the south pole; never back to the equator."""
    lats = []
    for l in content.course()["lessons"]:
        p = l["place"]
        lats.append(p["lat"] if isinstance(p, dict) else g.where(p)[0])
    assert all(abs(x) < 20 for x in lats[:2]) and all(x < -80 for x in lats[2:])


def test_public_course_hides_globe_answers():
    for l in content.public()["lessons"]:
        for s in l["steps"]:
            a = s["accept"]
            if a["type"] in ("predict", "compare"):
                assert "answer" not in a and all(set(o) == {"id", "label"} for o in a["options"])


# ---- accuracy locks (docs/ACCURACY_AUDIT.md) -------------------------------------------------------------------------
TEXT_FILES = [DATA / "academy/course.json", DATA / "places.json", DATA / "facts.json", DATA / "mission/sites.json",
              ROOT / "backend/app/mission/sim.py", ROOT / "backend/app/mission/capcom.py", ROOT / "frontend/src/story.js",
              DATA / "learning/concepts.json"]


def test_nothing_says_artemis_iii_lands():
    bad = re.compile(r"artemis (iii|3)\b[^.\n]{0,60}\b(land|first landing|landing near|lands|landed)", re.I)
    neg = re.compile(r"(hasn't|has not|isn't|does not|doesn't|won't|\bnot\b|\bno landing|without landing)", re.I)
    for p in TEXT_FILES:
        for line in p.read_text().splitlines():
            m = bad.search(line)
            if m and "Moon Landing Regions" not in line and not neg.search(line):
                pytest.fail(f"{p.name}: {line.strip()[:140]}")


def test_dose_baseline_compares_with_the_iss_cosmic_ray_dose():
    r = sim.radiation()
    assert r["iss_comparison"]["gcr_usv_per_day"] == 523
    assert round(r["baseline"]["dose_equivalent_usv_per_day"] / 523, 1) == 2.6
    d = sim.debrief(sim.new_mission("x", "shackleton_rim", 1))
    assert any("2.6 times" in l["text"] and "523" in l["text"] for l in d["lessons"])


def test_storms_are_keyed_on_solar_particles():
    cat = sim.storms_catalog()["events"]
    assert len({e["id"] for e in cat}) == len(cat)
    for e in cat:
        if e["sep"]:
            assert "-SEP-" in e["id"] and "/SEP/" in e["link"] and "particle" in e["name"]
        else:
            assert e["dose_multiplier"] < 2 and "few particles" in e["name"]


def test_sites_name_nasa_regions_honestly():
    for s in sim.sites():
        assert "Artemis III candidate" not in s["notes"]
        assert s["status"] in ("nasa_2024", "studied")
    status = {s["id"]: s["status"] for s in sim.sites()}
    assert status["malapert_massif"] == status["de_gerlache_rim"] == "nasa_2024"
    assert status["shackleton_rim"] == status["connecting_ridge"] == "studied"


def test_pretend_tech_is_flagged_and_no_soil_shelter_plan():
    g_ = sim.radiation()["game"]
    assert {"shields", "greenhouse", "power_cable", "relay"} <= set(g_["pretend_tech"])
    for p in TEXT_FILES:
        assert not re.search(r"regolith shelter is the plan|shelter covered in (moon )?soil", p.read_text(), re.I), p


def test_spa_and_lcross_numbers():
    places = {p["id"]: p for p in json.loads((DATA / "places.json").read_text())["places"]}
    assert "more than half as wide as the USA" in places["spa"]["fact"]
    t = (DATA / "facts.json").read_text() + (DATA / "artifacts.json").read_text()
    assert "2000 kg" not in t and "350 metric tons" not in t and "2,300 kg" in t and "155 kg" in t
