"""Round 15 (director_model/RESULTS.md): the "raw" feature set, the reply / slot heads, and the shadow-only runtime.

- The raw set holds perception + state only: no regex flag, no mission NLU, no router outcome, no grader result.
- A raw turn end reads the record the Session snapshots BEFORE routing (Shadow.perceive), so its inputs never depend on
  the route the rules took (the legacy record is taken after the router's floor / open-turn bookkeeping).
- weights_r15 (when shipped) runs in SHADOW only: whatever it outputs, every decision the Session makes is the same
  as without it; it is logged to the turn log and /api/director/stats, never consulted.
- The shipped policy is unchanged: weights.json (r12) + weights_r10 routes, DEFAULT_MODE guarded.
"""
import asyncio
import json

import numpy as np
import pytest

from app import director, models_client, session as sessions
from app.config import settings
from app.director_model import features as FX, runtime as RT
from app.gazetteer import Gazetteer
from app.mission import capcom, registry
from app.moments import MomentIndex

HAS_R15 = (RT.MODEL_DIR / f"{RT.R15_FILE}.json").exists()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def run(c):
    return asyncio.run(c)


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture
def clean(monkeypatch):
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()
    RT.reset_stats()
    yield
    RT._r15.clear()


FORBIDDEN = ("lx_", "nlu_", "rt_", "rw_", "nav_", "hot_", "lesson_graded", "lesson_pass", "gaz_", "has_num", "n_loads",
             "last_stop", "opt_named", "neg_now", "prev_ignored", "prev_acted", "tag_q", "tag_cmd", "tag_dd", "cc",
             "emo_", "ear_conf", "ear_alts", "ear_alt_hot", "ear_rescored", "ear_tier", "e13_nbest")


def test_the_raw_set_has_no_rules_output():
    assert FX.F_RAW == len(FX.RAW_FEATS) and len(set(FX.RAW_FEATS)) == FX.F_RAW
    for k in FX.RAW_KEEP:
        assert k in FX.FEATS, k
        assert not k.startswith(FORBIDDEN), f"{k} is a rules output (regex / NLU / router / grader) or a dead slot"
    # what it keeps: the ear, the entity layer, our own audio, the screen / lesson / mission state and timing
    for k in ("dd", "ear_link_p", "ear_agree", "e13_leak", "e13_qty", "ent_any", "on_air", "echo_recent", "scr_lesson",
              "st_choice", "offer_on", "lesson_step", "power", "since_play", "line_gap"):
        assert k in FX.RAW_KEEP, k
    assert FX.RAW_FEATS[-FX.EMB_DIM:] == [f"emb_{i}" for i in range(FX.EMB_DIM)]
    # the legacy set is untouched: every shipped file still reads its own prefix
    assert FX.F == FX.F_R13 == 275


def test_tag_view_keeps_labels_and_counts_only():
    out = {"utterances": [{"act": [{"tag": "discourse.act.question", "on": True},
                                   {"tag": "discourse.act.statement", "on": False}],
                           "intent": [{"tag": "intent.request_information", "on": True},
                                      {"tag": "discourse.intent.qa_factoid", "on": True},
                                      {"tag": "discourse.intent.takeaway_order", "on": True}]}],
           "spans": [{"type": "entity.mention.place", "text": "Tycho", "family": "entity"},
                     {"type": "safety.pii.private_name", "text": "Sam", "family": "pii"}],
           "events": [{"type": "discourse.assistant.command_complete"}]}
    v = FX.tag_view(out)
    assert v["act"] == ["question"] and set(v["intent"]) == {"request_information", "qa_factoid", "takeaway_order"}
    assert v["spans"] == {"entity.mention.place": 1, "safety.pii": 1} and v["complete"]
    assert "Tycho" not in json.dumps(v) and "Sam" not in json.dumps(v)
    rec = {"kind": "turn_end", "now": 0.0, "text": "how big is tycho", "mission": False, "kid_open": True,
           "pending_confirm": False, "referent": False, "last_place": False,
           "perc": {"tag": v, "emb": [0.1] * FX.EMB_DIM}}
    x = FX.raw_feats(rec, None)
    assert x[FX._RIDX["tact_question"]] == 1 and x[FX._RIDX["tint_qa_factoid"]] == 1
    assert x[FX._RIDX["tint_other"]] == 1          # takeaway_order is not in the kids' list
    assert x[FX._RIDX["emb_avail"]] == 1 and abs(float(x[FX._EMB0]) - 0.1) < 1e-6


