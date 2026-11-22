"""On-device turn log for improving the learned Director (docs/DIRECTOR_LOOP.md).

Settings -> Listening -> "Help improve the voice guide" (prefs.improve). ON by default since 0.4.3 (the owner: the
Director has never heard a real kid; every round was synthetic). An explicit opt-out stays off. While it is on, every
turn the router sees is appended to a JSONL file in the app data folder, as TEXT FEATURES only:

    the heard words (redacted: call signs, names, addresses, phone-like numbers; a turn the privacy guard caught is
    stored as "<private>"), Arc's tags / act / device_directed, the client's screen frame, the router decision, what
    the rules and the model decided, and outcome signals that arrive afterwards.
    v2 (0.4.3) adds what the learned Director saw at the turn, so an import replays what the model saw live:
      ear     the ear's ABI 2 read-out on the final words, numbers and enums only (ear_view): uconf / min word conf,
              eot, dropped words, decoder agreement, names-link p and state (never the name), almost-match p,
              quantity kinds, disfluency count, playback leak / flag, barge-in and its p, the pace numbers
      seen    the Director's own record of the turn (features.record): the situation class, the bare-turn guard,
              the hot-list match counts, the link / entity / e13 views (numbers and flags only)
      director  + mode, the primary model's and each routed file's act / p, which weight file each path consulted
              (guarded), what the guarded runtime finally did
      room    the room-state estimate (calm / busy / too loud) when the estimator is present
      wav     only in a grown-up's Playtest session (playtest.py): the file name of this turn's local audio clip
      trace   the turn graph's per-node trace (trace_view, docs/TURN_GRAPH.md): node names, ms, the node each
              decision node chose, small enum / number views; never words

Never: audio in the text log, the session id, the kid's call sign or any name, timestamps finer than the day (turn
times are seconds since the session's first logged turn). Nothing leaves the device: a developer imports a log only
when the family hands it over (`make director-import LOG=...`).

Outcome signals (one {"k": "signal"} line each, joined to its turn by `ref` on import; each carries the `day`, so the
grown-ups' counts can honour their day window, app/brain.py):
    repeat          the kid said (nearly) the same words again within REPEAT_S  -> what we did (or didn't) was wrong
    negate          "no" / "stop" / "back" / "not that" right after (NEG_S)    -> the action was wrong
    retap           the kid tapped the same thing twice within RETAP_S, right after a turn
    hint            a lesson step went to retry / hint right after a turn routed as its answer
    pass            (v2) a lesson step passed right after a turn routed as its answer (a positive signal)
    undo            (v2) an order the kid gave was reversed by the next order within UNDO_S (cancel, the opposite
                    switch, power moved back)
    confirm_cancel  a confirm we asked for was answered "no"
    confirm_yes     ... answered "yes" (a positive signal)
    misheard        (adult collection, all logs) "that's not what I said" / "I said ..." within MISHEARD_S: the words
                    were wrong (an ear error, not a Director error)
    barge           the speaker talked over our reply to that turn within BARGE_S (the reply was too long / wrong)
    nav_back        a navigation the turn caused was taken back within NAVBACK_S (the screen went back to where the
                    turn was said, or "back" / "map" was said): the navigation was wrong

Adult collection (adult_collect.py, Settings -> For grown-ups -> "Help improve Outpost Luna"; docs/ADULT_SESSIONS.md):
additive fields, only on turns logged while it is on for this profile:
    collect   true
    reply     what the app said and did for the turn: {"say": [lines, call signs redacted], "nav": {intent, arg},
              "place": entity id, "kinds": [decision types]}: the reply-line and navigation labels' candidates

Storage: <dir>/turns.jsonl, rotated to turns.1.jsonl at CAP_BYTES / 2, so the folder never holds more than ~CAP_BYTES.
Retention (docs/SECURITY.md "Retention"): on top of the size cap, lines older than RETAIN_DAYS (30) are dropped once a
day on the next write or read, and Playtest clips older than that are deleted; "Delete what's saved" and Reset delete it
all at once.
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

VERSION = 2              # 0.4.3: ear / seen / room / wav fields, pass / undo signals (import_logs reads 1 and 2)
GESTURE_S = 2.0          # round 8: a gesture this close before a turn is logged with it
CAP_BYTES = 5_000_000          # the whole log (two files); each file rotates at half
REPEAT_S = 10.0
NEG_S = 6.0
RETAP_S = 6.0
UNDO_S = 20.0                  # v2: an order reversed this soon after it ran
AFTER_TURN_S = 15.0            # a tap / lesson result this soon after a turn is about that turn
REPEAT_SHARE = 0.6
MISHEARD_S = 10.0              # "that's not what I said" this soon after a turn
BARGE_S = 20.0                 # talked over our reply this soon after the turn
NAVBACK_S = 15.0               # a navigation taken back this soon
RETAIN_DAYS = 30               # docs/SECURITY.md "Retention": the turn log keeps 30 days, whatever its size

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
MISHEARD = re.compile(r"\b(?:not what i said|i didn t say that|i did not say that|you misheard|you heard wrong|"
                      r"that s not what i said|no i said|i said)\b")
BACK_INTENTS = ("back", "panel_back", "map", "decline_offer")
_ARG = re.compile(r"^[a-z0-9_:.\-]{1,48}$")


def _course() -> str:
    """The active course id (app/courses.py), "moon" if anything is off."""
    try:
        from . import courses
        return courses.active()
    except Exception:   # noqa: BLE001
        return "moon"


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


def redact_line(text: str, names: list[str] | tuple = ()) -> str:
    """One of OUR lines (the reply), case kept for the labeller: call signs (built-in and the kid's), names after
    "my name is", and phone-like numbers replaced. At most 300 characters."""
    q = str(text or "")[:300]
    for c in sorted({*CALLSIGNS, *(norm(n) for n in names if n)}, key=len, reverse=True):
        if c:
            pat = r"[\s-]+".join(map(re.escape, c.split()))
            q = re.sub(rf"(?i)\b{pat}\b", "<callsign>", q)
    q = re.sub(r"(?i)\b(my name is|call me|i m called|i'm called)\s+\w+", lambda m: m.group(1) + " <name>", q)
    return re.sub(r"\s+", " ", _LONGNUM.sub("<number>", q)).strip()


def _arg(x):
    """A navigation's argument when it is an app id (a lesson, a site, a panel); never free words."""
    return x if isinstance(x, str) and _ARG.match(x) else None


_ENUM = re.compile(r"^[a-z_]{1,24}$")


def _enum(x) -> str | None:
    """A short lowercase label (a link state, a name kind, a quantity kind), or None: never free text."""
    return x if isinstance(x, str) and _ENUM.match(x) else None


def ear_view(ear: dict | None) -> dict | None:
    """v2: the ear's read-out on a turn's final words (session k["ear"]: libarc ABI 2 + the names linker), as numbers
    and enums only. No word, name, candidate, decoder text or audio ever: a name link keeps its p, state and kind, an
    almost match its p, a quantity its kind (and its value when small: "shields to 40" is the signal), a disfluency
    only its count."""
    if not ear:
        return None
    out: dict = {}
    for k in ("uconf", "min_wconf", "eot", "playback_leak", "barge_p", "speech_s", "max_pause_s", "end_silence_s",
              "conf", "agree"):
        v = _r(ear.get(k))
        if v is not None:
            out[k] = v
    for k in ("playback", "barge", "rescored"):
        if ear.get(k) is not None:
            out[k] = bool(ear[k])
    if "names" in ear:
        out["names"] = [{"p": _r(n.get("p")), "state": _enum(n.get("state")), "kind": _enum(n.get("kind"))}
                        for n in (ear.get("names") or []) if isinstance(n, dict)][:8]
    al = [a for a in ear.get("almost") or [] if isinstance(a, dict)]
    if al:
        out["almost"] = [{"p": _r(a.get("p"))} for a in al][:6]
    qs = [q for q in ear.get("quantities") or [] if isinstance(q, dict)]
    if qs:
        out["qty"] = []
        for q in qs[:6]:
            v = q.get("value")
            out["qty"].append({"kind": _enum(q.get("type")) or _enum(q.get("kind")) or _enum(q.get("unit")),
                               "value": v if isinstance(v, (int, float)) and abs(v) < 10000 else None})
    if ear.get("disfl"):
        out["disfl"] = len(ear["disfl"]) if isinstance(ear["disfl"], list) else 1
    if ear.get("n_dropped"):
        out["dropped"] = int(ear["n_dropped"]) if isinstance(ear["n_dropped"], (int, float)) else 1
    if ear.get("decoder_text"):
        out["dec"] = True
    if ear.get("alts"):
        out["n_alts"] = len(ear["alts"])
    if ear.get("nbest"):
        out["n_nbest"] = len(ear["nbest"])
    tier = (ear.get("hot") or {}).get("tier") if isinstance(ear.get("hot"), dict) else None
    if _enum(tier):
        out["tier"] = tier
    return out


def _numbers(d, depth: int = 0):
    """A nested view with only numbers, booleans and None kept (features.record's views); a string only under the key
    `tier` (the hot-list tier the ear matched: step / screen / names). Lists and free text never enter the log."""
    if depth > 3:
        return None
    if isinstance(d, bool) or d is None:
        return d
    if isinstance(d, (int, float)):
        return _r(d)
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if not isinstance(k, str) or isinstance(v, (list, tuple)):
                continue
            if isinstance(v, str):
                if k == "tier" and _enum(v):
                    out[k] = v
                continue
            out[k] = _numbers(v, depth + 1)
        return out
    return None


def seen_view(rec: dict | None, explain: dict | None = None) -> dict | None:
    """v2: what the learned Director saw at the turn end (features.record), numbers and flags only, plus the runtime's
    situation class and bare-turn guard (runtime.Shadow.explain)."""
    if not rec and not explain:
        return None
    rec = rec or {}
    out: dict = {}
    for k in ("e13", "link", "hot", "ent", "ear"):
        if isinstance(rec.get(k), dict):
            out[k] = _numbers(rec[k])
    for k in ("dd", "cc", "since_play", "line_gap", "since_speech"):
        v = _r(rec.get(k))
        if v is not None:
            out[k] = v
    for k in ("on_air", "speaking", "video_on", "alt_hot", "kid_open"):
        if rec.get(k) is not None:
            out[k] = bool(rec[k])
    if _enum(rec.get("playing_kind")):
        out["playing_kind"] = rec["playing_kind"]
    if explain:
        out["cls"] = explain.get("cls")
        out["bare"] = bool(explain.get("bare"))
    return out


# The turn graph's per-node trace (app/graph, docs/TURN_GRAPH.md), on a turn line as `trace`: node names, wall ms, the
# node a decision node chose, and each node's own small view (router outcome / reason / intent, the director handler,
# the model's act and p), numbers and code enums only: never words, never a name.
_TRACE_NODE = re.compile(r"^[a-z_]{1,24}(/[a-z_]{1,24}){0,3}$")
_TRACE_ENUM = re.compile(r"^[a-z][a-z0-9_+.:-]{0,39}$")
TRACE_MAX = 48


def trace_view(trace: list | None) -> list | None:
    """The graph run's trace -> what a turn line keeps: [{"n", "ms", "go"?, "o"?, "par"?, "cancelled"?}, ...]."""
    out: list = []
    for t in (trace or [])[:TRACE_MAX]:
        n = t.get("n") if isinstance(t, dict) else None
        if not isinstance(n, str) or not _TRACE_NODE.match(n):
            continue
        e: dict = {"n": n}
        if isinstance(t.get("ms"), (int, float)):
            e["ms"] = round(float(t["ms"]), 2)
        if isinstance(t.get("go"), str) and _TRACE_NODE.match(t["go"]):
            e["go"] = t["go"]
        o = t.get("o")
        if isinstance(o, dict):
            v = {k: (x if isinstance(x, (bool, int, float)) else x if isinstance(x, str) and _TRACE_ENUM.match(x)
                     else None) for k, x in o.items() if isinstance(k, str) and _TRACE_NODE.match(k)}
            v = {k: x for k, x in v.items() if x is not None}
            if v:
                e["o"] = v
        if isinstance(t.get("par"), dict):
            e["par"] = {k: round(float(x), 2) for k, x in t["par"].items()
                        if isinstance(k, str) and _TRACE_NODE.match(k) and isinstance(x, (int, float))}
        for k in ("cancelled", "interrupt"):
            if t.get(k):
                e[k] = True
        out.append(e)
    return out or None


_DIR_SIGN = {"percent": 0, "delta": 1, "little": 1}


def reverses(prev: dict | None, cmd: dict | None) -> bool:
    """v2 `undo`: `cmd` takes back the order `prev` ran: a cancel, the same switch flipped (shelter / power save), or
    power moved back (the same load, the opposite direction, or straight back from where it went)."""
    if not prev or not cmd:
        return False
    a, b = prev.get("type"), cmd.get("type")
    if b == "cancel":
        return True
    if a != b:
        return False
    if a in ("shelter", "power_save"):
        return prev.get("on") is not cmd.get("on") and cmd.get("on") is not None
    if a == "allocate":
        pa, ca = prev.get("amount") or {}, cmd.get("amount") or {}
        if prev.get("from") and cmd.get("to") == prev.get("from") and cmd.get("from") == prev.get("to"):
            return True
        if cmd.get("to") != prev.get("to"):
            return False
        pv, cv = pa.get("value"), ca.get("value")
        if pa.get("kind") in ("delta", "little") and ca.get("kind") in ("delta", "little") and \
                isinstance(pv, (int, float)) and isinstance(cv, (int, float)):
            return pv * cv < 0
    return False


def cmd_view(cmd: dict | None) -> dict | None:
    """v2: a Command in the log: its type and slots that are app words (a load, a task, a switch), never free text."""
    if not isinstance(cmd, dict) or not _enum(cmd.get("type")):
        return None
    out = {"type": cmd["type"]}
    for k in ("to", "from", "task", "what"):
        if _enum(cmd.get(k)):
            out[k] = cmd[k]
    if isinstance(cmd.get("on"), bool):
        out["on"] = cmd["on"]
    a = cmd.get("amount")
    if isinstance(a, dict) and _enum(a.get("kind")):
        v = a.get("value")
        out["amount"] = {"kind": a["kind"], "value": v if isinstance(v, (int, float)) and abs(v) < 10000 else None}
    return out


def log_dir() -> Path:
    env = os.environ.get("TURNLOG_DIR")
    if env:
        return Path(env)
    from .config import settings
    return (settings.cache_dir / "turnlog") if settings.cache_dir else (settings.data_dir / "turnlog")


class Store:
    """Append-only JSONL with one rotation (turns.jsonl -> turns.1.jsonl). Thread-safe; failures never reach the kid."""

    def __init__(self, d: Path | None = None, cap: int = CAP_BYTES, retain_days: int = RETAIN_DAYS):
        self.dir = d
        self.cap = cap
        self.retain_days = retain_days
        self.lock = threading.Lock()
        self._pruned: str | None = None    # the day prune() last ran

    @property
    def path(self) -> Path:
        return (self.dir or log_dir()) / "turns.jsonl"

    def append(self, obj: dict) -> bool:
        line = json.dumps(obj, separators=(",", ":"), default=str) + "\n"
        self.prune()
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

    def prune(self, today: str | None = None, force: bool = False) -> int:
        """Time-based retention: drop lines whose `day` is RETAIN_DAYS or more days old (a line with no day, from an older
        app, goes once its file is that old), and Playtest clips older than that. Runs at most once a day unless forced.
        Never raises (failures never reach the kid). Returns the lines + clips removed."""
        today = today or _dt.date.today().isoformat()
        if self._pruned == today and not force:
            return 0
        try:
            cut = (_dt.date.fromisoformat(today) - _dt.timedelta(days=self.retain_days - 1)).isoformat()
        except ValueError:
            return 0
        n = 0
        with self.lock:
            self._pruned = today
            for f in self.files():
                try:
                    old_file = _dt.date.fromtimestamp(f.stat().st_mtime).isoformat() < cut
                    keep, drop = [], 0
                    with open(f, encoding="utf-8") as fh:
                        for ln in fh:
                            m = _DAY_RE.search(ln)
                            if (m and m.group(1) < cut) or (not m and old_file):
                                drop += 1
                            else:
                                keep.append(ln)
                    if drop:
                        if keep:
                            tmp = f.with_name(f.name + ".tmp")
                            with open(tmp, "w", encoding="utf-8") as fh:
                                fh.writelines(keep)
                            os.replace(tmp, f)
                        else:
                            f.unlink(missing_ok=True)
                        n += drop
                except OSError:
                    continue
            for c in self.clips():
                try:
                    if _dt.date.fromtimestamp(c.stat().st_mtime).isoformat() < cut:
                        c.unlink(missing_ok=True)
                        n += 1
                except OSError:
                    continue
        return n

    def files(self) -> list[Path]:
        p = self.path
        return [x for x in (p.with_name("turns.1.jsonl"), p) if x.exists()]

    def clips(self) -> list[Path]:
        """A grown-up's Playtest session's audio clips (playtest.py), next to the log."""
        d = self.path.parent / "playtest"
        return sorted(d.glob("*.wav")) if d.is_dir() else []

    def stats(self) -> dict:
        self.prune()
        fs = self.files()
        n = 0
        for f in fs:
            with open(f, encoding="utf-8") as fh:
                n += sum(1 for line in fh if '"k":"turn"' in line)
        cl = self.clips()
        return {"dir": str(self.path.parent), "bytes": sum(f.stat().st_size for f in fs), "turns": n,
                "cap_bytes": self.cap, "clips": len(cl), "clip_bytes": sum(f.stat().st_size for f in cl),
                "retain_days": self.retain_days}

    def clear(self) -> int:
        """Settings "Delete what's saved": the text log and any playtest audio."""
        n = 0
        with self.lock:
            for f in self.files() + self.clips():
                f.unlink(missing_ok=True)
                n += 1
        return n


STORE = Store()
_DAY_RE = re.compile(r'"day":"(\d{4}-\d{2}-\d{2})"')


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
        self.last_gesture: tuple | None = None  # round 8: (gesture name, ts): voice and gesture co-occur
        self.last_cmd: tuple | None = None     # v2: (turn id, Command, ts) of the last order a turn ran (`undo`)
        self.nav_watch: dict | None = None     # a navigation a turn caused: {id, from, ts, moved} (`nav_back`)

    def _profile(self):
        return (getattr(self.sess, "prefs", None) or {}).get("profile")

    def collecting(self) -> bool:
        """An adult's "Help improve Outpost Luna" is on for this session's profile (adult_collect.py)."""
        try:
            from . import adult_collect
            return adult_collect.on_for(self._profile())
        except Exception:  # noqa: BLE001
            return False

    def on(self) -> bool:
        """prefs.improve (on by default), a grown-up's Playtest session (playtest.py) for as long as it runs, or an
        adult's collection for this profile (adult_collect.py)."""
        if (getattr(self.sess, "prefs", None) or {}).get("improve"):
            return True
        from . import playtest
        return playtest.active() or self.collecting()

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
            "profile": (getattr(self.sess, "prefs", None) or {}).get("profile"),   # [D3] whose turn (an id, never a name)
            "text": redact(text, self._names()), "nw": len(ws), "src": source,
            "arc": {"dd": _r(arc.get("device_directed")), "cc": _r(arc.get("command_complete")),
                    "act": list(arc.get("act") or [])[:4]},
            "course": _course(),   # an enum (the course id), next to the screen: never words (docs/COURSES.md §4.4)
            "frame": {"screen": ctx.screen, "step_type": ctx.step_type, "offer": ctx.offer,
                      "options": [redact(o) for o in (ctx.step_options or [])][:6],
                      "lesson_id": (self.sess.screen or {}).get("lesson_id"), "step": (self.sess.screen or {}).get("step")},
            "audio": {"speaking": bool(ctx.speaking), "playing": bool(ctx.playing), "on_air": ctx.on_air,
                      "echo_share": round(echo, 2), "n_recent": len(ctx.recent or []),
                      # round 8: what is playing (guide / capcom / crew / video): a video's audio leaks into the mic
                      "kind": ((getattr(self.sess, "belief", None) or {}).get("playing") or {}).get("kind")},
            # round 8: a hand gesture within GESTURE_S before the turn (voice + gesture co-occur, feat/gestures-v2)
            "gesture": self.last_gesture[0] if self.last_gesture and
            self.sess.clock() - self.last_gesture[1] <= GESTURE_S else None,
            "filter": [ctx.dd_min, ctx.dd_strong],
            "mode": (self.sess.belief or {}).get("mode"), "mission": bool((self.sess.belief or {}).get("mission_id")),
            "router": {"outcome": rt.get("outcome"), "reason": rt.get("reason"), "intent": rt.get("intent")},
            "director": None,
            # v2: the ear's read-out on this turn's final words (numbers and enums only), a heard turn only
            "ear": ear_view(arc.get("ear")) if source in ("listen", "voice", "ptt") else None,
            "room": _room(self.sess),
            **({"collect": True} if self.collecting() else {}),
        }

    def note_out(self, rec: dict | None, ds: list[dict]):
        """The decisions the session emitted for the turn being logged (Session.emit): kept on the record until
        finish() turns them into `reply` (adult collection only). Never written as is."""
        if rec is None or not rec.get("collect"):
            return
        rec.setdefault("_out", []).extend(d for d in ds if isinstance(d, dict))

    def _reply(self, out: list[dict]) -> dict:
        say, kinds, nav, place = [], [], None, None
        for d in out:
            t = d.get("t")
            if t and t not in kinds:
                kinds.append(t)
            if t == "say" and isinstance(d.get("text"), str):
                say.append(d["text"])
            elif t == "answer" and isinstance(d.get("r"), dict):
                if isinstance(d["r"].get("say"), str) and d["r"]["say"]:
                    say.append(d["r"]["say"])
                place = place or d["r"].get("place")
            elif t == "nav":
                nav = {"intent": _enum(d.get("intent")) or None, "arg": _arg(d.get("arg"))}
            if d.get("place") and not place:
                place = d.get("place")
        return {"say": [redact_line(x, self._names()) for x in say][:4], "nav": nav,
                "place": place if isinstance(place, str) and len(place) <= 64 else None, "kinds": kinds[:8]}

    def finish(self, rec: dict | None, director: dict | None = None, guard: bool = False):
        """Write the turn (after the decision), and score the previous turn against this one (repeat / negate /
        confirm). `director` = {"rules", "rules_cmd", "model", "p", "override", "final", "source", "confirm"}."""
        if rec is None or not self.on():
            return
        self.n += 1
        cmd = (director or {}).pop("_cmd", None) if director is not None else None
        if director is not None:
            rec["director"] = director
        if cmd is not None:
            rec["director"]["cmd"] = cmd_view(cmd)
        pcm = rec.pop("_pcm", None)
        out = rec.pop("_out", None)
        if rec.get("collect") and not guard:
            rec["reply"] = self._reply(out or [])
        if guard:
            rec["text"], rec["guard"] = "<private>", True
        elif pcm:            # a grown-up's Playtest session: the turn's audio next to the log (never a private turn)
            from . import playtest
            allow = False
            if rec.get("collect"):
                from . import adult_collect
                allow = adult_collect.audio_for(self._profile())
            wav = playtest.save_clip(rec["id"], pcm, allow=allow)
            if wav:
                rec["wav"] = wav
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
            if dt <= MISHEARD_S and MISHEARD.search(q):
                self._signal(prev, "misheard", dt, by=rec["id"])
            nw = self.nav_watch
            if nw is not None and nw["id"] == prev["id"] and dt <= NAVBACK_S and \
                    (rec["router"].get("intent") in BACK_INTENTS or NEG.match(q)):
                self._signal(prev, "nav_back", dt, by=rec["id"], how="said")
                self.nav_watch = None
        if cmd is not None and (director or {}).get("final") in ("command", "confirm_no"):
            lc = self.last_cmd
            if lc is not None and now - lc[2] <= UNDO_S and reverses(lc[1], cmd):
                self._signal({"id": lc[0]}, "undo", now - lc[2], by=rec["id"])
            self.last_cmd = (rec["id"], cmd, now) if cmd.get("type") != "cancel" else None
        self.store.append(rec)
        self.last = {"id": rec["id"], "words": ws, "ts": now, "outcome": rec["router"]["outcome"],
                     "final": (director or {}).get("final"), "confirm": bool((director or {}).get("confirm"))}
        if (director or {}).get("final") == "navigate" and not guard:
            self.nav_watch = {"id": rec["id"], "from": (rec.get("frame") or {}).get("screen"), "ts": now, "moved": False}

    def screen(self, name: str | None):
        """The client's screen changed. After a navigation a turn caused: once it moved away, a return to the screen
        the turn was said on within NAVBACK_S -> `nav_back` on that turn."""
        nw = self.nav_watch
        if nw is None or not self.on() or not name:
            return
        dt = self.sess.clock() - nw["ts"]
        if dt > NAVBACK_S:
            self.nav_watch = None
            return
        if name != nw["from"]:
            nw["moved"] = True
        elif nw["moved"]:
            self._signal({"id": nw["id"]}, "nav_back", dt, how="screen")
            self.nav_watch = None

    def barge(self):
        """The speaker talked over us (a barge-in) within BARGE_S of the last turn we acted on -> `barge` on it."""
        if not self.on() or self.last is None or self.last.get("final") in (None, "ignore"):
            return
        dt = self.sess.clock() - self.last["ts"]
        if dt <= BARGE_S and not self.last.get("barged"):
            self.last["barged"] = True
            self._signal(self.last, "barge", dt)

    def ui(self, event: str | None, target: str | None):
        """A tap / button. The same target twice within RETAP_S, right after a turn -> `retap` on that turn."""
        if not self.on() or not event or event in ("screen", "barge_in", "kid_done"):
            return
        now = self.sess.clock()
        if event == "gesture":
            self.last_gesture = (str(target or "")[:24] or None, now)
            return
        key = (event, target)
        if self.last_tap and self.last_tap[0] == key and now - self.last_tap[1] <= RETAP_S and \
                self.last is not None and now - self.last["ts"] <= AFTER_TURN_S:
            self._signal(self.last, "retap", now - self.last["ts"], ui=event)
        self.last_tap = (key, now)

    def lesson(self, status: str | None, step_type: str | None = None):
        """The Academy's grade for the step (the client reports it): retry / hint right after an `answer` turn."""
        if not self.on() or status not in ("retry", "hint", "missed", "passed"):
            return
        now = self.sess.clock()
        if self.last is not None and self.last["outcome"] == "answer" and now - self.last["ts"] <= AFTER_TURN_S:
            self._signal(self.last, "pass" if status == "passed" else "hint", now - self.last["ts"],
                         status=None if status == "passed" else status, step_type=step_type)

    def _signal(self, prev: dict, sig: str, dt: float, **k):
        self.store.append({"k": "signal", "v": VERSION, "s": self.sid, "ref": prev["id"], "sig": sig,
                           "day": _dt.date.today().isoformat(), "dt": round(dt, 2), **{a: b for a, b in k.items() if b is not None}})


def _room(sess) -> dict | None:
    """The room-state estimate (calm / busy / too loud, feat/classroom-teacher) when the session has one: its label and
    numbers only. None until that estimator is present."""
    try:
        r = getattr(sess, "room_state", None)
        r = r() if callable(r) else r
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(r, dict):
        return None
    return {k: (_enum(v) if isinstance(v, str) else _r(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
                else v if isinstance(v, bool) else None) for k, v in list(r.items())[:8]}


def _r(x):
    try:
        return None if x is None else round(float(x), 3)
    except (TypeError, ValueError):
        return None
