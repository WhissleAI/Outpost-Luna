# Local ear: Arc Transcriber Space

The ear is **Arc Transcriber Space** (`WhissleAI/arc-transcriber-space`, folder `nft2/`, revision `176d324`, CC BY-NC 4.0)
on **libarc** (C, `desktop/vendor/libarc`) + ONNX Runtime. One model gives the words, the turns, the names linked to the
screen's list, sound events and a device-directed head. It replaced Arc v1.1 Mini on torch + transformers (and the
round-7 hot-list logits processor); the model server no longer depends on torch, transformers or arc_audio.
Deepgram Flux (cloud) stays an option (`EAR=deepgram`) and the fallback when the ear is down and a key exists.

## Architecture

```
browser mic ──PCM16 80 ms──▶ backend /ws/listen ──▶ model server WS /v1/stream?ear=arc  (app/arc_ear.py)
                               │  1st frame + every screen change: {"t":"context","names":[{name,kind,aliases}] <= 40}
                               ◀── turn / words / arc / context_ack (relayed unchanged; posted to the session)
model server: app/nft2.py (ctypes) ──▶ libarc (arc_nft2_*) ──▶ ONNX Runtime = the onnxruntime wheel's C library
```

- **Setup (dev):** `make desktop-libarc ear-model` (libarc for this OS; the model, ~460 MB, into
  `model_server/models/arc-space`). Env: `ARC_SPACE_DIR` (the `nft2/` folder), `ARC_LIB` (libarc), `ARC_THREADS` (4).
  The desktop app downloads both on first run (docs/DESKTOP.md "First run: assets").
- **libarc**: the upstream C code (arc_transcriber `c/`, commit bfffb19), built as one shared library with CMake
  (`libarc.dylib`; `arc.dll` with clang / mingw-w64: it needs C11 atomics and GCC builtins). It links no ONNX Runtime:
  `ort_loader.c` loads the onnxruntime wheel's `libonnxruntime.*.dylib` / `onnxruntime.dll` by path (C API 23, served
  by the wheel's 1.32), so the installer carries one ONNX Runtime. Local changes are listed in its NOTICE.
- **Turns** (`arc_ear.EarStream`): an energy VAD with an adaptive floor opens a segment (2 voiced 80 ms chunks, 0.3 s
  pre-roll); a partial decode (no events) runs every 0.3 s on the open segment (backing off to 1.25x its cost, first 8 s
  only; it was 0.5 s / 2x, which gave a 1.3 s command one partial and read as "no streaming") and the first non-empty partial is the turn `start`; 0.5 s of silence (or `end_turn` / `stop`, or 15 s) closes
  it with one full decode. Order: `turn start`, `arc`, `words final`, `turn end` (a client resets its per-turn read on
  `start`). A segment with no words is not a turn; its `arc` message still carries the sound events (`speech:false`,
  no device-directed read).
- **Final words**: `text` = written form (digits, "40%") with every LINKED name in the list's spelling ("artemis two"
  -> "Artemis II"); `spoken` = the model's spoken form; `names` = `[{heard, entity, state, p, tag, kind}]`.
- **Routing on names** (`director._link`): `linked` -> that place (`ear_link`); `abstain` -> the gazetteer's candidates
  for `heard`, asked as "did you mean A or B?"; `not_in_list` -> `heard` searched in the whole gazetteer. The router
  and the Academy grader see the text with the canonical names, so "go to Mare Tranquillitatis" and lesson answers
  that are place names work on the text too.
