"""Record the voice pack (docs/VOICE_PACK.md): every line in backend/data/voice_pack/lines.json, spoken by the macOS
Spoken Content system voice, which must be "Siri Voice 1" (com.apple.siri.natural.Nora). macOS only.

    make voice-pack                         (= cd model_server && uv run python tools/voice_pack_record.py)
    … --check                               only verify the system voice and list what would be recorded
    … --limit 20                            record at most 20 lines (a quick listen)

Siri voices cannot be named with `say -v` (speech channel error -244), so each line is rendered with plain
`say -o …` (no -v, no -r), which speaks with the user's System voice. This script never changes that setting: it
reads it (defaults com.apple.Accessibility SpokenContentDefaultVoiceSelectionsByLanguage) before every batch and
again at the end, and refuses to record with any other voice.

Per line: render at the voice's OWN pace with its own pauses (no `say -r`, exactly as the app speaks at 1x: a forced
rate audibly degrades Siri's prosody; app/tts_os.SayEngine, os_voices.NATIVE_BAND), trim the
leading / trailing silence, normalise loudness (speech RMS to TARGET_RMS_DBFS, peaks under PEAK_DBFS), encode mono MP3
(MP3_KBPS kbps CBR at SR Hz, libsndfile/LAME: deterministic), decode it back and estimate the word timings on exactly
the audio the app will play (os_voices.estimate_timings, silence-snapped, the estimator the live macOS path uses).

Incremental: a line is re-rendered only when its text, role rate, voice or this recipe changed (`recipe` hash), or its
clip is missing / corrupt. Each batch is rendered between two voice checks and committed; if the voice is not Nora at
the end, every clip of this run is discarded and the previous index restored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import os_voices as ov  # noqa: E402
from app.voice_pack import clip_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "backend/data/voice_pack"
VOICE_ID = "com.apple.siri.natural.Nora"
VOICE_NAME = "Siri Voice 1 (Nora)"
SR = 22050
MP3_KBPS, MP3_LEVEL = 48, 0.75      # libsndfile compression level 0.75 = 48 kbps CBR at 22.05 kHz (MPEG-2 layer III)
TARGET_RMS_DBFS, PEAK_DBFS = -20.0, -1.0
PAD_S = 0.04                        # silence kept at each end after trimming
BATCH = 24
RECIPE = f"v2|say-native|{SR}|mp3-{MP3_KBPS}|rms{TARGET_RMS_DBFS}|pk{PEAK_DBFS}|pad{PAD_S}"
SETTING = "System Settings → Accessibility → Spoken Content → System voice → Siri Voice 1"


def system_voice() -> str | None:
    """The Spoken Content system voice id (read only, never changed)."""
    import plistlib
    try:
        out = subprocess.run(["/usr/bin/defaults", "export", "com.apple.Accessibility", "-"], capture_output=True,
                             timeout=10).stdout
        return ov.spoken_content_voice(plistlib.loads(out).get("SpokenContentDefaultVoiceSelectionsByLanguage"))
    except Exception:  # noqa: BLE001
        return None


def require_voice(when: str) -> None:
    v = system_voice()
    if v != VOICE_ID:
        sys.exit(f"voice pack: the macOS System voice is {v or 'unreadable'}, not {VOICE_ID} ({when}).\n"
                 f"  Set {SETTING}, then run `make voice-pack` again. (This script never changes the setting.)")


def recipe_hash(text: str) -> str:
    return hashlib.sha256(f"{RECIPE}|{VOICE_ID}|{text}".encode()).hexdigest()


def render(text: str) -> np.ndarray:
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="voicepack-")
    os.close(fd)
    try:
        r = subprocess.run(["say", "-o", path, "--file-format=WAVE", f"--data-format=LEI16@{SR}"],
                           input=ov.strip_markup(text).encode(), capture_output=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"say failed ({r.returncode}): {r.stderr.decode(errors='replace')[:200]}")
        pcm, sr = ov.read_wav(Path(path).read_bytes())
    finally:
        Path(path).unlink(missing_ok=True)
    return ov.resample(pcm, sr, SR)


def master(pcm: np.ndarray) -> np.ndarray:
    """Trim the silence at both ends (PAD_S kept), speech RMS to TARGET_RMS_DBFS, peaks under PEAK_DBFS."""
    t0, t1, _ = ov.silences(pcm, SR)
    a, b = max(0, int((t0 - PAD_S) * SR)), min(len(pcm), int((t1 + PAD_S) * SR))
    x = pcm[a:b].astype(np.float32) / 32768.0
    hop = int(SR * 0.02)
    n = len(x) // hop
    if n:
        fr = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
        act = fr[fr > fr.max() * 10 ** (-30 / 20)]
        rms = float(np.sqrt(np.mean(act ** 2))) if len(act) else float(fr.mean())
        x = x * (10 ** (TARGET_RMS_DBFS / 20) / max(rms, 1e-6))
    pk = float(np.abs(x).max()) if len(x) else 0.0
    ceil = 10 ** (PEAK_DBFS / 20)
    if pk > ceil:
        x = x * (ceil / pk)
    return np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)


def encode(pcm: np.ndarray, path: Path) -> None:
    import soundfile as sf
    sf.write(str(path), pcm, SR, format="MP3", subtype="MPEG_LAYER_III", bitrate_mode="CONSTANT",
             compression_level=MP3_LEVEL)


def one(line: dict, out_dir: Path) -> dict:
    from app.voice_pack import decode
    pcm = master(render(line["text"]))
    rh = recipe_hash(line["text"])
    name = f"{clip_id(line['key'])}-{rh[:8]}.mp3"
    p = out_dir / name
    encode(pcm, p)
    dec, sr = decode(p)                               # the timings come from what the app will actually play
    words = ov.display_words(line["text"])
    times = ov.estimate_timings(words, dec, sr)
    data = p.read_bytes()
    return {"file": f"clips/{name}", "text": line["text"], "role": line["role"], "rate": "native",
            "dur": round(len(dec) / sr, 3), "words": ov.words_header(times), "voice": VOICE_ID,
            "sha256": hashlib.sha256(data).hexdigest(), "recipe": rh, "bytes": len(data)}


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def clip_ok(e: dict | None) -> bool:
    if not e:
        return False
    p = PACK / e.get("file", "")
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest() == e.get("sha256")
    except OSError:
        return False


def write_index(clips: dict) -> None:
    doc = {"version": 1, "voice": VOICE_ID, "voice_name": VOICE_NAME, "recipe": RECIPE, "format":
           {"codec": "mp3", "kbps": MP3_KBPS, "sr": SR, "channels": 1}, "count": len(clips),
           "bytes": sum(e.get("bytes", 0) for e in clips.values()),
           "seconds": round(sum(e.get("dur", 0) for e in clips.values()), 1),
           "clips": dict(sorted(clips.items()))}
    tmp = PACK / "index.json.tmp"
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(PACK / "index.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="verify the voice and list what is missing; record nothing")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    if sys.platform != "darwin":
        sys.exit("voice pack: recording needs macOS (`say` with the Siri System voice). The pack itself ships to every OS.")
    manifest = load_json(PACK / "lines.json", None)
    if not manifest:
        sys.exit("voice pack: backend/data/voice_pack/lines.json missing: run `make voice-pack-lines` first")
    old = (load_json(PACK / "index.json", {}) or {}).get("clips", {})
    want = {l["key"]: l for l in manifest["lines"]}
    todo = []
    for k, l in want.items():
        e = old.get(k)
        if not (e and e.get("recipe") == recipe_hash(l["text"]) and clip_ok(e)):
            todo.append(l)
    print(f"voice pack: {len(want)} lines, {len(want) - len(todo)} recorded and current, {len(todo)} to record")
    require_voice("before recording")
    print(f"voice pack: System voice is {VOICE_ID} ({VOICE_NAME}): ok")
    if a.check:
        for l in todo[:40]:
            print("  missing:", l["text"])
        return 0
    if a.limit:
        todo = todo[: a.limit]
    clips_dir = PACK / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clips = {k: e for k, e in old.items() if k in want}       # lines no longer in the manifest drop out
    made: list[str] = []

    def discard(why: str):
        for f in made:
            (PACK / f).unlink(missing_ok=True)
        write_index(dict(old))
        sys.exit(f"voice pack: {why}; this run's {len(made)} clips were discarded and the previous index restored.\n"
                 f"  Set {SETTING}, then run `make voice-pack` again. (This script never changes the setting.)")
    t = time.perf_counter()
    with ThreadPoolExecutor(max(1, a.workers)) as pool:
        for i in range(0, len(todo), BATCH):
            batch = todo[i: i + BATCH]
            if system_voice() != VOICE_ID:
                discard(f"the System voice changed to {system_voice()} before batch {i // BATCH + 1}")
            try:
                res = list(pool.map(lambda l: (l["key"], one(l, clips_dir)), batch))
            except KeyboardInterrupt:
                discard("interrupted")
            if system_voice() != VOICE_ID:
                made.extend(e["file"] for _, e in res)
                discard(f"the System voice changed to {system_voice()} during batch {i // BATCH + 1}")
            for k, e in res:
                clips[k] = e
                made.append(e["file"])
            write_index(clips)
            done = i + len(batch)
            el = time.perf_counter() - t
            print(f"  {done}/{len(todo)}  {el:.0f}s  (~{el / done * (len(todo) - done):.0f}s left)", flush=True)
    if system_voice() != VOICE_ID:      # changed during the run: nothing from this run is trusted
        discard(f"the System voice changed to {system_voice()} during the run")
    write_index(clips)
    keep = {Path(e["file"]).name for e in clips.values()}
    pruned = 0
    for f in clips_dir.glob("*.mp3"):
        if f.name not in keep:
            f.unlink()
            pruned += 1
    mb = sum(e.get("bytes", 0) for e in clips.values()) / 1e6
    secs = sum(e.get("dur", 0) for e in clips.values())
    print(f"voice pack: {len(made)} recorded, {pruned} stale removed; {len(clips)}/{len(want)} clips, "
          f"{secs / 60:.1f} min, {mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
