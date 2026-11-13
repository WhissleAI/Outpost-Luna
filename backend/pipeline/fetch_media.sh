#!/usr/bin/env bash
# Downloads the NASA Moon color map and the Artemis II crew clips used by the app.
set -euo pipefail
cd "$(dirname "$0")/../data"
mkdir -p media/audio media/img ../../.cache
UA="Mozilla/5.0"
B=https://www.nasa.gov/wp-content/uploads
CLIPS=(
  2026/10/art002a000005-ck-vg-relief-color-audio
  2026/10/art002a00003708-clipped
  2026/10/art002a000025-reid-tourist
  2026/10/art002a000024-clipped
  2026/10/art002a000015-omg-stop-it
  2026/01/artemis-ii-names-new-craters-integrity-and-carroll
)
for p in "${CLIPS[@]}"; do
  f=media/audio/$(basename "$p").mp3
  [ -s "$f" ] || { echo "↓ $f"; curl -fsSL -A "$UA" -o "$f" "$B/$p.mp3"; }
done
if [ ! -s media/img/moon4k.jpg ]; then
  echo "↓ LRO color map (4K, from NASA SVS CGI Moon Kit)"
  curl -fsSL -o ../../.cache/moon4k.tif https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_4k.tif
  if command -v sips >/dev/null; then sips -s format jpeg -s formatOptions 80 ../../.cache/moon4k.tif --out media/img/moon4k.jpg >/dev/null
  else ffmpeg -loglevel error -y -i ../../.cache/moon4k.tif -q:v 3 media/img/moon4k.jpg; fi
fi
echo "Done."
