"""The turn engine as a graph (app/graph/turn.py, docs/TURN_GRAPH.md): the session runs one graph per turn; the old
engine (TURN_ENGINE=legacy) gives the same decisions; the trace reaches the turn log without words; the perception
fan-out; barge-in cancellation (off by default)."""
import asyncio
import json
import re
import time

import pytest

from app import director, models_client, safety, session as sessions, turnlog
from app.config import settings
from app.gazetteer import Gazetteer
from app.graph import turn as tg
from app.mission import capcom, registry
from app.moments import MomentIndex

_W: list = []


def world():
    if not _W:
        _W.extend([Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")])
    return _W


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("TURN_ENGINE", "graph")    # these tests are about the graph (a suite run may set legacy)
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()


_N = [0]


def new_sess(mission=False, improve=False):
    clock = Clock()
    _N[0] += 1      # a fresh session id: the local brain rotates its templates per session
    s = sessions.Session(f"tg-{_N[0]}", world()[0], world()[1], clock=clock, registry=registry)
    s.dm = None
    hello = {"t": "hello", "mode": "explorer"}
    if mission:
        hello = {"t": "hello", "mode": "mission", "mission_id": registry.create("shackleton_rim", 37, level="commander").id}
    asyncio.run(s.handle(hello))
    if improve:
        asyncio.run(s.handle({"type": "prefs", "improve": True}))
    s.clock_obj = clock
    return s


def said(s):
    return [d for d in s.outbox if d["t"] not in ("floor",)]


def strip_ids(ds):
    out = []
    for d in ds:
        d = {k: v for k, v in d.items() if k not in ("id", "after", "ids")}
        if isinstance(d.get("r"), dict):
            d["r"] = {k: v for k, v in d["r"].items() if k != "readout"}
        out.append(d)
    return json.loads(re.sub(r"\bm-[0-9a-f]{8}\b", "m-#", json.dumps(out)))    # mission ids are random


TURNS = [(False, "where did apollo 11 land"), (False, "show me the giant bullseye"), (False, "what does albedo mean"),
         (False, "my name is sam"), (False, "tell me about the far side"), (True, "move 20% to shields"),
         (True, "all power to science"), (True, "how much power is left"), (True, "send the rover for ice"),
         (True, "houston are we okay")]


@pytest.mark.parametrize("mission,text", TURNS)
def test_graph_and_legacy_engines_decide_the_same(monkeypatch, mission, text):
    got = {}
    for eng in ("legacy", "graph"):
        monkeypatch.setenv("TURN_ENGINE", eng)
        director.RULES.clear()
        director.PENDING.clear()
        capcom._explained.clear()
        s = new_sess(mission)
        asyncio.run(s.handle({"t": "typed", "text": text}))
        if mission and any(d["t"] == "ask_confirm" for d in s.outbox):
            s.clock_obj.t += 2
            asyncio.run(s.handle({"t": "typed", "text": "yes"}))
        got[eng] = strip_ids(said(s))
    assert got["legacy"] and got["legacy"] == got["graph"]


def test_the_director_handlers_are_nodes_of_a_subgraph_and_the_trace_names_the_one_that_answered(monkeypatch):
    seen = []
    orig = tg.TURN.start

    def start(state, **kw):
        h = orig(state, **kw)
        seen.append(kw["trace"])
        return h
    monkeypatch.setattr(tg.TURN, "start", start)
    s = new_sess()
    asyncio.run(s.handle({"t": "typed", "text": "what does albedo mean"}))
    names = [t["n"] for t in seen[0]]
    assert names[:4] == ["intake", "perceive", "safety", "route"]
    assert "direct/privacy" in names and "direct/glossary" in names and "direct/steering" in names
    assert "direct/brain" not in names        # the first handler to answer wins
    h = next(t for t in seen[0] if t["n"] == "direct/glossary")
    assert h["go"] == "steering" and h["o"] == {"handler": "glossary"}
    assert [n for n, _ in director.HANDLERS][-1] == "brain" and len(director.HANDLERS) == 13


def test_the_turn_log_keeps_the_trace_without_words(tmp_path, monkeypatch):
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path))
    s = new_sess(improve=True)
    s.clock_obj.t += 3
    asyncio.run(s.handle({"t": "typed", "text": "my name is sam and i live at 12 elm street"}))
    s.clock_obj.t += 3
    asyncio.run(s.handle({"t": "typed", "text": "where did apollo 11 land"}))
    recs = [json.loads(x) for f in turnlog.Store(tmp_path).files() for x in f.read_text().splitlines()]
    turns = [r for r in recs if r.get("k") == "turn"]
    assert len(turns) == 2 and all(r["trace"] for r in turns)
    blob = json.dumps([r["trace"] for r in turns])
    for w in ("sam", "elm", "apollo", "land"):
        assert w not in blob
    assert turns[0]["guard"] and turns[0]["text"] == "<private>"
    t1 = {t["n"]: t for t in turns[1]["trace"]}
    assert t1["route"]["o"]["outcome"] and all(isinstance(t["ms"], float) for t in turns[1]["trace"])


