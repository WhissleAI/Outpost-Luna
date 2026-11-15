# Voice pack: the recorded guide voice

Outpost Luna's fixed, scripted lines are pre-recorded with the macOS Siri voice **Siri Voice 1**
(`com.apple.siri.natural.Nora`). The clips ship in both the Mac and the Windows app, so every kid hears Nora for the
scripted lines. Anything else (answers, readbacks with live numbers, names) is still spoken live by the OS voice engine
(docs/VOICES.md).

## Files

| Path | What |
|---|---|
| `backend/data/voice_pack/lines.json` | the manifest: every fixed line, `{key, text, source, role, sources}`, key = `os_voices.pack_key(text)` |
| `backend/data/voice_pack/lines_live.md` | the report of what stays live, and why |
| `backend/data/voice_pack/index.json` | what is recorded: `{clips: {key: {file, text, dur, words, voice, sha256, recipe, bytes}}}` |
| `backend/data/voice_pack/clips/*.mp3` | one clip per line: mono MP3, 48 kbps CBR, 22.05 kHz. The name is a hash of the key and the recipe (keys are long and Windows paths are short) |

The clips are committed to git. The desktop build copies `backend/data` (minus media and caches) into the app, so the
pack is in both installers. `build-mac.sh`, `build-windows.ps1` and `cross-build-windows.sh` run
`backend/tools/voice_pack_check.py` first. `win_bundle_check.py compare` and `build_python.py` check that the pack is
there.

## Commands

```
make voice-pack-lines    # rebuild the manifest (any OS; needs node)
make voice-pack          # record missing / changed lines (macOS, System voice = Siri Voice 1)
make voice-pack-check    # list manifest lines with no clip; exit 1 if any
```

### The inventory (`backend/tools/voice_pack_lines.py` + `frontend/tools/voice_lines.mjs`)

- **Frontend half.** Every line the UI speaks from `story.js`, the course, the tour, the Now strip and the debrief,
  composed the way the UI composes it. It then splits each `say` into the units the floor actually requests: one
  `/api/tts` request per sentence, with fragments under 20 characters folded into the next (`floor.js sayLines`). The
  pack is looked up per request, so it is keyed per unit.
- **Backend half.** Flight School replies are built by the real code: success, reveal, "Here it is.", the hint ladder
  through `guide.ladder`, route progress and the check ride. Mission and session lines are harvested with `ast` from
  the places the app speaks from: a `say`, `decision("say", text=…)`, a task's label or ack, the returns of
  `capcom.readback` / `status`. A new fixed line is therefore picked up without editing the tool. An f-string with an
  open placeholder is listed in `lines_live.md`.
- **Expanded placeholders** (small, fixed sets): the preset call signs (plus the "Cadet", "cadet" and "Commander"
  fallbacks), the five sites, hours 1–12, warp factors, check-ride scores 0–5, debrief days 1–10 and storm counts 1–4.
  Everything else stays live.

### The recorder (`model_server/tools/voice_pack_record.py`)

- Siri voices can't be chosen with `say -v` (error -244). Each line is rendered with plain `say -o` (no `-v`), which
  uses the **System voice**. Before every batch, and again at the end, the recorder reads
  `defaults … SpokenContentDefaultVoiceSelectionsByLanguage`. If the voice isn't `com.apple.siri.natural.Nora`, it
  aborts and tells the owner to set *System Settings → Accessibility → Spoken Content → System voice → Siri Voice 1*.
  It never changes the setting. If the voice changes mid-run, it discards that run's clips and restores the previous
  index.
- **Native rate, natural pauses:** no `-r`. The app also speaks at the voice's own pace at 1×, and a forced rate
  audibly degrades Siri's prosody.
- It trims the silence at both ends (40 ms kept) and sets speech RMS to −20 dBFS with peaks under −1 dBFS, using gain
  only. It encodes MP3 with libsndfile (deterministic), decodes it back, and estimates the word timings on exactly the
  audio the app plays (`os_voices.estimate_timings`, snapped to silences, the same estimator as the live macOS path).
- It is incremental: a line is re-rendered only when its text, the voice or the recipe changed, or its clip is
  missing or corrupt. Clips that are no longer in the manifest are pruned.

## Runtime

`POST /v1/tts` on the model server (`app/tts_os.py`) asks `PACK_LOOKUP` (`app/voice_pack.py`) **before** the engine
when all of these hold (`pack_ok`):

1. the backend opted in (`"pack": true`);
2. the kid's pace is 1×;
3. no extra sentence pauses were requested (slow explain / vocab lines);
4. the resolved voice is this machine's **default guide voice**.

A hit returns a 24 kHz WAV with the same contract as live TTS: `X-TTS-Words` (the recorded timings when they cover the
same display words, else estimated on the clip), the end gap when a sentence follows, and `X-TTS-Engine: pack`. The
backend masters it like any line (volume, alarm offset) and passes `X-TTS-Engine` through, cache hits included (a
`.engine` sidecar). Its cache key includes the pack index's version, so a re-recorded clip is never hidden by a cached
render.

The backend's `use_pack` decides the opt-in:

| Case | Behaviour |
|---|---|
| **Pace** ≠ 1× | Live. A clip is never time-stretched. A cheap stretch would sound worse than the engine at that rate, and live is always correct. |
| **Settings toggle**, *Voice → "Use the recorded guide voice for story lines"* | On by default (`prefs.pack`). Off means live. |
| **Chosen voice** | Picking any voice other than the default turns the pack off: the kid hears their voice, live. Picking the default explicitly keeps it on (`steering.pack_allowed`, `floor.js packAllowed`). |
| **Roles** | The guide and CAPCOM are in the pack. With a good system voice, the default roles already give the guide, CAPCOM and the story the `system` voice (docs/VOICES.md, Roles), so recorded and live lines share one voice. As a backstop, while the pack is on, CAPCOM's live lines use the guide voice in any case. **Houston** (its own radio voice when a good en-US / en-GB voice is installed) and the hardware's **story** lines are always live. |
| **Windows** | The same clips play. Live lines use the Windows default guide voice, so a Windows kid hears Nora for scripted lines and the Windows voice for answers. |

## The OS voice at its own pace (2026-11)

At 1× the OS voice is no longer pushed. Before, `say -r` (~165–196 wpm), the steering baseline (`rate +1.0`,
`pause −1.5`), a 0.25 s gap cap and a look-ahead limiter made Siri sound processed. The sample line "A round dark sea
near the Moon's right edge. It's easy to spot with your own eyes." played in 4.06 s against the voice's own 5.0 s. Now:

- At pace 1×, and within ±8 % of it (persona and situation nudges), `say` gets no `-r`, WinRT gets rate 1 and SAPI 0
  (`os_voices.NATIVE_BAND`).
- Any other pace uses `-r` relative to the voice's **measured** native words/min (`SayEngine.native_wpm`, one
  calibration render per voice).
- A negative `pause` never shortens the voice's own pauses. Only a positive one adds silence.
- The backend cuts only pathological silences (over 1 s). Loudness is a single clean gain to the target with a
  −1 dBTP ceiling: no limiter or compressor on the OS voices. `MASTER_VERSION` 4 invalidates the old fast renders.
