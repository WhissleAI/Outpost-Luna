# Voice steering: the OS's own offline voices, steered by the Director

Every spoken line in Outpost Luna (Academy, Mission and the Moon library) is rendered by **the operating system's own
offline voice** (macOS `say`; Windows WinRT SpeechSynthesis, SAPI as the fallback). The Director picks *how* each line
is said, not only *what*: a style with a tag, numeric controls, emphasis and a situation. The OS voices honour the
rate (with the kid's speed) and pauses; the rest of the style is kept for the cache key, the slow / alarm rules and any
richer engine, and is dropped cleanly by the model server. Steer TTS Edge, the engine this was first written for, is
gone (owner decision 2026-11-14); this file keeps the policy.

## 1. The engine

| | |
| --- | --- |
| Where it runs | **only in the model server** (`model_server/app/tts_os.py`; rules in `os_voices.py`), behind `OS_TTS=on\|off` and `OS_TTS_ENGINE=auto\|say\|winrt\|sapi` |
| Nothing to download | macOS: `/usr/bin/say`. Windows: WinRT (pywinrt 3.2.1 wheels in the model server's lock, `sys_platform == 'win32'`), then SAPI through comtypes |
| Voices | this machine's, ranked (docs/VOICES.md "The OS voices"); persona roles mapped onto them |
| Warm-up | "Ready." rendered at startup in the guide's voice (`/health` `warm_ms`) |
| Health | `GET /health` → `models.tts: {loaded, error, engine, timing, voice, voice_name, voices, roles, locale, load_s, warm_ms}` |

`POST /v1/tts` on the model server (the request shape the backend always sent):

```json
{"text": "Copy, commander. Shields to *40* percent.", "voice": "capcom", "tag": "confidence",
 "controls": {"rate": 1.3, "pause": -1.5}, "markup": true, "pace": 1.0,
 "perform": {"genre": "children", "strength": 0.7, "para_index": 0, "para_len": 3, "next": "That leaves less for life support."}}
```

→ `audio/wav` (24 kHz mono 16-bit). Headers: `X-TTS-Voice` (the OS voice id), `X-TTS-Voice-Name`, `X-TTS-Engine`
(`say` / `winrt` / `sapi`), `X-TTS-Timing` (`os` / `estimated`), `X-TTS-Words`, `X-TTS-Ms`, `X-TTS-RTF`, `X-TTS-Rate`,
`X-TTS-Pause-Ms`, `X-TTS-Pace`. `voice` is a role (`guide`, `capcom`, `houston`, `story`) or an installed voice id; an
unknown or blocked id falls back to the guide's voice. Repeated lines come from a small in-memory cache, and the backend
caches every line on disk.

**Sentence streaming.** The floor splits text into sentences and prefetches the next one while the current one plays,
so per-sentence calls give the time to first audio of one sentence (~1.3 s with a Siri system voice, ~0.8 s with a
premium voice on the build Mac). A sentence with a next one ends on a 220 ms gap.

## 2. The fallback chain

`GET|POST /api/tts` (backend, `backend/app/tts.py`), `TTS_ENGINE=os|deepgram` (default `os`; an old `steer` value means
`os`):

1. **The OS voice** (model server `/v1/tts`, timeout `TTS_TIMEOUT_S`=8 s) → `audio/wav`, `X-TTS-Engine: os`.
2. **Deepgram Aura-2** (when `DEEPGRAM_API_KEY` is set; never in the desktop app) → `audio/mpeg`,
   `X-TTS-Engine: deepgram`, `X-TTS-Fallback` says why the OS voice was skipped. It gets the persona voice only.
3. **The browser voice**: 503 (no engine configured) or 502 (engines failed) with `{"fallback":"browser"}`; `floor.js`
   speaks with `speechSynthesis`, sentence by sentence.

The disk cache (`tts_cache/`) keys on engine + the concrete OS voice (the system voice also names the voice behind it)
+ text + the canonical JSON of the style + the sentence's place, so a re-steered line or a newly picked voice never
replays a stale rendering. `/api/tts?text=&voice=` keeps working: no style → the persona's default style.

## 3. Voices

Personas are roles (`steering.VOICES`); the model server maps them onto this machine's voices
(`os_voices.assign_roles`): the guide gets the best voice, CAPCOM a different good one (the other gender first),
Houston a third, the story voice a fourth, each falling back when fewer good voices are installed. Details, the ranking
and the build Mac's list: docs/VOICES.md.

Deepgram fallback: guide=`aura-2-thalia-en`, capcom/houston=`aura-2-orion-en`, story=`aura-2-iris-en`.

## 4. The steering policy (`backend/app/steering.py`)

`style_for(voice, text, situation, places)` → `style`. One table plus four rules; `tests/test_steering.py`
pins each row.

**Persona base** — guide `interest`; CAPCOM `confidence`, rate +0.3; story `nostalgia`, rate −0.5, f0_med +0.4;
houston `enunciated`, rate +1.2 (was −0.2: 2.1 words/s; §4d).

**Situations** (controls are z-scores against the voice's own neutral speech; tags alone are weak style switches, so each row
pairs its tag with controls that carry the effect):

| Situation | When | Tag | Controls |
| --- | --- | --- | --- |
| `storm_alert` | storm is here (sim event, status during a storm) | `determined` | rate +0.6, loud +0.8 |
| `storm_warning` | storm coming | `emphasis` | rate +0.3, loud +0.4 |
| `failure` | mission failure | `determined` | rate +0.3, loud +0.5 |
| `all_clear` | storm over | `relief` | rate −0.2, f0_iqr +0.5 |
| `night_low_power` | low battery in the dark | `serenity` | rate −0.5, loud −0.4, f0_iqr −0.3 |
| `comm_open` | Houston can hear us | `interest` | rate +0.2 |
| `mission_complete` | mission done | `pride` | loud +0.4, f0_iqr +0.8 |
| `readback` | CAPCOM confirms a command / status | `confidence` | rate +0.3 |
| `explain` | glossary: a hard word | `enunciated` | rate −0.8, pause +0.4 |
| `awe` | the line before crew audio plays | `amazement` | rate −0.4, f0_iqr +0.8 |
| `badge` | badge earned | `pride` | rate +0.3, loud +0.5, f0_iqr +1.0 |
| `passed` | lesson step passed | `happiness` | f0_iqr +0.6 |
| `retry` | wrong answer, hint, missed order | `sympathy` | rate −0.4, loud −0.2 |
| `story` | hardware tells its own story | `nostalgia` (story voice) | rate −0.5, f0_med +0.4 |
| `lesson_brief` | lesson brief | `interest` | rate −0.2 |
| `guard` | privacy guard | `serenity` | rate −0.3, loud −0.3 |

**Rules**

0. **No kid affect** (D6, `docs/BRAIN.md` §6a): the style never changes with a guess at how the kid feels. The old
   affect rule and its stream are deleted; `backend/tests/test_no_emotion.py` guards it.
1. **A question to the kid** (text ends with `?`) → f0_end ≥ +1.5 (rising).
2. **Emphasis**: in readbacks, alerts, failure, night and explanations, the first 3 distinct numbers; in any line, the
   place name when the Director resolved one. Sent as `style.emph`; the backend wraps them in emphasis markup (`*40*`,
   `<emph>Mare Tranquillitatis</emph>`) just before rendering, so captions stay clean and sentence splitting is not
   affected.
3. **Safety**: never `anger`, `contempt`, `disgust`, `sarcasm`, `panic`, `disappointment` (nor `irritation`,
   `frustration`, `skeptical`, `bored`) toward a kid. A forbidden tag from any source (row, caller, client) becomes the
   persona's tag; the backend re-checks the client's style. Controls are clamped to ±2.5.
4. **Performance**: every style carries `perform: {genre: "children", strength: 0.7}` (§1).

**Where the Director picks the situation**

| Producer | Situation |
| --- | --- |
| `director.decisions_for` (session Director and `/api/ask`) | `steering.situation_for(r)`: guard, glossary → explain, play → awe, command → readback, status → storm_alert / night_low_power / readback; the resolved place name for emphasis; `houston` action → houston voice |
| `Session.proactive` (sim events) | solar_storm → storm_warning / storm_alert, storm_end → all_clear (new say), comm_open, low_power → night_low_power (new calm say), failure, mission_complete |
| `Session.end_shift` | from the new state (storm / night low power / readback) |
| Academy `/api/academy/attempt` | passed / retry / hint / missed / done, badge → `badge` |
| Client-written lines (`floor.js` callers) | lesson brief, badge award, hardware story send `{situation}` only; the backend resolves it through the same table |

## 4b. Accessibility steering: speed, the `vocab` situation, vocabulary emphasis, word timings

> **2026-11: the OS voices speak at their own pace.** The baseline below is now `rate 0, pause 0`. At 1× (±8 %) the
> model server passes no `say -r` (WinRT rate 1, SAPI 0). Another pace uses `-r` relative to the voice's measured
> native words/min. A negative `pause` never shortens the voice's own pauses. The gap cap is 1.0 s (1.2 s at 0.75×
> and on slow lines). Loudness is one clean gain with a −1 dBTP ceiling and no limiter. The rows and numbers below
> describe the Steer era. Details: docs/VOICE_PACK.md, "The OS voice at its own pace".

**Speaking pace preference.** The kid's caption-bar speed (0.75× / 1× / 1.25× / 1.5×, `a11y.js`, stored on the device
only) goes to `/api/tts?speed=` (or rides on the say style as `speed`, from the Settings `rate`).
`steering.delivery(controls, speed)` adds the 1× delivery baseline (§4d) and then `speed_steer(speed)`. "1×" is the
new, faster default:

