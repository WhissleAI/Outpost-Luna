"""Mission Trainer API (docs/MISSION_CONTRACT.md)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from typing import Literal

from pydantic import BaseModel, Field

from . import registry, sim

router = APIRouter()

FRAME_S = 1.0          # one telemetry frame per second (the live clock's own position: sim.Mission.frac)


class StartReq(BaseModel):
    site: str
    seed: int | None = None
    roles: list[str] | None = None
    level: Literal["cadet", "commander"] = "cadet"   # Settings (docs/VOICES.md): the difficulty band, ages 7-9 / 10-12


class CommandReq(BaseModel):
    command: dict


class AdvanceReq(BaseModel):
    shifts: int = Field(1, ge=1, le=40)


class StepReq(BaseModel):
    dt_h: float = Field(..., ge=0, le=24)   # mission hours that passed on the client's live clock


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
        m = registry.create(req.site, req.seed, req.roles, level=req.level)
    except KeyError:
        raise HTTPException(404, f"unknown site {req.site!r}")
    return sim.to_state(m)


@router.get("/api/mission/{mid}")
def mission_state(mid: str):
    return sim.to_state(_mission(mid))


@router.get("/api/mission/{mid}/windows")
def mission_windows(mid: str):
    """Read-only: when Earth and the Sun are up over the whole mission, hour by hour, by the sim's own rule (env_at),
    as [start_h, end_h] spans. The cabin's Comm timeline and Power Sun strip draw these (Mission UX)."""
    m = _mission(mid)
    def spans(key):
        out, start = [], None
        for t in range(0, sim.MISSION_H + 1):
            up = bool(sim.env_at(m, t)[key]) if t < sim.MISSION_H else False
            if up and start is None:
                start = t
            elif not up and start is not None:
                out.append([start, t]); start = None
        return out
    return {"hours": sim.MISSION_H, "earth": spans("earth_visible"), "sun": spans("in_sun")}


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


@router.post("/api/mission/{mid}/step")
def mission_step(mid: str, req: StepReq):
    """The live mission clock (docs/GAMEPLAY.md): the client runs time (pause, 1x/2x/4x) and posts what passed."""
    _mission(mid)
    return registry.step(mid, req.dt_h)


@router.post("/api/mission/{mid}/skip")
def mission_skip(mid: str):
    """Skip to next event: the clock runs until something happens (at most a day)."""
    _mission(mid)
    return registry.skip(mid)


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
    try:
        while True:
            # the live clock moves the mission (POST /step); a frame shows it at its fractional hour
            await ws.send_json(sim.telemetry(m, 0 if m.over else m.frac, live=True))
            await asyncio.sleep(FRAME_S)
    except (WebSocketDisconnect, RuntimeError):
        return
