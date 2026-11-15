"""CI check: every fixed line in the voice pack manifest has a recorded clip (docs/VOICE_PACK.md).

    make voice-pack-check     (= python3 backend/tools/voice_pack_check.py)

Exit 0: complete. Exit 1: lines without a clip (listed), clips that don't match their checksum, or no index at all.
Exit 0 with a note when --allow-empty and nothing is recorded yet. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1] / "data" / "voice_pack"


def problems(pack: Path = PACK) -> tuple[list[str], list[str], int, float]:
    """(missing line texts, bad clip files, clips recorded, MB)."""
    lines = json.loads((pack / "lines.json").read_text(encoding="utf-8"))["lines"]
    try:
        clips = json.loads((pack / "index.json").read_text(encoding="utf-8")).get("clips", {})
    except (OSError, ValueError):
        clips = {}
    missing, bad, size = [], [], 0
    for l in lines:
        e = clips.get(l["key"])
        if not e:
            missing.append(l["text"])
            continue
        f = pack / e["file"]
        try:
            b = f.read_bytes()
        except OSError:
            missing.append(l["text"])
            continue
        size += len(b)
        if hashlib.sha256(b).hexdigest() != e.get("sha256"):
            bad.append(e["file"])
    return missing, bad, len(clips), size / 1e6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-empty", action="store_true", help="pass when nothing is recorded yet")
    a = ap.parse_args()
    missing, bad, n, mb = problems()
    total = len(json.loads((PACK / "lines.json").read_text(encoding="utf-8"))["lines"])
    if n == 0 and a.allow_empty:
        print(f"voice pack: nothing recorded yet ({total} lines): `make voice-pack` on a Mac with Siri Voice 1")
        return 0
    for t in missing[:50]:
        print("  no clip:", t)
    if len(missing) > 50:
        print(f"  … and {len(missing) - 50} more")
    for f in bad:
        print("  checksum mismatch:", f)
    print(f"voice pack: {total - len(missing)}/{total} lines recorded, {len(bad)} bad clips, {mb:.1f} MB")
    return 1 if missing or bad else 0


if __name__ == "__main__":
    sys.exit(main())
