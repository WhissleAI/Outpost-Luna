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
TITLE_NAMES = ["Byrgius Alpha", "Mare Humorum", "Reiner Gamma", "Aristarchus Plateau", "Orientale", "Hertzsprung",
               "Vavilov", "Glushko", "Ohm", "Integrity", "Carroll", "Earthrise", "Earthset"]
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
    names = [_clean(p.name) for p in gaz.places.values()]
    aliases = [a.title() if a != "artemis iii" else "Artemis III" for p in gaz.places.values() for a in p.aliases
               if a in PROPER_ALIASES]
    return _dedupe(names + aliases + TITLE_NAMES + CREW + JARGON)


def clip_keyterms(title: str, gaz: Gazetteer) -> list[str]:
    """Names in the clip's NASA title first (they're the likeliest in the audio), then the base list."""
    t = norm(title)
    in_title = [n for n in TITLE_NAMES + [_clean(p.name) for p in gaz.places.values()]
                if re.search(rf"\b{re.escape(norm(n))}\b", t)]
    return _dedupe(in_title + base_keyterms(gaz))
