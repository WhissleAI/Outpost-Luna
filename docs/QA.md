# QA sweep: release candidate `fix/handsfree-rc` (57bd674)

Branch `qa/sweep`. Driven live with Playwright (headless Chromium, Metal GPU) against the backend on :8403 (model server :8200,
read-only) and Vite on :5303, at 1440×900 and 1280×720, light and dark, plus a static read of every module. FLOWS.md is
the checklist. Screenshots are in `docs/img/qa/` (only for issues).

**Severity:** P0 blocker · P1 major · P2 polish.
**Owner:** `fix/rc-polish`, `fix/guidance`, `fix/story-onboarding`, `feat/keys`, or `qa` (fixed on this branch unless the
status says otherwise).

## Summary

| | P0 | P1 | P2 | total |
|---|---|---|---|---|
| qa: fixed here | 0 | 10 | 35 | 45 |
| qa: open (logged, not fixed) | 0 | 0 | 8 | 8 |
| routed to `fix/rc-polish` | 1 | 2 | 4 | 7 |
| routed to `fix/story-onboarding` | 0 | 1 | 7 | 8 |
| routed to `fix/guidance` | 0 | 0 | 6 | 6 |
| routed to `feat/keys` | 0 | 0 | 0 | 0 |
| **total** | **1** | **13** | **60** | **74** |

The owner's six reports map to QA-01 (lesson card over Mission), and to the in-flight work: the voice bar shake and the
double speech (`fix/rc-polish`), chatter graded as misses (`fix/rc-polish`), "Trace it: Orientale, then up to Ohm"
(`fix/guidance`), and the cabin giving no direction (`fix/story-onboarding`). They are not repeated below.

## Measured

- **Memory over mode switches** (CDP `Performance.getMetrics` after a forced GC, 12 Library ⇄ Mission switches with a
  mission running): before, every switch leaked +534 DOM nodes, +45 listeners and +0.43 MB (8,116 nodes / 772 listeners
  after 12). After QA-30, it is flat (1,697 nodes / 233 listeners).
- **10-minute soak** (Library asks, tour, Far/Near side, Flight School, Settings, Mission and Find it, an action every 4 s):
  see the table at the end.
- **States checked live:** first launch, returning cadet, offline (backend killed), backend back (the ear reconnects),
  model warming (`/api/health` not ready), and the picker → cabin → window views → debrief (real backend).
- **Not testable headless:** the mic-denied path. Chromium's `--use-fake-ui-for-media-stream` grants every prompt, so it
  was read in code only (`micBlocked` shows "Mic blocked", the reason and "Type instead").

## Issues

