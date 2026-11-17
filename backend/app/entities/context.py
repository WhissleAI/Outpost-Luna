"""Per-moment ear lists, derived from the registry and what is going on right now (docs/ENTITY_LAYER.md).

The ear (Arc Transcriber Space) takes one ordered list; order is its only weight (the first ~10-15 entries reach its
decoder prompt; every entry biases the words and can be linked). So "weighting" = a score per entity, then a sort:

    W_STEP     the open step / question expects it (its options, its target)
    W_SAID     we (the guide, CAPCOM) just named it: the kid's next turn often does too
    W_KID      the kid named it recently (decays over KID_HALF_LIFE_S)
    W_LOOKING  the place on screen / last place
    W_STATE    a mission state makes it relevant (a storm -> shields)
    W_RELATED  related to something above
    + the screen profile's rank (what the screen is about), which always fills the rest of the list

The list is rebuilt whenever the context changes (the session's names loop polls it every 0.25 s) and the ear applies
it from its next decode, mid-turn included (arc.h: names are the model's when each utterance closes).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .registry import Entity, Registry

W_STEP, W_SAID, W_KID, W_LOOKING, W_STATE, W_RELATED = 1000.0, 600.0, 500.0, 400.0, 300.0, 150.0
KID_HALF_LIFE_S = 120.0
SAID_MAX = 8            # names from what we just said: at most this many get the boost
GENERIC_ALIASES = {"descent stage", "lander", "rover", "impact site", "spacecraft"}


@dataclass
class Moment:
    screen: str | None = None
    step_ids: list[str] = field(default_factory=list)      # entities the open step expects
    step_words: list[str] = field(default_factory=list)    # its option words that are proper names but not entities
    said: list[str] = field(default_factory=list)          # our last lines (text)
    kid: list[tuple[str, float]] = field(default_factory=list)   # (entity id, seconds ago) the kid mentioned
    looking: str | None = None                             # the entity on screen / the last place
    states: list[str] = field(default_factory=list)        # active mission states ("storm", "dark", ...)


def scores(reg: Registry, m: Moment) -> dict[str, float]:
    s: dict[str, float] = {}

    def add(eid: str | None, w: float):
        e = reg.get(eid)
        if e is not None and e.ear and m.screen not in e.exclude_screens:
            s[e.id] = s.get(e.id, 0.0) + w

    for i, eid in enumerate(m.step_ids):
        add(eid, W_STEP - i)
    for i, e in enumerate([e for line in m.said for e in reg.mentions(line)][:SAID_MAX]):
        add(e.id, W_SAID - i)
    for eid, ago in m.kid:
        add(eid, W_KID * math.pow(0.5, max(0.0, ago) / KID_HALF_LIFE_S))
    add(m.looking, W_LOOKING)
    if m.states:
        for e in reg.entities:
            if set(e.states) & set(m.states):
                add(e.id, W_STATE)
    for eid in list(s):                 # one hop, from the boosted entities only
        for r in reg.get(eid).related:
            add(r, W_RELATED)
    return s


def dedupe_aliases(out: list[dict]) -> list[dict]:
    """An alias is a link target, so it must name ONE entry: aliases equal to another entry's name, shared by two
    entries, or generic are dropped."""
    names = {e["name"].lower() for e in out}
    seen: dict[str, int] = {}
    for e in out:
        for a in {a.lower() for a in e.get("aliases") or []}:
            seen[a] = seen.get(a, 0) + 1
    res = []
    for e in out:
        al = [a for a in e.get("aliases") or [] if a.lower() not in names and seen.get(a.lower(), 0) == 1
              and a.lower() not in GENERIC_ALIASES]
        e = {k: v for k, v in e.items() if k != "aliases"}
        if al:
            e["aliases"] = al[:12]
        res.append(e)
    return res


def ear_list(reg: Registry, m: Moment, cap: int | None = None, extra: list[dict] | None = None) -> list[dict]:
    """The ear's names list for this moment: boosted entities first (by score), `extra` entries (step words that are
    proper names but not in the registry) after the step's, then the screen profile in its order; <= cap."""
    cap = cap or reg.cap(m.screen)
    sc = scores(reg, m)
    boosted = sorted(sc, key=lambda i: (-sc[i], reg.get(i).rank))
    ordered: list[Entity] = [reg.get(i) for i in boosted]
    n_step = sum(1 for i in boosted if sc[i] >= W_STEP - len(m.step_ids))
    rest = [e for e in reg.screen_entities(m.screen) if e.id not in sc]
    entries = [e.ear_entry() for e in ordered[:n_step]] + list(extra or []) + \
        [e.ear_entry() for e in ordered[n_step:] + rest]
    out, have = [], set()
    for e in entries:
        k = e["name"].lower()
        if k not in have:
            have.add(k)
            out.append(e)
    return dedupe_aliases(out[:cap])
