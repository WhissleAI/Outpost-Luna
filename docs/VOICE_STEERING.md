# Voice steering: Steer TTS Edge, steered by the Director

Every spoken line in Outpost Luna (Academy, Mission and the Moon library) is rendered by **Steer TTS Edge**,
Whissle's own on-device TTS. The Director picks *how* each line is said, not only *what* is said: a style tag, numeric
prosody controls, emphasis on key words, and Steer's performance director for multi-sentence lines.

## 1. The engine

| | |
| --- | --- |
| Model | `WhissleAI/steer-tts-edge` (int4 acoustic model + int4 vocoder, ~12 MB, ONNX Runtime CPU, 24 kHz mono) |
| Package | `steertts-edge` (`OnnxTTS`, `Director`): a path dependency on `../../steer-tts/edge` in `model_server/pyproject.toml`. Elsewhere: `uv add "steertts-edge[hub] @ git+https://github.com/WhissleAI/steer-tts#subdirectory=edge"` |
| Where it loads | **only in the model server** (`model_server/app/tts_steer.py`), at startup, behind `STEER_TTS=on\|off` |
| Model files | `STEER_TTS_MODEL` (default: the Hugging Face cache snapshot, `hf download WhissleAI/steer-tts-edge`) |
| Director | `STEER_DIRECTOR` (default: `director.bin` next to the model, else `steer-tts/c/models/steer-tts-edge/director.bin`). It must be **format 2** (what `steertts_edge.Director` reads). The format-3 files shipped in the Steer apps fail with "unsupported director model version"; the server then runs without plans and says so in `/health` |
| Threads | `STEER_THREADS` (default 2) |
| Health | `GET /health` → `models.steer_tts: {loaded, error, director, director_error, voices, load_s, rss_added_mb}` |

`POST /v1/tts` on the model server:

```json
{"text": "Copy, commander. Shields to *40* percent.", "voice": "voice_0213", "tag": "confidence",
 "controls": {"rate": 0.3}, "guidance": null, "markup": true,
 "perform": {"genre": "children", "strength": 0.7, "para_index": 0, "para_len": 3, "next": "That leaves less for life support."}}
```

→ `audio/wav` (16-bit PCM; WAV because the browser decodes it with no codec delay and no extra dependency). Headers:
`X-Steer-Voice`, `X-Steer-Tag`, `X-Steer-Ctrl` (the controls actually used), `X-Steer-Ms`, `X-Steer-RTF`,
`X-Steer-Pause-Ms`. `GET /v1/tts/voices` lists the 200 voices, 51 tags, 12 controls and the director's genres.

