"""A/B of two copies of the ear's model on the same audio, read-out by read-out (docs/LOCAL_EAR.md "Lighter ear").

Each model runs in its own process through the app's own EarStream (live mode, the app's defaults), clip by clip, fed
in 80 ms chunks with 1.5 s of silence after; EVERY message the ear sends is kept, stamped with the audio time it came
out at. `compare` then lines the two runs up turn by turn and field by field.

    # 1. the clip sets (16 kHz PCM16 + refs + names lists) into OUT
    .venv/bin/python tools/ear_ab.py build --out OUT [--crew 60]
    # 2. each model in its own process (ARC_LIB / ARC_ORT as the app: libarc + its pinned ONNX Runtime)
    ARC_VERIFY=off .venv/bin/python tools/ear_ab.py run --model <nft2 dir> --tag A --out OUT
    ARC_VERIFY=off .venv/bin/python tools/ear_ab.py run --model <other nft2> --tag B --out OUT
    # 3. per-field agreement + WER / links / latency (and --noise A2: a second A run, the run-to-run noise)
    .venv/bin/python tools/ear_ab.py compare --out OUT A B [--noise A2]
    # the same comparison over two director_model/real_ear.py caches (the round-11 voice bank + echo bank)
    .venv/bin/python tools/ear_ab.py compare-cache <cache A> <cache B> [--noise <cache A2>]

Sets: golden (desktop/tests/golden, the release gate's 40 clips, tier_a names), crew (Artemis II crew audio cut at
pauses, Deepgram refs, the catalogue names said + 20 decoys: tools/ear_compare.py), orientale (the smoke gate's clip).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import resource
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
SR, CHUNK = 16000, 1280
DD_MIN = 0.5


# ------------------------------------------------------------------------------------------------- build
def build(out: Path, n_crew: int):
    import random
    import wave
    import ear_compare as EC
    (out / "wav").mkdir(parents=True, exist_ok=True)
    clips = []
    gold = json.loads((ROOT / "desktop/tests/golden/set.json").read_text())
    tier = [{"name": n} for n in json.loads((ROOT / "backend/tests/fixtures/ear_eval/tier_a.json").read_text())]
    for c in gold["clips"]:
        with wave.open(str(ROOT / "desktop/tests/golden/audio" / f"{c['clip']}.wav")) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2")
        clips.append({"id": f"golden_{c['clip']}", "set": "golden", "wav": EC.save(out, f"golden_{c['clip']}", x),
                      "ref": c["text"], "gold": c["names"], "numbers": c["numbers"], "names": tier,
                      "noisy": c["noisy"]})
    cat, screen_names = EC.catalogue()
    x = np.frombuffer((ROOT / "backend/tests/fixtures/crew_orientale_16k.s16le").read_bytes(), "<i2")
    clips.append({"id": "orientale", "set": "orientale", "wav": EC.save(out, "orientale", x),
                  "ref": "And now I can zoom in. I'm just gonna take out Orientale for a second. Oh my.",
                  "gold": ["Orientale Basin"], "names": screen_names({"screen": "map"})})
    # crew segments, as ear_compare.build cuts them (same seed)
    rng = random.Random(7)
    idx = json.loads((EC.DATA / "index/clips.json").read_text())["clips"]
    named, plain = [], []
    for c in idx:
        f = EC.DATA / "media/audio" / Path(c["file"]).name
        if not f.exists() or not c.get("words"):
            continue
        ws = c["words"]
        seg = [ws[0]]
        for w in ws[1:] + [None]:
            if w is None or w[0] - seg[-1][3] >= 0.8 or w[3] - seg[0][0] > 12:
                t0, t1 = seg[0][0], seg[-1][3]
                if 3 <= t1 - t0 <= 12 and len(seg) >= 5:
                    ref = " ".join(x[1] for x in seg)
                    g = EC.gold_names(ref, cat)
                    (named if g else plain).append({"file": f, "t0": max(0, t0 - 0.3), "t1": t1 + 0.3, "ref": ref,
                                                     "gold": g})
                seg = [w] if w else []
            else:
                seg.append(w)
    rng.shuffle(named)
    rng.shuffle(plain)
    k = min(len(named), n_crew * 3 // 5)
    for i, s in enumerate(named[:k] + plain[: n_crew - k]):
        x = EC.load16(s["file"], s["t0"], s["t1"])
        decoys = [e for e in cat if e not in s["gold"]]
        names = s["gold"] + rng.sample(decoys, 20)
        rng.shuffle(names)
        clips.append({"id": f"crew{i:03d}", "set": "crew", "wav": EC.save(out, f"crew{i:03d}", x), "ref": s["ref"],
                      "gold": [e["name"] for e in s["gold"]], "names": names})
    (out / "clips.json").write_text(json.dumps(clips, indent=1))
    print(f"{len(clips)} clips -> {out}: {dict(Counter(c['set'] for c in clips))}")


# ------------------------------------------------------------------------------------------------- run
def rss_mb() -> float:
    import psutil
    return round(psutil.Process().memory_info().rss / 1e6, 1)


def run(model: Path, tag: str, out: Path, threads: int, only: set | None):
    os.environ["ARC_SPACE_DIR"] = str(model)
    os.environ.setdefault("ARC_THREADS", str(threads))
    os.chdir(ROOT / "model_server")
    sys.path.insert(0, str(ROOT / "model_server"))
    rss0 = rss_mb()
    t = time.perf_counter()
    from app import arc_ear, arcmeta
    arcmeta.load()
    if arcmeta.STATE["arc"] is None:
        sys.exit(f"model not loaded: {arcmeta.STATE['error']}")
    info = {"tag": tag, "model": str(model), "load_s": round(time.perf_counter() - t, 2), "rss_before_mb": rss0,
            "rss_after_load_mb": rss_mb(), "files_mb": round(sum(p.stat().st_size for p in model.rglob("*")
                                                                 if p.is_file()) / 1e6, 1)}
    clips = json.loads((out / "clips.json").read_text())
    res, rss_steady = [], []
    t_all = time.perf_counter()
    for c in clips:
        if only and c["set"] not in only:
            continue
        x = np.frombuffer((out / "wav" / c["wav"]).read_bytes(), "<i2")
        x = np.concatenate([x, np.zeros(int(1.5 * SR), "<i2")])
        es = arc_ear.EarStream("assistant")
        es.set_names(c["names"])
        msgs, compute, audio_s = [], 0.0, 0.0
        for i in range(0, len(x), CHUNK):
            ch = x[i:i + CHUNK]
            audio_s += len(ch) / SR
            t = time.perf_counter()
            ms = es.feed_all(ch.tobytes())
            compute += time.perf_counter() - t
            msgs += [{**m, "_at": round(audio_s, 3)} for m in ms]
        t = time.perf_counter()
        msgs += [{**m, "_at": round(audio_s, 3), "_flush": True} for m in es.flush_all()]
        compute += time.perf_counter() - t
        ends = list(es.ends)
        try:
            es.close()
        except Exception:  # noqa: BLE001
            pass
        res.append({"id": c["id"], "set": c["set"], "msgs": msgs, "ends": ends, "compute_s": round(compute, 3),
                    "audio_s": round(len(x) / SR, 3)})
        rss_steady.append(rss_mb())
        fin = " | ".join(m["text"] for m in msgs if m["t"] == "words" and m.get("final"))
        print(f"{tag} {c['id']:16s} {compute / (len(x) / SR):.2f}x {fin[:90]!r}", flush=True)
    info["wall_s"] = round(time.perf_counter() - t_all, 1)
    info["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss /
                                (1e6 if sys.platform == "darwin" else 1e3), 1)
    info["rss_steady_mb"] = {"median": float(np.median(rss_steady)) if rss_steady else None,
                             "max": max(rss_steady) if rss_steady else None}
    info["rtf"] = round(sum(r["compute_s"] for r in res) / max(sum(r["audio_s"] for r in res), 1e-9), 3)
    (out / f"run_{tag}.json").write_text(json.dumps({"info": info, "results": res}))
    print(json.dumps(info))


# ------------------------------------------------------------------------------------------------- compare
def _norm_words(t: str) -> list[str]:
    import ear_compare as EC
    return EC.norm(t).split()


def _edit(a, b) -> int:
    import ear_compare as EC
    return EC.edit(a, b)


def turns_of(msgs: list[dict]) -> list[dict]:
    """The ear's messages grouped per turn: from `turn start` to `turn end` (a final `words` closes it too)."""
    turns, cur = [], None
    for m in msgs:
        t = m.get("t")
        if t == "turn" and m.get("state") == "start":
            cur = {"start_at": m.get("_at"), "partials": [], "final": None, "arc": None, "entity": [], "eot": [],
                   "barge": [], "end_at": None, "other": []}
            turns.append(cur)
            continue
        if cur is None:
            cur = {"start_at": None, "partials": [], "final": None, "arc": None, "entity": [], "eot": [], "barge": [],
                   "end_at": None, "other": []}
            turns.append(cur)
        if t == "words" and m.get("final"):
            cur["final"] = m
        elif t == "words":
            cur["partials"].append(m)
        elif t == "arc":
            cur["arc"] = m
        elif t == "entity":
            cur["entity"].append(m)
        elif t == "eot":
            cur["eot"].append(m)
        elif t == "barge_in":
            cur["barge"].append(m)
        elif t == "turn" and m.get("state") == "end":
            cur["end_at"] = m.get("_at")
            cur = None
        else:
            cur["other"].append(m)
    return turns


