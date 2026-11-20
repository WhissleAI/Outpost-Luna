"""The desktop copy of the crew clips: only the stretches the app can play, as mono speech-quality MP3 (docs/DESKTOP.md).

    cd backend && uv run --with imageio-ffmpeg==0.6.0 python -m pipeline.trim_media

Run after fetch_media.py (the desktop builds do). Cross-platform, no bash: Python plus the ffmpeg binary that the pinned
imageio-ffmpeg wheel ships for macOS, Windows and Linux (falls back to an `ffmpeg` on PATH if the wheel is missing).

  in:  data/media/audio/<stem>.mp3            NASA originals (96-192 kbps, mostly dual-mono stereo); never modified
  out: data/media/desktop/audio/<stem>.mp3    the kept stretches back to back, mono 24 kHz, 32 kbps CBR
       data/media/desktop/trim.json           {params, clips: {<file name>: {src_sha256, dur, segs: [[orig_t0, file_t0, len]]}}}

electron-builder ships data/media/desktop as the app's media/ (so trim.json lands at media/trim.json). The backend adds
a clip's `segs` to GET /api/clips/<id>, and the player (frontend/src/player.js) converts between clip time and file time
at the <audio> element, so every timestamp in the data (words, moments, artifact voices, lessons, vocab) stays in the
original clip's time. The dev app keeps the originals and has no trim.json: identity.

What can play (the kept stretches, each padded by MARGIN; stretches closer than JOIN are merged): every moment the
index cuts (moments.cut_clip tiles all of a clip's words, kid-safe or not), every artifact `voices` span, every
lesson clip in academy/course.json, and the "Hear the crew say it" window (t - 2 .. t + 4) of every vocab term. The
dropped parts are the silences between moments, which no playback reaches (a moment stops at its t1, then fades
200 ms). Deterministic: same originals + same data + same pinned ffmpeg = same bytes; up-to-date clips are skipped.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
SRC = DATA / "media/audio"
OUT = DATA / "media/desktop"
SR = 24000            # Hz: MPEG-2 Layer III. 16 kHz was tried for 0.4.3 and cost the ear +1.9-2.4 pt WER on crew segments
#                       (docs/LOCAL_EAR.md "Lighter ear"); 24 kHz keeps 12 kHz of bandwidth
BITRATE = "32k"       # CBR: exact seeking in every browser (a VBR MP3 without a TOC seeks approximately). Was 48 kbps
#                       (175 MB); docs/DESKTOP.md "Crew audio in the installer" has the before / after checks
MARGIN = 1.0          # s kept before and after every playable span (the player polls every 60 ms, then fades 200 ms)
JOIN = 3.0            # s: gaps shorter than this are kept, so short pauses stay and the file has few joins
VOCAB_SPAN = (2.0, 4.0)   # frontend/src/highlight.js + academy/vocab.js play [t - 2, t + 4] of a vocab term's source


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        exe = shutil.which("ffmpeg")
        if not exe:
            sys.exit("ffmpeg not found: run with `uv run --with imageio-ffmpeg==0.6.0 python -m pipeline.trim_media`")
        return exe


def ffmpeg_version(exe: str) -> str:
    out = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True).stdout
    return out.split("\n", 1)[0].strip()


# ------------------------------------------------------------------------------------------------- what can play
def _walk_clips(x, out: list):
    """Every {clip_id, t0, t1} dict anywhere in a JSON tree (lesson clips in course.json)."""
    if isinstance(x, dict):
        if x.get("clip_id") and "t0" in x and "t1" in x:
            out.append((str(x["clip_id"]), float(x["t0"]), float(x["t1"])))
        for v in x.values():
            _walk_clips(v, out)
    elif isinstance(x, list):
        for v in x:
            _walk_clips(v, out)
    return out


def playable_spans() -> dict[str, list[tuple[float, float]]]:
    """clip id -> [(t0, t1)] in the original clip's time: everything the app can ask the player to play."""
    from app.academy.vocab import terms
    from app.moments import MomentIndex

    index = MomentIndex(DATA / "index/clips.json")
    spans: dict[str, list[tuple[float, float]]] = {}
    add = lambda cid, a, b: spans.setdefault(cid, []).append((max(0.0, float(a)), float(b)))  # noqa: E731
    for m in index.moments:
        add(m["clip_id"], m["t0"], m["t1"])
    for a in json.loads((DATA / "artifacts.json").read_text(encoding="utf-8")):
        for v in a.get("voices") or []:
            add(v["clip_id"], v["t0"], v["t1"])
    for cid, t0, t1 in _walk_clips(json.loads((DATA / "academy/course.json").read_text(encoding="utf-8")), []):
        add(cid, t0, t1)
    for t in terms().values():
        s = t.get("source") or {}
        if s.get("clip_id"):
            add(s["clip_id"], float(s["t"]) - VOCAB_SPAN[0], float(s["t"]) + VOCAB_SPAN[1])
    return spans


