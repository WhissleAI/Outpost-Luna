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

`docs/img/ux/r1-*.jpg`: home, map, map_mid, lesson_choice, lesson_tap, lesson_feedback, vocab_listen, vocab_say, patch.

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
