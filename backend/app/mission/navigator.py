"""The landing-site navigator (docs/SITE_NAVIGATOR.md): real NASA numbers per site, NASA-style scoring, polar map layers.

Data: backend/data/sites_physics.json, built at BUILD time by pipeline/site_physics.py (never fetched at runtime).
Layers: the optional "site_layers" asset (5 PNGs + layers.json). Where they live:
  SITE_LAYERS_DIR        set by the desktop app (first-run asset manifest) to the installed folder
  <data_dir>/cache/site_layers   the dev checkout (`python -m pipeline.site_physics layers`)
The app works without them: GET /api/sites/navigator says {"layers": {"state": "missing" | "downloading"}} and the map
shows "Map layers downloading". On the desktop, POST /api/sites/layers/want asks the main process for the asset
(<ASSETS_DIR>/.want/site_layers, the same on-demand path as the Steer voice).

Scoring mirrors frontend/src/mission/navigator_score.js (tests check both against the same cases).
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings
from . import sim

router = APIRouter()
ASSET_ID = "site_layers"
LAYER_IDS = ("relief", "sunlight", "slope", "ice", "earth")

# Each criterion as a 0..1 score (1 = best). The ranges are the navigator's own scale (shown in the UI), chosen to span
# the 14 places: sunlight 30-90 %, Earth 0-100 %, ice 0-15 km, slope 0-15 deg.
CRITERIA = {
    "power": {"field": "sunlight_pct", "lo": 30.0, "hi": 90.0, "better": "high"},
    "comms": {"field": "earth_pct", "lo": 0.0, "hi": 100.0, "better": "high"},
    "ice": {"field": "ice_km", "lo": 0.0, "hi": 15.0, "better": "low"},
    "safety": {"field": "slope_deg", "lo": 0.0, "hi": 15.0, "better": "low"},
}
PRESETS = {
    "balanced": {"power": 1, "comms": 1, "ice": 1, "safety": 1},
    "power_first": {"power": 3, "comms": 1, "ice": 1, "safety": 1},
    "ice_first": {"power": 1, "comms": 1, "ice": 3, "safety": 1},
    "comms_first": {"power": 1, "comms": 3, "ice": 1, "safety": 1},
    "safety_first": {"power": 1, "comms": 1, "ice": 1, "safety": 3},
}


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads((settings.data_dir / "sites_physics.json").read_text())


def places() -> list[dict]:
    return load()["places"]


def place(pid: str) -> dict:
    for p in places():
        if p["id"] == pid:
            return p
    raise KeyError(pid)


def criterion(p: dict, cid: str) -> float:
    """0..1, 1 = best, for one criterion of one place."""
    c = CRITERIA[cid]
    v = p[c["field"]]["value"]
    if v is None:
        return 0.0
    t = (float(v) - c["lo"]) / (c["hi"] - c["lo"])
    t = max(0.0, min(1.0, t))
    return t if c["better"] == "high" else 1.0 - t


def score(p: dict, weights: dict | None = None) -> int:
    """0..100: the weighted mean of the four criteria (weights 0..3; all zero -> balanced)."""
    w = {k: max(0.0, float((weights or {}).get(k, 1))) for k in CRITERIA}
    if not sum(w.values()):
        w = {k: 1.0 for k in CRITERIA}
    tot = sum(w.values())
    return round(100 * sum(w[k] * criterion(p, k) for k in CRITERIA) / tot)


def best(field: str) -> dict:
    """The place with the most sunlight / Earth, or the least ice distance / slope ("which site has the most ice?")."""
    c = next(c for c in CRITERIA.values() if c["field"] == field)
    vals = [p for p in places() if p[field]["value"] is not None]
    return (max if c["better"] == "high" else min)(vals, key=lambda p: p[field]["value"])


# ---------------------------------------------------------------- layers
def layers_dir() -> Path:
    env = os.environ.get("SITE_LAYERS_DIR")
    return Path(env) if env else settings.data_dir / "cache" / "site_layers"


def layers_state() -> dict:
    d = layers_dir()
    if (d / "layers.json").exists() and all((d / f"{i}.png").exists() for i in LAYER_IDS):
        return {"state": "ready", **json.loads((d / "layers.json").read_text())}
    assets = os.environ.get("ASSETS_DIR")
    busy = bool(assets) and ((Path(assets) / ".active" / ASSET_ID).exists() or (Path(assets) / ".want" / ASSET_ID).exists())
    return {"state": "downloading" if busy else "missing", "managed": bool(assets)}


@router.get("/api/sites/navigator")
def navigator():
    d = load()
    playable = {s["id"] for s in sim.sites()}
    return {"places": [{**p, "playable": p["id"] in playable, "site": p.get("site") or (p["id"] if p["id"] in playable else None)}
                       for p in d["places"]],
            "sources": d["sources"], "criteria": [{**c, **CRITERIA[c["id"]]} for c in d["criteria"]["items"]],
            "criteria_source": d["sources"][d["criteria"]["source"]], "presets": PRESETS, "layers": layers_state()}


@router.post("/api/sites/layers/want")
def want_layers():
    """Desktop: ask the main process to download the optional map layers now (on-demand asset)."""
    assets = os.environ.get("ASSETS_DIR")
    if not assets:
        return {"ok": False, "managed": False}
    w = Path(assets) / ".want"
    w.mkdir(parents=True, exist_ok=True)
    (w / ASSET_ID).write_text("")
    return {"ok": True, "managed": True}


@router.get("/api/sites/layers/{name}")
def layer_file(name: str):
    m = re.fullmatch(r"([a-z]+)\.png", name)
    if not m or m.group(1) not in LAYER_IDS:
        raise HTTPException(404, "no such layer")
    f = layers_dir() / name
    if not f.exists():
        raise HTTPException(404, "map layers not installed")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "max-age=86400"})
