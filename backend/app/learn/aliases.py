"""Personal name aliases: how THIS kid says a name, learned from their own confirmations (docs/ON_DEVICE_LEARNING.md).

When the app asks "Did you mean Tycho?" because it heard "ticko", and the kid says yes (or taps Tycho), the heard form
"ticko" is a candidate alias of the entity `tycho` for this cadet. After enough evidence it becomes a private alias:
the next "fly to ticko" links to Tycho directly (director._link, after the ear's own sure links), with no question.

Guards (each one is a test in tests/test_learn.py):
  - evidence: MIN_CONFIRMS confirmations of the same heard form -> the same entity, or ONE confirmation of an offer the
    ear itself rated very close (Arc's sound-alike p >= HIGH_P);
  - never a common word, a filler, a yes / no word, or anything over MAX_WORDS words;
  - never a form that already names an entity in the registry (another entity's name, alias or spoken form; or this
    one's: no alias needed), a known mishearing of another entity, or a learned alias of another entity;
  - a "no" to the offer (or a removal) blocks that heard form: it is never learned for anyone after that;
  - at most CAP aliases; each decays (half-life HALF_LIFE_DAYS since it was last used or confirmed) and is dropped
    when its strength falls under MIN_STRENGTH;
  - only from turns that were not our own echo (the session checks; learn() refuses `echo=True`).

App-agnostic: needs a Registry (app/entities) and a plain dict for its state (app/learn/store.py persists it).
"""
from __future__ import annotations

import time

from ..entities.registry import Registry, toks

MIN_CONFIRMS = 2
HIGH_P = 0.85
CAP = 24
MAX_WORDS = 3
MIN_CHARS = 3
HALF_LIFE_DAYS = 45.0
MIN_STRENGTH = 0.5
DAY = 86400.0

# Never an alias: function words, fillers, yes / no words and the commonest English words a kid says to the app
# (a heard form made ONLY of these is refused; one real word among them is enough, e.g. "the jelly").
COMMON = set("""
a an the to of in on at is are was be it its this that these those so what and or but for with as do does did can will
would just i you he she we they me my your our their him her them us not no yes yeah yep yup nope nah ok okay sure
please thanks thank um uh oh ah hmm hey hi hello well like go going gone get got want need see look show tell where
when why who how which there here now then up down out over under back front far near side big small little more less
one two three four five six seven eight nine ten first last next again stop start help fly take make move turn open
close play pause skip find give put come let lets moon earth sun star stars space rocket ship crater craters sea rock
rocks place places thing things good bad cool wow yay nice all some any much many very too also only really maybe
""".split())


def norm_heard(s: str | None) -> str:
    return toks(s or "")


