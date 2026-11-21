"""The Brain's grown-up numbers (docs/BRAIN.md §4): counts only, read from what the app already keeps on this computer.

  GET /api/brain/summary?profile=p1&days=30

    talk     from the turn log (on by default since 0.4.3; app/turnlog.py, every cadet on this computer): turns, by
             voice / by typing, how many the app answered vs. let pass (not meant for it), the days with a turn, the
             room-state labels, and the outcome signals (hint / pass / repeat), all within the day window.
    safety   turns the word filter masked (`filtered`: router reason "safety") and turns the privacy guard kept private
             (`privacy`: turn log `guard`), split since D9 (`guarded` is their sum), and the in-memory care flags
             (app/safety.py, Session.flags) since the app started. Never the words.
    adapted  this cadet's on-device learning (app/learn): how many names it learned (not which: the names are in
             Settings → What the app has learned), the end-of-turn wait, the turns it learned from.
    log      whether the turn log holds anything and how big it is.

No text ever leaves this function: the turn log's `text` field is not read (only its `k`, `src`, `day`, `router`
outcome and reason, `room`, `guard` and signal `sig` fields), no alias heard form, no call sign. Loopback only (the LocalGuard middleware
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
    """Aggregate turn-log lines (JSON strings or dicts) into counts. Pure; never reads `text`.

    since: the first day (YYYY-MM-DD) to count. Turns AND signals honour it (a signal line carries its `day` since the
    D9 fix); a line with no day is of unknown age, so it counts only when there is no window.
    The safety counts are split: `filtered` = turns the word filter / Arc's safety tags masked (router reason
    "safety"), `privacy` = turns kept private by the privacy guard (a `guard` turn the filter did not mask).
    `guarded` (= filtered + privacy) stays for older readers."""
    out = {"turns": 0, "voice": 0, "typed": 0, "answered": 0, "passed_by": 0, "guarded": 0, "filtered": 0,
           "privacy": 0, "days": 0, "room": {k: 0 for k in ROOM_STATES}, "signals": {k: 0 for k in SIGNALS}}
    days = set()
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
        if since and (not day or day[:10] < since):
            continue
        if k == "signal":
            if r.get("sig") in SIGNALS:
                out["signals"][r["sig"]] += 1
            continue
        out["turns"] += 1
        if day:
            days.add(day[:10])
        if r.get("src") in VOICE_SRC:
            out["voice"] += 1
        else:
            out["typed"] += 1
        rt = r.get("router") if isinstance(r.get("router"), dict) else {}
        oc = rt.get("outcome")
        if oc == "ignore":
            out["passed_by"] += 1
        elif oc:
            out["answered"] += 1
        if rt.get("reason") == "safety":
            out["filtered"] += 1
            out["guarded"] += 1
        elif r.get("guard") is True:
            out["privacy"] += 1
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
    safety = {"guarded": talk.pop("guarded"), "filtered": talk.pop("filtered"), "privacy": talk.pop("privacy"),
              "care": care_flags()}
    return {"days": days, "talk": talk, "safety": safety,
            "adapted": adapted_view(profile), "log": {"turns": st.get("turns", 0), "bytes": st.get("bytes", 0)},
            "stored": "on this computer only", "words": False}
