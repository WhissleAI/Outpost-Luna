"""Settings → Reset Outpost Luna (docs/RESET.md): erase what this computer remembers about the kid.

Two levels:
  start  "Start over": the server's per-user state. That is the opt-in turn log, the TTS cache (spoken lines), and
         the in-memory missions, sessions, check rides and standing orders. The downloaded assets (models, the voice
         pack, crew audio, NASA videos) stay, so nothing has to download again.
  all    "Reset everything": the above, plus the NASA video cache and the embedding vector cache, plus the first-run
         downloads (reset_downloaded_assets, a hook: today's builds bundle every asset, so it has nothing to delete
         yet).
Progress, the call sign and every pref live in the browser (localStorage), and the shell clears them. In the desktop
app, Electron also clears its session storage and the per-user folders it owns, then relaunches (desktop/main/reset.js).

POST /api/reset?level=start|all is accepted only from our own page: same-origin (or a configured dev origin), with the
X-Outpost-Reset header (a cross-site page can't send it without a CORS preflight, which we refuse). It returns a
one-time token. The desktop shell checks that token (GET /api/reset/confirm) before it deletes anything, so nothing
else on the machine can make the app wipe itself.
"""
from __future__ import annotations

import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request

from .config import settings

router = APIRouter()
LEVELS = ("start", "all")
TOKEN_TTL_S = 60.0
_tokens: dict[str, tuple[float, str]] = {}   # token -> (issued monotonic, level)


def _rm_tree_contents(d: Path) -> int:
    """Delete everything inside d (not d itself). Returns the number of entries removed. Missing d is fine."""
    n = 0
    if not d.exists():
        return 0
    for p in list(d.iterdir()):
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            n += 1
        except OSError:
            pass   # a file the OS holds open (Windows): the desktop shell deletes the folder after stopping us
    return n


def reset_downloaded_assets() -> list[str]:
    """The first-run downloads (the desktop's per-user assets folder, settings.assets_dir) for "Reset everything". The
    backend does NOT delete them itself: the model server has the ear, tagger and embedder open (on Windows they can't
    be deleted) and the reset may still be refused. The desktop shell deletes the folder after stopping both children
    (desktop/main/reset.js: assets.clearAll + the folder), and the next launch runs the first-run download again.
    Returns the folders handed to the shell ([] in a dev checkout)."""
    d = getattr(settings, "assets_dir", None)
    return [str(d)] if d else []


def clear_memory() -> dict:
    """The in-memory per-user state: live missions, sessions, check rides, standing orders."""
    from . import session, director
    from .mission import registry
    from .academy import ride
    out = {"missions": len(registry.MISSIONS), "sessions": len(session.SESSIONS), "rides": len(ride.RIDES)}
    registry.MISSIONS.clear()
    session.SESSIONS.clear()
    ride.RIDES.clear()
    director.RULES.clear()
    director.PENDING.clear()
    return out


def targets(level: str) -> dict[str, list[Path]]:
    """Which folders each level empties (the unit tests read this). The paths come from the settings, never hard-coded."""
    from . import turnlog
    from .learn import store as learn_store
    start = [turnlog.log_dir(), settings.tts_cache(), learn_store.learn_dir()]   # learn: on-device learning
    return {"start": start, "all": start + [settings.video_cache(), settings.vector_cache()]}


def reset(level: str) -> dict:
    if level not in LEVELS:
        raise ValueError(level)
    from . import turnlog
    cleared: dict[str, int] = {}
    turnlog.STORE.clear()
    from . import learn
    learn.forget_cached()
    for d in targets(level)[level]:
        cleared[str(d)] = _rm_tree_contents(d)
    if level == "all":
        from . import video
        try:
            video.cache().clear()
        except Exception:   # noqa: BLE001 (best effort; the folder was emptied above)
            pass
        cleared["assets"] = len(reset_downloaded_assets())
    return {"level": level, "cleared": cleared, "memory": clear_memory()}


def _same_origin(req: Request) -> bool:
    o = req.headers.get("origin") or ""
    if not o:
        return False
    u = urlparse(o)
    if u.netloc and u.netloc == req.headers.get("host", ""):
        return True
    allowed = {x.strip().rstrip("/") for x in settings.cors_origins.split(",") if x.strip()}
    return o.rstrip("/") in allowed


@router.post("/api/reset")
def api_reset(req: Request, level: str = "start"):
    if req.headers.get("x-outpost-reset") != "1" or not _same_origin(req):
        raise HTTPException(403, "reset is only accepted from the app itself")
    if level not in LEVELS:
        raise HTTPException(400, "level must be start or all")
    out = reset(level)
    now = time.monotonic()
    for t, (at, _) in list(_tokens.items()):
        if now - at > TOKEN_TTL_S:
            _tokens.pop(t, None)
    tok = secrets.token_urlsafe(18)
    _tokens[tok] = (now, level)
    return {**out, "token": tok}


@router.get("/api/reset/confirm")
def api_reset_confirm(token: str = ""):
    """The desktop shell: was this reset really asked for by the app, just now? One use per token."""
    at, level = _tokens.pop(token, (0.0, ""))
    if not level or time.monotonic() - at > TOKEN_TTL_S:
        raise HTTPException(404, "no such reset")
    return {"level": level}
