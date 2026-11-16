"""Settings -> Help & diagnostics (issue #92, docs/DIAGNOSTICS.md): the diagnostics file, and the backend's own metrics
hooks (HTTP errors, mission saves / loads).

  GET  /api/metrics               this process's counters and latency histograms (app/diag.py; token-protected)
  GET  /api/diagnostics/contents  what a diagnostics file holds, in plain words (the page lists it before saving)
  POST /api/diagnostics/bundle    the zip itself, as the response body. Body: what the desktop shell knows (app, OS,
                                  hardware, engine.json minus the token, its own metrics). The shell asks the user
                                  where to save it (a save dialog) and writes it there; nothing is ever uploaded.

What goes in is a fixed list (CONTENTS), every JSON passed through diag.scrub() again (the logs were scrubbed when they
were written; this is the second net) and every log line re-parsed: a line that is not one of our JSON objects is
dropped. Never in it: audio, transcripts or the turn log, the token, the human-readable *.log files (third-party output
we do not control). tests/test_diagnostics.py checks the zip against all of that.
"""
from __future__ import annotations

import io
import json
import os
import platform
import sys
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from . import diag

router = APIRouter()

LOG_FILES_MAX = 8                 # the newest structured log files, across the three services
LOG_BYTES_MAX = 24 * 1024 * 1024  # and at most this much of them (uncompressed)
FORBIDDEN_SUFFIXES = (".wav", ".pcm", ".s16le", ".webm", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".log")
CONTENTS = [   # (name or folder/, what it is: the page shows these lines)
    ("README.txt", "A short note about this file"),
    ("system.json", "App, system and hardware details"),
    ("versions.json", "App and model versions, and the model file checks"),
    ("engine.json", "Where the engine runs (without its key)"),
    ("health/", "Health checks from both servers"),
    ("metrics/", "Speed, error and crash counts (last 30 days)"),
    ("logs/", "Recent technical logs"),
]
README = """Outpost Luna diagnostics file
=============================

You saved this from Settings > Help & diagnostics. Nothing was uploaded: send it only if you choose to.

Inside: app, system and hardware details; app and model versions; health checks; speed, error and crash counts
(last 30 days); recent technical logs.

Never inside: audio, what was said or typed, names, the turn log, or the app's key.

What each part means: docs/DIAGNOSTICS.md in the Outpost Luna repository.
"""


