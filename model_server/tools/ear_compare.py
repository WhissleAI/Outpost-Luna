"""Old ear vs new ear on the same REAL audio (docs/LOCAL_EAR.md "Arc Transcriber Space"): WER, name links, false turns
and false device-directed on room noise, echo of the app's own voice, turn-end and first-word latency, RTF, RAM, load.

    # 1. build the clip set once (16 kHz wavs + refs + names lists) into OUT
    python tools/ear_compare.py build --out OUT
    # 2. run each ear in its own process (one model in memory at a time)
    .venv/bin/python tools/ear_compare.py run --ear new --out OUT                       # this checkout (libarc)
    <old venv>/bin/python tools/ear_compare.py run --ear old --app-root <origin/main model_server> --out OUT
    # 3. the table
    python tools/ear_compare.py report --out OUT

Sets (all real recordings; synthetic speech is kept apart in `tts`, since the new model ignores TTS on purpose):
    crew     Artemis II crew audio (backend/data/media/audio), cut at pauses into 3-12 s segments; reference = the
             Deepgram nova-3 words in backend/data/index/clips.json (a machine reference, not human-checked); names list
             = the catalogue names said in the segment + 20 decoys (backend/app/names_list.py)
    libri    LibriSpeech test-clean (real read adult speech, human references), if on this machine (LIBRI_DIR)
    slurp    SLURP test (real people speaking commands to a device, headset + far-field; human refs), if present
    noise    real room-noise beds (cabin, cafe, room recordings; NOISE_DIR): no speech for the app
    echo     the app's own voice: the recorded Nora voice-pack clips + the macOS OS voice (`say -o`, never played)
    tts      the old synthetic ear fixtures (steer-tts voices, backend/tests/fixtures/ear_eval), for the record only
Each clip is fed in 80 ms chunks as fast as the ear runs, then 1.5 s of silence and stop. Latency = audio time between
the VAD's last voiced chunk and the chunk whose processing produced the final, plus that call's compute.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend/data"
SR, CHUNK = 16000, 1280
LIBRI = Path(os.environ.get("LIBRI_DIR", Path.home() / "dv3work/arc/data/evalset"))
SLURP_AUDIO = Path(os.environ.get("SLURP_DIR", Path.home() / "dv3work/arc_benchmarks/audio/slurp600"))
SLURP_REF = Path(os.environ.get("SLURP_REF", Path.home() / "dv3work/arc_benchmarks/data/slurp_manifest600.jsonl"))
NOISE = Path(os.environ.get("NOISE_DIR", Path.home() / "dv3work/assets/noise/audit/wav"))
DD_MIN = 0.5    # backend/app/turn_router.py DD_MIN: under it, "talking to someone else"


# ------------------------------------------------------------------------------------------------- text
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen " \
       "eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if 1100 <= n <= 1999 or 2010 <= n <= 2099:       # years read as years
        return num_words(n // 100) + " " + (num_words(n % 100) if n % 100 >= 10 else
                                           ("hundred" if n % 100 == 0 else "oh " + ONES[n % 100]))
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + num_words(n % 100))
    if n < 1_000_000:
        return num_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + num_words(n % 1000))
    return " ".join(ONES[int(c)] for c in str(n))


def norm(t: str) -> str:
    t = (t or "").lower().replace("%", " percent").replace("&", " and ")
    t = re.sub(r"(\d),(\d)", r"\1\2", t)
    t = re.sub(r"\d+", lambda m: " " + num_words(int(m.group())) + " ", t)
    t = re.sub(r"[^a-z' ]+", " ", t).replace("'", "")
    return re.sub(r"\s+", " ", t).strip()


def edit(a: list[str], b: list[str]) -> int:
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(b)]


# ------------------------------------------------------------------------------------------------- build
def load16(path: Path, t0: float = 0.0, t1: float | None = None) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t0), *(["-to", str(t1)] if t1 else []), "-i",
                          str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, check=True)
    return np.frombuffer(out.stdout, "<i2").copy()


def save(out: Path, cid: str, x: np.ndarray) -> str:
    (out / "wav").mkdir(parents=True, exist_ok=True)
    p = out / "wav" / f"{cid}.s16le"
    p.write_bytes(x.astype("<i2").tobytes())
    return p.name


def catalogue():
    sys.path.insert(0, str(ROOT / "backend"))
    from app.names_list import catalogue_names, screen_names
    return catalogue_names(), screen_names


def gold_names(ref: str, cat: list[dict]) -> list[dict]:
    r = f" {norm(ref)} "
    hits = []
    for e in cat:
        forms = [e["name"], *(e.get("aliases") or [])]
        if any(len(norm(f)) >= 4 and f" {norm(f)} " in r for f in forms):
            hits.append(e)
    # the longest wins when one name contains another ("Orientale Basin" vs "Orientale")
    return [e for e in hits if not any(o is not e and norm(e["name"]) in norm(o["name"]) and norm(o["name"]) in r
                                         for o in hits)]


def build(out: Path, n_crew: int, n_libri: int, n_slurp: int, n_echo: int):
    rng = random.Random(7)
    cat, screen_names = catalogue()
    clips = []
    # crew: segments at pauses >= 0.8 s, 3-12 s, >= 5 words
    idx = json.loads((DATA / "index/clips.json").read_text())["clips"]
    named, plain = [], []
    for c in idx:
        f = DATA / "media/audio" / Path(c["file"]).name
        if not f.exists() or not c.get("words"):
            continue
        ws = c["words"]           # [t0, word, speaker, t1]
        seg = [ws[0]]
        for w in ws[1:] + [None]:
            if w is None or w[0] - seg[-1][3] >= 0.8 or w[3] - seg[0][0] > 12:
                t0, t1 = seg[0][0], seg[-1][3]
                if 3 <= t1 - t0 <= 12 and len(seg) >= 5:
                    ref = " ".join(x[1] for x in seg)
                    g = gold_names(ref, cat)
                    (named if g else plain).append({"file": f, "t0": max(0, t0 - 0.3), "t1": t1 + 0.3, "ref": ref,
                                                     "gold": g, "src": c["id"]})
                seg = [w] if w else []
            else:
                seg.append(w)
    rng.shuffle(named)
    rng.shuffle(plain)
    k = min(len(named), n_crew * 3 // 5)
    for i, s in enumerate(named[:k] + plain[: n_crew - k]):
        x = load16(s["file"], s["t0"], s["t1"])
        decoys = [e for e in cat if e not in s["gold"]]
        names = s["gold"] + rng.sample(decoys, 20)
        rng.shuffle(names)
        clips.append({"id": f"crew{i:03d}", "set": "crew", "wav": save(out, f"crew{i:03d}", x), "ref": s["ref"],
                      "gold": [e["name"] for e in s["gold"]], "names": names, "src": s["src"]})
    base = screen_names({"screen": "map"})
    if (LIBRI / "refs.tsv").exists():
        rows = [ln.split("\t") for ln in (LIBRI / "refs.tsv").read_text().splitlines() if "\t" in ln]
        for i, (uid, ref) in enumerate(rng.sample(rows, min(n_libri, len(rows)))):
            x = load16(LIBRI / "clean" / f"{uid}.wav")
            clips.append({"id": f"libri{i:03d}", "set": "libri", "wav": save(out, f"libri{i:03d}", x), "ref": ref,
                          "names": base})
    if SLURP_REF.exists() and SLURP_AUDIO.exists():
        rows = [json.loads(ln) for ln in SLURP_REF.read_text().splitlines() if ln.strip()]
        rows = [r for r in rows if (SLURP_AUDIO / (r["id"].replace("slurp_test_", "") + ".flac")).exists()]
        for i, r in enumerate(rng.sample(rows, min(n_slurp, len(rows)))):
            x = load16(SLURP_AUDIO / (r["id"].replace("slurp_test_", "") + ".flac"))
            clips.append({"id": f"slurp{i:03d}", "set": "slurp", "wav": save(out, f"slurp{i:03d}", x), "ref": r["text"],
                          "device": r.get("device"), "names": base})
    for i, f in enumerate(sorted(NOISE.glob("*.wav")) if NOISE.exists() else []):
        x = load16(f, 0, 8)
        x = (x.astype(np.float32) * (10 ** (-30 / 20) / max(1e-6, np.sqrt(np.mean((x / 32768.0) ** 2))))).clip(
            -32768, 32767)  # -30 dBFS RMS, a typical in-session level
        clips.append({"id": f"noise{i:03d}", "set": "noise", "wav": save(out, f"noise{i:03d}", x), "ref": "",
                      "bed": f.stem, "names": base})
    vp = json.loads((DATA / "voice_pack/index.json").read_text())["clips"]
    lines = rng.sample(sorted(vp.values(), key=lambda c: c["file"]), min(n_echo, len(vp)))
    for i, c in enumerate(lines):
        x = load16(DATA / "voice_pack" / c["file"])
        clips.append({"id": f"echo{i:03d}", "set": "echo", "wav": save(out, f"echo{i:03d}", x), "ref": c["text"],
                      "voice": "nora_pack", "names": base})
    say_lines = ["Copy that. Shields are up twenty percent.", "Welcome back, cadet. Where shall we fly today?",
                 "That's the Sea of Tranquility, where Apollo 11 landed.", "Hold on, a solar storm is coming.",
                 "Great answer! Next lesson?", "Artemis two flew around the far side of the Moon.",
                 "Say take command when you are ready.", "The rover is heading to Shackleton crater.",
                 "Do you want to watch the video?", "Houston, we copy. Battery at eighty percent."]
    if sys.platform == "darwin":
        tmp = out / "say.aiff"
        for i, t in enumerate(say_lines):
            subprocess.run(["say", "-o", str(tmp), t], check=True)        # rendered to a file, never played
            x = load16(tmp)
            clips.append({"id": f"say{i:03d}", "set": "echo", "wav": save(out, f"say{i:03d}", x), "ref": t,
                          "voice": "os_say", "names": base})
        tmp.unlink(missing_ok=True)
    tts = ROOT / "backend/tests/fixtures/ear_eval"
    man = json.loads((tts / "manifest.json").read_text()) if (tts / "manifest.json").exists() else {}
    refs = {c["id"]: c for c in json.loads((tts / "set.json").read_text())["items"]} if (tts / "set.json").exists() else {}
    wavdir = tts / "audio"          # rendered by its render.py (gitignored): skipped when absent
    for c in (man.get("clips") or [])[:24]:
        p = wavdir / f"{c['clip']}.wav"
        if p.exists() and c["id"] in refs:
            clips.append({"id": f"tts_{c['clip']}", "set": "tts", "wav": save(out, f"tts_{c['clip']}", load16(p)),
                          "ref": refs[c["id"]].get("text", ""), "names": base})
    (out / "clips.json").write_text(json.dumps(clips, indent=1))
    from collections import Counter
    print(f"{len(clips)} clips -> {out}: {dict(Counter(c['set'] for c in clips))}")


# ------------------------------------------------------------------------------------------------- run
def rss_mb():
    import psutil
    return round(psutil.Process().memory_info().rss / 1e6, 1)


def peak_mb():
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e6 if sys.platform == "darwin" else 1e3), 1)


def run(ear: str, out: Path, app_root: Path | None, only: set | None):
    root = app_root or ROOT / "model_server"
    sys.path.insert(0, str(root))
    os.chdir(root)
    rss0 = rss_mb()
    t = time.perf_counter()
    from app import arc_ear, arcmeta
    arcmeta.load()
    load_s = time.perf_counter() - t
    if arcmeta.STATE["arc"] is None:
        sys.exit(f"{ear}: model not loaded: {arcmeta.STATE['error']}")
    info = {"ear": ear, "load_s": round(load_s, 2), "rss_before_mb": rss0, "rss_after_load_mb": rss_mb()}
    clips = json.loads((out / "clips.json").read_text())
    res = []
    vad_cls = arc_ear.Vad
    for c in clips:
        if only and c["set"] not in only:
            continue
        x = np.frombuffer((out / "wav" / c["wav"]).read_bytes(), "<i2")
        x = np.concatenate([x, np.zeros(int(1.5 * SR), "<i2")])
        es = arc_ear.EarStream("assistant")
        if ear == "old":
            es.set_decoder_context(names=[n["name"] for n in c["names"]])
        else:
            es.set_names(c["names"])
        vad = vad_cls()
        msgs, onset, last_voice, finals, first_word = [], None, None, [], None
        dd_seen, compute = [], 0.0
        audio_s = 0.0
        for i in range(0, len(x), CHUNK):
            ch = x[i:i + CHUNK]
            audio_s += len(ch) / SR
            q = vad.quiet(ch.astype(np.float32) / 32768.0)
            if not q:
                last_voice = audio_s
                onset = onset if onset is not None else audio_s - len(ch) / SR
            t = time.perf_counter()
            ms = es.feed_all(ch.tobytes())
            dt = time.perf_counter() - t
            compute += dt
            for m in ms:
                if m["t"] == "arc" and m.get("device_directed") is not None:
                    dd_seen.append(m["device_directed"])
                if m["t"] == "words" and m.get("text") and first_word is None and onset is not None:
                    first_word = audio_s - onset + dt
                if m["t"] == "words" and m.get("final"):
                    finals.append({"text": m["text"], "names": m.get("names"),
                                   "lat": (audio_s - (last_voice or audio_s)) + dt})
            msgs += ms
        t = time.perf_counter()
        ms = es.flush_all()
        compute += time.perf_counter() - t
        for m in ms:
            if m["t"] == "words" and m.get("final"):
                finals.append({"text": m["text"], "names": m.get("names"), "lat": None})
            if m["t"] == "arc" and m.get("device_directed") is not None:
                dd_seen.append(m["device_directed"])
        try:
            es.close()
        except Exception:  # noqa: BLE001
            pass
        hyp = " ".join(f["text"] for f in finals).strip()
        res.append({"id": c["id"], "set": c["set"], "hyp": hyp, "finals": finals, "first_word_s": first_word,
                    "dd": dd_seen, "turns": len(finals), "compute_s": round(compute, 3),
                    "audio_s": round(len(x) / SR, 3)})
        print(f"{ear} {c['id']:10s} {compute / (len(x) / SR):.2f}x  {hyp[:80]!r}", flush=True)
    info["peak_rss_mb"] = peak_mb()
    info["rss_end_mb"] = rss_mb()
    (out / f"results_{ear}.json").write_text(json.dumps({"info": info, "results": res}, indent=1))
    print(json.dumps(info))


# ------------------------------------------------------------------------------------------------- report
def report(out: Path):
    clips = {c["id"]: c for c in json.loads((out / "clips.json").read_text())}
    rows = {}
    for ear in ("old", "new"):
        p = out / f"results_{ear}.json"
        if p.exists():
            rows[ear] = json.loads(p.read_text())
    table = {}
    for ear, R in rows.items():
        rs = R["results"]
        t = {"info": R["info"]}
        for st in ("crew", "libri", "slurp", "tts"):
            xs = [r for r in rs if r["set"] == st]
            if not xs:
                continue
            e = n = 0
            for r in xs:
                ref, hyp = norm(clips[r["id"]]["ref"]).split(), norm(r["hyp"]).split()
                e += edit(ref, hyp)
                n += len(ref)
            t[f"wer_{st}"] = round(100 * e / max(1, n), 1)
            t[f"empty_{st}"] = sum(not r["hyp"] for r in xs)
            t[f"n_{st}"] = len(xs)
        sl = [r for r in rs if r["set"] == "slurp"]
        if sl:
            t["slurp_directed"] = round(100 * sum(bool(r["dd"]) and max(r["dd"]) >= DD_MIN for r in sl) / len(sl), 1)
        cr = [r for r in rs if r["set"] == "crew"]
        if cr:
            t["crew_directed"] = round(100 * sum(bool(r["dd"]) and max(r["dd"]) >= DD_MIN for r in cr) / len(cr), 1)
        # names (crew segments with a catalogue name said)
        ok = ab = wrong = miss = fl = tot = 0
        for r in cr:
            gold = clips[r["id"]]["gold"]
            if not gold and ear == "old":
                continue
            names = clips[r["id"]]["names"]
            hn = f" {norm(r['hyp'])} "
            if ear == "new":
                linked = {n["entity"] for f in r["finals"] for n in (f.get("names") or []) if n["state"] == "linked"}
                abst = sum(n["state"] == "abstain" for f in r["finals"] for n in (f.get("names") or []))
            else:
                linked = {e["name"] for e in names
                          if any(len(norm(x)) >= 4 and f" {norm(x)} " in hn for x in [e["name"], *(e.get("aliases") or [])])}
                abst = 0
            for g in gold:
                tot += 1
                if g in linked:
                    ok += 1
                elif abst:
                    ab += 1
                else:
                    miss += 1
            wrong += len([e for e in linked if e not in gold])
            fl += 0
        if tot:
            t["names_total"] = tot
            t["names_correct_pct"] = round(100 * ok / tot, 1)
            t["names_abstain_pct"] = round(100 * ab / tot, 1)
            t["names_missed_pct"] = round(100 * miss / tot, 1)
            t["names_wrong_links"] = wrong
        nz = [r for r in rs if r["set"] == "noise"]
        if nz:
            t["noise_false_turns"] = f"{sum(r['turns'] > 0 for r in nz)}/{len(nz)}"
            t["noise_false_directed"] = f"{sum(bool(r['dd']) and max(r['dd']) >= DD_MIN for r in nz)}/{len(nz)}"
        ec = [r for r in rs if r["set"] == "echo"]
        if ec:
            for v in ("nora_pack", "os_say"):
                xs = [r for r in ec if clips[r["id"]].get("voice") == v]
                if xs:
                    t[f"echo_{v}_transcribed"] = f"{sum(bool(r['hyp']) for r in xs)}/{len(xs)}"
        lat = [f["lat"] for r in rs if r["set"] in ("libri", "slurp", "crew") for f in r["finals"] if f["lat"] is not None]
        fw = [r["first_word_s"] for r in rs if r["set"] in ("libri", "slurp") and r["first_word_s"] is not None]
        if lat:
            t["turn_end_ms_p50"], t["turn_end_ms_p90"] = (round(1000 * float(np.percentile(lat, q))) for q in (50, 90))
        if fw:
            t["first_word_ms_p50"], t["first_word_ms_p90"] = (round(1000 * float(np.percentile(fw, q))) for q in (50, 90))
        sp = [r for r in rs if r["set"] in ("libri", "slurp", "crew")]
        t["rtf"] = round(sum(r["compute_s"] for r in sp) / max(1e-9, sum(r["audio_s"] for r in sp)), 3)
        table[ear] = t
    (out / "report.json").write_text(json.dumps(table, indent=1))
    keys = sorted({k for t in table.values() for k in t if k != "info"})
    print(f"{'metric':28s} " + " ".join(f"{e:>14s}" for e in table))
    for k in ["load_s", "rss_after_load_mb", "peak_rss_mb"]:
        print(f"{k:28s} " + " ".join(f"{str(t['info'].get(k)):>14s}" for t in table.values()))
    for k in keys:
        print(f"{k:28s} " + " ".join(f"{str(t.get(k)):>14s}" for t in table.values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("build", "run", "report"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ear", choices=("old", "new"))
    ap.add_argument("--app-root", type=Path)
    ap.add_argument("--only")
    ap.add_argument("--crew", type=int, default=45)
    ap.add_argument("--libri", type=int, default=40)
    ap.add_argument("--slurp", type=int, default=60)
    ap.add_argument("--echo", type=int, default=30)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "build":
        build(a.out, a.crew, a.libri, a.slurp, a.echo)
    elif a.cmd == "run":
        run(a.ear, a.out, a.app_root, set(a.only.split(",")) if a.only else None)
    else:
        report(a.out)


if __name__ == "__main__":
    main()