def test_trace_view_keeps_only_names_numbers_and_enums():
    tv = turnlog.trace_view([
        {"n": "route", "ms": 0.1234, "o": {"outcome": "question", "reason": "Where Is Tycho?", "p": 0.5}},
        {"n": "Free Text Node", "ms": 1}, {"n": "decide", "go": "director", "w": ["override"]},
        {"n": "perceive", "par": {"safety_tags": 2.0, "readout_prefetch": 3.0}}, {"n": "x", "cancelled": True}])
    assert tv == [{"n": "route", "ms": 0.12, "o": {"outcome": "question", "p": 0.5}},
                  {"n": "decide", "go": "director"},
                  {"n": "perceive", "par": {"safety_tags": 2.0, "readout_prefetch": 3.0}},
                  {"n": "x", "cancelled": True}]
    assert turnlog.trace_view(None) is None and turnlog.trace_view([]) is None


def test_learned_extras_reach_the_read_after_the_directors_step():
    """Like test_learn's check on the legacy engine: the model's features never see this cadet's learned aliases."""
    import inspect
    order = ["direct", "readout", "ear_readout", "director_step"]
    assert [tg.TURN.edges[a] for a in order[:-1]] == order[1:]
    assert "self.dm.step(" not in inspect.getsource(tg.director_node)
    assert "read_extras()" in inspect.getsource(tg.director_node)
    assert "dm.step(" in inspect.getsource(tg.director_step)


def test_a_typed_turn_asks_the_safety_read_and_the_readout_at_once(monkeypatch):
    spans = {}

    async def slow_tag(text, domain="assistant", command_context=None):
        if text == "where did apollo 11 land":      # (the claim check asks Arc about the answer's own sentences)
            assert domain not in spans
            t0 = time.perf_counter()
            await asyncio.sleep(0.1)
            spans[domain] = (t0, time.perf_counter())
        return None

    async def slow_safety(text, command_context=False):
        t0 = time.perf_counter()
        await asyncio.sleep(0.1)
        spans["safety"] = (t0, time.perf_counter())
        return []
    monkeypatch.setattr(models_client, "tag", slow_tag)
    monkeypatch.setattr(safety, "tagger_read", slow_safety)
    s = new_sess()
    asyncio.run(s.handle({"t": "typed", "text": "where did apollo 11 land"}))
    assert set(spans) == {"assistant", "safety"}           # the read-out is asked once (prefetched, then used)
    a, b = spans["assistant"], spans["safety"]
    assert a[0] < b[1] and b[0] < a[1]                     # the two calls overlapped: at once, not one after the other
    assert any(d["t"] in ("say", "card") for d in s.outbox)


