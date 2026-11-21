"""The brain's on-device weekly counts (D1 + D2 + D3, docs/BRAIN.md §7, docs/BRAIN_SIGNALS_AUDIT.md §4).

One small file, per computer, split by cadet profile. It works whether the turn log is on or off: the grown-ups'
talk and safety numbers no longer depend on it (D2: the turn log stays on by default, but turning it off costs the
grown-ups nothing).

    <dir>/counts.json   {v: 1, weeks: {"2026-W47": {"p1": {
                            "talk":   {turns, voice, typed, answered, passed_by, room: {calm, busy, loud}, days: [YYYY-MM-DD]},
                            "safety": {profanity: {typed, ptt, directed, room}, mask: {...}, pii: {...}, care: {...}}}}}}

    kinds     profanity  the word list or a profanity tag masked the turn
              mask       another filtered turn (toxicity, child.inappropriate)
              pii        the privacy guard kept the turn private ("Let's keep names and addresses private")
              care       a self-harm or grooming cue (the care line; app/care_flags.py keeps the flag itself)
    channels  typed      typed on the keyboard
              ptt        push-to-talk (Space or the mic held): the cadet meant it
              directed   open mic, and the ear rated it said to the app (dd >= the room's dd_strong)
              room       open mic, anything else: "heard near the app", never put on a cadet

Only typed and push-to-talk are this cadet's own. Open-mic counts land on whoever is playing (or whose turn it is in
crew rotation), so the grown-ups' view labels them "heard near the app".

What it may hold: whole numbers, ISO weeks, days (never a time), profile ids and the fixed enums above. Never a word,
the turn text, a tag's p, the screen, or a call sign. clean() runs on every read and write, so a bug or a hand edit
cannot widen it. Weeks older than KEEP_WEEKS are dropped on every write and read.

Erased by: Settings → Reset (app/reset.py empties the folder), DELETE /api/brain/counts (a grown-up's "Clear safety
counts", per cadet or all), and age (12 weeks). <dir> = $BRAIN_DIR, else <cache_dir>/brain, else <data_dir>/brain_state.
Written atomically (a temp file in the same folder, then os.replace), mode 0600, like app/learn/store.py.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
import threading
from pathlib import Path

KEEP_WEEKS = 12
KINDS = ("profanity", "mask", "pii", "care")
CHANNELS = ("typed", "ptt", "directed", "room")
ROOM_STATES = ("calm", "busy", "loud")
TALK = ("turns", "voice", "typed", "answered", "passed_by")
PROFILE = re.compile(r"^p\d{1,2}$")
WEEK = re.compile(r"^\d{4}-W\d{2}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_N = 10_000_000
_LOCK = threading.Lock()


def brain_dir() -> Path:
    env = os.environ.get("BRAIN_DIR")
    if env:
        return Path(env)
    from .config import settings
    return (settings.cache_dir / "brain") if settings.cache_dir else (settings.data_dir / "brain_state")


def _path() -> Path:
    return brain_dir() / "counts.json"


def week_of(day: _dt.date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(week: str) -> _dt.date:
    y, w = week.split("-W")
    return _dt.date.fromisocalendar(int(y), int(w), 1)


def channel(source: str | None, dd: float | None, dd_strong: float) -> str:
    """The channel of a turn: typed / ptt / directed / room (the open mic is "directed" only at dd >= dd_strong)."""
    if source == "ptt":
        return "ptt"
    if source in ("listen", "voice"):
        return "directed" if isinstance(dd, (int, float)) and dd >= dd_strong else "room"
    return "typed"


def profile_id(p) -> str:
    return p if isinstance(p, str) and PROFILE.match(p) else "p1"


# ---------- shape ----------
def _n(x) -> int:
    try:
        v = int(x)
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_N, v))


def _blank_cadet() -> dict:
    return {"talk": {**{k: 0 for k in TALK}, "room": {k: 0 for k in ROOM_STATES}, "days": []},
            "safety": {k: {c: 0 for c in CHANNELS} for k in KINDS}}


def _clean_cadet(raw) -> dict:
    out = _blank_cadet()
    if not isinstance(raw, dict):
        return out
    t = raw.get("talk") if isinstance(raw.get("talk"), dict) else {}
    for k in TALK:
        out["talk"][k] = _n(t.get(k))
    rm = t.get("room") if isinstance(t.get("room"), dict) else {}
    for k in ROOM_STATES:
        out["talk"]["room"][k] = _n(rm.get(k))
    days = t.get("days") if isinstance(t.get("days"), list) else []
    out["talk"]["days"] = sorted({d for d in days if isinstance(d, str) and DAY.match(d)})[-7:]
    sf = raw.get("safety") if isinstance(raw.get("safety"), dict) else {}
    for k in KINDS:
        row = sf.get(k) if isinstance(sf.get(k), dict) else {}
        for c in CHANNELS:
            out["safety"][k][c] = _n(row.get(c))
    return out


def clean(raw, today: _dt.date | None = None) -> dict:
    """Keep only ISO weeks (the last KEEP_WEEKS), profile ids, whole numbers, days and the fixed enums. Pure."""
    today = today or _dt.date.today()
    oldest = today - _dt.timedelta(weeks=KEEP_WEEKS - 1)
    oldest_week = week_of(oldest)
    out = {"v": 1, "weeks": {}}
    weeks = raw.get("weeks") if isinstance(raw, dict) and isinstance(raw.get("weeks"), dict) else {}
    for wk, cadets in weeks.items():
        if not isinstance(wk, str) or not WEEK.match(wk) or wk < oldest_week or not isinstance(cadets, dict):
            continue
        row = {p: _clean_cadet(c) for p, c in cadets.items() if isinstance(p, str) and PROFILE.match(p)}
        if row:
            out["weeks"][wk] = row
    return out


# ---------- the file ----------
def load(today: _dt.date | None = None) -> dict:
    try:
        return clean(json.loads(_path().read_text(encoding="utf-8")), today)
    except (OSError, ValueError):
        return clean(None, today)


def _save(body: dict) -> bool:
    p = _path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".counts-", suffix=".tmp")
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


def _update(profile, fn, today: _dt.date | None = None) -> bool:
    """Read, change one cadet's row of this week, clean, write. Never raises (a count never breaks a turn)."""
    today = today or _dt.date.today()
    try:
        with _LOCK:
            body = load(today)
            wk = week_of(today)
            row = body["weeks"].setdefault(wk, {}).setdefault(profile_id(profile), _blank_cadet())
            fn(row, today)
            return _save(clean(body, today))
    except Exception:  # noqa: BLE001
        return False


