# Outpost Luna desktop app

One installable app that runs with **no internet**: the Electron shell, an embedded CPython, the backend, the model
server and every model weight ship inside the installer. macOS arm64 is built and tested. Windows x64 is written but
**untested** (see below).

```
Outpost Luna.app / Outpost Luna.exe
 └─ Electron main process (desktop/main/main.js)
     ├─ splash "Warming up the models…" until both health checks pass
     ├─ python launch.py models  --port 47210   model_server (Arc Tagger, Arc v1.1 Mini ear + metadata, Steer TTS, MiniLM)
     ├─ python launch.py backend --port 47310   backend (API + /media + the built frontend at /)
     └─ BrowserWindow -> http://127.0.0.1:47310/
```

## Build (macOS)

```
make data                 # once: NASA media into backend/data/media (or copy it from another checkout)
make desktop-mac          # desktop-python + desktop-models + desktop-arctag + electron-builder -> desktop/dist/*.dmg
```

| target | what it does |
|---|---|
| `make desktop-python` | `desktop/scripts/build_python.py`: python-build-standalone 3.11 via `uv python install`; `uv export --frozen` of `backend/uv.lock` and `model_server/uv.lock` installed with `uv pip install --target` into `site/backend` and `site/models` (two folders because the numpy pins differ: 2.x vs 1.26); the vendored `arc-transcriber` and `steertts-edge` wheels; trims (stdlib tests, tk, `torch/include`, `torch/share`, `tests/`, `*.pyi`, static libs); precompiles bytecode with `--invalidation-mode unchecked-hash`; stages `backend/app`, `backend/data` (no media or caches), `model_server/app`, `frontend/dist` |
| `make desktop-models` | `desktop/scripts/gather_models.py`: copies every weight into `desktop/resources/models/` and checks it against `desktop/models.lock.json` (sha256 per file) |
| `make desktop-arctag` | CMake build of `desktop/vendor/arctag` (arc-tagger-c sources, native backend only) -> `libarctag.dylib` / `arctag.dll` |
| `make desktop-run` | run the shell against `desktop/resources` without packaging |
| `make desktop-clean` | delete `desktop/resources`, `desktop/build`, `desktop/dist` |

Caches stay in the tree: `desktop/build/uv-cache`, `desktop/build/uv-python`, and `ELECTRON_CACHE` / `ELECTRON_BUILDER_CACHE`
if you point them at `desktop/build/cache`. A full build needs about 5 GB free (resources 1.1 GB, unpacked app 1.9 GB,
dmg 1.0 GB, caches); `rm -rf desktop/dist/mac-arm64` after the dmg is made.

PyInstaller was not used: two separate servers with torch, onnxruntime and ctypes-loaded native libraries are simpler as
a plain relocatable interpreter plus `--target` folders; nothing is frozen, so tracebacks and the logs stay readable.

## What is in the bundle (macOS arm64, 0.1.0)

`Contents/Resources/` (unpacked app 1.9 GB; dmg 1.00 GB, since mp3 and weights barely compress):

