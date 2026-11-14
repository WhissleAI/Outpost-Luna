# Flows and views

This is every view and state in Outpost Luna, with what triggers it, and the screenshot state that shoots it. That
state is the `--states` name in `frontend/tools/ux_shots.py`. Each round shoots and critiques all of them (UX_ROUNDS.md),
not only the happy path.

Owners:
- **Shell:** Flight School, the Library, Settings, and global states (feat/ux-v3).
- **Mission UX:** the Mission section (they add it).

## Global (every screen)

| view / state | trigger | what the kid sees | shot |
|---|---|---|---|
| First paint, loading | app opens | the night sky, "Loading the Moon…", and the voice bar | `loading` |
| Offline (backend down) | `/api/places` fails | "Can't reach Outpost Luna. Close the app and open it again." on the sky | `offline` |
| Mic off | before the first gesture, or after the mic switch is pressed | voice bar: mic-off glyph, "Mic off", "Type instead" | `map` |
| Listening | the mic is open | mic tinted, bars breathing, "Listening", plus a "Space  Hold to talk" hint | `lesson_tap` |
| Hearing | the kid is talking | strip outlined in the accent, "Hearing you", the words in the field | (live) |
| Thinking | a turn was sent | dots, "Thinking" | (live) |
| Speaking | CAPCOM, Houston, the story voice or the crew | bars, "Speaking", and the caption inside the strip with the word being spoken underlined | `home` |
| Heard | a used turn | "Heard: …" in the field for 2.6 s | `lesson_feedback` |
| Didn't catch that | the router's `notice` (a clearly directed turn it couldn't use) | a small chip in the state slot, silent | (live) |
| Mic denied | the browser refuses the mic | "Mic blocked" plus the reason in the field; typing works | `mic_denied` |
| Model warming up | `/api/health`: the ear or Steer TTS is not loaded yet | the voice bar shows "Starting voice…" (dots), or "Voice off · type" after 3 min; typing works | `warming` |
| Caption duplicates screen text | the spoken line equals the question, feedback or brief on screen | the caption folds out of the strip but stays in `#captionBar` for screen readers | `lesson_feedback` |
| Voice bar moved | dragging the grip, arrow keys on the grip, or "move the voice bar to the top right" | the bar snaps to one of 6 anchors, remembered per screen class, and the caption flips side | `vbar_moved` |
| Answer card | a question anywhere (not a lesson answer) | a glass card top-left (Library: top-right): title, answer, crew button | (live) |
| Visual alert | an alarm, with "Flash for alerts" on | an edge flash plus a toast | (live) |
| Settings | the gear, Alt+A, or "open settings" | a modal sheet over a scrim: Voice · Sound · Listening · Reading & captions · Display · Cadets · Help (+ Camera & gestures when available) | `access`, `settings_listen`, `settings_cadets`, `settings_display` |
| About | the info icon | a drawer: the brief, the data sources, the NASA credit | (todo shot) |

## Flight School

| view / state | trigger | shot |
|---|---|---|
| Home (first run) | no call sign stored | `home` |
| Change call sign | the call-sign chip on the map | (same view, with "Use it") |
| Moon map (new cadet) | call sign set, 0 patches | `map` |
| Moon map (returning) | some patches earned | `map_mid` |
| Moon map, pin selected | tap a pin: the globe flies there and the card shows that lesson (Replay / Start) | `pin_selected` |
| Moon map (qualified) | the check ride passed | (todo shot: `map_done`) |
| Loading Flight School | the course is loading | `loading` |
| Flight School offline | `/api/academy/course` fails | (todo shot) |
| Lesson: choice | | `lesson_choice` |
| Lesson: tap / intent (no panel answers; the globe is the answer surface) | | `lesson_tap` |
| Lesson: keywords (read back) | | `lesson_keywords` |
| Lesson: command | | `lesson_command` |
| Lesson: answered, Next | a correct answer | `lesson_feedback` |
| Lesson: try again + hint | 1–2 misses | (todo shot) |
| Vocab: listen / match / say / fill | Space words | `vocab_listen`, `vocab_match`, `vocab_say`, `vocab_fill` |
| Lesson brief open | the "Brief" button | (todo shot) |
| Patch earned | the last step of a lesson | `patch` |
| Check ride (mini cockpit) | the last stop after the 6 lessons; shown as "Check ride", never "Lesson 7" (patches count n/7) | `ride` |
| Check ride failed | the ride ends without passing | (todo shot) |
| Qualified | the ride passed: patch, then Take command | (todo shot) |
| Future step types: find / rotate / compare on the globe | the learning designer (feat/learning-v3) | the card stays small; a step may have no panel answers |

## Library (Moon explorer)

| view / state | trigger | shot |
|---|---|---|
| Library | the Library tab, or "library" | `library` |
| Place or hardware card | tap a place or a marker, or ask | (todo shot) |
| Crew audio playing | "Hear the crew" | (todo shot) |
| Tour | Tour | (todo shot) |
| Find it | Find it | (todo shot) |

## Settings (v1, built)

| section | controls |
|---|---|
| **Voice** | curated voice list with preview (`GET /api/voices`; hidden until the endpoint exists), speed 0.75–1.5×, expressiveness calm ↔ lively, describe what happens |
| **Sound** | volume (every voice and the crew audio), alarms volume, flash for alerts, vibrate |
| **Listening** | hands-free / hold to talk; ignore other voices: relaxed / normal / strict |
| **Camera & gestures** | from the gestures agent (`window.__outpost.settingsSections`); not listed until it registers |
| **Reading & captions** | captions, caption line length, text size, easy-read font |
| **Display** | theme (system / light / dark), high contrast, less motion, graphics (high / low), reset voice bar position |
| **Cadets** | profiles (call sign, patches; switch, add up to 6), level (Cadet 7–9 / Commander 10–12), reset my patches (two taps) |
| **Help** | "No audio needed", transcript, voice and keyboard commands, pick a place on the Moon |

Everything is stored on this device, per cadet profile. The session gets
`{t:"prefs", type:"prefs", voice, rate, expressiveness, filter, level, listen}`.

| state | shot |
|---|---|
| Switching cadet | the app reloads as the other cadet (their call sign, map and settings) |
| New cadet | the app reloads to home (call sign) |

## Mission

Owner: Mission UX (`feat/ux-mission`). Every state below has a screenshot per round in `docs/img/ux/mission/`
(`<round>-<state>-<w>x<h>-<theme>.jpg`), shot by `states.py` through the dev hooks on `window.__cabinTest`.
Every action works by voice (the router's nav/order), by tap, and by keyboard. Gestures (`feat/gestures`) are one more
way in, through `missionUI.intent(name, arg)`, and nothing needs the camera.

### Flow

picker → Take command → cabin (seat) ⇄ panels → End shift … → storm → shelter → Call Houston → Finish mission → debrief →
Fly again (cabin) / New site (picker)

### Views and states

| State | What the kid sees | Primary action | Voice | Hook |
|---|---|---|---|---|
| **picker** | The Moon full-screen with the five sites as pins on the south pole (labels in a column with leader lines); a glass panel: "Pick your outpost site", Sun / Earth in days of your 10-day mission, Ice, a "NASA candidate region" or "Studied by scientists" tag, and the yearly-average sun on the picked site's second line | Take command | "pick Malapert", "take command" | (default) |
| **picker-hover** | Hovering a row lights its pin, and the reverse | | | |
| **seat** | The 3D cabin from the commander's seat: the window (the terrain or globe through a real hole), three DUs under it, Habitat and Rover panels on the left, Radiation and Comm panels on the right, Caution & warning and End shift on the pedestal | End shift | "end shift" | `panel(null)` |
| **panel-power / habitat / rover / radiation / comm / pedestal** | The camera dollies in; the panel fills the space above the comm strip at about 1:1 pixels; Seat button and Esc go back | the panel's controls | "open the X panel", "back to my seat" (router: `panel_*`, `panel_back`) | `panel(id)` |
| **cabin-orbit / site / rover / earth** | The window's view switcher: the NASA globe, or the LOLA terrain at the site, behind the rover, or toward Earth | | "zoom out", "show me the rover", "show me Earth", "back to the outpost" | view buttons |
| **cabin-site-night / day** | The low-light camera at night (neutral grey), the lit terrain by day; the sky readout says Sun and Earth elevation | | | `sky(sun, earth)` |
| **storm-warning** | A caution strip on the glass ("Storm warning · Arrives in ~6 h · 70% sure", a confidence meter), STORM WATCH lamp, the Radiation panel lit | Shields 40 | "shields to 40" | `warning(lead, conf)` |
| **storm-active** | A warning strip on the glass ("Solar particle storm · Real event, date · NASA DONKI" link), Shelter / Shields 40, lamps + master alarm, the Radiation panel lit "Radiation · Alert"; a new warning brings the camera back to the seat | Shelter | "everyone to the shelter" | `storm(true)` |
| **storm-shelter** | The strip says "Crew sheltered"; its buttons go | | | `shelter(true)` |
| **comm-open / comm-closed** | A short info strip "Earth in view" / "Earth set"; Call Houston says "Earth in view" or "No signal" | Call Houston | "call Houston" | `comm(open)` |
| **low-power** | LOW POWER lamp, master alarm, the Displays lit "Displays · Check", the Power number in red, a caution strip | | "more power to …" | `power(pct)` |
| **rover-out** | Rover panel: the task pressed, "Ice run · back in 6 h"; ROVER OUT status lamp; a progress chip on the glass | | "send the rover for ice", "bring the rover home" | `rover(task, eta)` |
| **confirm** | CAPCOM's card with Yes / No (Commander) | Yes | "yes" / "no" | `confirm(text)` |
| **cadet-offer** | Cadet (Settings → level): the panel the offer is about opens, with the two choices as big buttons there | the first choice | the choice's words | `cadet(true)` + `offer()` |
| **end-shift-busy** | End shift disabled while the shift runs | | | `busy(true)` |
| **houston-calling** | Call Houston shows "Signal travelling" with a progress line for the real round trip | | | `calling()` |
| **debrief-survived / failed / paused** | A sheet over the Moon (follows the theme): headline, one line, Grade + Score (no grade while paused), the shift-by-shift chart with storm shifts shaded, up to three one-sentence takeaways (≤ 20 words) each with its source, "NASA data used" disclosure; a score breakdown when the sim sends one | Fly again | "fly again", "new site" | `debrief(outcome)` |
| **fly-again** | A new mission at the same site, shift 1 | End shift | | |
| **ride** | The Flight School check ride in the same cabin (`createCabin(root, {mode: "ride"})`): displays, Habitat and End shift only; `cue("heaters")` pulses one control at a time and opens its panel | the cued control | | `ride(target)` |

### Data slots (for `feat/learning-v3`)

`env.storm_warning` / `env.storm_forecast` (`lead_h`/`eta_h`, `confidence`/`probability`), `env.storm.ends_in_h`,
`score_breakdown` / `breakdown` on the debrief, `window_sun_days` / `window_earth_days` and `nasa_candidate` on sites.
Each renders when present and is invisible when absent.
