"""The session Director (docs/SESSION_CONTRACT.md): one live session per browser. Streams in, one belief state,
several typed decisions out.

    inputs ──► Session.belief ──► policy ──► decisions (id, priority, after) ──► every socket of the session

Inputs:  hello / ui / typed / playback (WS /ws/session), words / turn / arc / emotion (posted by /ws/listen), mission
         events + state deltas (polled from the sim registry once a second; the sim has no hooks), lesson events.
Outputs: say, play, fly, highlight, card, hud, alert, ask_confirm, lesson, floor, cancel.

The turn itself is still `director.direct()`; this module decides WHEN to answer, what else to say around the answer,
what to drop on barge-in, and what to say without being asked (storms, comm windows, low power at night), under the
floor rules of §3.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections import deque
from typing import Any, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import director, models_client, steering, turnlog
from . import safety as safety_
from . import turn_router as router_
from .director_model import runtime as dmodel
from .director import P_ANSWER, P_BARGE, P_CRITICAL, P_GUARD, P_NARRATION, P_NUDGE, decision
from .gazetteer import norm
from .knowledge.answer import did_you_mean
from .mission import capcom
from .readout import summarize

router = APIRouter()

POLL_S = 1.0               # mission poll (telemetry deltas + new events)
NUDGE_QUIET_S = 8.0        # §3 rule 7: no nudge within 8 s of the last speech
NUDGE_EVERY_S = 30.0       # §3 rule 7: at most one nudge per 30 s
DEDUP_S = 6.0              # the same turn text from listen and from the client counts once
HOLD_MAX_S = 30.0          # held proactive decisions older than this are dropped (stale news)
CHATTER_DD = 0.5
ECHO_SHARE = 0.6           # §3 rule 2: ≥ 60% of the words appear in what we're playing → echo, not barge-in
RESOURCES = {"power_pct": "power", "life_support_pct": "life_support", "dose_msv": "dose"}
LOADS = ("shields", "life_support", "greenhouse", "science", "rover", "comms", "heaters")
REF_LOAD = {"dose": "shields", "life_support": "life support", "power": None}  # resource -> the load that moves it
PRONOUN = re.compile(r"\b(it|that|this one|that one)\b", re.I)
NAMED = re.compile(r"\b(power|battery|oxygen|air|life support|dose|radiation|shields?|greenhouse|science|rover|comms?|"
                   r"radio|heaters?)\b", re.I)
ALARM_EMOTIONS = ("frustrated", "confused", "scared", "anxious")
# Story beats CAPCOM speaks from the session (docs/GAMEPLAY.md). The others ride on a sim event that already has a line
# (forecast = storm_warning, crisis = solar_storm, recovery = storm_end, earthrise = comm_open), or the client says them
# (arrival: the cabin hello).
SPOKEN_BEATS = ("settle", "comm_gap", "first_dark", "ice_return", "final_downlink")


# Settings (docs/VOICES.md). The client owns persistence: it sends {t|type: "prefs", …} after hello on every connect.
PREF_DEFAULTS = {"voice": None, "voice_all": False, "engine": "os", "steer_voice": None, "rate": 1.0, "expressiveness": steering.EXPR_DEFAULT,
                 "filter": "normal", "level": "cadet", "listen": "handsfree", "volume": 1.0,
                 "improve": False, "pack": True}   # pack: the recorded guide voice for fixed lines (docs/VOICE_PACK.md); improve: the opt-in on-device turn log (turnlog.py, docs/DIRECTOR_LOOP.md)
LEVELS = ("cadet", "commander")
LISTEN = ("handsfree", "ptt")
OPEN_MIC = ("listen", "voice")    # turn sources from the open mic (the ear relay; the client's copy of an ear turn)


def clean_prefs(m: dict, cur: dict | None = None) -> dict:
    """A prefs message → the session's prefs. Unknown or invalid fields keep their current value (partial updates)."""
    from . import voices
    p = dict(cur or PREF_DEFAULTS)
    if "voice" in m:
        v = m.get("voice")
        if v in (None, "", "default"):
            p["voice"] = None
        elif voices.allowed(v):
            p["voice"] = v
    if "voice_all" in m:
        p["voice_all"] = bool(m.get("voice_all"))
    if m.get("engine") in steering.ENGINES:   # Settings -> Voice: the computer's voice (default) or Steer TTS
        p["engine"] = m["engine"]
    if "steer_voice" in m:
        v = m.get("steer_voice")
        if v in (None, "", "default"):
            p["steer_voice"] = None
        elif voices.steer_allowed(v):
            p["steer_voice"] = v
    if "pack" in m:       # Settings "Use the recorded guide voice for story lines" (on by default)
        p["pack"] = m.get("pack") is not False
    if "rate" in m:
        try:
            r = float(m["rate"])
            if r == r:
                p["rate"] = round(max(steering.SPEED_RANGE[0], min(steering.SPEED_RANGE[1], r)), 2)
        except (TypeError, ValueError):
            pass
    if "expressiveness" in m:
        p["expressiveness"] = steering.clamp_expr(m["expressiveness"])
    if m.get("filter") in router_.FILTERS:
        p["filter"] = m["filter"]
    if m.get("level") in LEVELS:
        p["level"] = m["level"]
    if "volume" in m:     # master volume: 1 = 100% = the -14 LUFS target; up to 2 (+6 dB into the limiter)
        try:
            v = float(m["volume"])
            if v == v:
                p["volume"] = round(max(0.0, min(2.0, v)), 2)
        except (TypeError, ValueError):
            pass
    if m.get("listen") in LISTEN:
        p["listen"] = m["listen"]
    if "improve" in m:    # only an explicit true turns the turn log on
        p["improve"] = m.get("improve") is True
    return p


# Decisions whose text is ours on screen (never "nav", which carries the kid's own words)
SHOWN_TYPES = ("alert", "ask_confirm", "hud", "card", "toast")
PREP_MISSING_LINE ="That's okay. You can skip this one, or use something else you have."
CALLSIGNS = ["Comet", "Nova", "Rocket", "Orbit", "Moon Moth", "Crater Cat", "Star Hopper", "Sky Otter", "Pulsar",
             "Moonbeam", "Rover Fox", "Stardust"]   # frontend/src/story.js CALLSIGNS
_CACHE: dict = {}


def _lessons() -> list[tuple[str, str]]:
    if "lessons" not in _CACHE:
        try:
            from .academy import content
            _CACHE["lessons"] = [(l["id"], l["title"]) for l in content.course()["lessons"]]
        except Exception:  # noqa: BLE001
            _CACHE["lessons"] = []
    return _CACHE["lessons"]


