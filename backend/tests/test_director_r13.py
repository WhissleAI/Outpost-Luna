"""Round 13: train / serve parity of the libarc ABI 2 read-outs (director_model/RESULTS.md, Round 13).

The live ear (model_server arc_ear.EarStream, ABI 2, live mode) puts its ABI 2 read-outs on the final words: utterance
and per-word confidence, the n-best, `almost` sound-alikes, typed quantities, clean_text, disfluencies, dropped tail
words and, live, playback_leak / playback / barge / eot (plus the pace numbers). The decode cache stores
replay.compact(the live messages) and the generator posts replay.messages(cached): the same turns through both paths
must give identical feature vectors at every step, with the e13_* slots really filled at the turn ends.
"""
import asyncio

import numpy as np

from app.director_model import features as FX, replay as RP, runtime as RT

from test_director_r12 import TYCHO, Capture, Clock, _arc, _drive, _final, _session, quiet  # noqa: F401


def _abi2(**k):
    base = {"uconf": 0.91, "min_wconf": 0.62, "wconf": [0.98, 0.95, 0.62, 0.97], "nbest": [], "walts": [],
            "clean_text": None, "disfl": [], "quantities": [], "n_dropped": 0, "almost": [],
            "speech_s": 1.4, "max_pause_s": 0.12, "end_silence_s": 0.5, "playback_leak": None, "playback": None,
            "barge": False, "barge_p": None, "eot": 0.04}
    base.update(k)
    if base["clean_text"] is None:
        base.pop("clean_text")
    return base


def _part(text, n=1, eot=0.02):
    return {"t": "words", "text": text, "final": False, "n_stable": n, "eot": eot}


# Four kid turns as the ABI 2 live ear sends them (shapes as in round-13 decodes): a sure link with high confidence; a
# sound-alike ("tie go" -> Tycho, almost) with a low word and a dropped tail word; a number turn with a typed quantity
# and a disfluency; and a turn heard over our own playback (leak 0.9, Arc's own playback flag, a barge-in read).
LIVE13 = [
    [{"t": "turn", "state": "start", "text": "Tell me"}, _part("Tell me"), _part("Tell me about", 2), _arc(0.83),
     {**_final("Tell me about Tycho.", "Tell me about tycho.", [TYCHO], "Tell me about Tycho.", 1.0),
      **_abi2(uconf=0.95, min_wconf=0.9, eot=0.31)},
     {"t": "turn", "state": "end", "text": "Tell me about Tycho."}],
    [{"t": "turn", "state": "start", "text": "Fly to"}, _part("Fly to"), _arc(0.77),
     {**_final("Fly to tie go.", "Fly to tie go.", [], "Fly to Tycho.", 0.5),
      **_abi2(uconf=0.58, min_wconf=0.21, n_dropped=1,
              almost=[{"heard": "tie go", "candidate": "Tycho", "p": 0.83, "kb_index": 3, "t0": 0.6, "t1": 1.1}])},
     {"t": "turn", "state": "end", "text": "Fly to tie go."}],
    [{"t": "turn", "state": "start", "text": "Shields to"}, _part("Shields to"), _part("Shields to um", 2), _arc(0.9),
     {**_final("Shields to um forty percent.", "Shields to um forty percent.", [], "Shields to 40 percent.", 0.8),
      **_abi2(clean_text="Shields to 40 percent.", disfl=[{"i": 2, "w": "um", "kind": "filler"}],
              quantities=[{"type": "percent", "value": 40, "unit": "%", "relative": 0}])},
     {"t": "turn", "state": "end", "text": "Shields to um forty percent."}],
    [{"t": "turn", "state": "start", "text": "the crater"}, _part("the crater"), _arc(0.4),
     {**_final("the crater rim is steep", "the crater rim is steep", [], "the crater rim is steep", 1.0),
      **_abi2(uconf=0.7, playback_leak=0.9, playback=True, barge=True, barge_p=0.71)},
     {"t": "turn", "state": "end", "text": "the crater rim is steep"}],
]


