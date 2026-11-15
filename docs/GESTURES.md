# Camera gestures

The camera is an input like voice, tap and keys: an open hand stops, a thumbs up says yes, a swipe goes to the next
thing, pointing picks, a fist steers (lean it and the Moon spins that way), and in the cabin your head looks around and
leaning in opens a panel. It
is off until a kid (or a parent) turns it on, it runs entirely on the computer, and the app works the same without it.

Code:
- `frontend/src/input/intents.js`: the one input bus.
- `input/defaults.js`: the shell's default handlers and the keyboard source.
- `gesture/tuning.js`: **every tuning constant, in one place** (classifier, fist spin, calibration).
- `gesture/classifier.js`: landmarks to gestures. Pure, so it is unit-tested.
- `gesture/spin.js`: the fist as a joystick: reading, stick, dead zone, gain curve, rate control, momentum, One Euro. Pure.
- `gesture/calibration.js`: the fist calibration and its local storage. Pure.
- `gesture/map.js`: **the one gesture → action map** (what each gesture means, per screen), the coach marks and the help card.
- `gesture/bind.js`: classifier events to intents (follows `map.js`).
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
| **Settings stay local** | They are kept in `localStorage` on this device: on/off, camera, preview, sensitivity, head-look, hand, phase 2, flip the spin, the self-view position, the calibrated hand size, which screens' coach marks were shown (`outpost-gestures`), and the fist calibration (`outpost-gestures-spin`: four ranges and a sign, never landmarks). |

## Gestures

Phase 1 is on when the camera is on. Phase 2 is behind **Extra gestures (try-out)**.

| Gesture | Intent | Fires when | Guards |
|---|---|---|---|
| **Open palm, facing the camera, held still 0.6 s** | `stop` | all five fingers out, pointing up, spread, the palm facing the camera (knuckle row ≥ 0.55 of the hand length; edge-on is not a stop); the palm moves under 0.8 hand-lengths/s AND stays within 0.25 hand-lengths of where the hold began, for 0.6 s | never in the first 1 s after the camera turns on (a hand already up is not a stop); fires once per showing; a 1 s cooldown; a waving palm, or a hand passing slowly through the frame, never fires (tested, tests/flows.test.js); the end pose of a swipe is not a stop. On a multi-step flow (the Library tour, the cabin tour, a crew clip) it PAUSES; a thumbs up resumes (docs/FLOWS.md §Pause and resume) |
| **Thumbs up / down** | `yes` / `no` | four fingers curled, thumb straight and vertical, above / below the fist; held 0.35 s | once per showing; a 1.2 s cooldown (a quick up-then-down is one yes) |
| **Show 1, 2, 3 or 4 fingers, held still 0.5 s** | `pick` {n} | index (1); index + middle spread in a V (2); index + middle + ring, or thumb + index + middle (3); all four with the thumb tucked (4). The same count for 6 frames, held 0.5 s with the hand still | once per showing (lower the hand or change the count to go again); a 1 s cooldown; the counts a hand passes through on the way to 3 never fire; a relaxed hand (two fingers together) is not 2; a fist never counts; the open hand with the thumb out is stop, never a count. **1 vs point:** a still index is "1" only when the point cursor is NOT on a control; on a control it is point and hold (the dwell presses it), and right after a "1" the same still index's dwell presses nothing. See §Answers |
| **Swipe left / right, open hand** | `next` / `prev` | an open hand moves ≥ 20 % of the frame (and ≥ 1.6 hand-lengths) sideways within 0.45 s, mostly straight (dx ≥ 2·dy, ≥ 75 % of the path) | one swipe is one step (a 0.7 s cooldown); the return stroke within 1.2 s is ignored; a fist sweep is a drag, not a swipe |
| **Point + dwell 0.8 s** | `point` {x, y, progress}, then `select` {x, y} | index finger out, the other three curled; the cursor (smoothed) stays within 3.5 % of the screen | the ring fills over 0.8 s; it selects once, then re-arms only after the cursor moves 7 % away |
| **Fist, then lean it** (a joystick) | `spin` {phase, x, y} | four fingers curled for 0.25 s (4 frames) grabs and sets the neutral pose; moving or leaning the fist away from it turns the Moon that way, faster the further you lean. **It never zooms** | stays grabbed through a flickering finger or a thumb popping out; releases on an open hand (3 frames), 0.3 s of anything else, or the hand gone 0.25 s; nothing else fires while it holds; the opening hand is not a stop or a swipe for 0.7 s. See §Fist spin |
| **Head pose** (cabin) | `look` {x, y}; `panel_open` {panel}; `panel_back` | from face position plus turn, against a neutral pose (calibration, or the first second, drifting slowly); lean in = face ≥ 1.22× neutral width for 0.4 s; back = ≤ 1.06× for 0.5 s | 8 % dead zone in the middle; the aimed panel lights up and a lean opens it (left: habitat up, rover down; centre: power; right: radiation up, comm down), only from the seat; a face back after 2 s away re-anchors the neutral pose; lean-back only from a panel; off with **Look around with your head** |
| **Pinch, then slide** (the zoom) | `zoom_rate` {phase, rate} | thumb tip on a part-bent index, held still 0.25 s (5 frames), engages; then sliding the pinched hand up zooms in, down zooms out, faster the further you slide; letting go stops it | never while a fist holds or within 0.5 s of one letting go; never a point, a count of 1, a fist or a thumbs up (distance + reach + angle, with hysteresis); nothing else fires while it holds; not in the cabin. See §Zoom |
| *Phase 2:* two-hand pinch / spread | `zoom` {factor} | both hands pinching (thumb tip at index tip); the distance between them changes > 3 % | off by default |