**The performance director.** For multi-sentence text, `director.bin` plans every sentence (rate, loudness, pitch level,
pitch range, ending, pause) for the `children` genre. Because the floor plays one sentence at a time, the client sends
each sentence's place (`i`, `n`, `next`), and the model server plans that sentence in context and appends the planned
pause (capped at 700 ms) when another sentence follows. The plan fills only the controls the style did not name:
**explicit controls win per key** (as Steer's own `--perform --ctrl`), so a storm alert stays fast and loud whatever
the plan says, while the plan still shapes pitch, range and endings across the sentences.

**Sentence streaming.** Not as a chunked HTTP response: the floor already splits text into sentences and prefetches
the next one while the current one plays, so per-sentence calls give the same time to first audio.

## 2. The fallback chain

`GET|POST /api/tts` (backend, `backend/app/tts.py`), `TTS_ENGINE=steer|deepgram` (default `steer`):

1. **Steer** (model server `/v1/tts`, timeout `TTS_TIMEOUT_S`=8 s) → `audio/wav`, `X-TTS-Engine: steer`.
2. **Deepgram Aura-2** (when `DEEPGRAM_API_KEY` is set) → `audio/mpeg`, `X-TTS-Engine: deepgram`, `X-TTS-Fallback`
   says why Steer was skipped. Aura can't steer: it gets the persona voice only.
3. **The browser voice**: 503 (no engine configured) or 502 (engines failed) with `{"fallback":"browser"}`; `floor.js`
   speaks with `speechSynthesis`, sentence by sentence.

The disk cache (`data/tts_cache/`) keys on engine + voice + text + the canonical JSON of the style + the sentence's
place, so a re-steered line never replays a stale rendering. The browser cache keys on the URL, which holds the style
too. `/api/tts?text=&voice=` keeps working: no style → the persona's default style.

## 3. Voices

Chosen from `voices.json` (200 voices with gender, pitch register, pace and median f0):

| Persona | Steer voice | Profile | Why |
| --- | --- | --- | --- |
| **guide** | `voice_0644` | female, mid register, average pace, 195 Hz | Warm and clear without being sing-song; average pace leaves room to slow down for explanations |
| **CAPCOM** | `voice_0213` | male, mid register, fast pace, 118 Hz | Crisp, confident mission control; naturally a bit faster, so readbacks sound like radio procedure |
| **story** | `voice_0602` | male, high register, slow pace, 196 Hz | The hardware speaking in first person must not sound like the guide or CAPCOM: a high male voice that takes its time |
| **houston** | `voice_0272` | male, low register, average pace, 109 Hz | "Houston here": a deeper, steadier voice from Earth, distinct from CAPCOM on the Moon |

Deepgram fallback: guide=`aura-2-thalia-en`, capcom/houston=`aura-2-orion-en`, story=`aura-2-iris-en`.

## 4. The steering policy (`backend/app/steering.py`)

`style_for(voice, text, situation, emotion, places)` → `style`. One table plus five rules; `tests/test_steering.py`
pins each row.

**Persona base** — guide `interest`; CAPCOM `confidence`, rate +0.3; story `nostalgia`, rate −0.5, f0_med +0.4;
houston `enunciated`, rate −0.2.

**Situations** (controls are z-scores against the voice's own neutral speech; tags alone are weak on Steer, so each row
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

1. **Kid affect** (Arc / emotion stream): frustrated → `sympathy`, confused → `serenity`, scared/anxious → `serenity`
   (all: rate −0.6…−0.7, pause +0.6…+0.8, softer); excited → `excited` (rate +0.4, f0_iqr +0.8), happy → `happiness`.
   Exceptions: an upset kid during an alarm keeps the alert's tag but loses the speed-up and loudness boost (rate −0.3,
   pause +0.5); good news stays good news, just slower; an excited kid doesn't hype a calm line (night, guard, retry).
2. **A question to the kid** (text ends with `?`) → f0_end ≥ +1.5 (rising).
3. **Emphasis**: in readbacks, alerts, failure, night and explanations, the first 3 distinct numbers; in any line, the
   place name when the Director resolved one. Sent as `style.emph`; the backend wraps them in Steer markup (`*40*`,
   `<emph>Mare Tranquillitatis</emph>`) just before rendering, so captions stay clean and sentence splitting is not
   affected.
4. **Safety**: never `anger`, `contempt`, `disgust`, `sarcasm`, `panic`, `disappointment` (nor `irritation`,
   `frustration`, `skeptical`, `bored`) toward a kid. A forbidden tag from any source (row, caller, client) becomes the
   persona's tag; the backend re-checks the client's style. Controls are clamped to ±2.5.
5. **Performance**: every style carries `perform: {genre: "children", strength: 0.7}` (§1).

**Where the Director picks the situation**

| Producer | Situation |
| --- | --- |
| `director.decisions_for` (session Director and `/api/ask`) | `steering.situation_for(r)`: guard, glossary → explain, play → awe, command → readback, status → storm_alert / night_low_power / readback; emotion from the turn context; the resolved place name for emphasis; `houston` action → houston voice |
| `Session.proactive` (sim events) | solar_storm → storm_warning / storm_alert, storm_end → all_clear (new say), comm_open, low_power → night_low_power (new calm say), failure, mission_complete |
| `Session.end_shift` | from the new state (storm / night low power / readback) |
| `Session._turn` alarm rewrite | re-steers the shortened line with the kid's emotion |
| Academy `/api/academy/attempt` | passed / retry / hint / missed / done, badge → `badge` |
| Client-written lines (`floor.js` callers) | lesson brief, badge award, hardware story send `{situation}` only; the backend resolves it through the same table |

## 4b. Accessibility steering: speed, the `vocab` situation, vocabulary emphasis, word timings

**Speaking pace preference.** The kid's caption-bar speed (0.75× / 1× / 1.25× / 1.5×, `a11y.js`, stored on the device
only) goes to `/api/tts?speed=`. `steering.speed_steer(speed)` maps it to two things:

| speed | `rate` offset (z, added on top of the Director's style, then clamped ±2.5) | Steer `pace` (global duration divisor) |
| --- | --- | --- |
| 0.75× | −0.83 | 0.85 |
| 1× | 0 | 1 |
| 1.25× | +0.64 | 1.13 |
| 1.5× | +1.17 | 1.25 |

`rate` keeps it an articulation change in the voice's own style (a storm alert stays faster than a calm line at every
speed); `pace` carries the rest, since rate z-scores saturate. The model server accepts `pace` (0.6–1.6) on `/v1/tts`
and reports it in `X-Steer-Pace`. Crew audio is a recording: it gets `playbackRate` (pitch preserved) instead.
Measured in Chrome: the same 10-word line took 3.86 s of caption time at 1× and 2.69 s at 1.5×.

