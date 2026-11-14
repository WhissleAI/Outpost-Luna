"""Deepgram `keyterm` lists: the lunar proper names we want the ear to spell right.

Deepgram allows up to 100 keyterms and 500 tokens per request and recommends 20-50 focused terms
(https://developers.deepgram.com/docs/keyterm), so lists are capped at MAX_TERMS.
"""
from __future__ import annotations

import re

from .gazetteer import Gazetteer, norm

MAX_TERMS = 50
CREW = ["Reid Wiseman", "Victor Glover", "Christina Koch", "Jeremy Hansen"]
# Gazetteer aliases are mostly kid words ("bullseye") and misspellings ("oriental"); only these are proper names.
PROPER_ALIASES = {"apollo 11", "armstrong", "aitken", "imbrium", "crisium", "artemis iii"}
# Lunar names that appear in NASA's clip titles but aren't in the starter gazetteer yet.
TITLE_NAMES = ["Byrgius Alpha", "Byrgius A", "Mare Humorum", "Grimaldi", "Kepler", "Pythagoras", "Orientale Basin", "Reiner Gamma", "Aristarchus Plateau", "Orientale", "Hertzsprung",
               "Vavilov", "Glushko", "Ohm", "Integrity", "Carroll", "Earthrise", "Earthset"]
# Hardware names kids and the voices clips say (Apollo-era artifacts, artifacts.json).
HARDWARE = ["Apollo", "Surveyor", "Lunar Roving Vehicle", "Lunar Module", "Charlie Duke", "Jim Lovell"]
JARGON = ["albedo", "ejecta", "regolith", "terminator", "mare"]


def _clean(name: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", name).strip()


def _dedupe(terms: list[str]) -> list[str]:
    seen, out = set(), []
    for t in terms:
        k = norm(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out[:MAX_TERMS]


def base_keyterms(gaz: Gazetteer) -> list[str]:
    names = [_clean(p.name) for p in gaz.features]  # artifacts have long English names; the ear doesn't need them
    aliases = [a.title() if a != "artemis iii" else "Artemis III" for p in gaz.features for a in p.aliases
               if a in PROPER_ALIASES]
    return _dedupe(names + aliases + TITLE_NAMES + CREW + HARDWARE + JARGON)


def clip_keyterms(title: str, gaz: Gazetteer) -> list[str]:
    """Names in the clip's NASA title first (they're the likeliest in the audio), then the base list."""
    t = norm(title)
    in_title = [n for n in TITLE_NAMES + [_clean(p.name) for p in gaz.features]
                if re.search(rf"\b{re.escape(norm(n))}\b", t)]
    return _dedupe(in_title + base_keyterms(gaz))


# ------------------------------------------------------------------------------------------- Arc ear (local)
# Arc's decoder context takes names + terms in order and keeps what fits its ~40-token list slot (arc_audio ctxprompt
# kb_max), so the order is a priority order: what the screen is about first (the client's context frame), then these.
# All of them (up to 200) also reach Arc's name linker / snap, which has no token budget.
ARC_HARDWARE = ["Apollo 16 rover", "Lunar Roving Vehicle", "Lunar Module", "Surveyor 3", "Surveyor", "Orion", "Integrity",
                "Artemis II", "Artemis III", "SLS"]
ARC_PLACES = ["Shackleton", "de Gerlache", "Malapert", "Cabeus", "Aristarchus", "Orientale", "Vavilov", "Tycho",
              "Copernicus", "Mare Tranquillitatis"]
ARC_CREW = ["CAPCOM", "Houston"] + CREW
TIER_A_MAX = 200


def glossary_terms(glossary_path) -> list[str]:
    import json
    try:
        g = json.loads(open(glossary_path).read())
        return list((g.get("terms") or {}).keys())
    except Exception:  # noqa: BLE001
        return []


def tier_a(gaz: Gazetteer, glossary_path=None) -> list[str]:
    """Lunar Tier A list for the Arc ear: core places, crew, hardware, then gazetteer names and glossary terms."""
    names = [_clean(p.name) for p in gaz.features]
    out = ARC_PLACES + ARC_CREW + ARC_HARDWARE + names + TITLE_NAMES + HARDWARE + JARGON
    if glossary_path is not None:
        out += glossary_terms(glossary_path)
    seen, res = set(), []
    for t in out:
        k = norm(t)
        if k and k not in seen:
            seen.add(k)
            res.append(t)
    return res[:TIER_A_MAX]
