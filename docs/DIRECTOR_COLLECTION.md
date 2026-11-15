# Director collection kit: real voices for every capability

The learned Director needs real kids' speech for every screen and every thing a kid can say there. That is the coverage
inventory, `director_model/coverage.json` (`docs/DIRECTOR_COVERAGE.md`).

There are two ways to get it, and both stay on the computer they are recorded on:

1. **A guided session** (`director_model/collect.py`): a 15-minute walk through prompts that cover the inventory.
2. **The in-app turn log** (Settings → "Help improve the voice guide", `docs/DIRECTOR_LOOP.md` §1): what the app hears
   in real use. It is passive, off by default, and holds text only.

Nobody uploads anything. A family or a tester hands a folder over by hand (USB stick, a shared drive they choose), or
deletes it.

## 1. Run a 15-minute session (a family or a tester)

```
pip install sounddevice                     # once (or have ffmpeg installed)
make director-collect OUT=~/Desktop/director_sessions
# = python3 director_model/collect.py --out ~/Desktop/director_sessions [--speaker child|adult] [--minutes 15]
```

1. **Who.** A kid with a parent or guardian next to them for the whole session, or an adult tester (`--speaker adult`).
   Use a quiet-ish room, with the laptop where the kid would normally play.
2. **Consent.** The script shows the consent text. The parent types `I AGREE`, or the session stops with nothing
   recorded. The parent can give an age band (6–8 / 9–12 / 13–17 / adult); it is optional. No names are asked for.
3. **The prompts.** About 75 prompts, each about 12 s with reading time, so about 15 minutes. Each prompt shows the
   screen it pretends to be on ("a NASA video is playing", "a hands-on Mission prep task", "the cabin") and one of four
   kinds:
   - **read:** read this line as you would say it to the app ("pause the video", "open the comm panel", "done!");
   - **free:** answer in your own words (a lesson question, or a question about the Moon);
   - **noisy:** be the room: talk to someone else, laugh, argue about whose turn it is, or read a line the way the
     app's own voice would say it (the echo);
   - **cooccur:** say the command while doing the hand gesture shown (a fist spinning the Moon).

   Press Enter to record (6–8 s), `s` to skip, `q` to stop. Skipping is always fine.
4. **What it chooses.** The plan puts the cells first that have no data yet and the features that are still landing
   (video, prep tasks, new lessons, OS-voice echo, gestures). It then walks the screens the way a kid moves through
   the app. `--plan` prints the plan without recording.
5. **Silent.** The script only records. It never plays anything through the speakers.

## 2. What a session folder holds

```
session-2026-11-14-<random tag>/
  consent.json      {"agreed": true, "date", "speaker": child|adult, "age_band", "parent_present", "uploaded": false, "text"}
  manifest.jsonl    per clip: clip, cell, screen + frame, kind, prompt, expected_text, gold {act, nav}, hot lists
  clips/000.wav     16 kHz mono PCM16, 6-8 s each
  README.txt        "delete this folder to delete the session"
```

No names, no device id, no clock time beyond the date. The tag is random.

## 3. Hand-over, import and deletion

- **Hand-over:** the family copies the folder to whoever runs the loop. That is the only way it leaves the machine.
- **Import:**
  ```
  cd model_server && uv run python ../director_model/collect_import.py decode --session <folder>   # the real Arc ear, with each clip's screen hot lists
  python3 director_model/collect_import.py items --session <folder>   # -> director_model/data/collected_turns.json (git-ignored)
  ```
  - The prompted labels are the gold, at confidence 1.0.
  - The ear's own words are what the Director replays.
  - Items split by session + cell: about 75 % train, 10 % val, 15 % `test_log`, which the gate checks.
- **Deletion:**
  - `python3 director_model/collect.py --delete <folder>` removes a session.
  - Delete `director_model/data/collected_turns.json` (and re-run `items` for the sessions you keep) when a family asks.
  - Sessions without an agreed `consent.json` are refused by the import.

## 4. Coverage target per cell

| | per cell | how to reach it |
|---|---|---|
| synthetic train (generator + coverage sweep) | ≥ 40 items | `make director-r8` (`--cov-sessions 1200`) |
| synthetic held-out | ≥ 8 items | `cls_coverage` (`--cov-heldout 10`) + the class sets |
| **real, collected** | **≥ 5 speakers, ≥ 10 clips** | about 366 cells × 10 clips ≈ 3,700 clips ≈ 50 sessions of 75 prompts (a session covers ~75 cells once; the plan rotates cells across sessions) |
| real, priority cells first | ≥ 3 speakers | the pending features, the navigation classes, the echo / room-talk negatives: ~120 cells ≈ 15 sessions |

A realistic first collection is **15 sessions** (5 families × 3, or testers), about 4 hours of total recording time.
That gives every priority cell 3+ real speakers, and gives the gate a real `test_log`.

## 5. The passive path (the in-app turn log)

`backend/app/turnlog.py`, opt-in. Round 8 adds two things the new capabilities need:

- `audio.kind`: what was playing (guide / capcom / crew / **video**), so the video's audio leaking into the mic
  becomes a labelled negative;
- `gesture`: a hand gesture within 2 s before the turn (voice + gesture co-occur).

`import_logs.py` now also keeps the router's navigation intent as the gold `nav` (the Director's nav head label) and
replays the gesture next to the turn. Everything else is unchanged: text only, redacted, off by default, deletable
from Settings.
