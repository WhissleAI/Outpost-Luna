"""Round 11: the "real-voice" bank. There are no real kid recordings, so the kid turns are rendered from every English
voice the Mac's `say` can render (plus the Steer TTS kid voices, real_ear.iter_audio), varied toward what a laptop mic
hears from a child in a room, and decoded by the real ear (real_ear.py decode). The decodes are then treated as real.

Silent: `say -o` renders to a temporary AIFF that is read and deleted at once. Nothing is ever played; no audio is kept.

Voice split (voice-disjoint): a speaker held out is held out in every accent it ships in (Eddy UK + US, ...).
  heldout  never in train or val: the `voice_ho` decode group -> the `test_voice_heldout` set
  val      the `val` group's Mac-voice decodes (the policy fit)
  train    everything else
The app's own OS voices (render_r8.OS_VOICES: the echo the train set hears) are never held out.
Siri voices: `say -v '?'` lists two (Aman, Tara: "Hi, I'm Siri!") under the same names as the non-Siri voices, so `say -v`
cannot address them separately; whichever `say` resolves the name to is what renders.

The noise bed of a kid turn (one kind per turn, drawn):
  none        the voice alone (+ the mic chain)
  babble      3 other renders of the bank, reversed half the time, + pink noise, SNR 3-20 dB
  tv          a NASA video's soundtrack (the app's downloaded videos) through the speaker, SNR 3-15 dB
  music       synthetic chords + a beat through the speaker, SNR 5-18 dB
  os_echo     one of the app's own lines in an OS voice through speaker -> mic, -1.0..+1.5 s from the kid's start,
              10-25 dB under the kid
  crew_echo   a NASA crew clip (the app's crew audio) through speaker -> mic, same delays / levels
  room        steady room noise (pink), SNR 15-30 dB
The kid voice itself (CHAIN "r11", what the round-11 train / val / held-out decodes use): rate 140-200 wpm; pitch up
toward a child (sox `pitch` +150..+500 cents keeping tempo on 50 %, a resample speed-up 1.04-1.20 on 30 %, else none); a
laptop mic (band-pass ~150 Hz - 4-7 kHz + a light limiter) on 60 %; room reverb (RT60 0.15-0.5 s, direct path kept
strong) on 30 %. Noise SNRs: babble 5-20, TV 6-18, music 8-20, echo 12-25 dB under the kid.
CHAIN "harsh" (the first 653 decodes, kept apart in cache/real_ear_r11_harsh as an ear stress set): rate 150-230, sox
+200..+700 cents, resample 1.06-1.30, a harder limiter, reverb RT60 0.2-0.7 s on 40 % with a weaker direct path,
babble 3-20 / TV 3-15 / music 5-18 dB, echo 10-25 dB under. On it the ear's WER was ~60 % (reverb and fast speech
the worst factors), too far from what a kid at a laptop sounds like to train on.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SR = 16000
HERE = Path(__file__).resolve().parent
CHAIN = os.environ.get("VB_CHAIN", "r11")
H = CHAIN == "harsh"
APP_ASSETS = Path(os.environ.get("APP_ASSETS", Path.home() / "Library/Application Support/Outpost Luna/assets"))

# every English voice `say -v '?'` lists on this Mac that `say -o` renders (2026-11-16; 43 names)
NATURAL = ["Samantha", "Daniel", "Karen", "Moira", "Tessa", "Rishi", "Kathy", "Fred", "Ralph", "Junior",
           "Aman (English (India))", "Tara (English (India))"]
ELOQUENCE = [f"{n} (English ({a}))" for n in ("Eddy", "Flo", "Grandma", "Grandpa", "Reed", "Rocko", "Sandy", "Shelley")
             for a in ("UK", "US")]
NOVELTY = ["Albert", "Bahh", "Boing", "Bubbles", "Jester", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox"]
SUNG = ["Bad News", "Good News", "Bells", "Cellos", "Organ"]
ALL = NATURAL + ELOQUENCE + NOVELTY + SUNG

HELDOUT = ["Tara (English (India))", "Junior", "Kathy", "Eddy (English (UK))", "Eddy (English (US))",
           "Rocko (English (UK))", "Rocko (English (US))", "Sandy (English (UK))", "Sandy (English (US))", "Jester",
           "Trinoids"]
VAL = ["Fred", "Aman (English (India))", "Grandma (English (UK))", "Grandma (English (US))", "Bubbles"]
TRAIN = [v for v in ALL if v not in HELDOUT and v not in VAL]


def vgroup(v: str) -> str:
    return ("natural" if v in NATURAL else "eloquence" if v in ELOQUENCE else "novelty" if v in NOVELTY else
            "sung" if v in SUNG else "steer")


def voices_for(group: str) -> list[str]:
    return {"voice_ho": HELDOUT, "val": VAL}.get(group, TRAIN)


# Round 11 (owner review): the novelty and sung voices are not plausible kid speech (74-84 % WER, 36-37 % empty on
# the real ear), so kid turns no longer use them; their earlier decodes live in cache/real_ear_r11_odd (a stress set,
# reported only). VB_ODD=1 brings them back.
ODD = os.environ.get("VB_ODD") == "1"


def pick_voice(group: str, rng: np.random.Generator) -> str:
    """Natural / Eloquence voices most of the time; the novelty and sung voices are a small share (kids do odd voices,
    but not most of the time)."""
    vs = voices_for(group)
    odd = [v for v in vs if v in NOVELTY or v in SUNG]
    norm = [v for v in vs if v not in odd]
    draw = rng.random()          # always drawn, so every other render keeps its random stream
    pool = odd if ODD and odd and draw < 0.12 else norm
    return str(pool[int(rng.integers(len(pool)))])


# ----------------------------------------------------------------------------------------------- audio helpers
def _ffmpeg(path: str, start: float = 0.0, dur: float | None = None) -> np.ndarray | None:
    cmd = ["ffmpeg", "-v", "quiet", "-ss", f"{max(0.0, start):.2f}"] + (["-t", f"{dur:.2f}"] if dur else []) + \
        ["-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode or not r.stdout:
        return None
    return np.frombuffer(r.stdout, "<i2").astype(np.float32) / 32768.0


def say(text: str, voice: str, rate: int | None = None, cents: int = 0) -> np.ndarray | None:
    """`say -o` (silent) -> float32 16 kHz; sox `pitch` when cents != 0. The temporary AIFF is deleted at once."""
    fd, path = tempfile.mkstemp(suffix=".aiff")
    os.close(fd)
    try:
        args = ["say", "-v", voice] + (["-r", str(rate)] if rate else []) + ["-o", path, text]
        if subprocess.run(args, capture_output=True, timeout=60).returncode:
            return None
        if cents and shutil.which("sox"):
            r = subprocess.run(["sox", "-q", path, "-t", "raw", "-e", "signed", "-b", "16", "-c", "1", "-r", str(SR),
                                "-", "pitch", str(cents), "rate", str(SR)], capture_output=True, timeout=60)
            if r.returncode == 0 and r.stdout:
                return np.frombuffer(r.stdout, "<i2").astype(np.float32) / 32768.0
        return _ffmpeg(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _norm(x, peak=0.5):
    return (peak * x / (np.abs(x).max() + 1e-9)).astype(np.float32)


def laptop_mic(x, rng):
    from scipy.signal import butter, lfilter
    hi = float(rng.uniform(4000, 7000))
    b, a = butter(3, [float(rng.uniform(120, 250)) / (SR / 2), hi / (SR / 2)], "band")
    y = lfilter(b, a, x).astype(np.float32)
    k = 2.0 if H else 1.2
    y = np.tanh(k * _norm(y, 0.6)) / np.tanh(k)           # a soft AGC / limiter
    return _norm(y), {"mic_hi": int(hi)}


def reverb(x, rng, rt=None):
    from scipy.signal import fftconvolve
    rt = float(rt or (rng.uniform(0.2, 0.7) if H else rng.uniform(0.15, 0.5)))
    n = int(rt * SR)
    rir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    rir[0] = 1.0 / (rng.uniform(0.3, 0.8) if H else rng.uniform(0.1, 0.35))
    return _norm(fftconvolve(x, rir)[: len(x) + n // 3]), round(rt, 2)


def pink(n, rng):
    pk = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) / np.sqrt(np.arange(1, n // 2 + 2)), n)
    return _norm(pk, 1.0)


def mix_at(x, noise, snr_db, speech_power):
    pn = np.mean(noise ** 2) + 1e-12
    return x + noise * np.sqrt(speech_power / (pn * 10 ** (snr_db / 10)))


_FILES: dict = {}


def _media(kind: str) -> list[str]:
    if kind not in _FILES:
        if kind == "tv":
            fs = sorted(glob.glob(str(APP_ASSETS / "videos" / "*.mp4")))
        else:
            fs = sorted(f for f in glob.glob(str(APP_ASSETS / "crew" / "audio" / "*.mp3")) if "-ck-" not in f)
        _FILES[kind] = fs
    return _FILES[kind]


def _dur(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def media_seg(kind: str, rng, dur: float):
    fs = _media(kind)
    if not fs:
        return None, None
    f = fs[int(rng.integers(len(fs)))]
    d = _dur(f)
    st = float(rng.uniform(0, max(0.0, d - dur - 0.5)))
    return _ffmpeg(f, st, dur), Path(f).name


ECHO_LINES = None


def app_lines() -> list[str]:
    global ECHO_LINES
    if ECHO_LINES is None:
        import pools as P
        ECHO_LINES = list(P.CAPCOM_LINES) + [x[0] for x in P.OFFERS.values()]
    return ECHO_LINES


# ----------------------------------------------------------------------------------------------- the renders
NOISES = ["none", "babble", "tv", "music", "os_echo", "crew_echo", "room"]
NOISE_P = [0.16, 0.2, 0.14, 0.1, 0.16, 0.12, 0.12]


def render_kid(j: dict, rng: np.random.Generator, bab_pool: list) -> tuple[np.ndarray | None, dict]:
    """A kid turn in a Mac voice through the room and a laptop mic, with one noise bed. -> (audio, meta)."""
    import render_r8 as R8
    v = j.get("voice") or pick_voice(j["group"], rng)
    rate = int(rng.uniform(150, 230) if H else rng.uniform(140, 200))
    odd = v in NOVELTY or v in SUNG
    pr = rng.random()
    cents = 0 if odd or pr >= 0.5 else int(rng.uniform(200, 700) if H else rng.uniform(150, 500))
    x = say(j["text"], v, rate, cents)
    if x is None or not len(x):
        return None, {"skip": "say failed", "voice": v}
    speed = 1.0
    if not odd and 0.5 <= pr < 0.8:          # resample speed-up: pitch and tempo together
        from scipy.signal import resample
        speed = float(rng.uniform(1.06, 1.30) if H else rng.uniform(1.04, 1.20))
        x = resample(x, int(len(x) / speed)).astype(np.float32)
    x = _norm(x)
    clean = x.copy()
    meta = {"voice": v, "vgroup": vgroup(v), "rate": rate, "cents": cents, "speed": round(speed, 2), "chain": CHAIN}
    if rng.random() < (0.4 if H else 0.3):
        x, meta["rt60"] = reverb(x, rng)
    if rng.random() < 0.6:
        x, m = laptop_mic(x, rng)
        meta.update(m)
    lead, tail = float(rng.uniform(0.2, 0.5)), 1.2
    meta["speech_s"] = [round(lead, 3), round(lead + len(x) / SR, 3)]
    y = np.concatenate([np.zeros(int(lead * SR), np.float32), x, np.zeros(int(tail * SR), np.float32)])
    ps = float(np.mean(x ** 2))
    noise = str(rng.choice(NOISES, p=NOISE_P))
    over = j.get("under")               # round 14 (real_ear r14 jobs): the kid talks over our own line, always
    if over:
        noise = "os_echo"
    if noise == "babble" and len(bab_pool) < 3:
        noise = "room"
    meta["noise"] = noise
    if noise == "babble":
        bab = np.zeros_like(y)
        for o in rng.choice(len(bab_pool), 3, replace=False):
            b = bab_pool[o][::-1] if rng.random() < 0.5 else bab_pool[o]
            st = int(rng.integers(0, max(1, len(y) - len(b))))
            bab[st:st + len(b)] += b[: len(y) - st]
        nz = 0.7 * _norm(bab, 1.0) + 0.3 * pink(len(y), rng)
        snr = float(rng.uniform(3, 20) if H else rng.uniform(5, 20))
        y = mix_at(y, nz, snr, ps)
        meta["snr_db"] = round(snr, 1)
    elif noise in ("tv", "music"):
        if noise == "tv":
            seg, src = media_seg("tv", rng, len(y) / SR)
        else:
            seg, src = R8.music(rng, len(y) / SR), "music"
        if seg is None or not len(seg):
            noise = meta["noise"] = "room"
        else:
            s2, _ = R8.speaker_to_mic(seg, rng)
            nz = np.zeros_like(y)
            nz[: min(len(y), len(s2))] = s2[: len(y)]
            snr = float((rng.uniform(3, 15) if H else rng.uniform(6, 18)) if noise == "tv" else
                        (rng.uniform(5, 18) if H else rng.uniform(8, 20)))
            y = mix_at(y, nz, snr, ps)
            meta.update(snr_db=round(snr, 1), src=src)
    elif noise in ("os_echo", "crew_echo"):
        if over:                        # round 14: the line that was playing, in the voice the app played it in
            ov, line = over["voice"], over["line"]
            e = say(line, ov)
            src = {"echo_voice": ov, "line": line, "over_play": True}
        elif noise == "os_echo":
            ov = str(rng.choice(R8.OS_VOICES))
            line = str(rng.choice(app_lines()))
            e = say(line, ov)
            src = {"echo_voice": ov, "line": line}
        else:
            e, nm = media_seg("crew", rng, float(rng.uniform(2.0, 5.0)))
            src = {"clip": nm}
        if e is None or not len(e):
            noise = meta["noise"] = "room"
        else:
            ref = _norm(e)
            e2, m = R8.speaker_to_mic(ref, rng)
            if over:
                # round 14: our line started 0.3-2 s before the kid (they talk over it); the kid from 3 dB under to
                # 12 dB over our echo (docs/ARC_ABI2.md section 8: kid turns over playback, -6..+5 dB around it)
                delay = float(rng.uniform(-2.0, -0.3))
                under = float(rng.uniform(-3, 12))
            else:
                delay = float(rng.uniform(-1.0, 1.5))           # the echo's start vs the kid's start
                under = float(rng.uniform(10, 25) if H else rng.uniform(12, 25))   # dB under the kid
            if over and lead + delay < 0:   # round 14: the clip opens on our line (the ear hears it from its start)
                pad = int(-(lead + delay) * SR) + 1
                y = np.concatenate([np.zeros(pad, np.float32), y])
                lead += pad / SR
                meta["speech_s"] = [round(v + pad / SR, 3) for v in meta["speech_s"]]
            st = int(max(0.0, lead + delay) * SR)
            e2 = e2[int(max(0.0, -(lead + delay)) * SR):]
            if st + len(e2) > len(y):
                y = np.concatenate([y, np.zeros(st + len(e2) - len(y), np.float32)])
            nz = np.zeros_like(y)
            nz[st:st + len(e2)] = e2
            # round 13: the app's playback as echoref.js hands it to the ear (feed_ref), stamped when it goes to the
            # speaker: e2's sample 0 (speaker_to_mic adds the output latency after it), less what was trimmed
            meta["_ref"] = [((st - int(max(0.0, -(lead + delay)) * SR)) / SR, ref)]
            pe = float(np.mean(e2 ** 2)) + 1e-12
            fmix = float(np.sqrt(ps / (pe * 10 ** (under / 10))))
            y = y + nz * fmix
            meta.update(echo_delay=round(delay, 2), echo_under_db=round(under, 1), **src)
            if m.get("_path"):        # round 14: the room, for the decode's canceller warm-up (render_r8.warm_up)
                meta["_path"] = {**m["_path"], "mix": m["_path"].get("mix", 1.0) * fmix}
    if noise == "room":
        snr = float(rng.uniform(15, 30))
        y = mix_at(y, pink(len(y), rng), snr, ps)
        meta["snr_db"] = round(snr, 1)
    bab_pool.append(clean)
    del bab_pool[:-40]
    if meta.get("_path"):         # the clip's final level change applies to its echo too
        meta["_path"]["mix"] *= 0.7 / (np.abs(y).max() + 1e-9)
    return _norm(y, 0.7), meta


def render_echo(j: dict, rng: np.random.Generator) -> tuple[np.ndarray | None, dict]:
    """Echo bank: one of the app's lines in voice j["voice"] (or a crew clip), through the laptop speaker into its mic,
    nothing else. The ear should return nothing; the analysis counts what leaks through."""
    import render_r8 as R8
    if j.get("clip"):
        e, nm = media_seg("crew", rng, float(rng.uniform(2.5, 5.0)))
        meta = {"clip": nm, "vgroup": "crew"}
    else:
        e = say(j["text"], j["voice"])
        meta = {"voice": j["voice"], "vgroup": vgroup(j["voice"])}
    if e is None or not len(e):
        return None, {"skip": "render failed"}
    ref = _norm(e)
    y, m = R8.speaker_to_mic(ref, rng)
    meta["_ref"] = [(0.0, ref)]   # round 13: our own playback (guide line or crew clip), the ear's reference (echoref.js)
    return y, {**meta, **m}
