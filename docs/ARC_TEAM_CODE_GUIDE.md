# Code guide for the Arc team

This guide is for reading the Ask the Moon code to see exactly where and how Arc Transcriber and Arc Tagger are called,
what we do with their outputs, and where new capabilities (lunar domain, list context, multi-stream) would plug in.

Read with:
- [`ARC_SPACE_DATA_PLAN.md`](ARC_SPACE_DATA_PLAN.md): vocabulary, tags, synthetic data, list-context fine-tuning.
- [`ARC_MULTISTREAM_PLAN.md`](ARC_MULTISTREAM_PLAN.md): telemetry + audio, masking, what we pass.
- [`STREAMS.md`](STREAMS.md): what is wired today.
- [`MISSION_CONTRACT.md`](MISSION_CONTRACT.md): game state and commands.
- [`CONTRACT.md`](CONTRACT.md): `/api/ask`.

## 1. Three processes

```
browser (frontend/, Vite :5173)
   │  mic PCM16 16 kHz ──► /ws/listen        text ──► POST /api/ask        game ──► /api/mission/*
   ▼
backend/ (FastAPI :8100)  ── app logic: Director, gazetteer, moments, claim check, mission
   │  words+audio ──► Deepgram Flux (cloud ear, for now)
   │  audio + words + context ──► model_server WS /v1/stream          (Arc v1.1 Mini metadata)
   │  text ──► model_server POST /v1/tag                               (Arc Tagger v0.3)
   ▼
model_server/ (FastAPI :8200) ── the ONLY process that loads weights; Head Start can share it (MODELS=host)
```

Run: `make setup && make data && make dev`, then open http://localhost:5173. Tests: `make test`. Health: `make health`.

## 2. Where Arc is called

| Arc model | Called from | How | Code |
| --- | --- | --- | --- |
| **Arc Tagger v0.3** (native int8 C lib via ctypes) | model server | A pool of handles per domain (`assistant`, `news`, `talk`); one handle per request, reset after | `model_server/app/arctag.py` (`ArcTagger`), `model_server/app/main.py` (`POST /v1/tag`) |
| Arc Tagger, streaming | model server | One handle per WebSocket; push / poll / endpoint / revision semantics, the same as Head Start | `model_server/app/tag_stream.py` (`WS /v1/tag/stream`) |
| **Arc v1.1 Mini** (audio metadata, external transcript, decoder not loaded) | model server | File: `predict(wav, words, domain, events="all")`. Live: `MetaStream` fed PCM + Deepgram words | `model_server/app/arcmeta.py` (`predict`, `MetaStream`, `awe_score`), `model_server/app/routes_meta.py` (`POST /v1/meta`, `WS /v1/stream`) |
| Context into Arc | model server | `{"t":"context"}` on `/v1/stream` → `names` go to `Stream.set_names()`; terms, mission state and telemetry are recorded, not used by Arc yet | `model_server/app/stream_context.py`; details in `STREAMS.md` |
| Arc Tagger from the app | backend | Every kid question → `POST /v1/tag` (domain `assistant`); fails open | `backend/app/models_client.py` (`tag`) |
| Arc Tagger, offline | backend pipeline | Every crew clip's words → `/v1/tag` (domain `news`) | `backend/pipeline/build_index.py` |
| Arc v1.1, offline | backend pipeline | Every clip → `/v1/meta` → awe per utterance | `backend/pipeline/build_audio_meta.py` |

## 3. What we use from Arc's output, and what we ignore

| Arc output | Used? | Where | Why |
| --- | --- | --- | --- |
| Entity spans (text, start/end) | **Yes** | `readout.summarize` → `director._link`; `build_index.py` | Mention detection is good; we link every span to our gazetteer with rapidfuzz |
| Entity span **type** (person/org/place) | **No** for lunar names | `gazetteer.link` ignores it | 75% of lunar names come back as `person` (`ARC_SPACE_DATA_PLAN.md` §2) |
| Number spans | Yes | `claims.numbers_in` (fact check), `mission/nlu._number` (command amounts), index NUMBER tags | Claim check and "move **20** percent" |
| PII spans | Yes, with an override | `director._hard_pii` / `_benign_pii` | Arc tags "Moon" in "Apollo 16 Moon buggy" as a street address, so spans that name a known place or hardware item are allowed through |
| Acts (question, command_request, statement) | Yes | `readout.summarize` → Director | Routing; shown in the UI read-out line |
| Intents | Weakly | Director | Fine intents misfire on kid space questions (Head Start saw the same) |
| `command_complete` event | Yes | `/ws/listen` → UI | When to answer |
| `device_directed` | Yes, mission mode | `director._mission_turn` | Under 0.5 with no command → `action:"none"` (ignore chatter) |
| Utterance ends, `speaker.change`, `turn_yield` | Yes | `moments._segments` / `cut_clip` | Cut crew audio into 8–25 s moments on sentence boundaries |
| `safety.pii.request` (utterance) | No | — | Fires on ordinary questions |
| Audio events (laughter, cheer, applause), bio events | Yes, offline | `arcmeta.awe_score` | Awe per moment. Laughter fires near-constantly on radio, so we subtract each clip's median |
| `affect.emotion.*` | Not available | — | Never emitted by Arc v1.1 Mini; emotion is off |
| Speakers / roles (Arc) | Not yet | — | Deepgram diarization is used instead (it also undercounts) |
| `names` link records | Not yet | — | `MetaStream` doesn't emit them (`STREAMS.md`) |

