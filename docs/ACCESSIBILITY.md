# Accessibility

Outpost Luna is voice-first, which helps kids who can't use a mouse and hurts kids who can't hear. This page lists
what we support, for whom, how to test it, and what is still missing. Settings open from the **Settings button** (the gear)
in the top bar (`#a11yBtn`, or <kbd>Alt</kbd>+<kbd>A</kbd>). They are saved in this browser's localStorage
(`outpost-a11y`) and are never sent to the server.

Code: `frontend/src/a11y.js` (settings, commands, audio description, alerts), `caption.js` (caption bar),
`highlight.js` (key-span marks, glossary cards), `academy/vocab.js` (Space words), `a11y.css`; server side
`backend/app/tts.py` (speed, word timings), `steering.py` (§4b of docs/VOICE_STEERING.md),
`model_server/app/tts_steer.py` (word timings, pace).

## The voice bar

The voice bar (mic, state, caption, typing) can be moved: drag its grip, or focus the grip and use the arrow keys
(Shift for bigger steps) and Enter; or say/type "move the voice bar to the top right". Each move is announced.
"Reset the voice bar", a double-click on the grip, or Settings → Display → Reset voice bar position puts it back.

## Who gets what

### Blind and low-vision kids

| Feature | How |
| --- | --- |
| **Voice-only operation** | Every turn goes through the same text path (voice or typing). Commands: "where am I?" (mode, lesson, the question, feedback, resources), "what can I do?" (the buttons on screen), "press *Next*" / "tap *Hear it again*" (any visible button by its name), "option 2", "faster" / "slower" / "normal speed", "say that again", "bigger text", "high contrast", "audio description on/off", "open settings". Lesson answers are never swallowed: commands are narrow full-phrase matches. |
| **Pick a place without the globe** | Settings → Help → "Pick a place on the Moon" (or <kbd>Alt</kbd>+<kbd>P</kbd>): a list of every place; "Tap it" does exactly what a globe tap does (Academy tap steps included). |
| **Audio description** | "Describe what happens": the Director's visual moves are announced in an aria-live region (always) and spoken by the guide (when on), after the current line: the globe flying to a place or coordinates, a card opening, a mission alert banner, a resource bar going red, an alert step, a badge. |
| **Screen readers** | Polite (`#a11yLive`) and assertive (`#a11yAlert`) live regions; every icon-only control is named (title → aria-label, automatic); highlighted places/words are buttons with labels ("Space word: albedo. Press for its meaning"). `ariaControl(el, label, {role, pressed, expanded, live})` is exported from `a11y.js` (and on `window.__outpost.a11y`) for the new cockpit controls. |
| **Keyboard** | Skip link to the answer box (first <kbd>Tab</kbd>); visible 3 px focus ring everywhere; DOM order = reading order; the settings dialog traps focus and closes with <kbd>Esc</kbd> (focus returns to the button); glossary cards open on <kbd>Enter</kbd> and close on <kbd>Esc</kbd>; the Academy focuses **Next** after a right answer. <kbd>Alt</kbd>+<kbd>W</kbd> = "where am I?". |
| **High contrast** | Black/white/yellow tokens, 2 px borders on every control, underlined links. |
| **Text size** | 100 / 125 / 150 % (panels, cards, dock, captions, top bar; the globe canvas is not scaled). |
| **Less motion** | Also follows the OS `prefers-reduced-motion`. |

### Deaf and hard-of-hearing kids

