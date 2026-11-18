# UX rounds

This is the round log for the Outpost Luna redesign on `feat/ux-v3`. For each workflow and round it records the
critique, what changed, and the screenshots.

- **Screenshots:** in `docs/img/ux/`, named `<round>-<state>-<width>-<theme>.jpg`. To regenerate them:
  `uv run --with playwright python frontend/tools/ux_shots.py --states … --tag rN`.
- **Ownership:**
  - **Shell owner** (this log): the design system, the shell, home, the course map, lessons, patches, the check
    ride, the Library, Access, the voice strip, captions and cards.
  - **Mission UX:** `mission/*`, `cabin.css`, `mission.css`.
  - **Copy:** `story.js`, `course.json`, and the spoken lines.
  - **Art:** `assets/icons/`, `assets/patches/`, `icons.js`.

## Checklist (every screen)

- one primary action
- nothing a kid wouldn't miss
- no emoji
- copy within budget
- consistent tokens
- no overlap or clipping at 1440×900 and 1280×720
- keyboard and voice paths work
- contrast AA
- works offline
- nothing on screen that does nothing

## Round 0: baseline (before)

Screenshots are in the scratchpad only (not committed). Critique:

- **Global:**
  - Five font families loaded from Google Fonts (Sora, Inter, JetBrains Mono, Barlow Condensed, Share Tech Mono), so
    the app is not offline.
  - Emoji in the mode switch (🎓 🛰️), the Access button (♿), the call-sign tag (🧑‍🚀), every lesson patch, and the
    "👉" hints.
  - The top bar has 9 items: a SpaceApps badge, two modes, Moon library, Find it, Access, About, theme, and "No audio
    needed".
  - The comm strip is two stacked rows: a state label, a truncated placeholder hint, a Space hint, an Ask button and a
    mic. The voice state is buried in mono caps.
  - The caption bar is a full-width strip with boxed and highlighted words. It duplicates the CAPCOM bubble on screen.
  - Key-span marks are noisy: boxed numbers ("Day [1]"), "?" superscripts on words, double underlines and ⌖ glyphs.
- **Home / first launch:**
  - There is no "what this is".
  - A 12-pill call-sign wall, a separate input, a "That's me" button, a "🎲 Surprise me" button, and a "👉" hint. No
    single Start.
- **Course map (the "board"):**
  - A 2-line hero, a paragraph, a progress bar, and three track headings.
  - Eight cards, each with a blurb and a tag.
  - A mentor card with a quote, a patch shelf that duplicates the cards, and a "Why this matters" paragraph.
  - Two "next" signals that compete: the card ring and the mentor button.
- **Lesson:**
  - On every step: an italic story beat, a CAPCOM paragraph bubble, "🔊 Hear it again", "NASA facts (4)", the
    question, the answers, and a "👉" instruction.
  - The answer area falls below the fold on short screens. The step dots are tiny.
  - Feedback is coloured text only.
- **Patch earned:** an emoji patch with a burst, a sentence, "🚀 Fly your check ride", "Patch map", and
  "👉 Say next, or tap the button".

## Round 1: shell, voice strip, home, course map, lesson, patch

### What changed

- **Design system:**
  - `tokens.css` (docs/DESIGN_SYSTEM.md): one accent (blue), semantic success/warning/danger only, 6 spacing steps,
    a 6-step type scale, radii, elevation, focus ring and motion, in light, dark and high contrast.
  - Inter and JetBrains Mono, self-hosted. Google Fonts is removed, and the easy-read font is bundled.
  - `styles.css` is rewritten on tokens. Mission CSS moved verbatim to `mission.css`. That file is a **pure move with
    no redesign**, handed to the Mission UX owner.
  - The old Flight School and caption rules are removed from `outpost.css`. The cockpit `.ck-*` and mission rules
    there are untouched.
- **Top bar:**
  - Brand on the left.
  - One segmented control: Flight School · Mission · Library. Library is now a destination, not a toggle.
  - Three icon buttons: Access, theme, About.
  - The SpaceApps badge is gone. "Find it" moved to the Library HUD. "No audio needed" moved into the Access panel.
