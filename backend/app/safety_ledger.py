"""The safety ledger (docs/BRAIN.md "Signals → Brain", docs/SECURITY.md "Retention"): what the safety path did, per
cadet profile, as day counts. On this computer only.

Why it exists: the turn log (app/turnlog.py) is a Director-training log that a family may turn off, and the care flags
used to live only in Session.flags in memory (lost on quit, every profile mixed). A grown-up needs to know, on the next
open of Settings → For grown-ups, that the guide suggested a break and a trusted grown-up, and on which day. Nothing more.

What one entry holds (and nothing else; `_clean` drops anything outside these fields before every write):

    p       the cadet profile ("p1".."p6", app/learn/store.profile_id)
    day     the local calendar day (YYYY-MM-DD), never a time
    kind    language | unkind | care | personal_info | unsafe_request   (what the safety path acted on)
    src     tagger | wordlist | phrase                                   (which check caught it: Arc Tagger, the word
                                                                          list, or the crisis / grooming phrase list)
    screen  the screen id (a short enum: "school", "cabin" ...)
    course  the course id ("moon", "archaeology")
    n       how many times that day

Never the words, never a tag score, never a session id, call sign or name. No trait labels: a count says what the app
did ("kept a turn private for language"), never what the cadet is.

Retention: `care` entries 30 days (RETAIN_CARE), every other kind 60 days (RETAIN_DAYS), pruned on every read and
write. Settings → Reset Outpost Luna (app/reset.py, desktop/main/reset.js) deletes the folder. Never in a Playtest
export (app/playtest.py only zips the turn log folder; this lives in its own folder).

A grown-up may dismiss the care banner; the entry itself stays until its 30 days are up (the dismissal is kept with it).

Storage: <dir>/ledger.json, atomic writes (temp file + rename), mode 0600 on POSIX (like app/learn/store.py).
<dir> = $SAFETY_LEDGER_DIR, else <cache_dir>/safety (the desktop app's per-user data folder), else <data_dir>/safety_state.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
from pathlib import Path

SCHEMA = "whissle.safety/1"
KINDS = ("language", "unkind", "care", "personal_info", "unsafe_request")
SOURCES = ("tagger", "wordlist", "phrase")
RETAIN_CARE = 30
RETAIN_DAYS = 60
MAX_ENTRIES = 2000           # a cap, so a stuck loop can never grow the file without bound
MAX_BYTES = 256 * 1024
_ENUM = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PID = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


def ledger_dir() -> Path:
    env = os.environ.get("SAFETY_LEDGER_DIR")
    if env:
        return Path(env)
    from .config import settings
    return (settings.cache_dir / "safety") if settings.cache_dir else (settings.data_dir / "safety_state")


def _today() -> str:
    return _dt.date.today().isoformat()


def _enum(x, default: str = "other") -> str:
    return x if isinstance(x, str) and _ENUM.match(x) else default


def _profile(p) -> str:
    return p if isinstance(p, str) and _PID.match(p) else "p1"


def _retain(kind: str) -> int:
    return RETAIN_CARE if kind == "care" else RETAIN_DAYS


def _keep(e: dict, today: str) -> bool:
    try:
        age = (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(e["day"])).days
    except (ValueError, KeyError, TypeError):
        return False
    return age < _retain(e["kind"])   # a day after "today" (a clock moved back) is kept, never lost


def _clean(raw) -> list[dict]:
    """Only the allowed fields, enums and day strings; anything else is dropped."""
    out = []
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict) or e.get("kind") not in KINDS or not isinstance(e.get("day"), str) \
                or not _DAY.match(e["day"]):
            continue
        n = e.get("n")
        out.append({"p": _profile(e.get("p")), "day": e["day"], "kind": e["kind"],
                    "src": e.get("src") if e.get("src") in SOURCES else "tagger",
                    "screen": _enum(e.get("screen")), "course": _enum(e.get("course"), "moon"),
                    "n": int(n) if isinstance(n, int) and not isinstance(n, bool) and 0 < n < 10**6 else 1,
                    **({"dismissed": True} if e.get("dismissed") is True and e["kind"] == "care" else {})})
    return out[-MAX_ENTRIES:]


class Ledger:
    """One small JSON file. Thread-safe; any IO error is swallowed (the safety line is never held up by the ledger)."""

    def __init__(self, d: Path | None = None):
        self.dir = d
        self.lock = threading.Lock()

    @property
    def path(self) -> Path:
        return (self.dir or ledger_dir()) / "ledger.json"

    def _read(self) -> list[dict]:
        try:
            p = self.path
            if p.stat().st_size > MAX_BYTES:
                return []
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return _clean(d.get("entries")) if isinstance(d, dict) and d.get("schema") == SCHEMA else []

    def _write(self, entries: list[dict]) -> bool:
        raw = json.dumps({"schema": SCHEMA, "entries": _clean(entries)}, separators=(",", ":"))
        try:
            d = self.path.parent
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / ".ledger.json.tmp"
            tmp.write_text(raw, encoding="utf-8")
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
            return True
        except OSError:
            return False

    def entries(self, profile: str | None = None, kinds=None, today: str | None = None) -> list[dict]:
        """The live entries (expired ones pruned, and the file rewritten when any were), optionally for one profile and
        some kinds."""
        today = today or _today()
        with self.lock:
            es = self._read()
            live = [e for e in es if _keep(e, today)]
            if len(live) != len(es):
                self._write(live)
        return [dict(e) for e in live if (profile is None or e["p"] == profile) and (kinds is None or e["kind"] in kinds)]

    def record(self, profile: str | None, kind: str, source: str, screen: str | None = None,
               course: str | None = None, today: str | None = None) -> bool:
        """Count one safety action. Unknown kinds are refused (False)."""
        if kind not in KINDS:
            return False
        today = today or _today()
        e = {"p": _profile(profile), "day": today, "kind": kind, "src": source if source in SOURCES else "tagger",
             "screen": _enum(screen), "course": _enum(course, "moon")}
        with self.lock:
            es = [x for x in self._read() if _keep(x, today)]
            for x in es:
                if all(x[k] == e[k] for k in ("p", "day", "kind", "src", "screen", "course")):
                    x["n"] += 1
                    x.pop("dismissed", None)   # a new care entry the same day: the banner shows again
                    break
            else:
                es.append({**e, "n": 1})
            return self._write(es)

    def care(self, profile: str | None = None, today: str | None = None) -> list[dict]:
        """The care banner's data: one row per profile and day (newest first), the courses it happened in, and whether a
        grown-up dismissed it. No words, no screen detail beyond the screen id."""
        rows: dict[tuple, dict] = {}
        for e in self.entries(profile, ("care",), today):
            r = rows.setdefault((e["p"], e["day"]), {"profile": e["p"], "day": e["day"], "n": 0, "courses": [],
                                                     "dismissed": True})
            r["n"] += e["n"]
            if e["course"] not in r["courses"]:
                r["courses"].append(e["course"])
            r["dismissed"] = r["dismissed"] and bool(e.get("dismissed"))
        return sorted(rows.values(), key=lambda r: (r["day"], r["profile"]), reverse=True)

    def dismiss_care(self, profile: str, day: str, today: str | None = None) -> int:
        """Hide the banner for that profile and day. The entry stays until its 30 days are up."""
        today = today or _today()
        n = 0
        with self.lock:
            es = [x for x in self._read() if _keep(x, today)]
            for x in es:
                if x["kind"] == "care" and x["p"] == _profile(profile) and x["day"] == day:
                    x["dismissed"] = True
                    n += 1
            self._write(es)
        return n

    def counts(self, profile: str | None = None, course: str | None = None, kinds=None, since: str | None = None,
               today: str | None = None) -> dict:
        """{kind: n} for a profile / course since a day."""
        out = {k: 0 for k in (kinds or KINDS)}
        for e in self.entries(profile, kinds, today):
            if (course is None or e["course"] == course) and (since is None or e["day"] >= since):
                out[e["kind"]] = out.get(e["kind"], 0) + e["n"]
        return out

    def clear(self) -> int:
        """Reset: delete the ledger file (and a stray temp file)."""
        n = 0
        with self.lock:
            for f in (self.path, self.path.with_name(".ledger.json.tmp")):
                try:
                    f.unlink()
                    n += 1
                except OSError:
                    pass
        return n


LEDGER = Ledger()


def kinds_of(sf: dict) -> list[tuple[str, str]]:
    """safety.classify's result -> the (kind, source) pairs the safety path acted on. The tags decide the kind; the
    word list and the phrase lists are their own sources."""
    tags = sf.get("tags") or []
    tagged = lambda *pre: any(t == p or t.startswith(p + ".") for t in tags for p in pre)  # noqa: E731
    out: list[tuple[str, str]] = []
    if sf.get("care"):
        out.append(("care", sf.get("care_src") or "tagger"))
    if sf.get("words"):
        out.append(("language", "wordlist"))
    elif tagged("safety.profanity"):
        out.append(("language", "tagger"))
    if tagged("safety.toxicity"):
        out.append(("unkind", "tagger"))
    if tagged("safety.child.inappropriate"):
        out.append(("unsafe_request", "tagger"))
    if sf.get("pii"):
        out.append(("personal_info", "tagger"))
    return out