def test_a_prefetch_that_fails_is_asked_again_by_the_readout(monkeypatch):
    n = {"calls": 0}

    async def flaky(text, domain="assistant", command_context=None):
        if text != "where did apollo 11 land":
            return None
        n["calls"] += 1
        if n["calls"] == 1:
            raise RuntimeError("model server restarting")
        return None
    monkeypatch.setattr(models_client, "tag", flaky)
    s = new_sess()
    asyncio.run(s.handle({"t": "typed", "text": "where did apollo 11 land"}))
    assert n["calls"] == 2 and any(d["t"] in ("say", "card") for d in s.outbox)


def _slow_readout(monkeypatch, started: asyncio.Event | None = None):
    async def slow_tag(text, domain="assistant", command_context=None):
        await asyncio.sleep(0.2)
        return None
    monkeypatch.setattr(models_client, "tag", slow_tag)


def _barge_mid_turn(s):
    async def main():
        t = asyncio.ensure_future(s.handle({"t": "typed", "text": "where did apollo 11 land", "source": "ptt"}))
        await asyncio.sleep(0.05)        # the turn is waiting on its read-out
        assert s._run is not None and not s._run.run.committed
        await s.barge_in()
        await t
    asyncio.run(main())


def test_barge_in_does_not_cancel_the_turn_by_default(monkeypatch):
    _slow_readout(monkeypatch)
    s = new_sess()
    s.belief["kid"]["safety"] = []      # the ear's safety read: no tagger call
    _barge_mid_turn(s)
    assert any(d["t"] in ("say", "card") for d in s.outbox) and s._run is None


def test_barge_in_cancels_the_turn_before_it_commits_when_switched_on(monkeypatch, tmp_path):
    monkeypatch.setenv("TURN_GRAPH_BARGE_CANCEL", "1")
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path))
    _slow_readout(monkeypatch)
    s = new_sess(improve=True)
    s.belief["kid"]["safety"] = []
    s.pending["d-old"] = {"t": "say", "id": "d-old", "priority": 3, "text": "an older line"}
    _barge_mid_turn(s)
    assert not any(d["t"] in ("say", "card", "answer") for d in s.outbox)
    cancels = [d for d in s.outbox if d["t"] == "cancel"]
    assert cancels and "d-old" in cancels[0]["ids"]          # the dropped older line is still cancelled on the client
    assert s.belief["floor"] == "kid" and s._run is None and s._tl is None
    recs = [json.loads(x) for f in turnlog.Store(tmp_path).files() for x in f.read_text().splitlines()]
    tr = [r for r in recs if r.get("k") == "turn"][0]["trace"]
    assert tr[-1].get("cancelled") and tr[-1]["n"] == "readout"


def test_the_poll_is_a_graph_run_and_matches_legacy(monkeypatch):
    got = {}
    for eng in ("legacy", "graph"):
        monkeypatch.setenv("TURN_ENGINE", eng)
        s = new_sess(mission=True)
        reg_m = registry.get(s.belief["mission_id"])
        registry.advance(reg_m.id, 14)       # into the first storm's warning window: proactive alerts
        asyncio.run(s.poll())
        got[eng] = strip_ids(said(s))
    assert got["legacy"] == got["graph"]


def test_replay_harness_replays_a_turn_log_through_both_engines(tmp_path, monkeypatch, capsys):
    """tools/turn_replay.py: a family's turn log (here: written by a session in this test) replays decision for
    decision the same through the old engine and the graph."""
    from tools import turn_replay
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path))
    s = new_sess(mission=True, improve=True)
    for text in ("move 20% to shields", "how much power is left", "what is a solar storm", "my name is sam"):
        s.clock_obj.t += 3
        asyncio.run(s.handle({"t": "typed", "text": text}))
    log = turnlog.Store(tmp_path).files()[0]
    assert len(turn_replay._log_turns(str(log))) == 3          # the private turn is never replayed
    assert turn_replay.replay(str(log), golden=False) == 0
    assert "identical: 3" in capsys.readouterr().out
