"""Round 8 audio for the real-ear decodes (real_ear.py): the sounds the mic hears that are NOT the kid.

  os_voice   the app's own line spoken by an OS voice (macOS `say`; the voices the app picks from) or by the Nora voice
             pack clip when the line has one (feat/voice-pack backend/data/voice_pack), played through the laptop
             speaker into the mic: band-limited, room reverb, -10..-25 dB, room noise
  file       a NASA crew recording segment (backend/data/media/audio, the clips the video overlay plays) through the
             same speaker -> mic chain: the video's narration leaking into the mic
  music      synthetic music (chords + a beat) through the speaker: the video's soundtrack
  say_kid    a kid line in an OS voice, pitched up (the fallback kid voices once Steer TTS is gone, feat/os-voices)
Silent: nothing is ever played through the speakers (`say -o` renders to a file; no `afplay`, no volume change).
Audio stays in memory: `say` and ffmpeg write to a temporary file that is deleted at once (no audio is kept on disk).
macOS only for `say`; elsewhere os_voice falls back to the Nora clip or is skipped.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR = 16000
HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "backend" / "data"
OS_VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Tessa", "Reed", "Flo", "Shelley", "Rishi"]
KID_VOICES = ["Samantha", "Karen", "Tessa", "Moira", "Flo", "Shelley"]   # (never the novelty voices)


def _decode_file(path: str, start: float = 0.0, dur: float | None = None) -> np.ndarray | None:
    """Any audio file -> float32 mono 16 kHz (ffmpeg, piped: nothing written)."""
    if not shutil.which("ffmpeg"):
        return None
    cmd = ["ffmpeg", "-v", "quiet", "-ss", f"{max(0.0, start):.2f}"] + (["-t", f"{dur:.2f}"] if dur else []) + \
        ["-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode or not r.stdout:
        return None
    return np.frombuffer(r.stdout, "<i2").astype(np.float32) / 32768.0


def say(text: str, voice: str, rate: int | None = None) -> np.ndarray | None:
    """macOS `say` -> float32 16 kHz; the temporary AIFF is deleted at once."""
    if sys.platform != "darwin" or not shutil.which("say"):
        return None
    fd, path = tempfile.mkstemp(suffix=".aiff")
    os.close(fd)
    try:
        args = ["say", "-v", voice] + (["-r", str(rate)] if rate else []) + ["-o", path, text]
        if subprocess.run(args, capture_output=True, timeout=60).returncode:
            return None
        return _decode_file(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


_PACK: dict = {}


def pack_clip(text: str) -> np.ndarray | None:
    """The Nora voice-pack clip of this line (feat/voice-pack), when the pack is on this checkout."""
    if "idx" not in _PACK:
        _PACK["idx"] = {}
        for base in [DATA / "voice_pack", Path(os.environ.get("VOICE_PACK_DIR", "/nonexistent"))]:
            f = base / "index.json"
            if f.exists():
                import json
                d = json.loads(f.read_text())
                for k, v in (d.get("clips") or d.get("lines") or {}).items() if isinstance(d.get("clips") or
                                                                                         d.get("lines"), dict) else []:
                    p = v.get("file") if isinstance(v, dict) else v
                    if p:
                        _PACK["idx"][k.lower().strip(" .!?")] = base / "clips" / Path(p).name
                break
    p = _PACK["idx"].get(text.lower().strip(" .!?"))
    return _decode_file(str(p)) if p and Path(p).exists() else None


def music(rng: np.random.Generator, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    root = rng.choice([196.0, 220.0, 261.6, 293.7])
    x = np.zeros(n, np.float32)
    for k, ratio in enumerate((1.0, 1.25, 1.5)):
        x += np.sin(2 * np.pi * root * ratio * t * (1 + 0.002 * k)).astype(np.float32) * 0.2
    beat = (np.sin(2 * np.pi * 2.0 * t) > 0.95).astype(np.float32) * rng.standard_normal(n).astype(np.float32) * 0.3
    return x + beat


def speaker_to_mic(x: np.ndarray, rng: np.random.Generator, noise_pool: list | None = None) -> tuple[np.ndarray, dict]:
    """A laptop speaker heard by its own mic: high-pass ~250 Hz, small-room reverb, -10..-25 dB, steady room noise."""
    from scipy.signal import butter, fftconvolve, lfilter
    b, a = butter(2, 250 / (SR / 2), "high")
    y = lfilter(b, a, x).astype(np.float32)
    rt = float(rng.uniform(0.25, 0.7))
    n = int(rt * SR)
    rir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    rir[0] = 1.0 / rng.uniform(0.2, 0.6)
    y = fftconvolve(y, rir)[: len(y) + n // 3].astype(np.float32)
    gain_db = float(rng.uniform(-25, -10))
    y = y / (np.abs(y).max() + 1e-9) * 0.5 * 10 ** (gain_db / 20)
    lead, tail = rng.uniform(0.1, 0.4), 1.0
    y = np.concatenate([np.zeros(int(lead * SR), np.float32), y, np.zeros(int(tail * SR), np.float32)])
    room = rng.standard_normal(len(y)).astype(np.float32) * 10 ** (float(rng.uniform(-55, -42)) / 20)
    return y + room, {"rt60": round(rt, 2), "gain_db": round(gain_db, 1)}


def render(j: dict, rng: np.random.Generator) -> tuple[np.ndarray | None, dict]:
    """A round-8 job's audio (float32 16 kHz) and its render meta; (None, why) when it cannot be rendered here."""
    a = j.get("audio") or {}
    kind = a.get("kind")
    if kind == "os_voice":
        clip = pack_clip(j["text"]) if rng.random() < 0.5 else None
        voice = "nora_pack" if clip is not None else str(rng.choice(OS_VOICES))
        x = clip if clip is not None else say(j["text"], voice)
        if x is None:
            return None, {"skip": "no os voice here"}
        if a.get("beep"):     # Houston relayed by CAPCOM: a static beep first (rendered, never played)
            t = np.arange(int(0.25 * SR)) / SR
            beep = (0.2 * np.sin(2 * np.pi * 1200 * t) + 0.05 * rng.standard_normal(len(t))).astype(np.float32)
            x = np.concatenate([beep, np.zeros(int(0.1 * SR), np.float32), x])
        y, m = speaker_to_mic(x, rng)
        # round 13: our own line, fed to the ear as its reference when it goes to the speaker (echoref.js)
        return y, {"voice": voice, **m, "_ref": [(0.0, x.astype(np.float32))]}
    if kind == "file":
        f = a["file"]
        p = DATA / f.lstrip("/") if not Path(f).is_absolute() or not Path(f).exists() else Path(f)
        if not p.exists():
            p = DATA / "media" / "audio" / Path(f).name
        x = _decode_file(str(p), float(a.get("start", 0)) - 0.2, float(a.get("dur", 3)) + 0.4)
        if x is None or not len(x):
            return None, {"skip": f"no audio {p.name}"}
        y, m = speaker_to_mic(x, rng)
        return y, {"src": p.name, **m}
    if kind == "music":
        y, m = speaker_to_mic(music(rng, float(rng.uniform(2.0, 4.0))), rng)
        return y, {"src": "music", **m}
    if kind == "say_kid":
        v = str(rng.choice(KID_VOICES))
        x = say(j["text"], v, rate=int(rng.uniform(150, 210)))
        if x is None:
            return None, {"skip": "no say"}
        from scipy.signal import resample
        f = float(rng.uniform(1.08, 1.25))           # pitch / speed up toward a child's voice
        x = resample(x, int(len(x) / f)).astype(np.float32)
        x = 0.5 * x / (np.abs(x).max() + 1e-9)
        lead = np.zeros(int(rng.uniform(0.2, 0.5) * SR), np.float32)
        return np.concatenate([lead, x, np.zeros(int(1.2 * SR), np.float32)]), {"voice": v, "pitch": round(f, 2)}
    return None, {"skip": f"kind {kind}"}
