"""Build data/index/clips.json from word-timed transcripts, using Arc Tagger through the model server.

Per clip:
  - Arc Tagger (domain `news`) over the words: entity spans -> FEATURE (after linking), number spans -> NUMBER,
    utterance ends and speaker changes -> boundaries for cutting moments.
  - Linking: every entity span is linked to the gazetteer with rapidfuzz; spans that don't link are dropped
    (the tagger finds mentions well but types lunar names as person/org, so types are ignored).
  - A name-only fallback catches lunar names the tagger missed (src "gazetteer").
  - COLOR / GEO_TERM / DIRECTION / AWE are still small rule lists (src "rules"); a lunar tagger domain replaces them.

  uv run python -m pipeline.build_index          # model server must be running (make models)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.config import settings  # noqa: E402
from app.gazetteer import Gazetteer, norm  # noqa: E402

RULES = [
    ("COLOR", r"^(yellow|brown|tan|gr[ae]y|green|blue|orange|bright|dark)"),
    ("GEO_TERM", r"^(albedo|ejecta|limb|relief|craters?|regolith|mountains?|plateau|rays?|swirls?|walls|terrain|"
                 r"hummocky|terminator|dust|pillowing|blanketing|boulder\w*|contact)$"),
    ("DIRECTION", r"^(northwest|north|south|east|eastern|west|western|center|middle|near|far|boundary|latitude)$"),
    ("AWE", r"^(wow|amazing|beautiful|fascinating|gosh|kidding)$"),
]
DESCRIPTOR_ALIASES = {"yellow", "brightest", "shiny", "snow", "bullseye", "target", "rings", "ring", "rays", "splash",
                      "swirl", "tadpole", "gamma", "spaceship", "spacecraft", "water", "biggest", "largest", "oldest",
                      "island", "face", "rains", "crises", "crisis", "monarch", "landed", "footprint", "orion", "pole"}


def words_of(path: Path) -> list[list]:
    """[[t, word, speaker, t1], ...] from a Deepgram (transcripts_dg) or Whisper (transcripts) transcript.

    Index 0 = start time and 1 = word stay fixed for the frontend; speaker is -1 when unknown (Whisper).
    """
    d = json.loads(path.read_text())
    return [[round(w["start"], 2), w["word"].strip(), w.get("speaker", -1), round(w.get("end", w["start"]), 2)]
            for s in d["segments"] for w in s.get("words", []) if w["word"].strip()]


def transcript_for(stem: str, whisper_only: bool = False) -> tuple[Path, str]:
    """Prefer the Deepgram transcript; fall back to Whisper."""
    dg = settings.data_dir / "transcripts_dg" / f"{stem}.json"
    if dg.exists() and not whisper_only:
        return dg, "deepgram"
    return settings.data_dir / "transcripts" / f"{stem}.json", "whisper"


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    whisper_only = "--whisper" in argv  # A/B against the old transcripts
    dest = settings.data_dir / ("index/clips_whisper.json" if whisper_only else "index/clips.json")
    gaz = Gazetteer(settings.data_dir / "places.json")
    names = {}
    for p in gaz.places.values():
        for a in {p.name, *p.aliases}:
            k = norm(a)
            if " " not in k and len(k) >= 5 and k not in DESCRIPTOR_ALIASES:
                names[k] = p.id
    manifest = json.loads((settings.data_dir / "clips_manifest.json").read_text())["clips"]
    http = httpx.Client(base_url=settings.model_server_url, timeout=30)
    try:
        http.get("/health").raise_for_status()
    except httpx.HTTPError:
        sys.exit(f"Model server not reachable at {settings.model_server_url}. Start it with `make models`.")

    out = []
    stats = {"arc_links": 0, "arc_unlinked": 0, "gazetteer_fallback": 0, "numbers": 0, "clips": 0, "words": 0,
             "deepgram": 0, "whisper": 0, "skipped": 0}
    for c in manifest:
        tx, src = transcript_for(c["stem"], whisper_only)
        if not tx.exists():
            stats["skipped"] += 1
            continue
        words = words_of(tx)
        if not words:
            stats["skipped"] += 1
            continue
        stats[src] += 1
        stats["clips"] += 1
        stats["words"] += len(words)
        r = http.post("/v1/tag", json={"words": [w[1] for w in words], "domain": "news"})
        r.raise_for_status()
        arc = r.json()
        tags: dict[int, dict] = {}
        for s in arc["spans"]:
            if s["family"] == "entity":
                hit = gaz.link(s["text"])
                if hit:
                    tags.setdefault(s["start"], {"i": s["start"], "type": "FEATURE", "label": hit[0].name,
                                                 "f": hit[0].id, "src": "arc", "p": round(s["score"], 2)})
                    stats["arc_links"] += 1
                else:
                    stats["arc_unlinked"] += 1
            elif s["family"] == "number" and s["type"] != "entity.numeral":
                tags.setdefault(s["start"], {"i": s["start"], "type": "NUMBER", "label": s["text"],
                                             "kind": s["type"].split(".")[-1], "src": "arc"})
                stats["numbers"] += 1
        for i, w in enumerate(w[1] for w in words):
            if i in tags:
                continue
            k = norm(w)
            if k in names:
                p = gaz.places[names[k]]
                tags[i] = {"i": i, "type": "FEATURE", "label": p.name, "f": p.id, "src": "gazetteer"}
                stats["gazetteer_fallback"] += 1
                continue
            for typ, pat in RULES:
                if re.search(pat, k):
                    tags[i] = {"i": i, "type": typ, "label": k, "src": "rules"}
                    break
        utts = [[u["start"], u["end"]] for u in arc.get("utterances", [])]
        events = [{"type": e.get("type"), "i": e.get("word", e.get("at"))} for e in arc.get("events", [])
                  if e.get("type") in ("speaker.change", "discourse.turn_yield")]
        # Diarization: speaker changes between consecutive words are cut points too.
        events += [{"type": "speaker.change", "i": i, "src": "deepgram"} for i in range(1, len(words))
                   if words[i][2] >= 0 and words[i][2] != words[i - 1][2]]
        events.sort(key=lambda e: (e["i"] is None, e["i"] or 0))
        speakers = sorted({w[2] for w in words if w[2] >= 0})
        out.append({"id": c["id"], "title": c["title"], "file": f"/media/audio/{c['stem']}.mp3",
                    "url": c.get("url"), "set": c.get("set"), "transcript": src, "speakers": speakers,
                    "dur": round(words[-1][3] + 1), "words": words, "tags": [tags[i] for i in sorted(tags)],
                    "utterances": utts, "events": events, "tagger_ms": arc.get("ms")})
        stats["places"] = stats.get("places", 0) + sum(t["type"] == "FEATURE" for t in tags.values())
        print(f"{c['id']:<36} {src:<8} {len(words):>5} words  {len(speakers)} spk  {len(utts):>3} utterances  "
              f"{sum(t['type'] == 'FEATURE' for t in tags.values()):>3} places  {arc.get('ms')} ms")
    dest.parent.mkdir(parents=True, exist_ok=True)
    built = "deepgram nova-3 (whisper fallback) + arc-tagger v0.3 + gazetteer link"
    dest.write_text(json.dumps({"built_with": "whisper + arc-tagger v0.3 + gazetteer link" if whisper_only else built,
                                "stats": stats, "clips": out}, separators=(",", ":")))
    print(f"wrote {dest} | {stats}")


if __name__ == "__main__":
    main()
