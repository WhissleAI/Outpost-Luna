"""Grade one answer against a step's `accept` rule. Voice and taps both count.

accept types:
  intent    {place}                 the kid named the place ("show me the south pole"), or tapped it
  tap       {place, also?, radius_deg?}   a tap on that place (id from the globe, or lat/lon within radius_deg)
  command   {expect:{type, ...}}    the mission NLU turns the words into a Command that matches `expect`;
                                    `more: true` means an allocate that raises the load's share
  keywords  {all?:[[syn,...],...], any?:[[syn,...]]}   every `all` group has a word heard; at least one `any` group
  choice    {answer, options:[{id,label,say:[...]}]}   a tapped option id, or words that name exactly one option
  vocab_match / vocab_say / vocab_fill / vocab_listen   Space words (app/academy/vocab.py, docs/VOCABULARY.md)
"""
from __future__ import annotations

import json
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
    # ---- vocab steps (a11y / learning design) ----
    if kind.startswith("vocab_"):
        from . import vocab
        return vocab.grade(acc, inp)
    return False, {}


# ---- paraphrase fallback (local embedder) ------------------------------------------------------------------------------
SIMILAR = 0.72   # cosine (all-MiniLM-L6-v2) between the answer and the step's reference line


def references(step: dict) -> list[str]:
    """What a right answer sounds like: the quoted order in the prompt (a readback), else the `any` synonyms."""
    q = re.findall(r'"([^"]+)"', step.get("prompt", ""))
    return q or [w for grp in step["accept"].get("any", []) for w in grp]


PROTOCOL = {"roger", "copy", "wilco", "say again", "repeat"}   # radio words the lesson is teaching: never paraphrased away


async def similar(step: dict, text: str) -> bool:
    """Keyword steps only, after the keyword rules failed. A readback passes when the mission NLU (rules + the local
    command bank) reads the same Command from it as from the quoted order; other steps pass on embedder similarity to
    the reference. Groups holding a number or a radio protocol word must still be heard exactly."""
    acc = step["accept"]
    if acc["type"] != "keywords" or not (text or "").strip():
        return False
    t = _norm(text)
    for grp in acc.get("all", []):
        strict = any(re.search(r"\d", w) for w in grp) or any(w in PROTOCOL for w in grp)
        if strict and not any(_has(t, w) for w in grp):
            return False
    refs = references(step)
    if re.findall(r'"([^"]+)"', step.get("prompt", "")):
        want = [nlu._shape(c) + (json.dumps(c.get("amount")),) for r in refs for c in nlu.parse(r)["commands"]]
        if want:
            got = (await nlu.understand(text))["commands"]
            return any(nlu._shape(c) + (json.dumps(c.get("amount")),) in want for c in got)
    from .. import models_client
    v = await models_client.embed([text, *refs], "query")
    if not v or len(v) < 2:
        return False
    return max(sum(a * b for a, b in zip(v[0], r)) for r in v[1:]) >= SIMILAR