| speed | `rate` offset from `speed_steer` (z, 4 per octave) | baseline `pause` (z) | inner-gap cap | `pace` | measured words/s (Steer era; re-measure on the OS voices) |
| --- | --- | --- | --- | --- | --- |
| 0.75× | −1.66 | +0.5 | 0.45 s | 0.85 | 2.5–2.9 (slower than the old 1×, 2.8–3.2) |
| **1×** | 0 | −1.5 | 0.25 s | 1 | **3.3–3.8** (Houston 3.0) |
| 1.25× | +1.29 | −1.5 | 0.25 s | 1.13 | 3.8–4.3 |
| 1.5× | +2.34 | −1.5 | 0.25 s | 1.25 | 3.9–4.4 |

These rate offsets sit on top of the baseline's +1.0 and are clamped at ±2.5. The model server turns rate and pace into
one multiplier, `pace · 2^(rate/4)` (macOS `say -r` = 165 wpm × it; WinRT `SpeakingRate` = it; SAPI `Rate` =
10·log3(it)), so 0.75× is ~0.76× and 1.5× ~1.9× of the plain voice, and a storm alert stays faster than a calm line
at every speed. At 1× a premium macOS voice speaks ~3.5 words/s, the brisk pace kids heard before. Crew audio is a
recording: it gets `playbackRate` (pitch preserved) instead.

