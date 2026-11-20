"""The Brain's grown-up numbers (docs/BRAIN.md §4): counts only, read from what the app already keeps on this computer.

  GET /api/brain/summary?profile=p1&days=30

    talk     from the opt-in turn log (app/turnlog.py, every cadet on this computer): turns, by voice / by typing, how
             many the app answered vs. let pass (not meant for it), the days with a turn, the room-state labels, and
             the outcome signals (hint / pass / repeat).
    safety   turns the privacy guard or the word filter kept private (turn log `guard`), and the in-memory care flags
             (app/safety.py, Session.flags) since the app started. Never the words.
    adapted  this cadet's on-device learning (app/learn): how many names it learned (not which: the names are in
             Settings → What the app has learned), the end-of-turn wait, the turns it learned from.
    log      whether the turn log holds anything and how big it is.

No text ever leaves this function: the turn log's `text` field is not read (only its `k`, `src`, `day`, `router`,
`room`, `guard` and signal `sig` fields), no alias heard form, no call sign. Loopback only (the LocalGuard middleware
on every route, app/main.py) and the local token, like GET /api/learn (diag.authorized).
"""
from __future__ import annotations

import datetime as _dt
import json

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

VOICE_SRC = ("listen", "voice", "ptt")
ROOM_STATES = ("calm", "busy", "loud")
SIGNALS = ("hint", "pass", "repeat", "negate", "undo")
MAX_DAYS = 365


def talk_counts(lines, since: str | None = None) -> dict:
    """Aggregate turn-log lines (JSON strings or dicts) into counts. Pure; never reads `text`."""
    out = {"turns": 0, "voice": 0, "typed": 0, "answered": 0, "passed_by": 0, "guarded": 0,
           "days": 0, "room": {k: 0 for k in ROOM_STATES}, "signals": {k: 0 for k in SIGNALS}}
    days = set()
    for ln in lines:
        try:
            r = json.loads(ln) if isinstance(ln, str) else ln
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        k = r.get("k")
        if k == "signal":
            if r.get("sig") in SIGNALS:
                out["signals"][r["sig"]] += 1
            continue
        if k != "turn":
            continue
        day = r.get("day") if isinstance(r.get("day"), str) else None
        if since and day and day < since:
            continue
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
        rm = r.get("room") if isinstance(r.get("room"), dict) else {}
        st = rm.get("state")
        if st in ROOM_STATES:
            out["room"][st] += 1
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


def care_flags() -> int:
    try:
        from .session import SESSIONS
        return sum(len(getattr(s, "flags", []) or []) for s in SESSIONS.values())
    except Exception:  # noqa: BLE001
        return 0


@router.get("/api/brain/summary")
def brain_summary(request: Request, profile: str | None = None, days: int = 30):
    from . import diag, turnlog
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")
    days = max(1, min(MAX_DAYS, int(days or 30)))
    since = (_dt.date.today() - _dt.timedelta(days=days - 1)).isoformat()
    talk = talk_counts(_turn_lines(), since)
    st = turnlog.STORE.stats()
    return {"days": days, "talk": talk, "safety": {"guarded": talk.pop("guarded"), "care": care_flags()},
            "adapted": adapted_view(profile), "log": {"turns": st.get("turns", 0), "bytes": st.get("bytes", 0)},
            "stored": "on this computer only", "words": False}