def flat(d, pre="") -> dict:
    """Nested dict / list -> {path: scalar}; lists of dicts by index."""
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if k.startswith("_"):
                continue
            out.update(flat(v, f"{pre}.{k}" if pre else k))
    elif isinstance(d, list):
        out[f"{pre}#n"] = len(d)
        for i, v in enumerate(d):
            out.update(flat(v, f"{pre}[{i}]"))
    else:
        out[pre] = d
    return out


TIMING = ("decode_ms", "ms", "wall_ms", "compute", "latency")


def field_agree(pairs: list[tuple[dict, dict]], tol: float = 0.05) -> dict:
    """Over (A message, B message) pairs: per field path, agreement (exact for strings / bools / ints, |delta| <= tol for
    floats), mean |delta| of numeric ones. Timing fields (wall clock) are skipped."""
    agree, n, delta = Counter(), Counter(), defaultdict(list)
    for a, b in pairs:
        fa, fb = flat(a or {}), flat(b or {})
        for k in set(fa) | set(fb):
            if any(t in k for t in TIMING):
                continue
            key = __import__("re").sub(r"\[\d+\]", "[]", k)
            va, vb = fa.get(k), fb.get(k)
            n[key] += 1
            if isinstance(va, float) or isinstance(vb, float):
                if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
                    d = abs(float(va) - float(vb))
                    delta[key].append(d)
                    agree[key] += d <= tol
                else:
                    agree[key] += va == vb
            else:
                agree[key] += va == vb
    return {k: {"n": n[k], "agree": round(agree[k] / n[k], 4),
                **({"mean_abs": round(float(np.mean(delta[k])), 5), "max_abs": round(float(np.max(delta[k])), 5)}
                   if delta.get(k) else {})} for k in sorted(n)}