**Robustness.**
- Every hand must be seen for 3 frames in a row before it can act.
- Finger states use hysteresis: a finger counts as straight above 1.62 and as curled again below 1.45 (tip-to-wrist distance over knuckle-to-wrist distance).
- A hand under 0.6 confidence, or a face under 0.6, is "not present": nothing acts on it.
- After any discrete gesture (stop, yes, no, swipe, select), no other discrete gesture fires for 0.35 s, so one movement is one action.
- The point cursor goes through a One Euro filter (steady when still, quick when moving) instead of a fixed smoothing.
- **Sensitivity** (Careful · Normal · Quick) scales hold times by 1/√k and swipe distance by 1/k. It never changes the pose geometry.
- **Calibration** (at most 30 s, skippable; see §Calibration) records the kid's hand size (later hands under 45 % of it are ignored), the fist's comfortable range per direction, and the neutral head pose.
- **Left / right hand** breaks a tie when two hands are about the same size.

## Fist spin

The fist is a joystick (rate control), not a drag. Making a fist **grabs** the Moon and remembers the pose at that
moment: where the hand is and how the fist is held (the wrist → middle-knuckle bone). From then on the **offset from
that neutral pose** is the stick:

- **x** (longitude): moving the fist sideways (in hand-lengths) plus leaning it left / right (the bone's angle in the image);
- **y** (latitude): moving it up / down plus tilting the knuckles toward / away from the screen (MediaPipe z; toward the screen = up, like pushing a joystick forward; the calibration flips it for a kid who tilts the other way);
- diagonals are both at once. Twisting the fist (the doorknob roll) is ignored: **the fist never zooms**.

The stick goes through a radial dead zone and a gain curve, and sets a target speed. The Moon eases toward it (limited
acceleration), so a jumpy fist never jolts it. **Opening the hand** releases: half the speed carries on and decays to a
stop within about a second (≈ 5–8° of coast in the e2e).

**Which way.** The surface moves the way the fist leans, as if you pushed the globe's skin (the same as a mouse drag:
fist right, the surface turns right; fist down, the north comes into view). **Settings → Camera & gestures → Flip the
spin** reverses it, for kids who think of it as flying a camera.

