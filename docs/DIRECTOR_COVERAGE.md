# Director coverage: every capability × every flow, and the plan for round 8

The learned Director runs on every turn, on every screen. It can only be as good as its data, and that data has to
cover what the app can do. This doc is the inventory of what the app can do, how much data each part has today, and
how round 8 fills the rest.

- **The inventory:** `director_model/coverage.json` (machine-readable), generated from the code by
  `director_model/coverage.py`.
- **Rebuild it:** `make director-coverage`.
- **Its test:** `backend/tests/test_director_coverage.py`. It fails when a router intent, a course step type or a
  screen appears without a probe, a cell and a generator.

## 1. What a cell is

A cell is **(screen or state) × (intent or act)**, built from the code:

| source | cells |
|---|---|
| `features.SCREENS` (map, callsign, lesson, lesson_done, ride, patch, brief, cabin, debrief, library) + the screens the branches add (video, prep) | one row per screen |
| every `turn_router` intent (`NAV`, panels, offers, site / task picks, the live clock: skip_event, time_pause / resume / warp) | `nav:<intent>`, on every screen where `nav_intent()` reads its probe phrase as that intent |
| every `accept.type` in `backend/data/academy/course.json` | `step:<type>:answer` and `step:<type>:wrong`, on lesson and ride |
| `features.CMD_TYPES` (+ confirm / cancel) | `cmd:<type>` in the cabin |
| questions, PII | `question` on every screen; `guard:pii` in the cabin and the library |
| silence | `ignore:chatter`, `ignore:echo`, `ignore:roomtalk`, `ignore:echo_os_voice` on every screen |
| **pending** (unmerged branches) | `video` / `prep` screens and their intents, `step:video`, `ignore:video_audio`, the briefing-video / learn-more / explorer-lesson offers, `gesture+voice` |

**Counts.** A cell's count is the number of generator items that exercise it, at the loop's sizes (train 2,400 + val
200 sessions; test 200; every class set at 160 turns). `coverage.item_cell()` maps each item to its cell.

**Targets.** A cell is covered at ≥ 40 synthetic train items and ≥ 8 held-out items. The real-data targets are in
`docs/DIRECTOR_COLLECTION.md` §4.

## 2. Coverage today and with the round-8 generator

| kind | cells | covered today (round-7 generator) | covered by the round-8 generator | pending a branch |
|---|---|---|---|---|
| navigate | 242 | 18 | 242 | 19 |
| lesson answers | 53 | 19 | 53 | 1 |
| silence (chatter / echo / room talk / OS-voice echo / video audio) | 47 | 18 | 47 | 17 |
| questions | 12 | 3 | 12 | 2 |
| orders (cabin commands) | 11 | 9 | 10 | 0 |
| voice + gesture | 4 | 2 | 4 | 4 |
| privacy guard | 2 | 2 | 2 | 0 |
| **all** | **371** | **71** | **370** | **43** |

- **Items:** synthetic train items go from 26,497 to 40,881, and held-out items from 4,599 to 7,597.
- **The one gap left** is `cabin|cmd:power_save` (night mode): 32 train items vs a target of 40. It is a new command
  type from gameplay-r2. Round 8 adds it to `features.CMD_TYPES` (appended), which also fixes a crash: the generator
  failed on `nlu_none` for any session with a power-save order.
- **Where today's data was:** the round-7 generator covered the flows its scripts visit (lesson answers on their own
  steps, cabin orders, Moon questions in the library, the round-6 / 7 class sets). Most of the 224 navigation gaps are
  app-wide intents ("what do I do", "go to the map", "say that again", "settings", the voice bar) that are valid on
  every screen but were only ever generated on two or three.

## 3. The round-8 generator (`director_model/pools_r8.py`, `gen_sessions.py`)

### The coverage sweep

`--cov-sessions 1200` adds train sessions that cycle round-robin through every gap cell, so each one gets its share
(`gen_sessions.coverage_script`, `pools_r8.cell_item`). Held-out phrases stay apart (`pools.cls_split`):

- `cls_coverage`: 10 per merged gap cell. It gates.
- `cls_coverage_pending`: 10 per pending cell. It reports only.

### The new classes

Each is a held-out set of 160 turns, plus a share of the hands-free train sessions (`--r8-p 0.35`).

