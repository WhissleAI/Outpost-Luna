"""Turn replay harness (docs/TURN_GRAPH.md "Parity"): the old turn engine vs the graph engine, decision for decision.

Three sources of turns, one diff:

  1. every turn the backend test suite exercises. Run the suite with this file as a pytest plugin; it records, per test,
     every decision a Session emits, every director.direct() answer (/api/ask) and every turn-log line, normalised
     (decision ids renumbered per test, mission ids and per-session turn-log ids masked):

         cd backend
         TURN_ENGINE=legacy uv run pytest -q -p tools.turn_replay --turn-record /tmp/legacy.jsonl.gz
         TURN_ENGINE=graph  uv run pytest -q -p tools.turn_replay --turn-record /tmp/graph.jsonl.gz
         uv run python tools/turn_replay.py diff /tmp/legacy.jsonl.gz /tmp/graph.jsonl.gz [--noise /tmp/legacy2.jsonl.gz]

     `--noise` is a second recording of the SAME engine: tests whose record differs between two runs of one engine
     (a random seed, wall-clock time) are reported as noisy and left out of the parity count.

  2. golden turns: director_model/data/gold*.json (hand-labelled turns, each in its mode), the held-out eval sets
     (backend/tests/eval: kid questions, mission orders) and the golden ear set's reference words
     (desktop/tests/golden/set.json, in both modes), each said into a fresh cabin / explorer session.
  3. logged turns: a turn log handed over by a family (turns.jsonl, docs/DIRECTOR_LOOP.md): the redacted words in the
     logged screen frame.

         uv run python tools/turn_replay.py replay [--log turns.jsonl] [--golden]

     replays 2 and 3 through two fresh sessions per turn, one per engine, with the same clock and a fresh sim, and diffs
     the decisions.

  4. latency: `uv run python tools/turn_replay.py bench [--rounds 5] [--model-ms 20]` times each golden turn through both
     engines (interleaved, offline; --model-ms simulates the local model server's Arc Tagger calls) and prints p50 / p90.

Exit 0 when every compared record is identical; 1 otherwise (the first differences are printed).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import gzip
import json
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
_DID = re.compile(r"^d-\d+$")
_MID = re.compile(r"\bm-[0-9a-f]{8}\b")
# turn-log fields that differ run to run by design (time, the per-session random id), not by decision
_TL_VOLATILE = ("t", "day", "s", "id", "ref", "by", "trace", "wav")


def normalise(obj, ids: dict):
    """Decision ids -> d#1, d#2 ... in order of first appearance (the global counter depends on test order); mission
    ids masked (random per mission)."""
    if isinstance(obj, dict):   # "ms": a wall-clock latency (Arc's read-out), never a decision
        return {k: normalise(v, ids) for k, v in obj.items() if k != "ms"}
    if isinstance(obj, (list, tuple)):
        return [normalise(v, ids) for v in obj]
    if isinstance(obj, str):
        if _DID.match(obj):
            return ids.setdefault(obj, f"d#{len(ids) + 1}")
        return _MID.sub("m-#", obj)
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


# ------------------------------------------------------------------------------------------------ pytest plugin (1)
_REC: dict = {"out": None, "test": None, "seq": [], "ids": {}}


def pytest_addoption(parser):
    parser.addoption("--turn-record", default=None, help="write every test's turn decisions here (.jsonl or .jsonl.gz)")


def _add(kind: str, payload):
    if _REC["test"] is None:
        return
    try:
        _REC["seq"].append([kind, normalise(copy.deepcopy(payload), _REC["ids"])])
    except Exception:   # noqa: BLE001  (a payload that cannot be copied: record its type only)
        _REC["seq"].append([kind, type(payload).__name__])


def pytest_configure(config):
    path = config.getoption("--turn-record", default=None)
    if not path:
        return
    _REC["out"] = gzip.open(path, "wt", encoding="utf-8") if path.endswith(".gz") else open(path, "w", encoding="utf-8")
    from app import director, session, turnlog

    emit0 = session.Session.emit

    async def emit(self, ds):
        _add("emit", list(ds))
        return await emit0(self, ds)

    session.Session.emit = emit
    direct0 = director.direct

    async def direct(text, read, gaz, index, context=None):
        r = await direct0(text, read, gaz, index, context)
        _add("direct", {"text": text, "r": {k: v for k, v in r.items() if k != "readout"}})
        return r

    director.direct = direct
    append0 = turnlog.Store.append

    def append(self, obj):
        _add("turnlog", {k: v for k, v in obj.items() if k not in _TL_VOLATILE})
        return append0(self, obj)

    turnlog.Store.append = append


import pytest  # noqa: E402


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if _REC["out"] is not None:          # before the test's fixtures (a fixture's hello / first turn counts too)
        _REC.update(test=item.nodeid, seq=[], ids={})


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item):
    if _REC["out"] is not None and _REC["test"] is not None:
        if _REC["seq"]:
            _REC["out"].write(json.dumps({"test": _REC["test"], "seq": _REC["seq"]}, default=str) + "\n")
        _REC["test"] = None


def pytest_unconfigure(config):
    if _REC["out"] is not None:
        _REC["out"].close()
        _REC["out"] = None


# ------------------------------------------------------------------------------------------------------------ diff
def _load(path: str) -> dict[str, list]:
    op = gzip.open if path.endswith(".gz") else open
    out: dict[str, list] = {}
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out[r["test"]] = r["seq"]
    return out


def _path(x, y, at: str = "") -> str:
    """Where two records first differ: a path and both values."""
    if isinstance(x, dict) and isinstance(y, dict):
        for k in list(x) + [k for k in y if k not in x]:
            if x.get(k, "<missing>") != y.get(k, "<missing>"):
                return _path(x.get(k, "<missing>"), y.get(k, "<missing>"), f"{at}.{k}")
    if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (u, v) in enumerate(zip(x, y)):
            if u != v:
                return _path(u, v, f"{at}[{i}]")
    return f"{at or '.'}: old {json.dumps(x)[:300]} | new {json.dumps(y)[:300]}"


def _first_diff(a: list, b: list) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"record {i} ({x[0]}) {_path(x[1], y[1])}"
    return f"length {len(a)} vs {len(b)}"


def _count(seq: list) -> dict:
    c = {"emit": 0, "decisions": 0, "direct": 0, "turnlog": 0}
    for k, p in seq:
        c[k] = c.get(k, 0) + 1
        if k == "emit" and isinstance(p, list):
            c["decisions"] += len(p)
    return c


def diff(a_path: str, b_path: str, noise: str | None = None, show: int = 10) -> int:
    a, b = _load(a_path), _load(b_path)
    noisy = set()
    if noise:
        n = _load(noise)
        noisy = {t for t in a if t in n and a[t] != n[t]} | (set(a) ^ set(n))
    only = sorted(set(b) - set(a))          # tests the old tree does not have (new tests): reported, not compared
    tests = sorted((set(a) | set(b)) - noisy - set(only))
    bad = [t for t in tests if a.get(t) != b.get(t)]
    if only:
        print(f"tests only in {Path(b_path).name}: {len(only)} (new tests, not compared)")
    tot = {"emit": 0, "decisions": 0, "direct": 0, "turnlog": 0}
    for t in tests:
        if t in a and a.get(t) == b.get(t):
            for k, v in _count(a[t]).items():
                tot[k] = tot.get(k, 0) + v
    print(f"tests with turns: {len(tests)} compared ({len(noisy)} noisy, left out); identical: {len(tests) - len(bad)}; "
          f"different: {len(bad)}")
    print(f"identical records: {tot['decisions']} decisions in {tot['emit']} emits, {tot['direct']} director answers, "
          f"{tot['turnlog']} turn-log lines")
    for t in bad[:show]:
        print(f"  DIFF {t}\n    {_first_diff(a.get(t) or [], b.get(t) or [])}")
    return 1 if bad else 0


# ------------------------------------------------------------------------------------------------ replay (2) and (3)
def _golden_turns() -> list[dict]:
    turns: list[dict] = []
    for f in ("gold.json", "gold_more.json"):
        p = ROOT / "director_model" / "data" / f
        if p.exists():
            for it in json.loads(p.read_text(encoding="utf-8")).get("items") or []:
                turns.append({"text": it["text"], "mode": it.get("mode") or "mission", "src": f})
    p = BACKEND / "tests" / "eval" / "kid_questions.json"     # the brain's held-out kid questions (explorer)
    if p.exists():
        turns += [{"text": q["q"], "mode": "explorer", "src": "kid_questions"}
                  for q in json.loads(p.read_text(encoding="utf-8")).get("questions") or []]
    p = BACKEND / "tests" / "eval" / "commands_heldout.json"  # held-out mission orders
    if p.exists():
        turns += [{"text": c["text"], "mode": "mission", "src": "commands_heldout"}
                  for c in json.loads(p.read_text(encoding="utf-8")).get("commands") or []]
    p = ROOT / "desktop" / "tests" / "golden" / "set.json"
    if p.exists():
        for c in json.loads(p.read_text(encoding="utf-8")).get("clips") or []:
            for mode in ("mission", "explorer"):
                turns.append({"text": c["text"], "mode": mode, "src": "golden_ear"})
    return turns


def _log_turns(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("k") != "turn" or not r.get("text") or r.get("guard") or r["text"] == "<private>":
                continue
            fr = r.get("frame") or {}
            out.append({"text": r["text"].replace("<callsign>", "comet"), "mode": "mission" if r.get("mission") else
                        (r.get("mode") or "explorer"), "src": "log", "screen": fr.get("screen"),
                        "step_type": fr.get("step_type"), "offer": fr.get("offer"),
                        "source": r.get("src") or "typed"})
    return out


_SEQ = [0]


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


async def _one(engine: str, turn: dict, world) -> list:
    from app import director, session
    from app.mission import capcom, registry
    os.environ["TURN_ENGINE"] = engine
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()
    clock = _Clock()
    _SEQ[0] += 1    # a fresh session id per run: the local brain rotates its templates per session
    s = session.Session(f"replay-{_SEQ[0]}", world[0], world[1], clock=clock, registry=registry)
    hello = {"t": "hello", "mode": "explorer"}
    if turn["mode"] == "mission":
        m = registry.create("shackleton_rim", 37, level="commander", save=False)
        hello = {"t": "hello", "mode": "mission", "mission_id": m.id, "role": None}
    await s.handle(hello)
    if turn.get("screen"):
        await s.handle({"t": "ui", "event": "screen", "screen": turn["screen"], "step_type": turn.get("step_type"),
                        "offer": turn.get("offer")})
    clock.t += 1.0
    src = turn.get("source") or "typed"
    if src in ("listen", "voice"):
        await s.handle({"t": "turn", "state": "start", "text": ""})
        clock.t += 0.5
        await s.handle({"t": "turn", "state": "end", "text": turn["text"]})
    else:
        await s.handle({"t": "typed", "text": turn["text"], "source": src})
    ids: dict = {}
    return normalise([d for d in s.outbox], ids)


def replay(log: str | None, golden: bool, show: int = 10, turns: list[dict] | None = None) -> int:
    """Each turn through a fresh session per engine (offline: no model server, no embedder), outboxes diffed."""
    os.environ.setdefault("MISSION_SAVE_DIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "turn_replay_saves"))
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app import models_client, safety
    from app.config import settings
    from app.gazetteer import Gazetteer
    from app.moments import MomentIndex

    async def off(*a, **k):
        return None

    async def no_tags(text, command_context=False):
        return []
    saved = (models_client.tag, models_client.embed, safety.tagger_read, os.environ.get("TURN_ENGINE"))
    models_client.tag, models_client.embed, safety.tagger_read = off, off, no_tags   # offline, deterministic
    try:
        world = (Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json"))
        turns = list(turns or []) + (_golden_turns() if golden else []) + (_log_turns(log) if log else [])
        bad = n_dec = 0
        for t in turns:
            a = asyncio.run(_one("legacy", t, world))
            b = asyncio.run(_one("graph", t, world))
            if a != b:
                bad += 1
                if bad <= show:
                    print(f"  DIFF [{t['src']}] {t['mode']}: {t['text']!r}\n    {_path(a, b)}")
            else:
                n_dec += len(a)
    finally:
        models_client.tag, models_client.embed, safety.tagger_read = saved[:3]
        if saved[3] is None:
            os.environ.pop("TURN_ENGINE", None)
        else:
            os.environ["TURN_ENGINE"] = saved[3]
    print(f"replayed turns: {len(turns)}; identical: {len(turns) - bad} ({n_dec} decisions); different: {bad}")
    return 1 if bad else 0


def bench(rounds: int = 5, model_ms: float = 0.0) -> int:
    """Per-turn latency of each engine (the golden turns, `rounds` times, engines interleaved), offline; `model_ms`
    simulates the local model server's Arc Tagger call (safety read and read-out each wait that long)."""
    import statistics
    import time
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app import director, models_client, safety, session
    from app.config import settings
    from app.gazetteer import Gazetteer
    from app.mission import capcom, registry
    from app.moments import MomentIndex

    async def tag(*a, **k):
        if model_ms:
            await asyncio.sleep(model_ms / 1000)
        return None

    async def tags(text, command_context=False):
        if model_ms:
            await asyncio.sleep(model_ms / 1000)
        return []

    async def off(*a, **k):
        return None
    os.environ.setdefault("MISSION_SAVE_DIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "turn_replay_saves"))
    models_client.tag, models_client.embed, safety.tagger_read = tag, off, tags
    world = (Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json"))
    turns = _golden_turns()
    ms: dict[str, list[float]] = {"legacy": [], "graph": []}

    async def one(engine: str, t: dict) -> float:
        os.environ["TURN_ENGINE"] = engine
        director.RULES.clear()
        director.PENDING.clear()
        capcom._explained.clear()
        _SEQ[0] += 1
        s = session.Session(f"bench-{_SEQ[0]}", world[0], world[1], clock=_Clock(), registry=registry)
        if t["mode"] == "mission":
            m = registry.create("shackleton_rim", 37, level="commander", save=False)
            await s.handle({"t": "hello", "mode": "mission", "mission_id": m.id, "role": None})
        else:
            await s.handle({"t": "hello", "mode": "explorer"})
        t0 = time.perf_counter()
        await s.handle({"t": "typed", "text": t["text"]})
        return (time.perf_counter() - t0) * 1000

    async def all_():
        for _ in range(rounds):
            for t in turns:
                for eng in (("legacy", "graph") if _ % 2 == 0 else ("graph", "legacy")):
                    ms[eng].append(await one(eng, t))
    asyncio.run(all_())
    for eng, xs in ms.items():
        xs.sort()
        print(f"{eng:6s} n={len(xs)} p50={statistics.median(xs):.2f} ms  p90={xs[int(len(xs) * 0.9)]:.2f} ms  "
              f"mean={statistics.fmean(xs):.2f} ms")
    d = statistics.median(ms["graph"]) - statistics.median(ms["legacy"])
    print(f"graph - legacy p50: {d:+.2f} ms (model server simulated at {model_ms:g} ms per call)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("diff", help="diff two suite recordings (pytest -p tools.turn_replay --turn-record ...)")
    d.add_argument("old")
    d.add_argument("new")
    d.add_argument("--noise", help="a second recording of the old engine (tests that differ run to run are left out)")
    d.add_argument("--show", type=int, default=10)
    r = sp.add_parser("replay", help="golden and logged turns through both engines")
    r.add_argument("--log", help="a turn log (turns.jsonl)")
    r.add_argument("--golden", action="store_true", help="the golden turns (director_model/data/gold*.json + ear set)")
    r.add_argument("--show", type=int, default=10)
    bp = sp.add_parser("bench", help="per-turn latency, old engine vs graph (offline)")
    bp.add_argument("--rounds", type=int, default=5)
    bp.add_argument("--model-ms", type=float, default=0.0, help="simulated Arc Tagger call time (ms)")
    a = ap.parse_args(argv)
    if a.cmd == "bench":
        return bench(a.rounds, a.model_ms)
    if a.cmd == "diff":
        return diff(a.old, a.new, a.noise, a.show)
    if not (a.log or a.golden):
        a.golden = True
    return replay(a.log, a.golden, a.show)


if __name__ == "__main__":
    raise SystemExit(main())