**`vocab` situation** — `enunciated`, rate −1.0, pause +0.6, f0_iqr +0.3: slower, clear gaps, a little more melody,
for new words and younger kids. Used by every Space-words attempt reply that isn't a pass, by "Hear it" on a glossary
card, and by the vocab step buttons.

**Per-word vocabulary emphasis.** `style_for(..., vocab=[terms])` keeps the lesson's terms that occur in the line
(`style.vocab`, ≤ 3); `/api/tts` wraps each in `<slow><emph>term</emph></slow>` (`steering.apply_markup`: vocab first,
then the usual number/place emphasis). The OS voices cannot stress one word, so the model server strips the markup;
the `vocab` situation's slower rate and longer pauses carry the effect.

**Word timings.** Per display word (the line without markup, split on whitespace), as `startMs-endMs,…`:
- **Windows (WinRT): real.** The voice's word-boundary cues (`IncludeWordBoundaryMetadata`: start time, duration and
  character position), mapped onto the display words by position, then by text in order (`os_voices.map_cues`).
- **macOS (`say`) and SAPI: estimated, anchored on the audio.** `os_voices.estimate_timings` finds the speech span and
  the inner silences (10 ms frames, −32 dB of the loudest), spreads the words over it by syllables + characters with
  nominal punctuation pauses, then snaps every comma / sentence break to the nearest real silence, so errors cannot
  build up along a long line. Inserted `[[slnc]]` pauses are known exactly.
The model server returns `X-TTS-Words`; `/api/tts` validates it, re-maps it after capping long silences, caches it next
to the WAV (`.words`) and returns it as `X-TTS-Words` (exposed for CORS). Deepgram and the browser voice have no
timings: the caption bar estimates from the audio length and syllables, or follows `speechSynthesis` boundary events.

## 4c. Settings: the kid's voice, rate and expressiveness

See `VOICES.md`: say styles carry `tts_voice`, `speed`, `expr` and `volume`, and `/api/tts` applies them
(`steering.apply_prefs`, `with_expressiveness`, `delivery`, `tts.finish`).

## 4d. Louder and faster: the delivery baseline and the master stage

Steer (the first engine) sounded low and slow. Raw renders measured −23.8 to −26.0 LUFS, 2.4–3.2 words/s, with long phrase gaps. Every
`/api/tts` render (now the OS voice) goes through three stages: native controls first, then two DSP steps
(`tts.speak` → `steering.delivery` → `tts.finish` → `app/loudness.py`).

**1. Native controls (the delivery baseline, `steering.BASE_CONTROLS`)**, added on top of every style at 1×:

| control | z | why | measured alone (guide) |
| --- | --- | --- | --- |
| `pause` | −1.5 | shorter phrase pauses: long gaps are most of what made it feel slow | 2.96 → 3.16 words/s |
| `rate` | +1.0 | faster articulation | +0.4 words/s with the pause change |
| `loud` | +0.4 | a little more vocal energy (projection) | +0.8 LU raw. It does not change the crest factor, so DSP still does the levelling |

Steer's `loud` tag was also tried. It was inconsistent: the guide got quieter (−24.4 LUFS against −23.8 base), and
Crater got louder but 1.7 dB peakier. So it is not used. `pace` is ignored by the running build (§4b).

