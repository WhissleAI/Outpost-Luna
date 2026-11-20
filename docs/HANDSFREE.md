# Hands-free: one router for every turn

The mic is always open. Most of what it hears is not for us: room chatter, hums, filler, and the app's own voice coming
back through the speakers. The app used to answer all of it, which caused the packaged-app loop. The app spoke, the ear
heard it, and the Guide fallback answered: "I don't know that one yet. Try: show me the giant bullseye…". That example
command was then heard and answered again.

Now every turn goes through one router, `backend/app/turn_router.py`, on the session (`WS /ws/session`), in every screen
of the app. This covers spoken turns from the Arc ear (relayed by `/ws/listen`, with the session id from the client's
context frame), the client's own copy of the same turn (deduplicated), and typed turns.

```
turn ──► route(text, screen ctx) ──► ignore | navigate | answer | order | question
```

## Routing table

| outcome | when | what happens |
|---|---|---|
| **ignore** | empty; filler or non-lexical ("oh", "um", "mm-mm", "uh-huh"); echo of our own voice; heard while we speak (or < 600 ms after) and not barge-in-worthy; Arc `device_directed` < 0.5; one word that is not an intent; a tap step's unrelated words; a long ramble in a lesson; [0.4.1] an answer to a guess or a choice (predict / choice step, a Now-card choice) with `device_directed` under `dd_strong` (0.7 at Normal): reason `crew_talk`, the bar shows "Crew talk", plus a "Heard “B” · Use it" chip when the words named one option exactly (`pick`) | silence. Our own speech is never cancelled. The mic chip shows "Didn't catch that" only when the turn was clearly device-directed (`notice`). |
| **navigate** | start, next, go back, patch map, lesson N or a title ("space words"), go to mission, take command, pick \<site>, debrief, fly again, another site, academy, library, zoom out / show the rover / back to the outpost, settings, slower / faster, say that again, the a11y commands (where am I, press X, option 2); the voice bar ("move the voice bar to the top right", "reset the voice bar": intent `a11y`, `text` = the canonical command `voicebar.js` parses), on every screen; in the cabin, the 3D panels ("open the comm / power / habitat panel", "go to the hab", "open the rover / radiation panel" → `panel_comm`, `panel_power`, `panel_habitat`, `panel_rover`, `panel_radiation`; "back", "back to my seat", "close the panel", "seat" → `panel_back`). Panel phrases never reach the mission NLU ("open the comm panel" once turned the radio off); without the word "panel" only open / go to / take me to count, so "check the power" stays a status order; yes / no to the screen's offer | a `nav` decision; the client runs it (`main.js runNav` → `academyUI.nav` / `missionUI.nav` / `setMode` / `a11y`) |
| **answer** | lesson or check-ride step: the utterance is a **plausible** answer (below); the call-sign screen | a `nav` with intent `answer`; the client grades it (`POST /api/academy/attempt`) |
| **order** | the mission cabin | the mission NLU + the learned Director (`director._mission_turn`); risky orders ask to confirm |
| **question** | anywhere: a wh-question or "tell me / show me / explain" (yes/no starts only when Arc says device-directed); the library; a clearly directed ≥ 3-word turn elsewhere | the Moon knowledge brain. "I don't know that one yet" (and the brain's "Did you mean…?") is spoken for a heard turn **only** for a clear question, and the fallback **at most once per 30 s**. It is spoken without examples; the examples are on the card only. |

Context first: in a lesson step an utterance is an answer, on the patch screen "next" and "yes" advance, in the cabin
an utterance is an order. A question works on every screen.

## Only plausible answers count

On a lesson or check-ride step, a heard (or typed) turn is a try, and so a miss when wrong, only when it is plausible
(`academy/grade.plausible`, used by both the router and the attempt API):

- it names an option: a word of it, or its number or letter ("one", "the second one", "b"; a bare "A" is option A,
  not filler);
- it overlaps what the step expects: the keywords, a place name, a mission order (not a bare "okay" = confirm), the
  space word;
- or it has 3+ content words and Arc `device_directed` ≥ the kid's filter (unknown counts).

Anything else ("Oh, it's.", "okay", "alright", "um", "what") routes to `ignore` (`not_an_answer`), silently.
On a `predict` or `earth_view` step a bare "yes" / "no" names an option, so it counts only when Arc
`device_directed` ≥ the strong threshold (0.7 at normal), or when it comes after the question finished playing and the
step has been open ≥ 1.5 s (`turn_router.yesno_counts`; the session stamps when each step opened). Otherwise it is room
talk (`room_yes_no`). If one
reaches the grader anyway, it answers `status: "ignored"` and the client counts nothing. The screen frame carries
`lesson_id` and `step`, so the router knows the step. CAPCOM's after-3-misses reveal needs 3 real misses **and** about
20 s since the step opened (`grade.reveal_due(misses, step_s)`, the client sends `step_s`); before that the third miss
gets the hint again.

## Mishears, extra words and room exclamations (round 7)

Most wrong turns are mishears before the router sees anything. Three rules handle them, all against the screen's own
short vocabulary, never against the whole language:

- **Sound-alikes** (`app/soundalike.py`): a Double-Metaphone-style key per word plus normalised edit distance, blended
  with spelling similarity. Offline, no dependencies.
  - The grader grades a failed spoken answer once more on what it sounds like, against the step's vocabulary
    (`grade.step_vocab`: options, keywords, places, side and day-night words, base parts, the space word). "four side"
    is the far side, "Malapart must be" is Malapert Massif, "rover go get eyes" asks for ice, "okay haters 40" is the
    heaters. The result carries `heard_as`.
  - `grade.plausible` counts a turn as a try when, after the repair, more than half of its content words are the step's
    own words ("rover go get eyes" yes; "my eyes hurt so much today" no).
  - Never rewritten: function words and fillers ("i see" is never "ice", "i know" is never "no"), numbers, words already
    heard as a vocab phrase. Short words ("ice", "radio") need the same consonants, the same number of syllables and
    the same first vowel ("eyes" ~ "ice"; "issue", "road", "ready" are not).
- **Navigation inside a longer turn** (`turn_router.nav_fuzzy`): the real ear adds words around a short command ("next
  liz liz", "tuesday next week", "give me a tour lance", "back to the map the other one", "i go back to my seat"). A
  navigation phrase inside the turn counts with at most one word before it and at most max(2, its length) after it.
  - One-word phrases only take the pending offer; "back", a decline, a lesson or a site never come from a fragment.
  - Every gate stays: device-directed, the hard mute (a fragment passes it only to take the offer once its line is off
    the air), and a lesson step's own answer wins ("is it the back": the far side, not navigation).
  - In the cabin, the word before "panel" is read as the closest panel name ("the comp panel" is the comm panel).
- **Room exclamations** (`turn_router.is_exclaim`): swearing and exclamations ("shit shit oh", "oh my god", "what the
  heck", "come on") are filler however device-directed Arc Tagger says they are (it gave "shit shit oh" 0.91;
  `docs/ARC_FEEDBACK.md`).

Router fixes found on the way: "go to the map" / "back to the map" were not map intents, and "panels" (plural) was not
a panel.

## Never hear ourselves

- `getUserMedia` uses `echoCancellation`, `noiseSuppression` and `autoGainControl` (`frontend/src/listen.js`).
- Every app voice (guide, CAPCOM, story, Houston, crew clips) reports `playback` with its text (`floor.js`). The session
  keeps the last 10 lines with when each played (`turn_router.Spoken`). Times are compared with the kid's turn
  **start**:
  - Lines playing then, or ended < 0.3 s before (the ear reports a turn start ~0.3 s after the sound): ≥ 60 % word
    overlap is an echo. The reply the screen is waiting for is the exception: a word that takes the pending offer
    ("next", "yes", "take command", "fly again") or a lesson step's answer is an echo only when a line was still on
    air at the turn start (`Spoken.on_air`, no 0.3 s tail). Our offer heard back, then the kid's "next" a few ms
    after it ended, is the kid. Other navigation words count as an echo when a line was playing (or ended < 0.3 s
    before) as the turn started.
  - Lines that ended 0.3–12 s before: only a near-verbatim repeat (≥ 85 %, ≥ 3 words). This catches an example
    command heard back a few seconds later. A kid answering with the prompt's words ("more power to the heaters")
    still gets through, and in lessons older lines are not used at all.
- A CAPCOM sequence (hello → brief → question, the patch line → the offer) is ONE say, a list of lines
  (`floor.say([...])`): one playback span, the floor held between lines. When a line ends with another say queued, its
  `playback` end carries `more: true` and the session holds the hard mute through the gap (`Spoken.end(more)`, at most
  4 s); the client's `floor.onAir` does the same, so the ear never slips in between lines.
- One utterance per user action: the floor drops a line that is the same (or ≥ 85 % the same) as one queued, playing or
  said in the last 3 s, in any voice (`{repeat: true}` for "Hear it again"). A sentence whose audio errors after it was
  heard is over, never re-said in the browser voice.
- While we speak (and for 600 ms after), only barge-in-worthy turns get through: a navigation or control word, or
  ≥ 3 words with `device_directed` ≥ 0.7. Space (push-to-talk) is always the kid's turn.
- The client does the same check before it sends anything (`voice.js`: `isFiller`, `turnIsEcho` over the last few
  lines, and `decideBarge` in `barge.js` while audio plays: docs/SESSION_CONTRACT.md §3 rule 2). `turnIsEcho` (`floor.js`) applies the server's exception: with the
  screen frame's pending offer or open step, the reply it waits for is an echo only when a line was on air at the
  turn start, never in the client's 2–3 s echo tail.

## The Director drives the flow

Each offer is one short line, spoken once, and the screen frame carries it (`offer`):
The offers are `OFFER` in `frontend/src/story.js` (copy v3), each spoken as its own short question:
- After a lesson: "Ready for the next lesson?" (before the check ride: "Ready for your check ride?"). "next" or "yes"
  opens it.
- After the check ride: "Ready to take command?"
- In the briefing (after picking a site): "Say take command when you're ready."
- After the debrief: "… Fly again?"
- During the first-mission cabin tour (`docs/STORY.md` §3) the frame's offer is `tour`: "next" / "yes" moves to the next
  beat, "skip tour" (`skip_tour`) ends it. "show me around" (`cabin_tour`) replays it.
- "What do I do?" / "help" / "I'm lost" / "what's my job" are one path on every screen: the router's `a11y` intent, the
  client's a11y `help` command, `window.__outpost.help`. Each screen answers: a lesson or the ride with the guidance hint
  ladder, the map and patch with the Academy's line, the cabin with its objective strip, the picker / debrief / library
  with theirs.

## Tests

- `backend/tests/test_turn_router.py`: every screen × every outcome, with noise, echo and adult chatter.
- `backend/tests/test_handsfree_loop.py`: the loop. Our own lines fed back as ear turns, hums, and ten feedback
  cycles. The fallback is limited to questions and to once per 30 s.
- `backend/tests/test_handsfree_run.py`: the whole app with no clicks (`tools/handsfree_run.py`, with the same turn
  timing as the live run: each turn starts right after the last event, so the offer's echo tail is exercised), noise at every
  screen.
- `backend/tests/test_handsfree_live.py` (`HANDSFREE_LIVE=http://…`): the app's own Steer TTS streamed into the Arc
  ear gets no reply; a kid's order in another voice does.
- `uv run python tools/handsfree_run.py --base http://127.0.0.1:8330 --audio`: the scripted run with real speech
  through the ear.

## The live mission clock (feat/mission-gameplay)

In the cabin, the router adds `skip_event` ("skip to next event", "skip ahead", "fast forward"), `time_pause` ("pause
the clock"), `time_resume` ("start the clock", "resume") and `time_warp` ("time warp four", "normal time"). These are
cabin only, and never during the tour. A bare "skip" stays a tour word.

The screen frame carries `offer: "task"` while the Now card has a job to do, so a "yes" does the job instead of being
heard as an echo or sent to the sim as a confirm. For a choice, `step_options` holds its labels, so naming one
("left", "ridge") is `task_choice`.

`tools/handsfree_run.py` does all of this by voice. It counts skips, jobs and clock commands and FAILs without them.
See docs/GAMEPLAY.md.

## Radio readback, talking over CAPCOM, hesitation (0.6)

- **Readback:** with Houston's order open on the Now card, a radio turn ("copy", "roger", "wilco") is graded against the
  order (`backend/app/mission/readback.py`, docs/GAMEPLAY.md §14.1).
  - A full readback runs the card's own order. CAPCOM adds "Good readback." as its own `say`, after its line.
  - A bare "copy" or a partial readback is never a new order. On Commander it gets one "Read back: <the card's
    words>." per step. On Cadet it gets nothing.
  - A radio turn that carries another order ("copy, send the rover for ice") runs that order.
  - A pending yes / no keeps "roger" as yes.
  - A readback cut in two by the end silence (the first half's `eot` < 0.5, the second within 1 s) is graded joined.
- **Talking over CAPCOM:** the ear's `barge_in` keeps its one job (the kid takes the floor, §3 rule 2). No line is
  added on any level. There is no check-ride radio step, so there is no "wait for 'over'" anywhere.
- **Hesitation:** a heard turn on a lesson step or in the cabin with fillers, a long pause or a low `uconf`
  (`backend/app/hesitation.py`) carries `hes: true` on its `heard` decision. The lesson's next hint rung, or the Now
  card's nudge, comes sooner, once per step (docs/LEARNING_DESIGN.md §13). The flag is never spoken, stored or logged.

## Room state (automatic, 2026-11-19, `feat/classroom-teacher`)

Schools asked for this: a classroom is noisy, and the owner rejected teacher-chosen noise presets. So the app decides on
its own how to listen. There is one estimator, `frontend/src/room.js`, wired in `voice.js`. It is never a setting. The
kid's Settings → Listening choice stays, and the room only ever makes listening **stricter** than that choice.

| room | what changes | the voice bar (`#spaceHint`; in the comm row too) |
|---|---|---|
| calm | nothing: open mic, the kid's filter | the usual "Hold to talk" |
| busy (floor up, or chatter turns) | the filter one level stricter (relaxed → normal → strict): the client barge gate (`barge.js filterLevels`), the room-talk check in `voice.js`, and the server router's dd gates (`session.filter_thresholds` → `turn_router.room_filter`) | nothing, while turns still work |
| busy, open mic keeps catching chatter (≥ 4 room-talk turns in 30 s) | hold to talk: open-mic turns are dropped on the client and ignored by the server (`ptt_only`). Space, holding the mic button, or a tap of the mic / **M** / controller **X** talks: a tap latches one turn that ends with the ear's turn end | "Busy room: hold the mic to talk" |
| loud (floor very high), or voice keeps failing (≥ 3 fails in 40 s) | hold to talk, typing offered | "Noisy room: hold the mic, or type" |
| still loud 20 s later, or one more fail | typing: the text box takes the keyboard once (never from another text box or under Settings); its placeholder says the line | "Too noisy: type instead" |
| calm again | open voice, silently | back to "Hold to talk" |

**Evidence** (read on the moment, never stored or logged):
- The **noise floor** is the 15th percentile of mic RMS over the last 125 frames (10 s) taken while none of our audio plays.
  Frames under our own voice or a held Space turn are skipped, and none older than 30 s count. A kid talking leaves
  gaps; classroom babble does not.
- **Room talk** comes from these sources:
  - the router's ignore reasons `crew_talk`, `not_directed`, `chatter`, `room_yes_no`, `callsign_other` (`voice.decided(outcome, text, d)`);
  - Arc `device_directed` under the effective floor;
  - a turn the router ignored with speech-to-noise under 2 (the turn's loudest frame over the floor);
  - held barge-ins for `not_directed` / `not_rated`;
  - open-mic turns heard while hold to talk is on, which are still read for evidence.
- **Failures** are a directed turn the app could not use (`notice`, `unclear`), `uconf` under 0.35 on a directed turn,
  or the same words again within 20 s of an ignore.
- Space and typed turns are never room talk.

**Hysteresis:**
- Entering and leaving use separate levels. Busy starts at floor ≥ 0.016 held for 4 s and ends under 0.009 held for 8 s.
  Loud starts at ≥ 0.05 held for 3 s and ends under 0.03 held for 8 s.
- Chatter starts busy at 3 turns making up ≥ 60 % of the open-mic turns, and allows calm only at ≤ 1 turn.
- Every state has a minimum dwell: busy 10 s, loud 15 s.
- Evidence slides out of 30 s / 40 s windows.
- Hold to talk, once asked, stays for the whole busy spell. It never flips back and forth.

**Session wire (additive):** the client sends `room` (`calm|busy|loud`) and `room_listen` (`open|hold|type`) with its
`prefs` message whenever the room changes (`prefs.roomWire`, `outpost:room`). See docs/SESSION_CONTRACT.md §7.

**Numbers** come from `node frontend/tools/room_harness.mjs`, which is also the last test in `tests/room.test.js`.
- Each scenario is a stream of 80 ms mic levels plus turn messages.
- The levels are real where the repo has them:
  - the mic hiss floor (0.0012);
  - the six recorded room-noise beds of `tests/fixtures/barge` (p20 0.021-0.026), from `tools/barge_clips.py`;
  - the kid command clips' speech frames (at -22 dBFS).
- Babble at an SNR is that kid level minus the SNR, with talker fluctuation (log-normal, sigma 0.35).
- Times are seconds from the scenario start, including ~3 s of floor warm-up.
- Flaps count a state left and re-entered within 20 s.

| scenario | busy at s | loud at s | hold at s | offer / type at s | switches | flaps | recover s | end | ok |
|---|---|---|---|---|---|---|---|---|---|
| quiet, kid talks (5 min) | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| quiet, kid's long answers | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| quiet, a grown-up remark /40 s | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| quiet, one loud cheer (1.5 s) | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| quiet, door slams x3 in 20 s | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| recorded bed noise_cabin_237374 | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| recorded bed noise_cafe_370973 | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| recorded bed noise_cafe_437461 | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| recorded bed noise_room_108695 | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| recorded bed noise_room_426767 | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| recorded bed noise_room_641306 | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| babble SNR 25 dB | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| babble SNR 20 dB | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| babble SNR 15 dB | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| babble SNR 10 dB | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| babble SNR 5 dB | 7.1 | - | - | - / - | 1 | 0 | - | busy/open | yes |
| babble SNR 0 dB | - | 6.2 | - | 6.2 / 26.2 | 1 | 0 | - | loud/type | yes |
| 2 kids chatting near the mic (quiet floor) | 16.1 | - | 20.6 | - / - | 1 | 0 | - | busy/hold | yes |
| busy bed + chatter turns | 17.2 | - | 22.3 | - / - | 1 | 0 | - | busy/hold | yes |
| voice keeps failing (Didn't catch that) | 7.1 | 22 | - | 22 / 30 | 2 | 0 | - | loud/type | yes |
| loud room (SNR 0) then quiet | 99.8 | 6.2 | 99.8 | 6.2 / 26.2 | 3 | 0 | 19.8 | calm/open | yes |
| classroom babble 60 s then quiet | 12.6 | - | - | - / - | 2 | 0 | 10 | calm/open | yes |
| chatter spell 60 s then quiet | 11.4 | - | 17.6 | - / - | 2 | 0 | 22.6 | calm/open | yes |
| floor wobbling at the busy edge | - | - | - | - / - | 0 | 0 | - | calm/open | yes |
| floor swinging across both edges | 21.2 | - | - | - / - | 8 | 0 | - | calm/open | yes |
| busy bed, our audio playing a lot | 21.2 | - | - | - / - | 1 | 0 | - | busy/open | yes |

**Reading the numbers:**
- Quiet rooms never switch. That holds with a kid talking 60 % of the time, a grown-up remark every 40 s, a cheer, and
  door slams.
- Every recorded noise bed and babble at SNR ≤ 10 dB reads busy in about 4 s once the floor is known. In busy, only the
  stricter filter changes and nothing is shown.
- SNR 15 dB and quieter stays calm.
- Two kids chatting near the mic reach hold to talk in about 20 s.
- Voice that keeps failing reaches typing in about 30 s.
- A busy room calms about 10 s after it goes quiet. Coming down from loud takes about 20 s (via busy, holding the mic).
- A floor swinging across both edges over 75 s follows the room (8 switches in 5 min) with no flapping.

**Caveats:**
- The browser's `noiseSuppression` / `autoGainControl` change the mic level on real laptops. Steady fan noise is
  removed before we see it, and babble mostly is not. The thresholds were set on the fixture mic chain, not on a real
  classroom: recalibrate them on the first school recordings.
- Arc asked to predict a room-noise / chatter signal directly: docs/ARC_FEEDBACK.md (2026-11-19).

**Tests:** `frontend/tests/room.test.js` (estimator, hysteresis, dwell, effects, the harness) and
`frontend/tests/room_voice.test.js`:
- busy → the line plus open-mic dropped plus a mic tap still talks;
- loud → typing;
- the barge gate one level stricter;
- the router's ignored room talk drives busy → hold.

`backend/tests/test_room_state.py` covers `room_filter`, the session thresholds, and hold / type ignoring open mic but
not Space or typed turns.

**Screenshots / tools:** `window.__outpost.room.force("busy")` gives hold to talk. `force("loud")` offers typing, and
`force("loud", "type")` gives typing. `force(null)` returns to automatic from calm. `window.__outpost.room.snapshot()`
returns `{state, mode, floor, line, filter}`.