**No zoom on the fist** (0.1.2 owner feedback: "with the fist move control, i end up zooming in/out"). Twist used to
zoom, and the wrist rolls naturally while a fist leans, so the Moon zoomed during a spin. The fist now only turns;
zoom is its own gesture (§Zoom).

**Zoomed in turns slower**, in proportion to the camera's distance, so close up the fist still steers precisely.

**In the cabin** the same fist looks around: the stick is the look offset (no momentum), and it springs back to the
middle on release, the same as the head and the controller's right stick. The controller's right stick on the Moon now
sends the same `spin` intent, so the fist and the stick feel the same.

**Bounded look, and the way back.** Every look input (head, fist, right stick) is clamped to ±0.2 rad yaw and ±0.1 rad
pitch, so the windshield and the consoles always stay in frame. Any look input that stops without an end event (the
face is lost, the camera goes off, the hand leaves the frame) springs back to the seat after 0.7 s. **Center view**
(the button under the deck, <kbd>R</kbd>, voice "center" / "look forward", or a gesture emitting the `recenter`
intent) returns to the seat at once and closes any open panel. The cabin tour's beats hold their look until the next
beat.

**Feedback.** While the fist holds, a small joystick ring at the bottom centre shows the grab (bright knob), the
direction and the speed (the arrow), with "Lean your fist to spin" until it moves and "Open your hand to stop" once it
does. Chevrons at the Moon's centre point where it is heading, brighter when faster, and they fade out with the
momentum. A soft low "tock" on grab and a higher "tick" on release (`sound.js tick()`, scaled by Volume).

**Filtering.** The stick goes through a One Euro filter (jitter out, little lag) at the landmark rate (30 fps or less);
the Moon itself moves every display frame from the spinner, so a 10–30 fps camera still turns it smoothly.

### Tuning (all in `gesture/tuning.js`)

