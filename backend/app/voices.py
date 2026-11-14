"""The Settings voices (docs/VOICES.md): 10 curated Steer TTS Edge voices with offline preview clips.

GET /api/voices                        → [{id, name, desc, preview_url}]
GET /api/voices/preview/<id>.wav       → the pre-rendered preview (16 kHz mono, ~2 s; static, from data/voice_previews)

`data/voices.json` is written by tools/voice_curate.py (scores included); this module only reads it. `allowed()` is the
allow-list `/api/tts` and the session's `prefs` accept for a voice id: the curated ids plus the persona voices.
"""
from __future__ import annotations

import json

from fastapi import APIRouter

from . import steering
from .config import settings

router = APIRouter()
PREVIEW_PREFIX = "/api/voices/preview"
_CACHE: dict = {}


def path():
    return settings.data_dir / "voices.json"


def previews_dir():
    return settings.data_dir / "voice_previews"


def load() -> dict:
    p = path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {"voices": []}
    if _CACHE.get("mtime") != mtime:
        _CACHE["data"], _CACHE["mtime"] = json.loads(p.read_text()), mtime
    return _CACHE["data"]


def curated() -> list[dict]:
    return list(load().get("voices") or [])


def ids() -> list[str]:
    return [v["id"] for v in curated()]


def allowed(voice_id: object) -> bool:
    return isinstance(voice_id, str) and (voice_id in ids() or voice_id in steering.VOICES.values())


def public() -> list[dict]:
    return [{"id": v["id"], "name": v["name"], "desc": v["desc"], "preview_url": f"{PREVIEW_PREFIX}/{v['id']}.wav"}
            for v in curated()]


@router.get("/api/voices")
def list_voices():
    return public()
