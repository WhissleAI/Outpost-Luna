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
| Check ride (mini cockpit) | lesson 8 | `ride` |
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

The Mission UX agent fills this in: the site picker, the cabin and its views, the storm, Houston, end shift, the
debrief and fly-again.
