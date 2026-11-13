"""Mission Trainer API (docs/MISSION_CONTRACT.md)."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from . import registry, sim

router = APIRouter()

FRAME_S = 1.0          # one telemetry frame per second
SHIFT_PREVIEW_S = 30.0  # a 6-hour shift plays out over ~30 s of wall time, then holds


class StartReq(BaseModel):
    site: str
    seed: int | None = None
    roles: list[str] | None = None


class CommandReq(BaseModel):
    command: dict


class AdvanceReq(BaseModel):
    shifts: int = Field(1, ge=1, le=40)


def _mission(mid: str) -> sim.Mission:
    m = registry.get(mid)
    if m is None:
        raise HTTPException(404, "no such mission")
    return m


@router.get("/api/mission/sites")
def mission_sites():
    return {"sites": [sim.public_site(s) for s in sim.sites()]}


@router.post("/api/mission/start")
def mission_start(req: StartReq):
    try:
        m = registry.create(req.site, req.seed, req.roles)
    except KeyError:
        raise HTTPException(404, f"unknown site {req.site!r}")
    return sim.to_state(m)


@router.get("/api/mission/{mid}")
def mission_state(mid: str):
    return sim.to_state(_mission(mid))


@router.post("/api/mission/{mid}/command")
def mission_command(mid: str, req: CommandReq):
    _mission(mid)
    if not isinstance(req.command.get("type"), str):
        raise HTTPException(422, "command.type is required")
    return registry.apply(mid, req.command)


@router.post("/api/mission/{mid}/advance")
def mission_advance(mid: str, req: AdvanceReq | None = None):
    _mission(mid)
    return registry.advance(mid, (req.shifts if req else 1))


@router.get("/api/mission/{mid}/debrief")
def mission_debrief(mid: str):
    return sim.debrief(_mission(mid))


@router.websocket("/ws/mission/{mid}")
async def mission_ws(ws: WebSocket, mid: str):
    await ws.accept()
    m = registry.get(mid)
    if m is None:
        await ws.send_json({"t": "error", "error": "no such mission"})
        await ws.close(code=4404)
        return
    last_key, since = None, time.monotonic()
    try:
        while True:
            key = (m.t_h, tuple(m.loads.values()), m.shelter, m.rover["busy"], m.over)
            if key != last_key:  # state changed: restart the in-shift preview
                last_key, since = key, time.monotonic()
            offset = min(sim.SHIFT_H, (time.monotonic() - since) / SHIFT_PREVIEW_S * sim.SHIFT_H)
            await ws.send_json(sim.telemetry(m, 0 if m.over else offset))
            await asyncio.sleep(FRAME_S)
    except (WebSocketDisconnect, RuntimeError):
        return
