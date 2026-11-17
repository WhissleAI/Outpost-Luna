"""The learned Director (backend/app/director_model): numpy runtime parity with the torch trainer, the shared step
features, and the session hook (shadow observes and never acts; `on` keeps the privacy guard)."""
import asyncio
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import director, models_client, session as sessions
from app.config import settings
from app.director_model import features as FX, runtime as RT
from app.gazetteer import Gazetteer
from app.main import app
from app.mission import capcom, registry
from app.moments import MomentIndex

FIX = Path(__file__).parent / "fixtures" / "director_model_parity.npz"


def run(c):
    return asyncio.run(c)


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    monkeypatch.setattr(models_client, "embed", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()
    RT.reset_stats()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_session(world, monkeypatch, mode="shadow"):
    monkeypatch.setenv("DIRECTOR_MODEL", mode)
    m = registry.create("shackleton_rim", 7)
    s = sessions.Session("dm-1", world[0], world[1], clock=Clock(), registry=registry)
    run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id}))
    return s


def test_numpy_streaming_matches_torch_parallel():
    """export.py saved held-out steps with the torch (int8-dequantized, parallel SSD) outputs; the numpy runtime,
    stepping one event at a time, must give the same probabilities."""
    m = RT.model()
    assert m is not None, RT._failed
    z = np.load(FIX)
    off = z["off"]
    worst = 0.0
    for i in range(len(off) - 1):
        st = None
        for t in range(off[i], off[i + 1]):
            o, st = m.step(st, z["feats"][t], z["toks"][t], z["wtok"][t], z["wfeat"][t])
            for k, _ in m.heads:
                worst = max(worst, float(np.abs(np.asarray(o[k]) - z[f"p_{k}"][t]).max()))
            mk = z["wtok"][t] > 0
            for k in FX.WORD_HEADS:
                if mk.any():
                    worst = max(worst, float(np.abs(o[k][mk] - z[f"p_{k}"][t][mk]).max()))
    assert worst < 1e-4, worst


def test_features_are_one_definition(world, monkeypatch):
    s = make_session(world, monkeypatch, "off")
    rec = FX.record(s, {"t": "words", "text": "move 20 percent to the shields"})
    x = FX.step_feats(rec, None)
    assert x.shape == (FX.F,) and len(FX.FEATS) == FX.F
    assert x[FX.FEATS.index("nlu_allocate")] == 1 and x[FX.FEATS.index("ev_words")] == 1
    toks, wtok, wfeat = FX.step_tokens(rec)
    assert (toks > 0).sum() == 6 and wfeat.shape == (FX.W, FX.WF)
    assert np.array_equal(FX.step_feats(rec, None), x)


def test_decode_and_compare_commands():
    o = {k: np.zeros(n) if n > 1 else 0.0 for k, n in FX.HEADS.items()}
    o["cmd_type"][FX.CMD_TYPES.index("allocate")] = 1
    o["amount"][FX.AMOUNTS.index("percent")] = 1
    o["load_to"][FX.LOADS.index("shields")] = 1
    o["load_from"][0] = 1
    for k in FX.WORD_HEADS:
        o[k] = np.zeros(FX.W)
    o["w_num"][-1] = 0.9
    c = FX.decode_command(o, ["shields", "to", "40"])
    assert FX.same_command(c, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 40}})


def test_shadow_runs_on_every_step_and_never_acts(world, monkeypatch):
    off = make_session(world, monkeypatch, "off")
    assert off.dm is None
    run(off.handle({"t": "typed", "text": "move 20% to shields"}))
    s = make_session(world, monkeypatch, "shadow")
    assert s.dm is not None
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    run(s.handle({"t": "words", "text": "move 20% to"}))
    run(s.handle({"t": "turn", "state": "end", "text": "move 20% to shields"}))
    s.dm.flush()
    assert [d["t"] for d in s.outbox if d["t"] != "floor"] == [d["t"] for d in off.outbox if d["t"] != "floor"]
    st = RT.stats()
    assert st["mode"] == "shadow" and st["steps"] >= 4 and st["turns"] == 1
    assert st["recent"] and st["recent"][-1]["rules"] == "command"


def test_on_mode_keeps_the_privacy_guard(world, monkeypatch):
    s = make_session(world, monkeypatch, "on")
    run(s.handle({"t": "typed", "text": "my name is Maya and I live at 12 Oak Street"}))
    assert any(d["t"] == "say" and d["priority"] == director.P_GUARD for d in s.outbox)


def test_stats_route(monkeypatch):
    monkeypatch.setenv("DIRECTOR_MODEL", "shadow")
    with TestClient(app) as c:
        r = c.get("/api/director/stats").json()
    assert r["mode"] == "shadow" and "act_agreement" in r and r["model"]["params"] > 0


