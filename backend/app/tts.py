"""Server TTS for the guide channel (docs/SESSION_CONTRACT.md §4, docs/VOICE_STEERING.md).

GET  /api/tts?text=…&voice=guide|capcom|story|houston[&style=<json>][&i=&n=&next=]  → audio, cached on disk by hash
POST /api/tts {text, voice, style?, i?, n?, next?}                                      → the same

Engines (TTS_ENGINE=steer|deepgram, default steer):
  steer     Steer TTS Edge on the model server (POST /v1/tts): Whissle's on-device TTS, steered per line by the
            Director's `style` (tag, controls, emphasis markup, performance director). → audio/wav
  deepgram  Deepgram Aura-2 over REST. → audio/mpeg
Fallback chain: steer → deepgram (when DEEPGRAM_API_KEY is set) → 503 {"fallback":"browser"} (speechSynthesis).

`style` is the `say.style` the Director sent (backend/app/steering.py); without one the persona's default style is
used, so `/api/tts?text=&voice=` keeps working. `i`/`n`/`next` place the sentence in its text, for the director's plan
(the client splits long text into sentences and asks for one at a time, prefetching the next). The cache key holds the
engine, the voice, the text and the style, so a re-steered line never plays a stale rendering.

The browser plays this as in-page audio, so Chrome's echo canceller can subtract it from the mic.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import steering
from .config import settings

router = APIRouter()

SPEAK_URL = "https://api.deepgram.com/v1/speak"
MAX_CHARS = 600
Persona = Literal["guide", "capcom", "story", "houston"]
# Deepgram Aura-2 voices (the fallback engine): a warm guide, a crisp CAPCOM, a younger voice for the hardware's story.
VOICES: dict[str, str] = {
    "guide": "aura-2-thalia-en",    # warm, clear, friendly
    "capcom": "aura-2-orion-en",    # calm, crisp male: mission control
    "story": "aura-2-iris-en",      # young, cheerful
    "houston": "aura-2-orion-en",
}
MEDIA = {"steer": ("audio/wav", ".wav"), "deepgram": ("audio/mpeg", ".mp3")}

CACHE_DIR: Path | None = None     # tests point this elsewhere; default data_dir/tts_cache (gitignored)


def cache_dir() -> Path:
    return CACHE_DIR or settings.data_dir / "tts_cache"


def cache_path(model: str, text: str, style: dict | None = None, engine: str = "deepgram") -> Path:
    """Engine + voice/model + text + style (canonical JSON) → one file. Deepgram ignores style (it can't steer)."""
    key = f"{model}\n{text}" if engine == "deepgram" else \
        f"{engine}\n{model}\n{text}\n{json.dumps(style or {}, sort_keys=True, separators=(',', ':'))}"
    h = hashlib.sha256(key.encode()).hexdigest()[:32]
    return cache_dir() / f"{h}{MEDIA[engine][1]}"


def clean_style(voice: str, text: str, style: dict | None) -> dict:
    """The client's style (from the Director) made safe, or the persona default. Only what reaches the engine."""
    if not isinstance(style, dict) or not style:
        style = steering.style_for(voice, text)
    persona = style.get("voice") if style.get("voice") in steering.VOICES else voice
    tag = str(style.get("tag") or "none")
    if tag in steering.FORBIDDEN:
        tag = steering.PERSONA_BASE[persona]["tag"]
    ctrl = {}
    for k, v in (style.get("controls") or {}).items():
        try:
            ctrl[str(k)] = round(max(-steering.CONTROL_LIMIT, min(steering.CONTROL_LIMIT, float(v))), 2)
        except (TypeError, ValueError):
            continue
    out = {"voice": persona, "steer_voice": steering.VOICES[persona], "tag": tag, "controls": ctrl}
    emph = [str(w)[:40] for w in (style.get("emph") or []) if str(w).strip()][:4]
    if emph:
        out["emph"] = emph
    if style.get("guidance"):
        out["guidance"] = max(1.0, min(2.0, float(style["guidance"])))
    perf = style.get("perform")
    if isinstance(perf, dict):
        out["perform"] = {"genre": str(perf.get("genre") or "children"),
                          "strength": max(0.0, min(1.0, float(perf.get("strength", 0.7))))}
    return out


async def _synth(model: str, text: str) -> bytes:
    """One Deepgram Aura call. Raises httpx.HTTPError (or RuntimeError on a non-audio reply)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(SPEAK_URL, params={"model": model, "encoding": "mp3"},
                         headers={"Authorization": f"Token {settings.deepgram_api_key}"}, json={"text": text})
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"deepgram speak {r.status_code}: {r.text[:160]}")
    return r.content


async def _steer(text: str, style: dict, place: dict) -> bytes:
    """One Steer TTS Edge render on the model server. Raises on any failure (the caller falls back)."""
    body = {"text": steering.apply_emphasis(text, style.get("emph")) if style.get("emph") else text,
            "voice": style["steer_voice"], "tag": style["tag"], "controls": style["controls"] or None,
            "markup": bool(style.get("emph"))}
    if style.get("guidance"):
        body["guidance"] = style["guidance"]
    if style.get("perform"):
        body["perform"] = {**style["perform"], **{k: v for k, v in place.items() if v is not None}}
    async with httpx.AsyncClient(base_url=settings.model_server_url, timeout=settings.tts_timeout_s) as c:
        r = await c.post("/v1/tts", json=body)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"steer tts {r.status_code}: {r.text[:160]}")
    return r.content


def _store(p: Path, audio: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(audio)
    tmp.replace(p)


async def speak(text: str, voice: str = "guide", style: dict | None = None, i: int | None = None,
                n: int | None = None, next_text: str | None = None):
    text = " ".join(text.split())
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=422)
    reasons: list[str] = []
    engines = ["steer", "deepgram"] if settings.tts_engine == "steer" else ["deepgram"]
    for engine in engines:
        if engine == "steer":
            st = clean_style(voice, text, style)
            place = {"para_index": i, "para_len": n, "next": " ".join((next_text or "").split())[:MAX_CHARS] or None}
            model, key = st["steer_voice"], {**st, **{k: v for k, v in place.items() if v is not None}}
        else:
            if not settings.deepgram_api_key:
                reasons.append("deepgram: DEEPGRAM_API_KEY is not set")
                continue
            st, model, key = None, VOICES[voice], None
        p = cache_path(model, text, key, engine)
        media = MEDIA[engine][0]
        headers = {"Cache-Control": "public, max-age=604800", "X-TTS-Voice": model, "X-TTS-Engine": engine}
        if st:
            headers["X-TTS-Style"] = f"{st['tag']} " + ",".join(f"{k}={v}" for k, v in st["controls"].items())
        if reasons:
            headers["X-TTS-Fallback"] = "; ".join(reasons)[:200]
        if p.exists():
            return Response(p.read_bytes(), media_type=media, headers={**headers, "X-TTS-Cache": "hit"})
        try:
            audio = await (_steer(text, st, place) if engine == "steer" else _synth(model, text))
        except Exception as e:  # noqa: BLE001 - any upstream failure means "next engine"
            reasons.append(f"{engine}: {str(e)[:160]}")
            continue
        _store(p, audio)
        return Response(audio, media_type=media, headers={**headers, "X-TTS-Cache": "miss"})
    no_engine = all(r.startswith("deepgram: DEEPGRAM_API_KEY") for r in reasons)
    return JSONResponse({"error": "tts unavailable" if no_engine else "tts failed", "reason": "; ".join(reasons)[:300],
                         "fallback": "browser"}, status_code=503 if no_engine else 502)


def _parse_style(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


@router.get("/api/tts")
async def tts(text: str = Query(..., min_length=1, max_length=MAX_CHARS), voice: Persona = "guide",
              style: str | None = Query(None, max_length=2000), i: int | None = Query(None, ge=0, le=200),
              n: int | None = Query(None, ge=1, le=200), next: str | None = Query(None, max_length=MAX_CHARS)):  # noqa: A002
    return await speak(text, voice, _parse_style(style), i, n, next)


class TTSBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHARS)
    voice: Persona = "guide"
    style: dict | None = None
    i: int | None = Field(None, ge=0, le=200)
    n: int | None = Field(None, ge=1, le=200)
    next: str | None = Field(None, max_length=MAX_CHARS)


@router.post("/api/tts")
async def tts_post(b: TTSBody):
    return await speak(b.text, b.voice, b.style, b.i, b.n, b.next)
