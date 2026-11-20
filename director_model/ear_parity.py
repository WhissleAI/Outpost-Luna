"""Downstream parity of two ears (docs/LOCAL_EAR.md "Lighter ear"): the SAME jobs decoded by two copies of the ear
(two real_ear.py caches), each replayed into a fresh backend Session as the live relay posts it (replay.messages), with
the shipped Director (DIRECTOR_MODEL default: guarded, the rules as fallback) and the backend router. Per job: what the
app did (every decision the Session sent: say / navigate / command / clarify ..., minus ids and clocks), and what the
learned Director read at the turn's end (its act head, argmax). Prints the agreement, the jobs that differ, and the
same counts per group.

    cd backend && .venv/bin/python ../director_model/ear_parity.py <cache A> <cache B> [--json out.json]

Echo-bank clips (our own line through the speaker) are replayed while that line plays (`playback` start/end), so the
echo check and the leak rule see what they see live.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from app import models_client, session as S  # noqa: E402
from app.config import settings  # noqa: E402
from app.director_model import features as FX, replay as RP, runtime as RT  # noqa: E402
from app.gazetteer import Gazetteer  # noqa: E402
from app.moments import MomentIndex  # noqa: E402

GAZ = Gazetteer(HERE.parent / "backend/data/places.json")
IDX = MomentIndex(settings.data_dir / "index/clips.json")
SKIP = {"id", "did", "at", "t0", "ts", "time", "clock", "seq", "session", "ms", "elapsed", "wall_ms", "turn_id"}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def slim(d):
    if isinstance(d, dict):
        return {k: slim(v) for k, v in sorted(d.items()) if k not in SKIP and not k.startswith("_")}
    if isinstance(d, list):
        return [slim(x) for x in d]
    if isinstance(d, float):
        return round(d, 2)
    return d


async def replay_one(d: dict, job: dict) -> dict:
    clock = Clock()
    sess = S.Session(f"p-{d['key']}", GAZ, IDX, clock=clock)
    acts: list = []
    sink: list = []
    if sess.dm is not None:              # the shipped Director (guarded); record its act read at each turn end
        orig = sess.dm.step

        def step(ev, read=None, _o=orig):
            out = _o(ev, read)
            if ev.get("t") == "words" and ev.get("final") and isinstance(out, dict) and out.get("act") is not None:
                try:
                    acts.append(FX.ACTS[int(max(range(len(out["act"])), key=lambda i: out["act"][i]))])
                except Exception:  # noqa: BLE001
                    pass
            return out
        sess.dm.step = step
    fr = job.get("frame") or {"screen": "cabin"}
    await sess.handle({"t": "hello", "mode": "academy" if fr.get("lesson_id") else "cadet", "session": sess.id,
                       **({"lesson_id": fr["lesson_id"]} if fr.get("lesson_id") else {})})
    await sess.handle({"t": "ui", "event": "screen", **fr})
    if fr.get("lesson_id") and fr.get("step") is not None:
        await sess.handle({"t": "lesson", "lesson_id": fr["lesson_id"], "step": fr["step"], "status": "task"})
    n0 = len(sess.outbox)
    echo = job.get("group") == "echo_bank"
    if echo:
        await sess.handle({"t": "playback", "kind": "crew" if job.get("clip") else "guide", "state": "start",
                           "id": "E1", "text": job.get("text") or ""})
    msgs = RP.messages(d) or []
    for m in msgs:
        clock.t += 0.3
        await sess.handle(dict(m))
    clock.t += 1.0
    if echo:
        await sess.handle({"t": "playback", "kind": "crew" if job.get("clip") else "guide", "state": "end", "id": "E1"})
    try:
        await sess.poll()
    except Exception:  # noqa: BLE001
        pass
    out = [slim(x) for x in sess.outbox[n0:]]
    return {"decisions": out, "acts": acts, "turn": bool(msgs)}


def load(cache: Path) -> dict:
    return {p.stem: json.loads(p.read_text()) for p in (cache / "dec").glob("*.json")}


def jobs(cache: Path) -> dict:
    out = {}
    for line in open(cache / "jobs.jsonl"):
        j = json.loads(line)
        out[j["key"]] = j
    return out


async def main_async(a):
    async def none(*x, **k):
        return None
    models_client.tag = none          # Arc Tagger read-outs are the same text either way; no model server needed
    ca, cb, js = load(a.a), load(a.b), jobs(a.a)
    keys = sorted(set(ca) & set(cb))
    same_dec, same_act, n_act, by_grp, diffs = 0, 0, 0, Counter(), []
    tot = Counter()
    for k in keys:
        ra, rb = await replay_one(ca[k], js.get(k, {})), await replay_one(cb[k], js.get(k, {}))
        g = js.get(k, {}).get("group", "?")
        tot[g] += 1
        ok = ra["decisions"] == rb["decisions"]
        same_dec += ok
        by_grp[g] += ok
        if ra["acts"] or rb["acts"]:
            n_act += 1
            same_act += ra["acts"] == rb["acts"]
        if not ok and len(diffs) < 60:
            diffs.append({"key": k, "group": g, "text": js.get(k, {}).get("text"), "A_hyp": ca[k].get("hyp"),
                          "B_hyp": cb[k].get("hyp"), "A": ra["decisions"], "B": rb["decisions"],
                          "A_acts": ra["acts"], "B_acts": rb["acts"]})
    rep = {"jobs": len(keys), "decisions_identical": round(same_dec / max(len(keys), 1), 4),
           "director_act_identical": round(same_act / max(n_act, 1), 4), "turns_with_act": n_act,
           "by_group": {g: f"{by_grp[g]}/{tot[g]}" for g in tot}, "diffs": diffs}
    print(json.dumps({k: v for k, v in rep.items() if k != "diffs"}, indent=1))
    for d in diffs[:20]:
        print(f"- {d['group']} {d['text']!r}\n    A {d['A_hyp']!r} -> {json.dumps(d['A'])[:300]}\n"
              f"    B {d['B_hyp']!r} -> {json.dumps(d['B'])[:300]}")
    if a.json:
        a.json.write_text(json.dumps(rep, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--json", type=Path)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
