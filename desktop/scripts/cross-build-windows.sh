#!/usr/bin/env bash
# Outpost Luna desktop: the Windows x64 installer, cross-built on a Mac (or Linux). An ALTERNATIVE to the primary,
# native path (desktop/scripts/build-windows.ps1 on a Windows PC, docs/BUILD_WINDOWS.md); same 8 steps, same inputs.
# The result has never run here: it is checked structurally (step 8) and must still be smoke-tested on Windows.
#
#   bash desktop/scripts/cross-build-windows.sh                 # everything -> desktop/dist/Outpost Luna Setup <v>.exe
#   SKIP_MEDIA=1 bash desktop/scripts/cross-build-windows.sh    # backend/data/media already in place
#   MAC_APP="/Applications/Outpost Luna.app" bash desktop/scripts/cross-build-windows.sh   # + parity vs a Mac build
#   DIR_ONLY=1 KEEP_INTERMEDIATES=1 bash desktop/scripts/cross-build-windows.sh   # unpacked app only, kept (no 7z pass)
#
# What differs from the native build, and why it is the same app:
#   python    python-build-standalone x86_64-pc-windows-msvc (the release `uv python install` picks; SHA256SUMS-checked)
#   packages  `uv pip install --python-platform x86_64-pc-windows-msvc`: the same locked versions, win_amd64 wheels
#   bytecode  compiled by this machine's CPython 3.11 (a .pyc depends on the Python version, not the OS)
#   arctag    arctag.dll from mingw-w64 gcc (AVX2 + FMA kernels, CPU-checked at load) instead of MSVC (scalar kernels)
#   libarc    arc.dll (the ear) from the same mingw-w64 gcc; ONNX Runtime is the Python wheel's, loaded by path at run time
#   assets    none bundled: the models, voice pack, crew audio and videos are first-run downloads (desktop/assets.manifest.json)
#   exe       electron-builder writes the NSIS installer; without Wine it cannot edit the .exe's icon / version
#             resources (signAndEditExecutable: false): the app shows Electron's default icon and file details.
# Needs: Node 22+, uv, CMake, mingw-w64 (brew install mingw-w64) or zig (brew install zig), 7-Zip (brew install
# sevenzip) for the installer check. About 5 GB free while it runs (0.3: no models bundled); intermediates are deleted at the end.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
T0=$(date +%s)
step() { printf '\n==> [%s] %s\n' "$(( $(date +%s) - T0 ))s" "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

export UV_CACHE_DIR="$ROOT/desktop/build/uv-cache"
export ELECTRON_CACHE="$ROOT/desktop/build/cache/electron"
export ELECTRON_BUILDER_CACHE="$ROOT/desktop/build/cache/electron-builder"
export npm_config_cache="$ROOT/desktop/build/cache/npm"
export CSC_IDENTITY_AUTO_DISCOVERY=false   # unsigned (docs/DESKTOP.md: Authenticode)
export PYTHONUTF8=1

step "1/8 prerequisites"
case "$(uname -s)" in Darwin|Linux) ;; *) die "on Windows use desktop/scripts/build-windows.ps1";; esac
command -v node >/dev/null  || die "Node missing: brew install node@22"
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
[ "$NODE_MAJOR" -ge 22 ] || die "Node $NODE_MAJOR found, need 22+"
command -v uv >/dev/null    || die "uv missing: curl -LsSf https://astral.sh/uv/install.sh | sh"
command -v cmake >/dev/null || die "CMake missing: brew install cmake"
if command -v x86_64-w64-mingw32-gcc >/dev/null; then CC_WIN=(x86_64-w64-mingw32-gcc); RC_WIN=x86_64-w64-mingw32-windres
elif command -v zig >/dev/null; then CC_WIN=(zig cc -target x86_64-windows-gnu); RC_WIN=""
else die "no Windows C compiler: brew install mingw-w64 (or brew install zig)"; fi
SEVENZ=$(command -v 7zz || command -v 7z || true)
FREE_GB=$(df -Pk "$ROOT" | awk 'NR==2{print int($4/1048576)}')
[ "$FREE_GB" -ge "${MIN_FREE_GB:-5}" ] || die "only ${FREE_GB} GB free; the cross-build needs about 5 GB while it runs (MIN_FREE_GB overrides)"
echo "node $(node -v), $(uv --version), $(cmake --version | head -1), compiler ${CC_WIN[*]}, 7-Zip ${SEVENZ:-none}, ${FREE_GB} GB free"
if [ -d desktop/resources/python/bin ]; then echo "note: desktop/resources holds a macOS build; it is replaced (build-mac.sh rebuilds it)"; fi

