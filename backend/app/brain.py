"""The Brain's grown-up numbers (docs/BRAIN.md §4, §7, §9): counts only, read from what the app keeps on this computer.

  GET /api/brain/summary?profile=p1&days=30

    scope    "cadet": this cadet's weekly counts store (app/brain_counts.py) and open care flags (app/care_flags.py),
             written whether the turn log is on or off (D2). "computer": the store holds nothing for this cadet in the
             window yet, so the counts come from the turn log (every cadet on this computer), as before D2.
    talk     turns, by voice / by typing, answered vs. let pass (not meant for it), the days with a turn, the room-state
             labels; with scope "computer" also the turn log's outcome signals (hint / pass / repeat), all in the window.
    safety   `filtered` (the word filter / safety tags masked the turn) and `privacy` (the privacy guard kept it
             private), split since D9 (`guarded` is their sum). With scope "cadet": `by_kind` (profanity / mask, each
             by channel: typed, ptt, directed, room), the last 4 weeks, and `care_flags` [{id, kind, day, n}] that
             wait for a grown-up (`care` is how many). Never the words.
    adapted  this cadet's on-device learning (app/learn): how many names it learned (not which: the names are in
             Settings → What the app has learned), the end-of-turn wait, the turns it learned from.
    log      whether the turn log holds anything and how big it is.

  GET /api/brain/class?profiles=p1,p2   every listed cadet's counts in one read (the teacher's class summary)
  DELETE /api/brain/counts?profile=p1   a grown-up's "Clear this cadet's safety counts" (and her care flags)

No text ever leaves this module: the turn log's `text` field is not read (only its `k`, `src`, `day`, `router`
outcome and reason, `room`, `guard` and signal `sig` fields), no alias heard form, no call sign. Loopback only (the
LocalGuard middleware on every route, app/main.py) and the local token, like GET /api/learn (diag.authorized).
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


def cadet_view(profile: str | None, since: _dt.date) -> dict | None:
    """[D1-D4] This cadet's weekly counts (app/brain_counts.py) and open care flags (app/care_flags.py), or None when
    the store holds nothing for this cadet in the window (an install from before the store: the turn log answers)."""
    from . import brain_counts, care_flags
    c = brain_counts.summary(profile, since)
    sf = c["safety"]
    flags = [{"id": f["id"], "kind": f["kind"], "day": f["day"], "n": f["n"]} for f in care_flags.open_flags(profile)]
    busy = c["talk"]["turns"] or any(v for row in sf.values() for v in row.values()) or flags
    if not busy:
        return None
    filtered = sum(sf["profanity"].values()) + sum(sf["mask"].values())
    privacy = sum(sf["pii"].values())
    return {"talk": {**c["talk"], "signals": {k: 0 for k in SIGNALS}},
            "safety": {"guarded": filtered + privacy, "filtered": filtered, "privacy": privacy, "care": len(flags),
                       "by_kind": {"profanity": sf["profanity"], "mask": sf["mask"]}, "care_flags": flags,
                       "weeks": c["weeks"]}}


@router.get("/api/brain/summary")
def brain_summary(request: Request, profile: str | None = None, days: int = 30):
    from . import brain_counts, diag, turnlog
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")
    days = max(1, min(MAX_DAYS, int(days or 30)))
    since_d = _dt.date.today() - _dt.timedelta(days=days - 1)
    pid = brain_counts.profile_id(profile)
    st = turnlog.STORE.stats()
    log = {"turns": st.get("turns", 0), "bytes": st.get("bytes", 0)}
    cv = cadet_view(pid, since_d)
    if cv is not None:   # [D2] the counts store: this cadet, whether the turn log is on or off
        return {"days": days, "scope": "cadet", **cv, "adapted": adapted_view(pid), "log": log,
                "stored": "on this computer only", "words": False}
    talk = talk_counts(_turn_lines(), since_d.isoformat())   # before the store: the turn log, every cadet
    safety = {"guarded": talk.pop("guarded"), "filtered": talk.pop("filtered"), "privacy": talk.pop("privacy"),
              "care": 0, "care_flags": []}
    return {"days": days, "scope": "computer", "talk": talk, "safety": safety, "adapted": adapted_view(pid),
            "log": log, "stored": "on this computer only", "words": False}


@router.get("/api/brain/class")
def brain_class(request: Request, profiles: str = "", days: int = 30):
    """[D7 prep] Every listed cadet's counts on this computer, in one read (the teacher's class summary). Counts only."""
    from . import brain_counts, diag
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")
    days = max(1, min(MAX_DAYS, int(days or 30)))
    since_d = _dt.date.today() - _dt.timedelta(days=days - 1)
    ids = [p for p in (profiles or "").split(",") if brain_counts.PROFILE.match(p)][:12]
    out = {}
    for p in ids:
        cv = cadet_view(p, since_d)
        out[p] = cv or {"talk": None, "safety": {"guarded": 0, "filtered": 0, "privacy": 0, "care": 0,
                                                 "by_kind": None, "care_flags": [], "weeks": []}}
    return {"days": days, "cadets": out, "words": False}


@router.delete("/api/brain/counts")
def brain_counts_clear(request: Request, profile: str | None = None):
    """A grown-up's "Clear safety counts" (Progress): one cadet's weekly counts and care flags, or everyone's."""
    from . import brain_counts, care_flags, diag
    if not diag.authorized(request.headers):
        raise HTTPException(401, "missing or wrong local token")
    if profile is not None and not brain_counts.PROFILE.match(profile):
        raise HTTPException(400, "bad profile")
    n = brain_counts.clear(profile)
    f = care_flags.ack(profile=profile) if profile else care_flags.clear()
    return {"cleared": n, "flags": f}