def name_key(nm: dict) -> tuple:
    return (nm.get("entity"), nm.get("state"))


def match_names(na: list[dict], nb: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """Pair heard names by time overlap (else by order)."""
    out, used = [], set()
    for a in na:
        best, bo = None, 0.0
        for j, b in enumerate(nb):
            if j in used:
                continue
            ov = min(a.get("t1") or 0, b.get("t1") or 0) - max(a.get("t0") or 0, b.get("t0") or 0)
            if ov > bo or (best is None and (a.get("heard") or "").lower() == (b.get("heard") or "").lower()):
                best, bo = j, max(ov, bo)
        if best is not None:
            used.add(best)
            out.append((a, nb[best]))
        else:
            out.append((a, None))
    out += [(None, b) for j, b in enumerate(nb) if j not in used]
    return out


def pctl(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3) if xs else None


def ece(ps: list[float], ok: list[bool], bins: int = 10) -> float | None:
    if not ps:
        return None
    tot = 0.0
    for b in range(bins):
        idx = [i for i, p in enumerate(ps) if (b / bins <= p < (b + 1) / bins) or (b == bins - 1 and p == 1.0)]
        if idx:
            tot += len(idx) * abs(np.mean([ps[i] for i in idx]) - np.mean([ok[i] for i in idx]))
    return round(tot / len(ps), 4)


def app_dd(arc: dict | None) -> float | None:
    return None if not arc else arc.get("device_directed")


def summarize_side(clips: dict, results: list[dict]) -> dict:
    """WER, links vs gold, empties, partial stability, timing for one run."""
    per_set = defaultdict(lambda: {"err": 0, "n": 0, "clips": 0})
    links = Counter()
    lp, lok = [], []
    empties = 0
    nturns = 0
    first_partial, turn_end, n_stable, n_part = [], [], [], 0
    for r in results:
        c = clips.get(r["id"], {})
        ts = turns_of(r["msgs"])
        finals = [t["final"] for t in ts if t["final"]]
        hyp = " ".join(f.get("text") or "" for f in finals)
        nturns += len(ts)
        empties += sum(1 for t in ts if t["final"] is not None and not (t["final"].get("text") or "").strip())
        if c.get("ref") is not None and r["set"] != "orientale":
            ref = _norm_words(c["ref"])
            s = per_set[r["set"]]
            s["err"] += _edit(ref, _norm_words(hyp))
            s["n"] += len(ref)
            s["clips"] += 1
        gold = [g.lower() for g in (c.get("gold") or [])]
        names = [n for f in finals for n in (f.get("names") or [])]
        linked = [n for n in names if n.get("state") == "linked"]
        if c.get("gold") is not None:
            got = {(n.get("entity") or "").lower() for n in linked}
            for g in gold:
                links["gold"] += 1
                links["linked_right"] += g in got
            for n in linked:
                links["linked"] += 1
                ok = (n.get("entity") or "").lower() in gold
                links["linked_wrong"] += not ok
                if n.get("p") is not None:
                    lp.append(float(n["p"]))
                    lok.append(ok)
            links["abstain"] += sum(1 for n in names if n.get("state") == "abstain")
            links["not_in_list"] += sum(1 for n in names if n.get("state") == "not_in_list")
            links["heard"] += len(names)
        for t in ts:
            if t["partials"] and t["start_at"] is not None:
                first_partial.append(t["partials"][0].get("_at", 0) - t["start_at"])
            for p in t["partials"]:
                if p.get("n_stable") is not None:
                    n_stable.append(p["n_stable"])
                n_part += 1
        for e in r.get("ends") or []:
            if e.get("at") is not None and e.get("last_voice") is not None:
                turn_end.append(e["at"] - e["last_voice"])
    out = {"wer": {k: round(v["err"] / max(v["n"], 1), 4) for k, v in per_set.items()},
           "wer_pooled": round(sum(v["err"] for v in per_set.values()) / max(sum(v["n"] for v in per_set.values()), 1), 4),
           "turns": nturns, "empty_finals": empties,
           "links": dict(links), "link_acc": round(links["linked_right"] / max(links["gold"], 1), 4),
           "wrong_link_rate": round(links["linked_wrong"] / max(links["linked"], 1), 4),
           "abstain_rate": round(links["abstain"] / max(links["heard"], 1), 4),
           "not_in_list_rate": round(links["not_in_list"] / max(links["heard"], 1), 4),
           "link_p_ece": ece(lp, lok),
           "partials": n_part, "n_stable_mean": round(float(np.mean(n_stable)), 3) if n_stable else None,
           "first_partial_s": {"p50": pctl(first_partial, .5), "p90": pctl(first_partial, .9)},
           "turn_end_s": {"p50": pctl(turn_end, .5), "p90": pctl(turn_end, .9)}}
    return out


def pair_runs(ra: list[dict], rb: list[dict]) -> dict:
    """Turn-level pairing of two runs over the same clips -> agreement report."""
    bb = {r["id"]: r for r in rb}
    same_nturns, n_clips = 0, 0
    finals, arcs, names_pairs, partial_pairs, words = [], [], [], [], [0, 0]
    text_same, n_final = 0, 0
    empty_flip = 0
    dd_dec = [0, 0]
    dd_abs, dh_abs = [], []
    per_set = defaultdict(lambda: [0, 0])
    diffs = []
    for a in ra:
        b = bb.get(a["id"])
        if b is None:
            continue
        n_clips += 1
        ta, tb = turns_of(a["msgs"]), turns_of(b["msgs"])
        same_nturns += len(ta) == len(tb)
        for x, y in zip(ta, tb):
            fa, fb = x["final"], y["final"]
            if fa or fb:
                n_final += 1
                sa, sb = (fa or {}).get("text") or "", (fb or {}).get("text") or ""
                text_same += sa == sb
                per_set[a["set"]][0] += sa == sb
                per_set[a["set"]][1] += 1
                wa, wb = _norm_words(sa), _norm_words(sb)
                words[0] += _edit(wa, wb)
                words[1] += max(len(wa), 1)
                empty_flip += bool(sa.strip()) != bool(sb.strip())
                if sa != sb and len(diffs) < 40:
                    diffs.append({"id": a["id"], "A": sa, "B": sb})
                finals.append((fa, fb))
                names_pairs += match_names((fa or {}).get("names") or [], (fb or {}).get("names") or [])
            if x["arc"] or y["arc"]:
                arcs.append((x["arc"], y["arc"]))
                da, db = app_dd(x["arc"]), app_dd(y["arc"])
                if da is not None and db is not None:
                    dd_dec[0] += (da >= DD_MIN) == (db >= DD_MIN)
                    dd_dec[1] += 1
                    dd_abs.append(abs(da - db))
                ha, hb = (x["arc"] or {}).get("directed_head"), (y["arc"] or {}).get("directed_head")
                if ha is not None and hb is not None:
                    dh_abs.append(abs(ha - hb))
            for pa, pb in zip(x["partials"], y["partials"]):
                partial_pairs.append((pa, pb))
    nm_same = sum(1 for p, q in names_pairs if p and q and name_key(p) == name_key(q))
    almost = [(p, q) for p, q in names_pairs if (p and p.get("state") == "almost") or (q and q.get("state") == "almost")]
    lp = [abs(p["p"] - q["p"]) for p, q in names_pairs if p and q and p.get("p") is not None and q.get("p") is not None]
    return {"clips": n_clips, "same_turn_count": round(same_nturns / max(n_clips, 1), 4),
            "finals": n_final, "final_text_identical": round(text_same / max(n_final, 1), 4),
            "final_text_identical_by_set": {k: round(v[0] / max(v[1], 1), 4) for k, v in per_set.items()},
            "word_diff_rate": round(words[0] / max(words[1], 1), 4), "empty_flips": empty_flip,
            "names": len(names_pairs), "name_entity_state_identical": round(nm_same / max(len(names_pairs), 1), 4),
            "almost": len(almost), "almost_identical": round(sum(1 for p, q in almost if p and q and
                                                                 p.get("candidate") == q.get("candidate") and
                                                                 p.get("state") == q.get("state")) /
                                                         max(len(almost), 1), 4),
            "link_p_mean_abs": round(float(np.mean(lp)), 4) if lp else None,
            "dd_decision_agree": round(dd_dec[0] / max(dd_dec[1], 1), 4), "dd_turns": dd_dec[1],
            "app_dd_mean_abs": round(float(np.mean(dd_abs)), 4) if dd_abs else None,
            "directed_head_mean_abs": round(float(np.mean(dh_abs)), 4) if dh_abs else None,
            "fields_final": field_agree(finals), "fields_arc": field_agree(arcs),
            "fields_partial": field_agree(partial_pairs), "diffs": diffs}


def compare(out: Path, a: str, b: str, noise: str | None):
    clips = {c["id"]: c for c in json.loads((out / "clips.json").read_text())}
    ra, rb = (json.loads((out / f"run_{t}.json").read_text()) for t in (a, b))
    rep = {"A": {**ra["info"], **summarize_side(clips, ra["results"])},
           "B": {**rb["info"], **summarize_side(clips, rb["results"])},
           "A_vs_B": pair_runs(ra["results"], rb["results"])}
    if noise:
        rn = json.loads((out / f"run_{noise}.json").read_text())
        rep["A_vs_A2"] = pair_runs(ra["results"], rn["results"])
    (out / f"compare_{a}_{b}.json").write_text(json.dumps(rep, indent=1))
    show(rep)


# ------------------------------------------------------------------------------------------------- real_ear caches
def load_cache(d: Path) -> dict:
    out = {}
    for p in (d / "dec").glob("*.json"):
        j = json.loads(p.read_text())
        out[j["key"]] = j
    return out


def cache_as_results(c: dict, keys: list[str]) -> list[dict]:
    """real_ear's compact events (backend/app/director_model/replay.compact) -> the run form turns_of() reads."""
    res = []
    for k in keys:
        j = c[k]
        msgs = []
        for e in j.get("events") or []:
            m = dict(e)
            m["_at"] = e.get("at")
            msgs.append(m)
        fx = (j.get("x") or {}).get("final")
        if fx:        # the final words' ear extras ride next to the compact events
            for m in reversed(msgs):
                if m.get("t") == "words" and m.get("final"):
                    m.update({kk: v for kk, v in fx.items() if kk not in m})
                    break
        res.append({"id": k, "set": j.get("group", "?"), "msgs": msgs, "ends": (j.get("x") or {}).get("ends") or [],
                    "x": j.get("x") or {}, "hyp": j.get("hyp", ""), "text": j.get("text", "")})
    return res


def compare_cache(a: Path, b: Path, noise: Path | None, out: Path | None):
    ca, cb = load_cache(a), load_cache(b)
    keys = sorted(set(ca) & set(cb))
    ra, rb = cache_as_results(ca, keys), cache_as_results(cb, keys)
    clips = {k: {"ref": ca[k].get("text") or "", "gold": None} for k in keys if ca[k].get("group") != "echo_bank"}
    rep = {"keys": len(keys), "A": summarize_side(clips, ra), "B": summarize_side(clips, rb),
           "A_vs_B": pair_runs(ra, rb)}
    # the extras real_ear keeps per clip: names (all finals), spoken, tags, audio events, directed head
    xa = [(x["x"], y["x"]) for x, y in zip(ra, rb)]
    rep["A_vs_B"]["fields_x"] = field_agree([({k: v for k, v in p.items() if k not in ("ends", "audio_s")},
                                              {k: v for k, v in q.items() if k not in ("ends", "audio_s")}) for p, q in xa])
    eb = [(x, y) for x, y in zip(ra, rb) if x["set"] == "echo_bank"]
    if eb:
        words_in = [sum(1 for t in turns_of(r["msgs"]) if t["final"] and (t["final"].get("text") or "").strip())
                    for r, _ in eb]
        words_in_b = [sum(1 for t in turns_of(r["msgs"]) if t["final"] and (t["final"].get("text") or "").strip())
                      for _, r in eb]
        rep["echo_bank"] = {"clips": len(eb), "A_clips_with_words": sum(1 for w in words_in if w),
                            "B_clips_with_words": sum(1 for w in words_in_b if w)}
    if noise:
        cn = load_cache(noise)
        kn = sorted(set(ca) & set(cn))
        rep["A_vs_A2"] = pair_runs(cache_as_results(ca, kn), cache_as_results(cn, kn))
    if out:
        out.write_text(json.dumps(rep, indent=1))
    show(rep)


def show(rep: dict):
    for side in ("A", "B"):
        s = rep[side]
        print(f"{side}: WER {s['wer']} pooled {s['wer_pooled']}; turns {s['turns']} empty {s['empty_finals']}; links "
              f"acc {s['link_acc']} wrong {s['wrong_link_rate']} abstain {s['abstain_rate']} nil {s['not_in_list_rate']}"
              f" ece {s['link_p_ece']}; partials {s['partials']} n_stable {s['n_stable_mean']}; first partial "
              f"{s['first_partial_s']}; turn end {s['turn_end_s']}"
              + (f"; rtf {s.get('rtf')} load {s.get('load_s')} rss load {s.get('rss_after_load_mb')} steady "
                 f"{s.get('rss_steady_mb')} files {s.get('files_mb')} MB" if 'rtf' in s else ""))
    for k in ("A_vs_B", "A_vs_A2"):
        if k not in rep:
            continue
        p = rep[k]
        print(f"{k}: same turn count {p['same_turn_count']}; final text identical {p['final_text_identical']} "
              f"({p['final_text_identical_by_set']}); word diff {p['word_diff_rate']}; empty flips "
              f"{p['empty_flips']}; names (entity,state) identical {p['name_entity_state_identical']} of "
              f"{p['names']}; almost identical {p['almost_identical']} of {p['almost']}; link p |d| "
              f"{p['link_p_mean_abs']}; dd decision {p['dd_decision_agree']} of {p['dd_turns']}; app_dd |d| "
              f"{p['app_dd_mean_abs']}; head |d| {p['directed_head_mean_abs']}")
        for grp in ("fields_final", "fields_arc", "fields_partial", "fields_x"):
            low = {f: v for f, v in (p.get(grp) or {}).items() if v["agree"] < 0.97 and v["n"] >= 5}
            print(f"  {grp}: {len(p.get(grp) or {})} fields, under 97%: "
                  + ", ".join(f"{f}={v['agree']}(n{v['n']})" for f, v in sorted(low.items())[:30]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--crew", type=int, default=60)
    r = sub.add_parser("run")
    r.add_argument("--model", type=Path, required=True)
    r.add_argument("--tag", required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--threads", type=int, default=2)
    r.add_argument("--only", default="")
    c = sub.add_parser("compare")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--noise")
    cc = sub.add_parser("compare-cache")
    cc.add_argument("a", type=Path)
    cc.add_argument("b", type=Path)
    cc.add_argument("--noise", type=Path)
    cc.add_argument("--json", type=Path)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.out, a.crew)
    elif a.cmd == "run":
        run(a.model, a.tag, a.out, a.threads, set(x for x in a.only.split(",") if x) or None)
    elif a.cmd == "compare":
        compare(a.out, a.a, a.b, a.noise)
    else:
        compare_cache(a.a, a.b, a.noise, a.json)


if __name__ == "__main__":
    main()
