"""The claim check (docs/REVAMP.md §3.4): the guide never says a number or a place that isn't on the fact sheet.

1. The LLM drafts the guide's line from the fact sheet of the places in play only.
2. Arc Tagger re-reads each sentence of the draft. Every number span must match a fact-sheet number (within 10%),
   and every place it names must be in play (or named in their facts).
3. Failed sentences are rewritten once (the LLM is told what failed), then dropped.
4. No key, LLM error, or nothing survives: the place's `fact` from places.json, verbatim (it is pre-verified).
"""
from __future__ import annotations

import json
import re

from . import models_client
from rapidfuzz import fuzz, process

from .config import settings
from .gazetteer import Gazetteer, norm
from .moments import fact_numbers, number_ok

PREVERIFIED = "places.json (pre-verified)"
SENT = re.compile(r"(?<=[.!?])\s+")
DIGITS = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand)?", re.I)
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20, "fifty": 50, "hundred": 100, "thousand": 1000,
           "million": 1e6, "billion": 1e9}
MULT = {"thousand": 1e3, "million": 1e6, "billion": 1e9}

_client = None


def available() -> bool:
    return bool(settings.anthropic_api_key)


async def _complete(prompt: str) -> str | None:
    """One LLM call. Tests monkeypatch this."""
    global _client
    if not available():
        return None
    try:
        if _client is None:
            from anthropic import AsyncAnthropic
            _client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=8.0)
        msg = await _client.messages.create(model=settings.ask_model, max_tokens=200, extra_body={"thinking": {"type": "disabled"}},
                                            messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if b.type == "text").strip() or None
    except Exception:  # noqa: BLE001 - any LLM failure falls back to verified text
        return None


# ---- number + place extraction ---------------------------------------------------------------------------------------
def numbers_in(text: str, spans: list[dict] | None = None) -> list[tuple[str, float]]:
    """Numbers in a sentence: Arc number spans when we have them, plus digits and number words as a backstop."""
    found: list[tuple[str, float]] = []
    chunks = [s["text"] for s in spans or [] if s.get("family") == "number"] + [text]
    seen = set()
    for chunk in chunks:
        for m in DIGITS.finditer(chunk):
            v = float(m.group(1).replace(",", "")) * MULT.get((m.group(2) or "").lower(), 1)
            if v not in seen:
                seen.add(v)
                found.append((m.group(0).strip(), v))
    # Number words ("three rings", "two thousand"): read runs of number words left to right.
    toks = norm(text).split()
    i = 0
    while i < len(toks):
        if toks[i] in WORDNUM and not (i and re.fullmatch(r"[\d.]+", toks[i - 1])):
            j, total, cur = i, 0.0, 0.0
            while j < len(toks) and toks[j] in WORDNUM:
                w = WORDNUM[toks[j]]
                if w >= 100:
                    cur = (cur or 1) * w
                    if w >= 1000:
                        total, cur = total + cur, 0.0
                else:
                    cur += w
                j += 1
            v = total + cur
            if v not in seen and not (toks[i] == "one" and j == i + 1):  # "one of the biggest" is not a claim
                seen.add(v)
                found.append((" ".join(toks[i:j]), v))
            i = j
        else:
            i += 1
    return found


def _place_keys(gaz: Gazetteer) -> list[tuple[str, str]]:
    keys = []
    for p in gaz.places.values():
        nm = norm(p.name)
        ks = {nm, p.id} | {norm(a) for a in p.aliases if len(a) >= 5 and norm(a)[:4] in f"{nm} {p.id}"}
        keys += [(k, p.id) for k in ks if len(k) >= 3]
    return keys


