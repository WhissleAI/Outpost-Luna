"""The crew-audio index built by pipeline/build_index.py (data/index/clips.json)."""
from __future__ import annotations

import json
from pathlib import Path


class MomentIndex:
    def __init__(self, path: Path):
        self.path = path
        self._mtime = None
        self.clips: list[dict] = []
        self.refresh()

    def refresh(self) -> None:
        """Reload when `make index` rewrites the file, so a rebuild needs no restart."""
        m = self.path.stat().st_mtime if self.path.exists() else None
        if m != self._mtime:
            self.clips = json.loads(self.path.read_text())["clips"] if m else []
            self._mtime = m

    def best_for(self, place_id: str) -> dict | None:
        """The clip that mentions the place most, starting a little before its first mention."""
        best, best_n = None, 0
        for c in self.clips:
            hits = [t for t in c["tags"] if t.get("f") == place_id]
            if len(hits) > best_n:
                best, best_n = (c, hits[0]), len(hits)
        if not best:
            return None
        c, first = best
        return {"id": c["id"], "t": c["words"][first["i"]][0], "mentions": best_n}

    def places_mentioned(self) -> set[str]:
        return {t["f"] for c in self.clips for t in c["tags"] if t.get("f")}