**`vocab` situation** — `enunciated`, rate −1.0, pause +0.6, f0_iqr +0.3: slower, clear gaps, a little more melody,
for new words and younger kids. Used by every Space-words attempt reply that isn't a pass, by "Hear it" on a glossary
card, and by the vocab step buttons.

**Per-word vocabulary emphasis.** `style_for(..., vocab=[terms])` keeps the lesson's terms that occur in the line
(`style.vocab`, ≤ 3); `/api/tts` wraps each in `<slow><emph>term</emph></slow>` (×1.4 × 1.2 duration, +2.5 st, +4 dB on
just that word) before rendering (`steering.apply_markup`: vocab first, then the usual number/place emphasis). The
Academy attempt route adds the step's term to every vocab step reply.

**Word timings (real, not estimated).** `steertts_edge` has no aligner, but its duration predictor is the alignment:
`OnnxTTS.mel()` expands each phone into `dur` mel frames (`tok = repeat(arange(N), dur)`, HOP 256 @ 24 kHz) before the
decoder. `tts_steer.py` wraps the instance's `_dec`/`_render` to capture `tok` per segment (markup renders one segment
per style span), recovers per-phone frames with `bincount`, folds phones into words with `to_phonemes()`' word index,
and maps spoken words onto the display words (each display token takes as many spoken words as it normalises to:
"40" → "forty"; on a mismatch, proportional over the real start/end). The reply carries
`X-Steer-Words: startMs-endMs,…` per display word; `/api/tts` validates it, caches it next to the WAV (`.words`) and
returns it as `X-TTS-Words` (exposed for CORS). Deepgram and the browser voice have no timings: the caption bar
estimates from the audio length and syllables, or follows `speechSynthesis` boundary events.

## 5. Measured (M-series Mac, CPU, 2 threads, warm)

| | |
| --- | --- |
| Model + director load | 0.5 s |
| Render, short CAPCOM line (~2.6 s audio) | ~115 ms on the model server; RTF ≈ 0.033 |
| **Time to first audio**, short CAPCOM line, uncached, through the backend (`GET /api/tts` with style) | **median 139 ms** (128–147 ms, 8 lines) |
| Cache hit | < 1 ms |
| RSS: steertts_edge + onnxruntime import | +23 MB |
| RSS: model + director loaded | +72 MB (≈ 95 MB with the import) |
| RSS after 20 long renders | +186 MB over the import (activation arenas are off, but the allocator keeps some pages) |
| In the full model server (Arc Tagger + Arc Meta already loaded) | `/health` reported +19 MB at load |

**Listen-proxy check** (6 samples rendered through `/api/tts` with Director styles, measured with Steer's own
`steertts.measure` — raw units: rate phones/s, loud dB, f0 semitones, f0_end st/s):

| Sample | Style | rate | loud | f0_med | f0_iqr | f0_end |
| --- | --- | --- | --- | --- | --- | --- |
| calm (night, low power) | serenity, rate −0.5, loud −0.4 | 4.83 | −8.00 | 5.26 | 6.72 | −7.50 |
| alert (storm) | determined, rate +0.6, loud +0.8 | **5.53** | **−6.02** | 4.89 | 5.66 | −6.42 |
| explain | enunciated, rate −0.8 (guide) | 4.51 | −1.64 | 11.81 | 2.65 | −2.22 |
| badge | pride, loud +0.5, f0_iqr +1 | 5.31 | −8.12 | 8.22 | 8.32 | 10.92 |
| story | nostalgia, rate −0.5 (story voice) | 4.58 | −5.64 | 7.99 | 4.11 | 0.98 |
| question | f0_end +1.5 (guide) | 6.38 | −0.06 | 13.70 | 3.92 | **36.04** |

Same text, same voice: the alert is 14% faster and 2 dB louder than the calm line; the question ends with a strong
rise. Different voices aren't comparable on absolute loudness/pitch.

## 6. Run it

```bash
cd model_server && uv run uvicorn app.main:app --port 8200          # STEER_TTS=on by default
cd backend && uv run uvicorn app.main:app --port 8100                # TTS_ENGINE=steer by default
curl -s localhost:8200/health | jq .models.steer_tts
curl -so line.wav "localhost:8100/api/tts?voice=capcom&text=Copy,%20commander." -D - | grep -i x-tts
```

## 7. Gaps

- The Academy attempt API doesn't receive the kid's emotion yet (the turn path does), so Academy lines are steered by
  outcome, not affect.
- Client-written mission lines (mission start, debrief) use the persona default style.
- The director is calibrated for its paired voice; on the four persona voices its plans are approximate.
- The format-3 `director.bin` from the Steer apps needs a newer `steertts_edge` to load.
