"""Barge-in harness, stage 1 (SILENT: nothing is ever played aloud; `say -o` only, never afplay).

Builds the test audio a mic would hear while CAPCOM says the Flight School Radiation step-5 prompt, streams each clip
through the real ear (backend WS /ws/listen -> model server Arc ear) in real time, 80 ms PCM16 frames, the same path
the browser mic uses, and writes what the ear said back plus the per-frame mic level to
frontend/tests/fixtures/barge/<case>.json. Stage 2 (tools/barge_harness.mjs) replays those into the real voice.js +
floor.js while the line "plays".

Sets (16 kHz mono):
  silence   mic hiss + mains hum only
  noise     real room-noise beds (cabin / cafe / room recordings, NOISE_DIR; the 16 ear_compare used)
  echo      the app's own voice leaking from the speakers: the recorded Nora voice-pack clips of the step's lines and
            the macOS OS voice (`say -o`), low-passed + a small room reverb, at a speaker-leak level
  command   real adult commands (SLURP test, SLURP_DIR) and OS-voice commands, spoken over the echo of the prompt
  answer    an answer to the step spoken over the question

    model_server/.venv/bin/python frontend/tools/barge_clips.py --listen ws://127.0.0.1:8204/ws/listen --work /tmp/x
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "backend/data/voice_pack"
OUT = ROOT / "frontend/tests/fixtures/barge"
NOISE = Path(os.environ.get("NOISE_DIR", Path.home() / "dv3work/assets/noise/audit/wav"))
SLURP = Path(os.environ.get("SLURP_DIR", Path.home() / "dv3work/arc_benchmarks/audio/slurp600"))
SR, CHUNK = 16000, 1280
PROMPT = "Doctors count radiation in mSv. So what is an mSv?"
SUCCESS = "Correct. One mSv is about 10 chest x-rays."
WARM = "Not quite. It measures how much radiation you got."
# Timeline of every clip (the mic is always on, so the ear and the app have heard the room and an earlier line):
#   0-2 s idle (room only) | 2 s: an earlier CAPCOM line (WARM) | 6 s: the test line (PROMPT) | 7.8 s: the kid, if any
WARM_AT, LINE_AT, LEN_S = 2.0, 6.0, 14.0
ONSET_S = LINE_AT + 1.8


def db(x):
    return 10 ** (x / 20)


def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-12))


def load(path: Path) -> np.ndarray:
    """Any audio file -> 16 kHz mono float32 (ffmpeg, never played)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def os_voice(text: str, voice: str, work: Path) -> np.ndarray:
    """macOS `say -o` to a file (never to the speakers)."""
    p = work / f"say_{voice}_{abs(hash(text)) % 10 ** 8}.aiff"
    if not p.exists():
        subprocess.run(["say", "-v", voice, "-o", str(p), text], check=True)
    return load(p)


def pack_clip(key: str) -> np.ndarray:
    idx = json.loads((PACK / "index.json").read_text())
    for v in idx.values():
        if isinstance(v, dict) and key in v and isinstance(v[key], dict):
            return load(PACK / v[key]["file"])
    raise KeyError(key)


def leak(x: np.ndarray, level_db: float, rng) -> np.ndarray:
    """A speaker heard by the mic: low-passed (small speakers, distance), a short room reverb, at level_db RMS."""
    y = np.convolve(x, np.ones(4) / 4, mode="same")                       # gentle low-pass
    n = int(0.25 * SR)
    rir = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.05 * SR))
    rir[0] = 1.0
    y = np.convolve(y, rir / np.abs(rir).sum() * 3, mode="full")[: len(x)]
    voiced = y[np.abs(y) > 0.02 * np.abs(y).max()] if np.abs(y).max() > 0 else y
    return y * (db(level_db) / max(rms(voiced), 1e-9))


def at_level(x: np.ndarray, level_db: float) -> np.ndarray:
    voiced = x[np.abs(x) > 0.05 * np.abs(x).max()]
    return x * (db(level_db) / max(rms(voiced), 1e-9))


