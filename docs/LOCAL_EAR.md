# Local ear: Arc v1.1 Mini

Arc is the ear by default (`EAR=arc`). One local model gives the words, the turns and the metadata. Deepgram Flux
(cloud) remains available as an option (`EAR=deepgram`) and as the fallback when the Arc ear is down or full and a key exists.

## Architecture

```
browser mic ──PCM16 80 ms──▶ backend /ws/listen ──▶ model server WS /v1/stream?ear=arc
                               │  1st frame: {"t":"context","names":Tier A (74)}
                               │  client context: its names first, then Tier A
                               ◀── words / turn / arc / emotion / context_ack (relayed unchanged; posted to the session)
```

- **Model server** (`model_server/app/arc_ear.py`, `routes_meta.py`): `ARC_EAR=on` (the default) loads Arc's decoder
  next to the heads (one load, shared weights). Each connection gets its own `arc.stream(transcript="builtin")`.
  - `TurnTracker` maps Arc's partials and finals, plus `command_complete` and an adaptive energy VAD, onto the browser's turn contract:
    - `start`: on the first non-empty partial;
    - `eager`: after ≥ 0.25 s of silence with command_complete p ≥ 0.5;
    - `resumed`: voice again after eager;
    - `end`: when Arc's pause rule closes the utterance (segmenter pause_s 0.5 / short_pause_s 0.6), or after 0.5 s of silence, which calls `Stream.end_turn()`.
  - Words are in written form (digits).
  - Finals use Arc's own `transcript_written` (names linked to the list's spelling).
  - The admission cap is shared with metadata mode (`META_MAX_SESSIONS`).
  - When the ear can't be served, the server replies `{"t":"ear","available":false,"reason"}` and closes with code 1013.
- **Backend** (`backend/app/listen.py`):
  - `EAR=arc|deepgram` (default `arc`).
  - With arc, a handshake waits for `{"t":"ear","available":true}`, with a 2 s timeout.
  - On failure: Flux if `DEEPGRAM_API_KEY` is set (the client gets an info message `{"t":"ear","ear":"deepgram","fallback":…}`); otherwise `error`, and the browser uses Web Speech push-to-talk.
- **Context** (`stream_context.py`):
  - In ear mode, names, terms and topic go to `Stream.set_context`, which feeds the decoder prompt. The prompt's list slot is about 40 tokens, so it takes the first ~10–12 names.
  - When names arrive before any audio (the backend's Tier A frame), the Arc stream is reopened with `names=`. Only that path builds the decoder's name-bias trie and the name-list snap.
- **/health** `models.arc_ear`: `decoder_loaded`, `load_s`, `rss_after_load_mb`, `rss_load_delta_mb`, `rss_now_mb`.

## Eval (`backend/tests/fixtures/ear_eval/`)

- **Test set:** 40 kid-style commands and questions (`set.json`): mission commands with numbers, lunar names, Academy answers, hardware, crew and glossary words.
- **Audio:**
  - Rendered locally with Steer TTS edge (`render.py`): 2 voices per item from 8 voices (4 high-pitched with f0 +2 st, 4 mid), 80 clips.
  - Every other clip has classroom-like noise: babble from 3 other clips plus pink noise, at 10–14 dB SNR.
  - The audio is gitignored; run `render.py` to rebuild it.
- **Arc:** `eval_arc.py`, in process, through `EarStream` (the same turn logic as the socket).
- **Flux:** `eval_flux.py`, reference only, streamed at real-time pace with the backend's keyterms.
- **Scoring** (`score.py`):
  - WER is computed after lowercasing, removing punctuation, and converting number words to digits.
  - Names count as correct only when the exact phrase appears.
  - Numbers count as correct when the digit token appears.

| ear (80 clips) | WER all | WER clean | WER noisy | names | numbers | endpoint p50 / p90 | RTF |
|---|---|---|---|---|---|---|---|
| Arc, no context | 0.273 | 0.109 | 0.437 | 24/46 (52%) | 23/24 | 880 / 1840 ms | 0.31 |
| **Arc + Tier A context** (default) | **0.262** | **0.087** | 0.437 | **28/46 (61%)** | 23/24 | 884 / 1654 ms | 0.32 |
| Arc + mission frame + Tier A | 0.268 | 0.098 | 0.437 | 28/46 (61%) | 23/24 | 874 / 1698 ms | 0.32 |
| Deepgram Flux + keyterms (reference, cloud) | 0.210 | 0.104 | 0.317 | 31/46 (67%) | 20/24 | 1038 / 1587 ms¹ | n/a |

¹ Flux didn't end the turn on 16 of 80 clips within 2.5 s of trailing audio. Arc ended every turn.

Results are in `results_arc_final.json` (no-context row), `results_arc_ctx_bias.json` (context rows) and `results_flux.json`.

- **Endpoint latency:**
  - Measured as the audio time of `turn end` minus the speech end in the TTS waveform, plus the wall time of the end_turn decode.
  - With a 0.6 s end silence the p50 was 958 ms; 0.5 s gives 880 ms. Clean clips are about 0.8 s and noisy ones about 1.4 s, because babble keeps the VAD voiced.
  - A sweep to 0.45 s end silence with a 10 dB VAD margin cut the p50 to 689 ms, but noisy WER went to 1.46: the babble was cut into extra turns. So the default stays at 0.5 s and 6 dB.
- **Context:**
  - Before the fix, context only reached the decoder prompt and the linker, and gave +2 names with clean WER 0.109 → 0.098.
  - Reopening the stream with `names=` (the bias trie plus snap) gives +4 names (52% → 61%) and clean WER 0.109 → 0.087.
  - Fixed examples: Vavilov, Cabeus, Malapert ("Malapart" before).
- **Numbers:** Arc gets 23/24 (it prints digits), better than Flux at 20/24.
- **Memory and speed:**
  - Loading the decoder takes the process from about 300 MB to about 790 MB RSS, and the load takes 5–23 s (cold cache).
  - Live CPU RTF is about 0.3 on 4 threads.

## Contextual biasing (round 7): the screen's hot lists

We know the vocabulary of every screen. The ear gets rich lists of it, weighted by context:

- **Building the lists.** `backend/app/hotlist.py` builds them from the app's JSON (places, artifacts, glossary, the
  course, the sites, the call signs and the router's nav / offer / help phrases). The result is versioned as data in
  `backend/data/ear_vocab.json`: run `python -m app.hotlist build` in `backend/`, and `tests/test_hotlist.py` fails if
  the file is out of date. `build_python.py` bundles the file in the Mac and Windows apps.
- **The tiers**, sent per screen (`Session.hot_words`):
  - `step`, the strongest boost: what the open step, offer or screen action expects. That is the step's options and
    say words, keywords, places, side / day-night words, the base parts of a command step and the space word; the
    offer's takers; the cabin's orders and panels; the site names on the picker; the call signs.
  - `names`, a strong boost on the Moon screens (map, patch, library, lesson done) and the picker: every place, crew
    member and piece of hardware.
  - `screen`, a light boost: the rest of the screen's vocabulary (glossary, the lesson's words, nav and help).
  - Function words, fillers and gazetteer misspelling aliases are never in a bias list.
