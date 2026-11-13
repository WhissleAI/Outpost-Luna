"""Model server: the only process that loads model weights. Apps call it over HTTP.

Written as a plain FastAPI app so it can later run unchanged as a Ray Serve deployment (`@serve.ingress(app)`)
when models need their own replicas and autoscaling.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator

from .arctag import ArcTagger
from .config import settings

STATE: dict = {"tagger": None, "tagger_error": None, "loaded_s": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = time.perf_counter()
    try:
        STATE["tagger"] = ArcTagger(settings.arctag_lib, settings.arctag_model_dir,
                                    [d.strip() for d in settings.arctag_domains.split(",") if d.strip()],
                                    settings.arctag_pool_size)
    except Exception as e:  # serve /health with the reason instead of crashing
        STATE["tagger_error"] = str(e)
    STATE["loaded_s"] = round(time.perf_counter() - t, 2)
    yield
    if STATE["tagger"]:
        STATE["tagger"].close()


app = FastAPI(title="Ask the Moon model server", version="0.1.0", lifespan=lifespan)


class TagRequest(BaseModel):
    text: str | None = Field(None, description="Plain text")
    words: list[str] | None = Field(None, description="Words in order; spans index into this list")
    domain: str = Field("assistant", description="assistant | news | talk (as loaded)")

    @model_validator(mode="after")
    def one_input(self):
        if bool(self.text) == bool(self.words):
            raise ValueError("send exactly one of text or words")
        if self.words and any(not w or " " in w for w in self.words):
            raise ValueError("words must be non-empty and contain no spaces")
        return self


@app.get("/health")
def health():
    tg = STATE["tagger"]
    return {
        "ok": tg is not None,
        "models": {"arc_tagger": {"loaded": tg is not None, "error": STATE["tagger_error"],
                                  "domains": sorted(tg.pools) if tg else [],
                                  "pool_size": settings.arctag_pool_size}},
        "load_s": STATE["loaded_s"],
    }


@app.post("/v1/tag")
async def tag(req: TagRequest):
    tg = STATE["tagger"]
    if tg is None:
        raise HTTPException(503, f"Arc Tagger not loaded: {STATE['tagger_error']}")
    text = req.text if req.text else " ".join(req.words)
    t = time.perf_counter()
    try:
        out = await run_in_threadpool(tg.tag_text, text, req.domain)
    except KeyError as e:
        raise HTTPException(400, str(e))
    out["ms"] = round((time.perf_counter() - t) * 1000, 2)
    if req.words and len(out.get("words", [])) != len(req.words):
        raise HTTPException(500, "tagger word split does not match the words sent")
    return out
