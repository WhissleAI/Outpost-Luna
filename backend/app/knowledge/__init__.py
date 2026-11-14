"""The local brain: knowledge cards (what to say) + a tiny embedder in the model server (what the kid means).
No cloud LLM. See docs/LOCAL_BRAIN.md."""
from __future__ import annotations

from ..config import settings
from ..gazetteer import Gazetteer
from .answer import Brain
from .cards import build

_BRAIN: dict = {}


def get(gaz: Gazetteer, facts: dict) -> Brain:
    """One Brain per gazetteer (built from the same data files; cheap, no model calls)."""
    b = _BRAIN.get(id(gaz))
    if b is None:
        b = _BRAIN[id(gaz)] = Brain(build(gaz, facts, settings.data_dir), settings.data_dir / "cache")
    return b
