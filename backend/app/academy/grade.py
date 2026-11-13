"""Grade one answer against a step's `accept` rule. Voice and taps both count.

accept types:
  intent    {place}                 the kid named the place ("show me the south pole"), or tapped it
  tap       {place, also?, radius_deg?}   a tap on that place (id from the globe, or lat/lon within radius_deg)
  command   {expect:{type, ...}}    the mission NLU turns the words into a Command that matches `expect`;
                                    `more: true` means an allocate that raises the load's share
  keywords  {all?:[[syn,...],...], any?:[[syn,...]]}   every `all` group has a word heard; at least one `any` group
  choice    {answer, options:[{id,label,say:[...]}]}   a tapped option id, or words that name exactly one option
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from ..gazetteer import Gazetteer
from ..mission import nlu, sim
from .content import DATA


@lru_cache(maxsize=1)
def gaz() -> Gazetteer:
    return Gazetteer(DATA / "places.json")


def _norm(text: str) -> str:
    return nlu._words_to_digits(nlu.norm(text or ""))


def _has(t: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(_norm(word))}(?![a-z0-9])", t) is not None


def _ang(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    c = math.sin(la1) * math.sin(la2) + math.cos(la1) * math.cos(la2) * math.cos(lo1 - lo2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _tap_ok(tap, acc: dict) -> bool:
    ids = {acc["place"], *acc.get("also", [])}
    if isinstance(tap, str):
        return tap in ids
    if isinstance(tap, dict):
        if tap.get("place") in ids:
            return True
        if tap.get("lat") is not None and tap.get("lon") is not None:
            r = acc.get("radius_deg", 6)
            for pid in ids:
                p = gaz().places.get(pid)
                if p and _ang((tap["lat"], tap["lon"]), (p.lat, p.lon)) <= r:
                    return True
    return False


def _more(cmd: dict, loads: dict) -> bool:
    a = cmd.get("amount") or {}
    kind, v = a.get("kind"), a.get("value")
    if kind in ("delta", "little"):
        return (v or 0) > 0
    if kind in ("all", "half"):
        return kind == "all" or loads.get(cmd.get("to"), 0) < 50
    if kind == "percent":
        return (v or 0) > loads.get(cmd.get("to"), 0)
    return False


def matching_command(text: str, expect: dict, loads: dict | None = None) -> dict | None:
    """The first Command the NLU reads from `text` that matches `expect`, else None."""
    loads = loads or dict(sim.DEFAULT_LOADS)
    for cmd in nlu.parse(text or "").get("commands", []):
        if any(k != "more" and cmd.get(k) != v for k, v in expect.items()):
            continue
        if expect.get("more") and not _more(cmd, loads):
            continue
        return cmd
    return None


def choice_of(inp: dict, acc: dict) -> str | None:
    if inp.get("choice"):
        return inp["choice"]
    t = _norm(inp.get("text", ""))
    if not t:
        return None
    hits = [o["id"] for o in acc["options"] if any(_has(t, w) for w in [o["label"], *o.get("say", [])])]
    return hits[0] if len(hits) == 1 else None


def grade(step: dict, inp: dict, loads: dict | None = None) -> tuple[bool, dict]:
    """(passed, extra). extra may hold the matched `command` or the `choice`."""
    acc, inp = step["accept"], inp or {}
    kind, text = acc["type"], inp.get("text") or ""
    if kind == "tap":
        return _tap_ok(inp.get("tap"), acc), {}
    if kind == "intent":
        if inp.get("tap") is not None and _tap_ok(inp["tap"], {**acc, "radius_deg": acc.get("radius_deg", 10)}):
            return True, {}
        p = gaz().match_text(text) if text else None
        return bool(p and p.id in {acc["place"], *acc.get("also", [])}), {}
    if kind == "command":
        cmd = matching_command(text, acc["expect"], loads)
        return cmd is not None, {"command": cmd} if cmd else {}
    if kind == "keywords":
        t = _norm(text)
        ok_all = all(any(_has(t, w) for w in grp) for grp in acc.get("all", []))
        ok_any = not acc.get("any") or any(any(_has(t, w) for w in grp) for grp in acc["any"])
        return bool(t) and ok_all and ok_any, {}
    if kind == "choice":
        c = choice_of(inp, acc)
        return c == acc["answer"], {"choice": c}
    return False, {}
