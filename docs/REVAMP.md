# Ask the Moon v2: Arc-first revamp

Status: plan, 2026-11-13 (Space Apps is Nov 14–15). Nothing in this document is built yet.

## 1. Are we using Arc Tagger well?

No. v1 doesn't use it at all. `scripts/build_index.py` tags words with a 14-entry keyword list (`LEX`), and the live
app matches kid questions with `includes()` over hand-written aliases. Neither one knows about turns, corrections,
numbers, safety or timing, so the app answers on a button press and has no judgement about *what* to do.

So we ran the real tagger on our data first. This is Arc Tagger v0.3, native int8, through Head Start's binding;
the script is `scripts/probe_tagger.py` and the full output is `docs/tagger_probe_2026-11-13.txt`.

| What we checked | Result on our data | What it means for the design |
|---|---|---|
| Speed (batch, M3 Pro, 1 thread) | 0.08–0.11 ms per word; the 344 s clip took 121 ms | The whole 59-clip library tags in about a second, so re-tagging is free and can run on every build |
| Finding lunar names | Entity spans landed on 30 of 45 lunar-name occurrences in 4 clips: 12/12 in the Hertzsprung clip, 8/13 naming, 8/15 mare, 2/5 Aristarchus. Whisper's misspellings ("Oriental", "Orin Ta", "Hertzprung") were still picked up | Use it to **detect mentions**. It finds the words even when the ASR misspells them |
| Entity *types* on lunar names | Wrong almost every time: Vavilov = person, Ohm = person, Orientale = organization, Glushko = person | **Never trust the type.** Every mention must be linked against a lunar gazetteer. Head Start found the same thing (Mona Lisa = person) |
| False mentions | "Peltor", "Galveston", "albedo", "Middle", "-south" | The gazetteer link rejects these. "Pythagoras" is a real crater, so the linker will correctly keep it |
| Numbers | "five degrees", "400", "100%", "20 kilometers"; types are mixed (count vs measure) | Every number is a **claim to check** against the gazetteer or LRO facts |
| Structure | 134 utterances in the 5:44 mare clip, plus `speaker.change`, `discourse.turn_yield` and `content.story_start` events | Gives clean cut points: crew audio can be played as **moments** that start and end on a sentence, not mid-word |
| Kid questions (`assistant` domain) | 9/9 got the right act (question / command_request). `command_complete` fired on 8/10. "show me Tycho, wait no I mean Copernicus" kept only Copernicus. "my name is Maya and I live at 42 Oak Street" was caught as private_name + street_address | Use the tagger for **when to answer**, **corrections** and **child privacy** |
| Gaps | "the moon is made of cheese right" got no act. `safety.pii.request` fires on ordinary questions. Emotion is not in the text read-out | Misconceptions need a fact check. Ignore the pii.request head (Head Start does too). Awe has to come from **Arc audio** |

Bottom line: Arc Tagger should be the app's spine. It sees every word from Deepgram, both for the crew library
offline and the kid live. It tells us what was mentioned, what was claimed, where sentences and turns end, what
kind of request this is, and what must stay private. What it can't do (lunar types, spatial relations, awe) we add
with a gazetteer linker, a few rules, and Arc's audio metadata.

## 2. The idea in one line

**Ask the Moon v2 is a voice guide that knows when to talk and when to let the astronauts talk.** A kid asks. The
guide either answers in one short sentence, or says "listen to this" and plays the real Artemis II moment, or
both. During a crew clip it can pause after a hard word ("albedo means how bright it is") and resume. Everything
it says has been checked against a list of facts with sources.

## 3. Architecture

Two pipelines share one index: **offline** builds Moon Moments from the crew library, **live** answers the kid.
The pieces are taken from Head Start (`~/Desktop/work/whissle/headstart`) and Steer (`wt-arc-narrator`) wherever they
already exist.