def _out(act, p, cmd_type="none", load=None):
    o = {k: np.full(n, 0.01) for k, n in FX.HEADS.items() if n > 1}
    o["act"] = np.full(len(FX.ACTS), (1 - p) / (len(FX.ACTS) - 1))
    o["act"][FX.ACTS.index(act)] = p
    o["cmd_type"][FX.CMD_TYPES.index(cmd_type)] = 0.9
    o["amount"][FX.AMOUNTS.index("delta_up")] = 0.9
    if load:
        for j, ld in enumerate(load):
            o["load_to"][FX.LOADS.index(ld)] = 0.95 if len(load) == 1 else 0.5 - 0.1 * j
    for k in FX.WORD_HEADS:
        o[k] = np.zeros(FX.W)
    return o


def test_policy_is_cost_aware():
    """runtime.policy: guard wins; a rules command stands unless the fitted veto fires (never on yes/no); the model
    fills only above its fitted per-act threshold; a torn allocate asks 'shields or heaters?'."""
    thr = {"cmd": 0.9, "ignore": 0.8, "ask": 0.8, "veto": 0.95}
    rc = [{"type": "allocate", "to": "shields", "amount": {"kind": "delta", "value": 10}}]
    w = "more power to the shields".split()
    assert RT.policy(_out("ignore", 0.99), w, [], True, thr) is None
    assert RT.policy(_out("answer", 0.9), w, rc, False, thr) is None
    assert RT.policy(_out("answer", 0.97), w, rc, False, thr)["act"] == "ask_clarify"
    assert RT.policy(_out("answer", 0.99), ["yes"], [{"type": "confirm"}], False, thr) is None
    assert RT.policy(_out("answer", 0.99), w, rc, False, {**thr, "veto": None}) is None
    assert RT.policy(_out("command", 0.85, "allocate"), w, [], False, thr) is None
    torn = _out("command", 0.97, "allocate", ["shields", "heaters"])      # sure it's a command, not of the load
    assert RT.cmd_conf(torn) < 0.9 and RT.policy(torn, w, [], False, thr) is None
    assert RT.policy(_out("answer", 0.99), w, rc, False, thr, mission=False) is None   # Academy: no veto
    c = RT.policy(_out("command", 0.95, "allocate", ["shields"]), w, [], False, thr)
    assert c["act"] == "command" and c["command"]["to"] == "shields"
    a = RT.policy(_out("ask_clarify", 0.9, "allocate", ["shields", "heaters"]), "more power to the".split(), [], False, thr)
    assert a == {"act": "ask_clarify", "clarify": ["shields", "heaters"]}


def test_policy_never_silences_a_very_short_turn():
    """Round 9 (RESULTS.md): with ignore_min_words, the model may not silence a turn shorter than that ("far side" said
    plainly is a real request); longer room talk / echo can still be silenced. None keeps the old behaviour."""
    thr = {"cmd": 0.95, "ignore": 0.8, "ask": 1.01, "veto": None, "ignore_min_words": 3}
    assert RT.policy(_out("ignore", 0.99), ["far", "side"], [], False, thr) is None
    assert RT.policy(_out("ignore", 0.99), "my brother took my pencil".split(), [], False, thr) == {"act": "ignore"}
    assert RT.policy(_out("ignore", 0.99), ["far", "side"], [], False, {**thr, "ignore_min_words": None}) == {"act": "ignore"}


def test_default_mode_is_guarded_with_rules_fallback(monkeypatch):
    """Round 10 (RESULTS.md): the default is `guarded` (was `shadow` since 2026-11-14, owner: until a round passes the
    gate). The shipped weights enable the model only in the classes that passed the full class gate (hot, echo), keep
    their fitted cost-aware thresholds, and with no model output the rules decide every turn."""
    monkeypatch.delenv("DIRECTOR_MODEL", raising=False)
    assert RT.mode() == "guarded"
    pol = RT.model().meta.get("policy")
    assert pol and pol["cmd"] >= 0.9 and (pol["veto"] is None or pol["veto"] >= 0.95)
    assert sorted(pol["classes"]) == ["echo", "hot"]
    assert not RT.allowed(pol, "quiet") and not RT.allowed(pol, "nav") and not RT.allowed(pol, "answer")
    sh = RT.Shadow.__new__(RT.Shadow)
    assert sh.decide_turn(None, "more power to the shields", False) is None


