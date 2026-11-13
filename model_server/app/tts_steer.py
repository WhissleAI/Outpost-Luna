"""Steer TTS Edge (Whissle's on-device TTS) behind the model server: POST /v1/tts.

The model (int4 acoustic + vocoder, ONNX Runtime CPU, ~12 MB of weights) and Steer's performance director
(`director.bin`, ~0.5 MB) load once at startup behind STEER_TTS=on|off. Loading fails open: /health carries the reason
and /v1/tts answers 503, so the backend falls back to Deepgram, then the browser voice.

Request (all but `text` optional; see steer-tts/docs/request.md):
    {text, voice, tag, controls:{rate, loud, f0_med, f0_iqr, f0_end, pause, …}, guidance, markup,
     perform:{genre:"children", strength, para_index, para_len, next}}
Reply: audio/wav (24 kHz mono 16-bit PCM; the browser decodes WAV with no codec delay). Headers carry what was
rendered: X-Steer-Voice, X-Steer-Tag, X-Steer-Ctrl, X-Steer-Ms, X-Steer-Pause-Ms.

The director: for multi-sentence text (or one sentence of a longer text, with `perform.next` / `para_index`), each
sentence gets a plan (rate, loud, pitch, range, ending, pause) for the genre. The plan fills the controls the caller did
not name; explicit controls win per key (as Steer's `--perform --ctrl`), so the app's steering stays in charge.
"""
from __future__ import annotations

import io
import re
import threading
import time
import wave

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import settings

router = APIRouter()
STATE: dict = {"tts": None, "director": None, "error": None, "director_error": None, "load_s": None,
               "rss_added_mb": None, "lock": threading.Lock()}
SR = 24000
CONTROL_RANGE = 3.0                  # the well-tested range (docs/request.md); the model accepts ±5
MAX_PAUSE_MS = 700                   # cap the director's paragraph pause between floor sentences
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“*<\[])")


def load() -> None:
    """Load the model and the director. Never raises: the reason goes to /health."""
    if settings.steer_tts.lower() != "on":
        STATE["error"] = "STEER_TTS=off"
        return
    import psutil
    t, r0 = time.perf_counter(), psutil.Process().memory_info().rss
    try:
        from steertts_edge import OnnxTTS
        model_dir = settings.steer_model_dir()
        if model_dir is None:
            raise FileNotFoundError("Steer TTS Edge model not found (set STEER_TTS_MODEL or `hf download "
                                    "WhissleAI/steer-tts-edge`)")
        tts = OnnxTTS(model_dir, threads=settings.steer_threads)
        tts("Ready.", voice=tts.default_voice)       # warm the graphs (first call allocates)
        STATE["tts"], STATE["model_dir"] = tts, str(model_dir)
    except Exception as e:  # noqa: BLE001 - fail open
        STATE["error"] = f"{type(e).__name__}: {e}"[:300]
    try:
        from steertts_edge import Director
        path = settings.steer_director_path()
        if path is None:
            raise FileNotFoundError("director.bin not found (set STEER_DIRECTOR)")
        STATE["director"] = Director(str(path))
    except Exception as e:  # noqa: BLE001 - the director is optional: no plans, the rest still works
        STATE["director_error"] = f"{type(e).__name__}: {e}"[:300]
    STATE["load_s"] = round(time.perf_counter() - t, 2)
    STATE["rss_added_mb"] = round((psutil.Process().memory_info().rss - r0) / 2**20)


def health() -> dict:
    tts = STATE["tts"]
    return {"steer_tts": {"loaded": tts is not None, "error": STATE["error"], "model_dir": STATE.get("model_dir"),
                          "director": STATE["director"] is not None, "director_error": STATE["director_error"],
                          "voices": len(tts.voices) if tts else 0, "load_s": STATE["load_s"],
                          "rss_added_mb": STATE["rss_added_mb"], "threads": settings.steer_threads}}


class Perform(BaseModel):
    genre: str | None = "children"
    strength: float = Field(0.8, ge=0, le=1.5)
    para_index: int | None = Field(None, ge=0, description="This sentence's index when the client splits the text")
    para_len: int | None = Field(None, ge=1)
    next: str | None = Field(None, max_length=600, description="The following sentence, when known")


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)
    voice: str | None = None
    tag: str = "none"
    controls: dict[str, float] | None = None
    guidance: float | None = Field(None, ge=0.5, le=3)
    markup: bool = False
    perform: Perform | None = None


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]


def _wav(audio: np.ndarray) -> bytes:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return b.getvalue()