## 4. One live turn, step by step

1. **Browser** (`frontend/src/voice.js`, `listen.js`): the mic is always on after the first gesture; hold Space to address
   the guide. It sends PCM16 80 ms frames on `/ws/listen`, plus a `{"t":"context", mission, names, terms}` frame in mission
   mode.
2. **Backend `/ws/listen`** (`backend/app/listen.py`):
   - tees the audio to Deepgram Flux (words, turn events; keyterms from `keyterms.py`) and to model server `/v1/stream`
     (Arc metadata + context);
   - relays `words`, `turn`, `arc`, `emotion` and `context_ack` back to the browser.
3. **Turn end:** the browser calls `POST /api/ask {text, context}`.
4. **`/api/ask`** (`backend/app/main.py`): `models_client.tag(text)` → Arc Tagger → `readout.summarize` (acts, mentions,
   numbers, PII, `pii_spans`, complete).
5. **Director** (`backend/app/director.py`, `direct()`), in order:
   1. privacy guard;
   2. mission turn (`_mission_turn` → `mission/nlu.understand` → sim → `mission/capcom`);
   3. misconceptions;
   4. glossary;
   5. tours (`_tour`);
   6. place/hardware linking (`_link`: alias, then a fuzzy link of Arc mentions; an ambiguous match returns `ask`);
   7. crew moments (`moments.MomentIndex.best_moment`);
   8. claim-checked guide line (`claims.guide_line`: LLM draft → Arc Tagger re-reads it → numbers ±10% and places must
      match `facts.json`);
   9. the LLM fallback.
6. **Response actions:** `fly`, `play`, `tour`, `ask`, `guard`, `say`, `view`, plus mission `command`, `status`,
   `houston` and `none`. The browser renders the card, speaks, and plays the moment with a hard-word pause.

## 5. Mission (game) code

| Piece | File | Notes |
| --- | --- | --- |
| Command understanding | `backend/app/mission/nlu.py` (`parse`, `understand`, `valid`) | Rules first (synonyms, amounts, compound, negation, conditionals, confirm/cancel, Arc number spans); LLM fallback must return schema-valid JSON |
| CAPCOM lines | `backend/app/mission/capcom.py` (`readback`, `status`, `houston`, `role_check`) | Real 2.6 s Moon round trip; units explained once |
| Simulation + API | `backend/app/mission/sim.py`, `routes.py`, `registry.py` | Deterministic per seed; real Sun/Earth (JPL Horizons) and solar events (DONKI / NOAA) cached in `backend/data/mission/` |
| Game UI | `frontend/src/mission/ui.js`, `client.js`, `mock.js` | Falls back to a labelled mock when the API is missing |

## 6. Where new Arc capabilities plug in

| New capability (from the plans) | App change needed | File |
| --- | --- | --- |
| `entity.mention.lunar_feature` / `spacecraft` / `mission` types | Trust the type and skip the fuzzy relink when confident | `director._link`, `build_index.py` |
| Native list API with per-span link output | Pass the gazetteer subset in view and read back link + score instead of rapidfuzz | `listen.py` (context), `models_client.tag`, `director._link` |
| `geo.term` / `geo.direction` / `geo.relation` | Replace the rule lists; relation → resolver for missions | `build_index.py` RULES, `moments.cut_clip` jargon |
| Mission command intents + slots | Replace or seed `mission/nlu.parse`; keep `valid()` as the schema gate | `mission/nlu.py` |
| Emotion / awe / urgency | Already consumed if emitted (`context.emotion`, `arcmeta.awe_score`) | `listen.py`, `director._tone` |
| Multi-stream (telemetry tokens) | Send `{"t":"telemetry"}` / `{"t":"event"}` on `/v1/stream` (the schema is in `ARC_MULTISTREAM_PLAN.md` §9); read new outputs (referent, command) | `listen.py`, `model_server/app/stream_context.py`, `routes_meta.py` |
| On-device ear (Arc Transcriber Edge) | Replace Deepgram Flux in `listen.py`; keep the same `words` / `turn` messages | `listen.py` |

## 7. Data the code reads

- **Places and hardware:**
  - `backend/data/places.json`: lunar features + kid aliases;
  - `artifacts.json`: 36 hardware items with sources;
  - `facts.json`: the fact sheet for the claim check;
  - `glossary.json`: kid explanations of hard words.
- **Crew audio and index:**
  - `backend/data/clips_manifest.json`: 74 NASA clips;
  - `transcripts_dg/`: Deepgram words with speakers;
  - `index/clips.json`: words + Arc tags + utterances;
  - `index/audio_meta.json`: Arc v1.1 awe.
- **Mission:** `backend/data/mission/` (sites, ephemerides, solar events, radiation numbers, each with source URLs).
- **NASA media** (gitignored): `backend/data/media/`, fetched with `make data`.
