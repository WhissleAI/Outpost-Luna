"""Outpost Luna backend. Owns the app's data and decisions; calls the model server for model output."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import netgate
netgate.install()   # School network mode + loopback-only listening: the one outbound gate (app/netgate.py, docs/SCHOOL_IT.md)
from . import diag, diagnostics, knowledge, models_client, network_api, reset, video  # noqa: E402
from .listen import router as listen_router
from .local_guard import LocalGuard, env_options as local_guard_options
from .config import settings
from .gazetteer import Gazetteer
from . import course_packs, courses
from .director import _voice as voice_moment, direct
from .moments import MomentIndex, public
from .readout import summarize

S: dict = {}


def course_gazetteer() -> Gazetteer:
    """The active course's places (docs/COURSES.md §4.3; the Moon: places.json + artifacts.json, as always)."""
    return Gazetteer(courses.path("gazetteer") or settings.data_dir / "places.json")


def _swap_gaz() -> None:
    S["gaz"] = course_gazetteer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    diag.setup("backend")   # [#92] JSON-lines log + metrics + the daily summary (app/diag.py, docs/DIAGNOSTICS.md)
    S["gaz"] = course_gazetteer()
    courses.on_change(_swap_gaz)   # a course switch swaps the places
    # [course switch] and starts getting what the new course still needs: its pack update, its own videos
    courses.on_change(course_packs.on_course_change)
    courses.on_change(video.on_course_change)
    S["index"] = MomentIndex(settings.data_dir / "index/clips.json")
    # Local brain: build the cards now, embed the question + command banks in the background (disk-cached; fails open).
    asyncio.create_task(_warm_brain())
    asyncio.create_task(video.prefetch_task())   # NASA video: pinned files on first online launch (docs/MEDIA.md)
    # [0.5.2] a cadet already on a course (no switch this launch) still gets its outdated pack replaced (min_version)
    course_packs.on_course_change()
    yield
    video.stop_prefetch()
    diag.shutdown()


async def _warm_brain():
    from .mission import nlu
    await knowledge.get(S["gaz"], S["index"].facts).warm()
    await nlu._bank_vecs()


app = FastAPI(title="Outpost Luna backend", version="0.2.0", lifespan=lifespan)
app.add_middleware(diagnostics.ErrorCounter)   # [#92] 5xx + unhandled exceptions, counted by code (app/diagnostics.py)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"])
# [#84] outermost: Host + Origin + per-launch token on every request and WebSocket (app/local_guard.py, docs/SECURITY.md)
app.add_middleware(LocalGuard, **local_guard_options(settings.cors_origins.split(",")))


class Playing(BaseModel):
    clip_id: str
    t: float = 0.0


class AskContext(BaseModel):
    last_place: str | None = None
    emotion: str | None = None
    playing: Playing | None = None
    mission: dict | None = None          # {"id": mid, "role": "power|life|comms|null"} (docs/MISSION_CONTRACT.md)
    device_directed: float | None = None  # Arc's last device_directed for this turn (from /ws/listen); low = chatter


class AskRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)
    context: AskContext | None = None


@app.get("/api/health")
async def health():
    return {"ok": True, "places": len(S["gaz"].places), "artifacts": len(S["gaz"].artifacts), "clips": len(S["index"].clips),
            "moments": len(S["index"].moments), "facts": len(S["index"].facts), "glossary": len(S["index"].glossary_terms),
            "llm": "none", "brain": "local", "cards": len(knowledge.get(S["gaz"], S["index"].facts).cards),
            "model_server": await models_client.health(), "voice": voice_route()}


def voice_route() -> dict:
    """Which ear the voice bar waits for: `ear` is EAR (arc | deepgram), `fallback` whether a failed local ear falls
    back to Deepgram (listen.py _listen). Without a fallback, a failed ear means voice off (frontend/src/engine.js)."""
    from .listen import ear_settings
    return {"ear": ear_settings.ear.strip().lower() or "arc", "fallback": bool(settings.deepgram_api_key)}