```
OFFLINE (build once, ~2 min for the 59 clips)
NASA mp3 ─► Deepgram nova-3 batch ─► Arc Tagger ─────────► Linker ──────────► Moments ──────────► Fact sheet
 (59+)      words, times, speaker   (news/talk domain;     mention → IAU      cut on utterance/   claims per moment:
            keyterms = lunar names  eou at DG utterances)  gazetteer entry    speaker.change;     number / color /
       └──► Arc audio metadata ──────────────────────────────────────────────► awe, laughter,      relation, each
            (bio + audio events: gasps, laughter; speaker)                     jargon, kid-safe    verified|impression|
                                                                                                   contradicted
LIVE (per kid turn)
mic ─► Deepgram Flux ─► Arc Tagger stream ─► Frame ───────► Resolver ──────► Director ──► Speak (TTS)
       (keyterms;       act, intent,         place          gazetteer +      FLY / SAY /    Play crew moment
       Eager/End of     command_complete,    mentions,      moment search;   PLAY / ASK /   Fly the globe
       turn)            corrections, PII,    descriptors    Arc verify for   WAIT / PAUSE-  (barge-in ducks
                        numbers              ("yellow")     unsure names     EXPLAIN        audio)
                                                                  │
                                         LLM answer ◄─ fact sheet ┘ ─► Arc Tagger re-reads the answer
                                                                       ─► claim check ─► TTS
```

### 3.1 Words: Deepgram, with Arc as the backup

- **Crew library (batch):** Deepgram nova-3 pre-recorded with `diarize`, `smart_format`, `utterances`, and
  `keyterm` set to the lunar names from each clip's NASA title plus the top gazetteer names. That fixes Whisper's
  "Oriental" and "Orin Ta" at the source, and the diarization gives us *which astronaut* is speaking ("Christina
  saw…"), which a kid cares about.
- **Kid (live):** Deepgram Flux, already wired in Head Start (`server/ear.py`, `FluxEar`). It gives turn events
  plus `keyterm`. Head Start's measurements: WER 0.020 against Arc Mini's 0.123, and a soft answer 212 ms p50 after
  the last word with `EagerEndOfTurn`. With the Arc `command_complete` gate (`FLUX_SOFT=eager+arc`), premature
  answers drop from 26 to 11 per 100 for +18 ms. Kids pause mid-question a lot, so we ship the gated version.
- **Fallback:** if Deepgram fails, Arc is the ear, and the web build falls back to Web Speech. A Deepgram key is
  already in `headstart/.env`.

### 3.2 Linker: from "Oriental" to an IAU feature

The tagger finds the mention; the linker decides which place it is.

1. **Gazetteer:** about 9,000 IAU lunar features (name, type, lat, lon, diameter, origin of the name), plus aliases
   for kid words ("bullseye" → Orientale, "the yellow part" → Aristarchus Plateau, "where Neil landed" →
   Tranquility Base) and the spoken names Artemis II proposed (Integrity, Carroll).
2. **Candidates:** exact match, then fuzzy and phonetic (trigram + Double Metaphone) over names and aliases, taking
   the top 20. Steer's book search does the same over 80k titles (`NameIndex`).
3. **Context priors:** the clip's NASA title, other places in the same moment, near side vs far side. "Ohm" in a
   far-side clip is the crater, not the unit.
4. **Accept / ask / drop:** offline, low-confidence links go to a review list (a short list for 59 clips, fixable in
   an hour by hand). Live, see 3.5.

This is also where "a long list" belongs. Steer measured that biasing Arc with a whole 61k-title list barely helps
(74–76% right), while **verifying candidates against the audio** does: 80% → 84–88%, with 0 right answers made
wrong. The same pattern applies to 9,000 Moon names: let the ear hear freely, build candidates, then verify.

### 3.3 Moon Moments: crew audio a kid can actually use

A clip is 41 s to 5:44 long. A kid needs 8–25 seconds about one place. A Moment is:

```jsonc
{
  "id": "m-aristarchus-01", "clip": "art002a000005", "t0": 31.2, "t1": 48.9,
  "speaker": "Christina Koch",                                    // Deepgram diarization + name map; "crew" if unsure
  "places": [{"id": "aristarchus", "conf": 0.96}],
  "text": "…it is like a yellow snow-capped mountain…",
  "claims": [{"kind": "color", "text": "yellow", "place": "aristarchus", "status": "verified",
              "source": "LROC color map: Aristarchus Plateau pyroclastic deposits"}],
  "jargon": [{"word": "albedo", "t": 40.1, "explain": "how bright or dark a surface is"}],
  "awe": 0.82,                                                    // Arc audio: gasps, laughter, pitch + text AWE words
  "kid_safe": true                                                // tagger profanity/toxicity spans = none
}
```

- **Cut points** come from tagger utterance ends, `speaker.change` and `turn_yield`, snapped to Deepgram word
  times. Never start or stop mid-sentence.
- **Ranking** a moment for a place: it mentions the place (linked), all claims verified or labeled as the crew's
  impression, length 8–25 s, high awe, clean edges, speaker known.
- **Relations** ("halfway between Orientale and Ohm", "northwest of Glushko, same latitude as Ohm") are parsed
  with rules over the tagger's spans plus direction words for now (`midpoint`, `northwest_of`, `same_lat`). A small
  resolver turns them into a location with an uncertainty radius. This replaces v1's hard-coded estimates and makes
  a ready-made test set for a RELATION head later.

### 3.4 The fact sheet and the claim check

Every claim gets one of three labels:
- **verified**: it matches the gazetteer, LRO data or a NASA page, with the source stored;
- **crew impression**: it can't be checked and is clearly experience ("it looks like a windswept desert");
- **contradicted**: it gets fixed or dropped.

Sources are tagger spans: numbers, place mentions, colors, relations.

The same check guards the **guide's own words**. The LLM (Haiku-class, Head Start's `answer.py` pattern) gets only
the fact sheet for the places in play. Its draft is re-read by Arc Tagger (about 1 ms). Every number and place it
mentions must match a fact-sheet entry, or the sentence is rewritten once and then dropped. Kids don't get
hallucinated crater sizes. This uses the tagger's long list of spans as a checklist.