class PersonalAliases:
    def __init__(self, reg: Registry, state: dict | None = None, clock=time.time):
        self.reg, self.clock = reg, clock
        st = state if isinstance(state, dict) else {}
        self.aliases: list[dict] = [dict(a) for a in st.get("aliases") or [] if isinstance(a, dict)]
        self.pending: list[dict] = [dict(a) for a in st.get("pending") or [] if isinstance(a, dict)]
        self.blocked: list[str] = [b for b in st.get("blocked") or [] if isinstance(b, str)]
        self.decay()

    # ---- state ----
    def state(self) -> dict:
        return {"aliases": self.aliases, "pending": self.pending[-32:], "blocked": self.blocked[-64:]}

    def strength(self, a: dict, now: float | None = None) -> float:
        now = self.clock() if now is None else now
        age = max(0.0, now - float(a.get("last", now))) / DAY
        return float(a.get("n", 1)) * 0.5 ** (age / HALF_LIFE_DAYS)

    def decay(self) -> int:
        now = self.clock()
        before = len(self.aliases)
        self.aliases = [a for a in self.aliases if self.strength(a, now) >= MIN_STRENGTH]
        self.pending = [p for p in self.pending if now - float(p.get("last", now)) <= 30 * DAY]
        return before - len(self.aliases)

    # ---- guards ----
    def why_not(self, heard: str, eid: str) -> str | None:
        """None when `heard` may become an alias of `eid`; else the reason (a short code)."""
        h = norm_heard(heard)
        ws = h.split()
        if not ws or len(h) < MIN_CHARS:
            return "too_short"
        if len(ws) > MAX_WORDS or len(h) > 40:
            return "too_long"
        if all(w in COMMON for w in ws):
            return "common_words"
        if self.reg.get(eid) is None:
            return "unknown_entity"
        owner = self.reg.resolve(h)
        if owner is not None:
            return "already_this_name" if owner.id == eid else "owned_by_another"
        if any(e.id != eid for e in self.reg.mentions(h)):
            return "contains_another"
        mh = self.reg._mishear.get(h)      # noqa: SLF001 - the registry's own mishearing table
        if mh is not None and mh != eid:
            return "mishear_of_another"
        if h in self.blocked:
            return "blocked"
        if any(a["heard"] == h and a["id"] != eid for a in self.aliases):
            return "alias_of_another"
        return None

    # ---- evidence ----
    def confirm(self, heard: str, eid: str, p: float | None = None, echo: bool = False, via: str = "yes") -> str:
        """The kid confirmed the offer (said yes, or tapped it). -> "learned" | "pending" | "refreshed" | "refused:<why>"."""
        if echo:
            return "refused:echo"
        why = self.why_not(heard, eid)
        if why:
            return f"refused:{why}"
        h, now = norm_heard(heard), self.clock()
        for a in self.aliases:
            if a["heard"] == h and a["id"] == eid:
                a["n"] = min(9, float(a.get("n", 1)) + 1)
                a["last"] = now
                return "refreshed"
        pend = next((x for x in self.pending if x["heard"] == h and x["id"] == eid), None)
        if pend is None:
            pend = {"heard": h, "id": eid, "n": 0, "first": now}
            self.pending.append(pend)
        pend["n"] = int(pend.get("n", 0)) + 1
        pend["last"] = now
        pend["p"] = max(float(pend.get("p", 0.0)), float(p or 0.0))
        if pend["n"] >= MIN_CONFIRMS or (p is not None and float(p) >= HIGH_P):
            self.pending.remove(pend)
            if len(self.aliases) >= CAP:     # full: the weakest goes
                self.aliases.sort(key=lambda a: self.strength(a, now))
                self.aliases.pop(0)
            self.aliases.append({"heard": h, "id": eid, "n": float(pend["n"]), "first": pend.get("first", now),
                                 "last": now, "uses": 0})
            return "learned"
        return "pending"

    def reject(self, heard: str, eid: str | None = None) -> bool:
        """A "no" to "Did you mean X?" for this heard form: drop what was gathered for it and never learn it."""
        h = norm_heard(heard)
        if not h:
            return False
        self.pending = [x for x in self.pending if x["heard"] != h]
        self.aliases = [a for a in self.aliases if a["heard"] != h]
        if h not in self.blocked:
            self.blocked.append(h)
            del self.blocked[:-64]
        return True

    def remove(self, heard: str) -> bool:
        """The parent removed it (Settings → What the app has learned): gone, and never learned again."""
        h = norm_heard(heard)
        had = any(a["heard"] == h for a in self.aliases) or any(x["heard"] == h for x in self.pending)
        self.reject(h)
        return had

    # ---- use ----
    def lookup(self, text: str | None) -> tuple[str, str] | None:
        """The longest learned alias said in `text` -> (entity id, heard form), or None."""
        t = f" {norm_heard(text)} "
        if not t.strip() or not self.aliases:
            return None
        for a in sorted(self.aliases, key=lambda a: -len(a["heard"])):
            if f" {a['heard']} " in t:
                return a["id"], a["heard"]
        return None

    def used(self, heard: str) -> None:
        for a in self.aliases:
            if a["heard"] == norm_heard(heard):
                a["last"] = self.clock()
                a["uses"] = int(a.get("uses", 0)) + 1

    def pairs(self) -> list[tuple[str, str]]:
        return [(a["heard"], a["id"]) for a in self.aliases]