def _hear(s, clock, text):
    run(s.handle({"t": "turn", "state": "start", "text": text}))
    clock.t += 0.3
    run(s.handle({"t": "words", "text": text}))
    run(s.handle({"t": "arc", "device_directed": 0.9, "command_complete": None}))
    clock.t += 0.4
    run(s.handle({"t": "turn", "state": "end", "text": text}))
    clock.t += 3.0


def _gen_session(world, sid):
    """A Session driven as the generator drives it (a Shadow with a sink: training data)."""
    clock = Clock()
    s = sessions.Session(sid, world[0], world[1], clock=clock, registry=registry)
    sink: list = []
    s.dm = RT.Shadow(s, sink=sink, run_model=False)
    run(s.handle({"t": "hello", "mode": "cadet"}))
    run(s.handle({"t": "ui", "event": "screen", "screen": "library", "step_type": None, "step_options": [],
                  "offer": None}))
    return s, clock, sink


def test_a_raw_turn_end_reads_the_pre_routing_snapshot(world, clean, monkeypatch):
    calls = []

    async def tag(text, domain="assistant", command_context=None):
        calls.append(("tag", text))
        return {"utterances": [{"act": [{"tag": "discourse.act.question", "on": True}]}], "spans": []}

    async def embed(texts, kind="query", timeout=None):
        calls.append(("embed", texts[0]))
        return [[0.05] * FX.EMB_DIM for _ in texts]
    monkeypatch.setattr(models_client, "tag", tag)
    monkeypatch.setattr(models_client, "embed", embed)
    s, clock, sink = _gen_session(world, "r15-snap")
    _hear(s, clock, "how big is tycho crater")       # a question: the direct path (the floor is reset before the step)
    _hear(s, clock, "um")                            # filler: the router ignores it (the step comes first)
    s.dm.flush()
    ends = [st["rec"] for st in sink if st["rec"]["kind"] == "turn_end"]
    assert len(ends) == 2 and all("raw" in r for r in ends)
    for r in ends:
        assert r["raw"]["route"] is None and r["raw"]["perc"]["emb"] is not None
        assert r["raw"]["floor"] == "kid"            # before routing, the kid holds the floor on both paths
    assert ends[0]["floor"] == "none"                # the legacy record of the direct path: after its bookkeeping
    assert ends[1]["floor"] == "kid"                 # ... and of the ignored turn: before it (the route leaked)
    assert ("embed", "how big is tycho crater") in calls and ("embed", "um") in calls
    # the raw vector carries the perception, never the route
    x = FX.raw_feats(ends[0], None)
    assert x[FX._RIDX["perc_avail"]] == 1 and x[FX._RIDX["tact_question"]] == 1
    assert x[FX._RIDX["floor_kid"]] == 1 and FX.step_feats(ends[0], None)[FX._IDX["floor_kid"]] == 0


def test_perceive_is_a_no_op_without_a_shadow_model(world, clean, monkeypatch):
    """The app pays for the pre-routing read only when weights_r15 is loaded (or the generator collects data)."""
    monkeypatch.setenv("DIRECTOR_R15", "off")
    RT._r15.clear()

    async def boom(*a, **k):
        raise AssertionError("no model-server call without the raw shadow model")
    monkeypatch.setattr(models_client, "embed", boom)
    clock = Clock()
    s = sessions.Session("r15-noop", world[0], world[1], clock=clock, registry=registry)
    run(s.handle({"t": "hello", "mode": "cadet"}))
    if s.dm is None:
        pytest.skip("DIRECTOR_MODEL=off in this environment")
    assert not s.dm.wants_perception()
    run(s.dm.perceive({"t": "typed", "text": "hello"}))
    assert s.dm.snap is None


def test_the_shipped_policy_is_unchanged():
    assert RT.DEFAULT_MODE == "guarded"
    meta = json.loads((RT.MODEL_DIR / "weights.json").read_text())
    assert meta.get("feat_set", "full") == "full"
    assert meta["policy"]["classes"] == ["quiet"] and meta["policy"]["routes"] == {"hot": "weights_r10",
                                                                                   "echo": "weights_r10"}
    assert RT.R15_FILE not in (meta["policy"].get("routes") or {}).values()


