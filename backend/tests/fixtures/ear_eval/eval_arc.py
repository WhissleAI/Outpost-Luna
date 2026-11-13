"""Arc ear eval, in process (model_server's EarStream: the same turn logic as /v1/stream?ear=arc), no network.

cd model_server && uv run python ../backend/tests/fixtures/ear_eval/eval_arc.py [--cond none,tier_a,mission] [--set k=v]

conditions: none = no context; tier_a = what the backend sends (Tier A list); mission = the mission UI's context frame
in front of Tier A (as /ws/listen merges it). Endpoint latency = audio time of `turn end` - speech end, + the wall time
of the call that emitted it (the end_turn decode). Audio is fed as fast as Arc takes it (not real-time pace).
"""
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, ".")
from score import score, summarize  # noqa: E402

from app import arc_ear, arcmeta  # noqa: E402
from app.stream_context import StreamContext  # noqa: E402

MISSION = {"names": ["CAPCOM", "Houston", "Shackleton", "Cabeus"],
           "terms": ["shields", "life support", "greenhouse", "science", "rover", "comms", "heaters", "end shift", "shelter",
                     "solar storm", "millisievert"]}


def ctx_for(cond, tier):
    if cond == "none":
        return None
    if cond == "tier_a":
        return {"t": "context", "names": tier}
    seen = {x.lower() for x in MISSION["names"] + MISSION["terms"]}
    return {"t": "context", "names": (MISSION["names"] + [n for n in tier if n.lower() not in seen])[:200],
            "terms": MISSION["terms"]}


def run_clip(path, ctx, s):
    x = sf.read(path, dtype="int16")[0].tobytes()
    es = arc_ear.EarStream("assistant", s=s)
    if ctx:
        StreamContext().update(ctx, es)
    finals, end_wall, msgs = [], None, []
    for i in range(0, len(x), 2560):
        t = time.perf_counter()
        out = es.feed_all(x[i:i + 2560])
        w = time.perf_counter() - t
        for m in out:
            msgs.append(m)
            if m["t"] == "words" and m["final"]:
                finals.append(m["text"])
            if m["t"] == "turn" and m["state"] == "end" and end_wall is None:
                end_wall = w
    out = es.flush_all()
    finals += [m["text"] for m in out if m["t"] == "words" and m["final"]]
    es.close()
    states = [m["state"] for m in msgs if m["t"] == "turn"]
    first_end = es.turns.ends[0] if es.turns.ends else None
    return {"hyp": " ".join(finals), "end": first_end, "end_wall": end_wall, "states": states,
            "rtf": es.compute_s / es.audio_s, "eager": "eager" in states}


def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a and not a.startswith("--"))
    conds = (args.get("cond") or "none,tier_a,mission").split(",")
    s = arc_ear.EarSettings(**{k: type(getattr(arc_ear.ear_settings, k))(v) for k, v in args.items() if k.startswith("ear_")})
    arcmeta.load()
    if not arcmeta.STATE["decoder"]:
        sys.exit(f"Arc ear not loaded: {arcmeta.STATE['error']}")
    items = {it["id"]: it for it in json.load(open(HERE / "set.json"))["items"]}
    man = json.load(open(HERE / "manifest.json"))["clips"]
    tier = json.load(open(HERE / "tier_a.json"))
    res = {"settings": s.model_dump(), "load": arcmeta.health()["arc_ear"], "conditions": {}}
    for cond in conds:
        rows = []
        for m in man:
            r = run_clip(HERE / "audio" / f"{m['clip']}.wav", ctx_for(cond, tier), s)
            sc = score(items[m["id"]], r["hyp"])
            lat = None
            if r["end"]:
                lat = round((r["end"]["at"] - m["speech_end_s"] + (r["end_wall"] or 0)) * 1000)
            rows.append({**m, **sc, "hyp": r["hyp"], "ref": items[m["id"]]["text"], "end_ms": lat,
                         "end_reason": r["end"]["reason"] if r["end"] else None, "states": r["states"], "rtf": round(r["rtf"], 3)})
        lats = [r["end_ms"] for r in rows if r["end_ms"] is not None]
        summ = {"all": summarize(rows), "clean": summarize([r for r in rows if not r["noisy"]]),
                "noisy": summarize([r for r in rows if r["noisy"]]),
                "endpoint_ms_p50": statistics.median(lats) if lats else None,
                "endpoint_ms_p90": sorted(lats)[int(0.9 * (len(lats) - 1))] if lats else None,
                "turn_end_missing": sum(r["end_ms"] is None for r in rows),
                "eager_rate": round(sum("eager" in r["states"] for r in rows) / len(rows), 2),
                "rtf_mean": round(statistics.mean(r["rtf"] for r in rows), 3)}
        res["conditions"][cond] = {"summary": summ, "rows": rows}
        print(cond, json.dumps(summ), flush=True)
    tag = args.get("tag", "arc")
    json.dump(res, open(HERE / f"results_{tag}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
