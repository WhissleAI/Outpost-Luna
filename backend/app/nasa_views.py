"""Real NASA views (0.4): the optional "nasa_views" asset (scripts/nasa_views_build.py -> scripts/asset_pack.py).

What it holds (index.json describes it; backend/data/SOURCES.md "NASA views" lists every source):
  sky/      SVS 4851 Deep Star Maps 2020 (the globe's real star sky)
  models/   NASA 3D Resources GLBs (Apollo LM, HDU, RASSOR, Mission Control, LRO, LADEE)
  rocks/    six Apollo samples (NASA/Astromaterials 3D, CC0) for the Library's Moon rocks tray
  images/   Earthrise / Earthset and Artemis geology-training photos (NASA Images, PD)
  sdo/      SDO AIA frames of the 14 May 2024 storm (AR 13664)
  names/    IAU/USGS nomenclature near the south pole and the Apollo sites

Where it lives: NASA_VIEWS_DIR (set by the desktop app from the asset manifest), else <data_dir>/cache/nasa_views (dev).
The app works without it (today's visuals): GET /api/views says {"state": "missing" | "downloading"}. On the desktop
POST /api/views/want asks the main process for it (<ASSETS_DIR>/.want/nasa_views), like the site navigator's layers.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .config import settings

router = APIRouter()
ASSET_ID = "nasa_views"
# only these folders and types are served; a name is one path segment of [A-Za-z0-9_.-] (no "..", no slashes)
_FILE = re.compile(r"(sky|models|rocks|images|sdo|names)/([A-Za-z0-9_-][A-Za-z0-9_.-]{0,80})\.(jpg|jpeg|png|webp|glb|json)")
_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
          "glb": "model/gltf-binary", "json": "application/json"}


def views_dir() -> Path:
    env = os.environ.get("NASA_VIEWS_DIR")
    return Path(env) if env else settings.data_dir / "cache" / "nasa_views"


def load_index() -> dict | None:
    """index.json of the installed pack, or None (absent or unreadable: the app keeps today's visuals)."""
    f = views_dir() / "index.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("pack") == ASSET_ID else None


def present(d: dict) -> dict:
    """Drop index entries whose file is not on disk (a partial dev build): the client never asks for a missing file."""
    base = views_dir()
    have = lambda e: isinstance(e, dict) and isinstance(e.get("file"), str) and _FILE.fullmatch(e["file"]) and (base / e["file"]).is_file()
    out = dict(d)
    for k in ("models", "rocks", "images"):
        out[k] = [e for e in d.get(k) or [] if have(e)]
    for k in ("sky", "names"):
        out[k] = d[k] if have(d.get(k)) else None
    sdo = d.get("sdo")
    if isinstance(sdo, dict):
        frames = [f for f in sdo.get("frames") or [] if have(f)]
        out["sdo"] = {**sdo, "frames": frames} if frames else None
    else:
        out["sdo"] = None
    return out


def state() -> dict:
    d = load_index()
    if d is not None:
        return {"state": "ready", **present(d)}
    assets = os.environ.get("ASSETS_DIR")
    busy = bool(assets) and (Path(assets) / ".active" / ASSET_ID).exists()
    return {"state": "downloading" if busy else "missing", "managed": bool(assets)}


@router.get("/api/views")
def views():
    """The installed pack's index (files that are present only), or its download state."""
    return state()


@router.post("/api/views/want")
def want_views():
    """Desktop: ask the main process to download the optional pack now (on-demand asset)."""
    assets = os.environ.get("ASSETS_DIR")
    if not assets:
        return {"ok": False, "managed": False}
    w = Path(assets) / ".want"
    w.mkdir(parents=True, exist_ok=True)
    (w / ASSET_ID).write_text("")
    return {"ok": True, "managed": True}


@router.get("/api/views/file/{folder}/{name}")
def view_file(folder: str, name: str):
    rel = f"{folder}/{name}"
    m = _FILE.fullmatch(rel)
    if not m:
        raise HTTPException(404, "no such file")
    base = views_dir().resolve()
    f = (base / rel).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "NASA views not installed")
    return FileResponse(f, media_type=_TYPES[m.group(3)], headers={"Cache-Control": "max-age=86400"})
