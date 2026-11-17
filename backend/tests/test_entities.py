"""The entity layer (docs/ENTITY_LAYER.md): the registry, per-moment ear lists, the session's entity memory, the
director acting on ids, and the round-12 entity features (appended; the shipped weights' decisions unchanged)."""
import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from app import director, models_client, session as sessions
from app.config import settings
from app.director_model import features as FX
from app.entities import EntityMemory, Moment, Registry, ear_list, registry
from app.entities.registry import SCHEMA
from app.gazetteer import Gazetteer
from app.moments import MomentIndex
from app.names_list import screen_names

DATA = Path(__file__).resolve().parents[1] / "data"
GAZ = Gazetteer(DATA / "places.json")


# ------------------------------------------------------------------------------------------------ the registry
def test_registry_file_is_valid_and_ids_are_unique():
    raw = json.loads((DATA / "entities" / "outpost_luna.json").read_text())
    assert raw["schema"] == SCHEMA
    R = registry()
    assert len(R.by_id) == len(raw["entities"])
    for e in R.entities:
        for r in e.related:
            assert R.get(r) is not None, (e.id, r)
        assert e.name and e.type and e.kind


def test_every_gazetteer_place_and_artifact_and_site_is_an_entity():
    R = registry()
    for pid in GAZ.places:
        assert R.get(pid) is not None, pid
    for s in json.loads((DATA / "mission" / "sites.json").read_text())["sites"]:
        assert R.get(s["id"]) is not None and R.get(s["id"]).type == "site"
    for les in json.loads((DATA / "academy" / "course.json").read_text())["lessons"]:
        assert R.get("lesson_" + les["id"]) is not None


def test_refs_point_at_real_records():
    R = registry()
    for e in R.entities:
        if e.ref and e.ref["source"] in ("places.json", "artifacts.json"):
            assert e.ref["id"] in GAZ.places, e.id


def test_resolve_mentions_and_mishears():
    R = registry()
    assert R.resolve("Mare Imbrium").id == "imbrium"
    assert R.resolve("sea of rain").id == "imbrium"
    assert [e.id for e in R.mentions("fly from tycho to the sea of rains")] == ["tycho", "imbrium"]
    assert R.mishear_of("send the rover to the jelly")[0].id.startswith("de_gerlache")
    assert R.mentions("") == [] and R.mishear_of("hello") is None


def test_controls_and_lessons_are_entities_but_never_ear_entries():
    R = registry()
    assert R.get("load_shields").type == "control" and "force field" in R.get("load_shields").aliases
    assert "storm" in R.get("load_shields").states
    names = {n["name"] for s in ("cabin", "map", "library", "lesson") for n in screen_names({"screen": s})}
    assert "Shields" not in names and "Rover" not in names and "Know your Moon" not in names


def test_a_registry_without_the_schema_is_refused():
    with pytest.raises(ValueError):
        Registry({"entities": []})
    with pytest.raises(ValueError):
        Registry({"schema": SCHEMA, "entities": [{"id": "a", "type": "t", "name": "A"},
                                                 {"id": "a", "type": "t", "name": "B"}]})


def test_a_tiny_app_registry_plugs_in():
    """A future app: its own file, its own screens; nothing Moon-specific in the module."""
    R = Registry({"schema": SCHEMA, "app": "zoo", "default_screen": "home",
                  "screens": {"home": {"cap": 3, "groups": [["animal"]]}},
                  "entities": [{"id": "lion", "type": "animal", "name": "Lion", "kind": "other", "aliases": ["big cat"]},
                               {"id": "otter", "type": "animal", "name": "Otter", "kind": "other",
                                "mishears": ["odder"]},
                               {"id": "yak", "type": "animal", "name": "Yak", "kind": "other"},
                               {"id": "emu", "type": "animal", "name": "Emu", "kind": "other"}]})
    assert [e["name"] for e in ear_list(R, Moment(screen="home"))] == ["Lion", "Otter", "Yak"]
    assert [e["name"] for e in ear_list(R, Moment(screen="home", said=["the emu is fast"]))][0] == "Emu"
    assert R.mishear_of("an odder swims")[0].id == "otter"


# ------------------------------------------------------------------------------------------------ per-moment lists
def test_the_moment_reorders_the_list():
    R = registry()
    base = [n["name"] for n in ear_list(R, Moment(screen="map"))]
    assert base[0] == "Sea of Tranquility"
    kid = [n["name"] for n in ear_list(R, Moment(screen="map", kid=[("tsiolkovskiy", 10.0)]))]
    assert kid[0] == "Tsiolkovskiy"
    step = [n["name"] for n in ear_list(R, Moment(screen="map", step_ids=["tycho"], kid=[("tsiolkovskiy", 1.0)]))]
    assert step[:2] == ["Tycho", "Tsiolkovskiy"]
    old = [n["name"] for n in ear_list(R, Moment(screen="map", kid=[("tsiolkovskiy", 3600.0)], said=["Ohm crater"]))]
    assert old[0] == "Ohm"                    # an hour-old mention has decayed below what we just said
    looking = [n["name"] for n in ear_list(R, Moment(screen="library", looking="apollo15_lrv"))]
    assert looking[0] == "Apollo 15 Lunar Roving Vehicle"


def test_cabin_sites_keep_their_short_names():
    L = {n["name"]: n for n in screen_names({"screen": "cabin"})}
    assert "de Gerlache" in L["de Gerlache Crater Rim"]["aliases"] and "de Gerlache" not in L


