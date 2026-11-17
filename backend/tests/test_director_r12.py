"""Round 12: train / serve parity of the learned Director's inputs (director_model/RESULTS.md, Round 12).

The live path: model_server arc_ear.EarStream emits a kid turn's messages, listen.py posts each one unchanged into
Session.handle, and the Shadow hook computes features.step_feats on every event. The training path: the decode cache
stores replay.compact(those messages) and gen_sessions.py posts replay.messages(cached) into the same Session class,
then label_session computes features.step_feats over the sink. The same turns through both paths must give identical
feature vectors (and word tokens) at every step, with the ear_* / ent_* read-outs filled and command_complete absent.
"""
import asyncio
from pathlib import Path

import numpy as np
import pytest

from app import models_client, session as sessions
from app.config import settings
from app.director_model import features as FX, replay as RP, runtime as RT
from app.gazetteer import Gazetteer
from app.moments import MomentIndex

GAZ = Gazetteer(Path(__file__).resolve().parents[1] / "data" / "places.json")
IDX = MomentIndex(settings.data_dir / "index/clips.json")


def _arc(dd):
    # everything arc_ear._finish sends; the Session reads device_directed / command_complete / act / safety only
    return {"t": "arc", "at": 2.4, "device_directed": dd, "directed_head": 0.31, "directed": True,
            "command_complete": None, "speaker": None, "act": None, "intent": None, "utt_open": False, "speech": True,
            "audio_events": [{"tag": "speech", "p": 0.9}], "bio_events": [], "cc_events": [], "names": [], "rtf": 0.21}


def _final(text, spoken, names, dec, agree):
    return {"t": "words", "text": text, "final": True, "spoken": spoken, "names": names, "tags": [], "conf": None,
            "alts": [], "decoder_text": dec, "agree": agree}


TYCHO = {"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 1.0, "tag": "lunar_feature",
         "kind": "lunar_feature", "t0": 0.9, "t1": 1.3, "src": "rnnt", "via": "name"}
# What EarStream sent for three kid turns on the library screen (shapes as in real r12 decodes): a sure link, a low-p
# link whose decoder text names another place, and a turn naming nothing (empty names list, decoder agrees).
LIVE = [
    [{"t": "turn", "state": "start", "text": "Tell me"}, {"t": "words", "text": "Tell me", "final": False},
     {"t": "words", "text": "Tell me about", "final": False}, _arc(0.83),
     _final("Tell me about Tycho.", "Tell me about tycho.", [TYCHO], "Tell me about Tycho.", 1.0),
     {"t": "turn", "state": "end", "text": "Tell me about Tycho."}],
    [{"t": "turn", "state": "start", "text": "How big is"}, {"t": "words", "text": "How big is", "final": False},
     _arc(0.71),
     _final("How big is Tycho pelicus?", "How big is tycho pelicus?", [{**TYCHO, "p": 0.93}],
            "How big is Copernicus?", 0.6),
     {"t": "turn", "state": "end", "text": "How big is Tycho pelicus?"}],
    [{"t": "turn", "state": "start", "text": "What is a crater?"}, _arc(0.66),
     _final("What is a crater?", "What is a crater?", [], "What is a crater?", 1.0),
     {"t": "turn", "state": "end", "text": "What is a crater?"}],
]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Capture:
    """Stands in for the loaded weights: records exactly what the live Shadow feeds the model."""
    F = FX.F

    def __init__(self):
        self.x, self.toks = [], []
        self.meta = {"policy": {}}

    def step(self, state, x, toks, wtok, wfeat):
        self.x.append(np.array(x))
        self.toks.append((np.array(toks), np.array(wtok), np.array(wfeat)))
        return {"act": np.eye(len(FX.ACTS))[FX.ACTS.index("wait")]}, state


def _session(sid, clock):
    s = sessions.Session(sid, GAZ, IDX, clock=clock)
    return s


async def _drive(sess, clock, turns):
    await sess.handle({"t": "hello", "mode": "cadet", "session": sess.id if hasattr(sess, "id") else "t"})
    await sess.handle({"t": "ui", "event": "screen", "screen": "library", "step_type": None, "step_options": [],
                       "offer": None})
    for msgs in turns:
        clock.t += 6.0
        for m in msgs:
            clock.t += 0.4
            await sess.handle(dict(m))
    sess.dm.flush()


