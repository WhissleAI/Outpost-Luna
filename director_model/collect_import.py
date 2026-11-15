"""Import collection-kit sessions (collect.py) into the Director loop (docs/DIRECTOR_COLLECTION.md).

  1. decode (model_server env): every clip through the real Arc ear (EarStream, the app's turn logic) with the hot lists
     its screen had (stored in the manifest) -> <session>/decodes.jsonl (text only)
       cd model_server && uv run python ../director_model/collect_import.py decode --session <folder> [--session ...]
  2. items (any env): decodes + the prompted labels -> director_model/data/collected_turns.json, the format the
     generator replays like imported turn logs (gen_sessions.logged_items): heard words, screen frame, gold act / nav,
     device_directed from Arc; split by a hash of the session + cell: ~75 % train, 10 % val, 15 % test_log
       python3 director_model/collect_import.py items --session <folder> [--session ...]
Sessions without a consent.json with "agreed": true are refused. collected_turns.json is git-ignored (data/), never
committed; delete it (and the session folders) when the family asks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "collected_turns.json"


def consented(d: Path) -> bool:
    try:
        return json.loads((d / "consent.json").read_text()).get("agreed") is True
    except Exception:  # noqa: BLE001
        return False


def cmd_decode(a):
    sys.path.insert(0, os.getcwd())
    from app import arc_ear, arcmeta
    from app.stream_context import StreamContext
    arcmeta.load()
    tier = json.load(open(HERE.parent / "backend" / "tests" / "fixtures" / "ear_eval" / "tier_a.json"))
    for s in a.session:
        d = Path(s).expanduser()
        if not consented(d):
            print("no consent, skipped:", d)
            continue
        rows = [json.loads(x) for x in open(d / "manifest.jsonl")]
        with open(d / "decodes.jsonl", "w") as f:
            for r in rows:
                with wave.open(str(d / r["clip"])) as w:
                    pcm = w.readframes(w.getnframes())
                es = arc_ear.EarStream("assistant")
                ctx = StreamContext()
                ctx.update({"t": "context", "names": tier}, es)
                if r.get("hot"):
                    ctx.update({"t": "context", "hot": r["hot"]}, es)
                msgs = []
                for i in range(0, len(pcm), 2560):
                    msgs += es.feed_all(pcm[i:i + 2560])
                msgs += es.flush_all()
                es.close()
                fin = [m for m in msgs if m["t"] == "words" and m.get("final") and m["text"].strip()]
                arcs = [m for m in msgs if m["t"] == "arc" and m.get("device_directed") is not None]
                f.write(json.dumps({"i": r["i"], "hyp": " ".join(m["text"] for m in fin),
                                    "dd": arcs[-1]["device_directed"] if arcs else None,
                                    "alts": [x for m in fin for x in m.get("alts") or []],
                                    "conf": next((m.get("conf") for m in fin if m.get("conf") is not None), None)}) + "\n")
        print("decoded", d, len(rows))


def split_of(key: str) -> str:
    x = int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % 100
    return "test" if x < 15 else "val" if x < 25 else "train"


def cmd_items(a):
    have = json.loads(OUT.read_text())["items"] if OUT.exists() else []
    seen = {(x.get("session"), x.get("i")) for x in have}
    n = 0
    for s in a.session:
        d = Path(s).expanduser()
        if not consented(d) or not (d / "decodes.jsonl").exists():
            print("skipped (no consent or not decoded):", d)
            continue
        dec = {r["i"]: r for r in map(json.loads, open(d / "decodes.jsonl"))}
        for r in map(json.loads, open(d / "manifest.jsonl")):
            if (d.name, r["i"]) in seen or r["i"] not in dec:
                continue
            h = dec[r["i"]]
            heard = h["hyp"].strip()
            if not heard and r["gold"].get("act") != "ignore":
                continue                     # the ear heard nothing: nothing to replay
            text = r.get("expected_text") or heard
            it = {"text": text, "heard": heard, "frame": r["frame"], "gold": r["gold"], "cat": "collected_" + r["kind"],
                  "root": f"col:{d.name}:{r['cell']}", "split": split_of(d.name + r["cell"]), "conf": 1.0,
                  "session": d.name, "i": r["i"], "cell": r["cell"]}
            if h.get("dd") is not None:
                it["dd"] = (max(0.0, h["dd"] - 0.01), min(1.0, h["dd"] + 0.01))
            if r.get("lesson"):
                it.update(lesson=r["lesson"], step=r["step"])
            have.append(it)
            n += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"note": "collection-kit sessions (collect_import.py); local only, never committed",
                               "items": have}, indent=1))
    print(f"{n} new items, {len(have)} total -> {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["decode", "items"])
    ap.add_argument("--session", action="append", default=[])
    a = ap.parse_args()
    {"decode": cmd_decode, "items": cmd_items}[a.cmd](a)