step "2/8 NASA media (backend/data/media: the Moon map ships; the crew clips are a first-run asset, see make asset-pack)"
if [ "${SKIP_MEDIA:-0}" = 1 ]; then echo "skipped (SKIP_MEDIA=1)"
else uv run --no-project --with pillow==11.3.0 python backend/pipeline/fetch_media.py; fi
[ -s backend/data/media/img/moon4k.jpg ] || die "backend/data/media is incomplete (re-run; fetch_media.py resumes)"

step "3/8 frontend dependencies"
(cd frontend && npm ci --no-audit --no-fund && node tools/fetch_vision.mjs)

step "4/8 embedded Python for Windows + win_amd64 packages + VC++ runtime + app code (frontend build included)"
uv run --no-project python backend/tools/voice_pack_check.py --allow-empty   # the voice pack ships to Windows too
uv run --no-project python desktop/scripts/build_python.py --target win-x64

step "5/8 first-run assets: nothing bundled (desktop/assets.manifest.json lists them; the app downloads them)"
python3 -c "import json,sys; m=json.load(open('desktop/assets.manifest.json')); miss=[a['id'] for a in m['assets'] if a['required'] and not a.get('url') and not a.get('fallback')]; sys.exit('assets without a download link: %s (make asset-pack asset-upload)' % miss if miss else 0)"
rm -rf desktop/resources/models   # an older build's bundled models

step "6/8 native libraries (arctag.dll: Arc Tagger; arc.dll: the ear; mingw-w64)"
rm -rf desktop/build/arctag-win desktop/build/libarc-win desktop/resources/native
CC=${CC_WIN[0]}
if [ "${#CC_WIN[@]}" -gt 1 ]; then   # zig: CMake wants one executable as the compiler
  mkdir -p desktop/build && CC="$ROOT/desktop/build/zig-cc-win"
  printf '#!/bin/sh\nexec zig cc -target x86_64-windows-gnu "$@"\n' > "$CC" && chmod +x "$CC"
fi
CMAKE_RC=()
[ -n "$RC_WIN" ] && CMAKE_RC=(-DCMAKE_RC_COMPILER="$RC_WIN")
cmake -S desktop/vendor/arctag -B desktop/build/arctag-win -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_C_COMPILER="$CC" "${CMAKE_RC[@]+"${CMAKE_RC[@]}"}" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build desktop/build/arctag-win --config Release
mkdir -p desktop/resources/native
DLL=$(ls desktop/build/arctag-win/arctag.dll desktop/build/arctag-win/libarctag.dll 2>/dev/null | head -1 || true)
[ -n "$DLL" ] || die "arctag.dll was not produced (see the CMake output above)"
cp "$DLL" desktop/resources/native/arctag.dll
cmake -S desktop/vendor/libarc -B desktop/build/libarc-win -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_C_COMPILER="$CC" "${CMAKE_RC[@]+"${CMAKE_RC[@]}"}" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build desktop/build/libarc-win --config Release
DLL=$(ls desktop/build/libarc-win/arc.dll desktop/build/libarc-win/libarc.dll 2>/dev/null | head -1 || true)
[ -n "$DLL" ] || die "arc.dll was not produced (see the CMake output above)"
cp "$DLL" desktop/resources/native/arc.dll
uv run --no-project python desktop/scripts/win_bundle_check.py dlls desktop/resources/native >/dev/null \
  || die "arctag.dll / arc.dll imports a DLL Windows does not have (see: python desktop/scripts/win_bundle_check.py dlls desktop/resources/native)"

