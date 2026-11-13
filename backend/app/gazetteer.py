"""Places on the Moon, and linking spoken mentions to them.

Mentions come from Arc Tagger entity spans (its *types* are unreliable for lunar names, so they are ignored) or from
plain text. Linking: exact alias match first, then fuzzy matching with rapidfuzz, which also catches ASR spellings
such as "Oriental" or "Hertzprung".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


@dataclass
class Place:
    id: str
    name: str
    lat: float
    lon: float
    diameter_km: float
    fact: str
    estimated: bool = False
    aliases: list[str] = field(default_factory=list)


class Gazetteer:
    def __init__(self, path: Path):
        raw = json.loads(path.read_text())
        self.places = {p["id"]: Place(**p) for p in raw["places"]}
        self._keys: list[tuple[str, str]] = []  # (normalized alias, place id)
        for p in self.places.values():
            for a in {p.name, *p.aliases}:
                self._keys.append((norm(a), p.id))
        self._names = [k for k, _ in self._keys]

    def match_text(self, text: str) -> Place | None:
        """Longest alias contained in the text, on word boundaries."""
        t = f" {norm(text)} "
        best, best_len = None, 0
        for key, pid in self._keys:
            if len(key) > best_len and re.search(rf"(?<![a-z0-9]){re.escape(key)}", t):
                best, best_len = self.places[pid], len(key)
        return best

    def link(self, mention: str, cutoff: float = 82) -> tuple[Place, float] | None:
        """Fuzzy link one mention (e.g. a tagger span) to a place."""
        m = norm(mention)
        if len(m) < 3:
            return None
        hit = process.extractOne(m, self._names, scorer=fuzz.ratio, score_cutoff=cutoff)
        if not hit:
            return None
        _, score, idx = hit
        return self.places[self._keys[idx][1]], score