def record_turn(profile, source: str | None, outcome: str | None, room: str | None = None,
                today: _dt.date | None = None) -> bool:
    """One routed kid turn: voice or typed, answered or let pass, the room label, the day."""
    def fn(row, day):
        t = row["talk"]
        t["turns"] += 1
        t["voice" if source in ("listen", "voice", "ptt") else "typed"] += 1
        if outcome == "ignore":
            t["passed_by"] += 1
        elif outcome:
            t["answered"] += 1
        if room in ROOM_STATES:
            t["room"][room] += 1
        d = day.isoformat()
        if d not in t["days"]:
            t["days"].append(d)
    return _update(profile, fn, today)


def record_safety(profile, kind: str, chan: str, today: _dt.date | None = None) -> bool:
    """One safety event: a kind (KINDS) on a channel (CHANNELS). Anything else is not counted."""
    if kind not in KINDS or chan not in CHANNELS:
        return False

    def fn(row, _day):
        row["safety"][kind][chan] += 1
    return _update(profile, fn, today)


def summary(profile, since: _dt.date, today: _dt.date | None = None) -> dict:
    """This cadet's counts in the weeks that overlap [since, today], plus the last 4 weeks' safety totals (oldest
    first) for the grown-ups' trend line. Pure read."""
    today = today or _dt.date.today()
    body = load(today)
    pid = profile_id(profile)
    talk = {**{k: 0 for k in TALK}, "room": {k: 0 for k in ROOM_STATES}, "days": 0}
    safety = {k: {c: 0 for c in CHANNELS} for k in KINDS}
    days: set[str] = set()
    for wk, cadets in body["weeks"].items():
        if week_start(wk) + _dt.timedelta(days=6) < since:
            continue
        c = cadets.get(pid)
        if not c:
            continue
        for k in TALK:
            talk[k] += c["talk"][k]
        for k in ROOM_STATES:
            talk["room"][k] += c["talk"]["room"][k]
        days.update(d for d in c["talk"]["days"] if d >= since.isoformat())
        for k in KINDS:
            for ch in CHANNELS:
                safety[k][ch] += c["safety"][k][ch]
    talk["days"] = len(days)
    trend = []
    for i in range(3, -1, -1):
        wk = week_of(today - _dt.timedelta(weeks=i))
        c = body["weeks"].get(wk, {}).get(pid)
        trend.append({"week": wk, **({k: sum(c["safety"][k].values()) for k in KINDS} if c else {k: 0 for k in KINDS})})
    return {"talk": talk, "safety": safety, "weeks": trend}


def clear(profile: str | None = None) -> int:
    """Erase every cadet's counts (profile None) or one cadet's. Returns the rows removed."""
    with _LOCK:
        if profile is None:
            n = sum(len(c) for c in load()["weeks"].values())
            try:
                _path().unlink(missing_ok=True)
            except OSError:
                pass
            return n
        body = load()
        pid = profile_id(profile)
        n = 0
        for wk in list(body["weeks"]):
            if body["weeks"][wk].pop(pid, None) is not None:
                n += 1
            if not body["weeks"][wk]:
                del body["weeks"][wk]
        _save(body)
        return n
