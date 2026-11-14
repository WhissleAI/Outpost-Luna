# Camera gestures

The camera is an input like voice, tap and keys: an open hand stops, a thumbs up says yes, a swipe goes to the next
thing, pointing picks, a fist turns the Moon, and in the cabin your head looks around and leaning in opens a panel. It
is off until a kid (or a parent) turns it on, it runs entirely on the computer, and the app works the same without it.

Code:
- `frontend/src/input/intents.js`: the one input bus.
- `input/defaults.js`: the shell's default handlers and the keyboard source.
- `gesture/classifier.js`: landmarks to gestures. Pure, so it is unit-tested.
- `gesture/bind.js`: gestures to intents.
- `gesture/engine.js`: the camera, frame pacing and the classifier.
- `gesture/worker.js`: MediaPipe, in a Web Worker.
- `gesture/ui.js` and `gestures.css`: the indicator, self-view, cursor, hints, Settings and calibration.
- `gesture/guide.js`: the cheat-sheet and the hints.
- `tools/fetch_vision.mjs`: the bundled runtime and models.

## Privacy and kids (non-negotiable)

| Rule | How |
|---|---|
| **Off by default** | `outpost-gestures.enabled` is `false` until **Settings → Camera & gestures → Use the camera for gestures** is turned on. No camera request happens before that (the e2e test checks). A voice command cannot turn the camera on. |
| **Always visible while on** | A red-dot "Camera on" chip with a **Turn off** button, on every screen. One click stops the stream (the webcam light goes out), terminates the worker, and frees the WASM heap. `body[data-camera=on]` is set for the shell. |
| **Frames never leave the device** | Each frame is downscaled (320 px) into an `ImageBitmap`, transferred to the worker and closed there after inference. Only landmark numbers come back. Only intents leave the gesture module. Nothing is stored, logged or sent. The intent log (`recentIntents()`) keeps the last 50 intent names, sources and times, and never landmarks (tested). |
| **No recognition or identity** | The face model is the 6-point BlazeFace detector (a box, eyes, nose, mouth, ears). It is used for head direction and distance only. There is no face mesh, no embedding and no comparison between faces. The self-view draws only a box round the face. |
| **Only the nearest person** | The largest hand and the largest face count. Hands under 45 % of the kid's calibrated hand size (people behind) are ignored. A second face never drives the view (tested). |
| **Offline** | The WASM runtime and the models are in the app, served from its own origin. There is no CDN at run time. Electron's request filter cancels any other host, so a CDN load would fail rather than leak. |
| **Electron** | `desktop/main/permissions.js` (unit-tested): the permission handler grants `media` (audio + video) to the app's own origin only. On macOS the first camera request goes through `systemPreferences.askForMediaAccess("camera")`. `NSCameraUsageDescription` is in `Info.plist` (`desktop/electron-builder.yml`), and `com.apple.security.device.camera` is in the entitlements. Windows: camera consent is the system privacy switch (docs/BUILD_WINDOWS.md §5). |
| **Settings stay local** | They are kept in `localStorage` on this device: on/off, camera, preview, sensitivity, head-look, hand, phase 2, the self-view position and the calibrated hand size. |

## Gestures

Phase 1 is on when the camera is on. Phase 2 is behind **Extra gestures (try-out)**.

