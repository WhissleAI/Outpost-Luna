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
| `prefs` (or `type:"prefs"`) | client | `{voice?, voice_all?, rate?, expressiveness?, filter?, level?}` | Settings, after `hello` on every connect (partial updates fine); acked with `{t:"prefs", applied}`. Never persisted server-side. See `VOICES.md` |
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

## 5. Additive fields (session Director, feat/session-director)

Nothing above was changed; these were only added:
- **`hello`**: `session` (the session id; required on the first hello), `mission_id` may be re-sent with a later
  `hello` (mode switch, new mission). Server replies `{t:"ready", session}` once.
- **`typed`**: `source:"voice"|"typed"` (the same turn text from the listen relay and from the client counts once).
- **`ui` events**: `barge_in` (the client accepted a barge-in: Space or its echo check), `kid_done`, `mission_start`
  `{id}`, `end_shift` (the session advances the sim and answers with `hud` + `card` + `say` + event decisions).
- **`/ws/listen`**: `?session=<id>`, or `session` inside a `{"t":"context"}` frame, attaches the relay to a session.
- **Decisions**: `say.delay_ms` (Houston round trip; the client waits before speaking), `say.proactive`; `card.asked`,
  `card.claims`, `card.readout`, `card.source`, `card.action`, `card.place`, `card.resolved` (the turn after "it" was
  resolved), `card.hint` (a heads-up card), `card.nudge` (a coaching card); `alert.source`; `play.moment` (the full
  moment). `ask.labels` (place names) on the old `/api/ask` `ask` object.

## 6. Additive fields (voice steering)

Nothing above was changed; these were only added (details: `docs/VOICE_STEERING.md`):
- **`say.voice`** may also be `"houston"` (Houston's reply after the radio delay).
- **`say.style`** on every `say` (session Director, `/api/ask` `decisions`, Academy attempt `decisions`):
  `{voice, tts_voice, tag, controls:{rate?, loud?, f0_med?, f0_iqr?, f0_end?, pause?, …}, perform:{genre, strength},
  situation?, emph?:[words], markup?:true}`. The client passes it unchanged to `GET /api/tts?…&style=<json>` (plus
  `i`, `n`, `next`: the sentence's place) or `POST /api/tts {text, voice, style, i, n, next}`. A client-written line may
  send only `{situation}` or `{emotion}`; the server resolves it. The server re-checks the tag (never anger, contempt,
  disgust, sarcasm, panic or disappointment) and clamps the controls.
- **Sim events**: `storm_end` → `alert:info` + `say` (all clear); `low_power` → also a calm `say`.
- **`/api/tts`** replies carry `X-TTS-Engine: os|deepgram`, `X-TTS-Voice` (the OS voice used), `X-TTS-Style`,
  `X-TTS-Words`, and `X-TTS-Fallback` when the OS voice was skipped; OS-voice audio is `audio/wav`, Deepgram
  `audio/mpeg`. `tts_voice` is a persona role or an installed OS voice id (`GET /api/voices`, docs/VOICES.md).