def place(bed: np.ndarray, x: np.ndarray, t: float) -> np.ndarray:
    i = int(t * SR)
    j = min(len(bed), i + len(x))
    bed[i:j] += x[: j - i]
    return bed


def hiss(rng) -> np.ndarray:
    t = np.arange(int(LEN_S * SR)) / SR
    return (rng.standard_normal(len(t)) * db(-62) + np.sin(2 * np.pi * 60 * t) * db(-58)).astype(np.float32)


def build(work: Path) -> dict[str, dict]:
    rng = np.random.default_rng(7)
    nora_prompt = np.concatenate([pack_clip("doctors count radiation in msv"), np.zeros(int(0.25 * SR), np.float32),
                                  pack_clip("so what is an msv")])
    nora_success = pack_clip("correct one msv is about 10 chest x rays")
    nora_warm = pack_clip("not quite it measures how much radiation you got")
    os_prompt = os_voice(PROMPT, "Samantha", work)
    os_spoken = os_voice("Doctors count radiation in millisieverts. So what is a millisievert?", "Samantha", work)
    cases: dict[str, dict] = {}

    def case(name, kind, audio, line=PROMPT, line_s=None, expect="no_barge", onset=None, said=None, line_audio=None):
        # line_env / warm_env: the clean line's 80 ms RMS, the envelope the app decodes from the TTS audio it plays
        cases[name] = {"kind": kind, "audio": np.clip(audio, -1, 1).astype(np.float32), "line": line, "line_at": LINE_AT,
                       "line_env": levels(line_audio if line_audio is not None else nora_prompt), "warm_env": levels(nora_warm),
                       "line_s": round(line_s if line_s is not None else len(nora_prompt) / SR, 3), "expect": expect,
                       "onset_s": onset, "said": said, "warm": WARM, "warm_at": WARM_AT, "warm_s": round(len(nora_warm) / SR, 3)}

    def with_lines(bed, line, level):
        """The earlier line and the test line, leaking from the speakers at `level` dB (None: a perfect echo canceller)."""
        if level is not None:
            place(bed, leak(nora_warm, level, rng), WARM_AT)
            place(bed, leak(line, level, rng), LINE_AT)
        return bed

    case("silence_hiss", "silence", hiss(rng))
    beds = sorted(NOISE.glob("*.wav"))
    for name in ("cabin_237374", "cafe_370973", "cafe_437461", "room_108695", "room_426767", "room_641306"):
        p = NOISE / f"{name}.wav"
        if not p.exists():
            continue
        x = load(p)
        x = np.tile(x, int(np.ceil(LEN_S * SR / len(x))))[: int(LEN_S * SR)]
        bed = hiss(rng)
        bed[: len(x)] += x
        case(f"noise_{name}", "noise", bed)
    print(f"noise beds available: {len(beds)}")
    case("echo_nora_prompt", "echo", with_lines(hiss(rng), nora_prompt, -30))
    case("echo_nora_prompt_hot", "echo", with_lines(hiss(rng), nora_prompt, -20))
    case("echo_nora_success", "echo", with_lines(hiss(rng), nora_success, -26), line=SUCCESS, line_s=len(nora_success) / SR,
         line_audio=nora_success)
    case("echo_os_prompt", "echo", with_lines(hiss(rng), os_prompt, -26), line_s=len(os_prompt) / SR, line_audio=os_prompt)
    case("echo_os_spoken_form", "echo", with_lines(hiss(rng), os_spoken, -26), line_s=len(os_spoken) / SR,
         line_audio=os_spoken)
    room = load(NOISE / "room_329533.wav")
    room = np.tile(room, int(np.ceil(LEN_S * SR / len(room))))[: int(LEN_S * SR)]
    case("echo_nora_plus_room", "echo", with_lines(hiss(rng) + room, nora_prompt, -26))

    def over_prompt(x, level=-20, onset=ONSET_S, leak_db=-30):
        return place(with_lines(hiss(rng), nora_prompt, leak_db), at_level(x, level), onset)

    slurp = {"slurp_stop_play": ("audio--1504191571-headset.flac", "stop play"),
             "slurp_quiet": ("audio-1502215844-headset.flac", "quiet"),
             "slurp_next": ("audio-1499265506-headset.flac", "next"),
             "slurp_pause_the_book": ("audio--1505407266.flac", "pause the book")}
    for name, (f, said) in slurp.items():
        p = SLURP / f
        if not p.exists():
            print("missing", p)
            continue
        x = load(p)
        # trim leading/trailing silence so the onset is where we put it
        e = np.convolve(np.abs(x), np.ones(400) / 400, mode="same")
        on = np.where(e > 0.1 * e.max())[0]
        x = x[max(0, on[0] - 800): on[-1] + 1600]
        case(name, "command", over_prompt(x, -22), expect="barge", onset=ONSET_S, said=said)
        if name in ("slurp_quiet", "slurp_next"):   # the same, with a working echo canceller (the leak 10 dB lower)
            case(name + "_aec", "command", over_prompt(x, -22, leak_db=-40), expect="barge", onset=ONSET_S, said=said)
    for name, voice, text in (("os_stop", "Fred", "Stop."), ("os_wait", "Daniel", "Wait."),
                              ("os_go_to_the_map", "Fred", "Go to the map.")):
        x = os_voice(text, voice, work)
        e = np.abs(x)
        on = np.where(e > 0.05 * e.max())[0]
        x = x[max(0, on[0] - 400):]
        case(name, "command", over_prompt(x), expect="barge", onset=ONSET_S, said=text)
        if name in ("os_stop", "os_wait"):
            case(name + "_aec", "command", over_prompt(x, leak_db=-40), expect="barge", onset=ONSET_S, said=text)
    x = os_voice("A radiation dose.", "Daniel", work)
    on = np.where(np.abs(x) > 0.05 * np.abs(x).max())[0]
    case("answer_radiation_dose", "answer", over_prompt(x[max(0, on[0] - 400):], onset=LINE_AT + 2.2),
         expect="barge_answer", onset=LINE_AT + 2.2, said="a radiation dose")
    return cases


