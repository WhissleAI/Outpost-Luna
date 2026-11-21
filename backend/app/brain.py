"""The Brain's grown-up numbers (docs/BRAIN.md §4, "Signals → Brain"): counts only, read from what the app already keeps
on this computer.

  GET /api/brain/summary?profile=p1&course=moon&days=30&sensitive=0

    talk     from the turn log (app/turnlog.py), for THIS cadet profile (and course, when given): turns, by voice / by
             typing, how many the app answered vs. let pass (not meant for it), the days with a turn, the room-state
             labels, and the outcome signals (hint / pass / repeat / negate / undo / retap / confirm_cancel), all inside
             the date window (signal lines carry their own day since feat/brain-signals; an older signal with no day is
             not counted). `retried` = how often the app had to try again (repeat + negate + undo + retap): the app's
             outcome, never a trait of the cadet. A turn written before profiles were logged belongs to no profile.
    safety   turns the privacy guard kept private, by category (pii / name always; language / unkind only with
             sensitive=1, the grown-up's "Show language and kindness counts" toggle, collapsed per ISO week), and the
             care entries from the safety ledger (app/safety_ledger.py) for this profile. Never the words.
    adapted  this cadet's on-device learning (app/learn): how many names it learned, the end-of-turn wait, the turns.
    log      whether the turn log holds anything and how big it is, and its retention.
    shadow   (in talk) P2 metrics logged but not shown (interruptions: turns the ear marked as a barge-in). Never rendered.

Every behaviour count (signals, guard categories, interruptions) skips echo turns (the router's echo reason, or a heard
turn mostly made of what the app just said) and heard turns Arc marked as not meant for the app (device_directed < 0.5).

No text ever leaves this function: the turn log's `text` field is not read. Loopback only (the LocalGuard middleware on
every route, app/main.py) and the local token, like GET /api/learn (diag.authorized).
"""
from __future__ import annotations

import datetime as _dt
import json
import re

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

VOICE_SRC = ("listen", "voice", "ptt")
ROOM_STATES = ("calm", "busy", "loud")
SIGNALS = ("hint", "pass", "repeat", "negate", "undo", "retap", "confirm_cancel")
RETRY_SIGNALS = ("repeat", "negate", "undo", "retap")      # the app had to try again
GUARD_ALWAYS = ("pii", "name")
GUARD_SENSITIVE = ("language", "unkind")                  # off unless a grown-up turns them on
MAX_DAYS = 365
MIN_N = 10                # no rate is shown on fewer turns than this (brain.js reads `min_n`)
DD_LOW = 0.5              # turn_router.DD_MIN
ECHO_SHARE = 0.6          # turnlog.REPEAT_SHARE: a heard turn mostly made of what the app just said
_COURSE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")


def _week(day: str) -> str:
    try:
        y, w, _ = _dt.date.fromisoformat(day[:10]).isocalendar()
        return f"{y}-W{w:02d}"
    except ValueError:
        return "?"


def _behaviour_ok(r: dict) -> bool:
    """A turn that may count toward a behaviour metric: not an echo, not low device-directed."""
    rt = r.get("router") if isinstance(r.get("router"), dict) else {}
    if rt.get("reason") == "echo":
        return False
    au = r.get("audio") if isinstance(r.get("audio"), dict) else {}
    es = au.get("echo_share")
    if isinstance(es, (int, float)) and es >= ECHO_SHARE and r.get("src") in VOICE_SRC:
        return False
    arc = r.get("arc") if isinstance(r.get("arc"), dict) else {}
    dd = arc.get("dd")
    return not (r.get("src") in ("listen", "voice") and isinstance(dd, (int, float)) and dd < DD_LOW)


