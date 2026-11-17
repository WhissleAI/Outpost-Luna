"""On-device learning: where the learned settings live, and how they are written.

One small JSON file per cadet profile (`profile-<id>.json`) plus one for the computer itself (`device.json`, the echo
path), in the per-user app data folder: `<cache_dir>/learning/` in the desktop app (the folder Settings → Reset
empties), `backend/data/learning_state/` in a dev checkout, or `LEARN_DIR`. Writes are atomic (a temp file in the same
folder, then rename), so a hard quit never leaves half a file; a file that does not parse is treated as empty.

What a file may hold is fixed by `ALLOWED` below: numbers, counters, short id strings, and (in a profile) the heard
form of a name the kid confirmed, at most ALIAS_MAX_CHARS long. No audio, no transcripts, no call sign. `clean()`
drops anything else before every write, so a bug elsewhere cannot widen what is stored.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

SCHEMA = "whissle.learn/1"
MAX_BYTES = 64 * 1024            # a profile file is a few KB; anything bigger is refused (and the old file kept)
ALIAS_MAX_CHARS = 40
_ID = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_LOCK = threading.Lock()


def learn_dir() -> Path:
    env = os.environ.get("LEARN_DIR")
    if env:
        return Path(env)
    from ..config import settings
    return (settings.cache_dir / "learning") if settings.cache_dir else (settings.data_dir / "learning_state")


def profile_id(pid: str | None) -> str:
    """A cadet profile id as the client sends it ("p1".."p6"); anything else is the default profile."""
    return pid if isinstance(pid, str) and _ID.match(pid) else "p1"


def path_for(name: str) -> Path:
    return learn_dir() / f"{name}.json"


def read(name: str) -> dict:
    try:
        p = path_for(name)
        if p.stat().st_size > MAX_BYTES:
            return {}
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and d.get("schema") == SCHEMA else {}


def write(name: str, body: dict) -> bool:
    """Atomic write of a cleaned body. False (and nothing changed) on any error: learning never stops the app."""
    body = clean({**body, "schema": SCHEMA})
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    if len(raw) > MAX_BYTES:
        return False
    with _LOCK:
        try:
            d = learn_dir()
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f".{name}.json.tmp"
            tmp.write_text(raw, encoding="utf-8")
            os.replace(tmp, d / f"{name}.json")
            if os.name != "nt":
                os.chmod(d / f"{name}.json", 0o600)
            return True
        except OSError:
            return False


def remove(name: str) -> bool:
    with _LOCK:
        try:
            path_for(name).unlink()
            return True
        except OSError:
            return False


def clear_all() -> int:
    """Every learned file (Reset learning for everyone, Settings → Reset). -> files removed."""
    n = 0
    with _LOCK:
        d = learn_dir()
        if not d.is_dir():
            return 0
        for p in d.iterdir():
            if p.suffix == ".json" or p.name.endswith(".json.tmp"):
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    pass
    return n


# ---- what a file may hold -----------------------------------------------------------------------------------------
_NUM = (int, float)


def _num(v) -> bool:
    return isinstance(v, _NUM) and not isinstance(v, bool) and v == v and abs(v) < 1e12


def _short(v, n: int = 24) -> bool:
    return isinstance(v, str) and 0 < len(v) <= n and _ID.match(v.replace(".", "_").replace(":", "_")) is not None


def _alias(v) -> bool:
    return isinstance(v, str) and 0 < len(v) <= ALIAS_MAX_CHARS and re.fullmatch(r"[a-z0-9 ']+", v) is not None


def _eid(v) -> bool:
    """An entity id (registry ids: lower-case words joined by _ or -)."""
    return isinstance(v, str) and re.fullmatch(r"[a-z0-9_-]{1,48}", v) is not None


def _nums(d) -> dict:
    """{short key: number} only."""
    return {k: v for k, v in (d or {}).items() if _short(k, 32) and _num(v)} if isinstance(d, dict) else {}


def clean(body: dict) -> dict:
    out: dict = {"schema": SCHEMA}
    for k in ("v", "created", "updated"):
        if _num(body.get(k)):
            out[k] = body[k]
    if isinstance(body.get("kind"), str) and body["kind"] in ("profile", "device"):
        out["kind"] = body["kind"]
    if _short(body.get("profile")):
        out["profile"] = body["profile"]
    if isinstance(body.get("echo"), dict):
        e = body["echo"]
        o = _nums(e)
        if isinstance(e.get("delays"), list):          # recent per-line delay estimates (ms), numbers only
            o["delays"] = [round(float(x), 1) for x in e["delays"][-64:] if _num(x)]
        if isinstance(e.get("delay_at"), list):        # when each was measured (minutes since the file was created)
            o["delay_at"] = [round(float(x), 2) for x in e["delay_at"][-64:] if _num(x)]
        if isinstance(e.get("leak_echo"), list):
            o["leak_echo"] = [round(float(x), 3) for x in e["leak_echo"][-128:] if _num(x)]
        if isinstance(e.get("leak_kid"), list):
            o["leak_kid"] = [round(float(x), 3) for x in e["leak_kid"][-128:] if _num(x)]
        out["echo"] = o
    if isinstance(body.get("aliases"), list):
        al = []
        for a in body["aliases"][:64]:
            if isinstance(a, dict) and _alias(a.get("heard")) and _eid(a.get("id")):
                al.append({"heard": a["heard"], "id": a["id"], **_nums({k: v for k, v in a.items() if k not in ("heard", "id")})})
        out["aliases"] = al
    if isinstance(body.get("pending"), list):          # confirmations not yet enough for an alias
        pd = []
        for a in body["pending"][:64]:
            if isinstance(a, dict) and _alias(a.get("heard")) and _eid(a.get("id")):
                pd.append({"heard": a["heard"], "id": a["id"], **_nums({k: v for k, v in a.items() if k not in ("heard", "id")})})
        out["pending"] = pd
    if isinstance(body.get("blocked"), list):          # heard forms a "no" or a removal ruled out
        out["blocked"] = [b for b in body["blocked"][-64:] if _alias(b)]
    if isinstance(body.get("habits"), dict):
        h = body["habits"]
        o = _nums(h)
        for k in ("yes_words", "no_words"):            # the kid's own short yes / no words, with counts
            if isinstance(h.get(k), dict):
                o[k] = {w: int(c) for w, c in list(h[k].items())[:16] if _alias(w) and len(w) <= 12 and _num(c)}
        out["habits"] = o
    if isinstance(body.get("policy"), dict):
        out["policy"] = _nums(body["policy"])
    return out