def places_in(text: str, gaz: Gazetteer, spans: list[dict] | None = None) -> set[str]:
    t = f" {norm(text)} "
    out = {pid for k, pid in _place_keys(gaz) if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", t)}
    keys = _place_keys(gaz)
    names = [k for k, _ in keys]
    for s in spans or []:
        if s.get("family") == "entity" and len(norm(s["text"])) >= 3:
            hit = process.extractOne(norm(s["text"]), names, scorer=fuzz.ratio, score_cutoff=90)
            # "Surveyor 3" is 90% like "surveyor 1": a fuzzy hit must not change a number.
            if hit and re.findall(r"\d+", norm(s["text"])) == re.findall(r"\d+", hit[0]):
                out.add(keys[hit[2]][1])
    return out


# ---- the check -------------------------------------------------------------------------------------------------------
def _allowed_places(place_ids: list[str], facts: dict, gaz: Gazetteer) -> set[str]:
    ok = set(place_ids)
    for pid in place_ids:
        for f in (facts.get(pid) or {}).get("facts", []):
            ok |= places_in(f["text"], gaz)
    return ok


def _source_for(sentence: str, place_ids: list[str], facts: dict, nums: list[float]) -> str:
    best, best_n = None, -1
    words = set(norm(sentence).split())
    for pid in place_ids:
        for f in (facts.get(pid) or {}).get("facts", []):
            n = len(words & set(norm(f["text"]).split())) + 10 * sum(number_ok(v, f.get("numbers", [])) for v in nums)
            if n > best_n:
                best, best_n = f["source"], n
    return best or "fact sheet"


async def check_sentence(sentence: str, place_ids: list[str], gaz: Gazetteer, facts: dict) -> tuple[list[str], str]:
    """-> (failures, source). No failures means verified."""
    out = await models_client.tag(sentence, "assistant")
    spans = (out or {}).get("spans") or []
    allowed_nums = fact_numbers(facts, place_ids)
    fails, vals = [], []
    for txt, v in numbers_in(sentence, spans):
        vals.append(v)
        if not number_ok(v, allowed_nums):
            fails.append(f'the number "{txt}" is not on the fact sheet')
    allowed = _allowed_places(place_ids, facts, gaz)
    for pid in places_in(sentence, gaz, spans) - allowed:
        fails.append(f'it names {gaz.places[pid].name}, which is not on the fact sheet')
    return fails, _source_for(sentence, place_ids, facts, vals)


def fact_sheet(place_ids: list[str], facts: dict, gaz: Gazetteer) -> str:
    lines = []
    for pid in place_ids:
        f, p = facts.get(pid) or {}, gaz.places.get(pid)
        if not p:
            continue
        if f.get("estimated") or p.estimated:
            head = f"{p.name} ({f.get('type', 'place')}, {f.get('side', '?')} side, crew-proposed name; size unknown)"
        else:
            head = f"{p.name} ({f.get('type', 'place')}, about {f.get('diameter_km', p.diameter_km):g} km, {f.get('side', '?')} side)"
        lines.append(head)
        lines += [f"- {x['text']}" for x in f.get("facts", [])] or [f"- {p.fact}"]
    return "\n".join(lines)


def fallback(place_ids: list[str], gaz: Gazetteer, short: bool = False) -> tuple[str, list[dict]]:
    p = gaz.places.get(place_ids[0]) if place_ids else None
    if not p:
        return "", []
    text = SENT.split(p.fact)[0] if short else p.fact
    return text, [{"text": text, "status": "verified", "source": PREVERIFIED}]


async def guide_line(place_ids: list[str], question: str, gaz: Gazetteer, facts: dict,
                     short: bool = False) -> tuple[str, list[dict], str]:
    """The guide's claim-checked line about the places in play. -> (say, claims, source)."""
    place_ids = [p for p in place_ids if p in gaz.places]
    if not place_ids:
        return "", [], "none"
    words = "10" if short else "25"
    prompt = (f"You are the Moon Guide in a kids' app (ages 5-10). A child said: \"{question}\" "
              "They mean the Moon place(s) on this fact sheet.\n"
              f"Fact sheet (the ONLY facts you may use):\n{fact_sheet(place_ids, facts, gaz)}\n\n"
              f"Answer in {'1 short sentence' if short else 'at most 2 short sentences'} (under {words} words total), "
              "simple friendly words. Use only numbers and place names from the fact sheet, written as digits. "
              "Reply with just the sentences.")
    draft = await _complete(prompt)
    if not draft:
        t, c = fallback(place_ids, gaz, short)
        return t, c, PREVERIFIED
    claims = await verify_draft(draft, place_ids, gaz, facts, prompt)
    say = " ".join(c["text"] for c in claims if c["status"] == "verified")
    if not say:
        t, c = fallback(place_ids, gaz, short)
        return t, claims + c, PREVERIFIED
    return say, claims, "llm+claimcheck"


async def verify_draft(draft: str, place_ids: list[str], gaz: Gazetteer, facts: dict,
                       prompt: str | None = None) -> list[dict]:
    """Check every sentence; rewrite failures once (when an LLM prompt is given), then drop."""
    claims = []
    for sent in [s.strip() for s in SENT.split(draft.strip()) if s.strip()]:
        fails, src = await check_sentence(sent, place_ids, gaz, facts)
        if fails and prompt:
            fix = await _complete(f"{prompt}\n\nYou wrote: \"{sent}\"\nThat sentence failed the fact check because "
                                  f"{'; '.join(fails)}. Rewrite just that one sentence using only the fact sheet. "
                                  "Reply with the sentence only.")
            if fix:
                fix = SENT.split(fix.strip())[0].strip().strip('"')
                fails2, src2 = await check_sentence(fix, place_ids, gaz, facts)
                if not fails2:
                    claims.append({"text": fix, "status": "verified", "source": src2})
                    claims.append({"text": sent, "status": "removed", "source": "; ".join(fails)})
                    continue
        if fails:
            claims.append({"text": sent, "status": "removed", "source": "; ".join(fails)})
        else:
            claims.append({"text": sent, "status": "verified", "source": src})
    return claims


def parse_json(out: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", out or "")
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