async def ear(listen: str, audio: np.ndarray) -> list[dict]:
    """Stream the clip in real time through WS /ws/listen (each clip ends in room tone, so turns end); every message
    back with its time since the first frame."""
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    msgs: list[dict] = []
    async with websockets.connect(listen, max_size=2 ** 22) as ws:
        while True:
            d = json.loads(await ws.recv())
            if d.get("t") == "ready":
                break
        t0 = time.monotonic()

        async def rx():
            async for raw in ws:
                if isinstance(raw, str):
                    d = json.loads(raw)
                    if d.get("t") in ("words", "turn", "arc"):
                        msgs.append({"ms": round((time.monotonic() - t0) * 1000), **d})

        task = asyncio.create_task(rx())
        n = len(pcm) // (CHUNK * 2)
        for k in range(n):
            await ws.send(pcm[k * CHUNK * 2:(k + 1) * CHUNK * 2])
            await asyncio.sleep(max(0.0, t0 + (k + 1) * CHUNK / SR - time.monotonic()))
        await asyncio.sleep(1.0)
        task.cancel()
    return msgs


def ear_offline(audio: np.ndarray, root: Path) -> tuple[list[dict], float]:
    """The same Arc ear in-process (model_server app.arc_ear.EarStream, the turn logic behind /v1/stream?ear=arc, with
    the backend's Tier A context): 80 ms chunks, each message stamped with the audio time at the end of its chunk plus
    that call's compute. Used when the machine is too loaded for the live socket to keep up (a backlog there shows as
    seconds of ear lag that a kid's machine doesn't have). Returns (messages, real-time factor)."""
    import sys
    sys.path.insert(0, str(root / "model_server"))
    from app import arc_ear, arcmeta
    from app.stream_context import StreamContext
    if not arcmeta.STATE.get("decoder"):
        arcmeta.load()
    tier = json.loads((root / "backend/tests/fixtures/ear_eval/tier_a.json").read_text())
    es = arc_ear.EarStream("assistant")
    StreamContext().update({"t": "context", "names": tier}, es)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    msgs: list[dict] = []
    for k in range(0, len(pcm), CHUNK * 2):
        c0 = es.compute_s
        out = es.feed_all(pcm[k:k + CHUNK * 2])
        ms = round((k // 2 + CHUNK) / SR * 1000 + (es.compute_s - c0) * 1000)
        ms = max(ms, msgs[-1]["ms"] if msgs else 0)      # in the order the ear sent them
        msgs += [{"ms": ms, **m} for m in out if m.get("t") in ("words", "turn", "arc")]
    rtf = es.compute_s / max(es.audio_s, 1e-6)
    es.close()
    return msgs, rtf


def levels(audio: np.ndarray) -> list[float]:
    n = len(audio) // CHUNK
    return [round(rms(audio[k * CHUNK:(k + 1) * CHUNK]), 5) for k in range(n)]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="ws://127.0.0.1:8204/ws/listen")
    ap.add_argument("--work", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--par", type=int, default=2)
    ap.add_argument("--offline", action="store_true", help="the Arc ear in-process (needs the model_server env)")
    ap.add_argument("--env-only", action="store_true", help="refresh line_env / warm_env in the existing fixtures")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    cases = build(work)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.env_only:
        for n, c in cases.items():
            p = OUT / f"{n}.json"
            if p.exists():
                fx = json.loads(p.read_text())
                fx.update(line_env=c["line_env"], warm_env=c["warm_env"])
                p.write_text(json.dumps(fx, separators=(",", ":")))
        return
    sem = asyncio.Semaphore(a.par)

    async def one(name, c):
        if a.only and a.only not in name:
            return
        if a.offline:
            sf.write(work / f"{name}.wav", c["audio"], SR)
            msgs, rtf = ear_offline(c["audio"], ROOT)
            fx = {k: v for k, v in c.items() if k != "audio"}
            fx.update(name=name, frame_ms=CHUNK * 1000 // SR, levels=levels(c["audio"]), ear=msgs, ear_path="offline",
                      rtf=round(rtf, 3))
            (OUT / f"{name}.json").write_text(json.dumps(fx, separators=(",", ":")))
            words = [m.get("text") for m in msgs if m.get("t") == "turn" and m.get("state") == "end"]
            print(f"{name:28s} {c['kind']:8s} rtf={rtf:.2f} turns={words[:6]}")
            return
        async with sem:
            sf.write(work / f"{name}.wav", c["audio"], SR)
            for attempt in range(4):        # the model server allows a few ear sessions; a busy one closes at once
                try:
                    msgs = await ear(a.listen, c["audio"])
                    break
                except websockets.ConnectionClosed:
                    await asyncio.sleep(3 + 3 * attempt)
            else:
                print(f"{name}: the ear never opened")
                return
        fx = {k: v for k, v in c.items() if k != "audio"}
        fx.update(name=name, frame_ms=CHUNK * 1000 // SR, levels=levels(c["audio"]), ear=msgs, ear_path="ws/listen")
        (OUT / f"{name}.json").write_text(json.dumps(fx, separators=(",", ":")))
        words = [m.get("text") for m in msgs if m.get("t") == "turn" and m.get("state") == "end"]
        print(f"{name:28s} {c['kind']:8s} turns={words}")

    if a.offline:
        for n, c in cases.items():
            await one(n, c)
    else:
        await asyncio.gather(*(one(n, c) for n, c in cases.items()))


if __name__ == "__main__":
    asyncio.run(main())
