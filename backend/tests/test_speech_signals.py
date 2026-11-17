"""Signals audit (docs/SPEECH_SIGNALS_AUDIT.md): the ear's names lists, its link decision, the sound-alike confirm,
and the round-12 Director features (appended; the shipped weights' decisions unchanged)."""
import asyncio
from pathlib import Path

import numpy as np
import pytest

from app import director, models_client, session as sessions
from app.config import settings
from app.director_model import features as FX
from app.gazetteer import Gazetteer
from app.moments import MomentIndex
from app.names_list import MAX, MAX_EAR, MAX_MOON, catalogue, dedupe_aliases, recent_names, screen_names

GAZ = Gazetteer(Path(__file__).resolve().parents[1] / "data" / "places.json")


def names(screen, **kw):
    return screen_names({"screen": screen}, **kw)


# ------------------------------------------------------------------------------------------------ names lists
def test_moon_screens_carry_every_place_and_every_piece_of_hardware():
    want = {e["name"] for e in catalogue()["place"] + catalogue()["hardware"]}
    for screen in ("library", "map"):
        got = {n["name"] for n in names(screen)}
        assert want <= got, (screen, sorted(want - got)[:5])
        assert len(names(screen)) <= MAX_MOON <= MAX_EAR
    assert names("library")[0]["name"].startswith("Apollo")       # the hardware library: hardware first
    assert names("map")[0]["name"] == "Sea of Tranquility"         # the map: the places first


def test_focused_screens_stay_short():
    for screen in ("cabin", "lesson", "video", "callsign", "prep"):
        assert len(names(screen)) <= MAX, screen


def test_no_alias_names_two_entries():
    for screen in ("library", "map", "cabin", "lesson", "video"):
        L = names(screen)
        own = {n["name"].lower() for n in L}
        seen = {}
        for n in L:
            for a in n.get("aliases") or []:
                assert a.lower() not in own, (screen, n["name"], a)
                assert a.lower() not in seen, (screen, n["name"], a, seen.get(a.lower()))
                seen[a.lower()] = n["name"]
                assert a.lower() != "descent stage"


def test_cabin_sites_own_their_short_names():
    L = {n["name"]: n for n in names("cabin")}
    assert "de Gerlache" in L["de Gerlache Crater Rim"]["aliases"] and "de Gerlache" not in L
    assert "Malapert" in L["Malapert Massif"]["aliases"] and "Malapert" not in L
    assert "Shackleton rim" in L["Shackleton Crater Rim"]["aliases"]
    assert "Shackleton" in L                                       # the crater itself ("explore Shackleton")
    assert "Lunar Roving Vehicle" not in L          # controls are not names: the ear would rewrite "the rover"


def test_spoken_forms_the_ear_produced_are_aliases():
    L = {n["name"]: n for n in names("map")}
    assert "Sea of Rain" in L["Sea of Rains"]["aliases"] and "Mare Imbrium" in L["Sea of Rains"]["aliases"]
    assert "Sea of Crisis" in L["Sea of Crises"]["aliases"]


def test_what_we_just_said_goes_first():
    L = names("map", recent=["That is Tsiolkovskiy, on the far side."])
    assert L[0]["name"] == "Tsiolkovskiy"
    assert [e["name"] for e in recent_names(["the crater Tycho"])] == ["Tycho"]
    assert recent_names([]) == [] and recent_names(["the sea of the moon"]) == []


def test_dedupe_aliases_drops_shared_and_name_colliding_aliases():
    out = dedupe_aliases([{"name": "A", "kind": "site", "aliases": ["x", "B", "descent stage"]},
                          {"name": "B", "kind": "site", "aliases": ["x", "y"]}])
    assert out == [{"name": "A", "kind": "site"}, {"name": "B", "kind": "site", "aliases": ["y"]}]


# ------------------------------------------------------------------------------------------------ the link decision
def link(text, ear, spoken=None):
    read = {"ear_names": ear, "available": True, "mentions": []}
    if spoken is not None:
        read["ear_spoken"] = spoken
    return director._link(text, read, GAZ)


def test_a_sure_link_acts():
    p, how, _ = link("fly to sea of rains", [{"heard": "sea of rains", "entity": "Sea of Rains", "state": "linked", "p": 1.0}])
    assert p.id == "imbrium" and how == "ear_link"