def _replayed(turns):
    cached = []
    for msgs in turns:
        ev, fx = RP.compact(msgs)
        hyp = " ".join(e["text"] for e in ev if e["t"] == "words" and e["final"])
        cached.append({"hyp": hyp, "events": ev, "x": {"final": fx}})
    return [RP.messages(d) for d in cached]


def test_abi2_live_and_replayed_turns_give_identical_features(quiet, monkeypatch):
    cap = Capture()
    monkeypatch.setattr(RT, "model", lambda: cap)
    clock_a = Clock()
    a = _session("par13-live", clock_a)
    a.dm = RT.Shadow(a, sink=[], run_model=True)
    asyncio.run(_drive(a, clock_a, LIVE13))
    replayed = _replayed(LIVE13)
    assert all(r is not None for r in replayed)
    clock_b = Clock()
    b = _session("par13-train", clock_b)
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
    # the Session kept the same ear read-out in both paths (the echo rule, the learner and the Director read it)
    assert a.belief["kid"]["ear"] == b.belief["kid"]["ear"]
    ends = [i for i, st in enumerate(sink) if st["rec"]["kind"] == "turn_end"]
    assert len(ends) == 4
    I = FX._IDX
    x1, x2, x3, x4 = (xs[i] for i in ends)
    for x in (x1, x2, x3, x4):
        assert x[I["e13_avail"]] == 1
        assert x[I["cc_avail"]] == 0
        for k in ("ear_conf", "ear_alts", "ear_alt_hot", "ear_rescored", "ear_tier_step", "ear_tier_screen"):
            assert x[I[k]] == 0, k       # the dead round-7 slots stay 0: ABI 2 travels under its own keys
    assert abs(x1[I["e13_uconf"]] - 0.95) < 1e-6 and abs(x1[I["e13_eot"]] - 0.31) < 1e-6
    assert x2[I["e13_almost"]] == 1 and abs(x2[I["e13_almost_p"]] - 0.83) < 1e-6 and x2[I["e13_dropped"]] == 1
    assert abs(x2[I["e13_min_wconf"]] - 0.21) < 1e-6
    assert x3[I["e13_qty"]] == 1 and x3[I["e13_disfl"]] > 0
    assert abs(x4[I["e13_leak"]] - 0.9) < 1e-6 and x4[I["e13_playback"]] == 1 and x4[I["e13_barge"]] == 1
    # no turn end without the read-out: steps between turns carry no e13 values
    for i, x in enumerate(xs):
        if i not in ends:
            assert x[I["e13_avail"]] == 0, i


def test_abi2_replay_is_verbatim_for_one_final_and_merged_for_several():
    ev, fx = RP.compact(LIVE13[1])
    out = RP.messages({"hyp": "Fly to tie go.", "events": ev, "x": {"final": fx}}, dd=0.6)
    fin = [m for m in out if m["t"] == "words" and m.get("final")][0]
    live = [m for m in LIVE13[1] if m["t"] == "words" and m.get("final")][0]
    for k in RP.ABI2_KEYS:
        assert fin.get(k) == live.get(k), k
    two = [LIVE13[0][-2], LIVE13[3][-2]]           # one clip, two finals: replayed as one turn
    ev2 = [{"t": "turn", "state": "start", "text": "a"}] + [dict(m) for m in two] + \
        [{"t": "turn", "state": "end", "text": "b"}]
    _, fx2 = RP.compact(ev2)
    assert fx2["uconf"] == 0.7 and fx2["playback_leak"] == 0.9 and fx2["playback"] is True and fx2["barge"] is True
    assert fx2["eot"] == 0.04 and len(fx2["wconf"]) == 8 and fx2["speech_s"] == 2.8


def test_a_pre_abi2_decode_replays_with_no_e13_read_out():
    ev, fx = RP.compact(LIVE13[0])
    fx = {k: v for k, v in fx.items() if k not in RP.ABI2_KEYS}
    out = RP.messages({"hyp": "Tell me about Tycho.", "events": ev, "x": {"final": fx}})
    fin = [m for m in out if m["t"] == "words" and m.get("final")][0]
    assert not any(k in fin for k in RP.ABI2_KEYS)
    assert FX.abi2_view({k: fin.get(k) for k in ("names", "spoken")}) == {}
