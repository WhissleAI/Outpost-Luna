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