- **Delivery.** `/ws/listen` checks the session's screen every 0.25 s and sends `{"t":"context","hot":{...}}` when the
  lists change (`EAR_HOT=1`).
- **In the ear** (`model_server/app/hotbias.py`, pure Python, no native code):
  1. The step list goes first in the decoder prompt.
  2. A token prefix-tree boost per tier (shallow fusion; phrases that start with a function word get no start bonus).
  3. The final 4 beams are rescored: + per hot phrase. An alternative must be within 0.6 of the top beam and the same
     length ±1 word, so a hot word replaces heard words and never rides in on an extra tail.
  - Weights: `EAR_HOT_STEP_START/CONT` 1.0 / 2.0, `EAR_HOT_NAMES_*` 1.0 / 2.0, `EAR_HOT_SCREEN_*` 0.3 / 1.2,
    `EAR_NBEST_*`.
- **On the final `words` message.** `alts` (the other beams), `conf` (mean token probability) and `hot` (the matched
  tier and its hits) ride along. The Director reads them as the `ear_*` / `hot_*` features.

Eval: `director_model/ear_hot_eval.py`. Every clip is rendered in memory with held-out kid-style Steer voices (half with
babble) and decoded twice (Tier A only vs + the hot lists). Results are in `director_model/RESULTS.md`, round 7.

## Gaps

- **Synthetic voices.** All voices are synthetic TTS, high-pitched but not real children. No real kid recordings were used, and nothing was spoken into the browser mic.
- **Names Arc still misses.** "Orientale" comes out as "oriental", "de Gerlache" as "Digo Laki", "Tycho" as "tiger", "regolith" as "regular life", and "Koch" is missed.
  - The decoder prompt only holds ~40 tokens of the list.
  - The name snap and linker don't fire on finals forced by our silence `end_turn()`. They link on Arc's own pause finals, but the linker's records arrive after `end_turn` returns.
  - A per-screen short list put first in the context frame is the cheapest next step.
- **Babble.** Arc transcribes background babble, with hallucinated tails like "…in the world". Noisy WER is 0.44 against 0.32 for Flux.
- **Late context frames.** Names that arrive after audio has started go to the decoder prompt and the linker only; the bias trie is swapped best effort.
- **Mid-session drops.** If the Arc ear drops mid-session, the client gets `error` (no live switch to Flux).