| Gesture | Intent | Fires when | Guards |
|---|---|---|---|
| **Open palm, held still 0.5 s** | `stop` | all five fingers out, pointing up, spread; the palm has moved less than 1.6 hand-lengths/s for 0.5 s | fires once per showing; a 1 s cooldown; a waving palm never fires (tested); the end pose of a swipe is not a stop |
| **Thumbs up / down** | `yes` / `no` | four fingers curled, thumb straight and vertical, above / below the fist; held 0.35 s | once per showing; a 1.2 s cooldown (a quick up-then-down is one yes) |
| **Swipe left / right, open hand** | `next` / `prev` | an open hand moves ≥ 20 % of the frame (and ≥ 1.6 hand-lengths) sideways within 0.45 s, mostly straight (dx ≥ 2·dy, ≥ 75 % of the path) | one swipe is one step (a 0.7 s cooldown); the return stroke within 1.2 s is ignored; a fist sweep is a drag, not a swipe |
| **Point + dwell 0.8 s** | `point` {x, y, progress}, then `select` {x, y} | index finger out, the other three curled; the cursor (smoothed) stays within 3.5 % of the screen | the ring fills over 0.8 s; it selects once, then re-arms only after the cursor moves 7 % away |
| **Fist, then move** | `rotate` {phase, dx, dy} | four fingers and the thumb curled for 0.15 s, then the palm moves | ends on an open hand or 0.2 s without a fist |
| **Head pose** (cabin) | `look` {x, y}; `panel_open` {panel}; `panel_back` | from face position plus turn, against a neutral pose (calibration, or the first second, drifting slowly); lean in = face ≥ 1.22× neutral width for 0.4 s; back = ≤ 1.06× for 0.5 s | 8 % dead zone in the middle; the aimed panel lights up and a lean opens it (left: habitat up, rover down; centre: power; right: radiation up, comm down), only from the seat; a face back after 2 s away re-anchors the neutral pose; lean-back only from a panel; off with **Look around with your head** |
| *Phase 2:* two-hand pinch / spread | `zoom` {factor} | both hands pinching (thumb tip at index tip); the distance between them changes > 3 % | off by default |
| *Phase 2:* raise hand, 0.8 s | `call_houston` | an open palm above the top of the face box | off by default (then a raised palm is just `stop`) |

**Robustness.**
- Every hand must be seen for 3 frames in a row before it can act.
- Finger states use hysteresis: a finger counts as straight above 1.62 and as curled again below 1.45 (tip-to-wrist distance over knuckle-to-wrist distance).
- **Sensitivity** (Careful · Normal · Quick) scales hold times by 1/√k and swipe distance by 1/k. It never changes the pose geometry.
- **Calibration** ("Show me your hand", at most 10 s) asks for an open hand, then a thumbs up, then "sit back and look at the screen". It records the kid's hand size (later hands under 45 % of it are ignored) and the neutral head pose.
- **Left / right hand** breaks a tie when two hands are about the same size.

## Gesture → intent → what each screen does

There is one intent bus (`input/intents.js`). Every device emits the same intents:
- **voice:** the router's `nav` decisions, `main.js` `runNav` → `emitIntent(intent, {arg, text}, "voice")`;
- **keys:** <kbd>Alt</kbd>+<kbd>→</kbd>/<kbd>←</kbd> next / prev, <kbd>Alt</kbd>+<kbd>Y</kbd>/<kbd>N</kbd> yes / no, <kbd>Alt</kbd>+<kbd>.</kbd> stop;
- **gestures:** `bind.js`.

Taps stay native DOM clicks, the reference path. A gesture `select` makes the same tap at the cursor: focus plus
`click()` on a control, or `pointerdown`/`pointerup` on the Moon canvas, which the globe treats as a tap.

Handlers run highest priority first:
1. screen handlers (`onIntent(name, h, {priority: 10})`);
2. the shell defaults (`defaults.js`, 0);
3. the shell's navigation (`shellNav`, -10), the old `runNav`.

A handler returns `true` to consume an intent.

The camera-off column shows the same action without the camera. Nothing in the app needs the camera.

