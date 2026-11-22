"""The small graph runtime under the turn engine (app/graph/runtime.py, docs/TURN_GRAPH.md): one test per feature."""
import asyncio
from dataclasses import dataclass, field

import pytest

from app.graph.runtime import END, Graph, GraphError, StepLimit, goto


@dataclass
class S:
    n: int = 0
    path: list = field(default_factory=list)
    a: object = None
    b: object = None
    x: object = None


def run(c):
    return asyncio.run(c)


def test_typed_state_nodes_static_edges_and_the_trace():
    g = Graph("t")

    async def one(s, r):
        s.path.append("one")
        return {"n": 1}

    def two(s, r):                  # plain functions are nodes too
        s.path.append("two")

    g.node("one", one, view=lambda s: {"n": s.n})
    g.node("two", two)
    g.edge("one", "two")
    res = run(g.check().run(S()))
    assert res.status == "done" and res.state.path == ["one", "two"] and res.state.n == 1 and res.last == "two"
    t1, t2 = res.trace
    assert t1["n"] == "one" and t1["w"] == ["n"] and t1["o"] == {"n": 1} and t1["ms"] >= 0
    assert t2["n"] == "two" and "go" not in t2


def test_a_decision_node_returns_goto_with_args_and_updates():
    g = Graph("t")

    def decide(s, r):
        return goto("say", update={"x": "picked"}, word="hello", times=2)

    def say(s, r, word, times):
        s.path.append(word * times)

    g.node("decide", decide)
    g.node("say", say)
    g.node("never", lambda s, r: s.path.append("never"))
    g.edge("decide", "never")       # Goto wins over the static edge
    res = run(g.run(S()))
    assert res.state.path == ["hellohello"] and res.state.x == "picked"
    assert res.trace[0]["go"] == "say" and res.trace[1]["a"] == ["times", "word"]


def test_conditional_routing_from_the_state():
    g = Graph("t")
    g.node("start", lambda s, r: None)
    g.node("big", lambda s, r: s.path.append("big"))
    g.node("small", lambda s, r: s.path.append("small"))
    g.branch("start", lambda s: "big" if s.n > 5 else "small")
    assert run(g.run(S(n=9))).state.path == ["big"]
    res = run(g.run(S(n=1)))
    assert res.state.path == ["small"] and res.trace[0]["go"] == "small"


def test_a_node_can_end_the_run_and_unknown_targets_fail_loudly():
    g = Graph("t")
    g.node("a", lambda s, r: END)
    g.node("b", lambda s, r: s.path.append("b"))
    g.edge("a", "b")
    assert run(g.run(S())).state.path == []
    bad = Graph("bad")
    bad.node("a", lambda s, r: "nowhere")
    with pytest.raises(GraphError):
        run(bad.run(S()))
    bad2 = Graph("bad2")
    bad2.node("a", lambda s, r: None)
    bad2.edge("a", "ghost")
    with pytest.raises(GraphError):
        bad2.check()


def test_parallel_fan_out_runs_at_once_and_merges_updates_in_order():
    g = Graph("t")

    async def slow_a(s, r):
        await asyncio.sleep(0.05)
        return {"a": "A", "x": "from a"}

    async def slow_b(s, r):
        await asyncio.sleep(0.05)
        return {"b": "B", "x": "from b"}

    g.parallel("perceive", {"a": slow_a, "b": slow_b})
    g.node("after", lambda s, r: s.path.append((s.a, s.b)))
    g.edge("perceive", "after")
    res = run(g.run(S()))
    assert res.state.path == [("A", "B")] and res.state.x == "from b"     # declared order: b's update last
    tr = res.trace[0]
    assert set(tr["par"]) == {"a", "b"} and tr["ms"] < 95, tr            # concurrent: ~50 ms, not ~100


def test_parallel_fan_out_error_cancels_the_other_branch():
    g = Graph("t")
    seen = []

    async def boom(s, r):
        await asyncio.sleep(0.01)
        raise ValueError("ear down")

    async def long(s, r):
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            seen.append("cancelled")
            raise

    g.parallel("p", {"boom": boom, "long": long})
    with pytest.raises(ValueError, match="ear down"):
        run(g.run(S()))
    assert seen == ["cancelled"]