def keep_ranges(spans: list[tuple[float, float]], dur: float = float("inf")) -> list[tuple[float, float]]:
    """The padded, merged union of `spans`, clipped to [0, dur]."""
    out: list[list[float]] = []
    for a, b in sorted((max(0.0, a - MARGIN), min(dur, b + MARGIN)) for a, b in spans):
        if b <= a:
            continue
        if out and a <= out[-1][1] + JOIN:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


# ------------------------------------------------------------------------------------------------- audio
def decode(exe: str, src: Path) -> bytes:
    """The whole clip as mono s16le PCM at SR (ffmpeg's stereo downmix averages L and R: the NASA stereo is dual-mono)."""
    return subprocess.run([exe, "-v", "error", "-nostdin", "-i", str(src), "-map", "0:a:0", "-ac", "1", "-ar", str(SR),
                           "-f", "s16le", "-"], capture_output=True, check=True).stdout


def encode(exe: str, pcm: bytes, dst: Path, title: str, url: str) -> None:
    tmp = dst.with_name(dst.name + ".part")
    subprocess.run([exe, "-v", "error", "-nostdin", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-map_metadata", "-1", "-metadata", f"title={title}", "-metadata", "artist=NASA",
                    "-metadata", f"comment=Courtesy NASA. Excerpts of {url}",
                    "-c:a", "libmp3lame", "-b:a", BITRATE, "-id3v2_version", "3", "-write_xing", "1",
                    "-fflags", "+bitexact", "-flags:a", "+bitexact", "-f", "mp3", str(tmp)],
                   input=pcm, check=True)
    tmp.replace(dst)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    exe = ffmpeg_exe()
    params = {"sr": SR, "bitrate": BITRATE, "margin": MARGIN, "join": JOIN, "ffmpeg": ffmpeg_version(exe)}
    manifest = json.loads((DATA / "clips_manifest.json").read_text(encoding="utf-8"))["clips"]
    index = {c["file"].rsplit("/", 1)[-1]: c for c in json.loads((DATA / "index/clips.json").read_text(encoding="utf-8"))["clips"]}
    spans = playable_spans()
    old_path = OUT / "trim.json"
    old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else {}
    old_clips = old.get("clips", {}) if old.get("params") == params else {}
    (OUT / "audio").mkdir(parents=True, exist_ok=True)

    clips, missing, before, after, dur_in, dur_out = {}, [], 0, 0, 0.0, 0.0
    for c in manifest:
        name = f"{c['stem']}.mp3"
        src, dst = SRC / name, OUT / "audio" / name
        if not (src.exists() and src.stat().st_size):
            missing.append(name)
            continue
        src_sha = sha256(src)
        ix = index.get(name)
        # The kept ranges in samples; a clip the index doesn't know (no timings) is kept whole.
        want = keep_ranges(spans.get(ix["id"], [])) if ix else []   # the end is clipped to the decoded length below
        prev = old_clips.get(name)
        if prev and prev["src_sha256"] == src_sha and prev.get("want") == [[round(a, 3), round(b, 3)] for a, b in want] \
                and dst.exists() and sha256(dst) == prev.get("out_sha256"):
            rec = prev
        else:
            print(f"✂ {name}", flush=True)
            pcm = decode(exe, src)
            n = len(pcm) // 2
            ranges = [(round(a * SR), min(n, round(b * SR))) for a, b in want] or [(0, n)]
            ranges = [(a, b) for a, b in ranges if b > a]
            segs, parts, pos = [], [], 0
            for a, b in ranges:
                parts.append(pcm[2 * a:2 * b])
                segs.append([round(a / SR, 6), round(pos / SR, 6), round((b - a) / SR, 6)])
                pos += b - a
            encode(exe, b"".join(parts), dst, c.get("title") or c["stem"], c.get("url", ""))
            rec = {"src_sha256": src_sha, "out_sha256": sha256(dst), "dur": round(n / SR, 6),
                   "want": [[round(a, 3), round(b, 3)] for a, b in want], "segs": segs}
        clips[name] = rec
        before += src.stat().st_size
        after += dst.stat().st_size
        dur_in += rec["dur"]
        dur_out += sum(s[2] for s in rec["segs"])

    keep = {f"{c['stem']}.mp3" for c in manifest}
    for f in (OUT / "audio").glob("*"):
        if f.name not in keep:
            f.unlink()
    tmp = OUT / "trim.json.part"
    tmp.write_text(json.dumps({"params": params, "clips": clips}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(old_path)
    print(f"{len(clips)}/{len(manifest)} clips: {before / 1e6:.0f} MB -> {after / 1e6:.0f} MB; "
          f"{dur_in / 3600:.2f} h -> {dur_out / 3600:.2f} h kept ({OUT.relative_to(DATA.parent)})")
    if missing:
        print(f"missing originals (run backend/pipeline/fetch_media.py): {missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