| Constant | Value | What |
|---|---|---|
| `palmHoldMs` | 600 ms | the open hand held still this long is a stop (fix/flow-resume; was 500) |
| `palmMaxSpeed` / `palmMaxDrift` | 0.8 hand-lengths/s / 0.25 hand-lengths | "still": slow now, and near where the hold began (was 1.6, no drift limit) |
| `palmArmMs` | 1000 ms | no stop in the first second after the camera turns on (`classifier.cameraOn()`) |
| `palmMinFacing` | 0.55 | knuckle width / hand length: the palm faces the camera (≈ 0.85), not edge-on (< 0.5) |
| `grabHoldMs` / `grabEnterFrames` | 250 ms / 4 | a fist held this long grabs |
| `grabReleaseFrames` | 3 | an open hand for this many frames releases |
| `grabReleaseMs` | 300 ms | neither fist nor open hand for this long releases |
| `afterGrabQuietMs` | 700 ms | after a release the open hand is not a stop or a swipe |
| `fistPosRange` | 1.0 hand-length | movement that counts as full stick (before calibration) |
| `fistRollRange` | 0.45 rad (≈ 26°) | lean that counts as full |
| `fistPitchRange` | 0.5 rad (≈ 29°) | tilt that counts as full |
| `fistFilter` | minCutoff 1.0, beta 0.8 | One Euro on the stick |
| `SPIN.dead` | 0.15 | radial dead zone |
| `SPIN.expo` | 1.6 | gain curve: speed ∝ ((|stick| − dead) / (1 − dead))^1.6 |
| `SPIN.maxSpeed` | 1.4 rad/s (≈ 80°/s) | at full stick, at the default distance |
| `SPIN.easeTau` / `maxAccel` | 0.12 s / 5 rad/s² | easing toward the target speed |
| `SPIN.releaseCarry` / `decayTau` / `stopBelow` | 0.5 / 0.35 s / 0.02 rad/s | the release momentum |
| `PINCH.on` / `off` | 0.22 / 0.38 hand-lengths | pinch starts / lets go (calibrated: on = 1.6 × the kid's pinch, 0.12–0.3; off = 1.7 × on) |
| `PINCH.minIndexReach` / `minThumbReach` / `maxTipCos` | 0.45 / 0.6 / 0.5 | the pinch's shape (stay: 0.38 / 0.5) |
| `PINCH.holdMs` / `holdFrames` / `stillRange` | 250 ms / 5 / 0.25 hand-lengths | a still pinch engages |
| `PINCH.releaseFrames` / `afterFistMs` | 3 / 500 ms | release; the quiet after a fist |
| `PINCH.slideRange` | 0.8 hand-lengths | slide that counts as full rate |
| `ZOOM.dead` / `expo` / `maxRate` | 0.15 / 1.4 / 0.9 ln per s (≈ 2.5×/s) | zoom dead zone, gain, max rate |
| `ZOOM.easeTau` / `stopTau` | 0.1 s / 0.08 s | ease in; stop on release (no coast) |
| `ZOOM.tapStep` / `voiceStep` / `stepMs` | 1.25 / 1.6 / 350 ms | a key tap; a voice step; their easing |
| `SPIN.refDistance` | 3.6 | the distance where maxSpeed applies (closer = slower, 0.25–1.5×) |

## Zoom: pinch and slide

One deliberate gesture, which can't fire during a spin:

1. **Pinch** your thumb tip to your index tip (the other fingers curled or relaxed) and hold it still for 0.25 s. A
   small zoom track appears beside the joystick ring ("Slide up or down to zoom"), with a soft tick.
2. **Slide** the pinched hand **up to zoom in, down to zoom out**. The slide from where it engaged is a rate, like the
   spin: a dead zone, a gain curve and a max rate (≈ 2.5× a second), eased.
3. **Let go** (open the pinch) to stop. The rate dies within ~0.2 s: no coasting zoom.

**What a pinch is, and is not.** Three features, in hand-lengths, with hysteresis (harder to start than to keep):
- the thumb tip to the index tip under 0.22 to start, kept until over 0.38 (calibrated per kid, below);
- the index part-bent: its tip is at least 0.45 from its knuckle (a fist folds it to about 0.3), and the thumb is out
  (its tip at least 0.6 from its base; a fist tucks it to about 0.4);
- the thumb and the index tips point at each other (the angle between them over 60°).

So a raised index with the thumb tucked is a count of 1 or a point (tips 1.3 apart), never a pinch; a thumbs up has the
tips a hand apart; a fist fails the reach. While a pinch engages or holds, nothing else fires: no point dwell, no
finger count, no stop. It never engages while a fist holds (a pinch shape inside a held fist is still the fist) or
within 0.5 s of a fist letting go, and making a fist ends a pinch first: never zoom and spin at once. The cabin has no
Moon zoom (its "zoom in / out" are the window views), so a pinch there does nothing.

**The same zoom everywhere.**
- **Keys:** <kbd>+</kbd> / <kbd>−</kbd> held zoom at the pinch's max rate; a quick tap still zooms one eased step (×1.25).
- **Controller:** RT/R2 zooms in and LT/L2 zooms out, as far as you press them (outside the cabin; in the cabin they keep the clock).
- **Voice:** "zoom in", "closer", "a bit closer"; "zoom out", "farther", "further away", "back out": an eased ×1.6 step (`turn_router.py` `zoom_in` / `zoom_out`, never in the cabin).
- **Selecting a place** eases the zoom to frame it (`globe.frameDistance`): small craters come closer (2.2), big seas fit the view (up to 3.4), whatever the kid zoomed to before.

All of them go through one zoomer (`gesture/spin.js createZoomer`, `input/defaults.js zoom_rate`), so they feel the same.

**Why not the two-hand pinch?** It stays behind **Extra gestures (try-out)**. It needs both hands up and in frame, which
is tiring for a kid and often fails at a laptop's field of view; one hand that can also stay on the desk is easier.

## Calibration

The first time the camera is turned on, a short calibration opens by itself (it is offered once; **Skip for now** keeps
the defaults, which are tuned to feel right without it). **Settings → Camera & gestures → Recalibrate** runs it again.

1. "Hold up your open hand." → the hand size (people behind are ignored below 45 % of it).
2. "Make a fist. Keep it still." → the neutral fist (0.4 s, moving under 0.15 hand-lengths).
3. "Now tilt it left… right… up… down." → each step ends when the fist has gone at least 30 % of the default range that
   way and stayed 0.45 s (a skipped or never-reached direction keeps the default, after 3.5 s at most). An arrow in the
   self-view shows which way.
4. "Pinch your thumb and finger." → the kid's pinch distance (the median over a 0.4 s hold). The pinch then starts
   under 1.6× that (0.12–0.3) and lets go over 1.7× the start. **Skip** skips just this step (the defaults apply).
5. "Sit back and look at the screen." → the neutral head pose.

Each direction's range is 85 % of the kid's biggest tilt that way, clamped to 0.35–2.2× the default, so full speed is a
comfortable tilt for that kid. If the kid's "up" tips the knuckles away from the screen, the tilt sign flips. It is
stored as `outpost-gestures-spin` (`{v, left, right, up, down, pitchSign, at}`); anything invalid is ignored. Steps run
on the landmark clock, so injected landmarks calibrate exactly like a camera (the e2e does).

## The map: gesture × screen → action

One meaning per gesture, everywhere (`gesture/map.js`). A blank cell does nothing on that screen.

| Gesture → intent | Moon (map, Library, Home) | Lesson, check ride | Menus (brief, site picker, debrief, patch, call sign) | Cabin (seat or panel) | Video overlay (hook) | Settings |
|---|---|---|---|---|---|---|
| **Open hand, still** → `stop` | stop the voice and the Moon | stop the voice | stop the voice | stop the voice and the clock | pause / play | stop the voice |
| **Thumbs up** → `yes` | take the offer | yes, on any answer that has a yes (Yes, Watch, Done) | the big button (take command, fly again) | confirm / do the Now card's step | watch the next one | — |
| **Thumbs down** → `no` | no thanks | no, on any answer that has a no (No, Skip) | no thanks | cancel | no thanks, close the video | — |
| **Show 1–4 fingers** → `pick` {n} | — | answer 1–4 (the badges show the numbers while the camera is on) | option 1–4 | choice 1–4 on the Now card | — | — |
| **Swipe left** → `next` | start the next lesson | next, after you answer | next | next view / next panel | next clip | — |
| **Swipe right** → `prev` | back | back | back | previous view / panel | previous clip | back |
| **Point and hold** → `point`, `select` | pick a pin or a place on the Moon | pick an answer or a place | press a button | press a control | press a button | press any switch or button |
| **Fist and lean** → `spin` | turn the Moon | turn the Moon to find it | turn the Moon (site picker) | look around | — | — |
| **Pinch and slide** → `zoom_rate` | zoom (up closer, down farther) | zoom | — | — | — | — |
| **Turn head** → `look` | — | — | — | look around, light the aimed panel | — | — |
| **Lean in / sit back** → `panel_open` / `panel_back` | — | — | — | open the aimed panel / back to the seat | — | — |
| *Two-hand pinch (phase 2)* → `zoom` | zoom | zoom | — | — | — | — |

**Discoverable.**
- **Coach mark:** the first time a screen comes up with the camera on, a small card at the top right shows the two or
  three gestures worth learning there ("Try this here"); it goes by itself after 8 s or on any gesture, and never
  shows again for that screen (remembered on this device).
- **Gestures help card:** the **Gestures** button on the camera chip lists everything that works on the current screen.
  It sits outside the gesture overlay, so point + dwell can press its Close.
- The hint chip still gives one line per screen ("Make a fist to spin" in the Library).

**Blended with voice and keys.** A hand gesture switches the shell to `html[data-input=gesture]`, which wears the same
TV focus ring as keys and the remote (`input/keys.css`). The point cursor focuses the control under it (so the ring is
on what a dwell will press); `select` focuses and clicks it. A key press or a mouse move switches the ring back.

**Video overlay hooks** (another branch builds the overlay; no video code here). The gestures already emit the intents;
while the overlay is open it sets `body[data-video=1]` (the help card and coach mark then show the video column) and
registers its handlers at priority 10, e.g. `onIntent("stop", () => videoOpen ? (togglePause(), true) : false, {priority: 10})`,
and the same for `next` / `prev` / `yes` / `no`. Open hand = pause keeps "same gesture, same meaning". Thumbs down ("No thanks")
closes the overlay, so a gesture can always get out of it. The overlay deletes `body[data-video]` when it closes; never
look it up with `closest()` (a click handler that did matched `<body>`: see docs/ROBUSTNESS.md).

**Removed or merged in this round.**
- **Fist + drag (follow)** → **fist + lean (rate)**. The fist no longer drags the surface 1:1; it is a joystick. The
  `rotate` intent stays on the bus for anything that wants a drag, but no gesture sends it.
- **The controller's right stick** on the Moon sends `spin` too (it sent per-frame `rotate` deltas), so stick and fist share one feel.
- **Raise hand = call Houston (phase 2) removed.** It made an open palm mean two things depending on its height; an open hand now always means stop. "Call Houston" is a voice line.
- **The cabin fist** now looks around with the same spring-back as the head and the controller (it accumulated drag deltas before).

## Answers: thumbs and fingers on any choice

`input/choices.js`. Gestures answer like taps, on every screen with a choice: a lesson's answers, the video step's
Watch / Skip, the prep card's Done / Skip, the mission's Now card, offers and confirms, the wipe confirm.

- **Thumbs up = yes, thumbs down = no**, by what the option *means*, never its position. First an explicit hook on the
  button (`data-yes` / `data-no`, or `data-intent="yes|no"`), then a small word list on its label (yes: Yes, Do it,
  Watch, Done, I did it, Start, Shelter now, Take…; no: No, No thanks, Skip, Not now, Decline, Cancel, Wait…).
  "Go back" and "Start over" are never a yes.
- **No yes / no option** (e.g. "Steer left / Steer right"): thumbs pick nothing and the hint chip says "Point at an
  answer, or hold up fingers". One exception: a thumbs up while the point cursor has focused an option presses that
  option ("yes, that one").
- **Fingers pick option N**, the same lists and order as the number keys (`input/keys.js`). The lesson's badges show
  numbers while the camera is on (`body[data-camera=on]`), also on the Yes / No / Sometimes row and on A–D answers.
- **Exactly like a tap:** the chosen button wears the focus ring for 300 ms (`.is-gesture-pick`), then it is clicked:
  the same grading, the same feedback.
- **Never behind a sheet:** nothing is answered while a dialog, Settings or the calibration is up.
- **With the camera on**, the lesson's do-line names the gesture ("Thumbs up for yes, down for no, or 3 fingers";
  "Make a fist and turn it, or point at Far side"). The coach mark for a lesson is thumbs up, show fingers, and point.

