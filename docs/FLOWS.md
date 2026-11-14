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
| Model warming up | the ear or TTS is still loading on the model server | **gap:** not surfaced yet. The voice bar should say "Starting…" until `/api/health` reports the ear loaded. | — |
| Caption duplicates screen text | the spoken line equals the question, feedback or brief on screen | the caption folds out of the strip but stays in `#captionBar` for screen readers | `lesson_feedback` |
| Voice bar moved | dragging the grip, arrow keys on the grip, or "move the voice bar to the top right" | the bar snaps to one of 6 anchors, remembered per screen class, and the caption flips side | `vbar_moved` |
| Answer card | a question anywhere (not a lesson answer) | a glass card top-left (Library: top-right): title, answer, crew button | (live) |
| Visual alert | an alarm, with "Flash for alerts" on | an edge flash plus a toast | (live) |
| Settings | the gear, Alt+A, or "open settings" | a popover: Voice · Reading & captions · Display · Alerts · Help | `access` |
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

## Settings (planned; the owner confirms scope)

The top-bar gear opens Settings, which folds in today's Access panel. Every control in it works today.

| section | today | planned |
|---|---|---|
| **Voice** | speed (0.75–1.5×), describe what happens | 1 of 10 curated voices with preview, expressiveness |
| **Sound** | — | master volume, alarm volume |
| **Listening** | — | hands-free vs push-to-talk; background-voice filter (relaxed / normal / strict) |
| **Reading & captions** | captions, caption line length, text size, easy-read font | — |
| **Display** | high contrast, less motion, reset the voice bar position | theme, graphics quality |
| **Alerts** | flash, vibrate | — |
| **Help** | "No audio needed", the transcript, voice and keyboard commands, pick a place | — |
| **Cadet profiles** | — | several cadets on one device |

## Mission

The Mission UX agent fills this in: the site picker, the cabin and its views, the storm, Houston, end shift, the
debrief and fly-again.
