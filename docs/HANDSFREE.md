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
| **ignore** | empty; filler or non-lexical ("oh", "um", "mm-mm", "uh-huh"); echo of our own voice; heard while we speak (or < 600 ms after) and not barge-in-worthy; Arc `device_directed` < 0.5; one word that is not an intent; a tap step's unrelated words; a long ramble in a lesson | silence. Our own speech is never cancelled. The mic chip shows "Didn't catch that" only when the turn was clearly device-directed (`notice`). |
| **navigate** | start, next, go back, patch map, lesson N or a title ("space words"), go to mission, take command, pick \<site>, debrief, fly again, another site, academy, library, zoom out / show the rover / back to the outpost, settings, slower / faster, say that again, the a11y commands (where am I, press X, option 2); the voice bar ("move the voice bar to the top right", "reset the voice bar": intent `a11y`, `text` = the canonical command `voicebar.js` parses), on every screen; in the cabin, the 3D panels ("open the comm / power / habitat panel", "go to the hab", "open the rover / radiation panel" → `panel_comm`, `panel_power`, `panel_habitat`, `panel_rover`, `panel_radiation`; "back", "back to my seat", "close the panel", "seat" → `panel_back`). Panel phrases never reach the mission NLU ("open the comm panel" once turned the radio off); without the word "panel" only open / go to / take me to count, so "check the power" stays a status order; yes / no to the screen's offer | a `nav` decision; the client runs it (`main.js runNav` → `academyUI.nav` / `missionUI.nav` / `setMode` / `a11y`) |
| **answer** | lesson or check-ride step: the utterance is the step's answer (choice, keywords readback, command, intent, tap by naming the place, vocab); the call-sign screen | a `nav` with intent `answer`; the client grades it (`POST /api/academy/attempt`) |
| **order** | the mission cabin | the mission NLU + the learned Director (`director._mission_turn`); risky orders ask to confirm |
| **question** | anywhere: a wh-question or "tell me / show me / explain" (yes/no starts only when Arc says device-directed); the library; a clearly directed ≥ 3-word turn elsewhere | the Moon knowledge brain. "I don't know that one yet" (and the brain's "Did you mean…?") is spoken for a heard turn **only** for a clear question, and the fallback **at most once per 30 s**. It is spoken without examples; the examples are on the card only. |

Context first: in a lesson step an utterance is an answer, on the patch screen "next" and "yes" advance, in the cabin
an utterance is an order. A question works on every screen.

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
- While we speak (and for 600 ms after), only barge-in-worthy turns get through: a navigation or control word, or
  ≥ 3 words with `device_directed` ≥ 0.7. Space (push-to-talk) is always the kid's turn.
- The client does the same check before it sends anything (`voice.js`: `isFiller`, `turnIsEcho` over the last few
  lines, and `shouldBargeIn` while audio plays). `turnIsEcho` (`floor.js`) applies the server's exception: with the
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
