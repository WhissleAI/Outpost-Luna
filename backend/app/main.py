"""Ask the Moon backend. Owns the app's data and decisions; calls the model server for model output."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm, models_client
from .config import settings
from .gazetteer import Gazetteer
from .moments import MomentIndex
from .readout import summarize
from .resolve import resolve

S: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    S["gaz"] = Gazetteer(settings.data_dir / "places.json")
    S["index"] = MomentIndex(settings.data_dir / "index/clips.json")
    yield


app = FastAPI(title="Ask the Moon backend", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"])


class AskRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)


@app.get("/api/health")
async def health():
    return {"ok": True, "places": len(S["gaz"].places), "clips": len(S["index"].clips),
            "llm": "on" if llm.available() else "off", "model_server": await models_client.health()}


@app.get("/api/places")
def places():
    return {"places": [asdict(p) for p in S["gaz"].places.values()]}


@app.get("/api/clips")
def clips():
    S["index"].refresh()
    return {"clips": S["index"].clips}


@app.post("/api/ask")
async def ask(req: AskRequest):
    S["index"].refresh()
    read = summarize(await models_client.tag(req.text, "assistant"))
    return await resolve(req.text, read, S["gaz"], S["index"])


# NASA media (audio supports HTTP Range for seeking), and the built frontend when it exists.
app.mount("/media", StaticFiles(directory=settings.data_dir / "media"), name="media")
if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
