"""Hardware left on the Moon (artifacts.json): catalog, gazetteer, /api/places, and the Director paths."""
import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import claims, models_client
from app.config import settings
from app.director import direct
from app.gazetteer import Gazetteer, norm
from app.main import app
from app.moments import MomentIndex
from app.readout import summarize

GAZ = Gazetteer(settings.data_dir / "places.json")
IDX = MomentIndex(settings.data_dir / "index/clips.json")
ARTS = json.loads((settings.data_dir / "artifacts.json").read_text())
NO_ARC = {"available": False}
TYPES = {"lander", "rover", "impact", "instrument", "memorial"}


def ask(text, read=NO_ARC, context=None):
    return asyncio.run(direct(text, read, GAZ, IDX, context))


@pytest.fixture(autouse=True)
def offline_arc(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", none)


# ---- catalog ---------------------------------------------------------------------------------------------------------
def test_catalog_fields_and_sources():
    assert 25 <= len(ARTS) <= 40 and len({a["id"] for a in ARTS}) == len(ARTS)
    for a in ARTS:
        assert a["kind"] in TYPES and re.fullmatch(r"\d{4}-\d{2}-\d{2}", a["landed"])
        assert -90 <= a["lat"] <= 90 and -180 <= a["lon"] <= 180
        assert a["story"] and a["sources"] and all(s["url"].startswith("https://") for s in a["sources"])
        for v in a.get("voices", []):
            assert v["who"] and v["t0"] < v["t1"] and any(c["id"] == v["clip_id"] for c in IDX.clips)


def test_every_story_number_is_on_the_fact_sheet():
    for a in ARTS:
        allowed = [n for f in IDX.facts[a["id"]]["facts"] for n in f["numbers"]]
        for txt, v in claims.numbers_in(a["story"]):
            assert any(abs(v - x) <= 0.1 * abs(x) for x in allowed), (a["id"], txt)


def test_possessive_norm_keeps_contractions():
    assert norm("Ohm's rays") == "ohm rays" and norm("what's albedo") == "what s albedo"
    assert GAZ.match_text("Ohm's rays").id == "ohm"


# ---- /api/places -----------------------------------------------------------------------------------------------------
def test_api_places_has_both_kinds():
    with TestClient(app) as c:
        ps = c.get("/api/places").json()["places"]
    kinds = {p["kind"] for p in ps}
    assert kinds == {"feature", "artifact"}
    art = next(p for p in ps if p["id"] == "apollo16_lrv")
    assert art["type"] == "rover" and art["mission"] == "Apollo 16" and art["crew"] and art["sources"]
    assert art["voices"][0]["clip_id"] == "duke" and art["voices"][0]["who"] == "Charlie Duke"
    feat = next(p for p in ps if p["id"] == "tycho")
    assert "type" not in feat and {"id", "name", "lat", "lon", "diameter_km", "fact", "estimated", "aliases"} <= set(feat)
    assert all(p["type"] in TYPES for p in ps if p["kind"] == "artifact")


# ---- Director --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,typ", [("show me the rovers", "rover"), ("what's left on the Moon", None),
                                      ("show me the hardware", None), ("show me the ghost rovers", "rover")])
def test_tour(text, typ):
    r = ask(text)
    assert r["action"] == "tour" and r["places"] and r["say"]
    assert all(GAZ.places[p].kind == "artifact" and (typ is None or GAZ.places[p].type == typ) for p in r["places"])


@pytest.mark.parametrize("text,pid", [("show me Surveyor 3", "surveyor3"), ("where did Apollo 11 land", "apollo11_lm_eagle"),
                                      ("what did the Apollo 16 rover do", "apollo16_lrv"),
                                      ("Surveyor three", "surveyor3"), ("show me Eagle", "apollo11_lm_eagle"),
                                      ("Challenger", "apollo17_lm_challenger"), ("LRV 2", "apollo16_lrv")])
def test_naming_an_artifact_flies_with_its_story(text, pid):
    r = ask(text)
    assert r["action"] == "fly" and r["place"] == pid and r["say"]
    assert r["view"] == {"lat": GAZ.places[pid].lat, "lon": GAZ.places[pid].lon}
    assert r["say"] in GAZ.places[pid].story or GAZ.places[pid].story.startswith(r["say"].split(".")[0])


def test_tapping_an_artifact_uses_its_full_name():
    for a in ARTS:
        r = ask(a["name"])
        assert r["action"] == "fly" and r["place"] == a["id"], a["name"]


def test_who_left_it_plays_the_voice_clip():
    r = ask("who left this here", context={"last_place": "apollo16_lrv"})
    assert r["action"] == "play" and r["moment"]["clip_id"] == "duke" and r["moment"]["speaker"] == "Charlie Duke"
    assert "Duke" in r["say"] and r["moment"]["t0"] == 10.4
    with TestClient(app) as c:
        got = c.get(f"/api/moments/{r['moment']['id']}")
    assert got.status_code == 200 and got.json()["clip_id"] == "duke"


def test_who_drove_it_says_crew_without_a_clip():
    r = ask("who drove it", context={"last_place": "apollo15_lrv"})
    assert r["place"] == "apollo15_lrv" and "Scott" in r["say"] and "Irwin" in r["say"]
    r = ask("who left this here", context={"last_place": "surveyor3"})
    assert "robot" in r["say"]


@pytest.mark.parametrize("text,clip", [("play the launch", "liftoff"), ("what did liftoff sound like", "liftoff"),
                                       ("play the splashdown", "splashdown"), ("can I hear Charlie Duke", "duke")])
def test_mission_sounds_play_voices(text, clip):
    r = ask(text)
    assert r["action"] == "play" and r["moment"]["clip_id"] == clip


def test_voices_moments_exist_with_names():
    duke = [m for m in IDX.moments if m["clip_id"] == "duke"]
    assert duke and all(m["speaker"] == "Charlie Duke" for m in duke)


# ---- privacy guard: Arc PII false hits on Moon words -----------------------------------------------------------------
def _pii(text, typ="street_address"):
    return summarize({"spans": [{"family": "pii", "type": f"safety.pii.{typ}", "text": text}], "utterances": [{}],
                      "events": []})


@pytest.mark.parametrize("text,span", [("Apollo 16 Moon buggy", "Moon"), ("Surveyor 3", "Surveyor 3"),
                                       ("show me Eagle", "Eagle"), ("who drove the LRV", "LRV")])
def test_moon_words_tagged_as_pii_are_not_guarded(text, span):
    assert ask(text, _pii(span))["action"] != "guard"


def test_real_address_and_name_are_still_guarded():
    assert ask("my name is Maya and I live at 42 Oak Street", _pii("42 Oak Street"))["action"] == "guard"
    assert ask("I live at 42 Oak Street", _pii("42 Oak Street"))["action"] == "guard"
    assert ask("call me at 555 123 4567", _pii("555 123 4567", "phone_number"))["action"] == "guard"
