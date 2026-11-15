"""The Settings voices (docs/VOICES.md): this computer's own offline OS voices, as the model server ranks them.

GET /api/voices                        → [{id, name, desc, preview_url}], best first (the first is the default guide voice)
GET /api/voices/preview/<id>.wav       → a short line in that voice, rendered on demand through /api/tts (so it is
                                         cached on disk and mastered like every other line)

The list comes from the model server's GET /v1/tts/voices (macOS: premium > enhanced > compact, novelty voices never;
Windows: OneCore / natural > SAPI), cached for TTL_S. `allowed()` is the allow-list `/api/tts` and the session's
`prefs` accept for a voice id: the persona roles (guide, capcom, houston, story) plus the installed voices.
`resolve()` turns a role into the concrete voice the model server picked for it, so the TTS cache key names the real
voice (a parent who installs a better voice gets new audio, not a stale rendering).
"""
from __future__ import annotations

import re
import time

import httpx
from fastapi import APIRouter, HTTPException

from . import steering
from .config import settings

router = APIRouter()
PREVIEW_PREFIX = "/api/voices/preview"
PREVIEW_LINE = "Hello! Ready to fly?"
TTL_S, RETRY_S = 30.0, 5.0
VOICE_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,160}$")
CATALOG: dict = {"voices": [], "roles": {}, "at": 0.0, "tried": 0.0}


def set_catalog(data: dict | None) -> None:
    """Install a GET /v1/tts/voices reply (tests use this too). None = the model server had nothing."""
    data = data or {}
    vs = [v for v in data.get("voices") or [] if isinstance(v, dict) and VOICE_ID.match(str(v.get("id", "")))]
    CATALOG.update(voices=vs, roles=dict(data.get("roles") or {}), engine=data.get("engine"), at=time.monotonic())


def _fresh() -> bool:
    return bool(CATALOG["voices"]) and time.monotonic() - CATALOG["at"] < TTL_S


async def refresh() -> None:
    """Re-read the list from the model server when stale. Fails open: the last good list stays."""
    if _fresh() or time.monotonic() - CATALOG["tried"] < (RETRY_S if not CATALOG["voices"] else TTL_S):
        return
    CATALOG["tried"] = time.monotonic()
    try:
        async with httpx.AsyncClient(base_url=settings.model_server_url, timeout=3.0) as c:
            r = await c.get("/v1/tts/voices")
        if r.status_code == 200:
            set_catalog(r.json())
    except (httpx.HTTPError, ValueError):
        pass


def refresh_sync() -> None:
    """The same, blocking and short, for sync callers (the session's prefs) that run before any async refresh did."""
    if CATALOG["voices"] or time.monotonic() - CATALOG["tried"] < RETRY_S:
        return
    CATALOG["tried"] = time.monotonic()
    try:
        r = httpx.get(settings.model_server_url.rstrip("/") + "/v1/tts/voices", timeout=1.5)
        if r.status_code == 200:
            set_catalog(r.json())
    except (httpx.HTTPError, ValueError):
        pass


def curated() -> list[dict]:
    """The voices Settings offers (the model server's `picker` set), best first."""
    vs = CATALOG["voices"]
    return [v for v in vs if v.get("picker", True)]


def ids() -> list[str]:
    return [v["id"] for v in CATALOG["voices"]]


def roles() -> dict[str, str]:
    return dict(CATALOG["roles"])


def allowed(voice_id: object) -> bool:
    if not isinstance(voice_id, str):
        return False
    if voice_id in steering.VOICES.values():
        return True
    if not CATALOG["voices"]:
        refresh_sync()
    return voice_id in ids()


def resolve(voice_id: str) -> str:
    """A role -> the installed voice the model server gave it; an installed id -> itself. Unknown: unchanged (the
    model server resolves it again, falling back to the guide's voice)."""
    return CATALOG["roles"].get(voice_id) or voice_id


def cache_tag(voice_id: str) -> str:
    """The voice as the TTS cache should know it: the system voice also names the voice behind it, so a parent who
    switches the Mac's system voice gets new audio."""
    v = next((x for x in CATALOG["voices"] if x["id"] == voice_id), None)
    return f"{voice_id}@{v['system_voice']}" if v and v.get("system_voice") else voice_id


def public() -> list[dict]:
    return [{"id": v["id"], "name": v.get("name") or v["id"], "desc": v.get("desc") or "",
             "preview_url": f"{PREVIEW_PREFIX}/{v['id']}.wav"} for v in curated()]


@router.get("/api/voices")
async def list_voices():
    await refresh()
    return public()


@router.get(PREVIEW_PREFIX + "/{voice_id}.wav")
async def preview(voice_id: str):
    await refresh()
    if not VOICE_ID.match(voice_id) or voice_id not in ids():
        raise HTTPException(404, "no such voice on this computer")
    from . import tts
    r = await tts.speak(PREVIEW_LINE, "guide", {"tts_voice": voice_id})
    if r.status_code != 200:
        raise HTTPException(503, "voice preview unavailable")
    return r
