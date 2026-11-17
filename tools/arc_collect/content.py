"""What the app says: the recorded voice-pack lines, the lines it speaks live, crew audio and NASA video sound.
Plus the guided session's prompts.

Sources, in order (first that exists):
    voice pack   <repo>/backend/data/voice_pack (index.json + clips/*.mp3, in git), else the installed app's
                 <user data>/Outpost Luna/assets/voice
    crew audio   --media-dir, the app's assets/crew, <repo>/backend/data/media/desktop/audio, <repo>/backend/data/media/audio
                 (`make data`), else the 7 s crew fixture in git (backend/tests/fixtures/crew_orientale_16k.s16le)
    NASA video   --media-dir, the app's assets/videos and cache/video, <repo>/backend/data/video_cache (*.mp4); the sound
                 is decoded with ffmpeg when it is installed, otherwise skipped (the manifest says so)
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import numpy as np

from devices import app_user_dir

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# Lines the app speaks LIVE with the OS voice (backend/data/voice_pack/lines_live.md), with typical values filled in.
LIVE_LINES = [
    # readbacks with live numbers (backend/app/mission/sim.py, gameplay.py)
    "Copy. Heaters now at 40%.",
    "Copy. Life support now at 55%.",
    "Rover back in about 3 hours. It used 28% battery.",
    "Rover turning around. Home in 2 hours.",
    "The rover is out. Back in about 4 hours.",
    "Sample logged. Science +5.",
    "That puts 80% into heaters, almost nothing else. Are you sure?",
    "Turning off life support can hurt the crew. Are you sure?",
    "The crew needs rest first. Shelter ready in 2 hours.",
    "Pick one: drill the ice or scan the ridge.",
    "Okay, we've got this. Power is low, so the rover waits.",
    "Houston here. Your words took 1.3 seconds to reach us. Short commands work best.",
    "There is no load called lights.",
    "The rover is busy. Back in 3 hours.",
    # Houston (its own role voice, always live)
    "Houston here. We copy you, Commander. Solar storm in twenty minutes. Get the crew to the shelter.",
    "Houston here. Good work on the power budget. The batteries will last the night.",
    "Houston, standing by. Tell us when the rover is home.",
    # coordinates and place answers (frontend/src/main.js, missions.js, academy/guide.py)
    "That spot is 89.9 degrees south, 0 degrees east. That's Shackleton crater, right at the south pole.",
    "That spot is 23.5 degrees north, 47.4 degrees west. Near Aristarchus, the brightest crater on the Moon.",
    "You found it. Tycho. Its bright rays stretch across the near side.",
    "That's Copernicus. Keep looking. The one we want is further south.",
    "That's Mare Imbrium. Try the dark patch to the right.",
    # Director answers, debrief with an open score
    "Nice flying, Commander. Grade B, 340 points.",
    "Nice flying, Cadet. Grade A, 412 points.",
    "The Moon has almost no air, so there is nothing to carry sound. Astronauts talk by radio.",
    "A day on the Moon lasts about two weeks, and so does a night.",
    "The far side is not dark. It gets just as much sunlight as the side we see.",
    "Shackleton crater is about twenty one kilometres across, and its floor never sees the Sun.",
    "Water ice hides in craters near the poles, where it is always colder than minus one hundred and fifty degrees.",
    "Gravity on the Moon is about one sixth of Earth's. You could jump six times higher.",
    # vocabulary lines (slowed on purpose in the app; here at the voice's own pace)
    "Regolith. Regolith is the dusty, broken rock that covers the Moon.",
    "Terminator. The terminator is the line between day and night.",
]


def _first_dir(cands) -> Path | None:
    for c in cands:
        if c and Path(c).expanduser().is_dir():
            return Path(c).expanduser()
    return None


# ---- voice pack ----------------------------------------------------------------------------------------------------
def voice_pack_dir() -> Path | None:
    u = app_user_dir()
    for c in (REPO / "backend" / "data" / "voice_pack", (u / "assets" / "voice") if u else None):
        if c and (Path(c) / "index.json").exists():
            return Path(c)
    return None


def pack_clips(pack: Path | None = None) -> list[dict]:
    """[{key, text, role, file (absolute), dur, voice}] from the voice pack's index.json."""
    pack = pack or voice_pack_dir()
    if not pack:
        return []
    idx = json.loads((pack / "index.json").read_text(encoding="utf-8"))
    out = []
    for key, c in sorted(idx.get("clips", {}).items()):
        f = pack / c["file"]
        if f.exists():
            out.append({"key": key, "text": c.get("text", key), "role": c.get("role"), "file": str(f),
                        "dur": c.get("dur"), "voice": c.get("voice") or idx.get("voice"),
                        "voice_name": idx.get("voice_name")})
    return out


def pack_line_texts(n: int | None, seed: int = 11) -> list[str]:
    """Texts of the voice pack's fixed lines (lines.json), a deterministic sample of n (all when n is None)."""
    for p in (REPO / "backend" / "data" / "voice_pack" / "lines.json",):
        if p.exists():
            lines = [l["text"] for l in json.loads(p.read_text(encoding="utf-8"))["lines"]]
            break
    else:
        lines = [c["text"] for c in pack_clips()]
    if n is None or n >= len(lines):
        return lines
    rng = random.Random(seed)
    return rng.sample(lines, n)


