"""The recorded voice pack (docs/VOICE_PACK.md): the app's fixed lines, pre-recorded with the macOS Siri voice
"Siri Voice 1" (Nora) at build time and shipped in both the Mac and Windows apps.

Layout (VOICE_PACK_DIR, default backend/data/voice_pack, the same folder the backend ships in the bundle):
    lines.json    the manifest (make voice-pack-lines): every fixed line, keyed by os_voices.pack_key(text)
    index.json    what is recorded (make voice-pack): {"clips": {key: {file, dur, words, voice, sha256, text_sha, …}}}
    clips/*.mp3   mono MP3, one per line, silence-trimmed and loudness-normalised

`lookup(key)` -> {pcm (int16), sr, words, voice, voice_name, text} or None. The index is re-read when its file changes
(a cheap stat per call), decoded clips are kept in a small LRU. Fails open: no folder, no index, a bad clip -> None, and
the line is rendered live.
"""
from __future__ import annotations

import collections
import hashlib
import json
import threading
from pathlib import Path

import numpy as np

from .config import settings

STATE: dict = {"dir": None, "mtime": None, "index": {}, "voice": None, "voice_name": None, "error": None}
_CLIPS: collections.OrderedDict = collections.OrderedDict()
CLIP_CACHE = 64
_LOCK = threading.Lock()


def clip_id(key: str) -> str:
    """The clip's file stem: a short hash of the key (keys can be long and hold spaces / %; Windows paths are short)."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def pack_dir() -> Path:
    return Path(settings.voice_pack_dir)


def _load() -> dict:
    d = pack_dir()
    idx = d / "index.json"
    try:
        m = idx.stat().st_mtime_ns
    except OSError:
        STATE.update(dir=str(d), mtime=None, index={}, error="no index.json")
        return STATE["index"]
    if STATE["mtime"] == m and STATE["dir"] == str(d):
        return STATE["index"]
    try:
        doc = json.loads(idx.read_text(encoding="utf-8"))
        clips = doc.get("clips") or {}
        STATE.update(dir=str(d), mtime=m, index=clips, voice=doc.get("voice"), voice_name=doc.get("voice_name"),
                     error=None)
    except (OSError, ValueError) as e:
        STATE.update(dir=str(d), mtime=m, index={}, error=f"{type(e).__name__}: {e}"[:200])
    _CLIPS.clear()
    return STATE["index"]


def decode(path: Path) -> tuple[np.ndarray, int]:
    """A clip (MP3, or WAV / FLAC in a fixture pack) -> (int16 mono, sample rate). libsndfile >= 1.1 reads MP3."""
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="int16", always_2d=True)
    return np.ascontiguousarray(x.mean(axis=1).astype(np.int16) if x.shape[1] > 1 else x[:, 0]), int(sr)


def lookup(key: str) -> dict | None:
    if settings.voice_pack.lower() == "off" or not key:
        return None
    with _LOCK:
        idx = _load()
        e = idx.get(key)
        if not e:
            return None
        if key in _CLIPS:
            _CLIPS.move_to_end(key)
            pcm, sr = _CLIPS[key]
        else:
            p = pack_dir() / e.get("file", f"clips/{clip_id(key)}.mp3")
            try:
                pcm, sr = decode(p)
            except Exception:  # noqa: BLE001 - a missing / unreadable clip: render live
                return None
            _CLIPS[key] = (pcm, sr)
            while len(_CLIPS) > CLIP_CACHE:
                _CLIPS.popitem(last=False)
    return {"pcm": pcm, "sr": sr, "words": e.get("words") or "", "voice": e.get("voice") or STATE["voice"],
            "voice_name": STATE.get("voice_name") or "Voice pack", "text": e.get("text") or ""}


def health() -> dict:
    with _LOCK:
        idx = _load()
    return {"voice_pack": {"enabled": settings.voice_pack.lower() != "off", "clips": len(idx),
                           "voice": STATE["voice"], "dir": STATE["dir"], "error": STATE["error"] if not idx else None}}