- **Names lists** (`backend/app/names_list.py`): a catalogue from places.json, artifacts.json, mission/sites.json and
  the crew lists, every entry with a `kind` and aliases for what is not said as written (Roman numerals "Artemis II"
  -> "Artemis 2" / "Artemis two"; Latin and English "Sea of Tranquility" + "Mare Tranquillitatis"; "LCROSS" -> "L
  cross"; "S-IVB" -> "S 4 B"; "ALSEP" -> "al sep"; parenthesised names; ASCII spellings). `screen_names(frame, step,
  last_place)` picks <= 40, most relevant first: the open step's options / places, the place being looked at, then
  the screen's world (Moon screens: the gazetteer, the Artemis II crew and craft, sites, hardware; cabin / brief /
  debrief: the mission sites, Houston, CAPCOM, crew; lessons: the step's names, then places). `session.ear_names()`
  builds it; `/ws/listen` sends it at the start and whenever it changes (it takes effect from the next decode).
- **device_directed**: the model's directed head is conservative (real device commands from SLURP: 32% >= 0.5, 67%
  >= 0.05; crew talk 11% of clips >= 0.05). The ear maps it onto the router's scale (`app_dd`: head 0.05 -> 0.5 =
  `DD_MIN`, 0.5 -> 0.7 = `DD_STRONG`; `EAR_DD_KNEE`, `EAR_DD_STRONG_AT`) and also sends the raw `directed_head`.
  **Calibrate on real kids' sessions** before trusting the not-directed gate.
- **Safety stays with Arc Tagger.** The model's tags.json lists `safety.profanity.*` / `safety.pii.*` (word level) and
  `safety.toxicity.*` (not for the `assistant` domain), but libarc's result surfaces no safety read and there are no
  `child.*` care tags: profanity / toxicity / care keep coming from Arc Tagger (`app/safety.py`).
- **Echo**: the model is trained to ignore synthetic (Kokoro-style) TTS, but the app's own voices ARE transcribed when
  they reach the mic (Nora voice pack 30/30, macOS OS voice 10/10 clean clips). The router's echo check
  (`turn_router.echo_of` against the lines we just spoke) stays the defence.
- **/health** `models.arc_ear`: `available`, `model`, `revision`, `backend` (`onnxruntime 1.32.0`), `load_s`,
  `rss_after_load_mb`, `rss_now_mb`.

## Old ear vs new ear (`model_server/tools/ear_compare.py`, real audio only)

Same clips, fed in 80 ms chunks, 1.5 s of silence after each; one model in memory at a time; Mac (arm64), 4 threads,
on a heavily loaded machine (load average 40-160), so absolute latencies are pessimistic and noisy.

| | Arc v1.1 Mini (torch) | Arc Transcriber Space (libarc) |
|---|---|---|
| WER, LibriSpeech test-clean (40 utts, human refs) | 5.2% | **2.2%** |
| WER, SLURP commands to a device (60, headset + far-field, human refs) | 47.1% | **19.3%** |
| WER, Artemis II crew audio (45 segments; ref = Deepgram nova-3, a machine ref) | 26.8% | **15.4%** |
| Name links, crew segments (34 names said; list = said + 20 decoys) | 64.7% correct, 35.3% missed, 2 extra | **97.1% correct**, 0% abstain, 2.9% missed, 3 extra links |
| Room noise (16 real beds: cabin, cafe, room; -30 dBFS): false turns | 16/16 | **1/16** |
| Room noise: false device-directed (>= 0.5) | 3/16 | **1/16** (after the wordless-segment gate) |
| Device-directed >= 0.5 on SLURP (real device commands) | 98.3% | 63.3% (mapped; raw head 31.7%) |
| Device-directed >= 0.5 on crew talk (not to a device) | 97.8% | **2.2%** |
| Echo: Nora voice pack / OS voice clips transcribed | 30/30, 10/10 | 30/30, 10/10 |
| Turn end (VAD speech end -> final), p50 / p90 | 1276 / 2187 ms | **1105 / 2087 ms** (847 / 953 ms on a rerun) |
| First words (onset -> first partial), p50 / p90 | **739 / 854 ms** | 1059 / 1673 ms |
| Real-time factor (compute / audio, with partials) | 1.13 | **0.50** |
| Load time | 6.0 s | 5.6 s (0.9-3.3 s warm) |
| RSS after load / peak (whole process) | 939 / 1075 MB | 955 / 985 MB |

Notes: the old ear's name check is text-based (the list's name or alias in its words); the new one is the model's own
link (`entity`). The first partial comes later than before (a whole-segment decode every 0.5 s instead of streaming
partials): a 2-word barge-in is heard ~0.3 s later. The torch-free model server also drops ~440 MB of site-packages
(torch 379 MB, transformers 59 MB) from the installer.

# History: Arc v1.1 Mini (replaced)



Arc is the ear by default (`EAR=arc`). One local model gives the words, the turns and the metadata. Deepgram Flux
(cloud) remains available as an option (`EAR=deepgram`) and as the fallback when the Arc ear is down or full and a key exists.

## Architecture (Arc v1.1 Mini)

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

## Partial-span links (0.3.0 fix)

The linker sometimes links ONE word of a two-word list name. Before the fix, `display_text` swapped just that word:
"show me the south pole" read "Show me the South **North Pole**" and routed north (16/16 test clips: "Pole" ->
"North Pole", p 0.72-0.99), and "Artemis two" read "Artemis II two". `arc_ear.guard_names` now looks at the word
next to the linked span: if it IS the rest of the name (numerals, Roman numerals and number words count as equal) the
link is widened over it ("Artemis II"); if it CONTRADICTS the rest ("South" for "North") the link becomes `abstain`
and the director routes on the text. The names list also has a "South Pole" entry of its own (`names_list.py`): the
linker does not link aliases, and "south pole" was only an alias of Shackleton. Measured on 46 clips (4 + 2 `say`
voices): every South Pole phrase links "South Pole" (p 1.0), North Pole stays north, "Artemis two" -> "Artemis II".

## Gaps

- **Synthetic voices.** All voices are synthetic TTS, high-pitched but not real children. No real kid recordings were used, and nothing was spoken into the browser mic.
- **Names Arc still misses.** "Orientale" comes out as "oriental", "de Gerlache" as "Digo Laki", "Tycho" as "tiger", "regolith" as "regular life", and "Koch" is missed.
  - The decoder prompt only holds ~40 tokens of the list.
  - The name snap and linker don't fire on finals forced by our silence `end_turn()`. They link on Arc's own pause finals, but the linker's records arrive after `end_turn` returns.
  - A per-screen short list put first in the context frame is the cheapest next step.
- **Babble.** Arc transcribes background babble, with hallucinated tails like "…in the world". Noisy WER is 0.44 against 0.32 for Flux.
- **Late context frames.** Names that arrive after audio has started go to the decoder prompt and the linker only; the bias trie is swapped best effort.
- **Mid-session drops.** If the Arc ear drops mid-session, the client gets `error` (no live switch to Flux).
