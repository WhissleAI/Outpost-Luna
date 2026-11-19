#!/bin/bash
# Stage everything the iPad app embeds, into ios/build/ (git-ignored). Run once before xcodebuild, and again after
# changing the backend, its data or the frontend:
#
#   bash ios/scripts/build_python.sh
#
#   build/Python.xcframework                 CPython 3.13 for iOS (BeeWare Python-Apple-support, PEP 730), pinned
#   build/stage/app/luna_ios.py              the in-process launcher (ios/python/luna_ios.py)
#   build/stage/app/backend/{app,data}       the backend, as in the desktop bundle (no media, no caches)
#   build/stage/app/frontend/                frontend/dist (built here if missing)
#   build/stage/app_packages.<sdk>/          site-packages per SDK (iphonesimulator / iphoneos): the backend's
#                                            locked pure-Python deps, numpy (BeeWare iOS wheel), pydantic-core
#                                            (cross-compiled: build_pydantic_core.sh)
#
# The Xcode "Install Python" phase copies the right app_packages into the app and turns every .so into a framework
# (Python.xcframework/build/utils.sh), as Apple requires. Nothing here touches the desktop build.
set -euo pipefail
IOS=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(cd "$IOS/.." && pwd)
B=$IOS/build
mkdir -p "$B/dl" "$B/stage"

fetch() {  # url sha256 out
  if [ ! -f "$3" ] || [ "$(shasum -a 256 "$3" | cut -d' ' -f1)" != "$2" ]; then
    echo "download $(basename "$3")"
    curl -fsSL "$1" -o "$3.part" && mv "$3.part" "$3"
  fi
  [ "$(shasum -a 256 "$3" | cut -d' ' -f1)" = "$2" ] || { echo "sha256 mismatch: $3"; exit 1; }
}

# 1. CPython for iOS
PAS=$B/dl/Python-3.13-iOS-support.b18.tar.gz
fetch https://github.com/beeware/Python-Apple-support/releases/download/3.13-b18/Python-3.13-iOS-support.b18.tar.gz \
  d06acf2a9c7964a8689566353a0e707402eff822037de5e29ba0e16040f7047d "$PAS"
if [ ! -d "$B/Python.xcframework" ]; then
  rm -rf "$B/pas" && mkdir -p "$B/pas" && tar -xzf "$PAS" -C "$B/pas"
  mv "$B/pas/Python.xcframework" "$B/" && rm -rf "$B/pas"
fi

# 2. numpy for iOS (BeeWare's index; numpy's own PyPI release has no iOS wheels for cp313)
NP=https://pypi.anaconda.org/beeware/simple/numpy/2.5.2.post1
fetch $NP/numpy-2.5.2.post1-cp313-cp313-ios_17_0_arm64_iphonesimulator.whl \
  ccd6094209e59b21a432e5815a790289abbbe7f4249f28895adceba2d01f037b "$B/dl/numpy-iphonesimulator.whl"
fetch $NP/numpy-2.5.2.post1-cp313-cp313-ios_17_0_arm64_iphoneos.whl \
  9fd06cac5ce4ba16decd52c189b5046cb727a36a9a1e50dbd3cc38c512cac1a3 "$B/dl/numpy-iphoneos.whl"

# 3. the backend's locked deps, minus numpy (step 2) and the optional speedups iOS can't load
#    (uvloop, httptools, watchfiles: uvicorn falls back to asyncio + h11; pyyaml: log config only).
#    rapidfuzz and websockets ship C speedups with pure-Python fallbacks: their macOS .so files are dropped below.
REQ=$B/requirements.txt
(cd "$ROOT/backend" && uv export --frozen --no-dev --no-hashes --no-emit-project) \
  | grep -E '^[a-z]' | grep -vE '^(numpy|uvloop|httptools|watchfiles|pyyaml|colorama)==' | sed 's/ ;.*//' > "$REQ"
rm -rf "$B/pure"
uv pip install --quiet --target "$B/pure" --no-deps --python-version 3.13 --python-platform aarch64-apple-darwin \
  --only-binary :all: -r "$REQ"
find "$B/pure" \( -name "*.so" -o -name "*.pyi" \) -delete
find "$B/pure" -type d -empty -delete
find "$B/pure" -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -rf "$B/pure/bin"

# 4. pydantic-core (Rust) for both SDKs
bash "$IOS/scripts/build_pydantic_core.sh" "$B" "$B/pydantic_core-out"

for SDK in iphonesimulator iphoneos; do
  D=$B/stage/app_packages.$SDK
  rm -rf "$D" && mkdir -p "$D"
  rsync -a "$B/pure/" "$D/"
  (cd "$D" && unzip -q -o "$B/dl/numpy-$SDK.whl")
  cp "$B/pydantic_core-out/$SDK/"*.so "$D/pydantic_core/"
done

# 5. the app: launcher, backend, frontend
A=$B/stage/app
rm -rf "$A" && mkdir -p "$A/backend"
cp "$IOS/python/luna_ios.py" "$A/"
rsync -a --exclude "__pycache__" "$ROOT/backend/app" "$A/backend/"
rsync -a --exclude "__pycache__" --exclude "media" --exclude "cache" --exclude "tts_cache" --exclude "video_cache" \
  --exclude "saves" --exclude "turnlog" --exclude "learning_state" --exclude "video/local" \
  "$ROOT/backend/data" "$A/backend/"
# the Moon map (2.5 MB, the one NASA image that ships, as on the desktop): `make data` fetches it from nasa.gov
MOON=${MOON_MAP:-$ROOT/backend/data/media/img/moon4k.jpg}
[ -f "$MOON" ] || { echo "no Moon map at $MOON: run make data (or set MOON_MAP=<moon4k.jpg>)"; exit 1; }
mkdir -p "$A/backend/data/media/img" && cp "$MOON" "$A/backend/data/media/img/moon4k.jpg"
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then (cd "$ROOT/frontend" && npm run build); fi
rsync -a "$ROOT/frontend/dist/" "$A/frontend/"
du -sh "$B/Python.xcframework" "$B/stage/"*
