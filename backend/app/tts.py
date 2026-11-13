"""Server TTS for the guide channel (docs/SESSION_CONTRACT.md §4).

GET /api/tts?text=…&voice=guide|capcom|story → audio/mpeg, cached on disk by hash.

The browser plays this as in-page audio, so Chrome's echo canceller can subtract it from the mic (speechSynthesis is
rendered by the OS, outside the page, and leaks into the open mic). The client splits long text into sentences and
asks for one sentence at a time (max 600 chars), prefetching the next.

Engine today: Deepgram Aura-2 over REST (POST https://api.deepgram.com/v1/speak?model=…, JSON {"text": …}).
On-device replacement: Steer TTS behind the model server (:8200), same route and cache, swap `_synth`.

No DEEPGRAM_API_KEY → 503 JSON, and the client falls back to speechSynthesis (sentence by sentence).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from .config import settings

router = APIRouter()

SPEAK_URL = "https://api.deepgram.com/v1/speak"
MAX_CHARS = 600
# Three distinct Aura-2 voices: a warm guide, a crisp CAPCOM, a younger voice for the hardware's own story.
VOICES: dict[str, str] = {
    "guide": "aura-2-thalia-en",    # warm, clear, friendly
    "capcom": "aura-2-orion-en",    # calm, crisp male: mission control
    "story": "aura-2-iris-en",      # young, cheerful
}


CACHE_DIR: Path | None = None     # tests point this elsewhere; default data_dir/tts_cache (gitignored)


def cache_dir() -> Path:
    return CACHE_DIR or settings.data_dir / "tts_cache"


def cache_path(model: str, text: str) -> Path:
    h = hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()[:32]
    return cache_dir() / f"{h}.mp3"


async def _synth(model: str, text: str) -> bytes:
    """One Deepgram Aura call. Raises httpx.HTTPError (or RuntimeError on a non-audio reply)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(SPEAK_URL, params={"model": model, "encoding": "mp3"},
                         headers={"Authorization": f"Token {settings.deepgram_api_key}"}, json={"text": text})
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"deepgram speak {r.status_code}: {r.text[:160]}")
    return r.content


@router.get("/api/tts")
async def tts(text: str = Query(..., min_length=1, max_length=MAX_CHARS),
              voice: Literal["guide", "capcom", "story"] = "guide"):
    text = " ".join(text.split())
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=422)
    model = VOICES[voice]
    p = cache_path(model, text)
    headers = {"Cache-Control": "public, max-age=604800", "X-TTS-Voice": model}
    if p.exists():
        return Response(p.read_bytes(), media_type="audio/mpeg", headers={**headers, "X-TTS-Cache": "hit"})
    if not settings.deepgram_api_key:
        return JSONResponse({"error": "tts unavailable", "reason": "DEEPGRAM_API_KEY is not set", "fallback": "browser"},
                            status_code=503)
    try:
        audio = await _synth(model, text)
    except Exception as e:  # noqa: BLE001 - any upstream failure means "use the browser voice"
        return JSONResponse({"error": "tts failed", "reason": str(e)[:200], "fallback": "browser"}, status_code=502)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(audio)
    tmp.replace(p)
    return Response(audio, media_type="audio/mpeg", headers={**headers, "X-TTS-Cache": "miss"})