# ---- crew + video --------------------------------------------------------------------------------------------------
def crew_files(media_dir: str | None = None) -> list[Path]:
    u = app_user_dir()
    d = _first_dir([media_dir, (u / "assets" / "crew") if u else None,
                    REPO / "backend" / "data" / "media" / "desktop" / "audio",
                    REPO / "backend" / "data" / "media" / "audio"])
    if not d:
        return []
    return sorted(p for p in d.rglob("*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".ogg"))


CREW_FIXTURE = REPO / "backend" / "tests" / "fixtures" / "crew_orientale_16k.s16le"


def video_files(media_dir: str | None = None) -> list[Path]:
    u = app_user_dir()
    out = []
    for d in (media_dir, (u / "assets" / "videos") if u else None, (u / "cache" / "video") if u else None,
              REPO / "backend" / "data" / "video_cache"):
        if d and Path(d).expanduser().is_dir():
            out += sorted(Path(d).expanduser().rglob("*.mp4"))
    return out


def load_audio(path: str | Path, start_s: float = 0.0, dur_s: float | None = None) -> tuple[np.ndarray, int]:
    """Mono float32 from a WAV / MP3 / FLAC (soundfile), a raw 16 kHz s16le fixture, or an MP4's sound (ffmpeg)."""
    p = Path(path)
    if p.suffix == ".s16le":
        x = np.fromfile(p, "<i2").astype(np.float32) / 32768
        sr = 16000
    elif p.suffix.lower() in (".mp4", ".m4a", ".mov", ".webm"):
        ff = shutil.which("ffmpeg")
        if not ff:
            raise RuntimeError("ffmpeg not installed: video sound skipped")
        cmd = [ff, "-v", "error", "-ss", f"{start_s:.2f}"] + (["-t", f"{dur_s:.2f}"] if dur_s else []) + \
              ["-i", str(p), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr.decode(errors='replace')[:160]}")
        x = np.frombuffer(r.stdout, "<f4").astype(np.float32)
        return x, 48000
    else:
        import soundfile as sf
        with sf.SoundFile(str(p)) as f:
            sr = f.samplerate
            if start_s:
                f.seek(min(f.frames, int(start_s * sr)))
            x = f.read(int(dur_s * sr) if dur_s else -1, dtype="float32", always_2d=True).mean(axis=1)
        return x, sr
    a = int(start_s * sr)
    b = len(x) if dur_s is None else a + int(dur_s * sr)
    return x[a:b], sr


# ---- guided prompts ------------------------------------------------------------------------------------------------
ADDRESSED = [  # said TO THE APP (the router's intents: coverage.json router_intents)
    "Open the comm panel.", "Pause the video.", "Where is Shackleton crater?", "Turn on the heaters.",
    "How far away is the Moon?", "Show me Tycho.", "Go to the far side.", "Start the mission.", "Next.",
    "Can you say that again?", "Send the rover to the ridge.", "Zoom in.", "Zoom out.", "Skip the tour.",
    "What's that crater?", "Take me back.", "Speed up time.", "Open the power panel.", "Why is it dark there?",
    "Put the crew in the shelter.", "Yes.", "No.", "Done!", "Go slower please.", "Mute the sound.",
    "What is regolith?", "Pick the south pole site.", "Show the rover view.", "Resume.", "I want to fly again.",
]
NOT_ADDRESSED = [  # said to SOMEONE ELSE in the room (the app should ignore these)
    "Can I have a snack after this?", "Whose turn is it?", "Look at this crater, it's huge!",
    "Wait, I'm almost done.", "Can you pass me the charger?", "That was so cool.", "Mom, come look at this.",
    "I'm going to beat your score.", "Hold on, the dog is barking.", "Do you want to try next?",
    "I think it's the big one on the left.", "Shh, I'm listening.", "Can you turn the light on?",
    "No, you already had a go.", "What time is dinner?", "I'll be right there.",
]
BARGE = [  # said OVER the app while it is talking
    "Stop.", "Wait, wait.", "Skip this.", "Hold on, what's that?", "No, go back.", "I already know that.",
    "Pause.", "Okay, okay, next.", "Wait, say that again.", "Can we do the rover instead?",
]


def guided_plan(minutes: float, seed: int = 7) -> list[dict]:
    """~minutes of prompts: addressed 40%, not addressed 30%, barge-in 30%, shuffled with no long runs of one kind.
    Each prompt: kind, label (addressed / not_addressed / barge_in), say (the line), shown text."""
    rng = random.Random(seed)
    per = 13.0                                         # seconds per prompt incl. reading time and the app's lines
    n = max(3, int(minutes * 60 / per))
    kinds = (["addressed"] * round(n * 0.4) + ["not_addressed"] * round(n * 0.3))
    kinds += ["barge_in"] * (n - len(kinds))
    rng.shuffle(kinds)
    pools = {"addressed": ADDRESSED[:], "not_addressed": NOT_ADDRESSED[:], "barge_in": BARGE[:]}
    for p in pools.values():
        rng.shuffle(p)
    out = []
    for i, k in enumerate(kinds):
        pool = pools[k]
        say = pool[i % len(pool)]
        head = {"addressed": "Say this TO THE APP", "not_addressed": "Say this to SOMEONE ELSE in the room",
                "barge_in": "TALK OVER THE APP NOW"}[k]
        out.append({"i": i, "kind": k, "label": k, "say": say, "head": head})
    return out
