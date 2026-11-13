"""Rebuild data/clips_manifest.json from NASA's Artemis Audio page (https://www.nasa.gov/artemisaudio/).

Takes every clip in the two "NEW Artemis II Lunar Flyby Recordings" sets (shorter + extended) plus the
existing hand-picked entries, which keep their ids and stems (the frontend and backend refer to them).

  curl -sL -A "Mozilla/5.0 ..." -o /tmp/artemisaudio.html https://www.nasa.gov/artemisaudio/
  uv run python -m pipeline.scrape_manifest /tmp/artemisaudio.html
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "clips_manifest.json"
SETS = {"NEW Artemis II Lunar Flyby Recordings (Shorter)": "shorter",
        "NEW Artemis II Lunar Flyby Recordings (Extended)": "extended",
        "Artemis II Lunar Flyby": "flyby"}
TOKEN = re.compile(r'<h([1-4])[^>]*>(.*?)</h\1>|href="(https://www\.nasa\.gov/wp-content/uploads/[^"]+\.mp3)"', re.S)


def parse(page: str) -> list[dict]:
    """[{set, title, url, stem}] in page order, for the sections in SETS."""
    out, section, title = [], None, None
    for m in TOKEN.finditer(page):
        if m.group(3):
            if section and title:
                url = m.group(3)
                out.append({"set": section, "title": title, "url": url, "stem": url.rsplit("/", 1)[1][:-4]})
            title = None
            continue
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
        if m.group(1) == "3":
            section = SETS.get(text)
        elif text:
            title = re.sub(r" ment Data$", "", text)  # stray CMS text on one NASA title
    return out


def slug(title: str, n: int = 4) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower().replace("’", "").replace("'", ""))
    stop = {"and", "the", "of", "a", "to", "from", "in", "on", "for", "as", "ment", "data"}
    return "-".join([w for w in words if w not in stop][:n])


def build(page: str, existing: list[dict]) -> list[dict]:
    by_stem = {c["stem"]: c for c in existing}
    rows = parse(page)
    flyby = [r for r in rows if r["set"] in ("shorter", "extended")]
    flyby += [r for r in rows if r["set"] == "flyby" and r["stem"] in by_stem]  # keep the old picks from this set
    seen_ids = {c["id"] for c in existing}
    clips = []
    for r in flyby:
        old = by_stem.get(r["stem"])
        if old:
            cid = old["id"]
        else:
            base = cid = slug(r["title"])
            k = 2
            while cid in seen_ids:
                cid, k = f"{base}-{k}", k + 1
            seen_ids.add(cid)
        clips.append({"id": cid, "stem": r["stem"], "title": r["title"], "set": r["set"], "url": r["url"]})
    missing = set(by_stem) - {c["stem"] for c in clips}
    if missing:
        raise SystemExit(f"existing clips not found on the page: {sorted(missing)}")
    return clips


def main() -> None:
    page = Path(sys.argv[1]).read_text()
    existing = json.loads(MANIFEST.read_text())["clips"]
    clips = build(page, existing)
    MANIFEST.write_text('{"source": "https://www.nasa.gov/artemisaudio/", "clips": [\n'
                        + ",\n".join(" " + json.dumps(c, ensure_ascii=False) for c in clips) + "\n]}\n")
    print(f"wrote {MANIFEST}: {len(clips)} clips "
          f"({sum(c['set'] == 'shorter' for c in clips)} shorter, {sum(c['set'] == 'extended' for c in clips)} extended)")


if __name__ == "__main__":
    main()