| ID | Sev | Area | Repro | Expected | Actual | Shot | Owner | Status |
|---|---|---|---|---|---|---|---|---|
| QA-01 | P0 | Screens | Start any lesson, then press Library or Mission | The lesson card goes away | It stays on top, covering the picker. Cause: school.css `.apanel.is-lesson{display:flex}` beats `.apanel[hidden]{display:none}`. No global `[hidden]{display:none!important}` exists, so any `.x.is-y{display:…}` can leak the same way | `img/qa/qa-01-lesson-card-over-picker.jpg` | fix/rc-polish | routed |
| QA-02 | P2 | Story | Press Start lesson on lesson 1 | CAPCOM speaks as CAPCOM; no offer after the kid already started | "Day one. CAPCOM pulls up a map of the Moon." is narrator copy in the CAPCOM voice. "Ready, Pulsar?" is spoken after Start, and the brief starts without waiting | | fix/story-onboarding | fixed (fix/story-onboarding): beats are first person ("Let's start with a map of the Moon"), "Here we go, <cs>." instead of an unanswered question; a test bans third-person CAPCOM and stray questions |
| QA-03 | P2 | Flight School | The map | "Lesson n of 6", patches n/7, "Check ride" | "Lesson 1 of 7", "0/7" | | fix/guidance | routed |
| QA-04 | P1 | Voice bar | The ear socket closes (model server restarted or full) | Kid-safe words; the mic comes back | "Voice hiccup: local ear closed" is shown for good, the mic goes off, and nothing retries | `img/qa/qa-04-voice-hiccup-and-leak.jpg` | qa | fixed b56f7f7 |
| QA-05 | P1 | Voice bar | `/ws/listen` fails once (backend still starting) | The mic works once it can | `wsBroken` latches until a reload | | qa | fixed b56f7f7 |
| QA-06 | P1 | Settings: Less motion | Less motion on, Library, Far side or tap a place | No flying or spinning | The globe flies 1.3 s, the ring pulses, and an OS change while open is ignored | | qa | fixed 2a6b494 |
| QA-07 | P1 | Settings: Help | Alt+P, or Help → Pick a place in Mission | The place picker, then the place is shown | Alt+P opens Voice (the picker is in Help); in Mission, "Go there" does nothing | | qa | fixed 2a6b494 |
| QA-08 | P2 | Library | Ask an ambiguous question, tap option 1 | The globe stays on the choice | The preview timers fly to options 2 and 3 afterwards, even after a mode switch | | qa | fixed 2a6b494 |
| QA-09 | P2 | Library | Places off → Flight School → Library | Places stay off and the button says so | The dots come back but the button reads off; the next press inverts it | | qa | fixed 2a6b494 |
| QA-10 | P2 | Library | Tour, then the card's × | The tour and its voice stop | The tour carries on and the card comes back | | qa | fixed 2a6b494 |
| QA-11 | P2 | Settings: Sound | Volume 20%, preview a voice, or the browser-voice fallback; Alarms 0% | Volume applies everywhere; Alarms applies only to alarms | The preview and the fallback play at 100%; Alarms 0% muted every chime (place taps, tour) | | qa | fixed 2a6b494, 1353ce7 |
| QA-12 | P2 | Library: Tour | Press Tour | A short tour | 36 stops (about 4 min), "36 stops!", "Next ›" | | qa | fixed 2a6b494 (8 firsts, "Next stop") |
| QA-13 | P2 | Library: card | "Where did Apollo 11 land?" | Each fact once | The status line appears in the meta row and again as the answer. The claim chip repeats all four sources joined into one truncated string | `img/qa/qa-13-card-duplicates.jpg` | qa | fixed 2a6b494 |
| QA-14 | P2 | Copy | The Library offline ask, an unnamed spot, Find it, the nudge | COPY.md budgets, no hype, labels that match | "Is the backend running?", "Try a darker or brighter patch!", Find-it clues of 15–20 words with "!" and "★", "Try a mission?" opening Find it, "Mission 1 of 5" in Find it | | qa | fixed 2a6b494 |
| QA-15 | P2 | Library: highlights | Tap a place whose fact names a space word | The marks stay; chips belong to this card | The marks vanish when "Hear the crew" arrives; stale "In this answer" chips stay on the next card; ⌖/? glyphs | | qa | fixed 2a6b494 |
| QA-16 | P2 | Settings: Voice | Open Settings | The default is labelled on the default | "Beacon … the default voice", but Aurora (voice_1085) is the default. The descriptions are cut off ("…keeps movi…") | `img/qa/qa-16-voice-default-truncated.jpg` | qa | fixed 1353ce7, 9edaefa |
| QA-17 | P2 | Settings: Cadets | Cadet A turns gestures on; switch to B. Make 6 cadets | Each cadet keeps their own; the cap is explained | B gets A's camera, hand and mission tier. "Add a cadet" silently does nothing at 6. "of 8 patches" | | qa | fixed 1353ce7 |
| QA-18 | P2 | Settings: a11y | Say "where am I?" | The tab names | "the Academy", "Mission control" | | qa | fixed 2a6b494 |
| QA-19 | P1 | Screens | Click Mission, then Flight School before the sites load | The picker never appears outside Mission | `enter()` awaits the client and then draws the picker, pins and fly-in over Flight School (mission/ui.js:105) | | fix/rc-polish | fixed 910fb4b |
| QA-20 | P1 | Screens / audio | Call Houston (or end the last shift), then switch to Library within 2.6 s | Nothing from Mission follows you | The CAPCOM card pops up over Library and Houston speaks. `houston()`, `run()` and `endShift()` don't re-check the screen after their await. `showDebrief()` is guarded on this branch | | fix/rc-polish | fixed 910fb4b |
| QA-21 | P2 | Audio | End the last shift | One "Mission over." | "Mission over." is spoken twice: the order reply, then the debrief line | | fix/rc-polish | fixed 910fb4b |
| QA-22 | P2 | Voice bar | In the cabin | The voice state is readable | "Listening"/"Speaking" is dark green on dark (well under AA) in the cabin dock | `img/qa/qa-22-cabin-voicebar-contrast.jpg` | fix/rc-polish | fixed 910fb4b |
| QA-23 | P1 | Cabin | A low-power or storm alert while in the seat view | The alert strip and the HUD title don't collide | The strip text is drawn over "Day 1 · Shift 1" (text on text, both unreadable) | | fix/story-onboarding | fixed (fix/story-onboarding): the clock/views row, sky and rover chip move down by the strip's measured height (`--alert-h`) |
| QA-24 | P2 | Cabin / data | Shackleton Rim or Connecting Ridge | A sunlit site reads as sunlit | "Sun −1.1°" while the site counts as 100% lit (ACCURACY_AUDIT #2). Show the Sun over the ridge line, or Sun up/down | | fix/story-onboarding | fixed (fix/story-onboarding): the sky readout says Sun up/down from the sim's `in_sun`; the elevation is in the tooltip |
| QA-25 | P2 | Cabin / data | The power page's load list, the radiation page, the storm strip "Shields 40", the check-ride "Shields up" | Pretend tech is tagged wherever it is shown | Only the shields knob and the Greenhouse rows carry the tag | | fix/story-onboarding | fixed (fix/story-onboarding): tag on the power list (Shields, Greenhouse), the RAD page Shields row, the storm strip's shields button and the ride's Shields order; tags stay visible at the seat |
| QA-26 | P2 | Cabin | Finish mission → "Fly again" or "yes" | A paused mission isn't wiped by accident | The paused debrief offers Fly again, which restarts from shift 1 with no confirm. "Finish mission" doesn't finish anything | | fix/story-onboarding | fixed (fix/story-onboarding): the paused debrief's primary is Resume mission; Fly again / Pick a new site / "fly again" ask "Start over?" first (offer `confirm_wipe`); "Finish mission" is now "See debrief" |
| QA-27 | P2 | Cabin / data | A storm with few particles (sep:false) | "Storm at Earth" | The cabin titles every storm "Solar particle storm" while CAPCOM says "few particles here" | | fix/story-onboarding | fixed (fix/story-onboarding): sep:false storms are "Storm at Earth · Few particles here" (caution, no shelter buttons); the Now strip says keep working |
| QA-28 | P2 | Course data | Lesson "Talk to Houston" | One number per fact | course.json says Malapert's Earth was up "9 of 10 days"; the picker and debrief say 9.5 | | fix/guidance | routed |
| QA-29 | P1 | Errors | Start the app with the backend down, then bring it up | The app recovers on its own | "Close the app and open it again." and a dead end (no retry) | `img/qa/qa-29-offline-dead-end.jpg` | qa | fixed 2a6b494 (retries every 3 s) |
| QA-30 | P1 | Performance | Switch Library ⇄ Mission 12× with a mission running | Flat memory | +534 nodes, +45 listeners, +0.43 MB per switch. The Escape listener on `#mCabin` kept every old cockpit (renderer, scene, PMREM) alive; dispose didn't free the GPU | | qa | fixed d704f9b |
| QA-31 | P1 | Performance | Start a mission, restart the backend, go to Library | No traffic while away | The telemetry socket reconnects every second forever, and stays subscribed in other modes | | qa | fixed d704f9b |
| QA-32 | P1 | Performance | Leave the cabin, or end the check ride, while the terrain tiles load | Nothing renders after hide | The render loop starts on a hidden or disposed terrain view and never stops | | qa | fixed d704f9b |
| QA-33 | P1 | Debrief | The debrief fetch is slow or fails | A loading line, then Retry | A blank screen, then "Grade ?" shown and spoken "Grade ?, N points" | | qa | fixed a95c6a1 |
| QA-34 | P2 | Debrief | Telemetry and the order reply both report "over" | One debrief | It re-fetches, re-renders and re-speaks "Mission over… Fly again?" | | qa | fixed a95c6a1 |
| QA-35 | P2 | Debrief chart | A 12–24 h storm | Every storm shift shaded | Only the shift it started in, centred half a shift late. The backend now sends `shifts[].storm_active` | | qa | fixed a95c6a1 |
| QA-36 | P2 | Debrief | A storm takeaway | A readable source | "DONKI 2017-09-04T23" (the title cut at the time's colon); now "NASA DONKI, 2024-10-09" | | qa | fixed a95c6a1 |
| QA-37 | P2 | Debrief | Any real mission | The "Next time" tip or a Flight School callback gets a slot | Data lessons always filled all three slots | | qa | fixed a95c6a1 |
| QA-38 | P2 | Debrief / copy | Fail a mission | No praise for a failure | "Mission over. Nice flying, Pulsar. Grade F…" | | qa | fixed a95c6a1 |
| QA-39 | P2 | Debrief chart | Sample mode | Day 1 first | "Day 0" and "Day 0 · shift 0" | | qa | fixed a95c6a1 |
| QA-40 | P2 | Debrief chart | Any debrief; or all lines ending near 0 | The dose axis is explained; labels stay on the chart | "Dose" on a 0–100% axis with no "% of limit". The third label could fall below the chart | | qa | fixed a95c6a1 |
| QA-41 | P2 | Debrief / data | Open "NASA data used" | An honest heading | The list includes China's Chang'e 4 and science papers. Now "Data used" | | qa | fixed a95c6a1 |
| QA-42 | P2 | Picker / data | The picker's source line | The right source | "days in view" linked the IAU Gazetteer (the site's first source). The numbers are JPL Horizons | | qa | fixed a95c6a1 |
| QA-43 | P2 | Picker / data | Shackleton Rim, Ice column | The truth | "No", while sites.json says the ice is a 6 h drive. Now "6 h away" | | qa | fixed a95c6a1 |
| QA-44 | P2 | Picker / data | Shackleton Floor | Why 0 sun still works; pretend tech tagged | Sun 0/10 with no word of the pretend rim cable. Now "Power by cable from the rim · Pretend tech" | | qa | fixed a95c6a1 |
| QA-45 | P2 | Data | A storm hits with Houston in view | No Earth storm scale at the Moon; ≤ 20 words | "It's the Real solar particle storm, 2024-05-09 (huge auroras on Earth, G5)" (21 words). The debrief says "a real G4 magnetic storm" | | qa | fixed 9edaefa |
| QA-46 | P2 | Data | Sample mode storms | Real DONKI events | The 2003 Halloween storms (before DONKI) and 2024-05-10 (the data says 05-09) | | qa | fixed 9edaefa |
| QA-47 | P2 | Data | Tap Aristarchus Plateau | Accurate | "The brightest crater…" (it's a plateau) | | qa | fixed 9edaefa |
| QA-48 | P2 | Data | Surveyor 1 | Accurate | "one of America's first safe Moon landings". Now "America's first soft landing there" | | qa | fixed 9edaefa |
| QA-49 | P2 | About | Open About | Short, scannable; no over-claim | One 170-word paragraph, with "Every fact shows its source" | | qa | fixed 42821f3 |
| QA-50 | P2 | Library | Idle 8 s in Library, then switch modes while the moments fetch runs | The nudge stays in the Library | "Hear the crew at …?" could appear in Flight School or Mission | | qa | fixed 2a6b494 |
| QA-51 | P2 | Library | Press Library while in the Library | Goes back (as the code comment says) | Re-flies to Orientale and stops speech | | qa | fixed 2a6b494 |
| QA-52 | P2 | Copy | grep | No emoji or stand-in glyphs | ★ ⌖ ⚠ ▶ › in UI strings. Now guarded by `frontend/tests/qa_copy.test.js` | | qa | fixed 2a6b494, 1353ce7 |
| QA-53 | P2 | Voice bar | Model warming | No Space hint until voice works | "Space · Hold to talk" next to "Starting voice…" | | qa | fixed 42821f3 |
| QA-54 | P1 | Picker | Double-click Take command, or click while saying "take command" | One mission | Two missions start, the greeting is spoken twice and the cabin is built twice. No error if the server fails | | qa | fixed 42821f3 |
| QA-55 | P2 | Picker | Hover a site row | Its pin lights (FLOWS picker-hover) | Only the label pill lights; `.mx-dot.is-hot` never applies | | qa | fixed 42821f3 |
| QA-56 | P2 | Settings: Text size | Text size 150% | Library surfaces scale too | Find it, the Library toolbar, the globe label and About stay at 100% | | qa | fixed 42821f3 |
| QA-57 | P2 | Performance | Model server never ready | Back off | `/api/health` polled every 2 s forever after "Voice off" | | qa | fixed 42821f3 |
| QA-58 | P2 | Flight School map | 1440 wide | The lesson blurb fits | "Near side, far side, and Shackleton crater at the pol…" is cut off | `img/qa/qa-58-map-blurb-truncated.jpg` | fix/guidance | routed |
| QA-59 | P2 | Course data | The radiation lesson | Units on every number | "inside the ISS (523)", no unit. The debrief side (sim.py) is fixed here | | fix/guidance | routed (course.json) |
| QA-60 | P2 | Places data | Ask "Mare Orientale" | The name matches the size | "Mare Orientale … 930 km": 930 km is the basin, the mare is about 300 km. The lessons use the name | | fix/guidance | routed |
| QA-61 | P2 | Picker perf | Leave the picker open | Idle CPU | The pins' SVG is rebuilt with 10 `querySelector` calls every frame, even with a still globe | | qa | open |
| QA-62 | P2 | Touch targets | Library toolbar (34 px), hardware markers (26 px), debrief × (36 px), pin labels (28 px) | ≥ 44 px (DESIGN_SYSTEM) | Below | | qa | open |
| QA-63 | P2 | Library | "Hear the crew" when `/api/clips` fails | Feedback | Nothing happens | | qa | open |
| QA-64 | P2 | Mission data | A storm warning | Particles arrive in minutes to hours (COPY.md) | "Particle storm likely within 6 hours" (Commander) / 12 h (Cadet), a fixed lead from `WARN_LEAD_H`; the sensor "a few hours' warning" vs "up to 1 hour" in course.json | | qa | fixed (fix/story-onboarding), product call: lead times kept (Cadet 12 h, Commander 6 h); copy says "Houston: particles likely within hours. Forecast: N hours (game)." and the strip "Forecast ~N h (game)" |
| QA-65 | P2 | Debrief | A low-power mission | A real takeaway | "Battery's low." (the callback line) fills a takeaway slot | | qa | open |
| QA-66 | P2 | Cabin | Return to a mission the server already finished | The debrief | The stale Day 1 HUD (only reachable when the sim moves while away, e.g. via the API) | | qa | open (edge) |
| QA-67 | P2 | Data | "NASA Provides Update on Artemis III Moon Landing Regions" as a link title | — | It's NASA's real headline, not our claim; left as is | | qa | open (note) |
| QA-68 | P2 | Mission audio | Return to Mission while a red edge flash is on | The flash ends with its alert | The visual-alert flash and banner can outlive the alert after a mode switch | | fix/rc-polish | fixed 910fb4b |
| QA-69 | P2 | Story | Debrief "New site" | A verb first (COPY.md buttons) | "New site"; the storm strip's "Shields 40" also has no verb | | fix/story-onboarding | fixed (fix/story-onboarding): "Pick a new site", "Set shields to 40" (strip and CAPCOM card), "Shelter the crew", "Resume mission", "See debrief" |
| QA-70 | P2 | Library | 1280×720 Library with the voice bar | No overlap | The NASA credit sits under the voice bar at 800 px wide (not at 1280/1440) | | qa | open (below the supported size) |
| QA-71 | P2 | Flight School | Know your Moon: tap a place | One voice | The same fact is played twice in two voices (owner report) | | fix/rc-polish | fixed (success line + "after" crew clip; floor dedupe) |
| QA-72 | P2 | Flight School | "Trace it: Orientale, then up to Ohm" | A newcomer can do it | Impossible without knowing where Ohm is (owner report) | | fix/guidance | routed (owner report) |
| QA-73 | P2 | Cabin | First mission | Direction | The cabin gives no direction (owner report) | | fix/story-onboarding | fixed (fix/story-onboarding): the first-mission cabin tour, the Now strip, "what do I do?" (docs/STORY.md) |
| QA-74 | P2 | Errors | The session socket fails to connect (backend busy) | Falls back to /api/ask quietly | Forwarding floor events to the null session threw "Cannot read properties of null (reading 'ui' / 'playback')" on every playback event (seen in ux_flow) | | qa | fixed 21ce6a3 |

## Checked and fine

- Captions on/off, caption line length, speed (guide, crew `playbackRate`, re-sent prefs), listen mode, the filter, theme
  (the pref and the top-bar button stay in sync), graphics quality (globe and cabin follow it live), high-contrast tokens.
- Leaving a screen stops its speech: Library tour → Mission, story → card ×, mission telemetry while in Flight School
  (after QA-31).
- The cabin's window views (Orbit / Site / Rover / Earth) switch and come back after a mode switch.
- The radio delay (1.3 s each way), the site window percentages, Malapert's 157 h dark spell, the dose limits and the
  credit line match ACCURACY_AUDIT and the data. No "Artemis III lands" anywhere in story.js or course.json.

## 10-minute soak

An action every 4 s for 10 minutes (Library asks, tour, Far/Near side, card ×, Flight School, Settings, Mission, Find it),
sampled after a forced GC (CDP `Performance.getMetrics`). There's no growth: the heap settles at about 14 MB, nodes swing
with the screen shown, and listeners stay flat. Main-thread CPU is about 7.5 s a minute (the globe, the cabin and the
picker's per-frame pin redraw, QA-61). No console errors.

| t (s) | JS heap (MB) | DOM nodes | listeners | main-thread CPU (s, cumulative) |
|---|---|---|---|---|
| 0 | 12.4 | 1,080 | 136 | 1.4 |
| 66 | 13.9 | 1,485 | 190 | 10.9 |
| 190 | 14.1 | 1,510 | 192 | 26.1 |
| 312 | 14.0 | 1,467 | 191 | 41.4 |
| 435 | 14.1 | 1,569 | 200 | 55.6 |
| 557 | 14.4 | 1,512 | 194 | 71.3 |

## Verification

- `node --test` (frontend): 72 pass. The new `tests/qa_copy.test.js` checks for emoji/glyphs in every UI source file,
  the Find-it budgets and developer text in errors.
- `pytest` (backend): 624 pass, 2 skipped. The new `tests/test_qa_mission.py` covers storm_active and the picker fields.
- Live `tools/handsfree_run.py --base http://127.0.0.1:8403 --models http://127.0.0.1:8200`: **PASS** (replies to
  noise: 0, qualified: True).
- `frontend/tools/ux_flow.py --base http://localhost:5303`: 22 checks, 0 console errors (after QA-74).
- `npm run build`: builds (dist deleted afterwards).