@app.get("/api/places")
def places():
    return {"places": [p.public() for p in S["gaz"].places.values()]}


@app.get("/api/clips")
def clips():
    S["index"].refresh()
    return {"clips": [{**c, "gain_db": clip_gain_db(c.get("file"))} for c in S["index"].clips]}


def clip_gain_db(file: str | None) -> float:
    """Playback gain (dB) that brings a crew clip to the TTS loudness target (data/clip_loudness.json, §4d); 0 unknown."""
    if "clip_gain" not in S:
        import json
        p = settings.data_dir / "clip_loudness.json"
        S["clip_gain"] = {k: v["gain_db"] for k, v in json.loads(p.read_text())["clips"].items()} if p.exists() else {}
    return S["clip_gain"].get((file or "").rsplit("/", 1)[-1], 0.0)


@app.get("/api/clips/{clip_id}")
def clip(clip_id: str):
    """One clip's word timings, tags and utterances (karaoke + place-following for a playing moment)."""
    S["index"].refresh()
    c = next((c for c in S["index"].clips if c["id"] == clip_id), None)
    if not c:
        raise HTTPException(404, "no such clip")
    out = {**{k: c.get(k) for k in ("id", "title", "file", "dur", "words", "tags", "utterances")},
           "gain_db": clip_gain_db(c.get("file"))}
    segs = clip_segs(c.get("file"))
    if segs:
        out["segs"] = segs
    return out


def clip_segs(file: str | None) -> list | None:
    """The desktop build ships trimmed crew audio (backend/pipeline/trim_media.py): [[clip_t0, file_t0, len], ...] maps
    clip time to file time (the player converts at the <audio> element). None with the original audio (dev)."""
    if not S.get("clip_segs"):    # re-read until found: the crew-audio asset may install after the backend started
        import json
        p = next((d / "trim.json" for d in settings.media_dirs() if (d / "trim.json").exists()), None)
        S["clip_segs"] = ({k: v["segs"] for k, v in json.loads(p.read_text(encoding="utf-8"))["clips"].items()}
                          if p else {})
    return S["clip_segs"].get((file or "").rsplit("/", 1)[-1])


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
# [#92] GET /api/metrics (token-protected) + Settings -> Help & diagnostics (app/diagnostics.py, docs/DIAGNOSTICS.md)
app.include_router(diag.metrics_router("/api/metrics"))
app.include_router(diagnostics.router)
diagnostics.install_mission_hooks()   # mission saves / loads / failures, counted around app/mission/registry.py
from .mission.routes import router as mission_router; app.include_router(mission_router)  # noqa: E402
from .mission.navigator import router as navigator_router; app.include_router(navigator_router)  # noqa: E402  (site navigator)
from .session import router as session_router; app.include_router(session_router)  # noqa: E402  (docs/SESSION_CONTRACT.md)
from .academy.routes import router as academy_router; app.include_router(academy_router)  # noqa: E402  (Academy)
from .academy.class_routes import router as class_router; app.include_router(class_router)  # noqa: E402  (Class lessons, docs/CURRICULUM.md)
from .tts import router as tts_router; app.include_router(tts_router)  # noqa: E402  (audio floor: GET /api/tts)
app.include_router(video.router)  # NASA video: catalog, offline cache, captions (docs/MEDIA.md)
app.include_router(reset.router)  # Settings → Reset Outpost Luna (docs/RESET.md)
network_api.setup(); app.include_router(network_api.router)  # Settings → For grown-ups → School network (docs/SCHOOL_IT.md)
from . import voices as _voices; app.include_router(_voices.router)  # noqa: E402  (Settings: GET /api/voices, docs/VOICES.md)
from .assets_api import router as assets_router; app.include_router(assets_router)  # noqa: E402  (Settings: About / Storage)
from .learn.api import router as learn_router; app.include_router(learn_router)  # noqa: E402  (on-device learning, docs/ON_DEVICE_LEARNING.md)
from .brain import router as brain_router; app.include_router(brain_router)  # noqa: E402  (the Brain: grown-up counts, docs/BRAIN.md)
from .playtest import router as playtest_router; app.include_router(playtest_router)  # noqa: E402  (a grown-up's Playtest session, docs/DIRECTOR_LOOP.md)
from .nasa_views import router as views_router; app.include_router(views_router)  # noqa: E402  (0.4 real NASA views, optional asset)
from .courses import router as courses_router; app.include_router(courses_router)  # noqa: E402  (read-only course manifests, docs/COURSES.md)
from .course_library import router as library_router; app.include_router(library_router)  # noqa: E402  (a course's Library: docs/COURSES.md "Course library")
from .course_packs import router as course_packs_router; app.include_router(course_packs_router)  # noqa: E402  (course packs: download / remove, docs/COURSES.md §4.2)