### 3.5 The Director: when to speak, when to play the astronauts

This is the product's brain, and it's where the tagger pays off most. It is a scoring policy over a small action
set, the same shape as Steer's Director and Head Start's search director. Rules first; learning later (§9).

| Action | What happens |
|---|---|
| `WAIT` | The kid is still talking: no `command_complete` and no Flux end of turn. Show live words; say nothing |
| `FLY` | Turn the globe and highlight. Free, so it happens as soon as a place resolves, even mid-sentence (Head Start-style speculation) |
| `SAY` | One or two TTS sentences from the fact sheet, ≤ 20 words for ages 5–7 |
| `PLAY` | Play a crew moment, introduced by one bridge line: "Christina saw this from Orion. Listen!" |
| `SAY+PLAY` | Short answer, then the moment as evidence |
| `ASK` | Clarify: "Did you mean Orientale, the giant bullseye?" while the globe previews it |
| `PAUSE_EXPLAIN` | During a crew moment: at the end of the sentence holding a jargon word, pause, explain in ≤ 12 words, resume |
| `NUDGE` | After 8 s of silence: offer the next mission or a related moment |
| `GUARD` | Private details or unkind words: no LLM call, gentle line ("Let's keep names and addresses private!") |

How it decides, using tagger read-outs:

| Signal (from) | Decision |
|---|---|
| `act=command_request` + place ("show me X") | `FLY` + `SAY` one line. Offer a crew moment if one ranks ≥ 0.7; auto-play it for under-8s if it's ≤ 15 s |
| Words like "astronaut", "crew", "say", "hear", "play" + place | `PLAY` the best moment; `SAY+PLAY` if the kid also asked a question |
| `act=question`, `qa_factoid` | `SAY` from the fact sheet; add `PLAY` if a moment has a verified claim on this exact point ("how did they describe the colors?") |
| A claim in the kid's words contradicts the fact sheet ("made of cheese", "the Moon has no craters") | `SAY` a gentle correction plus evidence: "Not cheese, but the crew did say it looked like a maple cookie!" |
| Link in the ask band (verify margin between accept and reject) | `ASK`, as in Steer's book search, which asks between −10.5 and −5.5 nats |
| Self-correction ("Tycho, no, Copernicus") | Use the corrected place; cancel the stale fly/answer (Head Start's frame does this) |
| `discourse.interruption` or kid speech during TTS or a clip | Duck the audio and listen. Resume only if the kid said nothing actionable |
| PII spans (private_name, street_address, phone) | `GUARD`; redact before logs or the LLM. Seen working on "my name is Maya and I live at 42 Oak Street" |
| A crew moment reaches a jargon span | `PAUSE_EXPLAIN` at the next utterance end; at most 1 per 30 s and none in the first 5 s |
| A crew moment mentions a new place | `FLY` there as the word is spoken (v1 already does this, but from keywords) |

Hard limits: never speak over crew audio, never play more than 30 s without a check-in for ages 5–7, never say
a number that isn't on the fact sheet.

### 3.6 Arc audio: the part text can't hear

The tagger reads text. Awe, laughter, gasps and silence ("…you just ain't right. Oh my word!") are in the audio. Arc
v1.1 Mini gives bio events and audio events at RTF 0.10 (Head Start, `ARC_META=mini`). Offline it scores each
moment's **awe**, which drives the Awe Map and the ranking. Live it gives `command_complete` and speaker turns to
the Director, and lets us tell the kid's voice from a classmate's.

## 4. One model host for Head Start, Ask the Moon and Steer

Today Head Start loads its models inside its own process (`server/app.py` startup: Arc, EmbeddingGemma, tagger
handles). If Ask the Moon does the same, a laptop running both demos holds two copies of everything. The fix is a
single local daemon, **`whissle-host`**, that owns the models. Apps connect to it over HTTP and WebSocket and never
load weights themselves.

**Built so far (2026-11-13):** `model_server/` is the first version, with Arc Tagger only. It is a FastAPI service
with a per-domain handle pool and `POST /v1/tag` + `GET /health`. The backend calls it and fails open. It runs
under the repo's `make dev`. The services use the standard open stack (FastAPI, pydantic-settings, uv, httpx,
rapidfuzz, Vite, three.js from npm) so each piece can scale on its own:
- the model server can become a Ray Serve deployment without code changes;
- the voice path should move to pipecat + LiveKit, as in production;
- moments, the gazetteer and memory should move to Postgres + pgvector, with pg_trgm for fuzzy names, as in
  production.

