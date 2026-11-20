"""The entity layer (docs/ENTITY_LAYER.md): one registry of named things, per-moment ear lists derived from it, and a
session memory of what was talked about. App-agnostic: an app supplies its registry file (and, optionally, a resolver
from its own domain ids, e.g. a gazetteer, to registry ids)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .context import Moment, dedupe_aliases, ear_list, scores
from .memory import EntityMemory
from .registry import SCHEMA, Entity, Registry, toks

DATA = Path(__file__).resolve().parents[2] / "data" / "entities"
APP_REGISTRY = DATA / "outpost_luna.json"

__all__ = ["SCHEMA", "Entity", "Registry", "EntityMemory", "Moment", "ear_list", "scores", "dedupe_aliases", "toks",
           "registry"]


@lru_cache(maxsize=1)
def registry() -> Registry:
    """The active course's registry (app/courses.py manifest `entities`; the Moon: data/entities/outpost_luna.json)."""
    try:
        from .. import courses
        return Registry.load(courses.path("entities") or APP_REGISTRY)
    except Exception:   # noqa: BLE001  (a broken course file never takes the ear's names list down)
        return Registry.load(APP_REGISTRY)
