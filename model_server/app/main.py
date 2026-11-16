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

from . import arcmeta, embed, tts_os, tts_steer
from .arctag import ArcTagger
from . import tag_stream
from .config import settings
from .local_guard import LocalGuard, env_options as local_guard_options

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
    arcmeta.load()   # ARC_META=mini|off; fails open, reason in /health
    tts_os.load()      # OS_TTS=on|off: the OS's own voices, warmed up; fails open, reason in /health
    embed.load()     # EMBED=on|off; fails open, reason in /health
    tts_steer.ensure()   # STEER_TTS=on|off, the optional engine: loads now if its asset is there, else on first use
    yield
    if STATE["tagger"]:
        STATE["tagger"].close()


app = FastAPI(title="Outpost Luna model server", version="0.1.0", lifespan=lifespan)
# [#84] Host + Origin + per-launch token on every request and WebSocket (app/local_guard.py, docs/SECURITY.md). No
# browser page ever talks to the model server: only the backend (server side, with the token) and local tools.
app.add_middleware(LocalGuard, **local_guard_options())
app.include_router(tag_stream.router)  # WS /v1/tag/stream
from .routes_meta import router as meta_router  # noqa: E402
app.include_router(meta_router)  # POST /v1/meta, WS /v1/stream
app.include_router(tts_steer.router)  # POST /v1/tts/steer, GET /v1/tts/steer/voices (the optional Steer engine)
app.include_router(tts_os.router)  # POST /v1/tts, GET /v1/tts/voices (the OS's offline voices)
app.include_router(embed.router)  # POST /v1/embed


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
                                  "pool_size": settings.arctag_pool_size},
                   **arcmeta.health(), **tts_os.health(), **tts_steer.health(), **embed.health()},
        "load_s": STATE["loaded_s"],
        "rss_mb": _rss_mb(),
    }


def _rss_mb() -> dict:
    """Current and peak resident memory in MB. Never raises: /health is the desktop app's readiness probe, so a
    failure here (e.g. the POSIX-only `resource` module on Windows) would leave the app waiting forever."""
    import sys

    import psutil
    out = {"now": None, "peak": None}
    try:
        mi = psutil.Process().memory_info()
        out["now"] = round(mi.rss / 2**20)
        if sys.platform == "win32":
            out["peak"] = round(getattr(mi, "peak_wset", mi.rss) / 2**20)   # Windows peak working set
        else:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            out["peak"] = round(peak / (2**20 if sys.platform == "darwin" else 2**10))  # bytes on macOS, KiB on Linux
    except Exception:  # noqa: BLE001 - diagnostics only
        pass
    return out


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
