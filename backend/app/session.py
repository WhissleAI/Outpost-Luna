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

from . import director, models_client, steering
from . import turn_router as router_
from .director_model import runtime as dmodel
from .director import P_ANSWER, P_BARGE, P_CRITICAL, P_GUARD, P_NARRATION, P_NUDGE, decision
from .gazetteer import norm
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
                                     "device_directed": None, "emotion": None},
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
        self.last_unknown = -1e9
        self.routes: list[dict] = []           # every routed turn (tests and /api/session/{id}/routes read it; capped)

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
        t = m.get("t")
        # The learned Director steps on every event (turn ends and typed turns step in _turn, after Arc Tagger).
        if self.dm is not None and t != "typed" and not (t == "turn" and m.get("state") == "end"):
            with contextlib.suppress(Exception):
                self.dm.step(m)
        if t == "hello":
            await self.on_hello(m)
        elif t == "typed":
            await self.on_turn(str(m.get("text") or ""), source=m.get("source") or "typed")
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
        self.history.append({"in": "hello", "mode": b["mode"], "ts": self.clock()})

    async def on_ui(self, m: dict):
        ev = m.get("event")
        self.history.append({"in": "ui", "event": ev, "ts": self.clock()})
        if ev == "screen":         # the client's screen frame (hands-free routing context)
            self.screen = {k: m.get(k) for k in ("screen", "step_type", "step_options", "offer") if k in m}
            return
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
            self.spoken.end(did)
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
        if t == "words":
            k["words"] = m.get("text") or ""
            if k["open"] and self.belief["floor"] in ("guide", "crew") and self._is_barge(k["words"]):
                await self.barge_in()
        elif t == "turn":
            st = m.get("state")
            if st in ("start", "resumed"):
                k.update(open=True, start=self.clock(), end=None, words=m.get("text") or "")
                if st == "start":
                    k["device_directed"], k["act"] = None, None   # Arc's read is per turn: never carry the last one
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
        return dd is None or float(dd) >= 0.5

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

    async def on_turn(self, text: str, source: str = "typed"):
        text = text.strip()
        if not text or self._dup(text, source):
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

    def route_ctx(self, source: str) -> router_.Ctx:
        k = self.belief["kid"]
        heard = source in ("listen", "voice", "ptt")
        # When the kid's turn started (the ear's StartOfTurn): echo can only begin while we speak.
        now = self.clock()
        t0 = k["start"] if k.get("start") is not None and now - k["start"] < 20 else now
        return router_.Ctx(
            screen=self.screen_name(), step_type=self.screen.get("step_type"),
            step_options=list(self.screen.get("step_options") or []), offer=self.screen.get("offer"),
            source=source if heard else "typed",
            dd=k.get("device_directed") if heard else None,
            speaking=heard and self.spoken.speaking(t0), playing=heard and self.spoken.playing_at(t0), recent=self.spoken.fresh(t0) if heard else [],
            older=self.spoken.older(t0) if heard else [],
            lessons=_lessons(), sites=_sites(), callsigns=CALLSIGNS)

    async def _note(self, rt: dict, text: str):
        rec = {"text": text, **rt, "screen": self.screen_name(), "ts": self.clock()}
        self.routes.append(rec)
        del self.routes[:-200]
        self.history.append({"route": rt["outcome"], "reason": rt.get("reason"), "text": text, "ts": self.clock()})
        if self.screen:   # a hands-free client: tell it what we heard (the mic chip shows "didn't catch that")
            await self.emit([decision("heard", P_ANSWER, outcome=rt["outcome"], reason=rt.get("reason"),
                                      notice=bool(rt.get("notice")) or None, text=text)])

    async def _turn(self, text: str, source: str):
        b, k = self.belief, self.belief["kid"]
        ctx_r = self.route_ctx(source)
        rt = router_.route(text, ctx_r, act=k.get("act"))
        if rt["outcome"] == "ignore":
            # Stay silent. Never cancel what we are saying for something we didn't mean to hear (our own echo).
            if self.dm is not None:
                with contextlib.suppress(Exception):
                    self.dm.step({"t": "turn", "state": "end", "text": text} if source == "listen" else
                                 {"t": "typed", "text": text, "source": source}, {"available": False})
                    self.dm.turn_result({"action": "none", "source": "router+" + rt["reason"]})
            k["open"] = False
            if b["floor"] == "kid":
                b["floor"] = "none"
            await self._note(rt, text)
            return
        await self._note(rt, text)
        if rt["outcome"] in ("navigate", "answer"):
            # The client owns the screens: it runs the navigation / grades the step answer (one decision, visual).
            k["open"] = False
            if b["floor"] == "kid":
                b["floor"] = "none"
            # a11y nav with a canonical command (the voice bar): the client runs `text`, so send the canonical form
            run_text = rt["arg"] if rt.get("intent") == "a11y" and rt.get("arg") else text
            await self.emit([decision("nav", P_ANSWER, intent=rt.get("intent") or "answer", arg=rt.get("arg"),
                                      text=run_text, heard=text if run_text != text else None)])
            return
        await self._direct_turn(text, source, rt, ctx_r)

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
        out = None
        if self.dm is not None:
            ev = {"t": "turn", "state": "end", "text": text} if source == "listen" else \
                {"t": "typed", "text": text, "source": source}
            with contextlib.suppress(Exception):
                out = self.dm.step(ev, read)
        emotion = k.get("emotion")
        ctx: dict = {"session": self.id}   # template rotation in the local brain is deterministic per session
        if b["last_place"]:
            ctx["last_place"] = b["last_place"]
        if emotion:
            ctx["emotion"] = emotion
        if b["mission_id"] and b["mode"] == "mission":
            ctx["mission"] = {"id": b["mission_id"], "role": b["role"]}
        if k.get("device_directed") is not None and source == "listen":
            ctx["device_directed"] = k["device_directed"]
        override = None
        if self.dm is not None and out is not None:
            guard = bool(self.gaz is not None and director._hard_pii(read, self.gaz)) or bool(
                director.NAME_GIVEN.search(norm(resolved)))
            override = self.dm.decide_turn(out, resolved, guard)
        if override and override["act"] == "command" and not (b["mission_id"] and b["mode"] == "mission"):
            override = None
        if override and override["act"] == "ignore":
            r = {"action": "none", "say": "", "source": "director_model", "decisions": []}
        elif override and override["act"] == "ask_clarify":
            opts = override.get("clarify") or []
            q = f"Did you mean {opts[0]} or {opts[1]}?" if len(opts) == 2 else director.SAY_AGAIN
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
        if heard and not router_.clear_question(text, ctx_r.dd, act):
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
        if kind == "solar_storm":
            st = self._storm_of(e)
            sev = int((st.event or {}).get("severity") or 2) if st else \
                (((s.get("env") or {}).get("storm") or {}).get("severity") or 2)
            warning = bool(st and e.get("t_h", 0) < st.start_h)
            crit = sev >= 3 and not warning
            pri = P_CRITICAL if crit else P_NARRATION
            line = ("Storm coming. Shields up, or get to the shelter." if warning else
                    "Storm's here! Shelter, and shields up.")
            if calm:
                line = "Okay, we've got this. " + capcom.short(line)
            al = decision("alert", pri, level="critical" if crit else "warn", text=e.get("text") or line, source=src)
            say = decision("say", pri, text=line, voice="capcom", proactive=True,
                           situation="storm_warning" if warning else "storm_alert", emotion=self._emotion())
            card = decision("card", pri, title="CAPCOM", body=e.get("text") or line, chips=["Solar storm", src or "NASA"],
                            actions=[{"label": "Go to shelter", "send": {"t": "typed", "text": "go to the shelter"}},
                                     {"label": "Shields to 40", "send": {"t": "typed", "text": "shields to 40"}}],
                            hint=True)
            if st:
                self.warned.add(st.start_h)   # the sim warned already: no second lookahead alert
            return [al, card, say]
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
                    decision("say", P_NARRATION, text="Dark, and the battery's low. Let's save power.",
                             voice="capcom", proactive=True, situation="night_low_power", emotion=self._emotion()),
                    decision("card", P_NUDGE, title="Coach", nudge=True,
                             body="Turn down science and the rover. Keep heaters and life support on.",
                             actions=[{"label": "Science to 5", "send": {"t": "typed", "text": "science to 5"}}])]
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
        if ds:
            await self.emit(ds)

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