Tested: `tests/choices.test.js` (the word list, the hooks, finger counts with hysteresis, 1 vs point) and
`tests/e2e/answers_e2e.py` (on L1: thumbs up answers Yes, thumbs down No, three fingers Sometimes; the far side by
click, Enter, the 2 key, voice, point-and-hold and fist spin; thumbs on Steer left / right show the hint).

## Gesture → intent → what each screen does

There is one intent bus (`input/intents.js`). Every device emits the same intents:
- **voice:** the router's `nav` decisions, `main.js` `runNav` → `emitIntent(intent, {arg, text}, "voice")`;
- **keys:** <kbd>Alt</kbd>+<kbd>→</kbd>/<kbd>←</kbd> next / prev, <kbd>Alt</kbd>+<kbd>Y</kbd>/<kbd>N</kbd> yes / no, <kbd>Alt</kbd>+<kbd>.</kbd> stop;
- **remote keys and game controllers** (docs/KEYBOARD.md): `input/keys.js` and `input/gamepad.js` emit `move`, `select`, `back`, `mic`, `pick`, `help` and the same `next` / `prev` / `yes` / `no`;
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
| **Library** (explorer) | stop the story or tour, the flight and the spin | — | *request:* next / previous tour stop | press a ghost marker or a place | **turn the Moon** (lean the fist; pinch and slide zooms) | — | tap / ask |
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
  - `tests/spin_zoom.test.js` (the clean zoom): no zoom during a fist spin in all 8 directions with the wrist rolled ±0.5 rad (the owner's report); the pinch pose vs a count of 1, a point, a fist, thumbs and counts 2–4, both hands, three tilts; pinch hysteresis (half-open never starts, flicker never releases); calibrated thresholds; pinch and slide up / down zooms, a still or brief or wandering pinch doesn't, letting go stops; never during or 0.5 s after a fist; a pinch never dwells or picks; no zoom in the cabin; the zoomer (dead zone, gain, max rate, no coast, key tap step, held rate, eased voice steps); the stored pinch; the map / help / coach copy; framing a selected place.
  - `tests/spin.test.js`: the rate-control math (dead zone, gain curve, max speed, easing, distance scaling, invert, release momentum and its decay); the One Euro filter; the fist reading (lean, tilt, twist); all 8 directions through the classifier; fist hysteresis (a flickering finger or a popping thumb never lets go or says yes; a brief fist never grabs; a lost hand releases); the after-release quiet (no stop, no swipe); the cross cooldown; low-confidence hands and faces; the calibration (per-direction ranges, the tilt sign, timeouts) and its storage (validation, junk, blocked storage); the gesture → action map (same gesture, same intent everywhere, ≤ 6-word copy, the video hook, screen keys, help rows, coach marks).
  - `tests/gestures.test.js`: every gesture's true positives; the false positives (a brief palm or thumb, a slow drift, an up-down wave, a waving palm, a far person's thumbs-up, a flickering hand, a relaxed hand, a moving point, a second face); cooldowns; the return stroke; sensitivity; dwell re-arm; grab deltas; head and lean; phase 2; handedness; the intent table; hint copy (≤ 6 words, no emoji); classifier speed.
  - `tests/intents.test.js`: bus priority, consumption, the wildcard, async handlers, throwing handlers, the intent-only log.