The rest of this section describes the target.

### 4.1 What the host holds

| Model | Size / where | Gives | Loaded |
|---|---|---|---|
| **Arc v1.1 Mini** (audio) | ~1.0 GB RSS, CPU, RTF 0.10 | Reads the **same audio** while Deepgram supplies the words (`transcript="external"` / `stream.add_words`): speakers + roles, `device_directed`, `command_complete` (+160–200 ms), audio events (laughter, applause, cheer: experimental), bio events (breath, cough), **names linked to a list we pass** (the gazetteer subset) | At start; shared by every session |
| **Arc Transcriber** (full, Parakeet 0.6B) | ~3.3 GB, MPS | Best words and names for **files**. Live, its metadata arrives more than 1 s late (Head Start measured this), so it is batch only | Lazy, for offline jobs; unloaded after 10 min idle |
| **Arc Tagger v0.3** | ~26 MB, native C int8, ~0.1 ms/word batch | Spans, numbers, PII, acts, intents, events, turn yield; also re-reads the guide's own text for the claim check | At start; one cheap handle per stream (handles aren't thread-safe) |
| **Emotion / age / gender**: whissle-large metadata head (prod gRPC sidecar) or STT-meta-1B locally | GPU host / ~1B params | Streaming emotion distribution per turn (`{emotion, intent, age, gender, probs}`, as in prod's `user-metadata`) | Optional. **For kids we read emotion only**, never age or gender |
| **EmbeddingGemma 2** | MPS | One space for text, audio and images: Head Start's reranker; moment and NASA-image search for the Moon | At start |
| **Steer TTS** (optional) | on-device | The guide's voice, with delivery hints (§5.2) | Lazy |

The Deepgram key lives in the host only. Apps send audio and get words back, so no app ever holds a key.

### 4.2 One stream, one timeline

```
app ──audio (16 kHz PCM, 80 ms chunks)──► whissle-host /v1/stream?domain=assistant&names=moon-gazetteer
                                            ├─► Deepgram Flux ───────────── words, Eager/EndOfTurn
                                            ├─► Arc v1.1 Mini (same audio) ─ speaker, device_directed, command_complete,
                                            │       + Deepgram's words         audio/bio events, name links
                                            ├─► emotion head (if enabled) ─ emotion probs per interim/final
                                            └─► Arc Tagger (on the words) ─ spans, acts, corrections, PII, turn events
app ◄──one merged event stream, every event stamped with audio time──┘
   {t:"words"} {t:"arc"} {t:"emotion"} {t:"tag"} {t:"turn", state:"eager|end|resumed"}
```

Other routes: `POST /v1/tag` (text or words, batch), `POST /v1/embed` (text | audio | image),
`POST /v1/batch/transcribe` (file → Deepgram + Arc Transcriber + tagger, which builds the Moon Moments), and
`GET /v1/health` (loaded models, RSS, open sessions).

Rules:
- **Weights load once; state is per session.** Each stream gets its own Arc stream state and tagger handle.
- **Admission cap, fail open.** Like prod's `WHISSLE_META_MAX_CONCURRENT`: past N sessions a new stream gets words
  plus the tagger only, with no Arc audio or emotion. The voice keeps working.
- **Head Start keeps an in-process mode** (`MODELS=local`) so its evals stay reproducible. `MODELS=host` makes it a
  client. Ask the Moon is host-only from day one.
- **Memory on one laptop:** two apps in-process ≈ 2 × (1.0 Arc Mini + EmbeddingGemma + tagger), and twice that again
  if both load the Transcriber. With the host it's one copy, and the 3.3 GB Transcriber exists only during batch
  jobs. Measure the real numbers with `/v1/health` once it's built; this table is from Head Start's figures.

### 4.3 What each signal does in Ask the Moon

| Signal | From | Used for |
|---|---|---|
| Words + turn events | Deepgram Flux | The question; when to answer (soft answer on eager, confirm on end) |
| `command_complete`, `device_directed` | Arc audio | Fewer premature answers (26 → 11 per 100 in Head Start); ignore a classmate talking to someone else |
| Name links to the gazetteer list | Arc audio | A second opinion on "Aris-tar-cus" next to the text linker; disagreements become an `ASK` |
| Speaker change | Arc audio | Classroom: two kids, two turns. Crew library: who is talking |
| Spans, acts, corrections, PII, numbers | Arc Tagger | Frame, privacy guard, claim check, jargon detection |
| **Kid emotion** (confused / frustrated / excited / bored) | metadata head | The Director slows down and simplifies after confusion, offers a mission after boredom, and matches energy when the kid is excited. Used in the moment and never stored |
| **Crew emotion + laughter / gasps** | metadata head + Arc audio events, run offline on the crew library | Each moment's **awe** score: Awe Map, moment ranking, and how excited the guide sounds when it introduces a clip |

## 5. A turn, end to end, with narration

### 5.1 Timeline of one question

A kid says: *"show me the bullseye… no wait, the yellow part, what did they say about it?"*

| t (ms) | Event | What the app does |
|---|---|---|
| 0 | Speech starts. Deepgram interim: "show me the" | `WAIT`: live words on screen |
| 600 | Tagger: `act=command_request`; linker: "bullseye" → Orientale | `FLY` to Orientale (free, speculative); no sound |
| 1,400 | Tagger: correction ("no wait") + new descriptor "the yellow part" → Aristarchus Plateau | Cancel the Orientale highlight and fly to Aristarchus |
| 2,600 | "what did they say about it": crew request, "it" = Aristarchus | Director picks `SAY+PLAY` with moment `m-aristarchus-01` (Christina, 17 s, awe 0.82, claims verified) |
| 2,850 | Flux `EagerEndOfTurn` + Arc `command_complete` | Answer now. LLM drafts one line from the fact sheet; the tagger re-reads it; claim check passes |
| ~3,300 | First sound (Steer TTS, upbeat): "That's the Aristarchus Plateau! Christina saw it from Orion. Listen." | A soft chime as the scene changes to crew audio (§5.2) |
| ~6,000 | Crew audio plays from 31.2 s; the transcript highlights word by word | The globe holds on Aristarchus; Christina's "yellow" lights up its color chip |
| crew says "albedo" | Look-ahead tagging flagged a jargon span; this is the end of that sentence | `PAUSE_EXPLAIN`: duck the crew audio, guide says "Albedo means how bright it is." Resume |
| moment ends (sentence end) | | `NUDGE` after 8 s of quiet: "Want to find it yourself? Try mission 1!" |
| (any time) kid talks | Flux StartOfTurn + Arc `device_directed` | Duck the audio and listen. If the kid's emotion reads "confused", the next answer is shorter and slower |

### 5.2 Narration: how the guide sounds

The guide and the crew take turns like two presenters. Arc decides the handoffs.

- **Look-ahead.** Before a moment plays, the tagger reads its transcript (it already has it) and marks place
  mentions (to `FLY` on), jargon (`PAUSE_EXPLAIN` points), sentence ends (safe places to pause), and awe peaks. This
  is Steer's Arc Reading, used for crew audio instead of a book.
- **Delivery hints.** The guide's lines are rendered with hints from the tagger and the emotion signals: brighter
  before a high-awe moment, slower and lower for an explanation, calm when the kid sounds confused. Steer's
  narrator already applies tagger-driven delivery hints and character voices.
- **Sound cues.** A short chime when the scene changes (guide → crew, or a new place). Steer's `ArcReading.cues` does
  this for a new time or place in a book. Crew audio is ducked, never mixed under speech.
- **Who speaks when.**
  - The crew never gets talked over.
  - The guide speaks only at sentence ends or turn yields.
  - Pauses for explanation are at most 1 per 30 s.
  - With no pause points in a moment, it plays straight through.
- **Captions always.** Every spoken word, from the guide or the crew, is on screen, so it works with the sound off
  in a classroom.

## 6. Product revamp

**Who:** kids 6–11 at home and in class. Their teacher is the second user.

**Core loop:** *Ask → See → Hear the astronauts → Do → Earn.*

| Mode | What the kid does | Arc's job |
|---|---|---|
| **Explore** | Talks to the Moon: "show me…", "why…", "what did they say about…" | Ear, tagger frame, linker, Director |
| **Listen Along** | Plays a crew moment and the guide comments like a co-pilot: flies to each place, pauses to explain "ejecta" | Moments, jargon spans, look-ahead tagging (Steer's Arc Reading pattern) |
| **Missions** | Clues written the way the crew gives directions ("northwest of Glushko, same latitude as Ohm"); tap or say the answer | Relation parses, resolver |
| **Talk Like an Astronaut** | Looks at a crater and describes it out loud; earns badges for geology words, colors and directions, then hears how the crew described the same place | Tagger spans on the kid's own speech (GEO_TERM, COLOR, DIRECTION, numbers) compared with the moment's spans. The crew practiced this on a maple cookie, which makes a great intro |
| **Awe Map** | Taps glowing spots where the crew gasped or laughed | Arc audio awe per moment |
| **Classroom** | Teacher sees the questions asked, misconceptions caught, missions done. No names, no audio | Tagger acts, intents, claim check; PII never stored |

**Trust you can see:** every fact shows a source chip (IAU, LRO, "crew 0:42"). Estimated places are drawn as a
dashed circle sized to their uncertainty. Crew impressions are labeled "how it looked to them".

**Safety by design:** no accounts, no stored audio, PII redacted before any LLM call or log, jailbreak attempts
blocked (`safety.jailbreak.attempt`, used in Head Start), and the claim check on every guide sentence.

**Judges' demo (30 s):** a kid says "show me the bullseye… no wait, the yellow part". The globe swings to
Orientale, then corrects to Aristarchus. The guide says one line, then "listen". Christina's real voice says
"yellow snow-capped mountain" while the globe zooms, and the guide pauses once to say what albedo means. The
screen shows the source chips and the tagger read-out.

## 7. What to build this weekend vs later

| | Weekend (Nov 14–15) | Later |
|---|---|---|
| Server | Stand up `whissle-host` (§4) from Head Start's `tagger.py`, `ear.py` (Flux), `arcmeta.py`, `embed.py`; Ask the Moon's server becomes a thin FastAPI app (Director, fact sheet, answers) that talks to the host | Head Start switches to `MODELS=host`; Steer and other demos join |
| Offline | Deepgram batch on all 59 flyby clips (plus launch/splashdown for SoundID); tagger; linker against a ~1,500-name subset of the IAU gazetteer (all named craters > 20 km, maria, basins, landing sites); moments; fact sheet; hand review of low-confidence links | Full 9k gazetteer; Apollo Lunar Surface Journal audio; NASA image captions in the same index |
| Live | Flux ear + tagger frame + `eager+arc` endpointing; Director rules from §3.5; claim-checked answers; `PAUSE_EXPLAIN` in Listen Along | Arc verify for unsure names; barge-in tuning; multilingual |
| Product | Explore + Listen Along + Missions, source chips, privacy guard | Talk Like an Astronaut, Awe Map, Classroom, SoundID |

## 8. How we'll know it works

Reuse Head Start's eval harness (`eval/run_ab.py`, the policy simulator) and add:

- **Name resolution:** 60 kid-style requests × 4 voices (TTS plus at least 2 real kids, with consent) → right place
  first. Target ≥ 85%, with ≤ 5% asks.
- **Moment quality:** for 30 places, does the top moment mention the place, start and end on a sentence, and last
  ≤ 25 s? Target ≥ 90%.
- **Claim check:** seed 50 answers with wrong numbers or places. Target catches ≥ 95%, with ≤ 5% false blocks on
  correct answers.
- **Timing:** last word → first sound p50 ≤ 700 ms. Premature answers ≤ 10 per 100 (kids pause more than adults).
- **Director:** agreement with a human-labeled set of 100 turns (SAY / PLAY / ASK / WAIT).

## 9. What to train

1. **Lunar tagger domain.** New tags `entity.mention.lunar_feature` (crater, mare, basin, mons, landing site),
   `geo.term`, `color.term`, and **RELATION spans** (`midpoint`, `direction_of`, `same_latitude`). Training text:
   Deepgram transcripts of all Artemis audio, the Apollo Lunar Surface Journal, gazetteer sentences generated with
   real names, and synthetic kid questions. The tag heads are definition-keyed (frozen definition embeddings), so ask
   the Arc team how far a new tag can get from a definition alone before fine-tuning.
2. **Kid-speech ear.** Adapt on children's voices (Deepgram keyterms first; our ASR later), especially for
   mispronounced names ("Aris-tar-cus").
3. **Director policy.** Learn from what kids do next: replay, skip, "again", "what?", leaving. This follows Steer's
   Director v3 design: labels from behavior, no words stored, a safety gate before any update.
4. **Spatial resolver.** Map RELATION parses to lat/lon with uncertainty. The crew's own proposals (Integrity,
   Carroll) are the first test cases.
5. **Awe from audio.** Calibrate Arc's bio and audio events on the crew library, where we have clear positives
   (Earthrise, "Oh my word!").

## 10. Open questions

- Answered: Arc v1.1 takes Deepgram's words directly (`arc-transcribe --asr deepgram`, `predict(..., transcript="external", words=...)`, `stream.add_words`) and still reads the audio for metadata. Still open: how long a `names` list Arc can link against before accuracy drops. Steer says verify a short candidate list rather than bias on the whole catalog.
- Emotion (checked 2026-11-13, agent B, EMOTION=off): no local streaming emotion model fits today. (1) Arc v1.1 Mini lists
  `affect.emotion.{neutral,happy,angry,sad,surprised}` and `affect.arousal.*` in `mini/tags.json` (status experimental,
  gate meta.speech, domains talk/news/meeting/...), but `arc.tags(domain, include_experimental=True)` returns no `affect.*`
  tag for any domain and `predict(...)` utterances never carry them: the readout does not expose the head. (2) The HF cache
  `models--WhissleAI--STT-meta-1B` holds only README.md (no weights, `model_config.yaml` recorded as missing), so it would
  need a download plus its runtime, and a 1B model is unlikely to stay near real time on CPU next to Arc. The model server
  sends `{"t":"emotion","available":false}` once per `/v1/stream` session. To turn it on: an Arc build that exposes the
  affect head (then read it from `live.utt` and emit only `emotion`, never age/gender). Arc's experimental audio events
  (laughter, applause, scream, glass_break) also saturate on air-to-ground radio audio, which is why the awe score is
  relative to the clip (app/arcmeta.py).
- Emotion for kids: is the metadata head calibrated on children's voices? If not, use it only to adapt pacing, never to label a child.
- What are the exact Deepgram keyterm limits for nova-3 batch vs Flux? Check the docs before relying on 100+ names.
- Should we name the astronauts in moments? Their names are public, but the diarization-to-name map must be checked
  by hand.
- The crew's names "Integrity" and "Carroll" are proposals, not IAU-approved names. The UI must say so.