| set | what | gold | branch |
|---|---|---|---|
| `cls_video_ctrl` | while a video plays: "pause it", "skip the video", "keep going", "watch" | navigate (`video_*`) | feat/media-v1 |
| `cls_video_echo` | the video's own audio in the mic: real NASA crew narration (4,679 transcript segments from `backend/data/index/clips.json`; the real-ear path renders the NASA audio itself), and music | ignore | feat/media-v1 |
| `cls_prep` | hands-on Mission prep: "done!", "skip this one", "hold on", "I need help", "where's the flour" | navigate (`prep_*`) / answer | feat/learning-v1 |
| `cls_prep_roomtalk` | kids away from the screen: laughter, flour, cookies, sibling arguments | ignore | feat/learning-v1 |
| `cls_voice_echo_os` | the app's own lines (the voice pack's 889 `lines.json` lines, plus "Houston says: …" relayed by CAPCOM after a beep), heard back in the OS voices or the Nora pack | ignore | feat/os-voices + feat/voice-pack |
| `cls_gesture_cooccur` | "go to Shackleton" while a fist spins the Moon (a `gesture` UI event at the turn) | the voice intent | feat/gestures-v2 |
| `cls_lesson_new` | answers to Phases and eclipses (core track), the explorer lessons Moon gravity and dust, and Apollo (unlocked after missions 1 and 2), and the `video` step | answer | feat/learning-v1 |
| `cls_offers_new` | take / decline: the first-mission briefing video, debrief "learn more", an explorer lesson unlocked | navigate | feat/learning-v1 |

### Real-ear audio for the new negatives (`director_model/render_r8.py`)

- **`os_voice`:** macOS `say -o` in the voices the app picks from, or the Nora pack clip of the line.
- **`file`:** the NASA recording segment.
- **`music`:** synthetic music.
- **The chain.** Each one goes through a laptop speaker → mic chain (high-pass, small-room reverb, −10 to −25 dB, room
  noise), then into the real Arc ear with the screen's hot lists.
- **Silent.** Nothing is ever played. Temporary files are deleted at once.
- **`say_kid`:** a pitched-up OS voice stands in for the kid voices once Steer TTS is gone (feat/os-voices removes
  `steertts_edge`).
- **Groups:** `app_os` and `video` in the real-ear cache.

### Hot lists

The `video` and `prep` screens get their own strong lists: the video controls; and done / skip / wait / help plus
flour, flashlight, eclipse, feather, hammer, regolith, ejecta… The new lessons' words join the course vocabulary
automatically once `course.json` has them.

### Features

Appended after the round-7 block: F 236 → 239.

- `nlu_other`: a command type newer than round 5.
- `gesture_now`: a gesture within 2 s.
- `video_on`: a video is playing.

`NAV_INTENTS` appends the clock and task-card intents, `next`, `video_*` and `prep_*`. Older weights read their prefix.

### The turn log

The turn log now records what was playing (`audio.kind`, e.g. `video`) and a gesture within 2 s. The import keeps the
router's navigation intent as the gold `nav` (`docs/DIRECTOR_COLLECTION.md` §5).

## 4. Dry run on today's main

These numbers are synthetic and come from the fitted error model; there are no real-ear decodes yet. The rules and the
shipped r4 s weights were run on the new sets. This is the gap the branches and round 8 must close.

| set | turns | rules: act acc / wrong actions | shipped r4 s `on` | what it says |
|---|---|---|---|---|
| cls_video_ctrl | 158 | 0.000 / 18 | 0.000 / 18 | no video screen in the router yet: "stop" reads as declining the frame's offer (the 18 wrong actions) |
| cls_prep | 159 | 0.000 / 33 | 0.000 / 33 | no prep screen yet: "done" / "skip" go nowhere, "say it again" becomes repeat (33 wrong intents) |
| cls_lesson_new | 157 | 0.274 / 0 | 0.274 / 0 | lessons not in course.json yet |
| cls_video_echo | 160 | 0.762 / 3 | 0.775 / 3 | the hard mute while a video plays catches most narration; what leaks through can become an ORDER ("it's like a super deep crater" → rover explore) |
| cls_prep_roomtalk | 159 | 0.730 / 7 | 0.805 / 7 | room talk becomes orders ("it looks like a crater" → rover explore) |
| cls_voice_echo_os | 160 | 0.844 / 6 | 0.869 / 6 | partial lines in another voice get through as orders ("…turn on night mode" → power save) |
| cls_gesture_cooccur | 158 | 0.924 / 1 | 0.924 / 1 | voice + gesture already works (the router ignores the gesture event) |
| cls_offers_new | 156 | 0.846 / 0 | 0.846 / 0 | yes / no take the new offers generically |
| cls_coverage (merged cells, 4 per cell) | 1046 | 0.846 / 27 | 0.850 / 27 | navigation 726 / 803 cells right; the shipped model has no navigate act (raw 0 / 803) |