@pytest.fixture
def quiet(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", none)
    monkeypatch.setenv("DIRECTOR_MODEL", "shadow")      # the model runs on every event and never acts


def test_live_and_replayed_turns_give_identical_features(quiet, monkeypatch):
    # live: the relay's messages, verbatim; the Shadow's own feature computation (what the weights would read)
    cap = Capture()
    monkeypatch.setattr(RT, "model", lambda: cap)
    clock_a = Clock()
    a = _session("par-live", clock_a)
    a.dm = RT.Shadow(a, sink=[], run_model=True)
    asyncio.run(_drive(a, clock_a, LIVE))
    # training: what the decode cache keeps (replay.compact), replayed as gen_sessions does (replay.messages), through
    # the generator's sink and label_session's feature call
    cached = []
    for msgs in LIVE:
        ev, fx = RP.compact(msgs)
        hyp = " ".join(e["text"] for e in ev if e["t"] == "words" and e["final"])
        cached.append({"hyp": hyp, "events": ev, "x": {"final": fx}})
    replayed = [RP.messages(d) for d in cached]
    assert all(r is not None for r in replayed)
    clock_b = Clock()
    b = _session("par-train", clock_b)
    sink: list = []
    b.dm = RT.Shadow(b, sink=sink, run_model=False)
    asyncio.run(_drive(b, clock_b, replayed))
    prev, xs, tk = None, [], []
    for st in sink:
        xs.append(FX.step_feats(st["rec"], prev))
        tk.append(FX.step_tokens(st["rec"]))
        prev = st["rec"]
    assert len(xs) == len(cap.x) > 0
    for i, (x_live, x_train) in enumerate(zip(cap.x, xs)):
        diff = [FX.FEATS[j] for j in np.nonzero(x_live != x_train)[0]]
        assert not diff, (i, sink[i]["rec"]["kind"], diff)
        for u, v in zip(cap.toks[i], tk[i]):
            assert np.array_equal(u, v), i
    # the read-outs the round-12 model learns from are really there, at the turn ends, in both paths
    ends = [i for i, st in enumerate(sink) if st["rec"]["kind"] == "turn_end"]
    assert len(ends) == 3
    I = FX._IDX
    x1, x2, x3 = (xs[i] for i in ends)
    assert x1[I["ear_names_avail"]] == 1 and x1[I["ear_linked"]] == 1 and x1[I["ear_link_sure"]] == 1
    assert x1[I["ear_dec_avail"]] == 1 and x1[I["ear_agree"]] == 1 and x1[I["ent_any"]] == 1
    assert x2[I["ear_link_sure"]] == 0 and abs(x2[I["ear_link_p"]] - 0.93) < 1e-6 and x2[I["ear_dec_name"]] == 1
    assert abs(x2[I["ear_agree"]] - 0.6) < 1e-6 and x2[I["ent_seen_before"]] == 1     # Tycho, named 7 s before
    assert x3[I["ear_names_avail"]] == 1 and x3[I["ear_linked"]] == 0 and x3[I["ear_dec_name"]] == 0
    for x in xs:       # the live ear has no command_complete: never available, in either path
        assert x[I["cc_avail"]] == 0 and x[I["cc"]] == 0
        for k in ("ear_conf", "ear_alts", "ear_alt_hot", "ear_rescored", "ear_tier_step", "ear_tier_screen"):
            assert x[I[k]] == 0, k        # the dead round-7 slots stay 0, as every shipped model was trained


def test_replay_keeps_the_live_order_and_invents_nothing():
    ev, fx = RP.compact(LIVE[1])
    out = RP.messages({"hyp": "How big is Tycho pelicus?", "events": ev, "x": {"final": fx}}, dd=0.5)
    assert [m["t"] for m in out] == ["turn", "words", "arc", "words", "turn"]
    assert out[0]["text"] == "How big is"                       # the turn start carries its first words, as live
    assert out[2] == {"t": "arc", "device_directed": 0.5, "command_complete": None}
    assert out[3]["decoder_text"] == "How big is Copernicus?" and out[3]["agree"] == 0.6 and out[3]["final"]
    assert RP.messages({"hyp": "x", "events": ev, "x": {}}) is None       # a pre-round-12 decode: no extras, no replay


# ------------------------------------------------------------------------------------------------ per-class routing
def test_pick_routes_a_class_to_its_own_file_and_policy():
    thr = {"classes": ["quiet", "nav"], "routes": {"hot": "weights_r10", "echo": "weights_r10"}, "ignore": 0.9}
    out = {"act": [1.0], "_routed": {"weights_r10": {"act": [0.5]}}}
    pols = {"weights_r10": {"ignore": 0.95}}
    assert RT.pick(thr, "quiet", out, pols) == (out, thr)
    assert RT.pick(thr, "echo", out, pols) == ({"act": [0.5]}, {"ignore": 0.95})
    assert RT.pick(thr, "short", out, pols) is None                 # not listed: the rules decide (guarded semantics)
    assert RT.pick(thr, "hot", {"act": [1.0]}, pols) is None         # the routed file did not load: the rules decide
    assert RT.pick(thr, "hot", out, {}) is None
    assert RT.allowed(thr, "echo") and RT.allowed(thr, "nav") and not RT.allowed(thr, "video")
    assert RT.pick({"classes": ["hot", "echo"]}, "echo", out) == (out, {"classes": ["hot", "echo"]})   # r10's form


def _two_files(tmp_path, routes, classes):
    import json
    import shutil
    src = Path(RT.__file__).parent
    meta = json.loads((src / "weights.json").read_text())
    r10 = src / ("weights_r10.json" if (src / "weights_r10.json").exists() else "weights.json")
    m10 = json.loads(r10.read_text())
    shutil.copy(r10.with_suffix(".npz"), tmp_path / "weights_r10.npz")
    (tmp_path / "weights_r10.json").write_text(json.dumps(m10))
    shutil.copy(src / "weights.npz", tmp_path / "weights.npz")
    meta["policy"] = {**(meta.get("policy") or {}), "classes": classes, "routes": routes}
    (tmp_path / "weights.json").write_text(json.dumps(meta))
    return m10


def test_the_routed_file_steps_on_every_event_with_its_own_state(tmp_path, monkeypatch, quiet):
    m10 = _two_files(tmp_path, {"echo": "weights_r10"}, ["quiet"])
    monkeypatch.setattr(RT, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(RT, "_model", None)
    monkeypatch.setattr(RT, "_failed", None)
    monkeypatch.setattr(RT, "_routed", {})
    monkeypatch.setenv("DIRECTOR_MODEL", "guarded")
    assert RT.model() is not None and set(RT.routed_models()) == {"weights_r10"}
    assert RT.policies()["weights_r10"]["classes"] == m10["policy"].get("classes")
    clock = Clock()
    s = _session("route", clock)
    s.dm = RT.Shadow(s, run_model=True)
    ref = RT.Model(tmp_path, "weights_r10")
    st, prev, n = None, None, 0
    real_step = RT.Shadow.step

    def check(self, ev, read=None):
        nonlocal st, prev, n
        out = real_step(self, ev, read)
        x = FX.step_feats(self.prev, prev)
        o10, st = ref.step(st, x, *FX.step_tokens(self.prev))
        prev = self.prev
        for k in o10:      # the routed output IS the r10 file stepped on the same stream (its own state)
            assert np.array_equal(np.asarray(o10[k]), np.asarray(out["_routed"]["weights_r10"][k])), k
        n += 1
        return out
    monkeypatch.setattr(RT.Shadow, "step", check)
    asyncio.run(_drive(s, clock, LIVE))
    assert n > 5
    monkeypatch.setenv("DIRECTOR_MODEL", "shadow")       # the one-env rollback: no routed step, the rules decide
    assert RT.Shadow(s, run_model=True).decide_turn({"act": np.ones(len(FX.ACTS))}, "x y z", False) is None


def test_slots_trained_at_zero_stay_zero_for_every_shipped_file():
    """The dead round-7 ear slots (and, for r12, cc) were 0 in every training set. libarc ABI 2 will fill conf / alts
    at serve time: each shipped file lists them as `trained_zero` and the runtime forces them back to 0, so filling
    them cannot move either model's outputs."""
    m = RT.model()
    if m is None or "weights_r10" not in RT.routed_models():
        pytest.skip("no shipped weights")
    dead = {"ear_conf", "ear_alts", "ear_alt_hot", "ear_rescored", "ear_tier_step", "ear_tier_screen"}
    assert dead | {"cc_avail", "cc"} <= set(m.meta["trained_zero"])
    assert dead <= set(RT.routed_models()["weights_r10"].meta["trained_zero"])
    rng = np.random.default_rng(0)
    x0 = rng.normal(size=FX.F).astype(np.float32)
    for k in dead | {"cc_avail", "cc"}:
        x0[FX._IDX[k]] = 0.0
    x1 = x0.copy()
    for k in dead:
        x1[FX._IDX[k]] = 0.9
    toks = (np.zeros(FX.K, np.int64), np.zeros(FX.W, np.int64), np.zeros((FX.W, FX.WF), np.float32))
    for mm in (m, RT.routed_models()["weights_r10"]):
        o0, _ = mm.step(None, x0, *toks)
        o1, _ = mm.step(None, x1, *toks)
        for k in o0:
            assert np.array_equal(np.asarray(o0[k]), np.asarray(o1[k])), k
