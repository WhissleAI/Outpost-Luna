"""Opt-in, on-device turn log for improving the learned Director (docs/DIRECTOR_LOOP.md).

Settings -> "Help improve the voice guide" (prefs.improve, OFF by default). Only while it is on, every turn the
router sees is appended to a JSONL file in the app data folder, as TEXT FEATURES only:

    the heard words (redacted: call signs, names, addresses, phone-like numbers; a turn the privacy guard caught is
    stored as "<private>"), Arc's tags / act / device_directed, the client's screen frame, the router decision, what
    the rules and the model decided, and outcome signals that arrive afterwards.

Never: audio, the session id, the kid's call sign or any name, timestamps finer than the day (turn times are seconds
since the session's first logged turn). Nothing leaves the device: a developer imports a log only when the family
hands it over (`make director-import LOG=...`).

Outcome signals (one {"k": "signal"} line each, joined to its turn by `ref` on import):
    repeat          the kid said (nearly) the same words again within REPEAT_S  -> what we did (or didn't) was wrong
    negate          "no" / "stop" / "back" / "not that" right after (NEG_S)    -> the action was wrong
    retap           the kid tapped the same thing twice within RETAP_S, right after a turn
    hint            a lesson step went to retry / hint right after a turn routed as its answer
    confirm_cancel  a confirm we asked for was answered "no"
    confirm_yes     ... answered "yes" (a positive signal)

Storage: <dir>/turns.jsonl, rotated to turns.1.jsonl at CAP_BYTES / 2, so the folder never holds more than ~CAP_BYTES.
<dir> = $TURNLOG_DIR, else <cache_dir>/turnlog (the desktop app's per-user data folder), else <data_dir>/turnlog.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import threading
from pathlib import Path

from .gazetteer import norm

VERSION = 1
CAP_BYTES = 5_000_000          # the whole log (two files); each file rotates at half
REPEAT_S = 10.0
NEG_S = 6.0
RETAP_S = 6.0
AFTER_TURN_S = 15.0            # a tap / lesson result this soon after a turn is about that turn
REPEAT_SHARE = 0.6

NEG = re.compile(r"^(?:no|nope|no no|stop|stop it|stop that|back|go back|cancel|cancel that|not that|not that one|"
                 r"wrong|that s wrong|that s not it|no wait|wait no|never mind|nevermind|undo|i didn t say that|"
                 r"that s not what i said)$")
CALLSIGNS = ["comet", "nova", "rocket", "orbit", "moon moth", "crater cat", "star hopper", "sky otter", "pulsar",
             "moonbeam", "rover fox", "stardust"]     # session.CALLSIGNS (frontend story.js)
_NAME = re.compile(r"\b(my name is|my name s|i m called|call me|they call me|my call sign is|my callsign is|"
                   r"i am called)\s+((?:\w+\s*){1,2})")
_ADDR = re.compile(r"\b(i live (?:at|on|in|near)|my address is|my house is (?:at|on)|my school is)\b.*$")
_PHONE = re.compile(r"\b(my (?:phone|phone number|number|mom s number|dad s number) is)\b.*$")
_LONGNUM = re.compile(r"\b\d{5,}\b|\b(?:\d+\s+){3,}\d+\b")


def redact(text: str, names: list[str] | tuple = ()) -> str:
    """Lowercased, punctuation-free words with call signs, names, addresses and phone-like numbers replaced."""
    q = norm(text or "")
    q = _ADDR.sub(lambda m: m.group(1) + " <address>", q)
    q = _PHONE.sub(lambda m: m.group(1) + " <number>", q)
    q = _NAME.sub(lambda m: m.group(1) + " <name> ", q).strip()
    for c in sorted({*CALLSIGNS, *(norm(n) for n in names if n)}, key=len, reverse=True):
        if c:
            q = re.sub(rf"\b{re.escape(c)}\b", "<callsign>", q)
    q = _LONGNUM.sub("<number>", q)
    return re.sub(r"\s+", " ", q).strip()


def log_dir() -> Path:
    env = os.environ.get("TURNLOG_DIR")
    if env:
        return Path(env)
    from .config import settings
    return (settings.cache_dir / "turnlog") if settings.cache_dir else (settings.data_dir / "turnlog")


class Store:
    """Append-only JSONL with one rotation (turns.jsonl -> turns.1.jsonl). Thread-safe; failures never reach the kid."""

    def __init__(self, d: Path | None = None, cap: int = CAP_BYTES):
        self.dir = d
        self.cap = cap
        self.lock = threading.Lock()

    @property
    def path(self) -> Path:
        return (self.dir or log_dir()) / "turns.jsonl"

    def append(self, obj: dict) -> bool:
        line = json.dumps(obj, separators=(",", ":"), default=str) + "\n"
        try:
            with self.lock:
                p = self.path
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.exists() and p.stat().st_size + len(line) > self.cap // 2:
                    os.replace(p, p.with_name("turns.1.jsonl"))
                with open(p, "a", encoding="utf-8") as f:
                    f.write(line)
            return True
        except OSError:
            return False

    def files(self) -> list[Path]:
        p = self.path
        return [x for x in (p.with_name("turns.1.jsonl"), p) if x.exists()]

    def stats(self) -> dict:
        fs = self.files()
        n = 0
        for f in fs:
            with open(f, encoding="utf-8") as fh:
                n += sum(1 for line in fh if '"k":"turn"' in line)
        return {"dir": str(self.path.parent), "bytes": sum(f.stat().st_size for f in fs), "turns": n,
                "cap_bytes": self.cap}

    def clear(self) -> int:
        n = 0
        with self.lock:
            for f in self.files():
                f.unlink(missing_ok=True)
                n += 1
        return n


STORE = Store()


def _overlap(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sb = set(b)
    return sum(w in sb for w in a) / max(len(a), len(b))


class SessionLog:
    """One per Session. `begin()` at the router, `finish()` once the turn is decided (writes it), `ui()` / `lesson()`
    for later outcome signals. Every method is a no-op unless the session's prefs.improve is on."""

    def __init__(self, sess, store: Store | None = None):
        self.sess = sess
        self.store = store or STORE
        self.sid = secrets.token_hex(4)        # a random per-session tag (never the session id)
        self.n = 0
        self.t0: float | None = None
        self.last: dict | None = None          # the last logged turn: {id, words, ts, outcome, final, confirm}
        self.last_tap: tuple | None = None     # (id, ts)

    def on(self) -> bool:
        return bool((getattr(self.sess, "prefs", None) or {}).get("improve"))

    def _t(self) -> float:
        now = self.sess.clock()
        if self.t0 is None:
            self.t0 = now
        return round(now - self.t0, 2)

    def _names(self) -> list[str]:
        return [x for x in ((getattr(self.sess, "screen", None) or {}).get("callsign"),
                            (getattr(self.sess, "belief", None) or {}).get("callsign")) if x]

    def begin(self, text: str, source: str, ctx, rt: dict, arc: dict | None = None) -> dict | None:
        if not self.on():
            return None
        from . import turn_router as R
        ws = R.words(text)
        recent = list(ctx.recent or []) + list(ctx.older or [])
        echo = max((_overlap(ws, R.words(x)) for x in recent), default=0.0)
        arc = arc or {}
        return {
            "k": "turn", "v": VERSION, "s": self.sid, "id": f"{self.sid}-{self.n}", "t": self._t(),
            "day": _dt.date.today().isoformat(),
            "text": redact(text, self._names()), "nw": len(ws), "src": source,
            "arc": {"dd": _r(arc.get("device_directed")), "cc": _r(arc.get("command_complete")),
                    "act": list(arc.get("act") or [])[:4]},
            "frame": {"screen": ctx.screen, "step_type": ctx.step_type, "offer": ctx.offer,
                      "options": [redact(o) for o in (ctx.step_options or [])][:6]},
            "audio": {"speaking": bool(ctx.speaking), "playing": bool(ctx.playing), "on_air": ctx.on_air,
                      "echo_share": round(echo, 2), "n_recent": len(ctx.recent or [])},
            "filter": [ctx.dd_min, ctx.dd_strong],
            "mode": (self.sess.belief or {}).get("mode"), "mission": bool((self.sess.belief or {}).get("mission_id")),
            "router": {"outcome": rt.get("outcome"), "reason": rt.get("reason"), "intent": rt.get("intent")},
            "director": None,
        }

    def finish(self, rec: dict | None, director: dict | None = None, guard: bool = False):
        """Write the turn (after the decision), and score the previous turn against this one (repeat / negate /
        confirm). `director` = {"rules", "rules_cmd", "model", "p", "override", "final", "source", "confirm"}."""
        if rec is None or not self.on():
            return
        self.n += 1
        if director is not None:
            rec["director"] = director
        if guard:
            rec["text"], rec["guard"] = "<private>", True
        now = self.sess.clock()
        ws = rec["text"].split()
        prev = self.last
        if prev is not None and not guard:
            dt = now - prev["ts"]
            q = rec["text"]
            if dt <= NEG_S and NEG.match(q):
                self._signal(prev, "negate", dt, by=rec["id"])
            if prev.get("confirm") and dt <= 30:
                fin = (director or {}).get("final")
                if fin == "confirm_no" or NEG.match(q):
                    self._signal(prev, "confirm_cancel", dt, by=rec["id"])
                elif fin == "confirm_yes":
                    self._signal(prev, "confirm_yes", dt, by=rec["id"])
            elif dt <= REPEAT_S and len(ws) >= 1 and _overlap(ws, prev["words"]) >= REPEAT_SHARE and \
                    not NEG.match(q):
                self._signal(prev, "repeat", dt, by=rec["id"], same_outcome=prev["outcome"] == rec["router"]["outcome"])
        self.store.append(rec)
        self.last = {"id": rec["id"], "words": ws, "ts": now, "outcome": rec["router"]["outcome"],
                     "final": (director or {}).get("final"), "confirm": bool((director or {}).get("confirm"))}

    def ui(self, event: str | None, target: str | None):
        """A tap / button. The same target twice within RETAP_S, right after a turn -> `retap` on that turn."""
        if not self.on() or not event or event in ("screen", "barge_in", "kid_done"):
            return
        now = self.sess.clock()
        key = (event, target)
        if self.last_tap and self.last_tap[0] == key and now - self.last_tap[1] <= RETAP_S and \
                self.last is not None and now - self.last["ts"] <= AFTER_TURN_S:
            self._signal(self.last, "retap", now - self.last["ts"], ui=event)
        self.last_tap = (key, now)

    def lesson(self, status: str | None, step_type: str | None = None):
        """The Academy's grade for the step (the client reports it): retry / hint right after an `answer` turn."""
        if not self.on() or status not in ("retry", "hint", "missed"):
            return
        now = self.sess.clock()
        if self.last is not None and self.last["outcome"] == "answer" and now - self.last["ts"] <= AFTER_TURN_S:
            self._signal(self.last, "hint", now - self.last["ts"], status=status, step_type=step_type)

    def _signal(self, prev: dict, sig: str, dt: float, **k):
        self.store.append({"k": "signal", "v": VERSION, "s": self.sid, "ref": prev["id"], "sig": sig,
                           "dt": round(dt, 2), **{a: b for a, b in k.items() if b is not None}})


def _r(x):
    try:
        return None if x is None else round(float(x), 3)
    except (TypeError, ValueError):
        return None