step "7/8 Electron + electron-builder (NSIS installer, Windows x64)"
cd desktop
npm ci --no-audit --no-fund
rm -rf dist/win-unpacked
EDIT=()
command -v wine >/dev/null || command -v wine64 >/dev/null || EDIT=(-c.win.signAndEditExecutable=false)   # no Wine: no icon / version edit
# The 7z pass (-mx=9 over ~2 GB) is the slow part: ~20 min on an idle Mac, hours on a saturated one. Do not use
# compression=store to skip it: the payload is then 2.08 GB, past NSIS's 2 GB installer limit, and makensis stalls.
# DIR_ONLY=1: only dist/win-unpacked (minutes, not the 7z pass): enough for every step-8 check except the installer's.
if [ "${DIR_ONLY:-0}" = 1 ]; then
  npx electron-builder --win dir --x64 --publish never "${EDIT[@]+"${EDIT[@]}"}"
else
  npx electron-builder --win nsis --x64 --publish never "${EDIT[@]+"${EDIT[@]}"}"
fi
cd "$ROOT"
EXE=""
if [ "${DIR_ONLY:-0}" != 1 ]; then
  EXE=$(ls -t desktop/dist/Outpost\ Luna\ Setup\ *.exe | head -1)
  [ -n "$EXE" ] || die "no installer in desktop/dist"
  cp -f "$EXE" desktop/dist/Outpost-Luna-win-x64.exe   # the stable GitHub release asset name (site + README link it)
fi

step "8/8 structural checks (the installer cannot run here)"
uv run --no-project python desktop/scripts/win_bundle_check.py dlls desktop/dist/win-unpacked/resources
uv run --no-project python desktop/scripts/win_bundle_check.py speech desktop/dist/win-unpacked/resources   # WinRT + SAPI speech packages
uv run --no-project python desktop/scripts/win_bundle_check.py runtime desktop/dist/win-unpacked/resources  # every runtime file
# The installer's payload must stay under NSIS's 2 GB limit (it is the uncompressed app the 7z archive holds).
PAYLOAD_MB=$(du -sk desktop/dist/win-unpacked | awk '{print int($1/1024)}')
echo "win-unpacked: ${PAYLOAD_MB} MB uncompressed, $(find desktop/dist/win-unpacked -type f | wc -l | tr -d ' ') files (NSIS limit: 2048 MB per installer)"
if [ -n "$SEVENZ" ] && [ -n "$EXE" ]; then
  # The NSIS installer holds the app as app-64.7z: unpack both and check that what the user installs is the same tree.
  X="$ROOT/desktop/build/installer-check"; rm -rf "$X"; mkdir -p "$X"
  "$SEVENZ" x -y -o"$X/nsis" "$EXE" >/dev/null
  "$SEVENZ" x -y -o"$X/app" "$X/nsis/\$PLUGINSDIR/app-64.7z" >/dev/null
  diff -rq "$X/app/resources" desktop/dist/win-unpacked/resources >/dev/null \
    && echo "installer payload == win-unpacked ($(find "$X/app" -type f | wc -l | tr -d ' ') files)" \
    || die "the installer's payload differs from dist/win-unpacked"
  [ -f "$X/app/Outpost Luna.exe" ] || die "the installer has no Outpost Luna.exe"
  rm -rf "$X"
elif [ -z "$EXE" ]; then echo "DIR_ONLY=1: no installer built, so it was not unpacked"
else echo "7-Zip not found: the installer itself was not unpacked (brew install sevenzip)"; fi
if [ -n "${MAC_APP:-}" ]; then
  uv run --no-project python desktop/scripts/win_bundle_check.py compare "$MAC_APP/Contents/Resources" desktop/dist/win-unpacked/resources
fi
# Keep only the installer: the unpacked app, the Python tree and the caches are several GB.
if [ "${KEEP_INTERMEDIATES:-0}" != 1 ]; then
  rm -rf desktop/dist/win-unpacked desktop/dist/builder-debug.yml desktop/dist/*.blockmap desktop/build/uv-cache \
         desktop/build/cache desktop/build/arctag-win desktop/build/libarc-win desktop/build/uv-python desktop/build/py-unpack
fi
if [ -n "$EXE" ]; then
  ls -lh "$EXE"
  echo "Installer: $ROOT/$EXE  ($(( $(date +%s) - T0 )) s). Cross-built: run it on Windows before shipping (docs/BUILD_WINDOWS.md §5)."
else echo "Unpacked app checked ($(( $(date +%s) - T0 )) s; DIR_ONLY=1, KEEP_INTERMEDIATES=1 keeps dist/win-unpacked)."; fi
