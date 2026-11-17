"""The playback timeline, the duplex recorder and the manifest.

One full-duplex stream does both jobs: every callback hands the speakers block i of the reference and receives block i
of the mic. The two WAVs therefore share one clock, sample for sample (ref.wav sample n went to the speakers in the
same callback that captured mic.wav sample n). The acoustic round trip (DAC + air + ADC) is measured from the chirps.
"""
from __future__ import annotations

import bisect
import json
import os
import queue
import threading
import time
from pathlib import Path

import numpy as np

from align import find_delay

KIT_VERSION = "1.0"


class Timeline:
    """Segments laid end to end on the shared clock (frames at the stream rate). Each audio segment keeps its PCM once
    (shared between repeats) and its own gain; silence is just a gap."""

    def __init__(self, sr: int):
        self.sr = sr
        self.segs: list[dict] = []
        self._starts: list[int] = []
        self.cursor = 0

    @property
    def total(self) -> int:
        return self.cursor

    def add(self, pcm: np.ndarray, gain_db: float = 0.0, **meta) -> dict:
        n = len(pcm)
        seg = {"start": self.cursor, "end": self.cursor + n, "pcm": pcm, "gain": float(10 ** (gain_db / 20)),
               "gain_db": gain_db, **meta}
        self.segs.append(seg)
        self._starts.append(seg["start"])
        self.cursor += n
        return seg

    def silence(self, seconds: float, kind: str | None = None, **meta) -> dict | None:
        """A gap. With `kind` (e.g. "noise_floor") it is listed in the manifest; otherwise it is just space."""
        n = int(round(seconds * self.sr))
        seg = None
        if kind:
            seg = {"start": self.cursor, "end": self.cursor + n, "pcm": None, "gain": 0.0, "gain_db": None,
                   "kind": kind, **meta}
            self.segs.append(seg)
            self._starts.append(seg["start"])
        self.cursor += n
        return seg

    def render(self, pos: int, n: int) -> np.ndarray:
        """Exactly what the speakers get for frames pos .. pos+n (mono, clipped to +-1)."""
        out = np.zeros(n, np.float32)
        i = bisect.bisect_left(self._starts, pos + n) - 1
        while i >= 0:
            s = self.segs[i]
            if s["end"] <= pos:
                break
            if s["pcm"] is not None:
                a, b = max(pos, s["start"]), min(pos + n, s["end"])
                if b > a:
                    out[a - pos: b - pos] += s["pcm"][a - s["start"]: b - s["start"]] * s["gain"]
            i -= 1
        np.clip(out, -1.0, 1.0, out=out)
        return out

    def at(self, frame: int) -> dict | None:
        i = bisect.bisect_right(self._starts, frame) - 1
        if i >= 0 and self.segs[i]["start"] <= frame < self.segs[i]["end"]:
            return self.segs[i]
        return None


# ================================================================================================= recorder
class Recorder:
    """Runs a Timeline through one duplex stream and writes mic.wav + ref.wav (float32, the stream rate)."""

    def __init__(self, sd, timeline: Timeline, rate: int, din: dict, dout: dict, out_channels: int, outdir: Path,
                 blocksize: int = 0):
        self.sd, self.tl, self.rate = sd, timeline, rate
        self.din, self.dout, self.out_channels = din, dout, out_channels
        self.outdir = Path(outdir)
        self.blocksize = blocksize
        self.pos = 0                         # frames handed to the speakers (= frames captured)
        self.q: queue.Queue = queue.Queue()
        self.done = threading.Event()
        self.status: dict = {"input_overflow": 0, "output_underflow": 0, "other": 0}
        self.first_times: dict | None = None
        self.frames_written = 0
        self.writer_error: str | None = None

    # ---- audio thread ----
    def _callback(self, indata, outdata, frames, t, status):
        if status:
            if getattr(status, "input_overflow", False):
                self.status["input_overflow"] += 1
            elif getattr(status, "output_underflow", False):
                self.status["output_underflow"] += 1
            else:
                self.status["other"] += 1
        if self.first_times is None:
            try:
                self.first_times = {"input_adc": float(t.inputBufferAdcTime), "output_dac": float(t.outputBufferDacTime),
                                    "now": float(t.currentTime)}
            except Exception:  # noqa: BLE001
                self.first_times = {}
        pos = self.pos
        ref = self.tl.render(pos, frames)
        outdata[:] = ref[:, None]
        self.q.put((indata[:, 0].copy(), ref))
        self.pos = pos + frames
        if self.pos >= self.tl.total:
            raise self.sd.CallbackStop()

    # ---- writer thread ----
    def _writer(self):
        import soundfile as sf
        try:
            with sf.SoundFile(str(self.outdir / "mic.wav"), "w", self.rate, 1, "FLOAT") as fm, \
                    sf.SoundFile(str(self.outdir / "ref.wav"), "w", self.rate, 1, "FLOAT") as fr:
                last_flush = time.monotonic()
                while True:
                    item = self.q.get()
                    if item is None:
                        break
                    mic, ref = item
                    fm.write(mic)
                    fr.write(ref)
                    self.frames_written += len(mic)
                    if time.monotonic() - last_flush > 5:
                        fm.flush()
                        fr.flush()
                        last_flush = time.monotonic()
        except Exception as e:  # noqa: BLE001
            self.writer_error = str(e)[:300]
            while self.q.get() is not None:   # keep draining so the audio thread never blocks
                pass

    def run(self, on_tick=None, tick_s: float = 0.1) -> dict:
        """Play + record until the timeline ends or Ctrl-C. on_tick(pos_frames) runs on this thread ~10x a second
        (progress, the guided prompts, manifest checkpoints). Returns {frames, interrupted, ...}."""
        w = threading.Thread(target=self._writer, daemon=True)
        w.start()
        interrupted = False
        stream = None
        t0 = time.monotonic()
        try:
            stream = self.sd.Stream(samplerate=self.rate, blocksize=self.blocksize,
                                    device=(self.din["index"], self.dout["index"]), channels=(1, self.out_channels),
                                    dtype="float32", callback=self._callback, finished_callback=self.done.set)
            stream.start()
            while not self.done.wait(tick_s):
                if on_tick:
                    on_tick(self.pos)
            if on_tick:
                on_tick(self.pos)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if stream is not None:
                try:
                    if interrupted:
                        stream.abort()
                    else:
                        stream.stop()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
                lat = getattr(stream, "latency", None)
            else:
                lat = None
            self.q.put(None)
            w.join()
        return {"frames": self.frames_written, "interrupted": interrupted, "wall_s": round(time.monotonic() - t0, 2),
                "status": self.status, "first_times": self.first_times,
                "portaudio_latency_s": list(lat) if isinstance(lat, (tuple, list)) else lat,
                "writer_error": self.writer_error}


