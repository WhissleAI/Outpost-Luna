"""The Director collection kit (docs/DIRECTOR_COLLECTION.md): a guided, consented, LOCAL recording session that covers
every cell of the capability inventory (director_model/coverage.json).

A tester or a family (a kid with a parent present, or an adult) runs one ~15 minute session. The script shows the app
screen it is pretending to be on and one prompt at a time:

  read     read this line aloud, as you would say it to the app ("pause the video")
  free     answer in your own words (the step's question; "the app just asked: Ready for the next lesson?")
  noisy    be the room: talk to someone else, laugh, say "oh no the flour", while the app is not being spoken to
  cooccur  say the command while doing the gesture shown (spin the Moon with a fist)

Each clip is saved with the expected intent and screen state, so the import is labelled without anyone listening.

  python3 director_model/collect.py --out ~/Desktop/director_sessions [--minutes 15] [--speaker child|adult]
  python3 director_model/collect.py --plan                       # print the session plan, record nothing
Recording: `sounddevice` (pip install sounddevice) or, without it, ffmpeg (macOS avfoundation / Windows dshow).

Privacy: nothing leaves this computer. The folder holds 16 kHz WAV clips, manifest.jsonl (prompt, screen, expected
intent; no names) and consent.json (the parent's agreement, the date, an age band; no names, no device id). Delete the
folder to delete everything; `--delete <session folder>` does it. Files are handed over by hand, never uploaded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
SR = 16000
CONSENT = """\
OUTPOST LUNA VOICE COLLECTION: PARENT / GUARDIAN CONSENT

This session records short voice clips to help Outpost Luna understand children better.
  * The clips stay on THIS computer, in the folder shown below. Nothing is uploaded or sent anywhere.
  * No names are recorded. Please do not say names, addresses, school names or phone numbers in the clips.
  * A parent or guardian stays with the child for the whole session. You can skip any prompt or stop at any time.
  * You decide whether to hand the folder to the Whissle team (by USB / a shared drive you choose). Until you do, nobody
    else has it. Delete the folder at any time to delete everything (or run: collect.py --delete <folder>).
  * If you hand it over, the clips are used only to train and test Outpost Luna's speech understanding, and are deleted
    on request.