| Feature | How |
| --- | --- |
| **Captions for every voice** | The caption bar shows every guide, CAPCOM, story and Houston sentence, highlighting the word being spoken, plus the crew audio (mirrored from the karaoke line, which uses the clip index's word timings). On by default. |
| **Word-synchronous timing** | Real timings from Steer TTS's duration predictor (`X-TTS-Words`), not an estimate. Fallbacks: syllable-weighted estimate over the audio length (Deepgram), `speechSynthesis` word boundaries (browser voice). The bar's `data-timing` says which (`timed` / `estimate` / `boundary` / `crew`). |
| **Transcripts** | Everything said (guide, CAPCOM, crew moments, your own turns, descriptions) in Settings → Transcript. |
| **Visual alerts** | With every alert: a flashing red screen edge plus a banner with a ⚠ icon and the alert text (mission banners, alert steps). |
| **Vibration** | `navigator.vibrate([180, 80, 180])` on alerts where supported (phones, tablets). |
| **Typing everywhere** | The answer box answers every Academy step, mission order and question; vocab "say it back" also accepts typing. |
| **"No audio needed"** | A note in Settings → Help: nothing in the app requires hearing. The "listen" vocab step shows the meaning as text too. |

### Kids who can't easily use a mouse, keys or their voice

**Camera gestures** (opt-in: Settings → Camera & gestures; docs/GESTURES.md):
- an open hand stops;
- thumbs up / down for yes / no;
- swipe for next / back;
- point and hold to press any button or tap the Moon (a ring fills over 0.8 s);
- a fist turns the Moon;
- in the cabin, the head looks around.

Every gesture is one more way to do something that voice, tap and keys already do. Nothing needs the camera.
**Sensitivity** (Careful / Normal / Quick) lengthens or shortens the hold times. **I use my left / right hand** and a
10-second calibration adapt it to the kid. Each gesture shows a short "Stop" / "Yes" / "Next" toast and is
announced in a polite live region. Keys: <kbd>Alt</kbd>+<kbd>→</kbd>/<kbd>←</kbd> next / back, <kbd>Alt</kbd>+<kbd>Y</kbd>/<kbd>N</kbd>
yes / no, <kbd>Alt</kbd>+<kbd>.</kbd> stop.

### Reading support

Easy-read font (Atkinson Hyperlegible from Google Fonts, loaded only when chosen, with wider letter/word spacing),
caption line length (24–80 characters, default 42, at most 4 lines), syllable hints on vocab words (`re·go·lith`).

### Speed

Voice speed 0.75× / 1× / 1.25× / 1.5× (settings, or "faster"/"slower"). Steer voices: `rate` on top of the Director's
style plus `pace` (docs/VOICE_STEERING.md §4b); the browser voice: `utterance.rate`; crew recordings: `playbackRate`
with pitch preserved. The caption bar shows the speed.

### Highlighting

Places/hardware (solid underline; press to fly there) and space words (dotted underline; press for the glossary card).
Shape, never colour alone. Numbers and mission resources are no longer marked (round 2 of docs/UX_ROUNDS.md: too noisy). Marked in
cards, captions, lesson prompts/feedback and mission event/radio text; the card also gets chips for its words and places.
Sources: `/api/glossary`, `/api/places`, and the Arc Tagger read-out `mentions` of the latest answer.

## How to test

1. `make dev`, open the app. Press <kbd>Tab</kbd> once: the skip link appears. <kbd>Alt</kbd>+<kbd>A</kbd> opens settings.
2. Academy → Space words. Click "Hear the meaning": the caption bar highlights each word as it's spoken
   (`#captionBar[data-timing=timed]`). Set 1.5×: the request carries `speed=1.5`, `X-TTS-Speed` shows `pace=1.25 rate=1.17`, the caption runs faster.
3. Keyboard only: <kbd>Tab</kbd> to an answer, <kbd>Enter</kbd>; focus lands on **Next**.
4. Type "where am I?", "option 2", "press next", "slower".
5. Turn on "Describe what happens", press "Far side": "The Moon turns to 0° north, 180° east." is announced and spoken.
6. High contrast + 150 %: everything fits one screen (the lesson panel scrolls inside itself).
7. Automated: `npx axe-core` is not a dependency; paste this in the console for a one-off WCAG run:
   ```js
   await import("https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"); (await axe.run()).violations.map(v => [v.id, v.nodes.length])
   ```
Unit tests: `frontend/tests/a11y.test.js` (settings persistence incl. blocked storage, commands, caption timing,
highlight tokenizing), `backend/tests/test_a11y_tts.py` (speed → rate/pace, vocab steering, timing passthrough + cache),
`model_server/tests/test_tts_steer.py` (real word timings, markup, pace).

Screenshots: `docs/img/a11y-caption-word-sync.jpg`, `docs/img/a11y-high-contrast-150.jpg`, `docs/img/a11y-settings-panel.jpg`.

## Manual WCAG 2.2 checklist (AA)

| Criterion | Status |
| --- | --- |
| 1.1.1 Non-text content | Icon buttons named; globe has a list alternative (place picker). Moon map canvas itself has no text alternative beyond the stage label. |
| 1.2.1/1.2.2 Captions (prerecorded) | Crew audio captioned word by word + transcript. |
| 1.3.1 Info and relationships | Dialogs, groups, live regions, radio group for speed. |
| 1.4.1 Use of colour | Marks use underline style/box/glyph as well as colour. |
| 1.4.3 / 1.4.11 Contrast | Base tokens ≥ 4.5:1 (documented in styles.css); high-contrast mode for more. |
| 1.4.4 Resize text | 150 % in-app plus browser zoom. |
| 2.1.1 Keyboard | All controls are buttons/inputs; globe via place picker. |
| 2.2.2 Pause, stop | Space interrupts speech; crew audio has Stop; tours stop on any key. |
| 2.3.1 Three flashes | Visual alert flashes 3 times in 1.6 s (≤ 3/s); off with "Less motion" (steady border). |
| 2.4.1 Bypass blocks | Skip link. |
| 2.4.7 Focus visible | 3 px ring, yellow in high contrast. |
| 3.3.2 Labels | Inputs labelled; settings have descriptions. |
| 4.1.2 Name, role, value | `aria-pressed` / `aria-expanded` kept in sync. |

## Known gaps

- The globe canvas is not itself accessible; kids who can't see it use the place picker and voice.
- Audio description of HUD changes watches the DOM (`.m-bar.is-alert`, `#mBanner`); the new cockpit should call
  `window.__outpost.a11y.describe(text)` / `.visualAlert(text)` directly when it lands.
- The chime itself has no hook: visual alerts fire on the banner/alert-step that accompanies it, not on every chime.
- Text size uses CSS `zoom` on panels (the CSS is px-based); Firefox < 126 ignores it.
- Deepgram fallback has no word timings (estimated); `vocab_listen` options carry no term, so its "Hear the meaning"
  line isn't word-stressed.
- axe-core was not run in CI; only the one-off console check above.
- Sign language video for crew moments is out of scope.
