"""What has been talked about in this session, by entity (docs/ENTITY_LAYER.md).

Every final turn's link results (the ear's names linked to the list, the registry's own matches of the words, a
known mishearing) and every line we speak become MENTION events:

    {"id", "by": "kid" | "guide" | "capcom" | "crew", "how": "ear_link" | "words" | "mishear" | "confirmed",
     "p": link p or None, "state": linked | abstain | ..., "screen", "t"}

The memory answers: what did the kid mention recently (the ear list's W_KID boost, the Director's recency features),
did the open step's target come up, was this asked before (story callbacks: "You asked about Tycho earlier."), and is
this the first time we hear of it. It lives in the session object only: never written to disk, never sent to a
model server. The opt-in turn log may record entity ids (never words) under its own rules (turnlog.py).
"""
from __future__ import annotations

from collections import deque

from .registry import Entity, Registry

MAX_EVENTS = 400
RECALL_AFTER_S = 120.0   # a callback ("You asked about Tycho earlier.") only for a mention at least this old
RECALL_EVERY_S = 300.0   # and at most one callback per entity per this long


class EntityMemory:
    def __init__(self, reg: Registry, clock):
        self.reg, self.clock = reg, clock
        self.events: deque = deque(maxlen=MAX_EVENTS)
        self._recalled: dict[str, float] = {}

    # ---- writing ----
    def note(self, eid: str, by: str, how: str, p: float | None = None, state: str | None = None,
             screen: str | None = None) -> dict | None:
        if self.reg.get(eid) is None:
            return None
        ev = {"id": eid, "by": by, "how": how, "p": p, "state": state, "screen": screen, "t": self.clock()}
        self.events.append(ev)
        return ev

    def note_turn(self, names: list[dict] | None, words: str, screen: str | None = None) -> list[dict]:
        """A kid's final turn: the ear's linked names (by the list's spelling) and the registry's matches of the
        heard words. -> the mention events (one per entity)."""
        out, seen = [], set()
        for n in names or []:
            if not isinstance(n, dict) or not n.get("entity"):
                continue
            e = self.reg.resolve(n["entity"])
            if e is not None and e.id not in seen and n.get("state") in ("linked", "abstain"):
                seen.add(e.id)
                out.append(self.note(e.id, "kid", "ear_link", n.get("p"), n.get("state"), screen))
        for e in self.reg.mentions(words):
            if e.id not in seen:
                seen.add(e.id)
                out.append(self.note(e.id, "kid", "words", None, None, screen))
        return [x for x in out if x]

    def note_line(self, text: str, by: str = "guide", screen: str | None = None) -> list[dict]:
        return [x for x in (self.note(e.id, by, "words", screen=screen) for e in self.reg.mentions(text)) if x]

    # ---- reading ----
    def kid_recent(self, window_s: float = 600.0) -> list[tuple[str, float]]:
        """(entity id, seconds ago) of the kid's mentions in the window, newest first, one per entity. Abstained
        links are not mentions (the ear was unsure)."""
        now, out, seen = self.clock(), [], set()
        for ev in reversed(self.events):
            if ev["by"] != "kid" or ev["state"] == "abstain":
                continue
            ago = now - ev["t"]
            if ago > window_s:
                break
            if ev["id"] not in seen:
                seen.add(ev["id"])
                out.append((ev["id"], ago))
        return out

    def last(self, eid: str, by: str | None = "kid", before: float | None = None) -> dict | None:
        for ev in reversed(self.events):
            if ev["id"] == eid and (by is None or ev["by"] == by) and (before is None or ev["t"] < before):
                return ev
        return None

    def count(self, eid: str, by: str | None = "kid") -> int:
        return sum(1 for ev in self.events if ev["id"] == eid and (by is None or ev["by"] == by))

    def recall_line(self, eid: str, now_turn_t: float | None = None) -> str | None:
        """"You asked about Tycho earlier." when the kid named it >= RECALL_AFTER_S before this turn (and we have not
        said so for it in RECALL_EVERY_S). Marks it said."""
        e: Entity | None = self.reg.get(eid)
        if e is None:
            return None
        now = self.clock()
        t0 = now_turn_t if now_turn_t is not None else now - 1e-6
        prev = self.last(eid, "kid", before=t0 - RECALL_AFTER_S)
        if prev is None or now - self._recalled.get(eid, -1e9) < RECALL_EVERY_S:
            return None
        self._recalled[eid] = now
        return f"You asked about {e.name} earlier."

    def summary(self) -> dict:
        """Ids and counts only (no words): for diagnostics and the opt-in turn log."""
        c: dict[str, int] = {}
        for ev in self.events:
            if ev["by"] == "kid":
                c[ev["id"]] = c.get(ev["id"], 0) + 1
        return {"kid_mentions": c, "events": len(self.events)}
