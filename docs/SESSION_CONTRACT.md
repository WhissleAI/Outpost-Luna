# Session contract: streams in, decisions out, and the rules of the floor

The Director becomes a **session Director**: one live session per browser. It reads every stream, keeps one picture of
what is going on, and sends **several typed decisions** back. The app follows one set of floor rules, so one voice
speaks at a time, the kid can always interrupt, and the app never answers itself.

## 1. Streams in (client → server, `WS /ws/session`)

All messages are JSON with `t` and the client clock `ts` (ms). Mic audio keeps flowing on `/ws/listen`; that relay posts
its events into the session server-side.

| `t` | From | Payload | Notes |
| --- | --- | --- | --- |
| `hello` | client | `{mode:"academy"\|"mission"\|"cadet", mission_id?, lesson_id?, role?}` | First message; sets the session id |
| `ui` | client | `{event:"tap_place"\|"tap_artifact"\|"button"\|"end_shift"\|"lesson_answer"…, id?, value?}` | Taps and buttons are input too |
| `playback` | client | `{kind:"guide"\|"crew", state:"start"\|"end"\|"interrupted", id?, t?}` | So the Director knows who holds the floor |
| `typed` | client | `{text}` | Typed questions; same path as speech |
| (server-side) `words` / `turn` / `arc` / `emotion` | `/ws/listen` relay | as today | Flux words + turns, Arc metadata |
| (server-side) `telemetry` / `event` | mission sim | as `MISSION_CONTRACT.md` | Proactive: storms, comm windows, alarms |

## 2. Decisions out (server → client, same socket)

A turn or an event can produce **several decisions**. Each has `id`, `priority` (0 = highest) and an optional `after`
(the id of a decision it waits for).

| `t` | Payload | Client does |
| --- | --- | --- |
| `say` | `{text, voice:"guide"\|"capcom"\|"story", audio_url?}` | Plays it on the guide channel (in-page audio, see §4); shows a caption |
| `play` | `{moment\|clip_id, t0, t1, explain:[{t,word,explain}]}` | Crew audio on the crew channel |
| `fly` / `highlight` | `{place?, view?, ids?}` | Globe |
| `card` | `{title, body, chips, actions:[{label, send:{t:"typed",text}\|{t:"ui",…}}]}` | Answer, CAPCOM or lesson card |
| `hud` | `{state}` or `{patch}` | Mission HUD |
| `alert` | `{level:"info"\|"warn"\|"critical", text, source?}` | Banner + chime |
| `ask_confirm` | `{text, yes:{…}, no:{…}}` | Yes/No; voice "yes"/"no" also works |
| `lesson` | `{lesson_id, step, status:"brief"\|"task"\|"passed"\|"retry"\|"done", score?}` | Academy UI |
| `floor` | `{holder:"kid"\|"guide"\|"crew"\|"none"}` | Indicator only |
| `cancel` | `{ids:[…]}` | Drop decisions not yet played (barge-in, newer turn) |

`/api/ask` stays for compatibility and returns the same decisions as a list (`decisions:[…]`), alongside the old fields.

## 3. The floor rules (who may speak when)

1. **One voice at a time.** The guide and crew audio never overlap; the guide speaks only at crew sentence ends.
2. **The kid always wins.**
   - **Hold Space** (anywhere except a text box; a focused button is blurred first) → the guide stops within 200 ms and
     crew audio ducks to 15%.
   - **Open-mic speech** while audio plays counts as barge-in only when ALL hold:
     - Flux `StartOfTurn`;
     - ≥ 2 words heard;
     - the words are **not** an echo of what we're playing (fewer than 60% of them appear in the current guide or crew
       text);
     - when Arc is available, `device_directed` ≥ 0.5.
3. **Never talk over the kid.** While the kid holds the floor, new `say` decisions wait; a newer turn cancels older,
   unplayed decisions.
4. **After an interruption:** if the kid's turn has no request, crew audio resumes and the guide doesn't repeat
   itself.
5. **Proactive speech** (storm warning, comm window, lesson coaching) only when the floor is `none`, except `critical`
   alerts, which take the floor after the current sentence.
6. **Priorities:** safety and privacy guard (0) > kid barge-in (1) > critical alert (2) > answer to the kid (3) >
   lesson/mission narration (4) > nudges (5).
7. **Silence is fine.** No nudge within 8 s of the last speech; at most 1 nudge per 30 s.

## 4. Audio channels in the browser

- **Guide channel:** server-rendered speech (`GET /api/tts?text=…&voice=…` → audio, cached), played as **in-page
  audio**, so the browser's echo cancellation can remove it from the mic. Falls back to `speechSynthesis` (sentence by
  sentence, never `cancel()` immediately before `speak()`).
- **Crew channel:** the existing crew-audio player.
- **Effects:** the chime.
- A single **floor manager** owns all three. It reports `playback` events on the session socket.
