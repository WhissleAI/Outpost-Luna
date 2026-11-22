"""A grown-up's Playtest session (docs/DIRECTOR_LOOP.md §1b): the turn log plus each kid turn's audio, on this computer.

Settings -> For grown-ups -> Playtest session. A grown-up confirms they have permission (the consent screen), then:
  * the turn log runs even if "Help improve the voice guide" was turned off (turnlog.SessionLog.on);
  * the mic relay (/ws/listen) keeps the last RING_S of the mic audio it already receives for the ear, in memory, and
    at each heard turn's end cuts that turn (PRE_S before the ear's turn start, to its end) for the session;
  * the turn log writes it as <turnlog dir>/playtest/<turn id>.wav (16 kHz mono PCM16) and names the file in the
    turn's `wav` field. The text log never holds audio;
  * "Export playtest" writes ONE zip (turn log + audio + app version + manifest.json) where the grown-up chooses
    (desktop: a save dialog in desktop/main; browser: a download). Nothing is ever uploaded.
It is off again when the grown-up stops it, after MAX_S, and when the app quits (state lives in this process only).
"Delete what's saved" (turnlog.Store.clear) deletes the audio with the text.

  GET  /api/playtest           {on, since_s, max_s, turns, clips, clip_bytes, cap_bytes}
  POST /api/playtest/start     {"consent": true} + the page's X-Outpost-Reset header -> starts (else 400)
  POST /api/playtest/stop
  POST /api/playtest/export    the zip, as the response body ({"app_version"} in the body: the desktop shell's)
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import re
import secrets
import threading
import time
import wave
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

SR = 16000
BYTES_S = SR * 2
RING_S = 40.0                  # the mic audio kept in memory per relay (only while a playtest runs)
PRE_S = 1.0                    # the ear opens a turn ~0.3-0.8 s after the speech starts
MAX_CLIP_S = 30.0
MAX_S = 3 * 3600.0             # a forgotten playtest turns itself off
CAP_BYTES = 400_000_000        # all clips together; past it no more audio is kept (the text log goes on)
FORMAT = "outpost-luna-playtest"
FORMAT_VERSION = 1
_ID = re.compile(r"^[0-9a-f]{8}-\d{1,6}$")

router = APIRouter()
_lock = threading.Lock()
STATE: dict = {"on": False, "since": None, "tag": None, "clips": 0}


def _now() -> float:
    return time.monotonic()


def active() -> bool:
    """A playtest is running (MAX_S after its start it turns itself off)."""
    if STATE["on"] and STATE["since"] is not None and _now() - STATE["since"] > MAX_S:
        stop()
    return bool(STATE["on"])


def recording() -> bool:
    """The mic relay keeps its ring buffer: a playtest runs, or an adult's "Help improve Outpost Luna" keeps audio
    (adult_collect.py; whose turn it is still decides whether a clip is written)."""
    if active():
        return True
    try:
        from . import adult_collect
        return adult_collect.audio_any()
    except Exception:  # noqa: BLE001
        return False


def start(consent: bool) -> dict:
    if consent is not True:
        raise ValueError("a grown-up has to confirm permission first")
    with _lock:
        if not STATE["on"]:
            STATE.update(on=True, since=_now(), tag=secrets.token_hex(3), clips=0)
    return status()


def stop() -> dict:
    with _lock:
        STATE.update(on=False, since=None)
    return status()


def audio_dir() -> Path:
    from . import turnlog
    return turnlog.STORE.path.parent / "playtest"


def status() -> dict:
    from . import turnlog
    st = turnlog.STORE.stats()
    on = bool(STATE["on"])
    return {"on": on, "since_s": round(_now() - STATE["since"], 1) if on and STATE["since"] is not None else None,
            "max_s": MAX_S, "turns": st["turns"], "clips": st["clips"], "clip_bytes": st["clip_bytes"],
            "cap_bytes": CAP_BYTES, "session_clips": STATE["clips"]}


class Recorder:
    """One per /ws/listen relay: the mic audio it forwards to the ear, kept (RING_S) only while a playtest runs, and cut
    into a kid turn at the ear's turn start / end messages. Sample positions are counted in bytes received."""

    def __init__(self, ring_s: float = RING_S):
        self.cap = int(ring_s * BYTES_S)
        self.buf = bytearray()
        self.pos = 0               # total bytes received while recording (the buffer's end)
        self.start: int | None = None

    def feed(self, b: bytes, on: bool | None = None) -> None:
        if not (recording() if on is None else on):
            if self.buf:
                self.buf, self.start = bytearray(), None
            return
        self.buf += b
        self.pos += len(b)
        if len(self.buf) > self.cap:
            del self.buf[: len(self.buf) - self.cap]

    def mark(self, m: dict) -> bytes | None:
        """An ear message: a turn start marks the clip's start; a turn end returns the clip (PCM16 bytes) or None."""
        if m.get("t") != "turn" or not self.buf:
            return None
        st = m.get("state")
        if st == "start":
            self.start = max(0, self.pos - int(PRE_S * BYTES_S))
            return None
        if st != "end":
            return None
        s0 = self.start if self.start is not None else self.pos - int(5 * BYTES_S)
        self.start = None
        s0 = max(s0, self.pos - len(self.buf), self.pos - int(MAX_CLIP_S * BYTES_S))
        a = s0 - (self.pos - len(self.buf))
        clip = bytes(self.buf[a - (a % 2):])
        return clip if len(clip) >= BYTES_S // 10 else None


def wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return buf.getvalue()


def save_clip(turn_id: str, pcm: bytes | None, allow: bool = False) -> str | None:
    """Write a turn's clip next to the log -> its name relative to the log folder ("playtest/<id>.wav"), or None (no
    playtest, no audio, a bad id, or over CAP_BYTES). `allow`: an adult's collection with audio on for this turn's
    profile (adult_collect.audio_for), checked by the caller."""
    from . import turnlog
    if not pcm or not (allow or active()) or not _ID.match(turn_id or ""):
        return None
    try:
        if turnlog.STORE.stats()["clip_bytes"] + len(pcm) > CAP_BYTES:
            return None
        d = audio_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{turn_id}.wav").write_bytes(wav_bytes(pcm))
        STATE["clips"] += 1
        return f"playtest/{turn_id}.wav"
    except OSError:
        return None


README = """Outpost Luna playtest export

turns.jsonl / turns.1.jsonl   the turn log: one line per turn the voice guide heard (redacted text, the ear's numbers,
                              what the app decided) and outcome signals. No names, no call signs.
playtest/<turn id>.wav        the kid's audio for that turn (16 kHz mono), recorded only during a grown-up's
                              Playtest session, after they confirmed permission.
manifest.json                 app version, date, counts.

It was written to the place you chose. Outpost Luna never uploads it. Delete this file to delete the export.
Developers: make director-import LOG=<this zip>
"""


def export_zip(app_version: str | None = None) -> tuple[bytes, dict]:
    """The export: turn log files, the clips, a manifest and a README, as zip bytes. -> (bytes, manifest)."""
    from . import turnlog
    st = turnlog.STORE.stats()
    files = turnlog.STORE.files()
    clips = turnlog.STORE.clips()
    sessions: set = set()
    for f in files:
        for line in open(f, encoding="utf-8"):
            if '"k":"turn"' in line:
                try:
                    sessions.add(json.loads(line).get("s"))
                except ValueError:
                    pass
    man = {"format": FORMAT, "format_version": FORMAT_VERSION, "app_version": app_version or _app_version(),
           "turnlog_version": turnlog.VERSION, "day": _dt.date.today().isoformat(), "turns": st["turns"],
           "clips": len(clips), "sessions": len(sessions - {None}), "sample_rate": SR,
           "consent": "a grown-up confirmed permission in Settings before audio was kept"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(man, indent=1) + "\n")
        z.writestr("README.txt", README)
        for f in files:
            z.write(f, f.name)
        for c in clips:
            z.write(c, f"playtest/{c.name}", compress_type=zipfile.ZIP_STORED)
    return buf.getvalue(), man


def _app_version() -> str | None:
    try:
        from .main import app
        return app.version
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------------------------- the routes
def _check(request: Request) -> None:
    from . import diag
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:  # noqa: BLE001
        b = {}
    return b if isinstance(b, dict) else {}


@router.get("/api/playtest")
def playtest_status(request: Request):
    _check(request)
    active()
    return status()


@router.post("/api/playtest/start")
async def playtest_start(request: Request):
    _check(request)
    if request.headers.get("x-outpost-reset") != "1":    # the page's own header (a cross-site page can't send it)
        raise HTTPException(400, "missing X-Outpost-Reset")
    b = await _body(request)
    try:
        return start(b.get("consent") is True)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/playtest/stop")
def playtest_stop(request: Request):
    _check(request)
    return stop()


@router.post("/api/playtest/export")
async def playtest_export(request: Request):
    _check(request)
    b = await _body(request)
    v = b.get("app_version") or ((b.get("app") or {}).get("version") if isinstance(b.get("app"), dict) else None)
    body, man = export_zip(str(v)[:32] if v else None)
    return Response(body, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="outpost-luna-playtest-{man["day"]}.zip"'})
