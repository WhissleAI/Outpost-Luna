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


# Round 14: the speaker -> mic path, calibrated to the real laptop of docs/ARC_ABI2.md section 8 (MacBook Pro M3 Pro,
# built-in speakers at 75 %): round trip 141-159 ms, our echo at the mic -29 dBFS (0 dB block) to -44 dBFS (-18 dB),
# room floor -57.5 dBFS; the speaker sits centimetres from the mic, so the direct path dominates a short laptop-room
# reverb. Real own-line playback_leak median there: 0.75. The round-8..13 path ("r13": 0.1-0.4 s latency, a long
# reverb whose tail carried ~20 dB more energy than the direct path, -10..-25 dB, a -55..-42 dB floor) gave a median
# leak of 0.38 on round 13's echo clips: the canceller cannot explain a tail that loud. SPEAKER_PROFILE=r13 (or
# profile="r13") reproduces the round-13 renders exactly (same draws).
SPEAKER_PROFILES = ("laptop", "r13")
SPEAKER_PROFILE = os.environ.get("SPEAKER_PROFILE", "laptop")
LAPTOP = {"delay_s": (0.141, 0.159), "rt60": (0.12, 0.3), "drr_db": (6.0, 16.0), "echo_dbfs": (-44.0, -29.0),
          "floor_dbfs": (-59.0, -56.0)}


def speaker_to_mic(x: np.ndarray, rng: np.random.Generator, noise_pool: list | None = None,
                   profile: str | None = None) -> tuple[np.ndarray, dict]:
    """A laptop speaker heard by its own mic: high-pass ~250 Hz (small drivers), a short room reverb under the direct
    path, the output latency, the echo level and the room floor of the real laptop (profile "laptop", round 14), or
    the round-8..13 path (profile "r13"). The reference the ear gets is `x` stamped at sample 0 (the moment the line is
    handed to the speaker, as echoref.js stamps it); the latency is added after it."""
    from scipy.signal import butter, fftconvolve, lfilter
    prof = profile or SPEAKER_PROFILE
    hp = 250.0 if prof == "r13" else LAPTOP.get("hp_hz", 250.0)
    if hp:
        b, a = butter(2, hp / (SR / 2), "high")
        y = lfilter(b, a, x).astype(np.float32)
    else:
        y = np.asarray(x, np.float32)
    if prof == "r13":
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
        return y + room, {"rt60": round(rt, 2), "gain_db": round(gain_db, 1), "profile": "r13"}
    L = LAPTOP
    rt = float(rng.uniform(*L["rt60"]))
    drr = float(rng.uniform(*L["drr_db"]))
    n = max(2, int(rt * SR))
    tail = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    tail[:int(0.002 * SR)] = 0.0                       # the first reflections arrive a few ms after the direct sound
    tail = tail / (np.sqrt(np.sum(tail ** 2)) + 1e-9) * 10 ** (-drr / 20)
    tail[0] = 1.0                                      # the direct path (unit energy) over the reverb tail
    y = fftconvolve(y, tail)[: len(y) + n // 3].astype(np.float32)
    act = np.abs(y) > 0.05 * (np.abs(y).max() + 1e-9)
    rms = float(np.sqrt(np.mean(y[act] ** 2))) if act.any() else 1e-9
    level = float(rng.uniform(*L["echo_dbfs"]))
    gain = 10 ** (level / 20) / (rms + 1e-12)
    y = y * gain
    delay = float(rng.uniform(*L["delay_s"]))
    y = np.concatenate([np.zeros(int(delay * SR), np.float32), y, np.zeros(SR, np.float32)]).astype(np.float32)
    floor = float(rng.uniform(*L["floor_dbfs"]))
    room = rng.standard_normal(len(y)).astype(np.float32) * 10 ** (floor / 20)
    # `_path`: this room, so the decode can warm the ear's canceller up on earlier playback through the SAME path
    # (warm_up below); private: real_ear pops it before writing the render meta
    return y + room, {"rt60": round(rt, 2), "drr_db": round(drr, 1), "echo_dbfs": round(level, 1),
                      "delay_ms": round(delay * 1000), "floor_dbfs": round(floor, 1), "profile": "laptop",
                      "_path": {"hp": hp, "tail": tail.astype(np.float32), "gain": gain, "delay": delay,
                                "floor": floor, "mix": 1.0}}


# Round 14: the ear's echo canceller adapts to the room over the lines it hears. Live, the stream has heard our earlier
# lines before the turn (it reopens only after EAR_STREAM_MAX_S idle: 24 restarts in the 25 min of section 8); a decode
# that opens a fresh stream per clip starts it unconverged. Measured (real_ear.py leak, the app's ear): a dry,
# perfectly aligned echo through a fresh stream read a median leak of 0.53 at the laptop's 150 ms latency (0.72 at
# 0 ms); after 2 earlier lines through the same path, 0.85. WARM_LINES earlier lines (the clip's own reference again,
# through the same room: the canceller learns the room, not the words) are decoded before the clip, and their messages
# dropped. 0 = round 13's fresh stream.
WARM_LINES = int(os.environ.get("EAR_WARM_LINES", "1"))
WARM_GAP_S = 1.5


def apply_path(x: np.ndarray, P: dict, rng: np.random.Generator) -> np.ndarray:
    """`x` through a room speaker_to_mic drew (its `_path`): the same filter, reverb, level, latency and floor, times
    the mix factor the caller applied to that echo in its clip."""
    from scipy.signal import butter, fftconvolve, lfilter
    y = np.asarray(x, np.float32)
    if P.get("hp"):
        b, a = butter(2, P["hp"] / (SR / 2), "high")
        y = lfilter(b, a, y).astype(np.float32)
    t = P["tail"]
    y = fftconvolve(y, t)[: len(y) + len(t) // 3].astype(np.float32) * float(P["gain"]) * float(P.get("mix", 1.0))
    y = np.concatenate([np.zeros(int(P["delay"] * SR), np.float32), y, np.zeros(int(WARM_GAP_S * SR), np.float32)])
    return (y + rng.standard_normal(len(y)).astype(np.float32) * 10 ** (P["floor"] / 20)).astype(np.float32)


def warm_up(refs: list, P: dict | None, rng: np.random.Generator, n: int | None = None):
    """-> (int16 PCM bytes, [(at, ref)], seconds) of `n` earlier playbacks to feed the ear before a clip whose own
    playback (refs) went through room P; (b"", [], 0.0) when there is nothing to warm (no reference / no path)."""
    n = WARM_LINES if n is None else n
    if not n or not refs or not P:
        return b"", [], 0.0
    segs, rr, t = [], [], 0.0
    src = refs[0][1]
    for _ in range(n):
        y = apply_path(src, P, rng)
        rr.append((t, src))
        segs.append(y)
        t += len(y) / SR
    x = np.concatenate(segs)
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes(), rr, t


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
