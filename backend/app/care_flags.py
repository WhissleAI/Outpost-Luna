"""Care flags that wait for a grown-up (D4, option b: docs/BRAIN_SIGNALS_AUDIT.md §3.3 S3, docs/BRAIN.md §7).

When a turn carries a self-harm or grooming cue (app/safety.py `care`), CAPCOM says the care line and the session
raises a flag. Before D4 the flag lived in memory and was gone when the app quit, so a grown-up rarely saw it. Now:

    <brain dir>/care.json   {v: 1, flags: [{id, kind, day, profile, n}]}

    kind     "self_harm" | "grooming"   (from the tag or the phrase backstop; never the words)
    day      YYYY-MM-DD                 (never a time)
    profile  the cadet playing, or whose turn it was in crew rotation (never a call sign)
    n        how many times that kind came up that day for that cadet (one flag per cadet, kind and day)

A flag stays until a grown-up marks it seen on the Progress page (POST /api/safety/flags/{id}/ack, or all of one
cadet's) and for MAX_DAYS at most. Never the words, the screen, the tag's p or a time of day: a grown-up who needs
more talks with the cadet. Reset empties the folder (app/reset.py). The reliability caveat travels with it: precision
is high, recall on indirect phrasing about 0.5, so a missing flag never means "all clear".
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import tempfile
import threading

from .brain_counts import PROFILE, brain_dir, profile_id

MAX_DAYS = 30
KINDS = ("self_harm", "grooming")
ID = re.compile(r"^[0-9a-f]{8}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCK = threading.Lock()


def kind_of(tags) -> str | None:
    """The care kind from a turn's tags (safety.classify `tags`): grooming wins over self-harm when both are there."""
    ts = [str(t) for t in (tags or [])]
    if any(t.startswith("safety.child.grooming_cue") for t in ts):
        return "grooming"
    if any(t.startswith("safety.crisis.self_harm") for t in ts):
        return "self_harm"
    return None


def _path():
    return brain_dir() / "care.json"


def clean(raw, today: _dt.date | None = None) -> dict:
    """Only known kinds, real days within MAX_DAYS, profile ids, hex ids and whole counts. Pure."""
    today = today or _dt.date.today()
    oldest = (today - _dt.timedelta(days=MAX_DAYS - 1)).isoformat()
    out = []
    flags = raw.get("flags") if isinstance(raw, dict) and isinstance(raw.get("flags"), list) else []
    for f in flags:
        if not isinstance(f, dict):
            continue
        fid, kind, day, prof = f.get("id"), f.get("kind"), f.get("day"), f.get("profile")
        if not (isinstance(fid, str) and ID.match(fid) and kind in KINDS and isinstance(day, str) and DAY.match(day)
                and day >= oldest and isinstance(prof, str) and PROFILE.match(prof)):
            continue
        try:
            n = max(1, min(999, int(f.get("n") or 1)))
        except (TypeError, ValueError):
            n = 1
        out.append({"id": fid, "kind": kind, "day": day, "profile": prof, "n": n})
    return {"v": 1, "flags": out[-200:]}


def load(today: _dt.date | None = None) -> dict:
    try:
        return clean(json.loads(_path().read_text(encoding="utf-8")), today)
    except (OSError, ValueError):
        return clean(None, today)


def _save(body: dict) -> bool:
    p = _path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".care-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f, separators=(",", ":"))
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return True
    except OSError:
        return False


def add(profile, kind: str | None, today: _dt.date | None = None) -> dict | None:
    """Raise (or bump) this cadet's flag for this kind today. Never raises."""
    if kind not in KINDS:
        return None
    today = today or _dt.date.today()
    pid, day = profile_id(profile), today.isoformat()
    try:
        with _LOCK:
            body = load(today)
            for f in body["flags"]:
                if f["profile"] == pid and f["kind"] == kind and f["day"] == day:
                    f["n"] = min(999, f["n"] + 1)
                    _save(clean(body, today))
                    return dict(f)
            f = {"id": secrets.token_hex(4), "kind": kind, "day": day, "profile": pid, "n": 1}
            body["flags"].append(f)
            _save(clean(body, today))
            return dict(f)
    except Exception:  # noqa: BLE001  (a flag never breaks a turn)
        return None


def open_flags(profile: str | None = None, today: _dt.date | None = None) -> list[dict]:
    fl = load(today)["flags"]
    return [f for f in fl if profile is None or f["profile"] == profile_id(profile)]


def ack(flag_id: str | None = None, profile: str | None = None) -> int:
    """A grown-up saw it: drop one flag (by id) or every flag of one cadet. Returns how many were dropped."""
    with _LOCK:
        body = load()
        keep = [f for f in body["flags"] if not ((flag_id and f["id"] == flag_id) or
                                                  (flag_id is None and profile and f["profile"] == profile_id(profile)))]
        n = len(body["flags"]) - len(keep)
        if n:
            body["flags"] = keep
            _save(body)
        return n


def clear() -> int:
    with _LOCK:
        n = len(load()["flags"])
        try:
            _path().unlink(missing_ok=True)
        except OSError:
            pass
        return n
