"""Ear before / after the per-screen hot lists (round 7): WER, keyword recall, NAME recall, false triggers.

Every clip is rendered once IN MEMORY (real_ear.iter_audio: held-out test voices, kid-style pitch / rate jitter, half
with classroom babble + pink noise, some reverb; no audio on disk) and decoded twice by the real Arc ear (EarStream,
the /v1/stream?ear=arc logic): `base` = the backend's Tier A context only (what ships today), `hot` = Tier A + the
screen's tiered hot lists (backend/app/hotlist.py; model_server/app/hotbias.py).

Sets
  mishear  the round-6 cls_mishear held-out items (kid answers / orders in their lesson or cabin frame)
  names    kid questions naming a place, a crew member or a piece of hardware, on the screen that shows it
  ear40    the 40-line ear eval (backend/tests/fixtures/ear_eval/set.json), 2 voices each; commands in the cabin,
           the rest in the library
  chatter  room chatter and adult talk on lesson / cabin screens, plus babble-only clips: false triggers = hot phrases
           in the decode that the speaker never said

  1. jobs   (backend env)       uv run --project backend python director_model/ear_hot_eval.py jobs
  2. decode (model_server env)  cd model_server && uv run python ../director_model/ear_hot_eval.py decode --procs 3
  3. score  (backend env)       uv run --project backend python director_model/ear_hot_eval.py score
Files (text only): director_model/cache/ear_hot/{jobs.jsonl, dec_<variant>.jsonl, score.json}.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("EAR_HOT_CACHE", HERE / "cache" / "ear_hot"))
EAR = HERE.parent / "backend" / "tests" / "fixtures" / "ear_eval"
ADULT = ["did you remember to take the chicken out", "i'll be back in five minutes", "can you pass me that",
         "we need to leave at four", "she said the meeting moved", "turn that down a bit please", "where are my keys",
         "it's getting late", "do you want some water", "i think it's going to rain", "let me call grandma back",
         "the car is in the shop", "dinner's almost ready", "what time is practice", "put your shoes on"]


def cmd_jobs(a):
    sys.path.insert(0, str(HERE.parent / "backend"))
    sys.path.insert(0, str(HERE))
    os.environ.setdefault("MODEL_SERVER_URL", "http://127.0.0.1:1")
    import gen_sessions as G
    import pools as P
    from app import hotlist as H
    from app.academy import content as AC
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []

    def frame_step(fr):
        if fr and fr.get("lesson_id") is not None and fr.get("screen") in ("lesson", "ride"):
            L = AC.lesson(fr["lesson_id"])
            return L["steps"][fr["step"]] if L else None
        return None

    def add(set_, text, frame, names=None, noise_only=False):
        k = f"{set_}{len(jobs):04d}"
        hot = H.hot_lists(frame, frame_step(frame))
        jobs.append({"key": k, "group": "test", "set": set_, "text": text, "frame": frame, "hot": hot,
                     "names": names or [], "seed": random.Random(k).randrange(1 << 30), "noise_only": noise_only})
    for it in G.class_set_items("mishear", a.n, 990_000 + 1000 * P.CLASSES.index("mishear")):
        add("mishear", it["text"], it["frame"])
    V = H.vocab()
    rng = random.Random(7)
    pools = [("place", V["places"], ["tell me about {x}", "where is {x}", "show me {x}", "how big is {x}",
                                     "what is at {x}"], "library"),
             ("crew", [c for c in V["crew"] if " " in c], ["who is {x}", "tell me about {x}", "what did {x} do"],
              "library"),
             ("hardware", [h for h in V["hardware"] if len(h) < 32], ["where is {x}", "tell me about {x}",
                                                                      "what is the {x}"], "library"),
             ("site", V["sites"], ["pick {x}", "land at {x}", "{x}"], "brief")]
    for kind, xs, tpls, screen in pools:
        for x in rng.sample(xs, min(len(xs), a.names_per)):
            add("names", rng.choice(tpls).format(x=x), {"screen": screen}, names=[x])
    items = json.loads((EAR / "set.json").read_text())["items"]
    for it in items:
        fr = {"screen": "cabin"} if it["id"].startswith("c") else {"screen": "library"}
        for v in range(2):
            add("ear40", it["text"], fr, names=it.get("names") or [])
    lessons = P.lesson_steps()
    for t in P.LESSON_CHATTER + ADULT:
        L, i = rng.choice(lessons)
        add("chatter", t, P.step_frame(L, i) if rng.random() < 0.6 else {"screen": "cabin"})
    for k in range(20):
        L, i = rng.choice(lessons)
        add("chatter", "", P.step_frame(L, i) if k % 2 else {"screen": "cabin"}, noise_only=True)
    with open(OUT / "jobs.jsonl", "w") as f:
        for j in jobs:
            f.write(json.dumps(j) + "\n")
    print(f"{len(jobs)} jobs -> {OUT / 'jobs.jsonl'}", {s: sum(j['set'] == s for j in jobs)
                                                       for s in ("mishear", "names", "ear40", "chatter")})


def _noise_clip(seed: int):
    """Babble-free room noise + a little pink noise, 2.5 s (the false-trigger probe without any speech)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    n = int(2.5 * 16000)
    pk = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) / np.sqrt(np.arange(1, n // 2 + 2)), n)
    x = 0.02 * pk / (np.abs(pk).max() + 1e-9) + 0.003 * rng.standard_normal(n)
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def _worker(args):
    wid, nproc, jobs, threads, variants = args
    os.environ["ARC_META_THREADS"] = str(threads)
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, str(HERE))
    from app import arc_ear, arcmeta
    from app.stream_context import StreamContext
    import real_ear as RE
    arcmeta.load()
    tier = json.load(open(EAR / "tier_a.json"))
    mine = jobs[wid::nproc]
    speech = [j for j in mine if not j["noise_only"]]
    clips = {j["key"]: (x, m) for j, x, m in RE.iter_audio(speech)}
    for j in mine:
        if j["noise_only"]:
            clips[j["key"]] = (_noise_clip(j["seed"]), {"noise_only": True})
    outs = {v: open(OUT / f"dec_{v}.w{wid}.jsonl", "w") for v in variants}
    for j in mine:
        if j["key"] not in clips:
            continue
        x, meta = clips[j["key"]]
        for v in variants:
            es = arc_ear.EarStream("assistant")
            ctx = StreamContext()
            ctx.update({"t": "context", "names": tier}, es)
            if v != "base":
                ctx.update({"t": "context", "hot": j["hot"]}, es)
            msgs = []
            t0 = time.perf_counter()
            for i in range(0, len(x), 2560):
                msgs += es.feed_all(x[i:i + 2560])
            msgs += es.flush_all()
            es.close()
            fin = [m for m in msgs if m["t"] == "words" and m.get("final") and m["text"].strip()]
            outs[v].write(json.dumps({"key": j["key"], "hyp": " ".join(m["text"] for m in fin),
                                      "alts": [a for m in fin for a in m.get("alts") or []],
                                      "conf": next((m.get("conf") for m in fin if m.get("conf") is not None), None),
                                      "rescored": any(m.get("rescored") for m in fin),
                                      "hot": next((m.get("hot") for m in fin if m.get("hot")), None),
                                      "s": round(time.perf_counter() - t0, 2), "render": meta}) + "\n")
            outs[v].flush()
    for f in outs.values():
        f.close()
    return len(mine)


def cmd_decode(a):
    from multiprocessing import get_context
    jobs = [json.loads(line) for line in open(OUT / "jobs.jsonl")]
    if a.only:
        jobs = [j for j in jobs if j["set"] in a.only.split(",")]
    variants = a.variants.split(",")
    t0 = time.time()
    with get_context("spawn").Pool(a.procs) as p:
        n = sum(p.map(_worker, [(i, a.procs, jobs, a.threads, variants) for i in range(a.procs)]))
    for v in variants:
        with open(OUT / f"dec_{v}{a.tag}.jsonl", "w") as f:
            for i in range(a.procs):
                w = OUT / f"dec_{v}.w{i}.jsonl"
                if w.exists():
                    f.write(w.read_text())
                    w.unlink()
    print(f"decoded {n} clips x {len(variants)} variants in {time.time() - t0:.0f} s")


# ------------------------------------------------------------------------------------------------- score
def cmd_score(a):
    sys.path.insert(0, str(EAR))
    sys.path.insert(0, str(HERE.parent / "backend"))
    from score import norm, edits
    from app import soundalike as SA
    jobs = {j["key"]: j for j in map(json.loads, open(OUT / "jobs.jsonl"))}
    res = {}
    for v in a.variants.split(","):
        f = OUT / f"dec_{v}{a.tag}.jsonl"
        if not f.exists():
            continue
        decs = [json.loads(line) for line in open(f)]
        by = {}
        for d in decs:
            j = jobs[d["key"]]
            r = by.setdefault(j["set"], {"n": 0, "err": 0, "ref_w": 0, "kw": 0, "kw_hit": 0, "kw_hit_sa": 0,
                                         "names": 0, "names_hit": 0, "false": 0, "false_turns": 0, "empty": 0,
                                         "rescored": 0})
            r["n"] += 1
            ref, hyp = norm(j["text"]), norm(d["hyp"])
            r["err"] += edits(ref, hyp)
            r["ref_w"] += len(ref)
            r["empty"] += not hyp
            r["rescored"] += bool(d.get("rescored"))
            rt, ht = " " + " ".join(ref) + " ", " " + " ".join(hyp) + " "
            hot = [p for p in (j["hot"]["step"] + j["hot"]["screen"]) if norm(p)]
            kws = {" ".join(norm(p)) for p in hot if f" {' '.join(norm(p))} " in rt and len(" ".join(norm(p))) >= 3}
            # keep the longest keyword when one is inside another ("far side" over "far")
            kws = {k for k in kws if not any(k != o and f" {k} " in f" {o} " for o in kws)}
            fixed = " " + " ".join(norm(SA.repair(d["hyp"], j["hot"]["step"])[0])) + " "
            for k in kws:
                r["kw"] += 1
                r["kw_hit"] += f" {k} " in ht
                r["kw_hit_sa"] += f" {k} " in fixed
            for nm in j.get("names") or []:
                k = " ".join(norm(nm))
                r["names"] += 1
                r["names_hit"] += f" {k} " in ht
            fl = [" ".join(norm(p)) for p in hot if len(" ".join(norm(p))) >= 3 and f" {' '.join(norm(p))} " in ht
                  and f" {' '.join(norm(p))} " not in rt]
            fl = [k for k in fl if not any(k != o and f" {k} " in f" {o} " for o in fl)]
            r["false"] += len(fl)
            r["false_turns"] += bool(fl)
        out = {}
        for s_, r in by.items():
            out[s_] = {"clips": r["n"], "wer": round(r["err"] / max(1, r["ref_w"]), 3),
                       "kw_recall": round(r["kw_hit"] / r["kw"], 3) if r["kw"] else None,
                       "kw_recall_soundalike": round(r["kw_hit_sa"] / r["kw"], 3) if r["kw"] else None,
                       "keywords": r["kw"], "name_recall": round(r["names_hit"] / r["names"], 3) if r["names"] else None,
                       "names": r["names"], "false_hot_per_100": round(100 * r["false"] / r["n"], 1),
                       "false_turns": r["false_turns"], "empty": r["empty"], "rescored": r["rescored"]}
        res[v] = out
    (OUT / f"score{a.tag}.json").write_text(json.dumps(res, indent=1))
    sets = ["mishear", "names", "ear40", "chatter"]
    print("| set | variant | clips | WER | keyword recall | + sound-alike | name recall | false hot / 100 clips |")
    print("|---|---|---|---|---|---|---|---|")
    for s_ in sets:
        for v, out in res.items():
            r = out.get(s_)
            if r:
                print(f"| {s_} | {v} | {r['clips']} | {r['wer']} | {r['kw_recall']} ({r['keywords']}) | "
                      f"{r['kw_recall_soundalike']} | {r['name_recall']} ({r['names']}) | {r['false_hot_per_100']} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["jobs", "decode", "score"])
    ap.add_argument("--n", type=int, default=160)
    ap.add_argument("--names-per", type=int, default=30)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--variants", default="base,hot")
    ap.add_argument("--only", default="")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    {"jobs": cmd_jobs, "decode": cmd_decode, "score": cmd_score}[a.cmd](a)
