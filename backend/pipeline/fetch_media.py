"""Download the NASA media the app uses into backend/data/media (make data). Cross-platform; no bash, curl or sips.

    python backend/pipeline/fetch_media.py            # stdlib only for the clips; Pillow for the Moon map conversion:
    uv run --no-project --with pillow==11.3.0 python backend/pipeline/fetch_media.py

  media/audio/<stem>.mp3   the Artemis II crew clips listed in backend/data/clips_manifest.json (rebuild that with
                           `python -m pipeline.scrape_manifest`)
  media/img/moon4k.jpg     the LRO colour map (4K TIFF from the NASA SVS CGI Moon Kit) as JPEG, quality 80

Files that already exist (non-empty) are kept, so a re-run only fetches what is missing. Downloads go to <name>.part
first and are renamed when complete. Exit 1 if anything failed.

The originals stay as downloaded (the dev app and the pipelines use them). The desktop builds then run
pipeline/trim_media.py (`make media-desktop`) for the installer's copy: only the playable stretches, mono 48 kbps.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
CACHE = Path(__file__).resolve().parents[2] / ".cache"
MOON_TIF = "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_4k.tif"
# NASA's CDN refuses requests without a browser User-Agent.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 "
      "Safari/537.36")


def fetch(url: str, dst: Path, tries: int = 3) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                for b in iter(lambda: r.read(1 << 20), b""):
                    f.write(b)
            if tmp.stat().st_size == 0:
                raise OSError("empty response")
            tmp.replace(dst)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"  ! {dst.name}: {e} (try {attempt}/{tries})", flush=True)
            tmp.unlink(missing_ok=True)
            time.sleep(2 * attempt)
    return False


def moon_map(out: Path) -> bool:
    if out.exists() and out.stat().st_size:
        return True
    try:
        from PIL import Image
    except ImportError:
        print("  ! Pillow is needed to convert the Moon map: "
              "uv run --no-project --with pillow==11.3.0 python backend/pipeline/fetch_media.py")
        return False
    tif = CACHE / "moon4k.tif"
    print("↓ LRO color map (4K, from NASA SVS CGI Moon Kit)", flush=True)
    if not (tif.exists() and tif.stat().st_size) and not fetch(MOON_TIF, tif):
        return False
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(tif) as im:
        out.parent.mkdir(parents=True, exist_ok=True)
        im.convert("RGB").save(out, "JPEG", quality=80)
    return True


def main() -> int:
    clips = json.loads((DATA / "clips_manifest.json").read_text())["clips"]
    failed = []
    for c in clips:
        f = DATA / "media/audio" / f"{c['stem']}.mp3"
        if f.exists() and f.stat().st_size:
            continue
        print(f"↓ {f.relative_to(DATA)}", flush=True)
        if not fetch(c["url"], f):
            failed.append(f.name)
    if not moon_map(DATA / "media/img/moon4k.jpg"):
        failed.append("moon4k.jpg")
    have = len([c for c in clips if (DATA / "media/audio" / f"{c['stem']}.mp3").exists()])
    print(f"{have}/{len(clips)} clips; moon map {'ok' if (DATA / 'media/img/moon4k.jpg').exists() else 'MISSING'}")
    if failed:
        print(f"failed: {failed}")
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
