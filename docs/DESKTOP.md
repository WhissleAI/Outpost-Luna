# Outpost Luna desktop app

One installable app that runs with **no internet** once it is set up: the installer holds the Electron shell, an
embedded CPython, the backend, the model server and the native libraries; the models, the recorded voice, the crew audio
and the NASA videos are **first-run assets**, downloaded once on first launch (or imported from the offline pack; see
"First run: assets"). macOS arm64 is built and tested. Windows x64 is built and
checked file by file, but **not yet run on a Windows PC** (see below).

```
Outpost Luna.app / Outpost Luna.exe
 └─ Electron main process (desktop/main/main.js)
     ├─ first launch only: "Getting Outpost Luna ready" until the required assets are in (main/assets.js)
     ├─ splash "Warming up the models…" until both health checks pass
     ├─ python launch.py models  --port 47210   model_server (Arc Tagger, Arc v1.1 Mini ear + metadata, the OS voice, MiniLM)
     ├─ python launch.py backend --port 47310   backend (API + /media + the built frontend at /)
     └─ BrowserWindow -> http://127.0.0.1:47310/
```

## Build

Builds run locally (no CI). One command per OS, from a fresh clone, with no accounts, keys or tokens:

| | command | output |
|---|---|---|
| macOS arm64 | `bash desktop/scripts/build-mac.sh` (or `make desktop-mac`) | `desktop/dist/Outpost Luna-<version>-arm64.dmg` |
| Windows x64 (not yet run on Windows) | `powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1` | `desktop\dist\Outpost Luna Setup <version>.exe`; step-by-step in [BUILD_WINDOWS.md](BUILD_WINDOWS.md) |
| Windows x64, cross-built on a Mac | `bash desktop/scripts/cross-build-windows.sh` | the same installer, checked structurally only ([BUILD_WINDOWS.md §8](BUILD_WINDOWS.md)) |

Both scripts run the same 8 steps: check prerequisites -> NASA media (`backend/pipeline/fetch_media.py`, from nasa.gov;
only the Moon map ships) -> frontend deps -> embedded Python + app code (`build_python.py`) -> check that every required
asset in `desktop/assets.manifest.json` has a download link (nothing is bundled) -> native libraries (CMake: Arc Tagger
`libarctag`, and `libarc`, the ear) -> Electron + electron-builder -> print the installer path. Caches stay in `desktop/build/`.

## First run: assets

`desktop/assets.manifest.json` lists every downloadable asset: one deterministic ustar `.tar` each, with its public
Dropbox link (`dl=1`), sha256, size, every file inside (path + size) and its licence files. `make asset-pack`
(`scripts/asset_pack.py`) builds the tars + the offline zip and rewrites the manifest; `make asset-upload`
(`scripts/upload_assets.py`, `DROPBOX_TOKEN_FILE=<file>`, never committed) uploads them to `/Outpost Luna/assets/v2/`
with the chunked upload-session API, makes public links and checks each one anonymously.

| id | what | required | download | installed as |
|---|---|---|---|---|
| `ear` | Arc Transcriber Space `nft2/` + LICENSE + NOTICE (CC BY-NC 4.0) | yes | 461 MB | `ARC_SPACE_DIR` |
| `tagger` | Arc Tagger v0.3 int8 + LICENSE + NOTICE | yes | 12 MB | `ARCTAG_MODEL_DIR` |
| `embedder` | all-MiniLM-L6-v2 int8 ONNX (Apache-2.0) | yes | 23 MB | `EMBED_MODEL_DIR` |
| `voice` | the recorded Nora voice pack (889 clips) | yes | 14 MB | `VOICE_PACK_DIR` |
| `crew` | trimmed Artemis II crew audio + `trim.json` (NASA) | no | 175 MB | `MEDIA_AUDIO_DIR` (served as `/media/audio`) |
| `videos` | the 8 pinned NASA videos + captions + posters | no | 199 MB | `VIDEO_PACK_DIR` (copied into the video cache) |