def test_situation_classes_are_read_from_session_state():
    """Round 10: the per-class enable keys on runtime.situation(rec, text), session state the runtime has at the turn
    end. Order: an on-screen control / step option said (hot) > fewer than 3 words (short) > our line or a clip on the
    air (echo) > a video playing (video) > anything else (quiet)."""
    long_ = "my brother took my pencil"
    assert RT.situation({"hot": {"step": 1, "screen": 0}, "on_air": True}, long_) == "hot"
    assert RT.situation({"hot": {"step": 0, "screen": 2}}, long_) == "hot"
    assert RT.situation({"on_air": True}, "far side") == "short"
    assert RT.situation({"on_air": True}, long_) == "echo"
    assert RT.situation({"speaking": True}, long_) == "echo"
    assert RT.situation({"playing_kind": "crew"}, long_) == "echo"
    assert RT.situation({"video_on": True}, long_) == "video"
    assert RT.situation({"hot": {"step": 0, "screen": 0}, "on_air": False}, long_) == "quiet"
    assert RT.situation(None, long_) == "quiet"
    assert set(RT.SITUATIONS) == {"hot", "short", "echo", "video", "quiet"}


def _guarded_shadow(monkeypatch, classes, rec):
    class _M:
        meta = {"policy": {"cmd": 0.95, "ignore": 0.8, "ask": 1.01, "veto": None, "ignore_min_words": 3,
                           "answer_ignore": 0.9, "nav": None, "classes": classes}}
    monkeypatch.setattr(RT, "model", lambda: _M())
    sh = RT.Shadow.__new__(RT.Shadow)
    sh.sess = type("S", (), {"belief": {"mission_id": "m1", "mode": "mission"}})()
    sh.cur = {"rec": rec}
    return sh


def test_guarded_mode_acts_only_in_listed_classes(monkeypatch):
    """DIRECTOR_MODEL=guarded: the model may act only in the situation classes its policy lists (each proven on the
    full gate to add no wrong action over the rules); the rules decide everywhere else. `on` keeps acting everywhere;
    `shadow` / `off` never act."""
    text = "my brother took my pencil"
    out = _out("ignore", 0.99)
    monkeypatch.setenv("DIRECTOR_MODEL", "guarded")
    assert RT.mode() == "guarded"
    assert _guarded_shadow(monkeypatch, ["echo"], {"on_air": True}).decide_turn(out, text, False) == {"act": "ignore"}
    assert _guarded_shadow(monkeypatch, ["echo"], {}).decide_turn(out, text, False) is None          # quiet: rules
    assert _guarded_shadow(monkeypatch, ["echo"], {"on_air": True, "hot": {"step": 1}}).decide_turn(out, text, False) is None
    assert _guarded_shadow(monkeypatch, [], {"on_air": True}).decide_turn(out, text, False) is None   # no classes
    sh = _guarded_shadow(monkeypatch, ["echo"], {"on_air": True})
    assert sh.decide_answer(out) is False                       # the lesson silencing has its own class
    assert _guarded_shadow(monkeypatch, ["answer"], {}).decide_answer(out) is True
    assert sh.decide_turn(out, text, True) is None              # the privacy guard still wins
    monkeypatch.setenv("DIRECTOR_MODEL", "on")
    assert _guarded_shadow(monkeypatch, ["echo"], {}).decide_turn(out, text, False) == {"act": "ignore"}
    for m in ("shadow", "off"):
        monkeypatch.setenv("DIRECTOR_MODEL", m)
        assert _guarded_shadow(monkeypatch, ["echo"], {"on_air": True}).decide_turn(out, text, False) is None


def test_guarded_without_classes_is_the_rules(monkeypatch):
    """Safe default: DIRECTOR_MODEL=guarded with weights whose policy has no "classes" key (every round before 10, or a
    hand-edited weights.json) enables the model nowhere: the turn, the navigate fill and the lesson silencing all stay
    with the rules."""
    class _M:
        meta = {"policy": {"cmd": 0.5, "ignore": 0.5, "ask": 0.5, "veto": None, "ignore_min_words": 3,
                           "answer_ignore": 0.5, "nav": 0.5}}
    monkeypatch.setattr(RT, "model", lambda: _M())
    monkeypatch.setenv("DIRECTOR_MODEL", "guarded")
    sh = RT.Shadow.__new__(RT.Shadow)
    sh.sess = type("S", (), {"belief": {"mission_id": "m1", "mode": "mission"}})()
    text = "my brother took my pencil"
    for rec in ({}, {"on_air": True}, {"hot": {"step": 1}}, {"video_on": True}):
        sh.cur = {"rec": rec}
        assert sh.decide_turn(_out("ignore", 0.99), text, False) is None
    assert sh.decide_answer(_out("ignore", 0.99)) is False
    assert sh.decide_nav(_out("ignore", 0.99), "map") is None
    assert not any(RT.allowed({"cmd": 0.5}, c) for c in RT.SITUATIONS + ("nav", "answer"))
    monkeypatch.setenv("DIRECTOR_MODEL", "on")                  # the same weights do act when unguarded
    sh.cur = {"rec": {}}
    assert sh.decide_turn(_out("ignore", 0.99), text, False) == {"act": "ignore"}
    assert sh.decide_answer(_out("ignore", 0.99)) is True
