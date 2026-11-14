"""Render the ear-eval set locally with Steer TTS edge (no cloud). 2 voices per item (8 voices, high-pitched first),
16 kHz mono; every other clip gets classroom-ish noise (babble from other clips + pink noise, 10-14 dB SNR).

uv run --no-project -p 3.12 --with <live_assist>/steer-tts/edge --with "onnxruntime>=1.24" --with soundfile --with scipy \
    python render.py
"""
import glob
import json
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from steertts_edge import OnnxTTS

HERE = Path(__file__).parent
OUT = HERE / "audio"
SR = 16000
rng = np.random.default_rng(7)

d = glob.glob(str(Path.home() / ".cache/huggingface/hub/models--WhissleAI--steer-tts-edge/snapshots/*/"))[0]
tts = OnnxTTS.from_pretrained(d)
tsr = int(getattr(tts, "sr", 0) or getattr(tts, "sample_rate", 0) or json.load(open(Path(d) / "config.json")).get("sample_rate", 24000))
by_f0 = sorted(tts.voices, key=lambda v: -tts.voice_stats(v)["f0_med"])
VOICES = by_f0[:4] + by_f0[60:62] + by_f0[120:122]       # 4 high-pitched (kid-like), 4 mid
CTRL = {v: ({"f0_med": tts.voice_stats(v)["f0_med"] + 2.0} if i < 4 else None) for i, v in enumerate(VOICES)}
items = json.load(open(HERE / "set.json"))["items"]
OUT.mkdir(exist_ok=True)


def pink(n):
    w = rng.standard_normal(n)
    f = np.fft.rfft(w)
    f /= np.sqrt(np.arange(1, len(f) + 1))
    x = np.fft.irfft(f, n)
    return x / (np.abs(x).max() + 1e-9)


clean = {}
manifest = []
for i, it in enumerate(items):
    for k in range(2):
        v = VOICES[(2 * i + k) % len(VOICES)]
        try:
            w = tts(it["text"], voice=v, ctrl=CTRL[v]) if CTRL[v] else tts(it["text"], voice=v)
        except Exception:  # noqa: BLE001 (ctrl not accepted for this voice)
            w = tts(it["text"], voice=v)
        w = np.asarray(w, np.float32).reshape(-1)
        g = gcd(tsr, SR)
        w = resample_poly(w, SR // g, tsr // g).astype(np.float32)
        w = 0.5 * w / (np.abs(w).max() + 1e-9)
        clip_id = f"{it['id']}_{k}"
        clean[clip_id] = w
        manifest.append({"clip": clip_id, "id": it["id"], "voice": v, "noisy": (2 * i + k) % 2 == 1})

ids = list(clean)
for m in manifest:
    w = clean[m["clip"]]
    fr = np.sqrt(np.mean(w[: len(w) // 160 * 160].reshape(-1, 160) ** 2, axis=1))
    m["speech_end_s"] = round(0.3 + (np.nonzero(fr > 0.01)[0][-1] + 1) * 0.01, 3)
    x = np.concatenate([np.zeros(int(0.3 * SR), np.float32), w, np.zeros(int(1.5 * SR), np.float32)])
    if m["noisy"]:
        bab = np.zeros_like(x)
        for o in rng.choice([c for c in ids if c[:3] != m["clip"][:3]], 3, replace=False):
            b = clean[o][::-1] if rng.random() < 0.5 else clean[o]
            st = int(rng.integers(0, max(1, len(x) - len(b))))
            bab[st:st + len(b)] += b[: len(x) - st]
        noise = 0.7 * bab / (np.abs(bab).max() + 1e-9) + 0.3 * pink(len(x))
        snr = float(rng.uniform(10, 14))
        ps, pn = np.mean(w ** 2), np.mean(noise ** 2) + 1e-12
        x = x + noise * np.sqrt(ps / (pn * 10 ** (snr / 10)))
        m["snr_db"] = round(snr, 1)
    x = np.clip(x, -1, 1)
    sf.write(OUT / f"{m['clip']}.wav", x, SR, subtype="PCM_16")
json.dump({"tts": "steer-tts-edge (OnnxTTS)", "voices": VOICES, "clips": manifest}, open(HERE / "manifest.json", "w"), indent=1)
print(len(manifest), "clips ->", OUT)
