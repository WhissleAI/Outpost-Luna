"""Fact-sheet entries for the hardware in artifacts.json, so the claim check can verify numbers in their stories.

Every sentence of an artifact's story / what_it_did / science becomes a fact carrying its numbers. Those texts were
written from the pages in the item's `sources` (each number appears there), so the source names those pages (minus
the LROC coordinate table, which only backs lat/lon).

  uv run python -m pipeline.artifact_facts      # rewrites the artifact entries in data/facts.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.claims import numbers_in  # noqa: E402
from app.config import settings  # noqa: E402

SENT = re.compile(r"(?<=[.!?])\s+")


def entries(artifacts: list[dict]) -> dict:
    out = {}
    for a in artifacts:
        titles = [x["title"] for x in a.get("sources", []) if "Coordinates of Lunar" not in x["title"]]
        src = "; ".join(titles or [x["title"] for x in a.get("sources", [])]) or "artifacts.json"
        facts, seen = [], set()
        for field in ("story", "what_it_did", "science"):
            for s in (x.strip() for x in SENT.split(a.get(field) or "") if x.strip()):
                if s not in seen:
                    seen.add(s)
                    facts.append({"text": s, "source": src, "numbers": sorted({int(v) if v == int(v) else v
                                                                          for _, v in numbers_in(s)})})
        out[a["id"]] = {"name": a["name"], "type": a["kind"], "artifact": True, "mission": a.get("mission", ""),
                        "lat": a["lat"], "lon": a["lon"], "side": "near" if abs(a["lon"]) <= 90 else "far",
                        "facts": facts}
    return out


def main() -> None:
    arts = json.loads((settings.data_dir / "artifacts.json").read_text())
    path = settings.data_dir / "facts.json"
    d = json.loads(path.read_text())
    d["places"] = {k: v for k, v in d["places"].items() if not v.get("artifact")} | entries(arts)
    J = lambda x: json.dumps(x, ensure_ascii=False)  # noqa: E731 - same compact layout as the hand-written file
    items = list(d["places"].items())
    lines = ["{", f'  "_note": {J(d["_note"])},', '  "places": {']
    for n, (pid, v) in enumerate(items):
        head = ", ".join(f"{J(k)}: {J(x)}" for k, x in v.items() if k != "facts")
        facts = ",\n".join(f"        {J(f)}" for f in v.get("facts", []))
        lines.append(f'    {J(pid)}: {{\n      {head},\n      "facts": [\n{facts}\n      ]\n    }}'
                     + ("," if n < len(items) - 1 else ""))
    path.write_text("\n".join(lines + ["  }", "}"]) + "\n")
    print(f"{len(arts)} artifacts -> {path}")


if __name__ == "__main__":
    main()