First launch downloads **510 MB** (required) and then 375 MB more in the background; the offline zip
(`outpost-luna-assets-v2.zip`) is all six, 885 MB. The flow (`desktop/main/assets.js`, `firstrun.html`):

- Everything goes to `<userData>/assets/<id>/` (`~/Library/Application Support/Outpost Luna/assets`,
  `%APPDATA%\Outpost Luna\assets`); `state.json` records what is installed.
- Downloads resume from `assets/.dl/<file>.part` with HTTP Range, are checked against the manifest's sha256, unpacked
  into `.staging/<id>`, every file's size checked, then renamed into place (the old copy moved aside first). A failed
  check never installs. Three tries with backoff; the ear can also come straight from Hugging Face at the pinned
  revision (`fallback`) when its link fails.
- The first-run screen shows each required asset's progress, **Try again**, **Continue later** (quits; the `.part`
  files stay and resume next launch) and **Import offline pack…** (a `.zip` from Dropbox or a USB stick: its tars are
  matched by name + sha256 and installed with no network). With no network it says so and offers the pack.
- The children start as soon as the required four are in. `crew` and `videos` download in the background after the
  window opens; until then the crew clips and videos are simply not available, and a failure is retried next launch.
  With the `videos` asset the backend's own nasa.gov prefetch is off (`VIDEO_PREFETCH=0`); unpinned videos still stream.
- Every launch re-checks each installed asset's file sizes (no hashing) and re-downloads only a damaged one.
- Free disk is checked before each download (tar + unpacked size).
- Tests and demos: `OUTPOST_USER_DATA=<folder>` (whole data folder) or `OUTPOST_ASSETS_DIR=<folder>`.

The camera-gesture models (8 MB) stay in the installer: the frontend serves them from its own origin.

## Asset updates (no app build)

Models and packs update without a new installer. The manifest has two copies with the same content, written together
by `scripts/asset_manifest.py` (used by `asset_pack.py` and `upload_assets.py`; a test checks they match):

- `site/assets/manifest.json` is **published** by `bash scripts/publish_site.sh` to
  <https://whissleai.github.io/Outpost-Luna/assets/manifest.json>, the URL installed apps check (git is the control).
- `desktop/assets.manifest.json` is **bundled**: the first-run source and the offline fallback.

Schema 2: the manifest carries `version` and `published_at`; each asset `id`, `version` (bumped on every new sha256),
`url` (https, `dl=1`), `sha256`, `size`, `required`, `min_app` / `max_app` (app versions it works with), `requires`
(`[{id, min_version}]`, other assets it needs), `licence`, `files`. In the bundled copy `min_version` makes an app build
replace an older install in the foreground (an app that needs a newer ear).

The flow (`desktop/main/updates.js`):

1. **Check.** 30 s after the window opens, and from Settings -> Storage & updates -> Check for updates, the app fetches
   the remote manifest (8 s timeout) and caches it in `assets/remote-manifest.json`. Offline means nothing changes.
2. **Stage.** Each installed asset whose version or sha changed, fits this app (`min_app` / `max_app`, `requires`) and
   is not older is downloaded in the background into `assets/.dl` (resumable). The download is paced and pauses while a
   mission runs or a video streams (`GET /api/assets/busy`). It is sha256-checked, unpacked into `assets/.pending/<id>`
   and size-checked. Settings shows "Update ready: restart".
3. **Swap on the next launch**, before the children start (nothing has the files open, on Windows too): `<id>` moves
   to `.prev/<id>` and the staged copy is renamed into place, marked *trial*.
4. **Confirm or roll back.** Once the model server answers, each trial asset must pass its load check (ear:
   `arc_ear.available`; tagger and embedder: `loaded`; voice: clips > 0). A pass keeps it and deletes `.prev`. A fail,
   or the model server dying with a trial asset in place, renames `.prev/<id>` back, restarts the model server, logs
   `assets: ROLLBACK <id> vN -> vM (...)` in `main.log`, and never offers that sha256 again.

