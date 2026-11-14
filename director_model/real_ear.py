"""REAL Arc decodes of the generator's kid turns (instead of the fitted error model): render each turn's text with Steer
TTS Edge (many voices, biased to higher-pitched / kid-like ones, rate jitter, half with classroom babble + pink noise
at 10-20 dB, some room reverb), decode the audio with the real Arc ear (model_server's EarStream: the same turn logic as
/v1/stream?ear=arc, with the backend's Tier A context frame), and cache {words partials, turn states, arc dd/cc, final}
per clip. gen_sessions.py replays these decodes as the kid's heard words and turn events (`--real-ear`).

Cache (gitignored, text only, ~5 KB per turn): director_model/cache/real_ear/{jobs.jsonl, dec/<key>.json}. NO audio is
kept on disk: each clip is rendered in memory (seeded, so it is reproducible) and decoded right away. A re-run skips
what is decoded; after a new Arc model, delete dec/ (`make director-retrain NEW_EAR=1`) and the audio is re-rendered.

  1. jobs    (backend env)   uv run --project backend python director_model/real_ear.py jobs --train 3000 --budget 3500
  2. decode  (model_server env: it has steertts-edge + Arc)  render in memory + decode with the real Arc ear
                             cd model_server && uv run python ../director_model/real_ear.py decode --procs 6

Voices: the 200 Steer voices ranked by median f0; rank % 5 == 0 -> test voices, rank % 5 == 1 -> val voices, others
train (the held-out sets never hear a training voice). Groups: train / val / test (key = group + text + variant).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("REAL_EAR_CACHE", HERE / "cache" / "real_ear"))
JOBS = CACHE / "jobs.jsonl"
SR = 16000


def key_of(group: str, text: str, var: int = 0) -> str:
    return hashlib.md5(f"{group}|{text}|{var}".encode()).hexdigest()[:16]


# ------------------------------------------------------------------------------------------------- 1. jobs
def items_of(script: dict) -> list[str]:
    out = []
    for it in script["items"]:
        if it.get("op") in ("end_shift", "emotion", "tap", "lesson", "echo") or "heard" in it or not it.get("text"):
            continue
        out.append(it["text"])
    return out


def cmd_jobs(a):
    sys.argv = [sys.argv[0]]
    import gen_sessions as G  # noqa: E402  (backend env)
    CACHE.mkdir(parents=True, exist_ok=True)
    have = {}
    if JOBS.exists():
        for line in open(JOBS):
            j = json.loads(line)
            have[j["key"]] = j
    new = []

    def add(group, text, var=0):
        k = key_of(group, text, var)
        if k in have:
            return
        rng = random.Random(k)
        j = {"key": k, "group": group, "text": text, "var": var, "seed": rng.randrange(1 << 30)}
        have[k] = j
        new.append(j)

    def sessions(split, n, seed0, mode):
        for k in range(n):
            rng = random.Random(seed0 + k)
            sc = G.kind_script(rng, split, seed0 + k)
            noised = mode == "all" or rng.random() < 0.5
            if noised:
                yield k, sc

    budget = {"train": a.budget, "val": a.val_budget, "test": a.test_budget}
    plan = [("train", "train", a.train, 10_000 + a.seed * 1_000_000, "half"), ("val", "val", a.val, 500_000, "half"),
            ("test", "test", a.test, 900_000, "all")]
    for group, split, n, seed0, mode in plan:
        n0 = len([j for j in have.values() if j["group"] == group])
        texts: set = set()
        for _, sc in sessions(split, n, seed0, mode):
            if len(texts) >= budget[group]:
                break
            for t in items_of(sc):
                if t not in texts:
                    texts.add(t)
                    add(group, t)
        # a second voice for the most frequent train texts (variety of decodes for the same words)
        print(f"{group}: {len([j for j in have.values() if j['group'] == group]) - n0} new jobs", flush=True)
    with open(JOBS, "a") as f:
        for j in new:
            f.write(json.dumps(j) + "\n")
    print(f"{len(new)} new jobs, {len(have)} total -> {JOBS}")


def load_jobs() -> list[dict]:
    return [json.loads(line) for line in open(JOBS)] if JOBS.exists() else []


# ------------------------------------------------------------------------------------------------- 2. render (in memory)
def iter_audio(jobs):
    """Render each job IN MEMORY (no audio is written to disk) -> (job, int16 PCM bytes at 16 kHz, render meta)."""
    import glob
    from math import gcd

    import numpy as np
    from scipy.signal import fftconvolve, resample_poly
    from steertts_edge import OnnxTTS
    d = glob.glob(str(Path.home() / ".cache/huggingface/hub/models--WhissleAI--steer-tts-edge/snapshots/*/"))[0]
    tts = OnnxTTS.from_pretrained(d)
    tsr = int(getattr(tts, "sample_rate", 0) or 24000)
    by_f0 = sorted(tts.voices, key=lambda v: -tts.voice_stats(v)["f0_med"])
    groups = {"test": [v for i, v in enumerate(by_f0) if i % 5 == 0], "val": [v for i, v in enumerate(by_f0) if i % 5 == 1],
              "train": [v for i, v in enumerate(by_f0) if i % 5 > 1]}
    bab_pool: list = []
    for j in jobs:
        rng = np.random.default_rng(j["seed"])
        vs = groups[j["group"]]
        # bias to higher-pitched (kid-like) voices: the list is f0-descending; draw an index ~ |N(0, 0.35 n)|
        vi = min(len(vs) - 1, int(abs(rng.normal(0, 0.35 * len(vs)))))
        v = vs[vi]
        ctrl = {"rate": float(rng.uniform(-1.0, 1.2))}
        if rng.random() < 0.5:
            ctrl["f0_med"] = float(tts.voice_stats(v)["f0_med"] + rng.uniform(0.5, 2.0))
        try:
            w = tts(j["text"], voice=v, ctrl=ctrl)
        except Exception:  # noqa: BLE001
            try:
                w = tts(j["text"], voice=v)
            except Exception as e:  # noqa: BLE001
                print("render fail", j["text"], e, flush=True)
                continue
        if w is None:
            continue
        w = np.asarray(w, np.float32).reshape(-1)
        g = gcd(tsr, SR)
        w = resample_poly(w, SR // g, tsr // g).astype(np.float32)
        w = 0.5 * w / (np.abs(w).max() + 1e-9)
        clean = w.copy()
        meta = {"voice": v, "voice_rank": vi, "ctrl": ctrl}
        if rng.random() < 0.3:      # room reverb: exponentially decaying noise RIR, RT60 0.2-0.6 s
            rt = rng.uniform(0.2, 0.6)
            n = int(rt * SR)
            rir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
            rir[0] = 1.0 / rng.uniform(0.3, 0.8)
            w = fftconvolve(w, rir)[: len(w) + n // 3].astype(np.float32)
            w = 0.5 * w / (np.abs(w).max() + 1e-9)
            meta["rt60"] = round(rt, 2)
        lead, tail = rng.uniform(0.2, 0.5), 1.2
        x = np.concatenate([np.zeros(int(lead * SR), np.float32), w, np.zeros(int(tail * SR), np.float32)])
        if rng.random() < 0.5 and len(bab_pool) >= 3:
            bab = np.zeros_like(x)
            for o in rng.choice(len(bab_pool), 3, replace=False):
                b = bab_pool[o][::-1] if rng.random() < 0.5 else bab_pool[o]
                st = int(rng.integers(0, max(1, len(x) - len(b))))
                bab[st:st + len(b)] += b[: len(x) - st]
            pk = np.fft.irfft(np.fft.rfft(rng.standard_normal(len(x))) / np.sqrt(np.arange(1, len(x) // 2 + 2)), len(x))
            pk = pk / (np.abs(pk).max() + 1e-9)
            noise = 0.7 * bab / (np.abs(bab).max() + 1e-9) + 0.3 * pk
            snr = float(rng.uniform(10, 20))
            ps, pn = np.mean(w ** 2), np.mean(noise ** 2) + 1e-12
            x = x + noise * np.sqrt(ps / (pn * 10 ** (snr / 10)))
            meta["snr_db"] = round(snr, 1)
        bab_pool.append(clean)
        bab_pool = bab_pool[-40:]
        yield j, (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes(), meta


# ------------------------------------------------------------------------------------------------- 3. decode
def _decode_worker(args):
    wid, nproc, jobs, threads = args
    os.environ["ARC_META_THREADS"] = str(threads)
    sys.path.insert(0, os.getcwd())
    from app import arc_ear, arcmeta
    from app.stream_context import StreamContext
    arcmeta.load()
    if not arcmeta.STATE.get("decoder"):
        print("Arc ear not loaded:", arcmeta.STATE.get("error"), flush=True)
        return 0
    tier = json.load(open(HERE.parent / "backend" / "tests" / "fixtures" / "ear_eval" / "tier_a.json"))
    (CACHE / "dec").mkdir(parents=True, exist_ok=True)
    done = 0
    t0 = time.time()
    for j, x, rmeta in iter_audio([j for j in jobs[wid::nproc] if not (CACHE / "dec" / f"{j['key']}.json").exists()]):
        out = CACHE / "dec" / f"{j['key']}.json"
        es = arc_ear.EarStream("assistant")
        StreamContext().update({"t": "context", "names": tier}, es)
        msgs = []
        for i in range(0, len(x), 2560):
            msgs += es.feed_all(x[i:i + 2560])
        msgs += es.flush_all()
        es.close()
        ev = []
        for m in msgs:
            if m["t"] == "words":
                ev.append({"t": "words", "text": m["text"], "final": bool(m.get("final"))})
            elif m["t"] == "turn":
                ev.append({"t": "turn", "state": m["state"], "text": m.get("text") or ""})
            elif m["t"] == "arc":
                ev.append({"t": "arc", "dd": m.get("device_directed"), "cc": m.get("command_complete")})
        finals = [e["text"] for e in ev if e["t"] == "words" and e["final"] and e["text"].strip()]
        out.write_text(json.dumps({"key": j["key"], "text": j["text"], "group": j["group"], "hyp": " ".join(finals),
                                   "events": ev, "render": rmeta, "rtf": round(es.compute_s / max(es.audio_s, 1e-6), 3)}))
        done += 1
        if done % 100 == 0:
            print(f"decode[{wid}] {done} ({time.time() - t0:.0f} s)", flush=True)
    return done


def cmd_decode(a):
    from multiprocessing import get_context
    jobs = load_jobs()
    todo = [j for j in jobs if not (CACHE / "dec" / f"{j['key']}.json").exists()]
    if a.order == "test_first":
        todo.sort(key=lambda j: {"test": 0, "val": 1, "train": 2}[j["group"]])
    print(f"decode {len(todo)} of {len(jobs)}", flush=True)
    t0 = time.time()
    with get_context("spawn").Pool(a.procs) as p:
        n = sum(p.map(_decode_worker, [(i, a.procs, todo, a.threads) for i in range(a.procs)]))
    print(f"decoded {n} in {time.time() - t0:.0f} s")


# ------------------------------------------------------------------------------------------------- reading the cache
class RealEar:
    """group -> text -> [decodes]. Used by gen_sessions.py."""

    def __init__(self, cache: Path = CACHE):
        self.by: dict = {}
        d = cache / "dec"
        if not d.exists():
            return
        for f in d.glob("*.json"):
            r = json.loads(f.read_text())
            self.by.setdefault(r["group"], {}).setdefault(r["text"], []).append(r)

    def get(self, group: str, text: str, rng: random.Random):
        xs = self.by.get(group, {}).get(text)
        return rng.choice(xs) if xs else None

    def n(self, group=None):
        return sum(len(v) for g, t in self.by.items() if group in (None, g) for v in t.values())


def cmd_stats(a):
    import difflib
    re_ = RealEar()
    for g in ("train", "val", "test"):
        rows = [r for t in re_.by.get(g, {}).values() for r in t]
        if not rows:
            continue
        err = n = 0
        empty = 0
        for r in rows:
            ref, hyp = r["text"].split(), r["hyp"].lower().replace(",", "").replace(".", "").replace("?", "").split()
            empty += not hyp
            sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
            err += sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")
            n += len(ref)
        print(f"{g}: {len(rows)} decodes, rough WER {err / max(1, n):.3f}, empty {empty}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["jobs", "decode", "stats"])
    ap.add_argument("--train", type=int, default=3000)
    ap.add_argument("--val", type=int, default=150)
    ap.add_argument("--test", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=int, default=3500)
    ap.add_argument("--val-budget", type=int, default=300)
    ap.add_argument("--test-budget", type=int, default=500)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--order", default="test_first")
    a = ap.parse_args()
    sys.path.insert(0, str(HERE))
    {"jobs": cmd_jobs, "decode": cmd_decode, "stats": cmd_stats}[a.cmd](a)