def test_a_low_p_link_is_offered_back_not_acted_on():
    # round 11: "fly to copernicus" -> "Fly Tycho pelicus", linked Tycho (p 1.0 there; here below LINK_ACT_P)
    p, how, c = link("fly tycho pelicus", [{"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 0.9}],
                     spoken="Fly tycho pelicus")
    assert p is None and how == "confirm" and c[0][0].id == "tycho"


def test_a_low_p_link_yields_to_what_the_ear_heard():
    # the written text carries the list spelling; the spoken words name another place by themselves
    p, how, _ = link("how big is orion", [{"heard": "Sea of Rains", "entity": "Sea of Rains", "state": "linked", "p": 0.8}],
                     spoken="how big is sea of crises")
    assert p.id == "crisium" and how == "alias"


def test_a_sound_alike_is_offered_back():
    p, how, c = link("tell me about the hurts brung", [], spoken="tell me about the hurts brung")
    assert p is None and how == "near" and c[0][0].id == "hertzsprung"


def test_no_name_no_offer():
    assert link("what is a crater", [], spoken="what is a crater") == (None, "", [])


def test_typed_turns_never_get_a_sound_alike_offer():
    assert director._link("tell me about the hurts brung", {"available": True, "mentions": []}, GAZ)[1] == ""


def run(c):
    return asyncio.run(c)


@pytest.fixture
def explorer(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    s = sessions.Session("t-sig", GAZ, MomentIndex(settings.data_dir / "index/clips.json"))
    return s


def test_the_director_asks_did_you_mean(explorer):
    r = run(director.direct("fly tycho pelicus", {"available": True, "ear_names": [
        {"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 0.9}], "ear_spoken": "Fly tycho pelicus"}, GAZ,
        explorer.index, {}))
    assert r["action"] == "ask" and r["source"] == "ear_confirm" and r["say"] == "Did you mean Tycho?"


def test_yes_to_the_confirm_is_the_name(explorer):
    explorer.belief["confirm_name"] = {"label": "Tycho", "at": explorer.clock()}
    assert explorer._confirm_reply("yeah") == "Tycho"
    assert "confirm_name" not in explorer.belief                 # one try
    explorer.belief["confirm_name"] = {"label": "Tycho", "at": explorer.clock()}
    assert explorer._confirm_reply("no the other one") is None and "confirm_name" not in explorer.belief
    explorer.belief["confirm_name"] = {"label": "Tycho", "at": explorer.clock() - 60}
    assert explorer._confirm_reply("yes") is None                # too late


# ------------------------------------------------------------------------------------------------ Director features
def test_round12_features_are_appended():
    assert FX.F_R11 == 242 and FX.FEATS[FX.F_R11] == "ear_names_avail" and FX.F_R12_EAR == FX.F_R11 + 11
    assert FX.FEATS[:FX.F_R11][-3:] == ["scr_video", "scr_prep", "st_video"]


def _turn_end(sess, ear):
    sess.belief["kid"]["ear"] = ear
    ev = {"t": "turn", "state": "end", "text": "fly to tycho"}
    return FX.record(sess, ev, {"available": False}), ev


def test_link_view_reads_the_ear(explorer):
    ear = {"names": [{"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 0.95},
                     {"heard": "zork", "entity": None, "state": "not_in_list", "p": 1.0}],
           "spoken": "fly to", "decoder_text": "Fly to Tycho", "agree": 0.67}
    v = FX.link_view(ear, ["Tycho", "Copernicus"])
    assert v["linked"] and v["p"] == 0.95 and not v["sure"] and v["not_in_list"] and v["step"] and not v["screen"]
    assert v["dec"] and v["agree"] == 0.67 and v["dec_name"]
    rec, _ = _turn_end(explorer, ear)
    assert rec["link"]["linked"] and rec["link"]["dec_name"]
    x = FX.step_feats(rec, None)
    i = FX._IDX
    assert x[i["ear_linked"]] == 1 and abs(x[i["ear_link_p"]] - 0.95) < 1e-6 and x[i["ear_link_sure"]] == 0
    assert x[i["ear_dec_name"]] == 1 and x[i["ear_names_avail"]] == 1
    # the round-7 slots stay as the shipped weights were trained: 0 (this ear has no n-best, confidence or hot tiers)
    for k in ("ear_conf", "ear_alts", "ear_alt_hot", "ear_rescored", "ear_tier_step", "ear_tier_screen"):
        assert x[i[k]] == 0, k


def test_new_features_never_reach_the_shipped_weights(explorer):
    """The r10 weights (F = 242) read the prefix only: the same turn end with and without the ear's new read-out gives
    bit-identical model outputs, so the guarded decisions cannot change."""
    from app.director_model import runtime
    m = runtime.model()
    if m is None:
        pytest.skip("no shipped weights")
    assert m.F == FX.F_R11
    ear = {"names": [{"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 0.5}], "spoken": "fly to tycho",
           "decoder_text": "Fly to Tycho", "agree": 0.4}
    rec1, _ = _turn_end(explorer, ear)
    rec0 = {k: v for k, v in rec1.items() if k != "link"}
    x1, x0 = FX.step_feats(rec1, None), FX.step_feats(rec0, None)
    assert not np.array_equal(x1, x0) and np.array_equal(x1[:m.F], x0[:m.F])
    toks = FX.step_tokens(rec1)
    o1, _ = m.step(None, x1, *toks)
    o0, _ = m.step(None, x0, *toks)
    for k in o1:
        assert np.array_equal(np.asarray(o1[k]), np.asarray(o0[k])), k