# ------------------------------------------------------------------------------------------------ memory
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_memory_records_kid_and_guide_mentions_and_recalls():
    c = Clock()
    m = EntityMemory(registry(), c)
    evs = m.note_turn([{"entity": "Tycho", "state": "linked", "p": 1.0}], "tell me about tycho and copernicus", "map")
    assert [e["id"] for e in evs] == ["tycho", "copernicus"] and evs[0]["how"] == "ear_link"
    m.note_line("Tsiolkovskiy is on the far side.", by="guide")
    assert [i for i, _ in m.kid_recent()] == ["copernicus", "tycho"] or {i for i, _ in m.kid_recent()} == {"tycho", "copernicus"}
    assert m.recall_line("tycho") is None           # just now: no callback
    c.t += 200
    m.note_turn([], "tycho again", "map")
    assert m.recall_line("tycho") == "You asked about Tycho earlier."
    assert m.recall_line("tycho") is None           # once per RECALL_EVERY_S
    assert m.recall_line("tsiolkovskiy") is None    # the guide said it, the kid never asked
    assert m.summary()["kid_mentions"]["tycho"] == 2


def test_an_abstained_link_is_not_a_kid_mention_for_the_ear_list():
    m = EntityMemory(registry(), Clock())
    m.note_turn([{"entity": "Tycho", "state": "abstain", "p": 0.4}], "", "map")
    assert m.kid_recent() == []


# ------------------------------------------------------------------------------------------------ acting on ids
def link(text, ear, spoken=None):
    read = {"ear_names": ear, "available": True, "mentions": []}
    if spoken is not None:
        read["ear_spoken"] = spoken
    return director._link(text, read, GAZ)


def test_a_linked_hardware_name_routes_by_id():
    p, how, _ = link("where is apollo 15 lunar roving vehicle",
                     [{"entity": "Apollo 15 Lunar Roving Vehicle", "state": "linked", "p": 1.0}])
    assert p.id == "apollo15_lrv" and how == "ear_link"


def test_a_known_mishearing_is_offered_back():
    # round 11: "where is tsiolkovskiy" -> "Where is siakowski"
    p, how, c = link("where is siakowski", [], spoken="Where is siakowski")
    assert p is None and how == "near" and c[0][0].id == "tsiolkovskiy"
    # a site is not a gazetteer place: the explorer offers nothing (the cabin takes it through the mission layer)
    assert director.place_of("de_gerlache_rim", GAZ) is None


def test_mission_dispatch_takes_the_linked_site():
    read = {"ear_names": [{"entity": "de Gerlache Crater Rim", "state": "linked", "p": 1.0}]}
    e = director.linked_entity(read, ("site",))
    assert e.id == "de_gerlache_rim"
    assert director.linked_entity({"ear_names": [{"entity": "de Gerlache Crater Rim", "state": "linked",
                                                  "p": 0.5}]}, ("site",)) is None


def run(c):
    return asyncio.run(c)


@pytest.fixture
def explorer(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    clock = Clock()
    s = sessions.Session("t-ent", GAZ, MomentIndex(settings.data_dir / "index/clips.json"), clock=clock)
    s.clock_obj = clock
    return s


def test_the_session_ear_list_follows_what_the_kid_said(explorer):
    explorer.memory.note_turn([], "where is tsiolkovskiy", "map")
    assert explorer.ear_names()[0]["name"] == "Tsiolkovskiy"


# ------------------------------------------------------------------------------------------------ Director features
def test_entity_features_are_appended_after_the_ear_block():
    assert FX.F_R12_EAR == 253 and FX.FEATS[FX.F_R12_EAR] == "ent_any" and FX.F_R12 == FX.F_R12_EAR + 8


def test_entity_features_read_the_memory(explorer):
    explorer.memory.note_turn([], "what is tycho", "map")
    explorer.clock_obj.t += 60
    explorer.memory.note_line("Tycho has bright rays.", by="guide")
    explorer.belief["kid"]["ear"] = {"names": [{"entity": "Tycho", "state": "linked", "p": 1.0}], "spoken": "tycho please"}
    rec = FX.record(explorer, {"t": "turn", "state": "end", "text": "Tycho please"}, {"available": False})
    en = rec["ent"]
    assert en["any"] and en["seen_before"] and en["guide_said"] and 0.5 < en["recency"] < 0.7
    x = FX.step_feats(rec, None)
    assert x[FX._IDX["ent_seen_before"]] == 1 and x[FX._IDX["ent_guide_said"]] == 1


def test_entity_features_never_reach_the_shipped_weights(explorer):
    from app.director_model import runtime
    # round 12: the routed r10 file (hot + echo) still reads its 242-wide prefix only; the primary r12 file reads all
    if runtime.model() is None or "weights_r10" not in runtime.routed_models():
        pytest.skip("no shipped weights")
    m = runtime.routed_models()["weights_r10"]
    assert runtime.model().F == FX.F
    explorer.memory.note_turn([], "what is tycho", "map")
    explorer.clock_obj.t += 30
    explorer.belief["kid"]["ear"] = {"names": [{"entity": "Tycho", "state": "linked", "p": 0.6}], "spoken": "tycho",
                                     "decoder_text": "Tycho", "agree": 1.0}
    rec1 = FX.record(explorer, {"t": "turn", "state": "end", "text": "tycho"}, {"available": False})
    rec0 = {k: v for k, v in rec1.items() if k not in ("ent", "link")}
    x1, x0 = FX.step_feats(rec1, None), FX.step_feats(rec0, None)
    assert not np.array_equal(x1, x0) and np.array_equal(x1[:m.F], x0[:m.F])
    toks = FX.step_tokens(rec1)
    o1, _ = m.step(None, x1, *toks)
    o0, _ = m.step(None, x0, *toks)
    for k in o1:
        assert np.array_equal(np.asarray(o1[k]), np.asarray(o0[k])), k