Integrity and security:
- https only, and every entry needs a sha256;
- a manifest that does not parse or validate is ignored as a whole, as is one with any URL outside the allow-list
  (dropbox.com, dropboxusercontent.com, huggingface.co, github.com / github.io / githubusercontent.com);
- a remote entry never changes where an asset is installed: `env` / `subdir` always come from the bundled manifest;
- **future hardening:** sign the manifest (e.g. minisign) and ship the public key in the app.

Offline / airgapped: the offline-pack zip carries its own `assets.manifest.json`. Importing a pack whose asset version
is newer (and fits this app) replaces the installed one; an older or same pack changes nothing.

Settings -> **Storage & updates** (`frontend/src/storage_ui.js`) lists each download's version and size, the total, the
update state, and has **Check for updates**. The backend relays the desktop's state: `GET /api/assets` reads
`ASSETS_STATE_FILE`, and `POST /api/assets/check` touches `ASSETS_CHECK_FILE`, which the main process watches. A dev
checkout answers `{managed: false}` and the section is hidden.

### How to ship an asset update

1. Build it: `make asset-pack` (all assets) or `uv run --project backend python scripts/asset_pack.py --only ear
   --no-zip`. A changed tar gets a new sha256, the next `version` and `url: null` in both manifest copies. Set
   `min_app` / `max_app` / `requires` by hand when the asset needs a particular app.
2. Upload it: `DROPBOX_TOKEN_FILE=<file holding the token> python3 scripts/upload_assets.py --only <file>.tar`. This
   uploads, makes the public `dl=1` link, verifies it anonymously and writes the URL into both copies.
3. Check: `git diff site/assets/manifest.json`, then commit (through a PR, like any change).
4. Publish: `bash scripts/publish_site.sh`. Installed apps pick it up on their next online launch and use it on the
   launch after that.

A new offline zip (`make asset-pack` without `--no-zip`) also needs uploading, so airgapped installs can get the update.

The pieces, also runnable on their own:

| target | what it does |
|---|---|
| `make desktop-python` | `desktop/scripts/build_python.py`: python-build-standalone 3.11 via `uv python install`; `uv export --frozen` of `backend/uv.lock` and `model_server/uv.lock` installed with `uv pip install --target` into `site/backend` and `site/models` (two folders because the numpy pins differ: 2.x vs 1.26); the vendored `arc-transcriber` wheel (on a Windows target also the pinned pywinrt + comtypes speech packages, checked present); trims (stdlib tests, tk, `torch/include`, `torch/share`, `tests/`, `*.pyi`, static libs, header-only `include/` dirs, and the packages nothing imports at run time: see "What the build drops"); precompiles bytecode with `--invalidation-mode unchecked-hash`; stages `backend/app`, `backend/data` (no media or caches), `model_server/app`, `frontend/dist` |
| `make data` | `backend/pipeline/fetch_media.py`: the 74 crew clips and the Moon map from nasa.gov into `backend/data/media` (resumable) |
| `make media-desktop` | `backend/pipeline/trim_media.py`: the installer's crew clips (playable stretches only, mono 48 kbps) + `trim.json` into `backend/data/media/desktop` (see "Crew audio in the installer") |
| `make asset-pack` / `make asset-upload` | the first-run assets (above) |
| `make desktop-libarc` | CMake build of `desktop/vendor/libarc` (libarc + the Arc Transcriber Space backend; ONNX Runtime loaded at run time from the Python wheel) -> `libarc.dylib` / `arc.dll` |
| `make desktop-arctag` | CMake build of `desktop/vendor/arctag` (arc-tagger-c sources, native backend only) -> `libarctag.dylib` / `arctag.dll` |
| `make desktop-run` | run the shell against `desktop/resources` without packaging |
| `make desktop-clean` | delete `desktop/resources`, `desktop/build`, `desktop/dist` |

