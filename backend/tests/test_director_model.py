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


def test_default_mode_is_on_with_rules_fallback(monkeypatch):
    """Switch-on criteria met (director_model/RESULTS.md, round 4): `on` by default; the shipped weights carry the fitted
    cost-aware thresholds; with no weights the rules decide every turn."""
    monkeypatch.delenv("DIRECTOR_MODEL", raising=False)
    assert RT.mode() == "on"
    pol = RT.model().meta.get("policy")
    assert pol and pol["cmd"] >= 0.9 and (pol["veto"] is None or pol["veto"] >= 0.95)
    sh = RT.Shadow.__new__(RT.Shadow)
    assert sh.decide_turn(None, "more power to the shields", False) is None
