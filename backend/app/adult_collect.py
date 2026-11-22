"""Settings -> For grown-ups -> "Help improve Outpost Luna": an ADULT tester's opt-in real-turn log (docs/ADULT_SESSIONS.md).

The learned Director needs real, labelled turns (docs/DIRECTOR_LOOP.md). Early users are adults, so an adult can opt in,
behind the grown-up gate, to keep their own turns with everything a labeller needs later:

  * OFF by default. Turning it on needs the page's own header, `consent: true` and `adult: true` (the consent screen);
    the frontend section is drawn only inside For grown-ups (after the 3-second hold / teacher PIN).
  * It is tied to the cadet profile that turned it on (`profile`, "p1".."p6"): a kid's profile on the same computer is
    never collected, and its turns never get audio from this switch.
  * While on, every turn of that profile is written to the turn log (turnlog.py) even if "Help improve the voice guide"
    is off, tagged `"collect": true`, with the extra label fields (`reply`: what the app said and did) and the outcome
    signals (repeat, negate, misheard, barge, nav_back, undo ...).
  * Audio is a SEPARATE switch (`audio`, off by default): each heard turn's clip, like a Playtest (playtest.py).
  * It switches itself off MAX_S (4 hours) after it was turned on, or when the app quits, whichever comes first
    (like the Playtest). The stored opt-in carries this process's random `boot` tag, so a new backend process (the
    app started again) reads it as off. The settings row shows "On until HH:MM" (`until`, epoch seconds). Collected
    turns stay until exported or deleted (and the turn log's own 30-day retention).
  * Nothing is sent. "Export to share" writes ONE zip with only the collected lines (redacted again on the way out),
    their signals and clips, where the adult chooses. "Delete everything" removes the collected lines and clips.

State: <turnlog dir>/collect.json {"on", "audio", "profile", "day", "consent_v", "until", "boot"}. No name, no device
id.

  GET  /api/collect            {on, audio, profile, until, max_s, turns, clips, clip_bytes}
  POST /api/collect            {"on": bool, "audio": bool, "consent": true, "adult": true, "profile": "p1"}
                               + the page's X-Outpost-Reset header (turning on needs consent + adult; off never does)
                               {"audio_only": true, "audio": bool, "profile": "p1"}: the audio switch, only while it
                               is on for that profile (else 409: never re-enables collection without the consent)
  POST /api/collect/export     the zip, as the response body ({"app_version"} in the body; + the page's header)
  POST /api/collect/delete     deletes the collected lines and their clips (+ the page's header)
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import secrets
import threading
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

FORMAT = "outpost-luna-collect"
FORMAT_VERSION = 1
CONSENT_V = 1                       # bump when the consent text changes (a stored opt-in under an older text is off)
MAX_S = 4 * 3600.0                  # switches itself off this long after it was turned on
BOOT = secrets.token_hex(6)          # this backend process: an opt-in from an earlier run of the app is off
_PID = re.compile(r"^p[1-6]$")
_lock = threading.Lock()
_cache: dict = {"path": None, "mtime": None, "st": None}
# audio_any() runs per mic frame (playtest.Recorder.feed): no syscall there. state() and _save() keep this in memory:
# (the opt-in file's path, BOOT) and until when audio is on (None: off). Only this process writes the file.
_fast: dict = {"key": None, "audio_until": None}
# collected(): the turn log scan, memoised on the log files' (name, size, mtime) (every append changes the size)
_scan: dict = {"key": None, "val": None}

router = APIRouter()


def _path() -> Path:
    from . import turnlog
    return turnlog.log_dir() / "collect.json"


def _now() -> float:
    return time.time()


_OFF = {"on": False, "audio": False, "profile": None, "day": None, "until": None}


def state() -> dict:
    """The stored opt-in: off when missing, unreadable, given under an older consent text, turned on by an earlier run
    of the app (another `boot`), or past its `until` (MAX_S after it was turned on)."""
    p = _path()
    try:
        mt = p.stat().st_mtime_ns
    except OSError:
        _fast.update(key=(str(p), BOOT), audio_until=None)
        return dict(_OFF)
    if _cache["path"] == str(p) and _cache["mtime"] == mt and _cache["st"] is not None and _cache.get("boot") == BOOT:
        out = dict(_cache["st"])
    else:
        try:
            st = json.loads(p.read_text())
        except (OSError, ValueError):
            st = {}
        ok = isinstance(st, dict) and st.get("consent_v") == CONSENT_V and st.get("on") is True and \
            st.get("boot") == BOOT and isinstance(st.get("until"), (int, float))
        out = {"on": bool(ok), "audio": bool(ok and st.get("audio") is True),
               "profile": st.get("profile") if ok and _PID.match(str(st.get("profile") or "")) else None,
               "day": st.get("day") if ok else None, "until": float(st["until"]) if ok else None}
        _cache.update(path=str(p), mtime=mt, st=out, boot=BOOT)
    _fast.update(key=(str(p), BOOT), audio_until=out["until"] if out["on"] and out["audio"] else None)
    if out["on"] and _now() >= out["until"]:
        return dict(_OFF)
    return out


def _save(st: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("collect.json.tmp")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, p)
    _cache.update(path=None, mtime=None, st=None)
    _fast.update(key=None, audio_until=None)


def on_for(profile: str | None) -> bool:
    """Collect this session's turns: on, and the session's profile is the one that turned it on."""
    st = state()
    return st["on"] and st["profile"] is not None and profile == st["profile"]


def audio_for(profile: str | None) -> bool:
    st = state()
    return on_for(profile) and st["audio"]


def audio_any() -> bool:
    """The mic relay keeps its ring buffer (playtest.Recorder) while some profile collects audio. Whose turn it is
    decides whether a clip is ever written (turnlog.SessionLog.finish -> audio_for). Called per mic frame: answered
    from memory (state() / set_state keep it; the 4-hour expiry is a clock check), the file is read only once."""
    if _fast["key"] != (str(_path()), BOOT):
        state()
    u = _fast["audio_until"]
    return u is not None and _now() < u


class NotOn(ValueError):
    """An audio-only change while collection is off for that profile (expired, quit, another profile)."""


def set_state(on: bool, audio: bool = False, consent: bool = False, adult: bool = False,
              profile: str | None = None, audio_only: bool = False) -> dict:
    """Turn it on (needs consent + adult + a profile id) or off. Audio only rides along with on.
    `audio_only`: the audio switch of a collection that is ON for this profile: it never turns collection on (after
    the 4 hours, or a restart, the adult has to read the consent again) and keeps the clock."""
    with _lock:
        if audio_only:
            cur = state()
            if not (cur["on"] and cur["profile"] is not None and cur["profile"] == profile):
                raise NotOn("it is off now: turn it on again first")
            _save({"on": True, "audio": bool(audio), "profile": profile, "consent_v": CONSENT_V,
                   "day": cur.get("day") or _dt.date.today().isoformat(), "until": round(cur["until"], 1),
                   "boot": BOOT})
            return status()
        if not on:
            cur = state()
            _save({"on": False, "audio": False, "profile": cur.get("profile"), "consent_v": CONSENT_V})
            return status()
        if consent is not True or adult is not True:
            raise ValueError("an adult has to read and accept the consent text first")
        if not _PID.match(str(profile or "")):
            raise ValueError("which profile is collecting?")
        cur = state()
        # changing the audio switch keeps the clock; turning on (again) starts MAX_S from now
        until = cur["until"] if cur["on"] and cur["profile"] == profile else _now() + MAX_S
        _save({"on": True, "audio": bool(audio), "profile": profile, "consent_v": CONSENT_V,
               "day": _dt.date.today().isoformat(), "until": round(until, 1), "boot": BOOT})
    return status()


# ------------------------------------------------------------------------------------------- the collected lines
def _is_collected(r: dict) -> bool:
    return r.get("k") == "turn" and r.get("collect") is True


def collected(files: list[Path] | None = None) -> tuple[list[dict], list[dict]]:
    """-> (collected turn lines, their signal lines), from the turn log files (the live one and the rotated one).
    Memoised on the files' sizes and mtimes; callers never mutate the lists."""
    from . import turnlog
    fs = files if files is not None else turnlog.STORE.files()
    key = []
    for f in fs:
        try:
            st = f.stat()
            key.append((str(f), st.st_size, st.st_mtime_ns))
        except OSError:
            key.append((str(f), None, None))
    key = tuple(key)
    if _scan["key"] == key and _scan["val"] is not None:
        return _scan["val"]
    turns, sigs = [], []
    for f in fs:
        try:
            fh = open(f, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"collect":true' not in line and '"k":"signal"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if _is_collected(r):
                    turns.append(r)
                elif isinstance(r, dict) and r.get("k") == "signal":
                    sigs.append(r)
    ids = {t["id"] for t in turns}
    val = (turns, [s for s in sigs if s.get("ref") in ids])
    _scan.update(key=key, val=val)
    return val


_CLIP = re.compile(r"^playtest/[0-9a-f]{8}-\d{1,6}\.wav$")


def clips_of(turns: list[dict]) -> list[str]:
    """The clip names ("playtest/<turn id>.wav") the collected lines point at."""
    return [w for w in (t.get("wav") for t in turns) if isinstance(w, str) and _CLIP.match(w)]


def clip_bytes() -> int:
    """The bytes of the collected turns' clips (kept out of the Playtest's own CAP_BYTES, playtest.save_clip)."""
    from . import turnlog
    d = turnlog.STORE.path.parent
    n = 0
    for c in clips_of(collected()[0]):
        try:
            n += (d / c).stat().st_size
        except OSError:
            pass
    return n


def status() -> dict:
    st = state()
    turns, _ = collected()
    clips = [t["wav"] for t in turns if t.get("wav")]
    from . import turnlog
    d = turnlog.STORE.path.parent
    cb = sum((d / c).stat().st_size for c in clips if (d / c).exists())
    return {"on": st["on"], "audio": st["audio"], "profile": st["profile"], "until": st.get("until"), "max_s": MAX_S,
            "turns": len(turns), "clips": len(clips), "clip_bytes": cb, "since": st.get("day")}


_TAG = re.compile(r"<[a-z]+>")


def scrub(r: dict, names: tuple = ()) -> dict:
    """Redact a collected line again on the way out (an older line, or a call sign the client never sent): the words
    between the tags go through turnlog.redact; the reply lines through turnlog.redact_line. Private turns keep no
    words. Keys outside the turn log's own schema never leave."""
    from . import turnlog
    r = dict(r)
    if r.get("guard"):
        r["text"] = "<private>"
        r.pop("wav", None)
        r.pop("reply", None)
    elif isinstance(r.get("text"), str):
        parts = _TAG.split(r["text"])
        tags = _TAG.findall(r["text"])
        out = []
        for i, p in enumerate(parts):
            if p.strip():
                out.append(turnlog.redact(p, names))
            if i < len(tags):
                out.append(tags[i])
        r["text"] = re.sub(r"\s+", " ", " ".join(out)).strip()
    rep = r.get("reply")
    if isinstance(rep, dict) and isinstance(rep.get("say"), list):
        r["reply"] = {**rep, "say": [turnlog.redact_line(s, names) for s in rep["say"] if isinstance(s, str)][:4]}
    return {k: v for k, v in r.items() if not k.startswith("_")}


README = """Outpost Luna: Help improve Outpost Luna (adult tester export)

turns.jsonl         one line per turn the app heard while "Help improve Outpost Luna" was on (redacted words, the ear's
                    numbers, the screen, what the app decided and said) and the signals after it (repeated, corrected,
                    barged in, went back). No names, no call signs, no clock times.
audio/<turn>.wav    only if you turned on "Also keep audio clips": that turn's audio (16 kHz mono).
manifest.json       app version, date, counts, the consent version.

Outpost Luna never uploads it. You chose where to save it, and you choose whether to share it.
Developers: make director-import LOG=<this zip>, then python3 director_model/label_ui/serve.py --log <this zip>
"""


def export_zip(app_version: str | None = None) -> tuple[bytes, dict]:
    """ONLY the collected lines (scrubbed), their signals and clips, a manifest and a README. -> (bytes, manifest)."""
    from . import playtest, turnlog
    turns, sigs = collected()
    d = turnlog.STORE.path.parent
    clips = [w for w in clips_of(turns) if (d / w).exists()]
    man = {"format": FORMAT, "format_version": FORMAT_VERSION, "app_version": app_version or playtest._app_version(),
           "turnlog_version": turnlog.VERSION, "day": _dt.date.today().isoformat(), "turns": len(turns),
           "signals": len(sigs), "clips": len(clips), "sessions": len({t.get("s") for t in turns} - {None}),
           "sample_rate": playtest.SR, "speaker": "adult", "consent_v": CONSENT_V,
           "consent": "an adult accepted the Help improve Outpost Luna text in Settings before anything was kept"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(man, indent=1) + "\n")
        z.writestr("README.txt", README)
        z.writestr("turns.jsonl", "".join(json.dumps(scrub(x), separators=(",", ":")) + "\n" for x in turns + sigs))
        for c in clips:        # the importer reads playtest/<id>.wav (import_logs.ZIP_WAV): the same member names
            z.write(d / c, c, compress_type=zipfile.ZIP_STORED)
    return buf.getvalue(), man


def delete_all() -> dict:
    """"Delete everything": the collected lines, their signals and clips. The rest of the turn log stays. All of it
    under the turn log's lock (a turn appended or a file rotated meanwhile can't slip between the read and the
    rewrite), over both files (the live one and the rotated turns.1.jsonl)."""
    from . import turnlog
    d = turnlog.STORE.path.parent
    n = n_clips = 0
    with turnlog.STORE.lock:
        files = turnlog.STORE.files()
        turns, _ = collected(files)
        ids = {t["id"] for t in turns}
        wavs = clips_of(turns)
        for f in files:
            keep = []
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        keep.append(line)
                        continue
                    if isinstance(r, dict) and (_is_collected(r) or (r.get("k") == "signal" and r.get("ref") in ids)):
                        n += 1
                        continue
                    keep.append(line)
            if keep:
                tmp = f.with_name(f.name + ".tmp")
                tmp.write_text("".join(keep), encoding="utf-8")
                os.replace(tmp, f)
            else:
                f.unlink(missing_ok=True)
        for w in wavs:
            try:
                (d / w).unlink()
                n_clips += 1
            except OSError:
                pass
    _scan.update(key=None, val=None)
    return {"deleted_lines": n, "deleted_clips": n_clips, **status()}


# ------------------------------------------------------------------------------------------------------- the routes
def _check(request: Request) -> None:
    from . import diag
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")


def _page(request: Request) -> None:
    if request.headers.get("x-outpost-reset") != "1":    # the page's own header (a cross-site page can't send it)
        raise HTTPException(400, "missing X-Outpost-Reset")


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:  # noqa: BLE001
        b = {}
    return b if isinstance(b, dict) else {}


@router.get("/api/collect")
def collect_status(request: Request):
    _check(request)
    return status()


@router.post("/api/collect")
async def collect_set(request: Request):
    _check(request)
    _page(request)
    b = await _body(request)
    try:
        return set_state(b.get("on") is True, audio=b.get("audio") is True, consent=b.get("consent") is True,
                         adult=b.get("adult") is True, profile=b.get("profile"), audio_only=b.get("audio_only") is True)
    except NotOn as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/collect/export")
async def collect_export(request: Request):
    _check(request)
    _page(request)
    b = await _body(request)
    v = b.get("app_version")
    body, man = export_zip(str(v)[:32] if v else None)
    return Response(body, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="outpost-luna-help-{man["day"]}.zip"'})


@router.post("/api/collect/delete")
def collect_delete(request: Request):
    _check(request)
    _page(request)
    return delete_all()