A full build needs about 6 GB free (media 0.5 GB + its trimmed copy 0.18 GB, resources 1.0 GB, unpacked app 1.5 GB,
dmg 0.65 GB, caches);
`build-mac.sh` deletes the unpacked app once the dmg is made. The vendored wheels `desktop/vendor/wheels/
arc_transcriber-1.2.1` (145 KB) is committed (CC-BY-NC-4.0, NOTICE inside).

PyInstaller was not used: two separate servers with torch, onnxruntime and ctypes-loaded native libraries are simpler as
a plain relocatable interpreter plus `--target` folders; nothing is frozen, so tracebacks and the logs stay readable.

## What is in the bundle (macOS arm64, 0.1.0)

`Contents/Resources/` (unpacked app 1.5 GB; dmg 646 MB, since mp3 and weights barely compress; before the trims
below: 1.9 GB and ~1.0 GB):

| path | size | contents |
|---|---|---|
| `python/` | 39 MB | CPython 3.11 (python-build-standalone), trimmed (no pip / setuptools) |
| `site/models/` | 728 MB | torch 2.11 CPU (333), transformers 5.19 (115), onnxruntime (42), scipy (68), numpy 1.26, sympy, fastapi/uvicorn, arc-transcriber 1.2.1, … (on Windows also winrt-* 3.2.1 and comtypes 1.4.17 for speech) |
| `site/backend/` | 47 MB | fastapi, uvicorn, httpx, websockets, rapidfuzz, numpy 2.x |
| `app/backend/app` | 1.1 MB | backend code, incl. `director_model/weights.json` + `weights.npz` (learned Director, numpy only) |
| `app/backend/data` | 9 MB | places, facts, glossary, index (clips + moments), transcripts, mission and academy data (read-only) |
| `app/backend/data/media` | 178 MB | 74 Artemis II crew clips, trimmed to what plays, mono 48 kbps (175 MB mp3, from `backend/data/media/desktop`) + `trim.json` + Moon colour map (2.5 MB, from `backend/data/media/img`) |
| `app/model_server` | 0.2 MB | model-server code |
| `app/frontend` | 0.7 MB | `frontend/dist` |
| `app/launch.py` | 4 KB | child entry point |
| `models/arc-v1.1/mini` | 68 MB | Arc v1.1 Mini: `model.q4.safetensors`, `heads.safetensors`, `tags.json`, `config.json`, `moonshine-streaming-tiny/` |
| `models/minilm` | 22 MB | all-MiniLM-L6-v2 `model.int8.onnx` + `tokenizer.json` (the fp32 `model.onnx` is not shipped) |
| `models/arctag` | 12 MB | Arc Tagger v0.3 `arctag_int8.onnx`, `arctag_meta.json`, `tokenizer.json` |
| `native/libarctag.dylib` | 0.2 MB | built from `desktop/vendor/arctag` |
| Electron framework | ~300 MB | Electron 44.10.0 |

Arc v1.1 `backbone="mini"` pulls **no other Hugging Face snapshot**: `mini/` carries its own Moonshine Streaming tiny
encoder, decoder and tokenizer, and `Arc.from_pretrained` only downloads when given a repo id (we always pass a folder).
`full/` (74 MB) is not shipped.

### Crew audio in the installer

NASA's originals (`backend/data/media/audio`, 547 MB, 9.3 h) are 96-192 kbps stereo whose two channels are identical.
`backend/pipeline/trim_media.py` (build step 2; `make media-desktop`) writes the installer's copy to
`backend/data/media/desktop`: **175 MB, 8.1 h**.