@app.get("/api/turnlog")
def turnlog_stats():
    """Settings -> "Help improve the voice guide": how much the turn log holds on this device (docs/DIRECTOR_LOOP.md)."""
    from . import turnlog
    return turnlog.STORE.stats()


@app.delete("/api/turnlog")
def turnlog_clear():
    """Delete the turn log on this device, and any playtest audio (Settings: "Delete what's saved")."""
    from . import turnlog
    return {"deleted_files": turnlog.STORE.clear()}


@app.get("/api/safety/flags")
def safety_flags(request: Request, profile: str | None = None):
    """[P0] The grown-up side (Settings → For grown-ups): the care banner's data from the safety ledger
    (app/safety_ledger.py): per cadet profile and day, the guide suggested a break and a trusted grown-up. Never the
    words. On this device only, kept 30 days, cleared by Reset. The local token, like /api/brain/summary."""
    from . import diag, safety, safety_ledger
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")
    from .learn.store import profile_id
    rows = safety_ledger.LEDGER.care(profile_id(profile) if profile else None)
    return {"flags": [{"kind": "care", **r} for r in rows], "line": safety.CARE_LINE,
            "retain_days": safety_ledger.RETAIN_CARE, "words": False}


@app.post("/api/safety/flags/dismiss")
async def safety_flags_dismiss(request: Request):
    """Hide one care banner ({profile, day}). The ledger entry itself stays until its 30 days are up."""
    from . import diag, safety_ledger
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")
    try:
        body = await request.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    from .learn.store import profile_id
    day = body.get("day") if isinstance(body.get("day"), str) else ""
    return {"dismissed": safety_ledger.LEDGER.dismiss_care(profile_id(body.get("profile")), day)}


@app.get("/api/director/stats")
def director_stats():
    """The learned Director (DIRECTOR_MODEL=off|shadow|guarded|on): mode, model, and shadow agreement with the rules."""
    from .director_model import runtime as dmodel
    return dmodel.stats()


# NASA media (audio supports HTTP Range for seeking), and the built frontend when it exists.
class MediaFiles(StaticFiles):
    """StaticFiles over several folders, first hit wins (settings.media_dirs: the desktop's installed crew-audio asset,
    then data_dir/media). A folder that does not exist yet (an asset still downloading) is simply skipped."""

    def __init__(self, dirs):
        self.dirs = list(dirs)
        super().__init__(directory=self.dirs[-1], check_dir=False)

    def get_directories(self, directory=None, packages=None):
        return [str(d) for d in self.dirs]


app.mount("/media", MediaFiles(settings.media_dirs()), name="media")
# Settings: the Steer voices' previews (pre-rendered, offline), before the frontend's catch-all mount.
app.mount(_voices.STEER_PREVIEW_PREFIX, StaticFiles(directory=_voices.steer_previews_dir(), check_dir=False),
          name="steer_voice_previews")
if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")