# ------------------------------------------------------------------------------------------------------- the hooks
class ErrorCounter:
    """ASGI middleware: every 5xx response and unhandled exception counted by code and logged (path only, no query)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def watch(msg):
            if msg["type"] == "http.response.start" and msg.get("status", 200) >= 500:
                diag.METRICS.error(f"http_{msg['status']}")
                diag.LOG.error("http_error", status=msg["status"], method=scope.get("method"), path=_route(scope))
            await send(msg)
        try:
            await self.app(scope, receive, watch)
        except Exception as e:
            diag.METRICS.error(f"unhandled_{type(e).__name__}")
            diag.LOG.error("unhandled", exc=type(e).__name__, method=scope.get("method"), path=_route(scope))
            raise


def _route(scope) -> str:
    p = scope.get("path", "")
    return p if len(p) < 120 else p[:120]


def install_mission_hooks() -> bool:
    """Mission saves / loads / failures, counted around app/mission/registry.py's own functions (no change to them):
    a save is an _autosave call that wrote mission.json (a new file: inode / mtime / size moved); one that should have and did not is a
    failure. A load is resume(): a mission back, or None while a save file was there (a failure)."""
    try:
        from .mission import registry
    except Exception:  # noqa: BLE001
        return False
    if getattr(registry, "_diag_hooked", False):
        return True
    save, resume = getattr(registry, "_autosave", None), getattr(registry, "resume", None)
    if save is None or resume is None or not hasattr(registry, "save_dir"):
        return False

    def mtime() -> tuple | None:   # the save is written to a temp file and renamed: a new inode every time
        try:
            st = (registry.save_dir() / "mission.json").stat()
            return st.st_ino, st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def autosave(m, *a, **kw):
        before_key, before = (getattr(m, "gp", {}) or {}).get("saved_key"), mtime()
        out = save(m, *a, **kw)
        gp = getattr(m, "gp", {}) or {}
        if gp.get("nosave") or gp.get("saved_key") == before_key:
            return out           # nothing to save (no change, or a practice run)
        after = mtime()
        if after is not None and after != before:
            diag.METRICS.inc("mission_saves")
        else:
            diag.METRICS.inc("mission_save_failures")
            diag.METRICS.error("mission_save_failed")
            diag.LOG.error("mission_save_failed")
        return out

    def resumed(*a, **kw):
        had = mtime() is not None
        m = resume(*a, **kw)
        if m is not None:
            diag.METRICS.inc("mission_loads")
            diag.LOG.event("mission_load", ok=True)
        elif had:
            diag.METRICS.inc("mission_load_failures")
            diag.METRICS.error("mission_load_failed")
            diag.LOG.error("mission_load_failed")
        return m

    registry._autosave, registry.resume, registry._diag_hooked = autosave, resumed, True
    return True


# -------------------------------------------------------------------------------------------------------- the bundle
def _json(v) -> bytes:
    return (json.dumps(diag.scrub(v, limit=2000), indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def _log_dir() -> Path | None:
    d = os.environ.get("LUNA_LOG_DIR")
    return Path(d) if d else None


def log_files(log_dir: Path | None = None) -> list[Path]:
    """The newest structured logs (<svc>.jsonl, <svc>.jsonl.N), at most LOG_FILES_MAX files / LOG_BYTES_MAX bytes."""
    d = log_dir if log_dir is not None else _log_dir()
    if d is None or not d.is_dir():
        return []
    fs = [p for p in d.iterdir() if p.is_file() and (p.name.endswith(".jsonl") or ".jsonl." in p.name)
          and not p.name.lower().endswith(FORBIDDEN_SUFFIXES)]
    out, total = [], 0
    for p in sorted(fs, key=lambda p: p.stat().st_mtime, reverse=True)[:LOG_FILES_MAX]:
        total += p.stat().st_size
        if total > LOG_BYTES_MAX and out:
            break
        out.append(p)
    return out


def clean_log(raw: bytes) -> bytes:
    """A structured log, line by line: only JSON objects with an `event`, scrubbed again. Anything else is dropped."""
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and "event" in d:
            out.append(json.dumps(diag.scrub(d), ensure_ascii=False, separators=(",", ":")))
    return ("\n".join(out) + ("\n" if out else "")).encode("utf-8")


def daily_files(base: Path | None = None) -> list[Path]:
    base = base if base is not None else diag.data_dir()
    d = base / "metrics" if base else None
    return sorted(d.glob("daily-*.json")) if d and d.is_dir() else []


def versions(shell: dict, models_health: dict) -> dict:
    """App, ABI, ONNX Runtime, model ids and their sha256 checks, out of the model server's /health."""
    m = (models_health or {}).get("models") or {}
    ear = m.get("arc_ear") or {}
    eng = ear.get("engine") if isinstance(ear.get("engine"), dict) else {}
    keep = ("model", "revision", "version", "loaded", "available", "enabled", "error", "backend", "engine", "voice",
            "verified", "verify", "domains", "pool_size", "dim", "ort_wheel")
    return {"app": ((shell or {}).get("app") or {}).get("version"), "backend_api": _app_version(),
            "python": sys.version.split()[0], "abi": (eng or {}).get("abi"), "ort": (eng or {}).get("ort"),
            "ort_wheel": ear.get("ort_wheel"),
            "models": {k: {f: v.get(f) for f in keep if f in v} for k, v in m.items() if isinstance(v, dict)}}


