#!/usr/bin/env bash
# Downloads the NASA Moon color map and the Artemis II crew clips used by the app.
set -euo pipefail
cd "$(dirname "$0")/../data"
mkdir -p media/audio media/img ../../.cache
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# Clip URLs come from clips_manifest.json (rebuild it with `python -m pipeline.scrape_manifest`).
python3 -c 'import json; [print(c["stem"], c["url"]) for c in json.load(open("clips_manifest.json"))["clips"]]' |
while read -r stem url; do
  f=media/audio/$stem.mp3
  [ -s "$f" ] || { echo "↓ $f"; curl -fsSL -A "$UA" -o "$f.part" "$url" && mv "$f.part" "$f"; }
done
if [ ! -s media/img/moon4k.jpg ]; then
  echo "↓ LRO color map (4K, from NASA SVS CGI Moon Kit)"
  curl -fsSL -o ../../.cache/moon4k.tif https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_4k.tif
  if command -v sips >/dev/null; then sips -s format jpeg -s formatOptions 80 ../../.cache/moon4k.tif --out media/img/moon4k.jpg >/dev/null
  else ffmpeg -loglevel error -y -i ../../.cache/moon4k.tif -q:v 3 media/img/moon4k.jpg; fi
fi
echo "Done."