| Screen (docs/FLOWS.md) | Open palm | Thumbs up / down | Swipe left / right | Point + dwell | Fist + drag | Head | Camera off |
|---|---|---|---|---|---|---|---|
| **Home** (call sign) | stop the guide | — / — | — | pick a suggested call sign, press **Start** | turn the Moon | — | tap / type / "call me Nova" |
| **Moon map** (Flight School) | stop | take the offer ("Next up") / no thanks | **next**: start the next lesson. **prev**: *request:* select the previous pin | press a pin or **Start** | turn the Moon | — | tap / "next" / Alt+→ |
| **Lesson: choice** | stop CAPCOM (barge-in) | — (never graded as an answer) | after a right answer: **Next**. *Request:* prev = step back | press an answer row | turn the Moon | — | tap / say the answer / "option 2" |
| **Lesson: tap / find** (V1) | stop | — | next after the answer | **point at the place on the Moon**: the dwell is a globe tap and is graded like a tap | turn the Moon to find it | — | tap the Moon / say the name / Alt+P list |
| **Lesson: turn the Moon** (V2, learning-v3 `globe_side`) | stop | — | next after the answer | — | **turn the Moon**: graded by the camera's centre longitude | — | drag / Near-Far toggle / "show me the far side" |
| **Lesson: terminator / compare / spot the difference** (V3, V4, V7) | stop | — | next after the answer | point at the line, the card or the option | turn the Moon | — | tap / say it |
| **Lesson: predict** (learning-v3) | stop | *request:* thumbs = the kid's yes / no prediction (never wrong) | next | point at an option | — | — | tap / say yes or no |
| **Lesson: keywords / command / vocab say** | stop | — | next after the answer | press Hear it again / the mic | — | — | voice or typing (gestures can't say words) |
| **Patch earned** | stop | take the offer (next lesson / check ride) | **next** | press **Next** | — | — | "next" / tap |
| **Check ride** (mini cockpit) | stop | confirm a risky order | next after a step | press controls | — | — | voice / tap |
| **Mission: site picker / brief** | stop | **take command** / no | *request:* cycle the sites | pick a site row, press Take command | turn the Moon | — | "take command" / tap |
| **Cabin, seat view** | stop CAPCOM / Houston | confirm / cancel a risky order (`missionUI.intent("confirm" / "cancel")`) | **window view** ORBIT → SITE → ROVER → EARTH (and back) | press any console control | **look around** (parallax) | turn = look around and light up the aimed panel; **lean in = open it** | "rover view", "open the comm panel", tap |
| **Cabin, panel open** | stop | confirm / cancel | **next / previous panel** (habitat → rover → power → displays → radiation → comm → shift) | press controls on the panel | look around | **sit back = back to the seat** | "back to my seat", Esc, tap |
| **Debrief** | stop | **fly again** / no | — | press Fly again / Another site | — | — | "fly again" / tap |
| **Library** (explorer) | stop the story or tour, and the flight | — | *request:* next / previous tour stop | press a ghost marker or a place | **turn the Moon** | — | tap / ask |
| **Settings** | — | — | — | press any control (the ring works on switches) | — | — | keyboard / tap |
| **Answer card** | stop | the card's Yes / No | — | press **Hear the crew** | turn the Moon | — | tap / voice |

**No conflicts with voice:**
- Gestures never produce text, so they can't answer a lesson by accident. A thumbs up is `yes`, and only the offer or confirm handler uses it, never the step grader.
- The router keeps owning spoken turns. `stop` from a palm is the same as Space or barge-in: it drops queued lines (`session.dropAll()`) and stops speech and the crew audio. It does not post `barge_in`, because no one is talking.
- Voice "next" in the cabin, which did nothing before, now steps the window view like a swipe. That is the one intended behaviour change.
- While a gesture is held, the mic stays as it is. A thumbs up does not open the mic.

## Architecture

```
camera ─► engine.js ──ImageBitmap 320px──► worker.js (MediaPipe Tasks Vision, module worker)
              ▲  rVFC, 1 frame in flight,                │ HandLandmarker (2 hands) + FaceDetector
              │  adaptive 30/24/15/10 fps                ▼
              └──────── landmarks (mirror space) ◄───────┘
                     │
                     ▼
            classifier.js ─► gesture events ─► bind.js ─► emitIntent(name, args, "gesture")
                                                               │
 voice: router nav ─► runNav ─► emitIntent(…, "voice") ────────┤
 keys: Alt+→ … ─► emitIntent(…, "keyboard") ───────────────────┤
                                                               ▼
                                   intents.js bus ─► screen (10) ─► shell defaults (0) ─► shellNav (-10)
```

**Runtime:**
- `@mediapipe/tasks-vision` is pinned at 0.10.35 in `package.json` and is Apache-2.0.
- Only the ES-module SIMD WASM build ships.
- The worker imports the WASM loader once and restores `self.ModuleFactory` before each task, because MediaPipe clears it after each one.
- It uses the GPU delegate (WebGL2 in an OffscreenCanvas) and falls back to the CPU.
- Vite builds the worker as an ES module (`worker.format: "es"`).

**Assets** (`npm run dev` / `npm run build` run `tools/fetch_vision.mjs` first; `npm run vision:check` verifies them):

| File | Bytes | Source |
|---|---|---|
| `vision_wasm_module_internal.wasm` | 11,153,641 | npm package (node_modules) |
| `vision_wasm_module_internal.js` | 322,082 | npm package |
| `hand_landmarker.task` | 7,819,105 | MediaPipe model bucket, sha256 `fbc2a300…7cde1` |
| `blaze_face_short_range.tflite` | 229,746 | MediaPipe model bucket, sha256 `b4578f35…0152f` |
| **Total** | **19.5 MB** (≈ 9.6 MB gzip-compressed in the installer) | |

These files go to `frontend/public/vision/` (gitignored), then `dist/vision/`, then the desktop bundle's
`resources/app/frontend/vision/`. They are served by the backend's static mount on the app's own origin with the right
`application/wasm` type. `build_python.py` fails the desktop build if any is missing, on Mac and Windows: both
`build-mac.sh` and `build-windows.ps1` run it, and both fetch the files right after `npm ci`. `smoke.py` checks every
file is served at the manifest's size.

Over the ~15 MB target: the WASM alone is 11.2 MB. Options:
- **FaceLandmarker:** not used. It would add 3.6 MB; BlazeFace is 0.23 MB and enough for head direction and lean.
- **GestureRecognizer:** not used. It would add 8.4 MB, and our own classifier is needed anyway for testability, swipes and dwell.
- **Hands-only build:** not available from MediaPipe.
- **Download on first opt-in:** would break "no network".

## Measured on this Mac (Apple M3 Pro, macOS 26.2), 2026-11-13

| | Electron 44.10.0 (Chromium 152), the desktop runtime | Chrome, headless (ANGLE Metal) | Headless SwiftShader (CI) |
|---|---|---|---|
| Model load (worker, both models) | 871 ms | 338 ms | 815–966 ms |
| Inference per frame (hands + face, 320×240) | **12.5 ms**, GPU delegate | 14 ms, GPU | 130–450 ms (adapts to 10 fps) |
| Frames a second | **20** (target 24 to 30, one frame in flight) | 20 | 4–7 |
| CPU with the camera on | `getAppMetrics`: GPU process 3 %, renderer 1 %, all processes 4 % (Electron's per-process share) | +27 % of one core (75 % → 102 %, Library screen) | — |
| Memory with the camera on | renderer 242 MB, GPU process 176 MB | — | — |
| Classifier | < 0.1 ms per frame (unit test) | | |

The Electron numbers come from **the camera check** (`desktop/scripts/camera_check/`), run with Chromium's fake camera.
It is a packaged `.app` built by electron-builder with the same Electron version, `NSCameraUsageDescription` and
entitlements, and the same session lockdown (`desktop/main/permissions.js`) as Outpost Luna. It loads the built UI from a
backend the way the packaged app does. In that run:
- the camera was off by default;
- the chip sat in the top bar;
- nothing was blocked off-origin;
- Turn off released the stream.

**macOS camera prompt.** Launched through LaunchServices (`OPEN=1`, like a double-click), the app's camera status was
`not-determined`. The page's request reached the permission handler, which called `askForMediaAccess("camera")`, and
the app then waited on the system consent dialog until the check timed out (nobody was there to answer). The webcam
fps still needs a human to click **Allow** once:
```
(cd desktop && npm ci && node node_modules/electron/install.js)
OPEN=1 bash desktop/scripts/camera_check/camera_check.sh http://127.0.0.1:8390
```
Launched from a terminal instead, macOS attributes the camera to the terminal (its "responsible process"), so no
prompt shows. The packaged app is always launched like the `OPEN=1` run.

A full dmg (`build-mac.sh`) was not built for this check: it needs at least 6 GB free, and the disk had 5.3–5.7 GB.
`build_python.py` and `smoke.py` check the vision files in the real bundle.

## Testing

- **Unit** (`npm test`, `node --test`):
  - `tests/gestures.test.js`: every gesture's true positives; the false positives (a brief palm or thumb, a slow drift, an up-down wave, a waving palm, a far person's thumbs-up, a flickering hand, a relaxed hand, a moving point, a second face); cooldowns; the return stroke; sensitivity; dwell re-arm; grab deltas; head and lean; phase 2; handedness; the intent table; hint copy (≤ 6 words, no emoji); classifier speed.
  - `tests/intents.test.js`: bus priority, consumption, the wildcard, async handlers, throwing handlers, the intent-only log.
- **Fixtures:** `tests/fixtures/gestures/*.json` are MediaPipe-shaped landmark sequences, synthesised by `synth.mjs` (canonical hand proportions plus seeded noise; regenerate with `node tests/fixtures/gestures/make_fixtures.mjs`). A real recording in the same shape (`{name, expect, frames:[{t, aspect, hands:[{lm, side, score}], faces:[{box, kp, score}]}]}`) can be dropped in, and the tests pick it up. Note: the thresholds are tuned on synthetic hands plus the fake-camera run, not yet on a panel of real kids' hands. Recording 10 kids' sessions is the next step.
- **End to end** (`tests/e2e/gestures_e2e.py`, Playwright headless Chromium with `--use-fake-device-for-media-stream`) runs the built app on the backend's origin, the same as the desktop app. It checks:
  1. off by default;
  2. Settings turns it on, and the bundled models run in the worker;
  3. no vision asset comes from off-origin;
  4. on each screen, injected landmark streams emit the right intents and the screen reacts: map swipe opens a lesson; palm → stop; noise → nothing; point → select taps the button under it; Library fist → rotate; thumbs → yes / no; brief thumbs-up → the cabin; cabin swipe → the next window view; head → look;
  5. one-click off releases the camera.

  Result: 21/21 pass on the merged app (ux-v3 + ux-mission). It also checks the chip is in the top bar, and that in the 3D cabin a lean opens the aimed panel and sitting back returns to the seat.
  ```
  cd frontend && npm run build    # then a backend serving frontend/dist on :8390
  uv run --no-project --with playwright==1.58.0 python tests/e2e/gestures_e2e.py --base http://127.0.0.1:8390
  ```
- `window.__outpost.gestures.inject(frames)` drives the classifier without a camera (tests, demos).
  `window.__outpost.intents.recent()` lists the last intents.

## Integration with the UX branches

`feat/gestures` merges `feat/ux-v3` (b7c66b0) and `feat/ux-mission` (34652b5). Edits to their files are marked
`[gestures]`.

**Done** (the gestures branch did these through the owners' own extension points):
- **Settings:** the **Camera & gestures** section registers itself in `window.__outpost.settingsSections` (`{id: "camera", title, after: "display", html(), bind(el)}`), so it is listed after Display. It needs no `a11y.js` edit beyond the "What can I do?" line.
- **Top bar:** the camera chip `#gxIndicator` sits just before the Settings gear (`#a11yBtn`). It floats under the stage's top-left controls only on a shell with no top bar.
- **Voice bar:** `vbar.addObstacle(".gx-preview:not([hidden])")`, so the bar never sits on the self-view.
- **Tokens:** `gestures.css` uses the colour, radius, type and `--space-*` tokens.
- **Icons:** `hand`, `thumbs-up`, `thumbs-down`, `pointer`, `grab`, `swipe` (move-horizontal), `head` (scan-face), `camera-off` and `zoom` (Lucide, ISC) are in `assets/icons/`, built by `build-art.mjs`. `gesture/icons.js` re-exports `icon()`. The icon test is green.
- **Cabin:** every cabin action goes through `missionUI.intent(name, arg)`. There is no synthetic pointer input.
  - `look` → `look(dx, dy)` (head and fist-drag)
  - `highlight_panel` → the panel the head is aimed at
  - `panel_open` → the highlighted or aimed panel
  - `panel_back` → the seat
  - `next` / `prev` → `view_next` / `view_prev` at the seat, `panel_next` / `panel_prev` in a panel
  - `yes` / `no` → `confirm` / `cancel` while an order waits

  The head aim follows the 5-panel layout: habitat (upper) and rover (lower) on the left, power (DU1) in the middle, radiation (upper) and comm (lower) on the right.

**Still open.** Paste these into docs/UX_ROUNDS.md under **Gesture requests**:

**Shell / UX lead** (`academy/*`, `feat/ux-v3`):
1. **Lesson step back:** `onIntent("prev", h, {priority: 10})` in `academy/ui.js`. In a lesson, go back one step if it is not graded yet. `next` already works through `academyUI.nav("next")`.
2. **Moon map pins:** `onIntent("next" | "prev")` moves the pin selection along the flight path; `yes` starts it.
3. **Predict steps** (learning-v3): `onIntent("yes" | "no")` as the kid's prediction.
4. Keep the `__outpost.gestures.summary()` line in `a11y.js` `options()` ("What can I do?") when Settings changes.

**Mission UX** (`mission/*`, `feat/ux-mission`):
1. **Site picker:** `onIntent("next" | "prev")` to cycle the sites, and `yes` to take command (today `yes` takes command on the brief).
2. **Houston:** phase 2 `call_houston` now asks "call Houston" through the normal turn path. If the cabin gets a direct Houston action, expose it as `missionUI.intent("call_houston")`.
3. **Optional:** a short "Lean in to open" label on the highlighted panel (`.is-hl`), so kids learn the lean.