def test_streaming_channel_sends_partial_outputs_while_the_run_goes_on():
    g = Graph("t")
    got = []

    async def first(s, r):
        await r.emit("heard")
        assert got == ["heard"]          # out before the run continues
        return None

    async def second(s, r):
        await r.emit("answer")

    g.node("first", first)
    g.node("second", second)
    g.edge("first", "second")

    async def stream(x):
        got.append(x)
    res = run(g.run(S(), stream=stream))
    assert got == ["heard", "answer"] and res.outputs == ["heard", "answer"]


def test_interrupt_and_resume_for_a_confirmation():
    g = Graph("t")

    def plan(s, r):
        s.path.append("plan")

    def confirm(s, r):
        ok = r.interrupt({"ask": "All power to science?"})
        s.x = ok

    def apply(s, r):
        s.path.append("applied" if s.x == "yes" else "dropped")

    g.chain("plan", "confirm", "apply")
    g.node("plan", plan)
    g.node("confirm", confirm)
    g.node("apply", apply)
    res = run(g.run(S()))
    assert res.status == "interrupted" and res.checkpoint.node == "confirm"
    assert res.checkpoint.value == {"ask": "All power to science?"} and res.state.path == ["plan"]
    done = run(g.run(None, resume=res.checkpoint, value="yes"))
    assert done.status == "done" and done.state.path == ["plan", "applied"]
    no = run(g.run(S()))
    assert run(g.run(None, resume=no.checkpoint, value="no")).state.path == ["plan", "dropped"]
    other = Graph("other")
    other.node("confirm", confirm)
    with pytest.raises(GraphError):
        run(other.run(None, resume=no.checkpoint, value="yes"))


def test_cancel_before_a_commit_node_stops_the_run_and_cleans_up():
    g = Graph("t")
    started = asyncio.Event()

    async def perceive(s, r):
        started.set()
        await asyncio.sleep(5)
        s.path.append("perceived")

    def commit(s, r):
        s.path.append("committed")

    g.node("perceive", perceive)
    g.node("commit", commit, commit=True)
    g.edge("perceive", "commit")

    @g.on_cancel
    def cleanup(s, r):
        s.path.append("cleanup")

    async def main():
        h = g.start(S())
        await started.wait()
        assert h.cancel() is True
        return await h
    res = run(main())
    assert res.status == "cancelled" and res.state.path == ["cleanup"] and res.trace[-1]["cancelled"]


def test_cancel_after_a_commit_node_lets_the_run_finish():
    g = Graph("t")
    inside = asyncio.Event()

    async def apply(s, r):
        inside.set()
        await asyncio.sleep(0.02)
        s.path.append("applied")

    g.node("apply", apply, commit=True)
    g.node("emit", lambda s, r: s.path.append("emitted"))
    g.edge("apply", "emit")

    async def main():
        h = g.start(S())
        await inside.wait()
        assert h.cancel() is False and h.run.cancel_requested
        return await h
    res = run(main())
    assert res.status == "done" and res.state.path == ["applied", "emitted"]


def test_a_cancel_from_outside_the_handle_still_propagates():
    g = Graph("t")
    g.node("wait", lambda s, r: asyncio.sleep(5))
    cleaned = []
    g.on_cancel(lambda s, r: cleaned.append(True))

    async def main():
        t = asyncio.ensure_future(g.run(S()))
        await asyncio.sleep(0.01)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    run(main())
    assert cleaned == [True]


def test_step_limit_stops_a_loop_that_never_settles():
    g = Graph("t", max_steps=10)
    g.node("spin", lambda s, r: "spin")
    with pytest.raises(StepLimit):
        run(g.run(S()))


def test_subgraph_runs_inline_with_a_prefixed_trace_and_a_depth_limit():
    inner = Graph("inner")
    inner.node("x", lambda s, r: s.path.append("inner-x"))
    outer = Graph("outer")

    async def call(s, r):
        res = await r.subgraph(inner, s)
        assert res.status == "done"

    outer.node("call", call)
    res = run(outer.run(S()))
    assert res.state.path == ["inner-x"] and [t["n"] for t in res.trace] == ["call", "inner/x"]
    rec = Graph("rec")

    async def again(s, r):
        await r.subgraph(rec, s)
    rec.node("again", again)
    with pytest.raises(GraphError):
        run(rec.run(S()))


def test_errors_in_a_node_propagate_unchanged():
    g = Graph("t")

    def bad(s, r):
        raise KeyError("x")
    g.node("bad", bad)
    with pytest.raises(KeyError):
        run(g.run(S()))
