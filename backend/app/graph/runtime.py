"""A small graph runtime for the turn engine (docs/TURN_GRAPH.md). LangGraph's ideas, none of its code or dependencies.

    g = Graph("turn")
    g.node("safety", safety)                      # async (or plain) fn(state, run, **args)
    g.edge("safety", "route")                     # static edge
    g.branch("route", lambda s: s.rt["outcome"])  # conditional edge: a function of the state -> the next node name
    g.parallel("perceive", {"tags": read_tags, "readout": prefetch})   # fan-out: asyncio, updates merged after
    res = await g.run(state, stream=emit)

A node returns:
    None           follow its edge / branch (no edge and no branch: the run ends)
    "name" | END   go there
    Goto(name, args, update)   a decision node: where to go, with keyword args for that node and state updates
    {"field": v}   state updates, then follow its edge / branch

The run (`Run`, the node's second argument) gives a node:
    run.emit(x)          the streaming channel: partial outputs go out while the run continues (awaits `stream`)
    run.interrupt(v)     pause the run here (a confirmation): the result carries a Checkpoint; `resume` re-enters
                         the same node and interrupt() then returns the resume value instead of pausing
    run.subgraph(g, s)   run another graph inline (its nodes are traced as "parent/child"), bounded by MAX_DEPTH; an
                         interrupt inside it pauses the parent too (the parent's Checkpoint.sub), and resuming the
                         parent re-enters the paused child node

Cancellation: `start()` runs the graph in its own asyncio task; `RunHandle.cancel()` cancels it unless a commit node
(commit=True: one that changes the world, a sim command, a sent decision the client must see) has started, so the
state is never left half-applied. The graph's `on_cancel(state, run)` cleanup runs before the run reports
"cancelled" (also when the cancel comes before the run's task started). A cancellation from outside the handle (the
server shutting down) is cleaned up and re-raised.

Every node is traced: {"n": name, "ms": wall time, "go": a decided next node, "w": state fields rebound, "a": arg
names, "o": the node's own small view (numbers / enums: the turn log keeps it, turnlog.trace_view)}.
A run longer than `max_steps` nodes raises StepLimit (a graph with a loop that never settles).
"""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

END = "__end__"
MAX_STEPS = 64
MAX_DEPTH = 4
_NOTHING = object()


class GraphError(RuntimeError):
    pass


class StepLimit(GraphError):
    """The run went over max_steps nodes."""


class Interrupt(Exception):
    """Raised by run.interrupt(): the run pauses at the current node (caught by the runtime, never by a node)."""

    def __init__(self, value: Any = None, sub: "Checkpoint | None" = None):
        super().__init__("interrupt")
        self.value = value
        self.sub = sub          # a subgraph paused: its own checkpoint (resumed at its node when the parent resumes)


@dataclass
class Goto:
    node: str
    args: dict = field(default_factory=dict)
    update: dict = field(default_factory=dict)


def goto(node: str, update: dict | None = None, **args) -> Goto:
    return Goto(node, args, update or {})


@dataclass
class Checkpoint:
    graph: str
    node: str
    args: dict
    state: Any
    value: Any
    steps: int
    sub: "Checkpoint | None" = None   # the node paused inside a subgraph: where that subgraph resumes


@dataclass
class Result:
    status: str                      # done | interrupted | cancelled
    state: Any
    trace: list[dict]
    outputs: list[Any]
    checkpoint: Checkpoint | None = None
    last: str | None = None          # the last node that ran


@dataclass
class Node:
    name: str
    fn: Callable | None
    commit: bool = False
    view: Callable | None = None
    branches: dict[str, Callable] | None = None    # a parallel fan-out node


class Run:
    """One run of a graph: the streaming channel, interrupt / resume, the trace, the commit flag."""

    def __init__(self, graph: "Graph", stream: Callable[[Any], Awaitable | None] | None = None,
                 trace: list | None = None, prefix: str = "", depth: int = 0, ctx: Any = None):
        self.graph, self.stream, self.ctx = graph, stream, ctx
        self.trace: list[dict] = trace if trace is not None else []
        self.outputs: list[Any] = []
        self.prefix, self.depth = prefix, depth
        self.root: Run = self           # a subgraph's run shares its root's commit / cancel flags
        self._committed = False
        self.cancel_requested = False
        self.by_handle = False
        self.node: str | None = None
        self._resume: Any = _NOTHING
        self._sub: Checkpoint | None = None   # resuming: the paused subgraph's checkpoint (run.subgraph takes it)
        self._entered = False                 # the run's task has reached its loop (RunHandle.cancel before that)
        self._cancel_pending = False

    @property
    def committed(self) -> bool:
        return self.root._committed

    @committed.setter
    def committed(self, v: bool):
        self.root._committed = bool(v)

    async def emit(self, x: Any):
        """The streaming channel: out now (the caller's `stream`), and kept on the result."""
        self.outputs.append(x)
        if self.stream is not None:
            r = self.stream(x)
            if inspect.isawaitable(r):
                await r

    def interrupt(self, value: Any = None) -> Any:
        if self._resume is not _NOTHING:
            v, self._resume = self._resume, _NOTHING
            return v
        raise Interrupt(value)

    async def subgraph(self, g: "Graph", state: Any, start: str | None = None, **args) -> Result:
        if self.depth + 1 > MAX_DEPTH:
            raise GraphError(f"subgraph depth over {MAX_DEPTH}: {g.name}")
        sub = Run(g, self.stream, self.trace, f"{self.prefix}{g.name}/", self.depth + 1, self.ctx)
        sub.root = self.root
        steps = 0
        cp, self._sub = self._sub, None
        if cp is not None and cp.graph == g.name:   # the parent resumed: re-enter the paused node (with the caller's
            start, args, steps = cp.node, dict(cp.args), cp.steps     # state), its interrupt() returns the value
            sub._sub = cp.sub
            sub._resume, self._resume = self._resume, _NOTHING
        res = await g._loop(state, sub, start or g.entry_node, args, steps)
        self.outputs += sub.outputs
        if res.status == "interrupted":   # pause the parent too (its checkpoint carries this one), never lose it
            raise Interrupt(res.checkpoint.value if res.checkpoint else None, res.checkpoint)
        return res