@pytest.mark.skipif(not HAS_R15, reason="weights_r15 not shipped")
def test_weights_r15_load_as_a_raw_shadow_model():
    m = RT.Model(RT.MODEL_DIR, RT.R15_FILE)
    assert m.feat_set == "raw" and m.F == FX.F_RAW and m.meta.get("shadow_only") is True
    assert m.zero.size == 0
    names = {n for n, _, _ in m.ptr}
    assert names == {"reply", "ent"}
    assert len(m.meta["ptr_cands"]["reply"]) == dict((n, k) for n, k, _ in m.ptr)["reply"]
    o, _ = m.step(None, np.zeros(m.F, np.float32), np.zeros(FX.K, np.int64), np.zeros(FX.W, np.int64),
                  np.zeros((FX.W, FX.WF), np.float32))
    for k in ("act", "reply", "ent", "opt", "nav_arg", "style"):
        assert abs(float(np.sum(o[k])) - 1.0) < 1e-4, k
    v = RT.r15_view(m, o)
    assert set(v) >= {"act", "p", "reply", "ent", "opt", "nav_arg", "style"}
    assert all(isinstance(x, (str, int, float, list, dict, type(None))) for x in v.values())


@pytest.mark.skipif(not HAS_R15, reason="weights_r15 not shipped")
def test_weights_r15_parity_fixture():
    """numpy streaming == the torch parallel pass (export.py wrote the fixture from the same file)."""
    from pathlib import Path
    f = Path(__file__).parent / "fixtures" / f"director_model_parity_{RT.R15_FILE}.npz"
    z = np.load(f)
    m = RT.Model(RT.MODEL_DIR, RT.R15_FILE)
    off = z["off"]
    worst = 0.0
    for i in range(len(off) - 1):
        st = None
        for t in range(off[i], off[i + 1]):
            o, st = m.step(st, z["feats"][t], z["toks"][t], z["wtok"][t], z["wfeat"][t])
            for k in ("act", "nav", "reply", "opt", "nav_arg"):
                worst = max(worst, float(np.abs(np.asarray(o[k]) - z[f"p_{k}"][t]).max()))
    assert worst < 2e-3, worst


def _app_session(world, sid, clock):
    s = sessions.Session(sid, world[0], world[1], clock=clock, registry=registry)
    run(s.handle({"t": "hello", "mode": "cadet"}))
    run(s.handle({"t": "ui", "event": "screen", "screen": "library", "step_type": None, "step_options": [],
                  "offer": None}))
    return s


def _script(s, clock):
    for t in ("how big is tycho crater", "oh it's okay", "where did apollo 11 land", "open the library",
              "what is regolith"):
        _hear(s, clock, t)
    return [{k: v for k, v in d.items() if k not in ("id", "ts")} for d in s.outbox]


@pytest.mark.skipif(not HAS_R15, reason="weights_r15 not shipped")
def test_the_raw_model_never_changes_a_decision(world, clean, monkeypatch):
    async def tag(text, domain="assistant", command_context=None):
        return {"utterances": [{"act": [{"tag": "discourse.act.question", "on": True}]}], "spans": []}

    async def embed(texts, kind="query", timeout=None):
        return [[0.05] * FX.EMB_DIM for _ in texts]
    monkeypatch.setattr(models_client, "tag", tag)
    monkeypatch.setattr(models_client, "embed", embed)
    monkeypatch.setenv("DIRECTOR_MODEL", "guarded")
    outs = {}
    for flag in ("off", "on"):
        monkeypatch.setenv("DIRECTOR_R15", flag)
        RT._r15.clear()
        RT.reset_stats()
        director.RULES.clear()
        clock = Clock()
        s = _app_session(world, f"r15-same-{flag}", clock)
        outs[flag] = _script(s, clock)
        if flag == "on":
            assert s.dm.wants_perception()
            st = RT.stats()["r15"]
            assert st["shadow_only"] and st["turns"] == 5 and st["perceived"] == 5, st
            rc = st["recent"][-1]
            assert set(rc) >= {"rules", "r15", "reply", "opt", "ent", "nav_arg", "style"}
            ex = s.dm.explain(s.dm.cur and s.dm.cur.get("out"), "what is regolith")
            assert "r15" in ex and "regolith" not in json.dumps(ex["r15"])
    assert outs["on"] == outs["off"], "the raw shadow model changed what the Session did"