Type  I AGREE  to continue, or anything else to stop: """

KID_SCENES = {"lesson": "a lesson step: the app asked a question", "ride": "the check ride", "cabin": "the cabin",
              "brief": "the mission picker", "map": "the patch map", "patch": "a patch was just earned",
              "lesson_done": "a lesson just finished", "library": "the Moon library", "debrief": "the debrief",
              "callsign": "choosing a call sign", "video": "a NASA video is playing",
              "prep": "a hands-on Mission prep task (flour, cookies, a flashlight)"}
NOISY = ["Talk to someone in the room about dinner for a few seconds.", "Laugh, then say 'oh no, the flour went everywhere'.",
         "Two people: argue about whose turn it is.", "Say 'wait, hold on' to someone else, not to the app.",
         "Hum or sing a bit.", "Say 'oh my gosh, look at that' to someone next to you.",
         "Read this aloud like the app is talking (the app's own voice echo): 'Copy. Rover heading out to collect ice.'"]


def load_cells() -> list[dict]:
    return json.loads((HERE / "coverage.json").read_text())["cells"]


def prompt_for(cell: dict, rng: random.Random) -> dict | None:
    """One prompt for a coverage cell: kind, the text the speaker sees, the expected label, the screen frame."""
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent / "backend"))
    os.environ.setdefault("MODEL_SERVER_URL", "http://127.0.0.1:1")
    import pools_r8 as P8
    it = P8.cell_item(cell, rng, "test")
    if it is None:
        return None
    gold = dict(it.get("gold") or {})
    if not gold:
        gold = {"act": "answer" if not str(it.get("cat", "")).endswith("wrong") else "nudge"}
    intent = cell["intent"]
    if intent.startswith("ignore:") or gold.get("act") == "ignore":
        kind = "noisy"
        say = rng.choice(NOISY) if intent in ("ignore:chatter", "ignore:roomtalk") else \
            f"Read this aloud like the app is speaking: '{(it.get('lines') or [it['text']])[0]}'"
    elif intent == "gesture+voice":
        kind, say = "cooccur", f"Make a fist and move it as if spinning the Moon, and at the same time say: '{it['text']}'"
    elif intent == "question" or intent.startswith("step:") and rng.random() < 0.5:
        kind, say = "free", f"Answer in your own words (any way a kid would say it). Example: '{it['text']}'"
    else:
        kind, say = "read", it["text"]
    return {"cell": cell["cell"], "screen": cell["screen"], "intent": intent, "kind": kind, "prompt": say,
            "expected_text": it["text"] if kind in ("read", "cooccur") else None, "gold": gold,
            "frame": it.get("frame") or {"screen": cell["screen"]}, "lesson": it.get("lesson"), "step": it.get("step"),
            "pending": cell.get("pending"), "seconds": 6 if kind != "noisy" else 8}


def plan(minutes: float, seed: int, speaker: str) -> list[dict]:
    """~minutes of prompts: every pending / gap cell first, then the rest, round-robin by screen so a session moves
    through the app the way a kid does; ~12 s per prompt with the reading."""
    rng = random.Random(seed)
    cells = load_cells()
    pri = sorted(cells, key=lambda c: (not c.get("pending"), not c.get("gap"), rng.random()))
    n = max(10, int(minutes * 60 / 12))
    out, seen = [], set()
    for c in pri:
        if len(out) >= n:
            break
        if (c["screen"], c["intent"].split(":")[0]) in seen and rng.random() < 0.6:
            continue
        p = prompt_for(c, rng)
        if p:
            if speaker == "adult" and p["kind"] == "noisy" and "argue" in p["prompt"]:
                p["prompt"] = "Say 'can you pass me that' to someone else in the room."
            out.append(p)
            seen.add((c["screen"], c["intent"].split(":")[0]))
    out.sort(key=lambda p: (p["screen"], p["kind"]))
    return out


# ------------------------------------------------------------------------------------------------- recording
def record(seconds: float, path: Path) -> bool:
    """Record mono 16 kHz PCM16 to `path`: sounddevice, else ffmpeg (avfoundation on macOS, dshow on Windows)."""
    try:
        import numpy as np
        import sounddevice as sd
        x = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="int16")
        sd.wait()
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(np.asarray(x).tobytes())
        return True
    except ImportError:
        pass
    if not shutil.which("ffmpeg"):
        print("  no recorder: pip install sounddevice (or install ffmpeg)")
        return False
    src = ["-f", "avfoundation", "-i", ":0"] if sys.platform == "darwin" else \
        ["-f", "dshow", "-i", "audio=" + os.environ.get("COLLECT_MIC", "Microphone")] if sys.platform == "win32" else \
        ["-f", "alsa", "-i", "default"]
    r = subprocess.run(["ffmpeg", "-v", "quiet", "-y", *src, "-t", str(seconds), "-ac", "1", "-ar", str(SR),
                        "-sample_fmt", "s16", str(path)])
    return r.returncode == 0 and path.exists()


def hot_lists(frame: dict, lesson, step) -> dict | None:
    """The ear's hot lists for the clip's screen (backend/app/hotlist.py), stored so the import decodes as the app."""
    try:
        sys.path.insert(0, str(HERE.parent / "backend"))
        from app import hotlist as H
        from app.academy import content as AC
        st = None
        if lesson:
            L = AC.lesson(lesson)
            st = L["steps"][step] if L and step is not None else None
        return H.hot_lists(frame, st)
    except Exception:  # noqa: BLE001
        return None


def run(a):
    tag = secrets.token_hex(4)
    folder = Path(a.out).expanduser() / f"session-{dt.date.today().isoformat()}-{tag}"
    p = plan(a.minutes, a.seed if a.seed is not None else secrets.randbelow(1 << 30), a.speaker)
    print(f"\nThis session has {len(p)} prompts (~{a.minutes:.0f} minutes). It will be saved in:\n  {folder}\n")
    ok = input(CONSENT).strip().upper() == "I AGREE"
    if not ok:
        print("Stopped. Nothing was recorded.")
        return
    band = input("Speaker age band (6-8 / 9-12 / 13-17 / adult, Enter to skip): ").strip()[:8]
    (folder / "clips").mkdir(parents=True)
    (folder / "consent.json").write_text(json.dumps({
        "agreed": True, "date": dt.date.today().isoformat(), "speaker": a.speaker, "age_band": band or None,
        "parent_present": a.speaker == "child", "uploaded": False,
        "text": CONSENT.split("Type")[0].strip()}, indent=1))
    (folder / "README.txt").write_text(
        "Outpost Luna voice collection session. Everything here stays on this computer until you hand it over.\n"
        "Delete this folder to delete the session.\n")
    man = open(folder / "manifest.jsonl", "w")
    for i, q in enumerate(p):
        print(f"\n[{i + 1}/{len(p)}]  Screen: {KID_SCENES.get(q['screen'], q['screen'])}")
        print(f"   {q['kind'].upper()}: {q['prompt']}")
        cmd = input("   Enter = record, s = skip, q = quit: ").strip().lower()
        if cmd == "q":
            break
        if cmd == "s":
            continue
        print(f"   recording {q['seconds']} s ... speak now")
        clip = folder / "clips" / f"{i:03d}.wav"
        if not record(q["seconds"], clip):
            continue
        row = {**q, "clip": f"clips/{clip.name}", "hot": hot_lists(q["frame"], q.get("lesson"), q.get("step")),
               "i": i}
        man.write(json.dumps(row) + "\n")
        man.flush()
    man.close()
    print(f"\nDone. Session saved in {folder}\nHand the folder over by hand if you want to; delete it to delete it.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="~/Desktop/director_sessions")
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--speaker", choices=["child", "adult"], default="child")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--plan", action="store_true", help="print the plan only (no recording)")
    ap.add_argument("--delete", default="", help="delete one session folder (and everything in it)")
    a = ap.parse_args()
    if a.delete:
        d = Path(a.delete).expanduser()
        if d.name.startswith("session-") and (d / "consent.json").exists():
            shutil.rmtree(d)
            print("deleted", d)
        else:
            print("not a collection session folder:", d)
        return
    if a.plan:
        p = plan(a.minutes, a.seed or 0, a.speaker)
        kinds = {}
        for q in p:
            kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
        print(f"{len(p)} prompts, ~{sum(q['seconds'] + 6 for q in p) / 60:.1f} min with reading time; {kinds}; "
              f"{len({q['cell'] for q in p})} cells, {sum(bool(q['pending']) for q in p)} for unmerged features")
        for q in p[:12]:
            print(f"  {q['screen']:10} {q['kind']:7} {q['intent']:28} {q['prompt'][:70]}")
        return
    run(a)


if __name__ == "__main__":
    time.tzset() if hasattr(time, "tzset") else None
    main()