- **Fixtures:** `tests/fixtures/gestures/*.json` are MediaPipe-shaped landmark sequences, synthesised by `synth.mjs` (canonical hand proportions plus seeded noise; regenerate with `node tests/fixtures/gestures/make_fixtures.mjs`). A real recording in the same shape (`{name, expect, frames:[{t, aspect, hands:[{lm, side, score}], faces:[{box, kp, score}]}]}`) can be dropped in, and the tests pick it up. Note: the thresholds are tuned on synthetic hands plus the fake-camera run, not yet on a panel of real kids' hands. Recording 10 kids' sessions is the next step.
- **End to end** (`tests/e2e/gestures_e2e.py`, Playwright headless Chromium with `--use-fake-device-for-media-stream`) runs the built app on the backend's origin, the same as the desktop app. It checks:
  1. off by default;
  2. Settings turns it on, and the bundled models run in the worker;
  3. no vision asset comes from off-origin;
  4. on each screen, injected landmark streams emit the right intents and the screen reacts: map swipe opens a lesson; palm → stop; noise → nothing; point → select taps the button under it; Library fist → rotate; thumbs → yes / no; brief thumbs-up → the cabin; cabin swipe → the next window view; head → look;
  5. the first-time calibration opens by itself and, on injected palm / fist-tilt / face landmarks, measures and saves every direction;
  6. **fist spin in all 8 directions, played in real time** (`injectPaced`): the Moon's centre moves the right way in latitude and longitude, the stick indicator and the heading arrow are up while it holds, and opening the hand coasts a few degrees and stops by itself;
  7. the coach mark on the Library, the Gestures help card, and `html[data-input=gesture]` after a gesture;
  8. one-click off releases the camera.

  Result (gestures-v2): **54/54** pass. The machine was heavily loaded by other jobs (load ≈ 36), so the fake-camera
  inference ran at ~9 s a frame; `--min-frames` / `--frames-timeout` lower the frame-flow bar on such a machine without
  touching the gesture checks, which run on injected landmarks.
  ```
  cd frontend && npm run build    # then a backend serving frontend/dist on :8390
  uv run --no-project --with playwright==1.58.0 python tests/e2e/gestures_e2e.py --base http://127.0.0.1:8390 [--min-frames 4 --frames-timeout 90]
  ```
  The browser runs headless with Chromium's fake camera (never the real one) and makes no sound: `tests/e2e/silent.py`
  adds `--mute-audio --disable-audio-output`, an init script that mutes media, keeps every AudioContext suspended and
  turns speechSynthesis off, and sets the app's volume to 0 (chrome-headless-shell ignores `--mute-audio` alone).