# ================================================================================================= manifest
def seg_entry(s: dict, sr: int, frames: int, i: int) -> dict | None:
    """A segment as the manifest lists it, cut at what was actually recorded (None when it never started)."""
    if s["start"] >= frames:
        return None
    end = min(s["end"], frames)
    e = {"i": i, "kind": s.get("kind"), "start_s": round(s["start"] / sr, 6), "end_s": round(end / sr, 6),
         "start_frame": s["start"], "end_frame": end}
    if end < s["end"]:
        e["truncated"] = True
    for k in ("text", "voice", "gain_db", "level_db", "level_block", "source", "label", "prompt", "role", "key",
              "src_start_s", "line_kind"):
        if k in s and s[k] is not None:
            e[k] = s[k]
    return e


def measure_chirps(outdir: Path, chirps: list[dict], chirp_pcm: np.ndarray, sr: int) -> list[dict]:
    """Recover the round trip at every chirp that was recorded (matched filter on mic.wav)."""
    import soundfile as sf
    out = []
    p = outdir / "mic.wav"
    if not p.exists():
        return out
    with sf.SoundFile(str(p)) as f:
        for c in chirps:
            if c["start"] + len(chirp_pcm) + sr >= f.frames:
                continue
            f.seek(c["start"])
            mic = f.read(len(chirp_pcm) + sr, dtype="float32")
            r = find_delay(mic, chirp_pcm * c["gain"], 0, sr)
            out.append({"at_s": round(c["start"] / sr, 3), "label": c.get("label"), **r})
    return out


def write_json(path: Path, obj: dict) -> None:
    """Atomic: a crash mid-write never leaves a half manifest."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def validate_manifest(m: dict, outdir: Path | None = None) -> list[str]:
    """Problems with a session manifest ([] = valid). Used by the tests and printed after every session."""
    errs = []
    for k in ("kit", "session", "status", "sample_rate", "frames", "files", "segments", "machine", "devices"):
        if k not in m:
            errs.append(f"missing {k}")
    if errs:
        return errs
    sr, frames = m["sample_rate"], m["frames"]
    if m["status"] not in ("complete", "stopped_early", "recording"):
        errs.append(f"bad status {m['status']}")
    prev = -1
    for s in m["segments"]:
        if not (0 <= s["start_frame"] <= s["end_frame"] <= frames):
            errs.append(f"segment {s['i']} outside the recording")
        if s["start_frame"] < prev:
            errs.append(f"segment {s['i']} out of order")
        prev = s["start_frame"]
        if abs(s["start_s"] - s["start_frame"] / sr) > 1e-5:
            errs.append(f"segment {s['i']} start_s != start_frame / sr")
    for p in m.get("prompts", []):
        if p.get("label") not in ("addressed", "not_addressed", "barge_in"):
            errs.append(f"prompt {p.get('i')} has bad label")
        if not (0 <= p.get("window_start_s", -1) <= p.get("window_end_s", -1) <= frames / sr + 1e-6):
            errs.append(f"prompt {p.get('i')} window outside the recording")
    if outdir is not None and m["status"] != "recording":
        import soundfile as sf
        for key in ("mic", "reference"):
            f = Path(outdir) / m["files"][key]
            if not f.exists():
                errs.append(f"{key} file missing")
                continue
            info = sf.info(str(f))
            if info.frames != frames or info.samplerate != sr:
                errs.append(f"{key}: {info.frames} frames @ {info.samplerate}, manifest says {frames} @ {sr}")
        for key in ("mic_16k", "reference_16k"):
            f = Path(outdir) / m["files"].get(key, "")
            if m["files"].get(key) and f.exists():
                info = sf.info(str(f))
                if abs(info.frames - frames * 16000 / sr) > 2:
                    errs.append(f"{key}: {info.frames} frames, expected ~{frames * 16000 / sr:.0f}")
    text = json.dumps(m)
    home = str(Path.home())
    if home and home != "/" and home in text:
        errs.append("manifest contains the home folder path")
    return errs
