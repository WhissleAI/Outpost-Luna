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

## Router requests (for the hands-free owner)

- "move the voice bar to the top / bottom / left / right / top left / bottom right …", "put the voice bar on the
  right", and "reset the voice bar": these should route to `nav` with intent `a11y`, so the client runs them
  (`main.js runNav` → `a11y.handleText`; `voicebar.parseBarCommand` parses them). Typed, they already work locally.

## Copy requests (for the copy owner)

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
