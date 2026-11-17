"""libarc ABI 2 read-outs in the backend (docs/ARC_ABI2.md): they reach the rules and the round-13 feature slots, never
the shipped Director weights' inputs; Arc's sound-alike names in "Did you mean"; typed quantities in mission amounts;
the echo reference's playback flag."""
import asyncio

import numpy as np
import pytest

from app import director as D
from app import session as sessions
from app.config import settings
from app.director_model import features as FX
from app.gazetteer import Gazetteer
from app.mission import nlu
from app.moments import MomentIndex

ABI2 = {"uconf": 0.41, "min_wconf": 0.12, "nbest": [{"text": "fly to tycho", "p": 0.3}],
        "almost": [{"heard": "tie go", "candidate": "Tycho", "p": 0.83, "kb_index": 3}],
        "quantities": [{"type": "percent", "value": 40, "unit": "%", "relative": 0}],
        "clean_text": "fly to", "disfl": [{"i": 0, "w": "um", "kind": "filler"}], "n_dropped": 1,
        "playback_leak": 0.2, "playback": False, "barge": True, "eot": 0.8}
BASE = {"names": [{"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 0.5}], "spoken": "fly to tycho",
        "decoder_text": "Fly to Tycho", "agree": 0.4}


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture()
def explorer(world):
    s = sessions.Session("abi2", world[0], world[1])
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    return s


def _turn_end(sess, ear):
    sess.belief["kid"]["ear"] = ear
    return FX.record(sess, {"t": "turn", "state": "end", "text": "fly to tycho"}, {"available": False})


# ------------------------------------------------------------------------------------------- the feature layout
def test_round13_block_is_appended():
    assert FX.F_R11 == 242 and FX.F_R12 == 261 and FX.FEATS[FX.F_R12] == "e13_avail" and FX.F == FX.F_R13 == 275


def test_abi2_fills_only_the_round13_slots(explorer):
    rec1 = _turn_end(explorer, {**BASE, **ABI2, "conf": None, "alts": []})
    explorer._r7_prev = None
    rec0 = _turn_end(explorer, dict(BASE, conf=None, alts=[]))
    assert rec1["e13"] and "e13" not in rec0
    assert rec1["ear"] == rec0["ear"] and rec1["link"] == rec0["link"]
    rec0 = {k: v for k, v in rec1.items() if k != "e13"}      # the same record without the ABI 2 read-out
    x1, x0 = FX.step_feats(rec1, None), FX.step_feats(rec0, None)
    assert np.array_equal(x1[:FX.F_R12], x0[:FX.F_R12]) and not np.array_equal(x1, x0)
    i = FX._IDX
    assert x1[i["e13_almost"]] == 1 and abs(x1[i["e13_almost_p"]] - 0.83) < 1e-6 and x1[i["e13_barge"]] == 1
    assert x1[i["e13_qty"]] == 1 and abs(x1[i["e13_uconf"]] - 0.41) < 1e-6
    for k in ("ear_conf", "ear_alts", "ear_alt_hot", "ear_rescored", "ear_tier_step", "ear_tier_screen"):
        assert x1[i[k]] == 0, k     # the round-7 slots: as r10 was trained


def test_abi2_never_reaches_the_shipped_weights(explorer):
    """Both shipped files (round 12: r12 xl, F = 261, and the routed r10 xl, F = 242): the same turn end with and
    without libarc ABI 2's read-out gives bit-identical outputs on every head, so the guarded decisions cannot change
    (as #121's test for the round-12 block)."""
    from app.director_model import runtime
    if runtime.model() is None:
        pytest.skip("no shipped weights")
    ms = [(runtime.model(), FX.F_R12)] + [(m, FX.F_R11) for m in runtime.routed_models().values()]
    rec1 = _turn_end(explorer, {**BASE, **ABI2, "conf": None, "alts": []})
    rec0 = {k: v for k, v in rec1.items() if k != "e13"}
    x1, x0 = FX.step_feats(rec1, None), FX.step_feats(rec0, None)
    toks = FX.step_tokens(rec1)
    for m, f in ms:
        assert m.F == f
        assert not np.array_equal(x1, x0) and np.array_equal(x1[:m.F], x0[:m.F])
        o1, _ = m.step(None, x1, *toks)
        o0, _ = m.step(None, x0, *toks)
        for k in o1:
            assert np.array_equal(np.asarray(o1[k]), np.asarray(o0[k])), k


def test_the_ear_message_keeps_conf_and_alts_empty(explorer):
    """on_listen stores the ABI 2 keys apart; conf / alts stay what the ear sends for them (null / [])."""
    msg = {"t": "words", "final": True, "text": "fly to Tycho", "conf": None, "alts": [], **BASE, **ABI2}
    asyncio.run(explorer.on_listen(msg))
    ear = explorer.belief["kid"]["ear"]
    assert "conf" not in ear and ear["alts"] == [] and ear["almost"] == ABI2["almost"] and ear["barge"] is True


# ------------------------------------------------------------------------------------------- rules
def test_arc_almost_is_offered_never_acted(world, monkeypatch):
    gaz = world[0]
    read = {"ear_names": [], "ear_spoken": "fly to tie go", "available": True, "mentions": [],
            "ear_almost": [{"candidate": "Tycho", "p": 0.83}]}
    for pol in ("arc_first", "arc", "ours_first"):
        monkeypatch.setattr(D, "ALMOST_POLICY", pol)
        place, how, cands = D._link("fly to tie go", read, gaz)
        assert place is None and how == "near" and cands[0][0].id == "tycho", pol
    monkeypatch.setattr(D, "ALMOST_POLICY", "arc_first")
    low = {**read, "ear_almost": [{"candidate": "Tycho", "p": 0.2}]}
    assert D.arc_almost(low["ear_almost"], gaz) is None


def test_quantities_fill_a_missing_amount_but_not_one_more():
    q = [{"type": "percent", "value": 45, "unit": "%", "relative": 1}]
    assert nlu._number("give the rover more power", {"ear_quantities": q}) == 45
    one = [{"type": "number", "value": 1, "unit": None, "relative": 1}]
    assert nlu._number("give the rover one more", {"ear_quantities": one}) is None
    assert nlu._number("shields to 40 percent", {"ear_quantities": q}) == 40   # the words' own number first


def test_same_turn_clean_text():
    assert D._same_turn("give protection 80 more percent", "um give protection 80 more percent")
    assert not D._same_turn("fly to Tycho", "something else")


@pytest.mark.parametrize("ear,drop", [({"playback_leak": 0.9, "barge": True}, True), ({"playback_leak": 0.85}, True),
                                      ({"playback_leak": 0.84, "playback": True}, False), ({"playback_leak": 0.0}, False)])
def test_the_real_laptop_rule_drops_on_the_leak_alone(ear, drop):
    """docs/ARC_ABI2.md section 8: leak >= 0.85 is our own playback; a barge-in no longer keeps it (it fired on 64 % of
    our own lines on a real laptop)."""
    assert sessions.ear_playback(ear) is drop


@pytest.mark.parametrize("ear,drop", [({"playback": True, "barge": False}, True), ({"playback": True, "barge": True}, False),
                                      ({"playback": False}, False), (None, False), ({}, False)])
def test_playback_flag_needs_no_barge_in(ear, drop):
    assert sessions.ear_playback(ear) is drop


def test_a_playback_turn_is_ignored_as_echo(explorer):
    explorer.belief["kid"]["ear"] = {"playback": True, "barge": False, "names": []}
    asyncio.run(explorer._turn("where is tycho", "listen"))
    assert explorer.routes[-1]["reason"] == "echo"


def test_ref_relay_message():
    from app.listen import ref_message
    assert ref_message({"t": "ref", "at": "1.5", "pcm": "AAAA"}) == {"t": "ref", "at": 1.5, "pcm": "AAAA"}
    assert ref_message({"t": "ref", "at": None, "pcm": "AAAA"})["at"] is None
    assert ref_message({"t": "ref", "pcm": ""}) is None and ref_message({"t": "ref", "at": "x", "pcm": "AA"}) is None
    assert ref_message({"t": "ref", "pcm": "A" * (16000 * 2 * 13 * 4 // 3)}) is None
