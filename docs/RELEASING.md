# Releasing Outpost Luna

There is no CI budget (GitHub Actions is off for this org), so every release is gated **locally**: a person runs
`make release-check` on the Mac, and `release-check.ps1` on the Windows build machine, against the exact installer
that will be uploaded. A release ships only when both say `PASS`. Issue #91.

Why: 0.3.4 and 0.3.5 shipped with a dead ear. Release signing re-signed the pinned ONNX Runtime, its sha256 no longer
matched the lock file, and the speech engine refused to load inside the signed app. Unit tests and a dev run both
passed, because neither ran the signed, installed app. Gate 2 (`smoke`) runs that app and fails on 0.3.5 (below).

## The gates

`python3 desktop/scripts/release_check.py` (stdlib only; `make release-check` and `release-check.ps1` call it) prints
one line per gate, writes `desktop/dist/release-check.json`, and exits 1 if any gate fails.

| gate | what it checks | fails when |
|---|---|---|
| `unit:backend`, `unit:model_server` | `uv run pytest -q` | any test fails |
| `unit:frontend`, `unit:desktop` | `npm test` (`node --test`) | any test fails |
| `smoke` | The **installed** app. macOS: the `.app` is copied out of the dmg into a temp folder (never `/Applications`), then `codesign --verify --strict --deep` and `spctl -a`. Windows: the installer is unpacked with 7-Zip and never run, so no registry entries or shortcuts are created. The app is launched headless and muted (`OUTPOST_HEADLESS=1`, `OUTPOST_MUTE_AUDIO=1`, `--mute-audio`) on its own data folder (`OUTPOST_USER_DATA`) and free ports (`OUTPOST_BACKEND_PORT` / `OUTPOST_MODELS_PORT`, never 47310 / 47210), with update checks off. It waits for `engine.json` and then for the model server's `/health` to report `arc_ear.available`, `engine.ort_source == "pinned"` and the model's sha256 verified. Then it runs `desktop/scripts/smoke.py` (voice ask, answer, OS voice, Flight School, Mission) and **a real voice turn**: Reid Wiseman's Artemis II clip (`backend/tests/fixtures/crew_orientale_16k.s16le`) goes through `/ws/listen` with the token from `engine.json`, and the final words must contain "Orientale", linked to `Orientale Basin` | any of these checks is false; also a bad signature (`--allow-unsigned` for dev builds) |
| `video` | Added in 0.3.11 (0.3.10 shipped with NASA's `phases_loop` failing and YouTube stuck on a bot card). The test app is launched with `--remote-debugging-port` on a free port, and the gate drives its page over DevTools, muted: `hammer_feather` and `far_side_view` must **play** in our own player (time moving), and the YouTube extra `diy_crater` must play in the embed, or, if YouTube refuses (its "confirm you're not a bot" card), show "won't play here" with **Watch on YouTube** (or its NASA fallback, pressed and played). `VIDEO_SWEEP=1` plays every catalog entry with YouTube **blocked in the page** (DevTools `Network.setBlockedURLs` on the page and, through auto-attach, on its out-of-process frames; `VIDEO_SWEEP_YT=1` keeps YouTube reachable): every NASA video (`nasa_file`, `pack_file`) must play from a local file (`available` = "cached": the cache or the installed video pack, played from `/api/video/<id>/file`), and the phases lesson's Watch how must offer `moon_phases_2025` | a NASA video does not play, or (sweep) streams instead of playing from a local file; a YouTube video hangs (neither plays nor ends on a card), or its card has neither the NASA fallback nor Watch on YouTube. A clean card only **warns** (YouTube's choice, per network). YouTube is skipped when the app says it is offline |
| `golden` | 40 fixed clips (`desktop/tests/golden/`, 4 MB: 20 clean and 20 with classroom noise; kid-style commands and questions with 23 names and 12 numbers) streamed at real-time pace through the installed app's ear. Scored with the ear eval's normalisation (`backend/tests/fixtures/ear_eval/score.py`) | WER > baseline + 0.03; name, link or number rate below baseline by more than 0.09 / 0.09 / 0.10; p50 or p95 latency (speech end to final words) above 1.5 × baseline + 150 ms. Latency only **warns** on a machine other than the one that recorded `baseline.json` |
| `fuzz:ws` | For `FUZZ_SECONDS` (120): random connections to `/ws/listen` and `/v1/stream`, with and without the token. They send real and random PCM of odd lengths, random and oversized context frames (5,000 names, unicode, wrong types), invalid UTF-8, reserved opcodes and RSV bits, unfinished fragments, unmasked frames, oversized pings, length fields that lie, odd close codes and garbage HTTP. Every 10 cases both servers must be healthy | a server unhealthy or restarted, a watchdog reset, a connection without the token accepted, ear slots still held 20 s after the fuzzer stops, or the voice turn broken afterwards |
| `fuzz:libarc` | `desktop/tests/fuzz/fuzz_libarc.c` against a **debug libarc built with `-fsanitize=address,undefined`** (`desktop/build/libarc-asan`), with the real model and the app's pinned ONNX Runtime, for `FUZZ_SECONDS`. Random names lists (empty, 2,000 names, unicode, 8 KB names, many aliases, odd kinds), context prompts, whole-clip transcribes and streams (feed, flush, double flush, names changed mid-stream) with random PCM lengths and values: silence, noise, tones, full scale, denormals, NaN, ±Inf, out of range. The same file builds as a libFuzzer target (`-DARC_LIBFUZZER`) on an LLVM that has libFuzzer (Apple clang does not). Mac and Linux; Windows runs `fuzz:ws` only | any ASan or UBSan report, or a crash. The log goes to `desktop/dist/fuzz_libarc.crash.txt`, and the summary line gives the case seed to replay: `desktop/build/libarc-asan/fuzz_libarc <nft2 dir> <libonnxruntime> 1 <seed>` |
| `soak` | Only with `SOAK=1`. For `SOAK_MINUTES` (10; 1440 for the 24 h soak), the golden clips are looped through the installed app's ear, one session per clip. RSS of the model server, the backend and Electron is sampled every 15 s | RSS rises more than `SOAK_LEAK_MB_PER_H` (60) MB/h after the first quarter and grows by more than 30 MB; p50 latency in the last quarter exceeds 1.5 × the second quarter + 100 ms; a child restart or watchdog reset; more than 1% of turns error |
| (older builds) | A build without `OUTPOST_HEADLESS` (before 0.3.6) would open a window and take focus, so the app is **not** launched. Its own model server is run straight from the installed bundle (its Python, `launch.py`, libarc, the pinned runtime), as `main.js` would start it, with no Electron, and the ear's state is reported. `smoke` then fails either way: such a build cannot be gated silently | always |
| `quit` | The app is asked to quit as the OS would (SIGTERM; `taskkill` without `/F` on Windows) | it needs a force-kill, `engine.json` is left behind, or a child process outlives it |

Silent by design: no window, no Dock icon, no focus change, no audio out. The owner's installed app, its data folder
and its ports are never touched. The test app's models come from `~/Library/Application Support/Outpost Luna/assets`
(`%APPDATA%\Outpost Luna\assets` on Windows). They are APFS copy-on-write clones on the Mac and hard links on Windows,
so they take no disk and the source is never written. Pass `--assets-seed <dir>` or `RC_ASSETS_SEED` to use another
folder. With no seed, the test app downloads its 510 MB like a first run. Everything goes to a temp folder that is
deleted at the end (`--keep` keeps it).

Options: `--gates unit,smoke,video,golden,fuzz,soak`, `--skip unit`, `--app <unpacked app>` (instead of an installer),
`--update-baseline` (records `desktop/tests/golden/baseline.json` again; do it on purpose, in its own commit, with the
reason), `FUZZ_SECONDS`, `FUZZ_SEED`, `SOAK=1`, `SOAK_MINUTES`.

### Measured on this Mac (M3 Pro, macOS 26.2), 2026-11-16

| | 0.3.7 (current release) | 0.3.5 (dead ear) |
|---|---|---|
| unit | backend 1197 passed, model_server 128 passed, frontend 260/260, desktop 63/63 | the same (it runs the repo's tests) |
| smoke | PASS: ear on onnxruntime 1.32.0 (pinned), ready in ~8 s; smoke.py ok; heard "...take out Orientale Basin..." linked | **FAIL**: `the ear never loaded: RuntimeError: ONNX Runtime library .../libonnxruntime.1.32.0.dylib is damaged or not the pinned build (sha256 fafafbb54a1e…, expected 51c5a25a3dfa…)` |
| golden | PASS: WER 0.016, names 23/23, linked 19/23, numbers 11/12, p50 / p95 ~0.9 / 2.1 s | not run (no ear) |
| fuzz | PASS: `fuzz:ws` 579 connections in 120 s; `fuzz:libarc` 17 cases / 206 API calls in 120 s, 0 ASan / UBSan reports | `fuzz:libarc` PASS (smoke fails in 13 s) |
| soak (`SOAK=1`, 10 min) | PASS: 143 turns; model server RSS 492 -> 495 MB; p50 939 -> 977 ms; no restarts | |
| quit | PASS in 0.9 s; engine.json removed; no children left | |
| whole check | 19.4 min with the 10 min soak (about 9.5 min without) | about 3 min |

## Mac release

1. **Version.** Bump `desktop/package.json` and `frontend/package.json` (plus their lock files), in a PR like
   "Release 0.3.7". Merge it to `main`.
2. **Build** from a clean `main`, signed and notarized (docs/DESKTOP.md, "Signing and notarization"):

   ```bash
   MAC_SIGN_IDENTITY="Developer ID Application: Whissle LLC (XXK95K57U5)" NOTARY_PROFILE=outpost-notary make desktop-mac
   ```

   The output is `desktop/dist/Outpost Luna-<version>-arm64.dmg`.
3. **Gate.** Run it on the dmg you just built. All lines must say `PASS`:

   ```bash
   make release-check DMG="desktop/dist/Outpost Luna-<version>-arm64.dmg"
   # optional, before a big release: SOAK=1 SOAK_MINUTES=1440 make release-check DMG=...   (24 h)
   ```

   Keep `desktop/dist/release-check.json`: its gate summaries go in the release PR or notes.
4. **Publish** under both names. The site and README link the stable name through `releases/latest/download/`:

   ```bash
   V=0.3.7
   cd desktop/dist
   cp "Outpost Luna-$V-arm64.dmg" "Outpost-Luna-$V-arm64.dmg"
   cp "Outpost Luna-$V-arm64.dmg" Outpost-Luna-mac-arm64.dmg
   shasum -a 256 "Outpost-Luna-$V-arm64.dmg" > "Outpost-Luna-$V-arm64.dmg.sha256"
   gh release create "v$V" --title "Outpost Luna $V" --notes-file notes.md \
     "Outpost-Luna-$V-arm64.dmg" "Outpost-Luna-$V-arm64.dmg.sha256" Outpost-Luna-mac-arm64.dmg
   ```

5. **Verify the site link.** The download must be the new file and must still pass the gate:

   ```bash
   curl -sIL https://github.com/WhissleAI/Outpost-Luna/releases/latest/download/Outpost-Luna-mac-arm64.dmg | grep -i '^location' | tail -1
   gh release download "v$V" -p Outpost-Luna-mac-arm64.dmg -D /tmp/rc && shasum -a 256 /tmp/rc/Outpost-Luna-mac-arm64.dmg
   make release-check DMG=/tmp/rc/Outpost-Luna-mac-arm64.dmg ARGS="--skip unit"    # the bytes users get
   ```

   Then open <https://whissleai.github.io/Outpost-Luna/> and check that "Download for Mac" resolves to the same file.

## Windows release

On the Windows build machine (docs/BUILD_WINDOWS.md), from the same `main` commit:

1. **Build:** `powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1`. The output is
   `desktop\dist\Outpost Luna Setup <version>.exe` plus the copy `desktop\dist\Outpost-Luna-win-x64.exe`.
2. **Gate:** the script picks the newest `*Setup*.exe` in `desktop\dist`:

   ```powershell
   powershell -ExecutionPolicy Bypass -File desktop\scripts\release-check.ps1
   # or: ... release-check.ps1 -Exe desktop\dist\Outpost-Luna-win-x64.exe ; -Gates smoke,golden ; $env:SOAK="1"
   ```

   It needs 7-Zip (`winget install --id 7zip.7zip -e`; electron-builder's `7za.exe` in `desktop\node_modules` also
   works), plus uv and Node for the unit suites. Python is found through `py -3`, then `python`, then the build's
   embedded `desktop\resources\python\python.exe`, then `uv run`. Latency in `golden` only warns here, because the
   baseline was recorded on the Mac. `fuzz:libarc` is skipped (the ASan build runs on the Mac). The installer is
   unsigned, so the Authenticode status is reported and not gated. Not yet run on a real PC (written and checked on
   the Mac, like `build-windows.ps1`): if a step breaks, especially the 7-Zip unpack or the `taskkill` quit, report
   the output.
3. **Upload** to the release the Mac step created:

   ```powershell
   gh release upload v<version> desktop\dist\Outpost-Luna-win-x64.exe --clobber
   ```

4. **Verify:** "Download for Windows" on the site (`releases/latest/download/Outpost-Luna-win-x64.exe`) must return
   the uploaded file. Compare its SHA-256: `Get-FileHash`.

## When a gate fails

- `smoke` saying `the ear never loaded: ...` means the ear is dead in this build: do not ship it. The reason comes
  from the model server's `/health` (`models.arc_meta.error`). Run with `--keep` to keep the test app's
  `userdata/logs`.
- `golden` lists the clips whose transcript changed (`changed` in the JSON report). If the change is intended (a new
  ear model, say), re-record the baseline in its own commit and say why.
- A `fuzz` failure is a bug to fix, not to retry. The summary gives the seed (`FUZZ_SEED=<seed>` re-runs the same
  protocol cases; the libarc replay command is in the line).
