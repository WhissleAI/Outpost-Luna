"""Ask the Moon backend. Owns the app's data and decisions; calls the model server for model output."""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm, models_client
from .listen import router as listen_router
from .config import settings
from .gazetteer import Gazetteer
from .director import _voice as voice_moment, direct
from .moments import MomentIndex, public
from .readout import summarize

S: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    S["gaz"] = Gazetteer(settings.data_dir / "places.json")
    S["index"] = MomentIndex(settings.data_dir / "index/clips.json")
    yield


app = FastAPI(title="Ask the Moon backend", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"])


class Playing(BaseModel):
    clip_id: str
    t: float = 0.0


class AskContext(BaseModel):
    last_place: str | None = None
    emotion: str | None = None
    playing: Playing | None = None


class AskRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)
    context: AskContext | None = None


@app.get("/api/health")
async def health():
    return {"ok": True, "places": len(S["gaz"].places), "artifacts": len(S["gaz"].artifacts), "clips": len(S["index"].clips),
            "moments": len(S["index"].moments), "facts": len(S["index"].facts), "glossary": len(S["index"].glossary_terms),
            "llm": "on" if llm.available() else "off", "model_server": await models_client.health()}


@app.get("/api/places")
def places():
    return {"places": [p.public() for p in S["gaz"].places.values()]}


@app.get("/api/clips")
def clips():
    S["index"].refresh()
    return {"clips": S["index"].clips}


@app.get("/api/clips/{clip_id}")
def clip(clip_id: str):
    """One clip's word timings, tags and utterances (karaoke + place-following for a playing moment)."""
    S["index"].refresh()
    c = next((c for c in S["index"].clips if c["id"] == clip_id), None)
    if not c:
        raise HTTPException(404, "no such clip")
    return {k: c.get(k) for k in ("id", "title", "file", "dur", "words", "tags", "utterances")}


@app.get("/api/moments")
def moments(place: str | None = None):
    S["index"].refresh()
    if place:
        return {"moments": [public(m) for m in S["index"].for_place(place, 5)]}
    return {"moments": [public(m) for m in S["index"].moments]}


@app.get("/api/moments/{moment_id}")
def moment(moment_id: str):
    S["index"].refresh()
    m = S["index"].get(moment_id)
    if not m and "-voice-" in moment_id:  # an artifact's voices span ("duke-voice-apollo16_lrv")
        p = S["gaz"].places.get(moment_id.split("-voice-", 1)[1])
        m = voice_moment(p, S["index"]) if p else None
    if not m:
        raise HTTPException(404, "no such moment")
    return public(m)


@app.post("/api/ask")
async def ask(req: AskRequest):
    S["index"].refresh()
    read = summarize(await models_client.tag(req.text, "assistant"))
    ctx = req.context.model_dump(exclude_none=True) if req.context else None
    return await direct(req.text, read, S["gaz"], S["index"], ctx)


app.include_router(listen_router)
from .mission.routes import router as mission_router; app.include_router(mission_router)  # noqa: E402

# NASA media (audio supports HTTP Range for seeking), and the built frontend when it exists.
app.mount("/media", StaticFiles(directory=settings.data_dir / "media"), name="media")
if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