def _clean_ctrl(tts, ctrl: dict | None) -> dict:
    out = {}
    for k, v in (ctrl or {}).items():
        if k not in tts.controls:
            raise HTTPException(400, f"unknown control {k!r}; one of {', '.join(tts.controls)}")
        out[k] = float(max(-CONTROL_RANGE, min(CONTROL_RANGE, v)))
    return out


def plans(req: TTSRequest, sentences: list[str]) -> list[tuple[dict, int]]:
    """Per sentence: (director controls, pause after in ms). Empty controls without a director or `perform`."""
    d, p = STATE["director"], req.perform
    if d is None or p is None or p.strength <= 0:
        return [({}, 0) for _ in sentences]
    genre = p.genre if p.genre in d.genres() else None
    if len(sentences) == 1 and (p.para_index is not None or p.next):
        n = p.para_len or (p.para_index or 0) + (2 if p.next else 1)
        r = d.reading(genre)
        plan = r.next({"text": sentences[0], "para_index": p.para_index or 0, "para_len": n},
                      {"text": p.next, "para_index": (p.para_index or 0) + 1, "para_len": n} if p.next else None)
        out = [plan]
    else:
        out = d.plan(sentences, genre=genre)
    return [(d.ctrl(x, p.strength), d.pause_ms(x)) for x in out]


def render(req: TTSRequest) -> tuple[np.ndarray, dict]:
    tts = STATE["tts"]
    voice = req.voice or tts.default_voice
    if voice not in tts.voice_info:
        raise HTTPException(400, f"unknown voice {voice!r}")
    if req.tag not in tts.tag2i:
        raise HTTPException(400, f"unknown tag {req.tag!r}")
    ctrl = _clean_ctrl(tts, req.controls)
    text = " ".join(req.text.split())
    sentences = split_sentences(text) or [text]
    pl = plans(req, sentences)
    chunks, used, pause_ms = [], [], 0
    with STATE["lock"]:   # one render at a time: ONNX sessions are shared and the CPU is the bottleneck anyway
        for i, (s, (dc, gap)) in enumerate(zip(sentences, pl)):
            c = {**{k: v for k, v in dc.items() if k not in ctrl}, **ctrl}   # explicit controls win per key
            used.append(c)
            kw = {"voice": voice, "tag": req.tag, "ctrl": c or None, "markup": req.markup}
            if req.guidance is not None:
                kw["guidance"] = req.guidance
            chunks.append(np.asarray(tts(s, **kw), np.float32))
            last = i == len(sentences) - 1
            pause_ms = min(gap, MAX_PAUSE_MS) if (not last or (req.perform and req.perform.next)) else 0
            if pause_ms and not last:
                chunks.append(np.zeros(int(SR * pause_ms / 1000), np.float32))
    audio = np.concatenate(chunks)
    if req.perform and req.perform.next and pause_ms:     # the floor plays sentence by sentence: leave the gap here
        audio = np.concatenate([audio, np.zeros(int(SR * pause_ms / 1000), np.float32)])
    return audio, {"voice": voice, "tag": req.tag, "ctrl": used[0] if len(used) == 1 else used, "pause_ms": pause_ms,
                   "sentences": len(sentences)}


@router.post("/v1/tts")
async def tts_route(req: TTSRequest):
    if STATE["tts"] is None:
        raise HTTPException(503, f"Steer TTS not loaded: {STATE['error']}")
    t = time.perf_counter()
    try:
        audio, info = await run_in_threadpool(render, req)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - a bad markup span etc.
        raise HTTPException(400, f"steer render failed: {e}"[:300])
    ms = (time.perf_counter() - t) * 1000
    dur = len(audio) / SR
    ctrl = info["ctrl"] if isinstance(info["ctrl"], dict) else info["ctrl"][0]
    return Response(_wav(audio), media_type="audio/wav", headers={
        "X-Steer-Voice": info["voice"], "X-Steer-Tag": info["tag"],
        "X-Steer-Ctrl": ",".join(f"{k}={v:.2f}" for k, v in ctrl.items()),
        "X-Steer-Ms": f"{ms:.0f}", "X-Steer-RTF": f"{ms / 1000 / max(dur, 1e-3):.3f}",
        "X-Steer-Pause-Ms": str(info["pause_ms"]), "X-Steer-Sentences": str(info["sentences"])})


@router.get("/v1/tts/voices")
def voices():
    tts = STATE["tts"]
    if tts is None:
        raise HTTPException(503, f"Steer TTS not loaded: {STATE['error']}")
    return {"voices": list(tts.voice_info.values()), "tags": tts.tags, "controls": tts.controls,
            "genres": STATE["director"].genres() if STATE["director"] else []}
