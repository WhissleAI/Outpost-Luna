"""The entity registry: every named thing an app knows, one record per thing (docs/ENTITY_LAYER.md).

App-agnostic: nothing here knows about the Moon. An app ships one registry file (JSON, schema "whissle.entities/1"):

    {"schema": "whissle.entities/1", "app": "...",
     "screens": {"<screen>": {"cap": 40, "groups": [["<group>", <limit>?], ...]} | {"same_as": "<screen>"}},
     "default_screen": "<screen>",
     "entities": [{
        "id": "tycho",                 stable id: what lessons, missions, story beats and the UI reference
        "type": "place",               place | site | hardware | mission | crew | spacecraft | control | unit | lesson ...
        "group": "place",              the screen profiles pick by group, in this file's order (= rank)
        "name": "Tycho",               canonical name: what the ear's list and the UI show
        "kind": "lunar_feature",       the ear's kind (arc.h kinds)
        "aliases": ["Tycho crater"],   other names, said as written; sent to the ear (biasing AND linking)
        "spoken": [...],               spoken forms ("Sea of Rain"); sent to the ear like aliases
        "mishears": ["tie co"],        what the ear hears for it: NEVER sent to the ear; they make the app ASK
        "related": ["copernicus"],     ids
        "lessons": ["moon"], "states": ["storm"], "screens": [...], "exclude_screens": [...],
        "ear": true,                   false: not a name the ear should link (controls, units, lessons)
        "ref": {"source": "places.json", "id": "tycho"}   where the domain payload lives
     }]}

The registry holds identity (names, forms, relations, relevance); domain payloads (coordinates, facts, physics) stay
in the files `ref` points to, so nothing is stored twice.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "whissle.entities/1"


def toks(s: str) -> str:
    """Lower-case words joined by single spaces: the form every match compares."""
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    name: str
    group: str = ""
    kind: str = "place"
    aliases: tuple[str, ...] = ()
    spoken: tuple[str, ...] = ()
    mishears: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    lessons: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    exclude_screens: tuple[str, ...] = ()
    ear: bool = True
    ref: dict | None = field(default=None, hash=False, compare=False)
    rank: int = 0

    def forms(self) -> list[str]:
        """Name, aliases and spoken forms: what the entity is CALLED (mishears are not names)."""
        return [self.name, *self.aliases, *self.spoken]

    def ear_entry(self) -> dict:
        """The ear's names-list entry ({"name", "kind", "aliases"?})."""
        al = [a for a in [*self.spoken, *self.aliases] if a.lower() != self.name.lower()]
        al = [a for i, a in enumerate(al) if a.lower() not in {b.lower() for b in al[:i]}]
        e = {"name": self.name, "kind": self.kind}
        if al:
            e["aliases"] = al
        return e


class Registry:
    def __init__(self, data: dict):
        if data.get("schema") != SCHEMA:
            raise ValueError(f"not a {SCHEMA} registry: {data.get('schema')!r}")
        self.app = data.get("app")
        self.screens: dict = data.get("screens") or {}
        self.default_screen = data.get("default_screen")
        ents = []
        for i, x in enumerate(data.get("entities") or []):
            ents.append(Entity(
                id=x["id"], type=x["type"], name=x["name"], group=x.get("group") or x["type"], kind=x.get("kind", "place"),
                aliases=tuple(x.get("aliases") or ()), spoken=tuple(x.get("spoken") or ()),
                mishears=tuple(x.get("mishears") or ()), related=tuple(x.get("related") or ()),
                lessons=tuple(x.get("lessons") or ()), states=tuple(x.get("states") or ()),
                screens=tuple(x.get("screens") or ()), exclude_screens=tuple(x.get("exclude_screens") or ()),
                ear=bool(x.get("ear", True)), ref=x.get("ref"), rank=i))
        self.entities: list[Entity] = ents
        self.by_id: dict[str, Entity] = {}
        for e in ents:
            if e.id in self.by_id:
                raise ValueError(f"duplicate entity id {e.id!r}")
            self.by_id[e.id] = e
        self._by_form: dict[str, list[str]] = {}
        for e in ents:
            for f in e.forms():
                k = toks(f)
                if k and e.id not in self._by_form.setdefault(k, []):
                    self._by_form[k].append(e.id)
        self._mishear: dict[str, str] = {}
        for e in ents:
            for m in e.mishears:
                self._mishear.setdefault(toks(m), e.id)
        self._forms_by_len = sorted(self._by_form, key=lambda k: -len(k))

    @classmethod
    def load(cls, path: str | Path) -> "Registry":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- lookups ----
    def get(self, eid: str | None) -> Entity | None:
        return self.by_id.get(eid or "")

    def resolve(self, name: str | None, prefer: tuple[str, ...] = ()) -> Entity | None:
        """The entity CALLED this (name, alias or spoken form; case and punctuation ignored). When two share a form,
        the one whose type is in `prefer` (in that order), else the first in the file."""
        ids = self._by_form.get(toks(name or ""))
        if not ids:
            return None
        for t in prefer:
            for i in ids:
                if self.by_id[i].type == t:
                    return self.by_id[i]
        return self.by_id[ids[0]]

    def by_ref(self, source: str, rid: str) -> Entity | None:
        for e in self.entities:
            if e.ref and e.ref.get("source") == source and e.ref.get("id") == rid:
                return e
        return None

    def mentions(self, text: str, types: tuple[str, ...] | None = None) -> list[Entity]:
        """Entities NAMED in the text (longest form first, non-overlapping, in text order)."""
        t = f" {toks(text)} "
        if not t.strip():
            return []
        used: list[tuple[int, int]] = []
        hits: list[tuple[int, Entity]] = []
        for k in self._forms_by_len:
            i = t.find(f" {k} ")
            while i >= 0:
                a, b = i + 1, i + 1 + len(k)
                if not any(a < y and x < b for x, y in used):
                    for eid in self._by_form[k]:
                        e = self.by_id[eid]
                        if types is None or e.type in types:
                            used.append((a, b))
                            hits.append((a, e))
                            break
                i = t.find(f" {k} ", i + 1)
        out, seen = [], set()
        for _, e in sorted(hits, key=lambda h: h[0]):
            if e.id not in seen:
                seen.add(e.id)
                out.append(e)
        return out

    def mishear_of(self, text: str) -> tuple[Entity, str] | None:
        """A known mishearing of an entity in the text ("the jelly" -> de Gerlache): (entity, the words)."""
        t = f" {toks(text)} "
        for k in sorted(self._mishear, key=len, reverse=True):
            if k and f" {k} " in t:
                return self.by_id[self._mishear[k]], k
        return None

    # ---- screens ----
    def profile(self, screen: str | None) -> dict:
        s = screen if screen in self.screens else self.default_screen
        p = self.screens.get(s) or {}
        seen = set()
        while "same_as" in p and p["same_as"] not in seen:
            seen.add(p["same_as"])
            p = self.screens.get(p["same_as"]) or {}
        return p

    def screen_entities(self, screen: str | None) -> list[Entity]:
        """What the screen is about, in weight order (its profile's groups, each group in file order)."""
        p = self.profile(screen)
        out: list[Entity] = []
        have: set[str] = set()
        for g in p.get("groups") or []:
            grp, lim = g[0], (g[1] if len(g) > 1 else None)
            xs = [e for e in self.entities if e.group == grp and e.ear and screen not in e.exclude_screens]
            for e in xs[:lim]:
                if e.id not in have:
                    have.add(e.id)
                    out.append(e)
        return out

    def cap(self, screen: str | None, default: int = 40) -> int:
        return int(self.profile(screen).get("cap") or default)
