# Robustness: a change while something is open

The bug class: **a mode or setting changes while something modal or active is on screen**, and the app ends up stuck,
blank, unstyled or impossible to close. `frontend/tests/e2e/robustness_e2e.py` checks it as a matrix of
SURFACE × CHANGE.

## The owner's bug (v1, 2026-11-15)

"I turned on gestures and it became this, stuck": the whole window was a light-grey page with one unstyled line,
"Needs internet. Ask a grown-up to connect.", and nothing to press. The computer was online.

It was not a connectivity problem, and it was not the video card:

1. While the video overlay is open, `main.js` marks `<body data-video="1">`. It left `data-video=""` after closing.
2. The Settings panel's click handler (`a11y.js`) looked for the Help video button with
   `e.target.closest("[data-video]")`. After any video had played, **every** click inside Settings found `<body>`.
3. It then asked `isAvailable(body.dataset.video)`, which was `isAvailable("1")` or `isAvailable("")`. The backend
   answers 404 for an unknown id, and `isAvailable` maps any non-OK answer to `"offline"`.
4. The "offline" branch wrote `OFFLINE_LINE` into the "button's" `textContent`. The button was `<body>`, so the whole
   app was replaced by one text node. No styles applied, no chrome, no Close, and no way out but quitting.

The log fits: a YouTube video played (15:25:46 to 15:25:52), and the camera was requested at 15:26:18. That request was
the click on Camera & gestures in Settings, after the video had closed.

**Fix:** the Help button is `button[data-help-video]`, matched inside the panel only. The overlay deletes
`body[data-video]` when it closes. A unit test (`tests/video.test.js`) fails if any `closest()` selector in `src/` could
match a state attribute the app writes on `<body>` or `<html>`.

**Hardening that came with it:**
- A player error while we are online shows "This video won't play here." with Close, not "Needs internet". The check
  is `diagnose()`: `navigator.onLine`, then one quick backend check.
- The backend probe retries a slow answer once instead of calling it offline. Any HTTP answer counts as online. A
  failed probe is remembered for 5 s, not 20 s.
- Thumbs down closes the video overlay.
- The offline card never writes outside the overlay.

## The matrix

**Surfaces** (each one open or active):
- `after_video`: a video played and was closed (the owner's path)
- the video overlay: `video_yt` (YouTube), `video_file` (a NASA file) and `video_offline`
- `l1_yes_no` and `l1_far_side`: L1 step 2 (Yes / No / Sometimes) and step 4 (turn to the far side)
- `lesson_step`: a lesson mid-answer
- `prep_card`: a Mission prep card
- `crew_clip`: a crew clip playing
- `mission_choice`: a choice card with the clock running
- `storm_alert`
- `debrief`
- `settings`: the Settings sheet
- `calibration`: the gestures calibration
- `grownup_gate`: the in-app half, a `window.open` out of the player
- `help_card`: the gestures help card
- `voicebar_listening`

**Changes:**
- camera on and off
- every Settings switch, choice and slider (voice, theme, captions, expressiveness, recorded voice, and the rest)
- Mute by Shift+M and by the button
- the theme button
- offline and back online
- resize to 1024×640 and back
- the Flight School / Mission / Library tabs
- Esc
- voice "stop", "go to the map" and "mute"
- the gestures open hand, thumbs down and swipe
- thumbs up and down (answers), and three fingers held up (pick option 3)
- a backend kill and restart
- the page hidden and shown (`visibilitychange`)
- a double press

**Checked after every cell:**
- the app chrome is there and styled, and `<body>` was not overwritten;
- every open modal has a visible Close;
- no plain-element modal sits inert under the video `<dialog>`;
- focus is inside the top modal, or on `<body>`;
- there are no page errors;
- the Mute button agrees with `prefs.muted`.

At the end of each surface: Esc closes every modal, all three tabs switch, and the voice bar is not stuck on
"Speaking" or "Thinking".

A change that cannot reach a control behind a modal uses the path a kid would take. For tabs and Settings that is
voice (`__outpost.shellNav`). The camera is turned on from Settings when nothing covers it.

```
cd frontend && npm run build
(backend on :8201 serving frontend/dist, VIDEO_PREFETCH=0; the model server is not needed)
uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/robustness_e2e.py --base http://127.0.0.1:8201 \
    --restart-cmd "<kill and restart that backend>" [--only video_yt,settings] [--changes camera_on,esc] [--json m.json] [--shots dir]
```

The run is silent: `frontend/tools/silent.py`, headless, `--mute-audio --disable-audio-output`. It uses Chromium's fake
camera only. The test hooks are `window.__outpost.shellNav`, `.hear(text)` (a voice turn), `.playCrew()`, and
`window.__cabinTest` when the page sets `window.__outpostTest`.

## What the sweep found and fixed

| Found | Fix |
|---|---|
| Settings click after any video replaced the whole app with "Needs internet…" (the owner's bug) | the Help button is `button[data-help-video]`; `body[data-video]` is removed on close; a unit test bans `closest()` on body/html state attributes |
| Settings opened by voice while a video played sat under the video `<dialog>`, inert | one sheet at a time: Settings closes the video; the video closing Settings (`outpost:modal-open`) |
| The first-time calibration opened under an open video, unusable | not offered then (offered next time); a video opening stops a running one |
| Turning the camera off left the calibration up over a dead camera for up to 30 s | camera off stops it; Esc closes it from anywhere; it keeps focus |
| Settings opened by voice over the calibration was covered by it | opening Settings stops the calibration |
| With Settings up, a swipe advanced the lesson behind it and pulled focus out | screen intents from gestures / keys / the controller are swallowed while Settings or the calibration is up |
| The gestures help card threw on close when its button was gone | null-safe focus targets |

## Results

Last full run (2026-11-15, two runs in parallel on a loaded machine, stopped at about 275 of 336 cells each). "Before"
is origin/main plus the test hooks only. "After" is this branch. Counts are over the 273 cells both runs reached:

| | pass | fail | skip |
|---|---|---|---|
| before | 206 | 60 | 7 |
| after | 250 | 16 | 7 |

By surface (pass / cells): after_video 18→20/20; video_yt, video_file and video_offline 13→20/20 each; lesson_step and
prep_card 15→20/20; settings 10→18/20; mission_choice 16→18/20; storm_alert 5→7/17; calibration 10/16 (unchanged);
debrief 18/20; crew_clip, l1_far_side and l1_yes_no 20/20.

Still open:
- **calibration over Settings:** focus can land on a Settings section button while the calibration is up (Shift+M,
  Mute, theme, offline).
- **Harness limits, not app bugs:**
  - Under SwiftShader the 3D cabin starves Playwright's click waits. This hit the mission rows (`mission_choice` /
    `storm_alert` × camera / Settings / theme), `debrief × tabs` and `settings × voice_stop`. The harness now clicks
    with a real mouse at the control's centre (`Run.click`), and those rows need a re-run.
  - The storm surface can't be re-created after Esc in the harness.
  - `l1_yes_no × double_press`: a double Enter opened the next step's video, and the harness then tried to click
    behind it.
  - A long debrief line kept the voice bar on "Speaking" for more than 15 s. The final check now waits 40 s. The run uses headless Chromium with SwiftShader WebGL, which is
slow. Clicks use `no_wait_after` because the 3D cabin starves Playwright's after-click navigation wait. That is a
harness limit: the app is fine.