- `window.__outpost.gestures.inject(frames)` drives the classifier without a camera (tests, demos);
  `injectPaced(frames)` plays them in real time (the rate control and its animation need wall-clock time), muting the
  camera's own frames meanwhile. `gestures.spin()` is the spinner's state; `gestures.calibration` the stored calibration.
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

## Live mission clock (feat/mission-gameplay)

In the cabin, an **open palm** also pauses the mission clock; it still stops speech too, because the mission's `stop`
handler never consumes the intent. A **thumbs up** does the Now card's step: its first button carries
`data-intent="yes"`, so the shell's `yes` default presses it when no confirm is pending. **Point + dwell** picks a
choice. Controller: View/Share pauses or runs the clock, RT/R2 skips to the next event, LT/L2 warps time.
See docs/GAMEPLAY.md §6.

## Needs a human with a webcam

Everything above was tuned and tested on synthetic landmarks (canonical hand proportions plus seeded jitter) and
Chromium's fake camera. Before calling it done, someone should try it with a real webcam and a few kids, and tune in
`gesture/tuning.js`:

1. **Fist depth signal (pitch).** It comes from MediaPipe's z, the noisiest coordinate. Check that tilting the knuckles
   toward / away from the screen reads as up / down, and that the calibration's sign flip catches kids who do it the
   other way. If the z is too noisy, set `fistTiltWeight` lower (position still steers). Twist no longer does anything.