- **Comm strip:** one row, the single place for voice:
  - a mic switch, showing the mic-off glyph when muted;
  - the state (Mic off · Listening · Hearing you · Thinking · Speaking · Didn't catch that), shown as bars plus one
    word;
  - the field, which shows the words while hearing and "Heard: …" for 2.6 s after a used turn;
  - Send.
  - The Space hint shows only when idle and empty.
  - No chips outside the Library, where there are 3.
- **Captions:**
  - One dark subtitle block centred above the strip, with the speaker in small caps.
  - The spoken word is underlined instead of boxed.
  - Marks are quieter: places get a solid underline and space words a dotted one. There are no boxes, glyphs or
    superscripts.
- **Home:**
  - Over the Moon: the tagline, a 2-line headline, a call-sign field (prefilled, with a shuffle icon), 5 suggested call
    signs, and **one Start**. The NASA credit line sits at the bottom.
  - Tapping a chip selects it, and Start commits. Voice ("call me Nova", "surprise me") still commits directly.
- **Course map:**
  - A title and an "n/8 patches" count with the call sign.
  - **One flight path**: 8 patch stops on a line that fills as patches are earned. Done stops are filled with a check,
    the next stop has an accent ring and a halo, and the rest are outlined.
  - **One Next-up card** with one Start (or Take command when qualified).
  - Tracks, the mentor quote, the shelf and "Why this matters" are gone. The comm strip stays visible, so "next" works
    by voice.
- **Lesson panel** (flush right, 420px):
  - A Map back button, "Lesson n of 8", and a segmented step bar.
  - The patch and the title.
  - CAPCOM's brief is a disclosure: open on the first look, closed later. Replay, Library and NASA facts sit inside it.
  - The question at 20px, then a one-line "how" only where it's not obvious, then the answers as 52px rows.
  - Feedback is a tinted row with an icon. The hint has a lightbulb icon.
  - **Next** is pinned at the bottom of the panel.
  - No story beat on screen (it's spoken) and no "👉".
- **Patch earned:** a large patch, "Patch earned", the badge name, the lesson title, one primary **Next: …**, and a
  quiet Map link.
- **Icons:** a temporary shim, `ui-icons.js` (`icon(name)`, `patch(id)`, the same API as the Art agent's
  `assets/icons.js`).

### Screenshots

`docs/img/ux/r1-*.jpg` (1440 dark only; pruned): home, map, map_mid, lesson_choice, lesson_tap, lesson_feedback,
vocab_listen, vocab_say, patch.

## Round 2: Moon-first, the Moon map, one voice bar (floating), glass cards, Settings

### Inputs

- **Product owner decisions (binding):**
  - The Moon is always the backdrop.
  - The course map is the Moon map.
  - CAPCOM is the voice strip only.
  - The voice bar floats and the kid can move it.
- **Coordinator critique of round 1:**
  - The caption and the strip are two objects in two places.
  - The lesson panel is an opaque sheet that is half empty.
  - "CAPCOM'S BRIEF +" is clutter.
  - Progress is shown twice.
  - The home button is pale, so it reads as disabled.
  - Five chips is too many.
  - The orange dots read as dust.
  - Eyebrows are everywhere.
  - Patches should use the art.

### Critique of round 1 (own)

- **Voice strip and captions:**
  - The caption floats separately from the strip and sits in a different place on home vs lessons.
  - In lessons it repeats the question that is already on the panel.
- **Lesson panel:**
  - A full-height opaque sheet with 40% empty space, which hides a third of the Moon.
  - "LESSON 1 OF 8" and the step dashes say the same thing.
- **Home:**
  - The primary button is pale accent with dark text, which reads as disabled on the dark sky.
  - The place dots behind the headline look like dust.
- **Map:**
  - A grid of patches has nothing to do with the Moon.
  - The globe sits idle behind an opaque sheet.
- **Patches:** generic line icons, not patches.
- **Global:** there is no error or loading treatment beyond raw dev text ("Start everything with `make dev`").

### What changed

- **One voice bar, the same everywhere:**
  - The caption now lives *inside* the strip, above the state row. It folds away when idle, with the spoken word
    underlined.
  - A spoken line that equals on-screen text (question, feedback, visible brief) is hidden from the strip but kept in
    `#captionBar` for screen readers.
  - "Didn't catch that" is a small chip in the state slot.
  - The glass material is theme-aware (`--color-overlay`), AA in both themes over the Moon.
- **Floating voice bar** (`voicebar.js`):
  - **Moving it:** a 6-dot grip, which pointer, touch and the keyboard can all drag. The arrow keys move it 12px
    (48px with Shift), and Enter, Esc or blur snaps it. A double-click resets it.
  - **Snapping:** it snaps to 6 anchors (top/bottom × left/centre/right), clamped inside the stage and under the top
    bar, and re-clamps on resize and when the bar grows.
  - **Remembering:** the position is saved per screen class (Moon screens / cabin) in localStorage. In the cabin it
    stays docked in the comm row until dragged out, and resetting re-docks it.
  - **Collision:** if the anchor would cover the lesson card, Next-up card, patch card, briefing, debrief, Settings or a
    dialog, it moves to the nearest free anchor. The screenshot `vbar_dragged` drags it to the top right in a lesson;
    it lands at the bottom right instead of covering the lesson card.
  - **Caption side:** the caption and chips flip below the row when the bar is at the top.
  - **Announcing and commands:** each move is announced ("Voice bar moved to top right."). The typed commands are
    "move the voice bar to the top / left / right / top right…" and "reset the voice bar". Spoken commands need the
    router (see Router requests).
  - **Reset in Settings:** Settings → Display has "Reset voice bar position".
- **Moon map:**
  - Each lesson is pinned to a real place on the near side, running down to the south-pole outpost. The places are
    listed below.
  - The pins show the art agent's `patch()`: earned in colour, the rest as a grey outline.
  - The next pin is bigger, with an accent ring and a halo.
  - The route follows great-circle arcs: done legs are solid accent and the rest are dotted. Stops round the back fade
    out, and the polar stops are nudged apart with a dot on the true spot.
  - One glass card shows Next up (patch, "Next up · place", title, one line) with one **Continue**.
  - Tapping a pin flies the Moon there, and the card switches to that lesson (Start / Replay). Tapping the selected pin
    again opens it.
  - The top-left pill shows "Flight School 3/8" and the call sign. The NASA credit sits top right.
- **Lesson:**
  - A glass card at the top right that hugs its content and never sits under the voice bar (`--strip-h`).
  - The patch art and title, then a quiet "Brief" text button (the brief is spoken).
  - The step dashes are the only progress shown ("Lesson n of 8" is sr-only for "where am I?").
  - Next sits in the card.
  - The globe flies to the lesson's place. Place dots show only on tap/intent steps.
- **Patch earned:** a centred glass card over the Moon with the large embroidered patch art, "Patch earned", the name,
  and one **Next: …**.
- **Home:**
  - The primary button is solid `--color-accent-strong` (#3563E9, white text, 5.1:1).
  - 3 suggestions plus "Pick for me".
  - No place dots.
  - The NASA credit line sits under the form.
- **Settings** (replaces Access; the gear in the top bar keeps `#a11yBtn`):
  - The sections are Voice · Reading & captions · Display · Alerts · Help.
  - Every control works. The planned sections are in FLOWS.md.
- **Errors:**
  - Offline: "Can't reach Outpost Luna. Close the app and open it again."
  - Flight School offline is the same, in a glass message.
  - Mic blocked: the state "Mic blocked" with the reason in the field. Typing still works.
- **Copy and art:**
  - Merged feat/copy-v3 and feat/art-v3, and dropped the `ui-icons.js` shim.
  - The offers come from `OFFER.*`; the call-sign line is `CALLSIGN_COPY.say`.
  - The lesson intro is three short lines (hello, brief, question), not one long line.
- **Docs:** `docs/FLOWS.md` is the inventory of every view and state.

### Lesson places (frontend `LESSON_PLACE`, for the copy and learning owners to adjust)

| lesson | place |
|---|---|
| moon | Sea of Rains |
| comms | Tranquility Base |
| words | Aristarchus Plateau |
| power | Malapert Massif |
| radiation | de Gerlache Rim |
| life | Cabeus (LCROSS) |
| history | Surveyor 3 / Apollo 12 |
| checkride | Connecting Ridge (the Outpost Luna site) |

### Checklist (round 2)

**Passes:**
- one primary action on the map, lesson, patch and home;
- no emoji (the icons test passes);
- tokens only;
- glass AA in both themes (checked numerically);
- no clipping at 1440 or 1280;
- the voice/typed path drives lessons (the harness answers every step by typing);
- offline fonts.

**Open:**
- The route leg Cabeus → Surveyor 3 → the outpost crosses the Moon. Reorder the places or bend the route.
- The check-ride mini cockpit (Mission's `cockpit.js`) is still dense inside the card.
- Model warming up has no UI yet (FLOWS.md gap).
- The mic-blocked message is browser-worded and truncated.
- The Library HUD needs its own round.

### Screenshots

`docs/img/ux/r2-*.jpg` (1440 dark + 1280 light):
- home
- map, map_mid, pin_selected
- vbar_moved, vbar_dragged
- lesson_choice, lesson_tap, lesson_feedback
- vocab_listen, vocab_say
- patch
- ride
- library
- access (Settings)
- mic_denied, offline
- cabin (voice bar docked)

## Round 3: map geometry, Settings v1, warm-up, Library

### Critique of round 2 (coordinator + own)

- **Map route:** the polar cluster (4 pins nudged by hand) plus the long great-circle arcs over the limb look
  accidental.
- **Pins on the limb:** squashed and clipped.
- **Places:** hard-coded in `ui.js`. They should come from course data.
- **Credit:** sits in a different spot per screen (top right on the map, under the form on home).
- **Settings:** a popover that overlaps the mission briefing, with text colliding. It should be modal.
- **Library HUD:** three stacked bits (toggles, controls, a tiny colour key). The highlight ring is a thick gold
  hoop, the loudest thing on screen.
- **Model warming up:** no UI.

### What changed

- **Map:**
  - The route draws only the legs flown (solid) and the leg to the next stop (dotted). Later legs aren't drawn.
  - Pins show only on the facing hemisphere and fade out before the limb, so nothing is squashed.
  - Close stops are pushed apart on screen automatically, with a dot left on the true spot. No more hand nudges.
  - The camera faces the next stop, so a polar next lesson turns the south pole toward the cadet.
  - Places are data-driven: a lesson's `place` in course.json (`{name, lat, lon}` or a place id) wins, and
    `LESSON_PLACE` is only the fallback (see Requests).
  - The Next-up card enters without jumping sideways.
- **Credit:** one fixed spot on every Flight School screen, bottom left. The voice bar treats it as an obstacle.
- **Settings v1:** a modal sheet over a scrim (closing About if it's open), with a section list on the left and one
  section on the right. Sections:
  - **Voice:**
    - The curated voice list from `GET /api/voices`, with ▶ preview. It is hidden while the endpoint 404s, so
      nothing on screen does nothing.
    - Speed, expressiveness (calm ↔ lively), and "describe what happens".
  - **Sound:** master volume (scales every voice and the crew audio, and stacks with the floor's ducking and fades),
    alarms volume (chimes), flash, vibrate.
  - **Listening:** hands-free vs hold to talk (`voice.js` ignores open-mic turns in hold mode) and the
    background-voice filter (relaxed / normal / strict).
  - **Reading & captions.**
  - **Display:** theme (system / light / dark, in step with the top-bar toggle), high contrast, less motion,
    graphics (high / low = 1× pixel ratio), reset the voice bar.
  - **Cadets:**
    - Profiles show the call sign and n/8 patches. The active one is marked "Playing"; the others have Switch.
    - Add a cadet, up to 6.
    - Level: Cadet 7–9 / Commander 10–12.
    - "Reset my patches" needs a second tap.
    - Each profile keeps its own call sign, progress, settings and voice-bar position.
  - **Help.**
  - **Sending prefs:** `{t:"prefs", type:"prefs", voice, rate, expressiveness, filter, level, listen}` goes on the
    session socket when the session connects and on every change.
  - **Extension point:** `window.__outpost.settingsSections` lets the gestures agent add "Camera & gestures"
    (DESIGN_SYSTEM.md).
- **Warm-up:** until `/api/health` reports the ear and Steer TTS loaded, the voice bar shows "Starting voice…" (dots).
  After 3 minutes without them it shows "Voice off · type". Typing works the whole time.
- **Library:**
  - One toolbar: Places · Hardware | Near side · Far side | Tour · Find it. The colour key is hidden; hover or focus a
    marker for its name.
  - The highlight ring is thin and white.
- **Voice bar:** "on the right" is accepted. The router routes the spoken bar commands (feat/router-v2, merged).
  `addObstacle` / `removeObstacle` and the `outpost:voicebar` event are there for the gesture self-view and hint chip.
- **Merged:** feat/ux-mission b2c89f6 and integ/desktop-v2 (router v2).

### Requests

- **Learning designer / copy:** give each lesson a `place` in `course.json`:
  - either `{"name": "Malapert Massif", "lat": -85.98, "lon": -1.67}`, or a place id from `/api/places`;
  - the map, the lesson camera and the Next-up card read it;
  - until then, `academy/ui.js` `LESSON_PLACE` is the fallback.
- **Backend:** `GET /api/voices` (curated 10, `preview_url`), and honour the `prefs` frame:
  - `voice`, `rate`, `expressiveness`, `filter`, `level`;
  - `listen: "ptt"` means: don't act on open-mic ear turns relayed server-side.
- **Mission (3D cabin):** the check ride should be a simplified version of the new cabin. Until then it keeps
  `cockpit.js` mini inside the glass card.

### Screenshots

`docs/img/ux/r3-*.jpg` (1440 dark + 1280 light):
- home
- map, map_mid, pin_selected
- lesson_tap
- library
- access (Settings · Voice), settings_listen, settings_cadets
- warming
- patch

## Round 4: lesson step types, polar map zoom, accuracy, functional pass

### Critique of round 3 (coordinator + own)

- **Polar map:** with the next stop at the pole, the 4 polar pins were a tight, unlabelled cluster in the middle of a
  whole-Moon view.
- **Fill-the-blank:** the prompt quotes the whole sentence, and then the step draws the same sentence again.
- **Say-it-back:** "Say this word back to me: regolith" sits above a "SAY IT BACK" label above "regolith".
- **Vocab source:** "Heard in:" plus a truncated 60-character link title plus "Hear the crew say it" on 3 lines.
- **Vocab listen:** the "how" line overlaps the revealed meaning (a negative margin).
- **Voice bar:**
  - It jumped to the bottom left in some lessons because the lesson card counted as an obstacle even though the
    card's max-height already keeps clear of a bottom bar.
  - "Reset the voice bar" could land somewhere other than the bottom: the Next-up card moved down while the bar was
    at the top, and then blocked the bottom.
  - It moved when Settings opened, even though the modal sits above it.
- **About:** "Artemis III hasn't landed yet" is wrong since 2026-02-27 (audit #1). It also over-claimed "real NASA
  data" (#10).

### What changed

- **Polar map:**
  - When the next stop is polar, the camera looks straight down at the pole (`flyTo` takes a `maxLat`; the map uses
    88°) at a close zoom, so the polar pins spread out.
  - The next pin is always labelled and reserves room for its label in the de-overlap; the other pins are labelled
    on hover or focus.
  - Anywhere else, the whole Moon.
- **Step types:**
  - Fill-the-blank shows only the prompt's lead-in ("Fill the blank"); the full prompt is still spoken.
  - Say-it-back drops the duplicate label.
  - The vocab source is one quiet row: "Hear the crew say it" plus a "Source" link, with the title as its tooltip.
  - The answer area has a consistent gap.
  - New harness state `lesson_retry`: two misses give try-again feedback plus a hint.
- **Voice bar:** a lesson or ride card, or the Next-up card, never counts as an obstacle for a bottom anchor, because
  they stack above it by design. Modals (Settings, About) don't move the bar.
- **About:**
  - Rewritten to the audit: Artemis III is a 2027 Earth-orbit test, and the first south-pole landing is planned for
    Artemis IV.
  - Pasted verbatim from COPY.md §8: the header line, the Flight School paragraph, and the LOLA/Kaguya and DONKI
    cells.
  - Added: CAPCOM and Houston are played by the game; privacy.
  - Merged feat/artemis-ref and feat/copy-v3 694f2e8. The copy guard tests pass.
- **Functional pass** (`frontend/tools/ux_flow.py`, 20 checks, 0 console errors), covering both input paths:
  1. first launch and the call sign by voice;
  2. lesson 1 entirely by voice (intent, tap by naming, choice, vocab_match), the patch, then "next";
  3. lesson 2 by click and typing (choice + 3 read-backs);
  4. Map; a done pin, then Replay, then back;
  5. the voice bar moved and reset by command;
  6. Settings: a pref saved, Esc closes;
  7. a Library question opens the card; back to Flight School.
- **Backend tests:** `test_handsfree_run`, `test_turn_router`, `test_academy` and `test_copy` pass (90 tests).

### Screenshots

`docs/img/ux/r4-*.jpg` (1440 dark + 1280 light):
- map_mid (polar zoom)
- lesson_keywords, lesson_command, lesson_retry
- vocab_listen, vocab_match, vocab_say, vocab_fill
- patch
- ride

## Round 5: Library details, qualified map, high contrast + 150%, Settings on the backend

### Critique (own)

- **High contrast + 150% text:**
  - The voice bar vanished off screen, because its left/top were multiplied by the CSS zoom.
  - The lesson card was shrunk back to 400px, so the title wrapped onto 3 lines.
- **Library:** the card, tour and Find-it were never shot. They read fine, but the answer card is long (the story
  plus More plus sources).
- **Settings → Voice:**
  - It showed a made-up "CAPCOM" entry on top of the server's own default.
  - The server's echo of the applied prefs was dropped by `session.js`, because "prefs" was not in its VISUAL set.
- **Voice choice:** the chosen voice also changed CAPCOM. The contract says only the guide changes, unless
  `voice_all` is on.

### What changed

- **Voice bar:** zoom-aware. It uses its on-screen size, and left/top are divided by the zoom.
- **Lesson card at 150%:** grows with the text instead of being shrunk.
- **Settings → Voice:**
  - The server's 10 voices, with the first as the default, and ▶ previews.
  - A "Use this voice for everyone" toggle.
  - The server's `applied` echo shows as "In use: …".
- **Client-spoken lines:** they carry `steer_voice` (guide only, unless `voice_all`), `speed` and `expr`.
- **Barge-in:** the client thresholds follow the filter level, with a test.
- **New states:** `library_card`, `library_find`, `library_tour`, `map_done`, `hc_lesson`.

### Pending

- **Steer recalibration** (feat/settings-be: −14 LUFS, faster baseline): re-check the speed labels, the
  master-volume mapping and the crew gain against the numbers in `docs/VOICES.md` when it lands.
- **Check ride:** the Mission ride API.

### Screenshots

`docs/img/ux/r5-*.jpg` (1280 light):
- library_card, library_find, library_tour
- map_done
- hc_lesson (high contrast, 150%)
- access (Settings · Voice with the server's voices)

## Round 6: the six globe step types (learning-v3), the new route, leftovers

### Inputs

- **Merged** `integ/desktop-v2` 499d50d (learning-v3):
  - 6 new globe step types, a `place` on every lesson, and the new lesson order;
  - `globe.js` `poleView`, `setSunDir` and `centerLatLon`.
- **Conflicts resolved, keeping both behaviours:**
  - `flyTo`'s 4th argument takes my `maxLat` number or their `{clamp:false}`;
  - the return keeps my `project` and their three functions;
  - `ui.js` keeps `stepTap`.

### Critique of the minimal renderers (draft shots, then mine)

- **Answered steps:** an answered step emptied the card. The kid lost what they picked, and a predict reveal had no
  context.
- **CAPCOM's shown answer:** after 3 misses it was only text; nothing was highlighted.
- **Compare:**
  - The two sites were only buttons; the globe showed nothing to compare.
  - The server's `data` (sun days, Earth days, km to ice) was never shown.
- **Terminator:** the "night" side was lit by the strong fill light, so there was no visible line to tap.
- **Route:** no progress feedback, no legs drawn, and a leftover "Surveyor 3" ring and label from the lesson's place.
- **Turn the Moon:** the side buttons were plain text, and the "This side" pill was ambiguous. Answered by voice, the
  globe didn't turn.
- **Earth view:** the "how" line repeated the prompt, and "Sometimes" overflowed its button.
- **Crew clips** marked `when: "after"` showed a button before the answer instead of playing after it.

### What changed

- **Answered steps stay on screen, locked:**
  - the kid's pick is marked "Your guess" (accent) or "Correct" (green);
  - CAPCOM's answer is marked "Answer" (green);
  - the buttons are disabled.
- **Feedback kinds:** `ok` (green), `reveal` (accent, for a predict guess, never "wrong"; carries the reveal source
  when there is one), and `shown` (neutral, "Here it is…").
- **On the Moon after a pass:** route steps draw the right route with numbered dots, and turn-the-Moon steps fly to the
  far side. A CAPCOM-shown answer flies there or rings it.
- **predict:** "Guess first. Then see the real data." plus numbered guesses. Every guess passes.
- **earth_view:** three compact answers in a row; the prompt carries the question.
- **globe_side:**
  - "Drag the Moon to turn it, or pick a side": two big side buttons, each with a little Moon disc;
  - a quiet "Check this view" grades where the camera looks.
- **terminator:** no buttons, just "Tap where light turns to dark". The globe dims its fill light while the step's Sun
  is locked, so the line is visible.
- **compare:**
  - two cards side by side, plus two labelled, tappable pins on the Moon (from `/api/mission/sites`);
  - after the answer each card shows the data, with the step's metric first and large.
- **route:**
  - a progress row (dots plus "Stop n of N", with Start over once you've tapped);
  - numbered dots and legs drawn on the Moon as you tap;
  - place dots on, the lesson ring cleared.
- **Clips:** a clip marked "after" auto-plays once the success line is said, and stays as a replay button.
- **Map:**
  - the lessons follow the course order (`course.json` is in map order: Tranquility → Surveyor 3 → Malapert →
    Shackleton → de Gerlache → Cabeus → Shackleton Rim);
  - the places come from `course.json`;
  - no more jump back to the equator.
- **Mission start sends `level`** (`client.start({…, level})`), so the band applies from the first request.
- **Mic errors are short:** "Mic is blocked. Type instead.", plus the no-mic, mic-busy and didn't-start messages.
- **The chosen voice applies to the guide only** unless `voice_all` is on (done in round 5).
- **Voice calibration** (integ/desktop-v2 027f1a3, merged):
  - `volume` is a 0–2 pref (1 = −14 LUFS) that the server applies; the guide `<audio>` stays at 1 and there is no
    client gain on Steer;
  - client-rendered lines add `style.volume`;
  - crew audio goes through Web Audio: the clip's `gain_db`, then a limiter (−1 dB, ratio 20, 3 ms / 50 ms), then
    the master volume;
  - a saved voice the server no longer has falls back to the default, and Settings opens at Voice once.
- **Map legs** use each stop's own done/next state, so a course where the earned patches aren't the first N stops
  still draws the right legs.
- **Functional pass:** 22 checks, 0 console errors. Lesson 1 runs by voice (intent, earth_view, predict, globe_side,
  intent); lesson 2 runs by click and typing (vocab_match, choice, predict, route, choice).
- **Backend:** `test_handsfree_run`, `test_handsfree_loop`, `test_turn_router`, `test_academy`, `test_learning` and
  `test_copy` pass (130 tests).

### Screenshots

`docs/img/ux/r6-*.jpg`:
- **Shots:**
  - every globe step, open (`g_earth`, `g_predict`, `g_side`, `g_terminator`, `g_compare`, `g_route`);
  - answered (`g_earth_done`, `g_predict_reveal`, `g_side_done`, `g_compare_done`, `g_route_done`);
  - CAPCOM's shown answer after 3 misses (`g_shown`);
  - the map (`map`, `map_mid`).
- **Sizes and themes:**
  - 1440 dark and 1280 light for everything;
  - 1440 light and 1280 dark for the six open steps.

## Router requests (for the hands-free owner)

- **Done** (feat/router-v2): "move the voice bar to the top / bottom / left / right / top left / bottom right …",
  "put the voice bar on the right", and "reset the voice bar" route to `nav` `a11y`. The client runs them through
  `voicebar.parseBarCommand`.
- **Open:** with `listen: "ptt"` in the prefs frame, ignore open-mic turns relayed by the ear (only push-to-talk
  turns count).

## Gesture requests (for the gestures agent)

- **Settings:** add "Camera & gestures" by pushing a section to `window.__outpost.settingsSections` (DESIGN_SYSTEM.md
  → Extension points).
- **Self-view and hint chip:**
  - register each with `window.__outpost.voiceBar.addObstacle(selector)`;
  - snap to the bar's six anchors (`spot(anchor)`), avoiding the bar's own;
  - listen for `outpost:voicebar` to re-place them.
- **Intents:** Flight School actions you can emit as intents, with the handlers already exposed:
  - next / continue: `academyUI.nav("next")`;
  - back / map: `nav("map")`;
  - yes / no: `nav("accept_offer")` / `nav("decline_offer")`;
  - select: focus + click.
- **Map pins:** each is a `<button class="pin" data-l="…">`. Point-and-dwell can click it: the first click selects
  and flies there, the second opens the lesson.

## Mission

Owner: Mission UX (`feat/ux-mission`). Files: `mission/*` (`ui.js`, `cabin.js`, `cockpit.js`, `terrain.js`,
`mission.css`), `cabin.css`, `src/mission.css`. Screenshots: `docs/img/ux/mission/<round>-<state>-<w>x<h>-<theme>.jpg`
(scratchpad drivers: `shots.py` for the states, `func.py` for the end-to-end pass).

### Round 0: baseline (before)

`r0-picker-1440x900-light`, `r0-cabin-1440x900-dark`, `r0-storm-1280x720-light`, `r0-debrief-1440x900-light`.

- **Picker:** a side panel with a 5-line paragraph, five cards each with three emoji facts (☀ ❄ 🌍), a site
  paragraph, three long source chips, "Team roles (optional)", and Take command below the fold at 1440×900. A
  separate CAPCOM card on the left repeats the brief with three lesson paragraphs. Two things talk at once.
- **Cabin:** a good direction (window over the NASA terrain, three display units, real controls), but loud:
  - The bulkhead is a brushed, grained, bolted SVG frame with 40+ bolts and Dzus fasteners. The plates have their own
    bolts. Everything competes with the window.
  - The window carries a breadcrumb that duplicates the view switcher, a MET/score line, a three-line sky readout,
    a top-centre NASA credit line and "LOW-LIGHT CAMERA · SUN BELOW HORIZON" over the terrain.
  - Displays put the page keys on both sides (PWR LIFE RAD COMM + SEL▲ SEL▼ +5 −5) and their text is 11px.
  - "NO EARTH" lights amber all the time, so amber means nothing. NIGHT is a lamp.
  - Two condensed fonts (Barlow Condensed, Share Tech Mono) from Google Fonts: not offline, not the design system.
  - END SHIFT and PTT · HOUSTON are both styled as hero buttons; END SHIFT has hazard stripes. No single primary.
  - A duplicate caption: the cabin's own phosphor line plus the docked caption bar.
- **Storm:** two banners at once: the mission banner (emoji, a run-on line with no spaces: "Solar stormG5…") over the
  window, and the accessibility visual-alert banner stacked above it. Both cover the middle of the view.
- **Debrief:** "Mission paused" with grade F while the mission is only paused. A dashed "☀ storm" marker. Six lessons
  paragraphs, a "Data we used" column of methodology text, a Mars line, and a stale "Warning" banner over the sheet.
  The CAPCOM card peeks out on the left. The primary action is below the fold.

### Round 1

`r1-{picker,cabin,storm,debrief}-{1440x900,1280x720}-{light,dark}.jpg`

**Cabin** (`cabin.js` rewritten, `cabin.css` rewritten on tokens):

- One grid, top to bottom: window → three displays → controls → comm strip, with one gap token and one plate style.
  The window is a hole in the panel: the glass's spread shadow paints the panel round it (no SVG bulkhead), so ORBIT
  still shows the globe through it.
- Window: clock ("Day 1 · Shift 1", site and score under it), a segmented view switcher with `icons.js` glyphs, the sky
  readout as one line bottom-left, the NASA credit bottom-right. Breadcrumb, MET line and the top credit are gone.
- Displays: one big number per unit (Power %, Life support %, Dose mSv) with a bar, then 3–4 rows. Page keys are one row
  under each screen. On PWR, the seven loads are buttons (select) and −5 / +5 act on the selected one.
- Controls: Hab (Shelter under a "Lift" cover, Heaters, Science as switches), Rover (Ice · Explore · Home), Shields ring
  (−/+, arrow keys), Caution & warning (8 lamps + master alarm), Call Houston + **End shift** (the one primary) and a
  quiet "Finish mission".
- Colour: red and amber only on lit warning/caution lamps, the master alarm and the alert strip. "No Earth", "Rover out",
  "In shelter" are blue status lamps; they never trip the master alarm.
- Alerts: the storm is a **strip along the glass's top edge** (icon, "Solar storm", "Real event, 10 May 2024 · NASA
  DONKI", Shelter / Shields 40); the clock and the switcher drop below it. Short warnings use the same strip for 7 s.
  The a11y module still flashes the screen edge, vibrates and announces (`a11y.visualAlert`), but its banner is hidden in
  the cabin so there is one alert, not two. The master alarm rings the glass in red instead of tinting it.
- Voice: every order animates its control (`.is-moved` on the shield ring, the switch, the rover plate, the load row);
  verified by `func.py` (shields to 40 → ring at 40 and pulses; rover for ice → Ice pressed, plate pulses).
- Houston: the PTT button shows "Signal travelling" with a progress line for the real round trip; the floating
  Moon–Earth signal panel is gone.
- Fonts: Inter / JetBrains Mono from tokens; `@fontsource/barlow-condensed` and `share-tech-mono` removed.

**Picker** (Moon-first): the globe is the backdrop with the five sites as pins on the south pole (selected one
labelled); a glass panel with a 2–6 word headline, one line, a Sun / Earth / Ice table (radio group, arrow keys), one
source link, **Take command**, and Team roles behind a disclosure. No CAPCOM card.

**Debrief:** a glass sheet: headline (Mission complete / paused / over), one line, Grade + Score (grade hidden while
paused), a shift-by-shift chart with storm shifts shaded, up to three one-sentence takeaways each with its source,
**Fly again** / New site, and "NASA data used" behind a disclosure. On short screens the chart and takeaways sit side by
side so the buttons never scroll away.

**Functional pass** (`func.py`, voice): pick Malapert by voice, arrow keys on the list, take command, shields to 40,
shelter, rover for ice, end shift ×4 to a real DONKI storm (2017-09-07), shelter, call Houston, debrief, fly again. All
pass except "shelter while the rover is out", which the sim correctly refuses ("Call them back first"); the test now
recalls the rover first. No console errors from Mission code (two `blob:` 404s per run come from `floor.js` revoking a
TTS clip that was cut off).

**Round 2 queue:**

- Picker pins: four of five sites are within 2° of the pole, so their dots overlap at any globe distance the camera
  allows. Try a polar inset, or fan the labels out with leader lines.
- Debrief takeaway 2 is three lines; the chart is flat for short missions (paused on day 3). Show the shift dots and
  the storm band labels.
- Lamp legends wrap to two lines at 10px; try 3 × 3 with the master alarm in the grid.
- Rover plate: show the route progress (the window has it; the plate only says "Parked" / "Ice run · 6 h").
- Data-driven slots for the game redesign (`feat/learning-v3`): warning confidence + lead time on the alert strip,
  score breakdown on the debrief.
- `src/mission.css` (moved from `styles.css`) still uses the legacy aliases: rewrite on tokens or delete what the new
  screens no longer use.

### Round 2: the cabin is a real cabin again (3D), five panels, every state

The owner compared r0 and r1: round 1 had flattened the cabin into a dashboard. Round 2 keeps round 1's clarity (one big
number per display, red/amber only for real alerts, the storm strip on the glass, voice orders pulse their control,
tokens + Inter/JetBrains Mono) and rebuilds the cabin as a room.

- **3D cabin** (`mission/cockpit3d.js`, three.js): the commander's seat in a surface habitat whose panels follow Orion's
  design language (three glass display units side by side, switch panels round them, a guarded switch, a big forward
  window). It is "inspired by Orion's cockpit", not a replica, and our outpost is not a NASA habitat. No NASA logos.
  - The window is a real hole in the bulkhead: the existing LOLA terrain and NASA globe views show through it, framed to
    the window. Lit by the window (area light), a ceiling strip and the displays' glow; PBR materials from the tokens.
  - The controls are the real DOM, mounted on the console faces with `CSS3DRenderer`: every switch, knob and key is still
    a `<button>`/slider with a label, focus, screen-reader text and voice. Nothing is canvas-only.
  - Panels: Displays (DU1 power, DU2 life support, DU3 radiation), Habitat, Rover, Radiation, Comm, and the pedestal
    (Caution & warning + End shift). Click a panel in the seat view, Tab into it, or say "open the X panel": the camera
    dollies in until the panel's DOM is about 1:1 (crisp). Seat button, Esc or "back to my seat" return.
  - Each alarm lights its own panel, with a glow and a label chip that says "Alert"/"Check" (never colour alone). A new
    warning brings the camera back to the seat so the strip and the lit panel are both in view.
  - Cadet (Settings → level): CAPCOM's two-way offers open the panel they are about with two big buttons there.
    Commander: panels stay closed until the kid opens them.
  - Motion: pointer parallax and a slight head-bob; reduced motion makes every camera move a cut. Settings → graphics
    "low" drops display glows and reflections and renders at 1× (`setQuality`). No WebGL → the round-1 flat grid.
  - 60 fps at 1440×900 and 1280×720 (headless Chromium, ANGLE/Metal), cabin + terrain together.
- **Gestures** (`feat/gestures`): `cabin.look(dx, dy)`, `highlightPanel(id)`, `openPanel(id)`, `seat()`, `nextPanel()`,
  `prevPanel()`; one entry for every input, `missionUI.intent(name, arg)` (`look`, `highlight_panel`, `panel_open`,
  `panel_next`/`prev`, `view_next`/`prev`, `confirm`/`cancel`, and every router nav intent). The camera is off by default.
- **Check ride**: `createCabin(root, {mode: "ride", onCommand, onEndShift})` → the same cabin with the displays, Habitat
  and End shift only; `cabin.cue("heaters" | "science" | "shields" | "end_shift" | "load:<key>" | …)` pulses one control
  and opens its panel; `cabin.update(state)` as usual.
- **Picker**: Sun and Earth in days of the 10-day mission ("10/10"), the yearly-average sun on the picked site's second
  line; "NASA candidate region" (Malapert, de Gerlache, NASA's Oct 2024 list) or "Studied by scientists"; pins with a
  label column and leader lines; row ↔ pin hover; Team roles removed. The 86 % vs 100 % bug is gone from the picker
  (C7 in `LEARNING_DESIGN.md`): both numbers now show, each labelled. The debrief text is the backend's.
- **Accuracy**: "Solar particle storm" (no G-scale) with the DONKI link; "Pretend tech" tags on shields and the
  greenhouse; debrief takeaways never claim Artemis III lands; `mock.js` now carries the real five sites and numbers.
- **Debrief**: follows the theme; no toasts over the sheet; the legend sits under the plot and storm bands are clipped
  to it; takeaways ≤ 20 words (parentheticals dropped, cut at a clause), the source link carries the detail.
- **Functional pass** (voice and click, `func.py`): pick a site → take command → shields to 40 → shelter → rover for ice →
  end shift to a real DONKI storm → shelter → call Houston → debrief → fly again. Both paths pass; no console errors.
  Click path: in 3D the first click on a closed panel opens it, the second acts (Seat first if another panel is open).

Screenshots: `r2-*` (every state, 1440×900 dark; key states at both sizes and themes), `spike-*`, `ride-*`.

### Round 3: full panels, the check ride in the cabin, learning-v3, the intent bus

`r3-*` (1440×900 dark): seat, panel-habitat/rover/radiation/comm/pedestal, storm-active, cabin-site-day, ride.

- **Panels hold their real content:**
  - Habitat: life support / greenhouse (pretend tech) / heaters meters, the heater and science switches, objectives with stars.
  - Rover: the task, ETA, a route mini-map, and battery, dose and ice runs when the sim sends them.
  - Radiation: the dose meter, the rate, "Shelter ready in N h", the warning's lead time and confidence meter, Shelter, Shields (pretend tech).
  - Comm: a 10-day timeline with a now marker (real windows when `comm_windows` arrives), Earth, the next window, radio delay, science to send, forecasts with confidence.
  - Power (DU1): the Sun strip (`next_sun_change_h`) and a Night key (`power_save`), shown only when the sim has night mode.
- **Pedestal:** the C&W lamps are 15px and readable from the seat. End shift is a lit 168×120 push-button.
- **Storm window:** a storm is glare (bloom 1.45), not fog. Re-clicking the view you are already on no longer re-flies the camera, which was the "grey haze" in the r2 storm shot.
- **Check ride:** `academy/ui.js` (`[ride]` lines) mounts the cabin full-stage, left of the lesson card, with the terrain behind the window.
  - The panels are Displays, Radiation and Rover. The step's expected order is cued.
  - The cabin's controls answer the step with the order buttons' words, graded by the same path.
  - `frontend/tools/ux_flow.py` passes 20/20 with 0 console errors.
- **learning-v3:**
  - Cabin and start: `env.warning`, `objectives`, `power_save`, `env.next_sun_change_h`, and `level` sent on start (Settings).
  - Picker: `site.status`/`status_label`.
  - Debrief: `stars` and `try` ("Next time").
- **Intent bus** (`input/intents.js`, `feat/gestures`): registered at priority 10 through `import.meta.glob`, so the mission builds with or without the bus.
  - Cabin: next/prev panel, panel_open/back, look (with highlight-on-aim), yes/no, call_houston, end_shift, and the router's panel/view names.
  - Picker: next/prev and yes.
  - The gestures branch conflicts with integ in files I don't own (main.js, a11y.js, globe.js, package files), so it is not merged here.
- `src/mission.css` and `mission/mission.css` are on tokens; no legacy aliases.

**Round 3 queue:** the 2.5D layered-DOM fallback for low-end GPUs (today: flat grid without WebGL), the Comm panel's
comm-window timeline and science waiting, the Rover panel's route, Orion-style bezel keys and a twizzle knob on the
DUs, `src/mission.css` legacy aliases, and the picker framing (the camera can't look straight down at the pole, so the
pins sit low; the labels now stay clear of the voice bar).

### 0.3.12 polish, group A: voice bar, check-ride cockpit, lessons

Evidence: the 0.3.11 polish audit (headless, 1440×900): voice bar stuck, clipped ride cockpit, repeated instructions.

- **Voice bar (P0):** "Starting voice…" only while the ear is really starting. `/api/health` carries the ear's load
  error (model server `arc_ear.error`) and which ear the voice waits for (backend `voice: {ear, fallback}`);
  `engine.warmState` turns a load error with no Deepgram fallback into **Voice off · type** at once, and so does the
  ear's first fatal `{"t":"error"}` (`engine.earErrorIsFatal`; a model server still starting, a full pool, a reload
  after a hung decode or a dropped stream still reconnect quietly). Grey mic, one fix line in the hint slot
  (`VOICE_FIX`); an ear that answers (`{"t":"ready"}`) clears it.
- **Check-ride cockpit (P0):** one cabin across the stage (no globe beside it). The 3D seat view is centred in the part
  left of the lesson card (`--ride-inset`, a camera view offset; the CSS3D panels render that part only) and its field
  of view widens until every console's body is inside it (`cockpit3d.fitFov`): the panel row scales, never clips. The
  Rover takes the Habitat's high seat in the ride (`RIDE_LAYOUT`). The caution & warning strip and master alarm are in
  the ride (the storm lights SOLAR STORM and HIGH DOSE); its End shift stays hidden. The clock reads "Day 1 of 2" and
  names the site (ride HUD: `site`, `ride: {day, days}`; `mission/ride.js`).
- **Fly the check ride (P1):** before the core lessons are done the button carries "Unlocks after 6 lessons (2/6)" and
  opens the next lesson; once ready it opens the ride itself (it used to drop the cadet on the map).
- **One instruction per step (P1):** the first-use "New" chip replaces the "do this" bullet; TTS and captions never say
  "New:"; captions fold the lead and the New line when they are on the card. The map no longer explains its own card
  ("Tap Start lesson", "Next: <title>" over the Next up card).
- **Predict before watch (P1):** "Watch how" waits in the Brief until the first answer, then sits under it; core lessons
  show NASA videos only (third-party extras stay on the Try-at-home card). A guess step waits for a guess: other words
  are never a miss and never reveal the answer, and a guess no longer matches a fuzzy near-miss of a label word.
- **Houston (P1):** the ride's radio call answers once, Houston's own reply with the 1.3 s light-time line (20 words).
- **Cabin readability (P1, quick wins):** unlit caution legends at .72 (about 5:1, was about 2:1). Console slant measured
  from the seat (`.c3.__c3.slant`): at most 7.5° in a mission, under 1° in the ride. Not done here: the 18 px HUD floor
  (deck sub-lines, progress chips, Now-card labels are 10–16 px), which belongs to the bigger cabin redesign.
- **Checks:** `tools/mission_ui.py` passes at 1280×720 and 1440×879 (as on main); `tools/ux_flow.py` 22/22 (its console
  errors were `/api/tts` 502s from a stub model server). Shots: before / after for the voice bar, the ride (question,
  Houston, storm at 1440 and 1280), lessons 1–2 and the Mission gate.

### 0.4 part 2: the cabin redesign, real NASA views

Owner's goal: the inside view looks like a person in a real spaceflight cabin with a real control bar (Orion's language:
flat display units with bezel keys, readable annunciators), and the window views are real NASA views. Shots:
before / after at 1440×900 and 1280×720 (seat, Earth below / up, site, orbit, storm, Radiation console, check-ride
storm, the hub).

- **One cockpit bar.** In the Mission cabin and the check ride the app header folds into the cockpit's top bar
  (`cabin.js foldHeader`, `body[data-cockpit]`): the same nodes (sections at the left, Settings · Mute · Theme · About at
  the right, drawn as bezel keys over the bar's ends), so the keyboard path, Mute next to Settings and every selector
  stay. Between them: **one display unit** (Day and time, the clock's state lamp and word, Sun / Earth, then
  Days · Science · Ice and the Log key) and three bezel keys (Play, Skip, Menu). The window's camera keys (Orbit, Site,
  Rover, Earth, Center) are one bezel row under the bar. The light header strip over the cockpit is gone; Up from the
  bar reaches the header keys (`spatial.js`).
- **18 px floor** for the HUD (`--hud-min`): the display unit, the keys, the Now card (label, title, meta, buttons, the
  say line), the alert strip, the rover pill, the Earth note. Narrower windows drop a key's word before its glyph, then
  the sky line and the brand.
- **Dark first run** (`PREF_DEFAULTS.theme = "dark"`, the pre-paint script): a choice made in Settings or with the top
  bar's theme key stays (System follows the OS as before).
- **No ceiling strip** (`cockpit3d.js`): its white bar showed as a thin line under the top bar at the wider fields of
  view `fitFov` uses.
- **Rover console**: its status ("Parked", "Ice run · back in 6 h") is at the top, never under the CAPCOM strip.
- **Window, real NASA views** (docs/MEDIA.md "NASA views", all optional; without the pack: today's visuals): NASA's
  HDU habitat at the outpost and lit solar arrays (no black slabs); the Earth view never empty (Earthrise / Earthset
  inset with "Earth rises Day N" and an arrow when Earth is down); the real Sun (SDO, 14 May 2024) in the storm strip
  and on the Radiation console, in missions and the check ride.
- **Mission hub**: straight down on the pole (`{ clamp: false }`), the LOLA relief sharp, the site named on its dot,
  the view centred in the free area left of the panel.
- **Settings**: "Save a diagnostics file…" and "Reset my patches" are 3-second holds (`bindHold`), like Reset.

### 0.4 cabin follow-up: readable in a storm, a Sun you recognise, the outpost in the window

A reviewer's notes on the 0.4 part 2 shots. Shots: before / after at 1440×900 and 1280×720 (seat, site, storm, storm
with the Radiation console open, the Rover console, the check-ride storm, the Site window over two minutes of drift).

- **Storm readability.** The takeover's shade covered the whole cabin (58% black over the consoles), so in a storm the
  Habitat, Rover, Displays and Comm consoles nearly vanished. In the 3D cabin the shade now sits between the room
  (WebGL shell and the window) and the consoles' DOM faces (`.c3::after` under `.c3-css`); a storm adds red alert light
  to the room (`cockpit3d setAlert`: hemisphere, cabin light, window light) and a red rim on each console. The cockpit
  bar stays at full strength. `tools/mission_ui.py storm_checks` forces a storm and checks every console text against
  its plate through every opacity and shade: values ≥ 4.5:1, labels ≥ 3:1. Without WebGL the flat cabin keeps a lighter
  shade (34%).
- **The real Sun.** AIA 131 is a dim teal disc (median ~35/255), so at 50-90 px it read as a dark blob, and swapping an
  `<img>` src every 140 ms showed black while each frame decoded. Each frame is now drawn once into a 320 px canvas
  (`cabin_views.js prepareFrame`): cropped to the whole disc (limb and corona, so AR 13664 at the west limb stays in),
  stretched to its lit pixels and mapped onto a gold ramp; the loop starts on the flare frame (16:55 UTC), skips a frame
  that isn't ready, and the frames are toned as soon as the pack is in (`preloadSun`). Until the first frame is drawn
  the disc is a warm glow, never dark. The Radiation console's Sun is 150 px with a ring on AR 13664 and "X8.7 flare" on
  the flare frame; the storm strip's is 64 px. Credit unchanged: "The actual Sun, 14 May 2024 · NASA/SDO".
- **Site view.** The camera circled 64 m out and aimed 18 m past the outpost, leaving NASA's HDU a few dark pixels.
  It now orbits the middle of the outpost (`terrain.js SITE_FRAME`: habitat, rover park, array) 52 m out, 15 m up, at
  42°, so the habitat, the arrays and the rover read at a glance over the whole drift; the HDU's bounce light is a
  little stronger. The Sun stays low (long shadows).
- **Flat consoles.** Rover and Comm were yawed 0.6 rad and pitched 0.62, the pedestal laid back 1.0: "Ice · Explore ·
  Home" and "Call Houston" leaned 13-15°. Every console face is now nearly square-on to the seat (yaw ±0.18, small
  tilts), ≤ 5° of lean at any window shape (`cockpit3d consoleSkew`, `c3.skew`; tests/cabin_flat.test.js and
  `mission_ui.py skew_checks` fail over 8°).
- **ux_audit2.py** holds "Reset my patches" for 3.4 s with a real pointer (a tap first, which must do nothing) instead
  of clicking it twice.

## Copy requests (for the copy owner)

- **Mission (from Mission UX):**
  - Debrief takeaways come from the backend `lessons[].text` (2–3 sentences each); the debrief shows only the first
    sentence. One short sentence per takeaway (≤ 110 characters) would read better.
  - `d.why` on the debrief: one sentence, ≤ 80 characters.
  - Picker line "Sun for power. Ice for water. Earth for radio." and headline "Pick your outpost site" are in
    `mission/ui.js`; move them to `story.js` if you want to own them.

- **Home headline:** `SCHOOL.hero` + `SCHOOL.hero2` is the home headline. It needs to fit 2 lines at 40px in 600px:
  ≤ 32 characters per line.
- **Map card blurb:** `LESSON_BLURB` is the only line on the Next-up card. Keep each ≤ 70 characters.
- **Lesson titles on the path:** `course.json` lesson titles show under each patch stop. ≤ 24 characters (2 lines of
  ~13) works best. "Talk like Mission Control" and "Lessons from past missions" wrap to 2 lines and are at the limit.
- **Lesson brief:** `course.json` `brief` sits inside a disclosure. Shorter is better: ≤ 2 sentences.
- **Step prompts:** `course.json` `prompt` is the 20px question. Ideally ≤ 90 characters, with no "say it, or tap…"
  in the prompt itself, because the panel shows a "how" line.
- **UI labels:** these live in `academy/ui.js` `UI` and `HOW`, `main.js` `PH`, and `index.html`. They are: Start, Next,
  Map, "Hear it again", "NASA facts", "CAPCOM's brief", "Next up", "Patch earned", "Take command", "Type instead",
  "Type an order", "Ask about the Moon", "Flight School / Mission / Library". Edit them in place if you want different
  words.
