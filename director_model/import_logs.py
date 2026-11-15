"""Turn the opt-in on-device turn logs (backend/app/turnlog.py) into labelled training turns (docs/DIRECTOR_LOOP.md).

    make director-import LOG=path/to/turnlog            # a folder (turns.jsonl + turns.1.jsonl) or files, comma list
    python3 director_model/import_logs.py --log ~/Downloads/turnlog --log other/turns.jsonl

Writes
  director_model/data/real_turns.json     every usable turn with a weak (or reviewed) gold act, its screen frame,
                                          Arc's device_directed, split train / val / test by a hash of the words
  director_model/data/review/review.jsonl the low-confidence turns for a person to correct: set "fix" to one of
                                          ignore | answer | command | navigate | ask_clarify | nudge | skip, then
                                          move (or copy) the line into reviewed.jsonl; the next import applies it
Weak labels come from the outcome signals the app logged after each turn (turnlog.py):
  * an ignored turn the kid REPEATED and the repeat was acted on      -> the repeat's act (the ignore was wrong)
  * an acted turn followed by "no" / "stop" / "back" / a cancelled confirm / a lesson hint on chatter
                                                                       -> ignore (short / not directed) or ask_clarify
  * an acted turn the kid repeated (same outcome)                      -> low confidence (we may have misheard)
  * a lesson answer that went to hint                                  -> nudge (a wrong answer) unless it was chatter
  * no signal                                                          -> what the app did (weak positive)
Guard turns ("<private>") and anything still carrying a redaction tag are never imported as text to learn.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
REVIEW = DATA / "review"
OUT = DATA / "real_turns.json"
REVIEW_MIN = 0.6           # below this confidence a turn goes to review instead of training
ACTS = ("ignore", "answer", "command", "navigate", "ask_clarify", "nudge", "confirm_yes", "confirm_no")
CHATTER = re.compile(r"^(?:oh|okay|ok|alright|yeah|yep|um|uh|hmm|wait|so|it s|its|it|the|a|oh it s|oh it s the|"
                     r"oh okay|okay okay|alright alright|oh wait|oh cool|oh nice|hold on|one sec)(?: \w+)?$")
ACT_OF_FINAL = {"ignore": "ignore", "navigate": "navigate", "answer": "answer", "command": "command",
                "confirm_yes": "confirm_yes", "confirm_no": "confirm_no", "ask_clarify": "ask_clarify", "guard": None,
                "nudge": "nudge", "alert": None, "wait": None}


def files_of(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        for x in p.split(","):
            x = Path(x).expanduser()
            if x.is_dir():
                out += [f for f in (x / "turns.1.jsonl", x / "turns.jsonl") if f.exists()]
                out += sorted(f for f in x.glob("*.jsonl") if f.name not in ("turns.jsonl", "turns.1.jsonl"))
            elif x.exists():
                out.append(x)
    return out


def read(files: list[Path]) -> tuple[list[dict], dict]:
    turns, sigs = [], defaultdict(list)
    for f in files:
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue          # a torn last line (the app was closed mid-write)
            if r.get("k") == "turn":
                turns.append(r)
            elif r.get("k") == "signal":
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
    neg = kinds & {"negate", "confirm_cancel", "retap"}
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
    return it


def run(files: list[Path], out: Path = OUT, review_dir: Path = REVIEW, quiet: bool = False) -> dict:
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
    res = {"files": [str(f) for f in files], "turns": len(turns), "signals": sum(len(v) for v in sigs.values()),
           "items_total": len(keep), **dict(st)}
    if not quiet:
        print(json.dumps(res, indent=1))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="append", required=True, help="a turnlog folder or .jsonl file (repeatable)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--review", default=str(REVIEW))
    a = ap.parse_args()
    fs = files_of(a.log)
    if not fs:
        raise SystemExit(f"no turn logs in {a.log}")
    run(fs, Path(a.out), Path(a.review))


if __name__ == "__main__":
    main()
