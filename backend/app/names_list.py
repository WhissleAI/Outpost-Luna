"""The ear's NAMES LIST per moment, for Arc Transcriber Space (model_server/app/arc_ear.py; docs/LOCAL_EAR.md).

Since the entity layer (docs/ENTITY_LAYER.md) this is a thin adapter: the names, aliases, spoken forms, groups and
screen profiles live in the registry (data/entities/outpost_luna.json, app/entities), and the list is derived from it
plus the moment (app/entities/context.py): the open step's targets, what we just said, what the kid named recently,
the place on screen, the mission state, then what the screen is about.

The model takes entries {"name", "kind", "aliases"} and uses them three ways: it biases the transcript toward them,
puts the first ~10-15 in its decoder prompt, and LINKS what was said to an entry (names[i].entity = our `name`, state
linked / abstain / not_in_list). Rules (the model's guide, and the signals audit, docs/SPEECH_SIGNALS_AUDIT.md):
  - `kind` always set; short and current: <= 40 on a focused screen, <= 80 on the Moon screens; most relevant first;
  - an alias names ONE entry (aliases link too); no generic aliases; no entries made only of generic words;
  - controls ("the rover", "shields") are never entries: the ear rewrites a linked span in the list's spelling.
`session.ear_names()` builds the list; /ws/listen sends it ({"t":"context","names":[...]}) whenever it changes.
"""
from __future__ import annotations

import re

from .entities import Moment, dedupe_aliases, ear_list, registry
from .entities.context import GENERIC_ALIASES  # noqa: F401  (re-exported for older callers)

MAX = 40           # the cap for a focused screen (cabin, lesson, video ...): the model card's "<= 30-50"
MAX_MOON = 80      # the Moon screens (map, library, patch, lesson_done): every place AND every piece of hardware
MAX_EAR = MAX_MOON  # what /ws/listen and the model server accept (the longest list a screen sends)
GENERIC = set("sea crater basin mare north south pole valley mountain plateau rim floor ridge base the of".split())


def generic(name: str) -> bool:
    return all(w in GENERIC for w in re.findall(r"[a-z]+", name.lower()))


def catalogue() -> dict[str, list[dict]]:
    """Every name the ear may be given, by registry group ({"name","kind","aliases"?,"id"})."""
    out: dict[str, list[dict]] = {}
    for e in registry().entities:
        if e.ear:
            out.setdefault(e.group, []).append({**e.ear_entry(), "id": e.id})
    return out


def catalogue_names() -> list[dict]:
    """Everything the ear may be given (for offline tools: the ear eval's decoys; the director's sound-alikes)."""
    return [e.ear_entry() for e in registry().entities if e.ear]


def recent_names(lines) -> list[dict]:
    """Registry entries named in these lines (what we just said / showed), as ear entries."""
    out, seen = [], set()
    for line in lines or []:
        for e in registry().mentions(line or ""):
            if e.ear and e.id not in seen and not generic(e.name):
                seen.add(e.id)
                out.append({**e.ear_entry(), "id": e.id})
    return out


def step_targets(step: dict | None, options: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """The open step's targets: (registry ids, extra ear entries for proper-name options the registry lacks)."""
    from .academy.grade import step_vocab
    R = registry()
    ids, extra = [], []
    for w in step_vocab(step, list(options or []), aliases=False):
        e = R.resolve(w) or R.get(w)
        if e is not None and e.ear:
            if e.id not in ids:
                ids.append(e.id)
        elif re.search(r"[A-Z]", w) and len(w) >= 3 and not generic(w) and len(w.split()) <= 4:
            extra.append({"name": re.sub(r"\s+", " ", w).strip(), "kind": "place"})
    return ids, extra


def screen_names(frame: dict | None, step: dict | None = None, last_place: str | None = None,
                 recent: list[str] | None = None, kid: list[tuple[str, float]] | None = None,
                 states: list[str] | None = None) -> list[dict]:
    """The names list for this moment, most relevant first ({"name","kind","aliases"?})."""
    fr = frame or {}
    screen = fr.get("screen") or "map"
    ids, extra = ([], [])
    if screen in ("lesson", "ride"):
        ids, extra = step_targets(step, fr.get("step_options") or [])
    R = registry()
    looking = last_place if R.get(last_place) is not None else None
    m = Moment(screen=screen, step_ids=ids, said=list(recent or []), kid=list(kid or []), looking=looking,
               states=list(states or []))
    return ear_list(R, m, extra=extra)


__all__ = ["MAX", "MAX_MOON", "MAX_EAR", "catalogue", "catalogue_names", "dedupe_aliases", "recent_names",
           "screen_names", "step_targets"]