def _app_version() -> str | None:
    try:
        from .main import app
        return app.version
    except Exception:  # noqa: BLE001
        return None


async def _models(path: str) -> dict:
    """The model server's /health or /metrics (with the token); {"error"} when it does not answer."""
    import httpx

    from .config import settings
    from .local_guard import auth_headers
    try:
        async with httpx.AsyncClient(base_url=settings.model_server_url, timeout=3.0, headers=auth_headers()) as c:
            r = await c.get(path)
            return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"model server did not answer: {type(e).__name__}"}


async def _backend_health() -> dict:
    try:
        from .main import health
        return await health()
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}


def contents(log_dir: Path | None = None) -> dict:
    """What a diagnostics file holds right now (the page shows it before saving)."""
    logs = log_files(log_dir)
    items = [{"name": n, "what": w + (f" ({len(logs)} files)" if n == "logs/" else "")} for n, w in CONTENTS
             if n != "logs/" or logs]
    return {"items": items, "never": "No audio, no words, no names, no keys.", "uploaded": False}


async def build(shell: dict | None = None, *, log_dir: Path | None = None, data_dir: Path | None = None,
                models_health: dict | None = None, models_metrics: dict | None = None,
                backend_health: dict | None = None) -> tuple[bytes, list[str]]:
    """The zip (bytes) and its file names. `shell`: the desktop shell's part ({app, os, hardware, engine,
    main_metrics}); everything in it is scrubbed, and engine.json never carries the token."""
    shell = shell if isinstance(shell, dict) else {}
    mh = models_health if models_health is not None else await _models("/health")
    mm = models_metrics if models_metrics is not None else await _models("/metrics")
    bh = backend_health if backend_health is not None else await _backend_health()
    engine = {k: v for k, v in (shell.get("engine") or {}).items() if not diag.sensitive_key(k)} \
        if isinstance(shell.get("engine"), dict) else {"note": "not running in the desktop app"}
    files: dict[str, bytes] = {
        "README.txt": README.encode("utf-8"),
        "system.json": _json({"saved_at": diag._iso(time.time()), "app": shell.get("app"), "os": shell.get("os"),
                              "hardware": shell.get("hardware"),
                              "backend": {"python": sys.version.split()[0], "platform": platform.platform(),
                                          "machine": platform.machine(), "pid": os.getpid()}}),
        "versions.json": _json(versions(shell, mh)),
        "engine.json": _json(engine),
        "health/backend.json": _json(bh),
        "health/model_server.json": _json(mh),
        "metrics/backend.json": _json(diag.METRICS.snapshot()),
        "metrics/model_server.json": _json(mm),
    }
    if shell.get("main_metrics"):
        files["metrics/main.json"] = _json(shell["main_metrics"])
    for p in daily_files(data_dir):
        try:
            files[f"metrics/{p.name}"] = _json(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    for p in log_files(log_dir):
        try:
            files[f"logs/{p.name}"] = clean_log(p.read_bytes())
        except OSError:
            pass
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            assert not name.lower().endswith(FORBIDDEN_SUFFIXES), name
            z.writestr(name, body)
    return buf.getvalue(), list(files)


# ------------------------------------------------------------------------------------------------------- the routes
def _check(request: Request) -> None:
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")


@router.get("/api/diagnostics/contents")
def diagnostics_contents(request: Request):
    _check(request)
    return contents()


@router.post("/api/diagnostics/bundle")
async def diagnostics_bundle(request: Request):
    _check(request)
    try:
        shell = await request.json()
    except Exception:  # noqa: BLE001 (no body: the page in a browser)
        shell = {}
    body, names = await build(shell if isinstance(shell, dict) else {})
    diag.METRICS.inc("diagnostics_saved")
    diag.LOG.event("diagnostics_bundle", files=len(names), bytes=len(body))
    stamp = time.strftime("%Y-%m-%d")
    return Response(body, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="outpost-luna-diagnostics-{stamp}.zip"'})
