import asyncio

from app import models_client
from app.config import settings
from app.gazetteer import Gazetteer
from app.moments import MomentIndex
from app.readout import summarize
from app.resolve import resolve

GAZ = Gazetteer(settings.data_dir / "places.json")
IDX = MomentIndex(settings.data_dir / "index/clips.json")
NO_ARC = {"available": False}


async def _no_arc(*a, **k):
    return None


def ask(text, read=NO_ARC):
    return asyncio.run(resolve(text, read, GAZ, IDX))


def test_alias_and_kid_descriptor():
    assert GAZ.match_text("show me the giant bullseye").id == "orientale"
    assert GAZ.match_text("where did Neil Armstrong land").id == "tranquillitatis"


def test_fuzzy_link_catches_asr_spellings():
    assert GAZ.link("Oriental")[0].id == "orientale"
    assert GAZ.link("Hertzprung.")[0].id == "hertzsprung"
    assert GAZ.link("Galveston") is None


def test_self_correction_uses_the_last_place():
    r = ask("show me Tycho, wait no I mean Copernicus")
    assert r["place"] == "copernicus" and r["corrected"]


def test_crew_request_plays_a_moment_when_indexed():
    r = ask("what did the astronauts say about Aristarchus")
    if IDX.best_moment("aristarchus"):
        assert r["action"] == "play" and r["moment"]["clip_id"]
    else:
        assert r["action"] == "fly"


def test_far_side_view():
    assert ask("show me the far side")["action"] == "view"


def test_hard_pii_is_guarded():
    raw = {"spans": [{"family": "pii", "type": "safety.pii.street_address", "text": "42 Oak Street"}],
           "utterances": [{}], "events": []}
    r = ask("I live at 42 Oak Street", summarize(raw))
    assert r["action"] == "guard"


def test_unknown_without_llm(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(models_client, "tag", _no_arc)
    assert ask("tell me a joke")["action"] == "say"