1b. **The pinch** (`PINCH`): do real kids' pinches start under 0.22 hand-lengths and stay under 0.38 while they slide?
   Does a fist ever pass `minIndexReach` 0.45 / `minThumbReach` 0.6 (it must not)? Does a relaxed "OK" pinch pass the
   angle gate (`maxTipCos` 0.5)? Is 0.25 s to engage quick enough, and `slideRange` 0.8 hand-lengths a comfortable
   full-speed slide? Is ~2.5×/s (`ZOOM.maxRate`) too fast for a kid? Does the zoom track read clearly by the ring?
2. **Ranges and feel**: `fistPosRange`, `fistRollRange`, `SPIN.dead`, `SPIN.expo`, `SPIN.maxSpeed`, the momentum
   (`releaseCarry`, `decayTau`). Does a relaxed fist sit in the dead zone? Is full speed a comfortable lean?
3. **Grab / release hysteresis** at a real 15–30 fps with motion blur: `grabHoldMs`, `grabReleaseFrames`, `grabReleaseMs`.
4. **The One Euro settings** (`fistFilter`, `pointFilter`): jitter vs lag on a real camera.
5. **Calibration timing** with a real kid: are 0.45 s holds and 30 % minimum tilt right? Is the arrow clear?
6. **Spin direction default** (surface follows the fist) vs Flip: ask kids which feels right.
7. Whether the coach mark's 8 s and its corner placement are noticed without getting in the way.
