"""Crew-clip loudness manifest (docs/VOICE_STEERING.md §4d): integrated loudness and true peak of every NASA clip in
data/media/audio (ffmpeg's EBU R128 meter), and the playback gain that brings it to the TTS target (-14 LUFS).

    cd backend && uv run python tools/clip_loudness.py          # needs ffmpeg on PATH (dev only; the app never runs it)

Writes data/clip_loudness.json: {"target_lufs", "clips": {"<file name>": {"lufs", "tp_dbtp", "gain_db"}}}.
/api/clips returns `gain_db` per clip. The client plays crew audio through a GainNode at that gain, followed by a
limiter (DynamicsCompressor: threshold -1 dB, knee 0, ratio 20, attack 3 ms, release 50 ms). Most clips are already
louder than the target (gain < 0, a plain attenuation). The quiet ones need the limiter, because their sources already
peak at about +1.5 dBTP.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from app.loudness import TARGET_LUFS  # noqa: E402

DATA = HERE.parent / "data"


def measure(path: Path) -> tuple[float, float]:
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null",
                        "-"], capture_output=True, text=True, check=False)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+) LUFS", tail).group(1))
    p = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail).group(1))
    return i, p


def main():
    clips = {}
    for f in sorted((DATA / "media" / "audio").glob("*.mp3")):
        i, p = measure(f)
        clips[f.name] = {"lufs": i, "tp_dbtp": p, "gain_db": round(TARGET_LUFS - i, 1)}
        print(f.name, clips[f.name], flush=True)
    (DATA / "clip_loudness.json").write_text(json.dumps({"target_lufs": TARGET_LUFS, "meter": "ffmpeg ebur128",
                                                         "clips": clips}, indent=1) + "\n")


if __name__ == "__main__":
    main()
