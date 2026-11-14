"""Before/after calibration of the Steer delivery (docs/VOICE_STEERING.md §4d, docs/VOICES.md): loudness, peak, words/s
and Arc-ear WER (clean and 5 dB pink noise) for the 10 Settings voices and the four personas, rendered

    before  raw: POST /v1/tts with the persona's style, no delivery baseline, no mastering (what /api/tts sent until now)
    after   through the real /api/tts pipeline in process (tts.speak: delivery baseline + gap cap + -14 LUFS master)

and re-renders the preview clips through the pipeline (16 kHz mono, mastered to the target after resampling).

    cd backend && uv run python tools/voice_calibrate.py --out /tmp/calib.json [--previews] [--no-ear]

One model-server request at a time (read-only): renders and ear sessions are sequential, with a short pause.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from app import loudness as L, steering, tts as T, voices  # noqa: E402
from app.config import settings  # noqa: E402
from voice_curate import NOISE_SNR_DB, PREVIEW_LINE, SCORE_LINES, add_noise, ear, edits, norm, resample  # noqa: E402

SR16 = 16000


def active(x: np.ndarray, sr: int) -> np.ndarray:
    """Speech span: leading/trailing frames under -45 dB from the loudest 10 ms frame trimmed (level independent)."""
    fr = int(0.01 * sr)
    n = len(x) // fr
    e = 20 * np.log10(np.sqrt(np.mean(x[: n * fr].reshape(n, fr) ** 2, axis=1) + 1e-12))
    on = np.where(e > e.max() - 45)[0]
    return x[on[0] * fr:(on[-1] + 1) * fr] if len(on) else x


async def render_before(c: httpx.AsyncClient, persona: str, voice: str, text: str) -> bytes:
    st = steering.style_for(persona, text)
    body = {"text": text, "voice": voice, "tag": st["tag"], "controls": st["controls"] or None,
            "perform": st["perform"]}
    r = await c.post("/v1/tts", json=body)
    r.raise_for_status()
    return r.content


async def render_after(persona: str, voice: str | None, text: str, speed=None) -> tuple[bytes, dict]:
    style = {"steer_voice": voice} if voice else None
    r = await T.speak(text, persona, style, speed=speed)
    if r.status_code != 200:
        raise RuntimeError(r.body[:200])
    return r.body, dict(r.headers)


async def measure(wavs: list[bytes], ws_url: str | None) -> dict:
    W = D = E = NE = N = 0
    lus, tps, hyps = [], [], []
    for line, b in zip(SCORE_LINES, wavs):
        x, sr = L.read_wav(b)
        lus.append(L.lufs(x, sr))
        tps.append(L.true_peak_db(x))
        D += len(active(x, sr)) / sr
        W += len(line.split())
        if ws_url:
            x16 = resample(x.astype(np.float32), sr)
            h = await ear(ws_url, x16)
            await asyncio.sleep(0.2)
            hn = await ear(ws_url, add_noise(x16))
            await asyncio.sleep(0.2)
            hyps.append([h, hn])
            E += edits(norm(line), norm(h))
            NE += edits(norm(line), norm(hn))
            N += len(norm(line))
    out = {"lufs": round(float(np.mean(lus)), 2), "lufs_spread": round(float(max(lus) - min(lus)), 2),
           "tp_dbtp": round(float(max(tps)), 2), "wps": round(W / D, 2)}
    if ws_url:
        out.update({"wer": round(E / N, 3), "wer_noisy": round(NE / N, 3), "hyp": hyps})
    return out


def preview(b: bytes) -> bytes:
    """Pipeline render -> 16 kHz mono, re-mastered to the target after resampling (no new overs)."""
    x, sr = L.read_wav(b)
    y = resample(x.astype(np.float32), sr).astype(np.float64)
    y = L.cap_gaps(y, SR16, max_gap_s=steering.GAP_FAST_S, lead_s=0.02, tail_s=0.05)
    y, _ = L.master(y, SR16)
    return L.write_wav(y, SR16)


async def main(a):
    T.CACHE_DIR = Path(tempfile.mkdtemp(prefix="calib-"))
    settings.tts_engine = "steer"
    settings.model_server_url = a.models
    settings.tts_timeout_s = 30
    ws_url = None if a.no_ear else a.models.replace("http", "ws", 1) + "/v1/stream?ear=arc"
    rows = []
    targets = [(f"persona:{p}", p, steering.VOICES[p]) for p in ("guide", "capcom", "houston", "story")]
    targets += [(v["id"], "guide", v["id"]) for v in voices.curated() if v["id"] != steering.VOICES["guide"]]
    if a.ids:                             # candidates for a swap: just these, as the guide
        targets = [(i, "guide", i) for i in a.ids.split(",")]
        voices.allowed = lambda v: isinstance(v, str) and v.startswith("voice_")   # not curated yet: let them through
    async with httpx.AsyncClient(base_url=a.models, timeout=60) as c:
        for name, persona, vid in targets:
            row = {"name": name, "persona": persona, "voice": vid}
            if not a.after_only:
                before = []
                for line in SCORE_LINES:
                    before.append(await render_before(c, persona, vid, line))
                    await asyncio.sleep(0.15)
                row["before"] = await measure(before, ws_url)
            after = []
            for line in SCORE_LINES:
                after.append((await render_after(persona, None if name.startswith("persona:") else vid, line))[0])
                await asyncio.sleep(0.15)
            row["after"] = await measure(after, ws_url)
            if a.speeds:
                row["speeds"] = {}
                for s in (0.75, 1.25, 1.5):
                    ws_ = []
                    for line in SCORE_LINES:
                        ws_.append((await render_after(persona, None if name.startswith("persona:") else vid, line,
                                                       speed=s))[0])
                        await asyncio.sleep(0.15)
                    row["speeds"][str(s)] = await measure(ws_, None)
            rows.append(row)
            print(json.dumps({k: (v if k in ("name",) else {kk: vv for kk, vv in v.items() if kk != "hyp"})
                              for k, v in row.items() if k in ("name", "before", "after")}), file=sys.stderr, flush=True)
        if a.previews:
            out = Path(a.preview_dir)
            out.mkdir(parents=True, exist_ok=True)
            for v in voices.curated():
                b, _ = await render_after("guide", v["id"], PREVIEW_LINE)
                (out / f"{v['id']}.wav").write_bytes(preview(b))
                await asyncio.sleep(0.15)
    Path(a.out).write_text(json.dumps({"noise_snr_db": NOISE_SNR_DB, "rows": rows}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="http://127.0.0.1:8200")
    ap.add_argument("--out", required=True)
    ap.add_argument("--previews", action="store_true")
    ap.add_argument("--preview-dir", default=str(HERE.parent / "data" / "voice_previews"))
    ap.add_argument("--no-ear", action="store_true")
    ap.add_argument("--after-only", action="store_true")
    ap.add_argument("--ids", help="comma-separated voice ids to measure instead of the curated set + personas")
    ap.add_argument("--speeds", action="store_true", help="also words/s at 0.75x / 1.25x / 1.5x")
    asyncio.run(main(ap.parse_args()))