| path | size | contents |
|---|---|---|
| `python/` | 60 MB | CPython 3.11 (python-build-standalone), trimmed |
| `site/models/` | 817 MB | torch 2.11 CPU (333), transformers 5.19 (115), onnxruntime (85), scipy (68), numpy 1.26, sympy, fastapi/uvicorn, arc-transcriber 1.2.1, steertts-edge 1.3.0, … |
| `site/backend/` | 50 MB | fastapi, uvicorn, httpx, websockets, rapidfuzz, numpy 2.x |
| `app/backend/app` | 1.1 MB | backend code, incl. `director_model/weights.json` + `weights.npz` (learned Director, numpy only) |
| `app/backend/data` | 9 MB | places, facts, glossary, index (clips + moments), transcripts, mission and academy data (read-only) |
| `app/backend/data/media` | 525 MB | 74 Artemis II crew clips (522 MB mp3) + Moon colour map (2.5 MB); mapped straight from `backend/data/media` |
| `app/model_server` | 0.2 MB | model-server code |
| `app/frontend` | 0.7 MB | `frontend/dist` |
| `app/launch.py` | 4 KB | child entry point |
| `models/arc-v1.1/mini` | 68 MB | Arc v1.1 Mini: `model.q4.safetensors`, `heads.safetensors`, `tags.json`, `config.json`, `moonshine-streaming-tiny/` |
| `models/minilm` | 22 MB | all-MiniLM-L6-v2 `model.int8.onnx` + `tokenizer.json` (the fp32 `model.onnx` is not shipped) |
| `models/arctag` | 12 MB | Arc Tagger v0.3 `arctag_int8.onnx`, `arctag_meta.json`, `tokenizer.json` |
| `models/steer-tts-edge` | 12 MB | Steer TTS Edge v1: `onnx/{enc,dec,voc}.onnx`, `spkproj.safetensors`, `front/`, `voices.*`, `config.json`, `director.bin` |
| `native/libarctag.dylib` | 0.2 MB | built from `desktop/vendor/arctag` |
| Electron framework | ~300 MB | Electron 44.10.0 |

Arc v1.1 `backbone="mini"` pulls **no other Hugging Face snapshot**: `mini/` carries its own Moonshine Streaming tiny
encoder, decoder and tokenizer, and `Arc.from_pretrained` only downloads when given a repo id (we always pass a folder).
`full/` (74 MB) is not shipped.

## Where things go at run time

| | macOS | Windows |
|---|---|---|
| app (read-only) | `/Applications/Outpost Luna.app/Contents/Resources` | `%LOCALAPPDATA%\Programs\Outpost Luna\resources` |
| writable data | `~/Library/Application Support/Outpost Luna/` | `%APPDATA%\Outpost Luna\` |

Under the writable folder: `logs/{main,models,backend}.log`, `cache/{vectors,tts}` (backend `CACHE_DIR`),
`children.json` (child pids), `ports.json` (last ports), `hf/` (an empty `HF_HOME`), and Chromium's own state. Nothing is
written inside the bundle: the app runs from a read-only dmg mount.

The env vars the shell sets for the children (also usable by hand):

| model server | backend |
|---|---|
| `ARCTAG_LIB`, `ARCTAG_MODEL_DIR`, `ARC_META_WEIGHTS`, `STEER_TTS_MODEL`, `STEER_DIRECTOR`, `EMBED_MODEL_DIR` | `DATA_DIR`, `CACHE_DIR`, `FRONTEND_DIST`, `MODEL_SERVER_URL`, `CORS_ORIGINS`, `TTS_ENGINE=steer` |

Both get `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `PYTHONNOUSERSITE=1`,
`PYTHONDONTWRITEBYTECODE=1`, and an environment built from an allow-list (PATH, HOME, TEMP, …), so **no API key from the
launching shell reaches them**; `launch.py` also drops `DEEPGRAM_API_KEY`, `NASA_API_KEY`, `HF_TOKEN` and similar keys.
The build refuses to bundle any `.env*` file. With no defaults changed, `make dev` keeps its old paths (Head Start's
`libarctag`, the HF cache resolved through `HF_HOME` / `HF_HUB_CACHE`, `model_server/models/minilm`).

## Offline guarantees

- **Ear:** `/ws/listen` uses the local Arc ear. Deepgram is only a fallback when the ear is down *and* a key is set; with
  no key it sends `{"t":"error"}` and closes (fails closed).
