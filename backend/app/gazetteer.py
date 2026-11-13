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


# Contractions keep their 's ("what's" -> "what s", which the Director's rules expect); other 's is possessive.
_KEEP_S = {"it", "what", "that", "there", "here", "who", "where", "let", "he", "she", "name", "how", "when", "why"}
_POSS = re.compile(r"\b([a-z0-9]+)['\u2019]s\b")
_NUMWORDS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight",
             "9": "nine", "10": "ten", "11": "eleven", "12": "twelve", "13": "thirteen", "14": "fourteen",
             "15": "fifteen", "16": "sixteen", "17": "seventeen"}


def norm(s: str) -> str:
    s = _POSS.sub(lambda m: m.group(0) if m.group(1) in _KEEP_S else m.group(1), s.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


ARTIFACT_FIELDS = ("mission", "agency", "landed", "status", "story", "what_it_did", "science", "crew", "sources",
                   "voices", "image")


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
    kind: str = "feature"  # "feature" (a named landform) | "artifact" (hardware left on the Moon, artifacts.json)
    # Artifact-only fields (empty for features). `type` is lander|rover|impact|instrument|memorial (artifacts.json `kind`).
    type: str = ""
    mission: str = ""
    agency: str = ""
    landed: str = ""
    status: str = ""
    story: str = ""
    what_it_did: str = ""
    science: str = ""
    crew: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    voices: list[dict] = field(default_factory=list)
    image: str | None = None

    def public(self) -> dict:
        """The /api/places item: features keep the old shape plus `kind`; artifacts add their fields."""
        d = {k: getattr(self, k) for k in ("id", "name", "lat", "lon", "diameter_km", "fact", "estimated", "aliases",
                                           "kind")}
        if self.kind == "artifact":
            d["artifact_kind"] = self.type
            d.update({k: getattr(self, k) for k in ARTIFACT_FIELDS})
        return d


def _spoken_variants(alias: str) -> set[str]:
    """'Apollo 16 rover' -> also 'apollo sixteen rover' (ASR and kids say numbers as words)."""
    a = norm(alias)
    out = {a}
    words = [_NUMWORDS.get(w, w) for w in a.split()]
    out.add(" ".join(words))
    return out


KIND_WORDS = {"lander": ["lander", "lunar module", "landing site"], "rover": ["rover", "moon buggy", "buggy"],
              "impact": ["impact", "crash site", "impact site"]}


def load_artifacts(path: Path) -> list[Place]:
    """artifacts.json -> Places with kind 'artifact'. `fact` is the story, so the claim-check fallback says it verbatim."""
    if not path.exists():
        return []
    out = []
    for a in json.loads(path.read_text()):
        crew = {norm(c) for c in a.get("crew", [])} | {norm(c).split()[-1] for c in a.get("crew", []) if c.strip()}
        aliases = set()
        for al in [a["name"], *a.get("aliases", [])] + [f"{a.get('mission', '')} {w}" for w in KIND_WORDS.get(a["kind"], [])]:
            if norm(al) and norm(al) not in crew:  # crew names belong to the features (e.g. Armstrong -> Tranquility)
                aliases |= _spoken_variants(al)
        aliases.discard(norm(a["name"]))
        out.append(Place(id=a["id"], name=a["name"], lat=float(a["lat"]), lon=float(a["lon"]), diameter_km=0,
                         fact=a.get("story", ""), aliases=sorted(aliases), kind="artifact", type=a["kind"],
                         **{k: a.get(k, [] if k in ("crew", "sources", "voices") else "") for k in ARTIFACT_FIELDS
                            if k != "image"}, image=a.get("image")))
    return out


class Gazetteer:
    def __init__(self, path: Path, artifacts: Path | None | bool = True, features_only: bool = False):
        """Features from places.json, plus artifacts.json next to it (artifacts=False or features_only skips them)."""
        raw = json.loads(path.read_text())
        self.places = {p["id"]: Place(**p) for p in raw["places"]}
        if artifacts and not features_only:
            for a in load_artifacts(path.parent / "artifacts.json" if artifacts is True else artifacts):
                self.places[a.id] = a
        self._keys: list[tuple[str, str]] = []  # (normalized alias, place id)
        for p in self.places.values():
            for a in {p.name, *p.aliases}:
                self._keys.append((norm(a), p.id))
        self._names = [k for k, _ in self._keys]

    @property
    def features(self) -> list[Place]:
        return [p for p in self.places.values() if p.kind == "feature"]

    @property
    def artifacts(self) -> list[Place]:
        return [p for p in self.places.values() if p.kind == "artifact"]

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

    def candidates(self, mention: str, floor: float = 75, limit: int = 3) -> list[tuple[Place, float]]:
        """Best fuzzy score per place for one mention, highest first (for the Director's ask band)."""
        m = norm(mention)
        if len(m) < 3:
            return []
        best: dict[str, float] = {}
        for _, score, idx in process.extract(m, self._names, scorer=fuzz.ratio, score_cutoff=floor, limit=30):
            pid = self._keys[idx][1]
            best[pid] = max(best.get(pid, 0), score)
        return [(self.places[p], s) for p, s in sorted(best.items(), key=lambda x: -x[1])[:limit]]
