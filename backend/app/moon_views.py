"""Open Moon data: the optional "moon_views" asset (scripts/moon_views_build.py -> scripts/asset_pack.py), the same
shape as nasa_views (app/nasa_views.py) with its own NOTICE, for media beyond NASA's own pack:

  photos/  one real Apollo surface photo per landing site (NASA Image and Video Library, public domain)
  layers/  "Rock ages": the USGS Unified Geologic Map of the Moon 1:5M (2020; CC0) pre-rendered as an equirectangular
           PNG by geologic period, with a simplified legend
  models/  Apollo 11 Command Module Columbia (Smithsonian NASM 3D, CC0), simplified for the turntable
  facts/   Lunar Sample Compendium facts (NASA JSC, public domain) for the Moon rocks tray

Every index entry carries credit, source and licence_class (pd | cc0 | by | by-sa); the build refuses anything else.
Where it lives: MOON_VIEWS_DIR (set by the desktop app from the asset manifest), else <data_dir>/cache/moon_views
(dev). Without it the app is exactly as before: GET /api/moon-views says {"state": "missing" | "downloading"}.
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
ASSET_ID = "moon_views"
LICENCE_CLASSES = ("pd", "cc0", "by", "by-sa")
# only these folders and types are served; a name is one path segment with one dot (no "..", no slashes)
_FILE = re.compile(r"(photos|layers|models|facts)/([A-Za-z0-9][A-Za-z0-9_-]{0,80})\.(jpg|png|glb|json)")
_TYPES = {"jpg": "image/jpeg", "png": "image/png", "glb": "model/gltf-binary", "json": "application/json"}


def views_dir() -> Path:
    env = os.environ.get("MOON_VIEWS_DIR")
    return Path(env) if env else settings.data_dir / "cache" / "moon_views"


def load_index() -> dict | None:
    f = views_dir() / "index.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("pack") == ASSET_ID else None


def _ok(e) -> bool:
    return (isinstance(e, dict) and isinstance(e.get("file"), str) and _FILE.fullmatch(e["file"]) is not None
            and e.get("licence_class") in LICENCE_CLASSES and (views_dir() / e["file"]).is_file())


def present(d: dict) -> dict:
    """Drop entries whose file is missing or whose licence class is not one we ship: the client never asks for them."""
    out = {k: d.get(k) for k in ("schema", "pack", "version", "credit")}
    for k in ("photos", "layers", "models"):
        out[k] = [e for e in d.get(k) or [] if _ok(e)]
    facts = d.get("rock_facts")
    out["rock_facts"] = {k: v for k, v in facts.items() if isinstance(v, dict) and v.get("facts")} if isinstance(facts, dict) else {}
    return out


def state() -> dict:
    d = load_index()
    if d is not None:
        return {"state": "ready", **present(d)}
    assets = os.environ.get("ASSETS_DIR")
    busy = bool(assets) and (Path(assets) / ".active" / ASSET_ID).exists()
    return {"state": "downloading" if busy else "missing", "managed": bool(assets)}


@router.get("/api/moon-views")
def moon_views():
    return state()


@router.post("/api/moon-views/want")
def want_moon_views():
    assets = os.environ.get("ASSETS_DIR")
    if not assets:
        return {"ok": False, "managed": False}
    w = Path(assets) / ".want"
    w.mkdir(parents=True, exist_ok=True)
    (w / ASSET_ID).write_text("")
    return {"ok": True, "managed": True}


@router.get("/api/moon-views/file/{folder}/{name}")
def moon_view_file(folder: str, name: str):
    rel = f"{folder}/{name}"
    m = _FILE.fullmatch(rel)
    if not m:
        raise HTTPException(404, "no such file")
    base = views_dir().resolve()
    f = (base / rel).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "Moon views not installed")
    return FileResponse(f, media_type=_TYPES[m.group(3)], headers={"Cache-Control": "max-age=86400"})