- **What is kept.** Everything the app can ask the player to play, each span padded by 1 s and merged across gaps
  under 3 s: every moment `moments.cut_clip` makes (they tile all of a clip's words, kid-safe or not), every artifact
  `voices` span (`artifacts.json`), every lesson clip (`academy/course.json`), and the "Hear the crew say it" window
  (t - 2 .. t + 4 s) of every vocab term (`academy.vocab.terms()`). What goes is the silence between moments (a moment
  stops at its `t1`, then fades for 200 ms), so the head and tail of a clip and the long gaps in the 20-minute
  recordings. `backend/tests/test_trim_media.py` checks that every playable span fits inside one kept stretch.
- **Encoding.** Mono (the L+R average; the channels are identical, so the level is unchanged), 24 kHz, 48 kbps CBR
  MP3 (CBR seeks exactly in every browser), via the ffmpeg 7.1 + LAME in the pinned `imageio-ffmpeg==0.6.0` wheel.
  Measured against the originals: 0-1 sample offset at every checked moment, waveform correlation 0.97-1.00, RMS
  level -0.4 dB (the encoder's low-pass). ID3 tags: title, "NASA", and the nasa.gov source URL; the attribution in
  `clips.json` / `clips_manifest.json` and the app's credit line are untouched.
- **Clip time vs file time.** All data stays in the original clip's time. `trim.json` maps it:
  `segs = [[clip_t0, file_t0, len], ...]` per file; the backend adds a clip's `segs` to `GET /api/clips/<id>`, and the
  player converts only at the `<audio>` element (`frontend/src/cliptime.js`: seek, the karaoke clock, the pause at a
  sentence end, `context.playing.t`). No `trim.json` (the dev app, which serves the originals) means no `segs`.
- **Deterministic and incremental.** Same originals + data + pinned ffmpeg gives the same bytes; a clip whose source
  sha256 and kept ranges are unchanged is skipped (a re-run takes seconds). Change the index, artifacts, course or
  glossary and the next build re-cuts what moved.

### What the build drops from the Python tree

On top of the earlier trims, `build_python.py` removes, for both macOS and `--target win-x64`: pip, setuptools,
pkg_resources, `_distutils_hack` + `distutils-precedence.pth` and wheel (from the interpreter and the site folders);
pygments; networkx; hf_xet; `torch/bin/protoc*`; numpy's `f2py`; `onnxruntime/{transformers,quantization,tools}`;
each site folder's `bin/` console scripts; header-only `include/` dirs; and on macOS
`onnxruntime/capi/libonnxruntime.*.dylib` (34 MB). The reasons are in the comment above `UNUSED_PACKAGES`.

How it was checked: both children run from the trimmed tree with `python -X importtime`, through
`desktop/scripts/smoke.py` and a fresh TTS line: none of these modules is imported (the backend tries `pygments` from
`httpx._main` and falls back, as it always did: `site/backend` never had pygments). `otool -L` shows the onnxruntime
binding does not link the C-API dylib, and `lsof` shows it unmapped during inference. `torch/bin/torch_shm_manager`
stays: `import torch` refuses to start without it on macOS / Linux. Not dropped: sympy, scipy, `torch._inductor`,
`torch._dynamo`, `torch.distributed`, `torch.testing` (all imported by `import torch` itself) and `transformers/models`.
Result: `python/` 57 -> 39 MB, `site/models/` 812 -> 728 MB, `site/backend/` 48 -> 47 MB.

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
| `ARCTAG_LIB`, `ARCTAG_MODEL_DIR`, `ARC_META_WEIGHTS`, `EMBED_MODEL_DIR` (speech: `OS_TTS`, `OS_TTS_ENGINE`, `OS_TTS_LOCALE` keep their defaults) | `DATA_DIR`, `CACHE_DIR`, `FRONTEND_DIST`, `MODEL_SERVER_URL`, `CORS_ORIGINS`, `TTS_ENGINE=os` |

Both get `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `PYTHONNOUSERSITE=1`,
`PYTHONDONTWRITEBYTECODE=1`, and an environment built from an allow-list (PATH, HOME, TEMP, …), so **no API key from the
launching shell reaches them**; `launch.py` also drops `DEEPGRAM_API_KEY`, `NASA_API_KEY`, `HF_TOKEN` and similar keys.
The build refuses to bundle any `.env*` file. With no defaults changed, `make dev` keeps its old paths (Head Start's
`libarctag`, the HF cache resolved through `HF_HOME` / `HF_HUB_CACHE`, `model_server/models/minilm`).

## Offline guarantees

- **Ear:** `/ws/listen` uses the local Arc ear. Deepgram is only a fallback when the ear is down *and* a key is set; with
  no key it sends `{"t":"error"}` and closes (fails closed).
- **TTS:** the OS's own offline voices through the model server (macOS `say`; Windows WinRT, then SAPI); the app has
  no Deepgram key, so if the OS voice fails the browser voice speaks.
- **NASA data:** baked into `backend/data` (no NASA API calls at run time; `NASA_API_KEY` is only for the offline pipeline).
- **Renderer:** every request that is not our backend origin (or `data:`, `blob:`) is cancelled by
  `session.webRequest` and logged as `blocked` in `main.log`. Today that means the Google Fonts stylesheet in
  `frontend/index.html` (and `a11y.js`'s Atkinson Hyperlegible): it fails at once and the UI falls back to system fonts.
  Follow-up for the frontend owner: self-host those fonts (e.g. `@fontsource/*`) so the offline app looks like the web app.
  External links open in the system browser (they will not load offline, which is fine).
- **Mic and camera:** the permission handler grants audio and video capture only to `http://127.0.0.1:<backend port>`;
  everything else (screen capture, location, notifications, other origins) is denied. The camera is only ever
  requested when the kid turns on Settings → Camera & gestures (docs/GESTURES.md); on macOS the first request goes
  through `systemPreferences.askForMediaAccess("camera")`. `NSMicrophoneUsageDescription` and
  `NSCameraUsageDescription` are in `Info.plist`; the entitlements carry `device.audio-input` and `device.camera`.
- **Gesture models:** the MediaPipe WASM runtime and the two models (19.5 MB) are in `app/frontend/vision/`, served
  from our own origin. `build_python.py` fails the build if any is missing; `smoke.py` checks they are served with
  the right sizes.

## Speech

The app speaks with the operating system's own offline voices (docs/VOICES.md "The OS voices"); nothing is bundled
for it on macOS, and on Windows only the pywinrt / comtypes packages. The model server picks the engine at startup,
ranks this machine's voices, maps the guide / CAPCOM / Houston / story roles onto them and renders "Ready." to warm up;
`/health` → `models.tts` says which engine, voice and warm-up time. The Electron main process waits only for the two
`/health` answers, never for a speech model, and the voice bar shows "Warming up" until `models.tts.loaded` (or 3 min).
Settings → Voice lists the voices and tells parents where to download clearer ones.

### Re-tested with the OS voices, 2026-11-14 (macOS 26.2, from the mounted dmg, machine under load ~8)

| | |
|---|---|
| installer | **604 MB** (`Outpost Luna-0.1.0-arm64.dmg`, 633,453,400 bytes; Steer's model folder and wheel gone) |
| cold start to window | 17.7 s (models healthy at 17.2 s); the model server's speech warm-up ("Ready.") 2.6 s inside that |
| speech | engine `say`; default (guide) "Your Mac's system voice" = Aaron (Siri); CAPCOM Tara (Premium), Houston Aman (Premium); 25 voices ranked |
| first audio | one sentence: 1.6 s (Siri system voice), 1.5–1.7 s (Tara premium) under load; idle 1.3 s / 0.8 s. Cache hit ~3 ms |
| smoke.py | ALL PASS (health incl. `tts`, Settings voices, ear, answer, OS-voice TTS 200 `audio/wav`, 11/11 word timings ending at 4,560 of 4,601 ms, Flight School, mission, gesture assets) |

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
| installer (`Outpost Luna-0.1.0-arm64.dmg`) | **1.00 GB** (0.65 GB since the audio and Python trims) |
| unpacked `.app` | **1.9 GB** (1.5 GB since) |
| cold start to window (launch -> models healthy -> UI shown) | **15.9 s** (models healthy at 13.7 s); the first run straight after a build was ~24 s to models healthy |
| RAM, steady after a voice turn | **~1.23 GB** total: model server 578 MB, backend 101 MB, Electron main + helpers ~550 MB |
| voice ask (`say "show me the giant bullseye"`, 16 kHz) | Arc ear heard *"show me the giant bull's eye."*; turn end 0.56 s after speech end |
| answer | `/api/ask` 73 ms: "The Sea of Rains, Mare Imbrium, is about 1,146 km across." |
| TTS (then Steer) | 200 `audio/wav`, 330 KB, 376 ms |
| Flight School | course (8 lessons); lesson `moon` step graded; check ride started |
| Mission cabin | shift started at Shackleton Rim, `shields +5` order, shift advanced, debrief |
| quit | both children got SIGTERM and exited; `children.json` emptied; no stray processes |

Re-run: `PYTHONPATH=desktop/resources/site/backend desktop/resources/python/bin/python3 desktop/scripts/smoke.py --base http://127.0.0.1:47310`.

## Signing and notarization (macOS)

`build-mac.sh` has three modes, chosen by two env vars:

| env | result |
|---|---|
| (none) | ad-hoc signature. Gatekeeper blocks a downloaded copy until right-click > Open |
| `MAC_SIGN_IDENTITY="Developer ID Application: Whissle LLC (XXK95K57U5)"` | Developer ID signature with the hardened runtime and a secure timestamp. Not notarized: Gatekeeper still warns on a downloaded copy |
| `MAC_SIGN_IDENTITY=...` and `NOTARY_PROFILE=outpost-notary` | signed, notarized and stapled: the `.app` first (so a copy in /Applications opens offline), then the dmg. Ends with `spctl` checks |

```bash
# once per Mac: the Developer ID Application certificate + private key in the login keychain
security find-identity -v -p codesigning
# once per Mac: notary credentials in the keychain (app-specific password from appleid.apple.com;
# or --key AuthKey_XXXX.p8 --key-id ... --issuer ... for an App Store Connect API key)
xcrun notarytool store-credentials outpost-notary --apple-id <apple-id> --team-id XXK95K57U5
# release build (SKIP_PREP=1 reuses desktop/resources/ from a previous run)
MAC_SIGN_IDENTITY="Developer ID Application: Whissle LLC (XXK95K57U5)" NOTARY_PROFILE=outpost-notary \
  bash desktop/scripts/build-mac.sh
```

How it signs:
- `desktop/scripts/sign-resources.js` (electron-builder `afterPack`) finds every Mach-O file under
  `Contents/Resources/{python,site,native,app,models}` (about 210: the CPython binary, torch / onnxruntime / numpy
  extension modules, `libarctag.dylib`) and signs each with `--options runtime --timestamp`. Executables also get
  `build-resources/entitlements.mac.plist`.
- `electron-builder.yml` `signIgnore`s those trees, because `@electron/osx-sign` would otherwise "sign" every model
  file, image and `.pyc` through extended attributes.
- osx-sign then signs the Electron framework, helpers and the app with the hardened runtime and the same
  entitlements: microphone, camera, JIT, unsigned executable memory, and disable library validation (needed by the
  embedded CPython and the torch wheels).
- If notarization fails, the script saves Apple's log to `desktop/dist/notary-log.json`. That log lists each binary
  that is unsigned or missing the hardened runtime.

Windows: Authenticode needs an OV/EV certificate (see the Windows section). Until then, the Windows installer is
unsigned.

## Windows (built and checked structurally; not yet run on Windows)

No Windows machine has run the app yet. The Windows branches are unit-tested with the platform mocked
(`desktop/main/*.test.js`, `desktop/tests/`, `model_server/tests/test_platform_win.py`), `build-windows.ps1` is
parsed and dry-run in PowerShell 7, and a cross-built installer has been unpacked and compared with the Mac app
([BUILD_WINDOWS.md §8](BUILD_WINDOWS.md)).

- `build_python.py`: `python.exe` at the install root, `Lib/` + `DLLs/` + `libs/` trimming, `npm run build` via
  `shell=True` (on a Windows host). It puts the **Visual C++ runtime** (`msvcp140*.dll`, `vcruntime140*.dll`, pinned
  `msvc-runtime` wheel) next to `python.exe`: torch, onnxruntime and rapidfuzz import `MSVCP140.dll`, which
  python-build-standalone does not ship and a clean Windows lacks. Then every `.dll` / `.pyd` import is checked to
  resolve in the bundle or in Windows (`desktop/scripts/win_bundle_check.py dlls`); the build fails otherwise.
  `--target win-x64` lays out the same tree from a Mac (the cross-build).
- `arctag.py`: loads `arctag.dll` with `os.add_dll_directory` + `winmode=0`. `desktop/vendor/arctag/CMakeLists.txt` builds it with
  `ARCTAG_BUILD_SHARED` (dllexport). With MSVC, `native.c` takes its scalar kernels (MSVC has no `__x86_64__`):
  correct but slower than AVX2; mingw-w64 (the cross-build) and clang get the AVX2 path, checked against the CPU at load.
  The library opens model files through `u8_fopen` (`src/u8file.h`: UTF-8 → `_wfopen`), so an install under a user
  folder with non-ASCII characters works.
- Supervisor: `taskkill /T /F`; stale-pid checks read the command line through CIM (`Get-CimInstance Win32_Process`) so
  a reused pid that is someone else's `python.exe` is left alone (tasklist's image name only as a fallback);
  `windowsHide`, not detached (no console window); the parent watchdog uses `OpenProcess` + `WaitForSingleObject`.
- Keys (`keys.js`): no menu bar in a packaged build; Ctrl+= / Ctrl+- / Ctrl+0 and F11 give the zoom and full screen
  the macOS View menu has.
- Camera / microphone: Windows has no per-app prompt; the system privacy switches decide. `permissions.js` logs what
  Windows reports (`windows privacy camera: denied`), and the page says "blocked" (`gesture/guide.js cameraErrorText`).
- Servers bind 127.0.0.1 only, so Windows Defender Firewall never prompts.
- PyPI's Windows torch wheels are CPU-only already. `soundfile` ships its own libsndfile DLL.
- `fetch_media.py` is plain Python (urllib) plus Pillow for the Moon map: no bash, curl or sips. `trim_media.py` is
  plain Python plus the ffmpeg binary inside the pinned `imageio-ffmpeg==0.6.0` wheel (`uv run --with`), which has
  builds for Windows x64, macOS and Linux: nothing to install by hand.
- Clone to a short path (`C:\src\atm`) or enable long paths: torch's deepest files pass 260 characters otherwise.
- NSIS per-user install, unsigned: SmartScreen warns. Authenticode needs an OV/EV code-signing certificate
  (`WIN_CSC_LINK` / `WIN_CSC_KEY_PASSWORD`, or Azure Trusted Signing).

## Follow-ups

- Arc ear without torch: an ONNX export of Arc v1.1 Mini (trunk + Moonshine tiny) would drop torch, transformers and
  sympy (~490 MB unpacked) and cut model-server RAM.
- Trim `transformers/models/*` to the few the app imports (~90 MB).
- Self-hosted fonts (frontend owner), an app icon (`build-resources/icon.icns` / `.ico`), auto-update (out of scope offline).