def _sites() -> list[tuple[str, str]]:
    if "sites" not in _CACHE:
        try:
            from .mission import sim
            _CACHE["sites"] = [(s["id"], s["name"]) for s in sim.sites()]
        except Exception:  # noqa: BLE001
            _CACHE["sites"] = []
    return _CACHE["sites"]


def _words(t: str) -> list[str]:
    return [w for w in norm(t or "").split() if w]


def _p(x):
    return None if x is None else round(float(x), 3)


class Session:
    def __init__(self, sid: str, gaz=None, index=None, clock: Callable[[], float] = time.monotonic,
                 registry=None):
        self.id, self.gaz, self.index, self.clock = sid, gaz, index, clock
        self._registry = registry
        self.sockets: set[Any] = set()
        self.outbox: list[dict] = []     # every decision ever sent (tests read this; capped)
        self.history: deque = deque(maxlen=40)
        self.belief: dict = {
            "mode": "mission", "role": None, "mission_id": None, "state": None, "lesson": None,
            "floor": "none", "kid": {"open": False, "words": "", "start": None, "end": None, "command_complete": None,
                                     "device_directed": None, "emotion": None, "safety": None},
            "last_place": None, "playing": None, "referent": None,
        }
        self.pending: dict[str, dict] = {}     # unplayed say/play decisions by id
        self.held: list[tuple[float, list[dict]]] = []   # proactive bundles waiting for the floor (§3 rule 5)
        self.last_speech = -1e9
        self.last_nudge = -1e9
        self.warned: set = set()               # storm starts already warned about
        self.ev_seen = 0                       # mission events already handled
        self.recent_turns: deque = deque(maxlen=6)  # (norm text, ts)
        self.poll_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.dm = dmodel.attach(self)          # the learned Director (DIRECTOR_MODEL=off|shadow|on), None when off
        # Hands-free (turn_router.py): what we said lately (echo check + hard mute), the client's screen, the fallback.
        self.spoken = router_.Spoken(clock)
        self.screen: dict = {}                 # {screen, step_type, step_options, offer} from the client (ui:screen)
        self.step_since: float | None = None   # when the current screen / step opened
        self.last_unknown = -1e9
        self.routes: list[dict] = []           # every routed turn (tests and /api/session/{id}/routes read it; capped)
        # [P0] safety flags for the parent / teacher side (GET /api/safety/flags): kind, tags, screen, time; no words
        self.flags: list[dict] = []
        # The kid's Settings (docs/VOICES.md): sent by the client on every connect; in memory only, never persisted.
        self.prefs: dict = dict(PREF_DEFAULTS)
        # Settings "Help improve the voice guide" (prefs.improve, off by default): text-only turn log on this device.
        self.tlog = turnlog.SessionLog(self)
        self._tl: dict | None = None           # the turn being logged (begin in _turn, written when decided)

    # ---- plumbing --------------------------------------------------------------------------------------------------
    def registry(self):
        if self._registry is not None:
            return self._registry
        return director._sim()

    async def emit(self, ds: list[dict]):
        if self.dm is not None:
            self.dm.emitted(ds)
        for d in ds:
            if d["t"] in ("say", "play"):
                self.pending[d["id"]] = d
            if d["t"] == "say":
                self.spoken.said(d.get("text") or "")
                self._with_prefs(d)
            elif d["t"] in SHOWN_TYPES:   # round 8: our text put on screen is an echo reference too (Spoken.shown)
                for k in ("text", "ack", "line"):
                    if isinstance(d.get(k), str):
                        self.spoken.show(d[k])
            self.outbox.append(d)
            self.history.append({"out": d["t"], "id": d["id"], "text": d.get("text") or d.get("title"), "ts": self.clock()})
        del self.outbox[:-400]
        for ws in list(self.sockets):
            for d in ds:
                try:
                    await ws.send_json(d)
                except Exception:  # noqa: BLE001
                    self.sockets.discard(ws)
                    break

    # ---- Settings (docs/VOICES.md) ------------------------------------------------------------------------------------
    @property
    def level(self) -> str:
        """cadet | commander: for the mission sim and the Academy (the learning designer's), passed through only."""
        return self.prefs.get("level") or "cadet"

    def ptt_only(self) -> bool:
        return self.prefs.get("listen") == "ptt"

    def filter_thresholds(self) -> tuple[float, float]:
        return router_.thresholds(self.prefs.get("filter"))

    def _with_prefs(self, d: dict):
        """A say decision gets the kid's voice / rate / expressiveness on its style; /api/tts applies them."""
        persona = d.get("voice") or (d.get("style") or {}).get("voice") or "guide"
        base = d.get("style") or steering.style_for(persona, d.get("text") or "")
        new = steering.apply_prefs(base, base.get("voice") or persona, self.prefs)
        if new != base:           # default Settings leave the decision exactly as it was
            d["style"] = new

    def _pass_level(self):
        """Settings prefs.level onto the mission: it picks the difficulty band (sim.set_level)."""
        m = self._mission()
        if m is not None:
            with contextlib.suppress(Exception):
                from .mission import sim as _sim   # the level is the difficulty band (docs/LEARNING_DESIGN.md §6.5)
                if isinstance(m, _sim.Mission):
                    _sim.set_level(m, self.level)
                else:
                    m.level = self.level

    async def on_prefs(self, m: dict):
        self.prefs = clean_prefs(m, self.prefs)
        self._pass_level()
        self.history.append({"in": "prefs", "ts": self.clock()})
        for ws in list(self.sockets):    # an ack with what was applied (not a decision: never in the outbox)
            with contextlib.suppress(Exception):
                await ws.send_json({"t": "prefs", "applied": dict(self.prefs)})

    def _mission(self):
        reg, mid = self.registry(), self.belief["mission_id"]
        if reg is None or not mid:
            return None
        with contextlib.suppress(Exception):
            return reg.get(mid)
        return None

    def _state(self) -> dict | None:
        return director._as_state(self._mission())

    # ---- streams in --------------------------------------------------------------------------------------------------
    async def handle(self, m: dict):
        t = m.get("t") or m.get("type")      # the Settings UI sends {type: "prefs"}; everything else uses `t`
        if t == "prefs":
            await self.on_prefs(m)
            return
        # The learned Director steps on every event (turn ends and typed turns step in _turn, after Arc Tagger).
        if self.dm is not None and t != "typed" and not (t == "turn" and m.get("state") == "end"):
            with contextlib.suppress(Exception):
                self.dm.step(m)
        if t == "hello":
            await self.on_hello(m)
        elif t == "typed":
            await self.on_turn(str(m.get("text") or ""), source=m.get("source") or "typed", arc=m)
        elif t == "ui":
            await self.on_ui(m)
        elif t == "playback":
            await self.on_playback(m)
        elif t == "lesson":
            await self.on_lesson(m)
        elif t in ("words", "turn", "arc", "emotion"):
            await self.on_listen(m)

    async def on_hello(self, m: dict):
        b = self.belief
        b["mode"] = m.get("mode") or b["mode"]
        if "role" in m:
            b["role"] = m.get("role")
        if m.get("lesson_id"):
            b["lesson"] = {"lesson_id": m["lesson_id"], "step": 0, "status": "brief"}
        if m.get("mission_id") and m["mission_id"] != b["mission_id"]:
            b["mission_id"], b["state"], b["referent"] = m["mission_id"], None, None
            self.warned.clear()
            mi = self._mission()
            self.ev_seen = len(getattr(mi, "events", []) or [])
            b["state"] = self._state()
        if m.get("mode") == "cadet":
            b["mission_id"] = None
        if isinstance(m.get("prefs"), dict):      # Settings may ride on hello too
            self.prefs = clean_prefs(m["prefs"], self.prefs)
        self._pass_level()
        self.history.append({"in": "hello", "mode": b["mode"], "ts": self.clock()})

    async def on_ui(self, m: dict):
        ev = m.get("event")
        self.history.append({"in": "ui", "event": ev, "ts": self.clock()})
        if ev == "screen":         # the client's screen frame (hands-free routing context)
            new = {k: m.get(k) for k in ("screen", "step_type", "step_options", "offer", "lesson_id", "step") if k in m}
            key = lambda s: (s.get("screen"), s.get("lesson_id"), s.get("step"))  # noqa: E731
            if key(new) != key(self.screen):
                self.step_since = self.clock()      # when this step opened (turn_router.yesno_counts)
            self.screen = new
            return
        if ev == "lesson_result":  # the Academy's grade of a step answer (turn log outcome signal only)
            self.tlog.lesson(m.get("status"), m.get("step_type") or self.screen.get("step_type"))
            return
        if ev == "gesture":        # round 8: a hand gesture (feat/gestures-v2): the Director sees voice + gesture together
            self.last_gesture = (str(m.get("id") or m.get("target") or "")[:24], self.clock())
        self.tlog.ui(ev, m.get("id") or m.get("target"))
        if ev in ("tap_place", "tap_artifact") and m.get("id"):
            self.belief["last_place"] = m["id"]
        elif ev == "barge_in":     # the client accepted a barge-in (Space, or its echo check passed)
            await self.barge_in()
        elif ev == "kid_done":
            if self.belief["floor"] == "kid":
                await self.set_floor("none")
        elif ev == "mission_start":
            await self.on_hello({"mission_id": m.get("id"), "mode": "mission"})
        elif ev == "end_shift":
            await self.end_shift()
        elif ev == "lesson_answer":
            await self.on_lesson({"event": "answer", **m})

    async def on_playback(self, m: dict):
        kind, st, did = m.get("kind") or "guide", m.get("state"), m.get("id")
        if st == "start":
            self.belief["playing"] = {"kind": kind, "id": did, "text": (self.pending.get(did) or {}).get("text") or m.get("text"),
                                      "t": m.get("t"), "since": self.clock()}
            self.spoken.start(did, self.belief["playing"]["text"] or "")
            if self.belief["floor"] != "kid":
                self.belief["floor"] = kind
        else:  # end | interrupted
            self.spoken.end(did, more=bool(m.get("more")) and st == "end")   # `more`: the next line is queued
            if did:
                self.pending.pop(did, None)
            self.belief["playing"] = None
            self.last_speech = self.clock()
            if self.belief["floor"] in ("guide", "crew"):
                self.belief["floor"] = "none"
            await self.release_held()

    async def on_lesson(self, m: dict):
        """Lesson events from the Academy (owned by the Academy agent): track progress; pass `lesson` decisions on."""
        lesson = {k: m[k] for k in ("lesson_id", "step", "status", "score") if k in m}
        if lesson:
            self.belief["lesson"] = {**(self.belief["lesson"] or {}), **lesson}
        if m.get("status"):
            await self.emit([decision("lesson", P_NARRATION, **lesson)])

    async def on_listen(self, m: dict):
        """Posted by /ws/listen (server-side relay): Flux words + turns, Arc metadata, emotion."""
        k, t = self.belief["kid"], m.get("t")
        ptt = self.ptt_only()
        if t == "words":
            k["words"] = m.get("text") or ""
            if m.get("final"):     # the ear's extras ride on the final words: names linked to the screen's list (Arc
                # Transcriber Space: [{heard, entity, state, p, tag, kind}]), and the round-7 n-best fields when an ear has them
                k["ear"] = {x: m.get(x) for x in ("alts", "conf", "hot", "rescored", "names", "spoken") if m.get(x) is not None}
            if not ptt and k["open"] and self.belief["floor"] in ("guide", "crew") and self._is_barge(k["words"]):
                await self.barge_in()
        elif t == "turn":
            st = m.get("state")
            if ptt and st != "end":
                return            # push-to-talk only: the open mic never takes the floor (Arc metadata still kept)
            if st in ("start", "resumed"):
                k.update(open=True, start=self.clock(), end=None, words=m.get("text") or "")
                if st == "start":
                    k["device_directed"], k["act"], k["safety"] = None, None, None   # Arc's read is per turn: never carry the last one
                    k["ear"] = None
                if self.belief["floor"] == "none":
                    await self.set_floor("kid")
            elif st == "end":
                k.update(open=False, end=self.clock(), words=m.get("text") or k["words"])
                await self.on_turn(k["words"], source="listen")
        elif t == "arc":
            if m.get("command_complete") is not None:
                k["command_complete"] = m["command_complete"]
            if m.get("device_directed") is not None:
                k["device_directed"] = m["device_directed"]
            if m.get("act"):
                k["act"] = m["act"] if isinstance(m["act"], list) else [m["act"]]
            if isinstance(m.get("safety"), list):   # [P0] Arc Tagger's safety tags for this turn (safety.py)
                k["safety"] = m["safety"]
        elif t == "emotion" and m.get("label"):
            k["emotion"] = m["label"]

    def _is_barge(self, words: str) -> bool:
        """§3 rule 2, server side: ≥ 2 words, not an echo of what's playing, device-directed when Arc says so."""
        ws = _words(words)
        if len(ws) < 2 or router_.is_filler(words):
            return False
        playing = set(_words((self.belief["playing"] or {}).get("text") or ""))
        if playing and sum(w in playing for w in ws) / len(ws) >= ECHO_SHARE:
            return False
        if router_.echo_of(words, self.spoken.recent()):   # any of our last few lines, not only the one playing
            return False
        dd = self.belief["kid"]["device_directed"]
        return dd is None or float(dd) >= self.filter_thresholds()[0]

    async def set_floor(self, holder: str):
        if self.belief["floor"] != holder:
            self.belief["floor"] = holder
            await self.emit([decision("floor", P_BARGE, holder=holder)])
        if holder == "none":
            await self.release_held()

    async def barge_in(self):
        """The kid wins (§3 rule 2): cancel every unplayed decision below the guard; the kid holds the floor."""
        drop = [i for i, d in self.pending.items() if d["priority"] > P_GUARD]
        for i in drop:
            self.pending.pop(i, None)
        self.belief["kid"]["open"] = True
        out = [decision("cancel", P_BARGE, ids=drop)] if drop else []
        self.belief["floor"] = "kid"
        out.append(decision("floor", P_BARGE, holder="kid"))
        await self.emit(out)

    # ---- the kid's turn --------------------------------------------------------------------------------------------
    def _dup(self, text: str, source: str = "typed") -> bool:
        """The same turn arriving twice: from the ear relay and from the client (another source) within DEDUP_S, or
        from the same source within a second. A kid who says "end shift" again 4 s later means it."""
        q, now = norm(text), self.clock()
        fam = "listen" if source == "listen" else "client"
        if any(q == x and (now - ts < 1.0 or (f != fam and now - ts < DEDUP_S)) for x, ts, f in self.recent_turns):
            return True
        self.recent_turns.append((q, now, fam))
        return False

    def resolve_referent(self, text: str) -> str:
        """"Give it more" → "give shields more": "it"/"that" is the resource that changed most recently (telemetry
        deltas), mapped to the load that moves it. Only when the turn names nothing itself."""
        ref = self.belief.get("referent")
        if not ref or not PRONOUN.search(text) or NAMED.search(text):
            return text
        key = ref["key"]
        word = key.replace("_", " ") if key in LOADS else None
        if word is None:
            res = RESOURCES.get(key, key)
            asks_status = re.search(r"\b(how|what|is|status|check|left)\b", text, re.I)
            word = res.replace("_", " ") if asks_status else REF_LOAD.get(res)
        if not word:
            return text
        return PRONOUN.sub(word, text, count=1)

    def _alarm(self) -> bool:
        s = self.belief["state"] or {}
        return bool(s.get("alerts")) or bool(((s.get("env") or {}).get("storm") or {}).get("active"))

    async def on_turn(self, text: str, source: str = "typed", arc: dict | None = None):
        text = text.strip()
        if not text:
            return
        if arc and source in OPEN_MIC:
            # the client's copy of an ear turn carries the ear's Arc read for THIS turn (the relay's copy of the same
            # turn is a duplicate and dropped below); without it a stale read from an older turn would be used
            k = self.belief["kid"]
            if isinstance(arc.get("dd"), (int, float)):
                k["device_directed"] = float(arc["dd"])
            if "safety" in arc:
                k["safety"] = arc["safety"] if isinstance(arc.get("safety"), list) else None
        if self.ptt_only() and source in OPEN_MIC:
            # Settings listen="ptt": open-mic turns are not for us; only push-to-talk (source "ptt") and typed count.
            self.history.append({"route": "ignore", "reason": "ptt_only", "text": text, "ts": self.clock()})
            return
        if self._dup(text, source):
            return
        async with self.lock:
            await self._turn(text, source)

    # ---- hands-free routing (turn_router.py) ------------------------------------------------------------------------
    def screen_name(self) -> str:
        s = self.screen.get("screen")
        if s:
            return s
        b = self.belief
        if b["mode"] == "mission":
            return "cabin" if b["mission_id"] else "brief"
        return "library" if b["mode"] == "cadet" else "map"

    def open_step(self) -> dict | None:
        """The course step the client's screen frame has open (lesson_id + step), for grade.plausible."""
        lid, i = self.screen.get("lesson_id"), self.screen.get("step")
        if not lid or not isinstance(i, int) or self.screen.get("screen") not in ("lesson", "ride"):
            return None
        from .academy import content
        les = content.lesson(lid)
        steps = (les or {}).get("steps") or []
        return steps[i] if 0 <= i < len(steps) else None

    def ear_names(self) -> list[dict]:
        """The ear's names list for the screen the kid is on (names_list.py; /ws/listen sends it to Arc Transcriber
        Space on every change): <= 40 {"name", "kind", "aliases"}, most relevant first."""
        from .names_list import screen_names
        return screen_names({**self.screen, "screen": self.screen_name()}, self.open_step(), self.belief.get("last_place"))

    def hot_words(self) -> dict:
        """The ear's tiered hot lists for the screen the kid is on (round 7, hotlist.py; /ws/listen sends them to the
        Arc ear): {"step": strongest boost, "screen": lighter, "v": data version}."""
        from .hotlist import hot_lists
        return hot_lists({**self.screen, "screen": self.screen_name()}, self.open_step())

    def route_ctx(self, source: str) -> router_.Ctx:
        k = self.belief["kid"]
        heard = source in ("listen", "voice", "ptt")
        # When the kid's turn started (the ear's StartOfTurn): echo can only begin while we speak.
        now = self.clock()
        t0 = k["start"] if k.get("start") is not None and now - k["start"] < 20 else now
        dd_min, dd_strong = self.filter_thresholds()
        return router_.Ctx(
            dd_min=dd_min, dd_strong=dd_strong,
            screen=self.screen_name(), step_type=self.screen.get("step_type"),
            step_options=list(self.screen.get("step_options") or []), offer=self.screen.get("offer"),
            step=self.open_step(),
            step_age=(t0 - self.step_since) if self.step_since is not None else None,
            source=source if heard else "typed",
            dd=k.get("device_directed") if heard else None,
            speaking=heard and self.spoken.speaking(t0), playing=heard and self.spoken.playing_at(t0),
            on_air=heard and self.spoken.on_air(t0), recent=self.spoken.fresh(t0) if heard else [],
            older=self.spoken.older(t0) if heard else [],
            shown=self.spoken.shown(t0) if heard else [],
            lessons=_lessons(), sites=_sites(), callsigns=CALLSIGNS)

    async def _note(self, rt: dict, text: str, safety: bool = False):
        # [P0] a safety turn (Arc's tags or the word list): the logs keep that it happened, never the words, and the
        # client gets the decision without them (it shows nothing for it either way)
        safety = safety or rt.get("reason") == "safety"
        shown = "[safety]" if safety else text
        rec = {"text": shown, **rt, "screen": self.screen_name(), "ts": self.clock()}
        self.routes.append(rec)
        del self.routes[:-400]
        self.history.append({"route": rt["outcome"], "reason": rt.get("reason"), "text": shown, "ts": self.clock()})
        if self.screen:   # a hands-free client: tell it what we heard (the mic chip shows "didn't catch that")
            await self.emit([decision("heard", P_ANSWER, outcome=rt["outcome"], reason=rt.get("reason"), intent=rt.get("intent"),
                                      notice=bool(rt.get("notice")) or None, text="" if safety else text,
                                      safety=True if safety else None)])

    def _end_event(self, text: str, source: str, rt: dict | None = None) -> dict:
        ev = {"t": "turn", "state": "end", "text": text} if source == "listen" else \
            {"t": "typed", "text": text, "source": source}
        if rt:      # the router's decision rides on the step (features: rt_*, rw_*)
            ev["route"] = {"outcome": rt.get("outcome"), "reason": rt.get("reason"), "intent": rt.get("intent")}
        return ev

    async def _turn(self, text: str, source: str):
        k = self.belief["kid"]
        ctx_r = self.route_ctx(source)
        # [P0] safety first (safety.py): Arc's tags, then the word list. A crisis or grooming cue gets one gentle line
        # and a flag for the grown-ups; a rude / toxic turn is ignored (never graded, never a question).
        tags = k.get("safety") if source in OPEN_MIC or source == "ptt" else None
        if tags is None:   # no read from the ear: ask Arc Tagger on the words (~20 ms on the local model server)
            tags = await safety_.tagger_read(text)
        sf = safety_.classify(text, tags)
        ctx_r.unsafe = sf["mask"]
        if sf["care"]:
            self.flags.append({"kind": "care", "tags": [t for t in sf["tags"] if t.startswith(safety_.CARE_TAGS)],
                               "screen": self.screen_name(), "ts": self.clock()})   # never the words themselves
            del self.flags[:-50]
            k["open"] = False
            await self._note({"outcome": "care", "reason": "safety"}, text, safety=True)
            await self.emit([decision("say", P_ANSWER, text=safety_.CARE_LINE, voice="capcom")])
            return
        rt = router_.route(text, ctx_r, act=k.get("act"))
        # the opt-in turn log keeps no words of a turn Arc marked private or unsafe: it is stored as private (the
        # guard path), so a false PII flag costs only the text in the log, never the turn on screen
        self._tl = self.tlog.begin(text, source, ctx_r, rt, k)
        if self._tl is not None and (sf["pii"] or sf["mask"]):
            self._tl["_guard"] = True
        try:
            await self._routed(text, source, ctx_r, rt)
        finally:
            if self._tl is not None:
                self.tlog.finish(self._tl, self._tl.pop("_dir", None), guard=bool(self._tl.pop("_guard", False)))
            self._tl = None

    def _log_dir(self, **d):
        if self._tl is not None:
            self._tl["_dir"] = {k_: v for k_, v in d.items() if v is not None}

    async def _routed(self, text: str, source: str, ctx_r: router_.Ctx, rt: dict):
        b, k = self.belief, self.belief["kid"]
        out = None
        if rt["outcome"] in ("ignore", "navigate", "answer") and self.dm is not None:
            # The learned Director steps on every routed turn end (the same stream it was trained on); on a lesson
            # step's answer it may silence the turn (room chatter: "oh, it's", "okay") when it is sure enough
            # (runtime.answer_policy; off unless the shipped weights carry a fitted threshold).
            with contextlib.suppress(Exception):
                out = self.dm.step(self._end_event(text, source, rt), {"available": False})
            nv = self._model_nav(out, rt)
            if nv is not None:
                rt = nv
            elif rt["outcome"] == "answer" and out is not None and self.dm.decide_answer(out):
                rt = {"outcome": "ignore", "reason": "model_chatter"}
                dmodel.STATS["model_overrides"] += 1
                if self._tl is not None:
                    self._tl["router"]["model"] = "ignore"
        ma, mp = self.dm.model_act(out) if (self.dm is not None and out is not None) else (None, None)
        if rt["outcome"] == "ignore":
            # Stay silent. Never cancel what we are saying for something we didn't mean to hear (our own echo).
            if self.dm is not None:
                with contextlib.suppress(Exception):
                    self.dm.turn_result({"action": "none", "source": "router+" + rt["reason"]})
            self._log_dir(rules="ignore", model=ma, p=_p(mp), final="ignore")
            k["open"] = False
            if b["floor"] == "kid":
                b["floor"] = "none"
            await self._note(rt, text)
            return
        await self._note(rt, text)
        if rt["outcome"] in ("navigate", "answer"):
            if self.dm is not None:
                with contextlib.suppress(Exception):
                    self.dm.turn_result({"action": "navigate" if rt["outcome"] == "navigate" else "answer_step",
                                         "source": "router+" + str(rt.get("intent") or rt["outcome"])})
            fin = "navigate" if rt["outcome"] == "navigate" else "answer"
            self._log_dir(rules=fin, model=ma, p=_p(mp), final=fin)
            # The client owns the screens: it runs the navigation / grades the step answer (one decision, visual).
            k["open"] = False
            if b["floor"] == "kid":
                b["floor"] = "none"
            # a11y nav with a canonical command (the voice bar): the client runs `text`, so send the canonical form
            if rt.get("intent") == "prep_help" and rt.get("arg") == "missing":   # round 8: a gentle way out
                await self.emit([decision("say", P_ANSWER, text=PREP_MISSING_LINE, voice="capcom")])
            run_text = rt["arg"] if rt.get("intent") == "a11y" and rt.get("arg") else text
            await self.emit([decision("nav", P_ANSWER, intent=rt.get("intent") or "answer", arg=rt.get("arg"),
                                      text=run_text, heard=text if run_text != text else None)])
            return
        await self._direct_turn(text, source, rt, ctx_r)

    def _model_nav(self, out, rt: dict) -> dict | None:
        """Round 7, `on` mode: the model navigates a turn the router did not (runtime.nav_policy: the `nav` head, a
        fitted threshold, intents it can run without an argument). -> a router-shaped navigate decision, or None."""
        if self.dm is None or out is None or rt.get("outcome") == "navigate":
            return None
        nv = None
        with contextlib.suppress(Exception):
            nv = self.dm.decide_nav(out, self.screen.get("offer"))
        if not nv:
            return None
        dmodel.STATS["model_overrides"] += 1
        if self._tl is not None:
            self._tl["router"]["model"] = "navigate:" + nv
        arg = self.screen.get("offer") if nv in ("accept_offer", "decline_offer") else None
        return {"outcome": "navigate", "reason": "model_nav", "intent": nv, "arg": arg}

    async def _direct_turn(self, text: str, source: str, rt: dict, ctx_r: router_.Ctx):
        b, k = self.belief, self.belief["kid"]
        self.history.append({"in": source, "text": text, "ts": self.clock()})
        # §3 rule 3: a newer turn cancels older, unplayed decisions.
        old = [i for i, d in self.pending.items() if d["priority"] > P_GUARD]
        for i in old:
            self.pending.pop(i, None)
        pre = [decision("cancel", P_BARGE, ids=old)] if old else []
        if b["floor"] == "kid":
            b["floor"] = "none"
        k["open"] = False

        resolved = self.resolve_referent(text) if b["mission_id"] else text
        read = summarize(await models_client.tag(resolved, "assistant"))
        names = (k.get("ear") or {}).get("names") if source in OPEN_MIC or source == "ptt" else None
        if names:   # the ear's names for THIS turn: director._link routes on names[i].entity, not on the raw words
            read = {**read, "ear_names": names}
        out = None
        if self.dm is not None:
            with contextlib.suppress(Exception):
                out = self.dm.step(self._end_event(text, source, rt), read)
        nv = self._model_nav(out, rt)
        if nv is not None:          # round 7: the model's navigation of a question / order turn (fitted, guarded)
            with contextlib.suppress(Exception):
                self.dm.turn_result({"action": "navigate", "source": "director_model+" + nv["intent"]})
            await self.emit(pre + [decision("nav", P_ANSWER, intent=nv["intent"], arg=nv["arg"], text=text)])
            return
        emotion = k.get("emotion")
        ctx: dict = {"session": self.id}   # template rotation in the local brain is deterministic per session
        ctx["level"] = self.level          # Settings: cadet | commander (passed through; docs/VOICES.md)
        if b["last_place"]:
            ctx["last_place"] = b["last_place"]
        if emotion:
            ctx["emotion"] = emotion
        if b["mission_id"] and b["mode"] == "mission":
            ctx["mission"] = {"id": b["mission_id"], "role": b["role"], "level": self.level}
        if k.get("device_directed") is not None and source == "listen":
            ctx["device_directed"] = k["device_directed"]
        override = None
        guard = bool(director.NAME_GIVEN.search(norm(resolved)))
        with contextlib.suppress(Exception):
            guard = guard or bool(self.gaz is not None and director._hard_pii(read, self.gaz))
        if self.dm is not None and out is not None:
            override = self.dm.decide_turn(out, resolved, guard)
        if override and override["act"] == "command" and not (b["mission_id"] and b["mode"] == "mission"):
            override = None
        if override and override["act"] == "ignore":
            r = {"action": "none", "say": "", "source": "director_model", "decisions": []}
        elif override and override["act"] == "ask_clarify":
            opts = override.get("clarify") or []
            q = did_you_mean(opts) if len(opts) == 2 else director.SAY_AGAIN
            r = {"action": "ask", "say": q, "source": "director_model", "ask": {"question": q, "options": opts}}
            r["decisions"] = director.decisions_for(r, text, ctx)
        else:
            if override and override["act"] == "command":
                ctx["commands"] = [override["command"]]
            r = await director.direct(resolved, read, self.gaz, self.index, ctx)
        if override:
            dmodel.STATS["model_overrides"] += 1
        r = self._gate_fallback(r, text, ctx_r, k.get("act"))
        if self.dm is not None:
            self.dm.turn_result(r)
        if self._tl is not None:
            from .director_model import features as _fx
            ma, mp = self.dm.model_act(out) if (self.dm is not None and out is not None) else (None, None)
            rc = _fx.rules_command(r) if not override else None
            self._log_dir(rules=None if override else _fx.rules_act(r), rules_cmd=(rc or {}).get("type"),
                          model=ma, p=_p(mp), override=(override or {}).get("act"), final=_fx.rules_act(r),
                          source=r.get("source"),
                          confirm=bool(r.get("needs_confirm")) or any(d.get("t") == "ask_confirm"
                                                                       for d in r.get("decisions") or []))
            self._tl["_guard"] = guard or r.get("action") == "guard"
        if r.get("action") == "none":
            await self.emit(pre)
            return
        if self.screen and self.screen_name() != "cabin" and rt["outcome"] == "question":
            # A hands-free client outside the cabin renders the explorer answer itself (artifacts, tours, crew audio).
            slim = {k_: v for k_, v in r.items() if k_ not in ("decisions", "readout")}
            await self.emit(pre + [decision("answer", P_ANSWER, r=slim, asked=text)])
            return
        ds = list(r.get("decisions") or [])
        if r.get("place"):
            b["last_place"] = r["place"]
        if r.get("state"):
            self._observe_state(r["state"])
        if resolved != text:
            for d in ds:
                if d["t"] == "card":
                    d["resolved"] = resolved
        # Urgency: upset during an alarm → shorter, calmer lines.
        if (emotion or "").lower() in ALARM_EMOTIONS and self._alarm():
            for d in ds:
                if d["t"] == "say":
                    d["text"] = "Okay, we've got this. " + capcom.short(d["text"])
                    d["style"] = steering.style_for(d.get("voice") or "capcom", d["text"], emotion=emotion,
                                                    situation=(d.get("style") or {}).get("situation") or "storm_alert")
        # Multi-stream: a storm starting within the next shift → one warning alongside the answer.
        if b["mission_id"] and r.get("action") in ("command", "status"):
            ds += self._storm_lookahead()
        evs = await self._new_events(spoken=False) if b["mission_id"] else []
        await self.emit(pre + ds)
        if evs:   # sim events this turn caused (an "end shift" said aloud): proactive, under the floor rules
            await self.offer(evs)

    def _gate_fallback(self, r: dict, text: str, ctx_r: router_.Ctx, act) -> dict:
        """The brain's "I don't know that one yet" (and its "Did you mean…?" guesses) are spoken for a heard turn only
        when it was clearly a device-directed question, and the fallback at most once per UNKNOWN_EVERY_S."""
        heard = ctx_r.source in ("listen", "voice")   # a Space (ptt) or typed question may always get the fallback
        brain = (r.get("readout") or {}).get("brain") or {}
        unknown = r.get("source") == "none" or (r.get("say") or "").startswith(director.UNKNOWN)
        guess = r.get("action") == "ask" and brain.get("status") in ("ask", "unknown")
        if not (unknown or guess):
            return r
        none = {**r, "action": "none", "say": "", "decisions": [], "source": "router+quiet"}
        if heard and not router_.clear_question(text, ctx_r.dd, act, ctx_r.dd_strong):
            return none
        if unknown:
            now = self.clock()
            if heard and now - self.last_unknown < router_.UNKNOWN_EVERY_S:
                return none
            self.last_unknown = now
        return r

    # ---- mission: polling, deltas, proactive ------------------------------------------------------------------------
    def _observe_state(self, s: dict):
        """Track which resource/load changed most recently (the referent of "it")."""
        prev, self.belief["state"] = self.belief["state"], s
        if not prev:
            return
        best, mag = None, 0.0
        for k in RESOURCES:
            a, c = (prev.get("resources") or {}).get(k), (s.get("resources") or {}).get(k)
            if a is not None and c is not None:
                d = abs(float(c) - float(a)) * (10 if k == "dose_msv" else 1)
                if d > mag + 1e-9 and d >= 0.5:
                    best, mag = k, d
        for k in LOADS:
            a, c = (prev.get("loads") or {}).get(k), (s.get("loads") or {}).get(k)
            if a is not None and c is not None and abs(c - a) >= 1 and abs(c - a) * 2 > mag:
                best, mag = k, abs(c - a) * 2   # a load the kid moved is the most salient change
        if best:
            self.belief["referent"] = {"key": best, "ts": self.clock(), "delta": mag}

    def _storm_lookahead(self) -> list[dict]:
        m, s = self._mission(), self.belief["state"] or {}
        t = s.get("mission_time_h")
        if m is None or t is None:
            return []
        for st in getattr(m, "storms", []) or []:
            if t < st.start_h <= t + 6 and st.start_h not in self.warned:
                self.warned.add(st.start_h)
                sev = (st.event or {}).get("severity") or 2
                return [decision("alert", P_CRITICAL if sev >= 3 else P_NARRATION, level="warn",
                                 text=f"Solar storm coming in the next shift (severity {sev} of 3).", source="DONKI")]
        return []

    async def poll(self):
        """One poll step: state deltas + new sim events → proactive decisions. Run every POLL_S by the socket."""
        s = self._state()
        if s is None:
            return
        self._observe_state(s)
        if self.dm is not None:
            with contextlib.suppress(Exception):
                self.dm.step({"t": "poll"})
        ds = await self._new_events(spoken=True)
        if ds:
            await self.offer(ds)
        await self.release_held()

    async def _new_events(self, spoken: bool) -> list[dict]:
        m = self._mission()
        evs = list(getattr(m, "events", []) or [])
        new, self.ev_seen = evs[self.ev_seen:], len(evs)
        new = [e for e in new if e.get("kind") != "beat"] + [e for e in new if e.get("kind") == "beat"]   # news first
        out: list[dict] = []
        for e in new:
            out += self.proactive(e)
        return out

    def _emotion(self) -> str | None:
        return self.belief["kid"].get("emotion") or None

    def proactive(self, e: dict) -> list[dict]:
        """One sim event → decisions. Text mirrors the sim's own line; CAPCOM speaks short."""
        kind, s = e.get("kind"), self.belief["state"] or {}
        calm = (self.belief["kid"].get("emotion") or "").lower() in ALARM_EMOTIONS
        src = (e.get("source") or {}).get("title") if isinstance(e.get("source"), dict) else None
        if kind in ("solar_storm", "storm_warning"):
            st = self._storm_of(e)
            sev = int((st.event or {}).get("severity") or 2) if st else \
                (((s.get("env") or {}).get("storm") or {}).get("severity") or 2)
            warning = kind == "storm_warning" or bool(st and e.get("t_h", 0) < st.start_h)
            crit = sev >= 3 and not warning
            pri = P_CRITICAL if crit else P_NARRATION
            if kind == "solar_storm" and e.get("sep") is False:   # few particles reach the Moon: a near miss
                line = "Storm at Earth, but few particles here. Keep working."
            elif warning and e.get("confidence") == "possible":
                line = "A storm is possible. Shelter now, or wait and watch?"
            else:
                line = ("Storm coming. Shelter now, or wait?" if warning else
                        "Storm's here! Shelter, and shields up.")
            if calm:
                line = "Okay, we've got this. " + capcom.short(line)
            al = decision("alert", pri, level="critical" if crit else "warn", text=e.get("text") or line, source=src)
            say = decision("say", pri, text=line, voice="capcom", proactive=True,
                           situation="storm_warning" if warning else "storm_alert", emotion=self._emotion())
            card = decision("card", pri, title="CAPCOM", body=e.get("text") or line, chips=["Solar storm", src or "NASA"],
                            actions=[{"label": "Go to shelter", "send": {"t": "typed", "text": "go to the shelter"}},
                                     {"label": "Set shields to 40", "send": {"t": "typed", "text": "shields to 40"}}],
                            hint=True)
            if st:
                self.warned.add(st.start_h)   # the sim warned already: no second lookahead alert
            return [al, card, say]
        if kind == "beat" and e.get("beat") in SPOKEN_BEATS:
            # a story beat (gameplay.py) with no sim event line of its own: CAPCOM says it once, under the floor rules
            return [decision("say", P_NARRATION, text=e.get("text") or "", voice="capcom", proactive=True,
                             situation="all_clear" if e.get("beat") in ("ice_return", "complete") else None,
                             emotion=self._emotion())]
        if kind == "shelter_limit":
            return [decision("alert", P_NARRATION, level="info", text=e.get("text") or "Crew out of the shelter."),
                    decision("say", P_NARRATION, text="A day in the shelter is the limit. Crew out to rest.",
                             voice="capcom", proactive=True, situation="all_clear", emotion=self._emotion())]
        if kind == "comm_open":
            return [decision("alert", P_NARRATION, level="info", text=e.get("text") or "Comm window open."),
                    decision("say", P_NARRATION, text="Comm window open. Houston can hear us.", voice="capcom",
                             proactive=True, situation="comm_open", emotion=self._emotion())]
        if kind == "storm_end":
            return [decision("alert", P_NARRATION, level="info", text=e.get("text") or "The storm is over.", source=src),
                    decision("say", P_NARRATION, text="Storm's over. All clear, Commander.", voice="capcom",
                             proactive=True, situation="all_clear", emotion=self._emotion())]
        if kind == "dose_alert":
            return [decision("alert", P_NARRATION, level="warn", text=e.get("text") or "Radiation is high.", source=src)]
        if kind in ("low_power",) or (kind == "sunset" and ((s.get("resources") or {}).get("power_pct") or 100) < 35):
            return [decision("alert", P_NARRATION, level="warn", text=e.get("text") or "Battery is low."),
                    decision("say", P_NARRATION, text="Dark, and the battery's low. Night mode?",
                             voice="capcom", proactive=True, situation="night_low_power", emotion=self._emotion()),
                    decision("card", P_NUDGE, title="Coach", nudge=True,
                             body="Night mode saves power. Keep heaters and life support on.",
                             actions=[{"label": "Night mode on", "send": {"t": "typed", "text": "night mode on"}}])]
        if kind in ("failure", "mission_complete"):
            return [decision("alert", P_CRITICAL if kind == "failure" else P_NARRATION,
                             level="critical" if kind == "failure" else "info", text=e.get("text") or kind),
                    decision("say", P_CRITICAL if kind == "failure" else P_NARRATION, text=e.get("text") or "",
                             voice="capcom", proactive=True, situation=kind, emotion=self._emotion())]
        return []

    def _storm_of(self, e: dict):
        """The sim storm an event belongs to (the 6 h warning and the start share its real date)."""
        for st in getattr(self._mission(), "storms", []) or []:
            if (st.event or {}).get("date") == e.get("real_date"):
                return st
        return None

    async def offer(self, ds: list[dict]):
        """Proactive decisions under §3 rules 3, 5, 7: never over the kid; non-critical only when the floor is none;
        a critical alert takes the floor after the current sentence (the client finishes it); nudges rate-limited."""
        now = self.clock()
        nudge = [d for d in ds if d["priority"] >= P_NUDGE]
        rest = [d for d in ds if d["priority"] < P_NUDGE]
        if nudge:
            if now - self.last_speech >= NUDGE_QUIET_S and now - self.last_nudge >= NUDGE_EVERY_S and \
                    self.belief["floor"] == "none" and not self.pending:
                self.last_nudge = now
                rest += nudge
        if not rest:
            return
        floor = self.belief["floor"]
        crit = any(d["priority"] <= P_CRITICAL for d in rest)
        if floor == "kid" or (floor != "none" and not crit):
            self.held.append((now, rest))
            return
        await self.emit(rest)

    async def release_held(self):
        """The floor came back to none: send what was held, oldest first, dropping stale news."""
        if not self.held or self.belief["floor"] != "none":
            return
        now = self.clock()
        held, self.held = self.held, []
        ds = [d for ts, bundle in held if now - ts <= HOLD_MAX_S for d in bundle]
        ds = [d for d in ds if not self._overtaken(d)]
        if ds:
            await self.emit(ds)

    def _overtaken(self, d: dict) -> bool:
        """A held storm decision the live mission clock has overtaken (no storm and no warning now): drop it, or CAPCOM
        says "Storm coming. Shelter now?" after the storm has passed (docs/GAMEPLAY.md)."""
        m = self._mission()
        if m is None or d.get("t") not in ("say", "card", "alert"):
            return False
        style = (d.get("style") or {}).get("situation") or d.get("situation")
        storm_d = style in ("storm_warning", "storm_alert") or "Solar storm" in (d.get("chips") or []) or \
            (d.get("t") == "alert" and any(w in str(d.get("text", "")).lower() for w in ("storm", "particle")) and
             d.get("level") in ("warn", "critical"))
        if not storm_d:
            return False
        try:
            from .mission import sim
            return not sim.env_at(m, m.t_h)["storm"] and sim._warning(m) is None
        except Exception:  # noqa: BLE001
            return False

    async def end_shift(self):
        """The End shift button through the session: the sim advances, then HUD + shift line + events."""
        reg, mid = self.registry(), self.belief["mission_id"]
        if reg is None or not mid or not hasattr(reg, "advance"):
            return
        async with self.lock:
            r = reg.advance(mid, 1)
            self._observe_state(r["state"])
            out = [decision("hud", P_ANSWER, state=r["state"])]
            evs = await self._new_events(spoken=True)
            text = r.get("say") or ""
            say = decision("say", P_NARRATION, text=text, voice="capcom", situation=steering.situation_for(
                {"action": "status", "state": r["state"]}), emotion=self._emotion()) if text else None
            card = decision("card", P_NARRATION, title="CAPCOM", body=text, chips=[])
            out += [card] + ([say] if say else [])
            out += self._storm_lookahead()
        await self.emit(out)
        if evs:
            await self.offer(evs)


