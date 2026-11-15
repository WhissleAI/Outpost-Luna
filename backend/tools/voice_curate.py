"""Curate the Settings voices (docs/VOICES.md): render a kid-facing line with ~40 Steer TTS Edge candidates, score each one
objectively, pick 10 clear and varied voices, and write backend/data/voices.json + the offline preview clips.

    cd backend && uv run python tools/voice_curate.py --models http://127.0.0.1:8200 [--out data] [--n 40] [--pick 10]

Read-only use of the model server: POST /v1/tts (render) and WS /v1/stream?ear=arc (the Arc ear round trip), one
request at a time. Steps:

1. candidates  stratified over gender x pitch register x pace (Steer's voices.json, via GET /v1/tts/voices): two per
               stratum, the lowest and highest f0 in it, plus the four persona voices the app already uses.
2. render      SCORE_LINES (two kid-facing sentences) with the guide's base style (tag `interest`, perform children 0.7).
3. measure     intelligibility: each render resampled to 16 kHz and streamed through the Arc ear, no context; WER with
               the ear eval's normaliser (tests/fixtures/ear_eval/score.py). Loudness (active-speech RMS dBFS), peak,
               clipped-sample share, duration and words/s, f0 median and range (5th-95th pct, semitones) and f0 IQR
               (semitones: how lively the melody is) from a small autocorrelation pitch tracker.
   The same audio again with pink noise at 5 dB SNR (clean speech scores near the ceiling for every voice; noise
               is what separates them).
4. pick        clear = WER <= 0.10 clean and <= 0.25 noisy, no clipping, loudness within 6 dB of the median. Farthest-point
               selection over (f0 median st, f0 IQR st, words/s), z-scored, seeded with the guide voice (the default,
               always offered, even if it misses the noisy bar); CAPCOM's, Houston's and the story's voices are never
               offered. Near-ties go to the lower clean + noisy WER.
5. previews    PREVIEW_LINE rendered per pick, trimmed, 16 kHz mono PCM16 -> data/voice_previews/<id>.wav.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import sys
import wave
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests" / "fixtures" / "ear_eval"))
from score import edits, norm  # noqa: E402

SCORE_LINES = [
    "Good morning, Commander! The rover found ice near the south pole crater.",
    "Set the shields to forty percent, then check the battery before the storm.",
]
PREVIEW_LINE = "Hello! Ready to fly?"
STYLE = {"tag": "interest", "perform": {"genre": "children", "strength": 0.7}}
PERSONA_VOICES = ["voice_0644", "voice_0213", "voice_0602", "voice_0272"]   # guide, capcom, story, houston
DEFAULT = "voice_0644"
SR_OUT = 16000
NOISE_SNR_DB = 5.0          # the noisy pass: pink noise at 5 dB SNR (a busy room); the clean pass is near the ceiling


def read_wav(b: bytes) -> tuple[np.ndarray, int]:
    w = wave.open(io.BytesIO(b))
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768.0
    return x, sr


def resample(x: np.ndarray, sr: int, to: int = SR_OUT) -> np.ndarray:
    if sr == to:
        return x
    n = int(round(len(x) * to / sr))
    # a 2x box pre-filter keeps aliasing down for 24k -> 16k (speech energy is far below 8 kHz)
    k = np.ones(3, np.float32) / 3
    xf = np.convolve(x, k, mode="same")
    return np.interp(np.linspace(0, len(xf) - 1, n), np.arange(len(xf)), xf).astype(np.float32)


def trim(x: np.ndarray, sr: int, db: float = -40.0, pad_s: float = 0.08) -> np.ndarray:
    fr = int(sr * 0.02)
    e = np.array([np.sqrt(np.mean(x[i:i + fr] ** 2) + 1e-12) for i in range(0, max(len(x) - fr, 1), fr)])
    on = np.where(20 * np.log10(e + 1e-12) > db)[0]
    if not len(on):
        return x
    a, b = max(0, on[0] * fr - int(pad_s * sr)), min(len(x), (on[-1] + 1) * fr + int(pad_s * sr))
    return x[a:b]


def pink(n: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spec), dtype=np.float32)
    f[0] = 1.0
    y = np.fft.irfft(spec / np.sqrt(f), n)
    return (y / np.sqrt(np.mean(y ** 2))).astype(np.float32)


def add_noise(x: np.ndarray, snr_db: float = NOISE_SNR_DB) -> np.ndarray:
    """Pink noise at `snr_db` against the active-speech level (the same noise for every voice: seeded)."""
    fr = int(SR_OUT * 0.02)
    e = np.array([np.mean(x[i:i + fr] ** 2) for i in range(0, max(len(x) - fr, 1), fr)])
    p = float(np.mean(e[e > e.max() * 1e-3])) if (e > 0).any() else 1e-6
    return (x + pink(len(x)) * np.sqrt(p / 10 ** (snr_db / 10))).astype(np.float32)


def f0_track(x: np.ndarray, sr: int = SR_OUT, fmin: float = 70, fmax: float = 450) -> np.ndarray:
    """Normalised-autocorrelation pitch per 40 ms frame (10 ms hop); voiced when the peak > 0.55 and the frame is loud."""
    fr, hop = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    rms_all = np.sqrt(np.mean(x ** 2) + 1e-12)
    out = []
    for i in range(0, len(x) - fr, hop):
        f = x[i:i + fr] - np.mean(x[i:i + fr])
        if np.sqrt(np.mean(f ** 2)) < 0.3 * rms_all:
            continue
        ac = np.correlate(f, f, "full")[fr - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        if seg[k] < 0.55:
            continue
        lag = k + lo
        if 0 < k < len(seg) - 1:      # parabolic interpolation
            a, b, c = seg[k - 1], seg[k], seg[k + 1]
            lag += 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
        out.append(sr / lag)
    return np.array(out)


def st(hz: float, ref: float = 100.0) -> float:
    return 12 * math.log2(hz / ref)


def measure(x: np.ndarray, sr: int) -> dict:
    y = trim(x, sr)
    fr = int(sr * 0.02)
    e = np.array([np.sqrt(np.mean(y[i:i + fr] ** 2) + 1e-12) for i in range(0, max(len(y) - fr, 1), fr)])
    active = e[20 * np.log10(e) > 20 * np.log10(e.max()) - 30]
    f0 = f0_track(resample(y, sr))
    sts = np.array([st(f) for f in f0]) if len(f0) else np.array([0.0])
    return {"dur_s": round(len(y) / sr, 3), "rms_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(active ** 2)))), 2),
            "peak_dbfs": round(float(20 * np.log10(np.abs(x).max() + 1e-9)), 2),
            "clip_pct": round(float(np.mean(np.abs(x) >= 0.999) * 100), 4),
            "f0_med_hz": round(float(np.median(f0)), 1) if len(f0) else None,
            "f0_iqr_st": round(float(np.percentile(sts, 75) - np.percentile(sts, 25)), 2),
            "f0_range_st": round(float(np.percentile(sts, 95) - np.percentile(sts, 5)), 2)}


async def tts(c: httpx.AsyncClient, voice: str, text: str) -> bytes:
    r = await c.post("/v1/tts", json={"text": text, "voice": voice, **STYLE})
    r.raise_for_status()
    return r.content


async def ear(ws_url: str, pcm16k: np.ndarray) -> str:
    """Stream 16 kHz audio through the Arc ear (as fast as it takes it; turn logic runs on audio time) -> the words."""
    import websockets
    pcm = (np.clip(np.concatenate([np.zeros(4000), pcm16k, np.zeros(16000)]), -1, 1) * 32767).astype("<i2").tobytes()
    finals: list[str] = []
    last_partial = ""
    async with websockets.connect(ws_url, max_size=None) as ws:
        hello = json.loads(await ws.recv())
        if not hello.get("available"):
            raise RuntimeError(f"ear unavailable: {hello}")

        async def reader():
            nonlocal last_partial
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                m = json.loads(raw)
                if m.get("t") == "words":
                    if m.get("final"):
                        finals.append(m.get("text") or "")
                        last_partial = ""
                    else:
                        last_partial = m.get("text") or ""
        rt = asyncio.create_task(reader())
        for i in range(0, len(pcm), 2560):
            await ws.send(pcm[i:i + 2560])
            await asyncio.sleep(0.005)
        await ws.send(json.dumps({"t": "stop"}))
        try:
            await asyncio.wait_for(rt, 30)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - the server closes after stop
            rt.cancel()
    return " ".join(f for f in finals + ([last_partial] if last_partial else []) if f).strip()


def candidates(voices: list[dict], n: int) -> list[dict]:
    by = {}
    for v in voices:
        by.setdefault((v["gender"], v["pitch_register"], v["pace"]), []).append(v)
    out = {v["name"]: v for v in voices if v["name"] in PERSONA_VOICES}
    for key in sorted(by):
        vs = sorted(by[key], key=lambda v: v["f0_median_hz"])
        for v in ([vs[0], vs[-1]] if len(vs) > 1 else vs):
            out.setdefault(v["name"], v)
    return list(out.values())[: max(n, len(PERSONA_VOICES))]


def pick(rows: list[dict], k: int) -> list[dict]:
    """The default guide voice first (always offered: it is what the kid hears before choosing, so "keep the default"
    must be on the list even if it doesn't pass the noisy bar), then k-1 clear voices by farthest-point selection.
    CAPCOM's, Houston's and the story's own voices are never offered: choosing one would make the guide sound like them."""
    ok = [r for r in rows if r.get("wer") is not None]
    med = float(np.median([r["rms_dbfs"] for r in ok]))
    clear = [r for r in ok if r["wer"] <= 0.10 and r.get("wer_noisy", 0) <= 0.25 and r["clip_pct"] == 0
             and abs(r["rms_dbfs"] - med) <= 6]
    for r in rows:
        r["clear"] = r in clear
    others = set(PERSONA_VOICES) - {DEFAULT}
    pool = [r for r in ok if r["id"] == DEFAULT] + [r for r in clear if r["id"] != DEFAULT and r["id"] not in others]
    feats = np.array([[st(r["f0_med_hz"] or 100), r["f0_iqr_st"], r["words_per_s"]] for r in pool])
    z = (feats - feats.mean(0)) / (feats.std(0) + 1e-9)
    chosen = [0] if pool and pool[0]["id"] == DEFAULT else [int(np.argmin([r["wer"] for r in pool]))]
    while len(chosen) < min(k, len(pool)):
        d = np.min(np.linalg.norm(z[:, None, :] - z[None, chosen, :], axis=2), axis=1)
        d[chosen] = -1
        d = d - 0.05 * np.array([r["wer"] + r.get("wer_noisy", 0) for r in pool])   # near-ties: the clearer voice
        chosen.append(int(np.argmax(d)))
    return [pool[i] for i in chosen]


async def main(a):
    out = Path(a.out)
    prev_dir = out / "voice_previews"
    prev_dir.mkdir(parents=True, exist_ok=True)
    ws_url = a.models.replace("http", "ws", 1) + "/v1/stream?ear=arc"
    async with httpx.AsyncClient(base_url=a.models, timeout=60) as c:
        rows = json.loads(Path(a.from_scores).read_text()) if a.from_scores else []
        cands = [] if a.from_scores else candidates((await c.get("/v1/tts/voices")).json()["voices"], a.n)
        print(f"{len(cands) or len(rows)} candidates", file=sys.stderr)
        for v in cands:
            row = {"id": v["name"], "gender": v["gender"], "register": v["pitch_register"], "pace": v["pace"],
                   "catalog_f0_hz": v["f0_median_hz"]}
            errs = n = nerrs = 0
            ms, hyps, nhyps, dur = [], [], [], 0.0
            for line in SCORE_LINES:
                x, sr = read_wav(await tts(c, v["name"], line))
                m = measure(x, sr)
                ms.append(m)
                dur += m["dur_s"]
                x16 = resample(x, sr)
                hyp = await ear(ws_url, x16)
                hyps.append(hyp)
                errs += edits(norm(line), norm(hyp))
                n += len(norm(line))
                await asyncio.sleep(0.2)
                nhyp = await ear(ws_url, add_noise(x16))
                nhyps.append(nhyp)
                nerrs += edits(norm(line), norm(nhyp))
                await asyncio.sleep(0.2)    # keep the shared model server's load modest
            row.update({"wer": round(errs / n, 3), "wer_noisy": round(nerrs / n, 3), "hyp": hyps, "hyp_noisy": nhyps,
                        "rms_dbfs": round(float(np.mean([m["rms_dbfs"] for m in ms])), 2),
                        "peak_dbfs": max(m["peak_dbfs"] for m in ms), "clip_pct": max(m["clip_pct"] for m in ms),
                        "dur_s": round(dur, 2), "words_per_s": round(sum(len(l.split()) for l in SCORE_LINES) / dur, 2),
                        "f0_med_hz": round(float(np.median([m["f0_med_hz"] or 0 for m in ms])), 1),
                        "f0_iqr_st": round(float(np.mean([m["f0_iqr_st"] for m in ms])), 2),
                        "f0_range_st": round(float(np.mean([m["f0_range_st"] for m in ms])), 2)})
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("id", "wer", "wer_noisy", "rms_dbfs", "clip_pct", "words_per_s", "f0_med_hz",
                                                  "f0_iqr_st")}), file=sys.stderr)
        chosen = pick(rows, a.pick)
        Path(a.raw).write_text(json.dumps(rows, indent=1))
        for r in chosen:
            x, sr = read_wav(await tts(c, r["id"], PREVIEW_LINE))
            y = trim(resample(x, sr), SR_OUT)
            y = y / max(np.abs(y).max(), 1e-6) * 10 ** (-3 / 20)     # previews peak at -3 dBFS: same loudness ceiling
            b = io.BytesIO()
            with wave.open(b, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR_OUT)
                w.writeframes((y * 32767).astype("<i2").tobytes())
            (prev_dir / f"{r['id']}.wav").write_bytes(b.getvalue())
            r["preview_s"] = round(len(y) / SR_OUT, 2)
    print(json.dumps([r["id"] for r in chosen]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="http://127.0.0.1:8200")
    ap.add_argument("--out", default=str(HERE.parent / "data"))
    ap.add_argument("--raw", default="voice_scores.json", help="all candidates' scores (not committed)")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--pick", type=int, default=10)
    ap.add_argument("--from-scores", help="re-pick and re-render previews from a saved --raw file (no ear pass)")
    asyncio.run(main(ap.parse_args()))