- **TTS:** Steer TTS Edge on the model server; the Deepgram fallback needs a key, otherwise the browser voice.
- **NASA data:** baked into `backend/data` (no NASA API calls at run time; `NASA_API_KEY` is only for the offline pipeline).
- **Renderer:** every request that is not our backend origin (or `data:`, `blob:`) is cancelled by
  `session.webRequest` and logged as `blocked` in `main.log`. Today that means the Google Fonts stylesheet in
  `frontend/index.html` (and `a11y.js`'s Atkinson Hyperlegible): it fails at once and the UI falls back to system fonts.
  Follow-up for the frontend owner: self-host those fonts (e.g. `@fontsource/*`) so the offline app looks like the web app.
  External links open in the system browser (they will not load offline, which is fine).
- **Mic:** the permission handler grants audio capture only to `http://127.0.0.1:<backend port>`; everything else
  (camera, location, notifications, other origins) is denied. `NSMicrophoneUsageDescription` is in `Info.plist`.

## Process supervision

- Ports: last used (`ports.json`), else 47310 / 47210, 47311 / 47211, …, else OS-chosen. Keeping them stable keeps the UI
  origin, and so its `localStorage` (settings, Flight School progress), the same across runs.
  `OUTPOST_BACKEND_PORT` / `OUTPOST_MODELS_PORT` override.
- Children are spawned `detached` (own process group) on POSIX; quitting sends SIGTERM to the group, then SIGKILL after
  4 s. On Windows, `taskkill /PID <pid> /T /F`.
- `children.json` records the pids; the next start kills any still-running pid whose command line is our launcher
  (guards against pid reuse), then clears the file.
- `launch.py` exits when its parent (Electron) dies: tested by crashing Electron, which left no Python behind.
- A child that exits is restarted (up to 3 times a minute), then an error dialog points at the logs.
- Single instance: a second launch focuses the existing window.

## Tested on this Mac (macOS 26.2, Apple Silicon), 2026-11-13

The packaged app, run from the **read-only mounted dmg**, with the network blocked for Electron and both children by
`sandbox-exec -f desktop/scripts/offline.sb` (loopback only; Chromium's inner sandbox cannot nest under sandbox-exec,
so this test run used `--no-sandbox`; a normal launch keeps it), no keys in the environment:

| | |
|---|---|
| installer (`Outpost Luna-0.1.0-arm64.dmg`) | **1.00 GB** |
| unpacked `.app` | **1.9 GB** |
| cold start to window (launch -> models healthy -> UI shown) | **15.9 s** (models healthy at 13.7 s); the first run straight after a build was ~24 s to models healthy |
| RAM, steady after a voice turn | **~1.23 GB** total: model server 578 MB, backend 101 MB, Electron main + helpers ~550 MB |
| voice ask (`say "show me the giant bullseye"`, 16 kHz) | Arc ear heard *"show me the giant bull's eye."*; turn end 0.56 s after speech end |
| answer | `/api/ask` 73 ms: "The Sea of Rains, Mare Imbrium, is about 1,146 km across." |
| Steer TTS | 200 `audio/wav`, 330 KB, 376 ms |
| Flight School | course (8 lessons); lesson `moon` step graded; check ride started |
| Mission cabin | shift started at Shackleton Rim, `shields +5` order, shift advanced, debrief |
| quit | both children got SIGTERM and exited; `children.json` emptied; no stray processes |

Re-run: `PYTHONPATH=desktop/resources/site/backend desktop/resources/python/bin/python3 desktop/scripts/smoke.py --base http://127.0.0.1:47310`.

## Signing and notarization (macOS, later)

Now: ad-hoc signature (`identity: "-"`), no hardened runtime. Gatekeeper blocks a downloaded copy until the user
right-clicks > Open (or `xattr -dr com.apple.quarantine "/Applications/Outpost Luna.app"`). To ship:

1. An Apple Developer Program membership and a **Developer ID Application** certificate (.p12) -> CI secrets
   `CSC_LINK` (base64 p12) and `CSC_KEY_PASSWORD`; drop `identity: "-"` and `CSC_IDENTITY_AUTO_DISCOVERY=false`.
2. `hardenedRuntime: true` with `build-resources/entitlements.mac.plist` (audio input, JIT, unsigned executable memory,
   disable library validation: needed by the embedded CPython, torch and the ctypes-loaded `libarctag`).
3. electron-builder signs every Mach-O under `Resources/` (the Python tree has hundreds of `.so`/`.dylib`); expect the
   first signed build to surface a few that need `--deep`-style handling, and keep `.pyc` precompiled so nothing is written.
4. Notarization: an App Store Connect API key (`APPLE_API_KEY` .p8, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER`) or
   `APPLE_ID` + `APPLE_APP_SPECIFIC_PASSWORD` + `APPLE_TEAM_ID`; set `mac.notarize: true`. Stapling is automatic.

## Windows (written, untested)

Everything below is **untested**: no Windows machine was available.

- `build_python.py`: `python.exe` at the install root, `Lib/` trimming, `npm run build` via `shell=True`.
- `arctag.py`: loads `arctag.dll` with `os.add_dll_directory` + `winmode=0`. `desktop/vendor/arctag/CMakeLists.txt` builds it with
  `ARCTAG_BUILD_SHARED` (dllexport). With MSVC, `native.c` takes its scalar kernels (MSVC has no `__x86_64__`):
  correct but slower than AVX2; `-T ClangCL` would get the AVX2 path. Model paths go to the C library as UTF-8, so an
  install path with non-ASCII characters may fail to open the model.
- Supervisor: `taskkill /T /F`, `tasklist` for stale-pid checks, `windowsHide`; the parent watchdog uses
  `OpenProcess` + `WaitForSingleObject`.
- PyPI's Windows torch wheels are CPU-only already. `soundfile` ships its own libsndfile DLL.
- `fetch_media.sh` converts the Moon map with `sips` or `ffmpeg`; the Windows runner may lack both (copy `moon4k.jpg` in, or add
  an ffmpeg step).
- NSIS per-user install, unsigned: SmartScreen warns. Authenticode needs an OV/EV code-signing certificate
  (`WIN_CSC_LINK` / `WIN_CSC_KEY_PASSWORD`, or Azure Trusted Signing).

## CI (`.github/workflows/desktop.yml`)

Matrix `macos-14` (dmg) and `windows-latest` (NSIS), on `workflow_dispatch` or a `desktop-v*` tag; uploads the installers
as artifacts. It creates no secrets and is not triggered by pushes to branches. It needs:

| | |
|---|---|
| `secrets.HF_TOKEN` | read token for the private WhissleAI model repos |
| `vars.DESKTOP_MODELS_REPO` (recommended) | a private HF model repo holding `desktop/resources/models` exactly as gathered here: `HF_TOKEN=<write token> python desktop/scripts/gather_models.py --upload WhissleAI/outpost-luna-desktop-models` (run by a person, once per model change) |
| `desktop/vendor/wheels/*.whl` | `arc_transcriber-1.2.1` (145 KB) and `steertts_edge-1.3.0` (54 KB), built by `build_python.py --build-wheels`; not committed yet |

Why a bundle repo: the upstream HF repos do not have the versions the app runs. `WhissleAI/arc-v1.1@6f63715` is
identical to the local cache, but `WhissleAI/arc-tagger` only has v0.4.0 / v0.4.1 (the app ships v0.3 from Head Start,
and its `arctag_int8.onnx` differs), and `WhissleAI/steer-tts-edge`'s history was squashed to v2.x (the local v1
snapshot `a888162` no longer exists on the Hub, and steertts-edge 1.3.0 needs the v1 graphs). Without
`DESKTOP_MODELS_REPO` the workflow fetches upstream with `DESKTOP_MODELS_STRICT=0` and the installer would carry
different Arc Tagger and Steer weights (and no MiniLM).

## Follow-ups

- Arc ear without torch: an ONNX export of Arc v1.1 Mini (trunk + Moonshine tiny) would drop torch, transformers and
  sympy (~490 MB unpacked) and cut model-server RAM.
- Trim `transformers/models/*` to the few the app imports (~90 MB).
- Re-encode the crew clips (522 MB of mp3) at a speech bitrate (e.g. 48 kbps mono): about 4x smaller.
- Self-hosted fonts (frontend owner), an app icon (`build-resources/icon.icns` / `.ico`), auto-update (out of scope offline).