SESSIONS: dict[str, Session] = {}
MAX_SESSIONS = 200
CTX: dict = {}   # gaz, index (set by main.py's lifespan through `bind`)


def bind(gaz, index):
    CTX["gaz"], CTX["index"] = gaz, index


def get(sid: str | None, create: bool = True) -> Session | None:
    sid = re.sub(r"[^A-Za-z0-9_.-]", "", str(sid or ""))[:64]
    if not sid:
        return None
    s = SESSIONS.get(sid)
    if s is None and create:
        if len(SESSIONS) >= MAX_SESSIONS:
            SESSIONS.pop(next(iter(SESSIONS)))
        s = SESSIONS[sid] = Session(sid, CTX.get("gaz"), CTX.get("index"))
    if s is not None and s.gaz is None:
        if not CTX:
            with contextlib.suppress(Exception):
                from .main import S as main_state   # lazy: main imports this module
                bind(main_state.get("gaz"), main_state.get("index"))
        s.gaz, s.index = CTX.get("gaz"), CTX.get("index")
    return s


async def post(sid: str | None, m: dict):
    """/ws/listen → session: words / turn / arc / emotion (fails open: listen never breaks on a session error)."""
    s = get(sid, create=True) if sid else None
    if s is None:
        return
    if m.get("t") == "turn" and m.get("state") == "end":   # the Director may take a while: never stall the relay
        task = asyncio.create_task(s.handle(m))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
        return
    with contextlib.suppress(Exception):
        await s.handle(m)


_TASKS: set = set()


@router.websocket("/ws/session")
async def session_ws(ws: WebSocket):
    await ws.accept()
    s: Session | None = None
    poller: asyncio.Task | None = None

    async def poll_loop(sess: Session):
        while True:
            await asyncio.sleep(POLL_S)
            with contextlib.suppress(Exception):
                await sess.poll()

    try:
        while True:
            m = await ws.receive_json()
            if not isinstance(m, dict):
                continue
            if s is None:
                if m.get("t") != "hello":
                    await ws.send_json({"t": "error", "message": "send hello first"})
                    continue
                s = get(m.get("session") or m.get("id"))
                if s is None:
                    await ws.send_json({"t": "error", "message": "hello needs a session id"})
                    continue
                s.sockets.add(ws)
                poller = asyncio.create_task(poll_loop(s))
                await ws.send_json({"t": "ready", "session": s.id})
            await s.handle(m)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        if poller:
            poller.cancel()
        if s is not None:
            s.sockets.discard(ws)
