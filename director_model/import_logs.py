"""Turn the on-device turn logs (backend/app/turnlog.py) into labelled training turns (docs/DIRECTOR_LOOP.md).

    make director-import LOG=path/to/turnlog            # a folder (turns.jsonl + turns.1.jsonl), files, or a playtest
    python3 director_model/import_logs.py --log ~/Downloads/turnlog --log outpost-luna-playtest-2026-11-19.zip

Reads turn log v1 (0.3-0.4.2) and v2 (0.4.3: the ear's read-out, what the Director saw, pass / undo signals) lines,
and a grown-up's "Export playtest" zip (backend/app/playtest.py: the turn log + playtest/<turn id>.wav + manifest.json;
members are read by name, never extracted as paths).
Writes
  director_model/data/real_turns.json     every usable turn with a weak (or reviewed) gold act, its screen frame,
                                          Arc's device_directed, (v2) the ear's read-out to replay on the final words,
                                          split train / val / test by a hash of the words
  director_model/data/review/review.jsonl the low-confidence turns for a person to correct: set "fix" to one of
                                          ignore | answer | command | navigate | ask_clarify | nudge | skip, then
                                          move (or copy) the line into reviewed.jsonl; the next import applies it
  director_model/data/real_audio/<zip>/   a playtest's clips (wav) + clips.jsonl: each with its turn's gold, frame and
                                          the screen it was said on; the re-test set's input
Real-turn re-test set (playtest audio through the real Arc ear, held out from training):
    cd model_server && uv run python ../director_model/import_logs.py decode --audio ../director_model/data/real_audio/<zip>
    python3 director_model/import_logs.py retest       # -> data/real_retest.json (gen_sessions: test_log_audio)
Weak labels come from the outcome signals the app logged after each turn (turnlog.py):
  * an ignored turn the kid REPEATED and the repeat was acted on      -> the repeat's act (the ignore was wrong)
  * an acted turn followed by "no" / "stop" / "back" / a cancelled confirm / an undone order / a lesson hint on
    chatter                                                            -> ignore (short / not directed) or ask_clarify
  * an acted turn the kid repeated (same outcome)                      -> low confidence (we may have misheard)
  * a lesson answer that went to hint                                  -> nudge (a wrong answer) unless it was chatter
  * a lesson answer that passed right after (v2 `pass`)                -> answer, confidence 0.9
  * no signal                                                          -> what the app did (weak positive)
Guard turns ("<private>") and anything still carrying a redaction tag are never imported as text to learn (and a
private turn never has audio).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
REVIEW = DATA / "review"
OUT = DATA / "real_turns.json"
AUDIO = DATA / "real_audio"
RETEST = DATA / "real_retest.json"
ZIP_LOG = re.compile(r"^turns(\.1)?\.jsonl$")
ZIP_WAV = re.compile(r"^playtest/([0-9a-f]{8}-\d{1,6})\.wav$")
REVIEW_MIN = 0.6           # below this confidence a turn goes to review instead of training
ACTS = ("ignore", "answer", "command", "navigate", "ask_clarify", "nudge", "confirm_yes", "confirm_no")
CHATTER = re.compile(r"^(?:oh|okay|ok|alright|yeah|yep|um|uh|hmm|wait|so|it s|its|it|the|a|oh it s|oh it s the|"
                     r"oh okay|okay okay|alright alright|oh wait|oh cool|oh nice|hold on|one sec)(?: \w+)?$")
ACT_OF_FINAL = {"ignore": "ignore", "navigate": "navigate", "answer": "answer", "command": "command",
                "confirm_yes": "confirm_yes", "confirm_no": "confirm_no", "ask_clarify": "ask_clarify", "guard": None,
                "nudge": "nudge", "alert": None, "wait": None}


def files_of(paths: list[str]) -> list:
    """Log sources: .jsonl paths, and for a playtest zip, (zip path, member name) pairs of its turn log files."""
    out: list = []
    for p in paths:
        for x in p.split(","):
            x = Path(x).expanduser()
            if x.is_dir():
                out += [f for f in (x / "turns.1.jsonl", x / "turns.jsonl") if f.exists()]
                out += sorted(f for f in x.glob("*.jsonl") if f.name not in ("turns.jsonl", "turns.1.jsonl"))
                out += sorted(x.glob("*.zip"))
            elif x.exists():
                out.append(x)
    res: list = []
    for f in out:
        if isinstance(f, Path) and f.suffix == ".zip":
            with zipfile.ZipFile(f) as z:
                names = z.namelist()
            res += [(f, n) for n in ("turns.1.jsonl", "turns.jsonl") if n in names]
        else:
            res.append(f)
    return res


def lines_of(src):
    if isinstance(src, tuple):
        with zipfile.ZipFile(src[0]) as z:
            yield from z.read(src[1]).decode("utf-8", "replace").splitlines()
        return
    with open(src, encoding="utf-8") as fh:
        yield from fh


def zips_of(files: list) -> list[Path]:
    return sorted({f[0] for f in files if isinstance(f, tuple)})


def read(files: list) -> tuple[list[dict], dict]:
    turns, sigs = [], defaultdict(list)
    for f in files:
        for line in lines_of(f):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue          # a torn last line (the app was closed mid-write)
            if not isinstance(r, dict):
                continue
            if r.get("k") == "turn" and r.get("id"):
                turns.append(r)
            elif r.get("k") == "signal" and r.get("ref"):
                sigs[r["ref"]].append(r)
    seen, uniq = set(), []
    for t in turns:              # the same log handed over twice
        if t["id"] not in seen:
            seen.add(t["id"])
            uniq.append(t)
    return uniq, sigs


def final_act(t: dict) -> str | None:
    d = t.get("director") or {}
    f = d.get("final")
    if f:
        return ACT_OF_FINAL.get(f, f)
    return {"ignore": "ignore", "navigate": "navigate", "answer": "answer"}.get((t.get("router") or {}).get("outcome"))


def weak_label(t: dict, sigs: list[dict], by_id: dict) -> tuple[str | None, float, str]:
    """-> (gold act, confidence 0..1, why)."""
    act = final_act(t)
    kinds = {s["sig"] for s in sigs}
    text = t.get("text") or ""
    dd = (t.get("arc") or {}).get("dd")
    chatter = bool(CHATTER.match(text)) or t.get("nw", 9) <= 1 and (t.get("router") or {}).get("outcome") == "answer"
    if act is None:
        return None, 0.0, "no decision"
    if act == "ignore":
        rep = [s for s in sigs if s["sig"] == "repeat"]
        if rep:
            nxt = by_id.get(rep[0].get("by"))
            na = final_act(nxt) if nxt else None
            if na and na != "ignore" and not {s["sig"] for s in rep_sigs(nxt, by_id)} & {"negate", "confirm_cancel"}:
                return na, 0.75, "ignored, then repeated and acted on"
            return "ignore", 0.4, "ignored and repeated, the repeat was not taken either"
        return "ignore", 0.8 if (dd is not None and dd < 0.5) or chatter else 0.65, "ignored, no complaint"
    neg = kinds & {"negate", "confirm_cancel", "retap", "undo"}
    if act == "answer" and "pass" in kinds and "hint" not in kinds:
        return "answer", 0.9, "a lesson answer that passed"
    if act == "answer" and "hint" in kinds:
        if chatter:
            return "ignore", 0.75, "chatter graded as a lesson answer (went to hint)"
        return "nudge", 0.6, "a wrong lesson answer"
    if neg:
        if chatter or (dd is not None and dd < 0.5):
            return "ignore", 0.6, f"acted, then {sorted(neg)}: chatter / not directed"
        return "ask_clarify", 0.45, f"acted, then {sorted(neg)}"
    if "repeat" in kinds:
        return act, 0.45, "acted, then repeated (maybe misheard)"
    if "confirm_yes" in kinds:
        return act, 0.9, "confirmed"
    return act, 0.7, "acted, no complaint"


def rep_sigs(t: dict, by_id: dict) -> list[dict]:
    return t.get("_sigs") or []


def split_of(text: str) -> str:
    x = int(hashlib.md5(("log:" + text).encode()).hexdigest()[:8], 16) % 100
    return "test" if x < 15 else "val" if x < 25 else "train"


def load_reviewed() -> dict:
    out = {}
    f = REVIEW / "reviewed.jsonl"
    if f.exists():
        for line in open(f):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("fix") in (*ACTS, "skip"):
                out[r["id"]] = r["fix"]
    return out


def to_item(t: dict, act: str, conf: float, why: str) -> dict:
    fr = t.get("frame") or {}
    dd = (t.get("arc") or {}).get("dd")
    it = {"text": t["text"], "heard": t["text"], "cat": "log_" + act, "root": "log:" + t["text"],
          "gold": {"act": act}, "conf": round(conf, 2), "why": why, "id": t["id"], "split": split_of(t["text"]),
          "frame": {"screen": fr.get("screen") or "map", "step_type": fr.get("step_type"),
                    "step_options": fr.get("options") or [], "offer": fr.get("offer"),
                    "lesson_id": fr.get("lesson_id"), "step": fr.get("step")}}
    if dd is not None:
        it["dd"] = (max(0.0, dd - 0.02), min(1.0, dd + 0.02))
    if act == "command":
        it["gold"] = {"act": "command"}      # the Command itself comes from the clean teacher at generation
    rt = t.get("router") or {}
    if act == "navigate" and rt.get("outcome") == "navigate" and rt.get("intent"):
        it["gold"]["nav"] = rt["intent"]       # round 8: which navigation (the nav head's label)
    if t.get("gesture"):
        it["gesture"] = t["gesture"]          # round 8: replayed as a gesture next to the turn
    ear = ear_replay(t.get("ear"))
    if ear:
        it["ear"] = ear                       # v2: the ear's read-out, replayed on the final words (e13_* live)
    cls = (t.get("seen") or {}).get("cls")
    if cls:
        it["situ_live"] = cls
    if t.get("wav"):
        it["wav"] = t["wav"]
    return it


def ear_replay(e) -> dict | None:
    """A v2 turn's `ear` (turnlog.ear_view: numbers and enums) -> the session's k["ear"] form the generator posts on
    the final words, so features.abi2_view / link_view read what they read live (names keep p / state / kind but no
    entity; an almost match gets a placeholder candidate)."""
    if not isinstance(e, dict) or not e:
        return None
    out = {k: e[k] for k in ("uconf", "min_wconf", "eot", "playback_leak", "playback", "barge", "barge_p", "speech_s",
                             "max_pause_s", "end_silence_s", "conf", "agree", "rescored") if e.get(k) is not None}
    if isinstance(e.get("names"), list):
        out["names"] = [{"p": n.get("p"), "state": n.get("state"), "kind": n.get("kind")}
                        for n in e["names"] if isinstance(n, dict)]
    if e.get("almost"):
        out["almost"] = [{"candidate": "<name>", "p": a.get("p")} for a in e["almost"] if isinstance(a, dict)]
    if e.get("qty"):
        out["quantities"] = [{"type": q.get("kind"), "value": q.get("value")} for q in e["qty"] if isinstance(q, dict)]
    if e.get("disfl"):
        out["disfl"] = [{"kind": "x"}] * int(e["disfl"])
    if e.get("dropped"):
        out["n_dropped"] = int(e["dropped"])
    return out


def run(files: list, out: Path = OUT, review_dir: Path = REVIEW, quiet: bool = False, audio_dir: Path = AUDIO) -> dict:
    turns, sigs = read(files)
    by_id = {t["id"]: t for t in turns}
    for t in turns:
        t["_sigs"] = sigs.get(t["id"], [])
    reviewed = load_reviewed() if review_dir == REVIEW else {}
    if review_dir != REVIEW and (review_dir / "reviewed.jsonl").exists():
        for line in open(review_dir / "reviewed.jsonl"):
            r = json.loads(line)
            if r.get("fix") in (*ACTS, "skip"):
                reviewed[r["id"]] = r["fix"]
    items, review, st = [], [], Counter()
    for t in turns:
        text = t.get("text") or ""
        if t.get("guard") or not text or "<" in text:      # private / redacted: never learned as text
            st["skipped_private"] += 1
            continue
        if t["id"] in reviewed:
            if reviewed[t["id"]] == "skip":
                st["reviewed_skip"] += 1
                continue
            items.append(to_item(t, reviewed[t["id"]], 1.0, "reviewed"))
            st["reviewed"] += 1
            continue
        act, conf, why = weak_label(t, t["_sigs"], by_id)
        if act is None:
            st["no_decision"] += 1
            continue
        if conf < REVIEW_MIN:
            review.append({"id": t["id"], "text": text, "frame": t.get("frame"), "router": t.get("router"),
                           "director": t.get("director"), "dd": (t.get("arc") or {}).get("dd"),
                           "signals": [s["sig"] for s in t["_sigs"]], "guess": act, "why": why, "fix": None})
            st["to_review"] += 1
            continue
        items.append(to_item(t, act, conf, why))
        st["labelled"] += 1
        st["act_" + act] += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    prev = json.loads(out.read_text())["items"] if out.exists() else []
    keep = {x["id"]: x for x in prev}
    for x in items:          # a later import (or a review) replaces the earlier label of the same turn
        keep[x["id"]] = x
    out.write_text(json.dumps({"items": list(keep.values())}, indent=0))
    review_dir.mkdir(parents=True, exist_ok=True)
    rf = review_dir / "review.jsonl"
    old = set()
    if rf.exists():
        old = {json.loads(line)["id"] for line in open(rf) if line.strip()}
    with open(rf, "a") as f:
        for r in review:
            if r["id"] not in old and r["id"] not in reviewed:
                f.write(json.dumps(r) + "\n")
    clips = extract_audio(zips_of(files), {x["id"]: x for x in items}, audio_dir)
    res = {"files": [":".join(map(str, f)) if isinstance(f, tuple) else str(f) for f in files], "turns": len(turns),
           "signals": sum(len(v) for v in sigs.values()), "items_total": len(keep), "clips": clips,
           "versions": dict(Counter(t.get("v", 1) for t in turns)), **dict(st)}
    if not quiet:
        print(json.dumps(res, indent=1))
    return res


def extract_audio(zips: list[Path], labelled: dict, audio_dir: Path = AUDIO) -> int:
    """A playtest zip's clips of LABELLED turns -> <audio_dir>/<zip stem>/<turn id>.wav + clips.jsonl (the turn's gold,
    frame, words, split). Members are matched by name (ZIP_WAV) and written under our own names, never as given."""
    n = 0
    for zf in zips:
        with zipfile.ZipFile(zf) as z:
            man = {}
            if "manifest.json" in z.namelist():
                try:
                    man = json.loads(z.read("manifest.json"))
                except ValueError:
                    man = {}
            rows = []
            d = audio_dir / re.sub(r"[^A-Za-z0-9_.-]", "_", zf.stem)
            for name in z.namelist():
                m = ZIP_WAV.match(name)
                if not m or m.group(1) not in labelled:
                    continue
                it = labelled[m.group(1)]
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{m.group(1)}.wav").write_bytes(z.read(name))
                rows.append({"id": m.group(1), "wav": f"{m.group(1)}.wav", "gold": it["gold"], "conf": it["conf"],
                             "frame": it["frame"], "text": it["text"], "split": it["split"], "cat": it["cat"],
                             **({"dd": it["dd"]} if it.get("dd") else {})})
            if rows:
                (d / "clips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
                (d / "manifest.json").write_text(json.dumps(man, indent=1))
                n += len(rows)
    return n


def cmd_decode(a):
    """Model server env: every playtest clip through the real Arc ear (the app's EarStream, the clip's screen hot
    lists) -> <audio dir>/decodes.jsonl, each in the real_ear cache form (hyp, events, x.final) replay.messages reads."""
    import importlib.util
    import os
    import sys
    import wave
    sys.path.insert(0, os.getcwd())
    from app import arc_ear, arcmeta
    from app.stream_context import StreamContext
    arcmeta.load()
    spec = importlib.util.spec_from_file_location("dm_replay", HERE.parent / "backend/app/director_model/replay.py")
    RP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RP)
    tier = json.load(open(HERE.parent / "backend" / "tests" / "fixtures" / "ear_eval" / "tier_a.json"))
    for ad in a.audio:
        d = Path(ad).expanduser()
        rows = [json.loads(x) for x in open(d / "clips.jsonl")]
        with open(d / "decodes.jsonl", "w") as f:
            for r in rows:
                with wave.open(str(d / r["wav"])) as w:
                    pcm = w.readframes(w.getnframes())
                es = arc_ear.EarStream("assistant")
                StreamContext().update({"t": "context", "names": tier}, es)
                msgs = []
                for i in range(0, len(pcm), 2560):
                    msgs += es.feed_all(pcm[i:i + 2560])
                msgs += es.flush_all()
                es.close()
                ev, fx = RP.compact(msgs, arc_ear.agreement)
                hyp = " ".join(e["text"] for e in ev if e["t"] == "words" and e["final"] and e["text"].strip())
                f.write(json.dumps({"id": r["id"], "hyp": hyp, "events": ev, "x": {"final": fx}}) + "\n")
        print("decoded", d, len(rows))


def cmd_retest(a):
    """Decoded playtest clips -> data/real_retest.json: the real-turn re-test set (gen_sessions test_log_audio).
    Only clips whose words hash to the held-out split, unless --all (report only: those words may also train)."""
    items = []
    for d in sorted(p for p in Path(a.audio_root).glob("*") if (p / "decodes.jsonl").exists()):
        dec = {r["id"]: r for r in map(json.loads, open(d / "decodes.jsonl"))}
        for r in map(json.loads, open(d / "clips.jsonl")):
            if r["id"] not in dec or (r["split"] != "test" and not a.all):
                continue
            dd = dec[r["id"]]
            if not (dd.get("hyp") or "").strip() and r["gold"].get("act") != "ignore":
                continue
            items.append({**{k: r[k] for k in ("id", "gold", "conf", "frame", "text", "cat", "split")},
                          "heard": dd.get("hyp") or "", "root": "log:" + r["text"], "decode": dd,
                          **({"dd": tuple(r["dd"])} if r.get("dd") else {})})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"note": "playtest audio decodes (import_logs.py retest); local only",
                                       "items": items}, indent=0))
    print(f"{len(items)} re-test items -> {a.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="import", choices=["import", "decode", "retest"])
    ap.add_argument("--log", action="append", default=[], help="a turnlog folder, .jsonl file or playtest .zip "
                    "(repeatable)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--review", default=str(REVIEW))
    ap.add_argument("--audio", action="append", default=[], help="decode: a data/real_audio/<zip> folder")
    ap.add_argument("--audio-root", default=str(AUDIO))
    ap.add_argument("--all", action="store_true", help="retest: every decoded clip, not only the held-out split")
    a = ap.parse_args()
    if a.cmd == "decode":
        return cmd_decode(a)
    if a.cmd == "retest":
        a.out = a.out or str(RETEST)
        return cmd_retest(a)
    if not a.log:
        raise SystemExit("usage: import_logs.py --log <turnlog folder | .jsonl | playtest .zip>")
    fs = files_of(a.log)
    if not fs:
        raise SystemExit(f"no turn logs in {a.log}")
    run(fs, Path(a.out or OUT), Path(a.review))


if __name__ == "__main__":
    main()