## 5. Round 8: the plan and the gate

`make director-r8` (`director_model/run_r8.sh`) runs end to end once the branches land. It uses one model server on
:8298 and `PROCS=3` decoders.

1. **Inventory.** `coverage.py` writes `coverage.json` (what is missing today).
2. **Real ear.**
   - `real_ear.py jobs` covers the kid turns (train 900 / val 300 / test 500 + every class), the app's lines in the OS
     voices / the Nora pack (`app_os`), and the video audio (`video`).
   - It decodes them with the hot lists. Set `VOICE_PACK_DIR` to the pack until feat/voice-pack is merged.
3. **Generate.**
   - Train: 2,400 sessions (`--hf-p 0.3 --r8-p 0.35`) plus the coverage sweep (`--cov-sessions 1200`), in 4 shards.
   - Val 200, every test set, every `cls_*` including round 8's, `cls_coverage` (10 / cell), `cls_coverage_pending`,
     and `test_log`. Collected sessions join `test_log` through `collect_import.py`.
4. **Train.** m, and xl with the cost-sensitive command loss (`--fp-exec 0.5`, round 7's xl failures were command
   fills).
5. **Evaluate.** Both candidates and the shipped r4 s, on the same sets.
6. **Gate** (`loop.py gate`, unchanged criteria). New: `--pending`. Class sets whose feature is not merged are reported
   but do not gate (the rules cannot act on a screen the app does not have yet).
   - Default pending: the eight round-8 sets + `cls_coverage_pending`.
   - Once the branches are merged, run with `PENDING=` (empty), so every set gates. That includes `cls_video_echo`,
     `cls_prep_roomtalk`, `cls_voice_echo_os`, `cls_gesture_cooccur` and the new ones: wrong actions ≤ rules, act
     accuracy ≥ rules, and no regression vs the shipped weights.
7. **No export.** A PASS is exported as a separate, deliberate step. `DIRECTOR_MODEL` stays `shadow` until the owner
   flips it.

**What needs the branches merged first:**

- **feat/media-v1:** the `video` screen in the client's screen frame; video playback reported to the session
  (`playback` kind `video`); the router's video intents.
- **feat/learning-v1:** the `prep` screen and its done / skip / wait / help intents; the new lessons and the `video`
  step in `course.json`; the briefing / learn-more / explorer-lesson offers in the frame.
- **feat/os-voices + feat/voice-pack:** `lines.json` and the clips in `backend/data/voice_pack` (the echo text and
  audio). Steer TTS is gone, so the kid voices move to `render_r8.say_kid` automatically.
- **feat/gestures-v2:** the client posting `{"t":"ui","event":"gesture","id":<name>}` to the session.

**After each merge:**

1. Add the screen / intents to `features.SCREENS` / the router.
2. Run `make director-coverage`, so the test passes again.
3. Drop the set from `PENDING`.

## 6. On integ/v1 (all round-8 branches merged)

- **Router.** The `video` screen (media-v1, `turn_router.VIDEO_CMDS`) and the new `prep` screen
  (`turn_router.PREP_CMDS`: `prep_done` / `prep_skip` / `prep_wait` / `prep_help`; a real question still answers;
  anything else is ignored). The Academy sends `{"screen": "prep", "offer": "prep_task"}` while a Mission prep card is
  up and runs the four intents.
- **Gestures.** The client posts `{"t": "ui", "event": "gesture", "id": <classifier event>}` for each discrete gesture
  (`gesture/ui.js` `onGesture`, wired in `main.js`), so `session.last_gesture` and the `gesture_now` feature are live.
- **Features.** `features.SCREENS` is unchanged: `video` and `prep` have no one-hot slot (the shipped weights keep
  their layout); `video_on`, `gesture_now` and the `video_*` / `prep_*` nav intents carry them.
- **Inventory.** `coverage.py` lists `video` and `prep` as real router screens (`ROUTER_SCREENS`), not pending;
  `video_watch` stays pending (on a lesson's video step "watch" is the step's answer, not a router intent). The
  class-set pendings (`pools_r8.PENDING`, echo / gesture cells) are unchanged: they gate on real-ear data, not on a merge.