class RunHandle:
    """A graph run in its own task (Graph.start): await it for the Result; cancel() honours commit nodes."""

    def __init__(self, task: asyncio.Task, run: Run):
        self.task, self.run = task, run

    def cancel(self) -> bool:
        """Cancel the run unless it has passed a commit node (then it finishes: the world already changed)."""
        if self.task.done():
            return False
        if not self.run._entered:      # the task has not started yet: a task.cancel() now would escape before the
            self.run.by_handle = True  # loop (no on_cancel, no Result); the loop sees this flag on its first step
            self.run._cancel_pending = True
            return True
        if self.run.committed:
            self.run.cancel_requested = True
            return False
        self.run.by_handle = True
        self.task.cancel()
        return True

    def done(self) -> bool:
        return self.task.done()

    def __await__(self):
        return self.task.__await__()


async def _call(fn: Callable, *a, **k):
    r = fn(*a, **k)
    if inspect.isawaitable(r):
        r = await r
    return r


class Graph:
    def __init__(self, name: str, max_steps: int = MAX_STEPS):
        self.name, self.max_steps = name, max_steps
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, str] = {}
        self.branches: dict[str, Callable[[Any], str]] = {}
        self.entry_node: str | None = None
        self.cancel_hook: Callable | None = None

    # ---- building ----------------------------------------------------------------------------------------------------
    def node(self, name: str, fn: Callable | None = None, *, commit: bool = False, view: Callable | None = None):
        """Add a node (or use as a decorator: @g.node("name"))."""
        def add(f: Callable):
            if name in self.nodes or name == END:
                raise GraphError(f"node {name!r} twice")
            self.nodes[name] = Node(name, f, commit, view)
            if self.entry_node is None:
                self.entry_node = name
            return f
        return add(fn) if fn is not None else add

    def parallel(self, name: str, branches: dict[str, Callable], *, view: Callable | None = None):
        """A fan-out node: every branch fn(state, run) runs at once (asyncio); each returns a dict of state updates (or
        None), applied in the order given once all are done. The first branch to raise cancels the others and the
        error is the run's."""
        if name in self.nodes:
            raise GraphError(f"node {name!r} twice")
        self.nodes[name] = Node(name, None, False, view, dict(branches))
        if self.entry_node is None:
            self.entry_node = name

    def edge(self, src: str, dst: str):
        self.edges[src] = dst

    def chain(self, *names: str):
        for a, b in zip(names, names[1:]):
            self.edge(a, b)

    def branch(self, src: str, router: Callable[[Any], str]):
        self.branches[src] = router

    def entry(self, name: str):
        self.entry_node = name

    def on_cancel(self, fn: Callable):
        """Cleanup when a run is cancelled: fn(state, run) (sync or async), so the state stays consistent."""
        self.cancel_hook = fn
        return fn

    def check(self) -> "Graph":
        """Every edge points at a node (a branch's targets are checked when it routes)."""
        for a, b in self.edges.items():
            if a not in self.nodes or (b != END and b not in self.nodes):
                raise GraphError(f"edge {a} -> {b}: unknown node")
        for a in self.branches:
            if a not in self.nodes:
                raise GraphError(f"branch from unknown node {a}")
        if self.entry_node not in self.nodes:
            raise GraphError("no entry node")
        return self

    # ---- running -----------------------------------------------------------------------------------------------------
    async def run(self, state: Any, *, stream: Callable | None = None, resume: Checkpoint | None = None,
                  value: Any = None, trace: list | None = None, ctx: Any = None, _run: Run | None = None) -> Result:
        run = _run or Run(self, stream, trace, ctx=ctx)
        start, args, steps = self.entry_node, {}, 0
        if resume is not None:
            if resume.graph != self.name:
                raise GraphError(f"checkpoint of {resume.graph}, not {self.name}")
            state, start, args, steps = resume.state, resume.node, dict(resume.args), resume.steps
            run._resume = value
            run._sub = resume.sub
        return await self._loop(state, run, start, args, steps)

    def start(self, state: Any, **kw) -> RunHandle:
        """Run in a new task (cancellable through the handle)."""
        run = Run(self, kw.pop("stream", None), kw.pop("trace", None), ctx=kw.pop("ctx", None))
        task = asyncio.ensure_future(self.run(state, _run=run, **kw))
        return RunHandle(task, run)

    async def _loop(self, state: Any, run: Run, cur: str | None, args: dict, steps: int) -> Result:
        last = None
        try:
            run._entered = True
            while cur is not None and cur != END:
                if run.root._cancel_pending and not run.committed:
                    raise asyncio.CancelledError()
                steps += 1
                if steps > self.max_steps:
                    raise StepLimit(f"{self.name}: over {self.max_steps} steps (at {cur})")
                node = self.nodes.get(cur)
                if node is None:
                    raise GraphError(f"{self.name}: no node {cur!r}")
                run.node = cur
                if node.commit:
                    run.committed = True     # set before the node's first await: a cancel now waits for the end
                nxt, args = await self._step(node, state, run, args)
                last = cur
                cur = nxt
        except Interrupt as i:
            cp = Checkpoint(self.name, run.node or "", args, state, i.value, steps - 1, i.sub)
            run.trace.append({"n": run.prefix + (run.node or ""), "interrupt": True})
            return Result("interrupted", state, run.trace, run.outputs, cp, run.node)
        except asyncio.CancelledError:
            run.trace.append({"n": run.prefix + (run.node or ""), "cancelled": True})
            if self.cancel_hook is not None and run.depth == 0:
                await _call(self.cancel_hook, state, run)
            if not run.root.by_handle or run.depth:
                raise
            t = asyncio.current_task()
            if t is not None and hasattr(t, "uncancel"):
                t.uncancel()
            return Result("cancelled", state, run.trace, run.outputs, None, run.node)
        return Result("done", state, run.trace, run.outputs, None, last)

    async def _step(self, node: Node, state: Any, run: Run, args: dict) -> tuple[str | None, dict]:
        before = _fields(state)
        t0 = time.perf_counter()
        rec: dict = {"n": run.prefix + node.name}
        if args:
            rec["a"] = sorted(args)
        run.trace.append(rec)
        try:
            if node.branches is not None:
                out = await self._fan_out(node, state, run, rec)
            else:
                out = await _call(node.fn, state, run, **args)
        finally:
            rec["ms"] = round((time.perf_counter() - t0) * 1000, 3)
        decided = None
        nargs: dict = {}
        if isinstance(out, Goto):
            _apply(state, out.update)
            decided, nargs = out.node, dict(out.args)
        elif isinstance(out, str):
            decided = out
        elif isinstance(out, dict):
            _apply(state, out)
        elif out is not None:
            raise GraphError(f"node {node.name} returned {type(out).__name__}")
        if decided is not None:
            nxt = decided
            rec["go"] = decided
        elif node.name in self.branches:
            nxt = self.branches[node.name](state)
            rec["go"] = nxt
        else:
            nxt = self.edges.get(node.name)
        w = _rebound(before, state)
        if w:
            rec["w"] = w
        if node.view is not None:
            try:
                v = node.view(state)
            except Exception:   # noqa: BLE001  (a view never breaks a turn)
                v = None
            if v:
                rec["o"] = v
        if nxt is not None and nxt != END and nxt not in self.nodes:
            raise GraphError(f"{self.name}: {node.name} -> unknown node {nxt!r}")
        return nxt, nargs

    async def _fan_out(self, node: Node, state: Any, run: Run, rec: dict) -> None:
        names = list(node.branches)
        ms: dict[str, float] = {}

        async def one(name: str):
            t0 = time.perf_counter()
            try:
                return await _call(node.branches[name], state, run)
            finally:
                ms[name] = round((time.perf_counter() - t0) * 1000, 3)

        tasks = [asyncio.ensure_future(one(n)) for n in names]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        failed = next((t for t in tasks if t.done() and not t.cancelled() and t.exception() is not None), None)
        if failed is not None:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            rec["par"] = ms
            raise failed.exception()
        rec["par"] = ms
        for t in tasks:
            upd = t.result()
            if isinstance(upd, dict):
                _apply(state, upd)
        return None


def _fields(state: Any) -> dict[str, int] | None:
    d = getattr(state, "__dict__", None)
    if d is None and isinstance(state, dict):
        d = state
    return {k: id(v) for k, v in d.items()} if d is not None else None


def _rebound(before: dict | None, state: Any) -> list[str]:
    if before is None:
        return []
    now = _fields(state) or {}
    return sorted(k for k, v in now.items() if before.get(k) != v)


def _apply(state: Any, upd: dict):
    for k, v in (upd or {}).items():
        if isinstance(state, dict):
            state[k] = v
        else:
            if not hasattr(state, k):
                raise GraphError(f"state has no field {k!r}")
            setattr(state, k, v)