def talk_counts(lines, since: str | None = None, profile: str | None = None, course: str | None = None,
                sensitive: bool = False) -> dict:
    """Aggregate turn-log lines (JSON strings or dicts) into counts. Pure; never reads `text`.
    profile / course: only lines that carry that profile / course. since: only lines on or after that day (a line with
    no day is skipped when a window is set)."""
    out = {"turns": 0, "voice": 0, "typed": 0, "answered": 0, "passed_by": 0, "guarded": 0,
           "days": 0, "room": {k: 0 for k in ROOM_STATES}, "signals": {k: 0 for k in SIGNALS}, "retried": 0,
           "guard": {k: 0 for k in GUARD_ALWAYS}, "min_n": MIN_N, "shadow": {"interruptions": 0}}
    if sensitive:
        out["guard"].update({k: 0 for k in GUARD_SENSITIVE})
        out["weekly"] = {}
    days = set()
    skip: set = set()        # turn ids that may not count toward behaviour (echo / not meant for the app)
    for ln in lines:
        try:
            r = json.loads(ln) if isinstance(ln, str) else ln
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        k = r.get("k")
        if k not in ("turn", "signal"):
            continue
        day = r.get("day") if isinstance(r.get("day"), str) else None
        if since and (not day or day < since):
            continue
        if profile and r.get("profile") != profile:
            continue
        if course and r.get("course") != course:
            continue
        if k == "signal":
            if r.get("sig") in SIGNALS and r.get("ref") not in skip:
                out["signals"][r["sig"]] += 1
                if r["sig"] in RETRY_SIGNALS:
                    out["retried"] += 1
            continue
        ok = _behaviour_ok(r)
        if not ok and isinstance(r.get("id"), str):
            skip.add(r["id"])
        out["turns"] += 1
        if day:
            days.add(day[:10])
        if r.get("src") in VOICE_SRC:
            out["voice"] += 1
        else:
            out["typed"] += 1
        oc = (r.get("router") or {}).get("outcome") if isinstance(r.get("router"), dict) else None
        if oc == "ignore":
            out["passed_by"] += 1
        elif oc:
            out["answered"] += 1
        if r.get("guard") is True:
            out["guarded"] += 1
            gk = r.get("guard_kind")
            if gk in out["guard"] and (gk in GUARD_ALWAYS or ok):
                out["guard"][gk] += 1
                if gk in GUARD_SENSITIVE and day:
                    w = out["weekly"].setdefault(_week(day), {"language": 0, "unkind": 0})
                    w[gk] += 1
        rm = r.get("room") if isinstance(r.get("room"), dict) else {}
        st = rm.get("state")
        if st in ROOM_STATES:
            out["room"][st] += 1
        ear = r.get("ear") if isinstance(r.get("ear"), dict) else {}
        if ok and ear.get("barge") is True:
            out["shadow"]["interruptions"] += 1
    out["days"] = len(days)
    return out


def _turn_lines():
    from . import turnlog
    for f in turnlog.STORE.files():
        try:
            with open(f, encoding="utf-8") as fh:
                yield from fh
        except OSError:
            continue


def adapted_view(profile: str | None) -> dict:
    """This cadet's on-device learning as counts (no heard forms, no names)."""
    try:
        from .learn import for_profile
        v = for_profile(profile).describe(include_aliases=False)
    except Exception:  # noqa: BLE001  (learning never breaks the summary)
        return {"names": 0, "wait_s": 0.5, "turns": 0, "waits_longer": False}
    h = v.get("habits") or {}
    wait = float(h.get("end_silence_s") or 0.5)
    return {"names": len(v.get("aliases") or []), "wait_s": round(wait, 1), "turns": int(h.get("turns") or 0),
            "waits_longer": wait > 0.5}


def care_flags(profile: str | None = None) -> int:
    """Care entries in the safety ledger (kept 30 days) for this profile: how many times the guide suggested a break."""
    try:
        from .safety_ledger import LEDGER
        return sum(r["n"] for r in LEDGER.care(profile))
    except Exception:  # noqa: BLE001
        return 0


@router.get("/api/brain/summary")
def brain_summary(request: Request, profile: str | None = None, course: str | None = None, days: int = 30,
                  sensitive: int = 0):
    from . import diag, turnlog
    from .learn.store import profile_id
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")
    days = max(1, min(MAX_DAYS, int(days or 30)))
    since = (_dt.date.today() - _dt.timedelta(days=days - 1)).isoformat()
    pid = profile_id(profile)
    crs = course if isinstance(course, str) and _COURSE.match(course) else None
    talk = talk_counts(_turn_lines(), since, pid, crs, sensitive=bool(sensitive))
    st = turnlog.STORE.stats()
    safety = {"guarded": talk.pop("guarded"), "guard": talk.pop("guard"), "care": care_flags(pid)}
    if sensitive:
        safety["weekly"] = talk.pop("weekly", {})
    return {"days": days, "profile": pid, "course": crs, "talk": talk, "safety": safety,
            "adapted": adapted_view(pid),
            "log": {"turns": st.get("turns", 0), "bytes": st.get("bytes", 0), "retain_days": turnlog.RETAIN_DAYS},
            "stored": "on this computer only", "words": False}
