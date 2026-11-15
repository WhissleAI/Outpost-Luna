"""Settings -> About / Storage: the desktop app's installed assets and their updates (docs/DESKTOP.md "Asset updates").

The renderer only talks to our own origin, so the Electron main process (desktop/main/updates.js) shares its state
through two files whose paths it passes in the environment:
  ASSETS_STATE_FILE  the summary it writes: {managed, app_version, installed: [{id, title, version, bytes, ...}],
                     total_bytes, update: {state: up_to_date|available|downloading|paused|ready|offline|error, ...}}
  ASSETS_CHECK_FILE  touched by POST /api/assets/check; the main process watches it and runs a check
GET /api/assets/busy tells the background downloader to wait (a mission runs or a video streams), like the video
prefetch. In a dev checkout (no desktop) GET /api/assets answers {"managed": false}.
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter

from .config import settings

router = APIRouter()


@router.get("/api/assets")
def assets():
    f = settings.assets_state_file
    if not f:
        return {"managed": False}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"managed": True, "error": "unreadable"}
    except (OSError, ValueError):
        return {"managed": True, "installed": [], "update": {"state": "unknown"}}


@router.post("/api/assets/check")
def check():
    f = settings.assets_check_file
    if not f:
        return {"ok": False, "managed": False}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(time.time()), encoding="utf-8")
    return {"ok": True}


@router.get("/api/assets/busy")
def busy():
    from . import video
    try:
        return {"busy": bool(video.busy())}
    except Exception:  # noqa: BLE001 (never stall the downloader on an error here)
        return {"busy": False}