**Slow on purpose:** the `explain` and `vocab` situations, and any line with vocabulary words, get no baseline rate or
pause and a gentle 0.6 s gap cap (`steering.SLOW_SITUATIONS`). They keep the situation's own −0.8 / −1.0 rate.

**2. Gap cap (`loudness.cap_gaps`):** silences inside the line longer than 0.25 s (0.45 s at 0.75×) are cut to that
length, with the middle removed. Leading silence becomes 30 ms. The trailing silence is 220 ms when another sentence follows
(the director's paragraph gap, up to 700 ms on the model server) and 50 ms on the last one. Steer's word timings are
remapped through the same cut (`X-TTS-Words` stays in sync with the audio).

**3. Master (`loudness.master`):**
- ITU-R BS.1770-4 integrated loudness (K-weighting applied in the frequency domain, 400 ms gated blocks; a 997 Hz
  0 dBFS sine reads −3.01 LUFS, and it matches ffmpeg `ebur128` to 0.1 LU).
- Gain to **−14 LUFS**. Storm, warning and failure lines (`steering.ALARM_SITUATIONS`) get **−12 LUFS**.
- The Settings `volume` adds 20·log10(volume) dB: up to +6 dB, down to −30.
- A **look-ahead peak limiter** with a 5 ms look-ahead and 5 ms attack ramp, a 10 ms hold and a 5 ms release ramp:
  the gain is never a step and never hard-clips. The sample ceiling is −1.5 dBFS. The true peak (4× oversampled) is
  then checked against **−1 dBTP**.
- Limiting costs a little loudness, so the gain is re-measured and topped up (up to 4 passes, ±0.2 LU).

Low male voices have a high crest factor: Crater, `voice_1207`, has an 18 dB peak-to-loudness ratio. They need the
most limiting and land at −14.3 instead of −14.1.

The result is cached as it is sent, and the cache key carries `MASTER_VERSION` (2), so no pre-calibration rendering is
replayed. The `X-TTS-Loudness: <LUFS> LUFS <TP> dBTP` header reports each miss. Cost: 10–30 ms of numpy per render on
a cache miss. Deepgram (MP3) and the browser voice are not mastered.

**Crew audio:** the NASA clips measure −25.7 to −7.2 LUFS, and their sources already peak at +1.4 to +2.3 dBTP.
`tools/clip_loudness.py` (ffmpeg, dev only) writes `data/clip_loudness.json`, and `/api/clips` and `/api/clips/{id}`
return `gain_db` (= −14 − clip LUFS, from −6.8 to +11.7 dB). The client must play crew audio through a `GainNode` at that
gain, then a `DynamicsCompressorNode` used as a limiter (threshold −1, knee 0, ratio 20, attack 0.003, release 0.05).
That way, switching between crew audio and our voices doesn't jump. 30 of 74 clips need a boost; the rest are a plain
cut. No normalised copy is shipped: the 525 MB of media would double.

**Master volume:** UI 100% is the −14 LUFS target, and anything above 100% must go through the `volume` pref, not
client gain. The client's own `audio.volume` for the guide should stay at 1.

Tests: `tests/test_loudness.py` covers the reference tone; target ±1 LU at four input levels; no sample over the
ceiling; a smooth limiter gain; the alarm and volume offsets; every persona through `/api/tts` at the target and cached
as mastered; the gap cap with remapped word timings; the faster default rate; slow lines kept slow; and the crew-clip
gains.

## 5. Measured (build Mac, macOS 26.2, M-series, warm, cache miss, per sentence)

| voice | first audio (1-sentence render) | 3 sentences, each | words/s at 1× |
| --- | --- | --- | --- |
| Your Mac's system voice (Siri) | 1.28 s | 1.3–1.6 s | ~3.4 |
| Tara (Premium) | 0.80 s | 0.8–1.0 s | ~3.7 |
| cache hit (any) | ~1 ms | | |

## 6. Run it

```bash
cd model_server && uv run uvicorn app.main:app --port 8200          # OS_TTS=on by default
curl -s localhost:8200/health | jq .models.tts
curl -s localhost:8200/v1/tts/voices | jq '.roles, [.voices[] | {id, desc}]'
curl -s localhost:8200/v1/tts -H 'content-type: application/json' -d '{"text":"Copy, commander.","voice":"capcom"}' -D - -o /tmp/l.wav
```

## 7. Gaps

- No per-word emphasis, pitch or loudness steering on the OS voices (markup stripped; tag / f0 / loud ignored).
- macOS word timings are estimates (good at phrase breaks, approximate inside a phrase); Windows has real ones.
- The Siri system voice is ~1.5× slower to render than a premium voice; the next follow-up is a pre-rendered voice pack
  for the fixed lines (`tts_os.PACK_LOOKUP`).
