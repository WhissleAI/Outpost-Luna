# Arc for Space: data and tag plan for Arc Transcriber + Arc Tagger

2026-11-13 · Whissle · For the Arc modelling team (Arc Transcriber, Arc Tagger)

Contents:
1. Why
2. Baseline
3. NASA datasets
4. Tag taxonomy
5. Building the real-audio dataset
6. Synthetic data
7. Context and name lists
8. Training and evaluation
9. Running it locally
10. Asks and open questions

---

## 1. Why: smart transcription for space, fully on-device

We want Arc Transcriber and Arc Tagger fine-tuned on NASA audio, so they hear space speech well and mark the meaning in it
as it streams. Everything must run locally: a spacecraft, a classroom tablet or a museum kiosk can't count on the cloud.

**The product.**
- **What it is:** Ask the Moon is a voice-first 3D Moon for kids, built for NASA Space Apps 2026 (Nov 14–15).
- **Challenge:** it targets *Abandoned but not Forgotten: Storytelling about NASA's Discarded Equipment on the Moon and Mars*.
- **How it works:** a kid asks out loud ("show me the rovers left on the Moon", "who drove the Apollo 16 rover?"), the
  globe flies there, and the hardware tells its story. Real NASA audio plays at the right second: Artemis II crew
  describing craters, Apollo astronauts' messages, launch loops.
- **Code:** this repo (`WhissleAI/ask-the-moon`, private).

**What "smart" means here.** A plain transcript is words. A smart one is words plus the meaning we mark on them, word by
word, while the person is still talking:

- *where*: lunar features, landing sites and hardware, linked to a place on the Moon, even when misspoken
  ("Oriental" → Mare Orientale)
- *who*: which astronaut or controller is speaking, and their role (CAPCOM, Flight, crew)
- *what is happening*: mission events (go/no-go, liftoff, burns, loss of signal, splashdown) and audio events (static,
  quindar tones, laughter, gasps)
- *what they mean*: descriptions vs commands vs questions; colors, geology terms, directions and spatial relations
  ("northwest of Glushko")
- *how it feels*: awe, excitement, tension
- *when to act*: the request is complete, the speaker yielded the turn, someone interrupted

**Why local.**
- **Comms:** deep-space links run with seconds to minutes of delay and blackouts; Artemis II lost signal behind the Moon.
- **Privacy:** kids' audio shouldn't leave the device.
- **Size:** one shared model host on a laptop already serves two apps (Ask the Moon and Head Start). That only works if
  the models are small. Today Arc Tagger is about 26 MB and about 0.1 ms per word; Arc v1.1 Mini is about 1 GB in RAM.

---

## 2. Baseline: what Arc does on Artemis II audio today

Arc Tagger v0.3 (domain `news`) finds lunar names well but types 75% of them as people, misses about 10%, and has no tags
for geology, directions or awe. Measured 2026-11-13 on all 60 Artemis II flyby recordings: 60,583 words, Deepgram nova-3
transcripts. Reproduce it with `backend/pipeline/probe_tagger.py` and the index build (`make index`).

| What we measured | Result | What to fix |
| --- | --- | --- |
| Lunar-name mentions found as entity spans | 820 linked to a gazetteer place | Keep: recall survives ASR misspellings ("babilov", "Oriental") |
| Entity type on those lunar names | person 616 · place 116 · organization 88 | New type `entity.mention.lunar_feature` |
| Lunar names the tagger missed (caught by gazetteer fallback) | 97 (~10%): Aristarchus 23, Orientale 19, Reiner Gamma 18, Integrity 15 | Recall on multi-word names and names that are also common words ("Integrity" = the spacecraft) |
| Unlinked entity spans | 1,081, top: Earth 96, Jeremy 65, albedo 64, Grimaldi 39, Kepler 21, Byrgius A ~31 | Gazetteer gaps (Grimaldi, Kepler, Pythagoras, Mare Humorum) + jargon mistaken for names |
| Direction words tagged as entities | ~100 (northwest 25, south 24, north 12, …) | New `geo.direction` and RELATION spans |
| Crew names (Jeremy, Christina, Reid, Victor) | Typed correctly as person | Use as speaker-naming evidence |
| Number spans | 645 | Keep; type `measure` vs `count` is mixed |
| Speed (native int8, 1 thread) | 0.08–0.11 ms per word; a 344 s clip tags in ~120 ms | Fine for on-device |

**Audio side.**
- **Arc v1.1 Mini speed:** in our model server it runs at RTF 0.03–0.06 on files, but close to RTF 1 when streamed live
  under load. Its metadata lands 1.2–4 s after the words.
- **Emotion:** its `affect.emotion.*` tags never appear in its output, so emotion is currently off.
- **Speakers:** Deepgram diarization undercounts them, finding 1–2 on clips with 3–4 crew.

---

## 3. NASA datasets to use

**Status:** the full inventory (contents, hours, labels, licence, download command, which tags each teaches) is being
verified now and will be added to this section. These sources are already in hand:

| Dataset | What it gives | Status in this repo | Download |
| --- | --- | --- | --- |
| [NASA Artemis Audio Library](https://www.nasa.gov/artemisaudio/) | ~113 clips (MP3 + WAV). 59 Artemis II lunar-flyby crew observations; launch, in-flight and splashdown loops; Apollo astronaut messages; crew interviews; briefings; `3-hour-lunar-surface-observation.wav` | 60 flyby clips downloaded, Deepgram-transcribed and indexed | `backend/pipeline/scrape_manifest.py` + `fetch_media.sh` (`make data`) |
| Shared Drive folder "original" (from a collaborator) | 50 files, all also on the NASA page: the non-flyby half (launch, in-flight, splashdown, interviews, 22 briefing WAVs) | Not downloaded; fetch from NASA directly | — |
| [NASA SVS CGI Moon Kit](https://svs.gsfc.nasa.gov/4720/) | LRO LROC color map (2k–16k), LOLA elevation | 4K color map used for the globe | `fetch_media.sh` |

Usage terms for NASA media: free to use, with no implied NASA endorsement.

---

## 4. Tag taxonomy: what the models should mark

We need:
- 8 new text tags in Arc Tagger;
- 6 new or recalibrated audio tags in Arc Transcriber;
- a new `space` domain in both.

Everything else reuses the existing r8 ontology. *New* = not in r8 today; *calibrate* = exists but doesn't fire usefully
on space audio.

### Arc Tagger (text, per word / span / utterance)

| Tag | Status | Definition | Example (real or kid) |
| --- | --- | --- | --- |
| `entity.mention.lunar_feature` | New | A named place on the Moon: crater, mare, basin, mons, rille, plateau, swirl, pole | "down on **Vavilov**", "the **Aristarchus Plateau**" |
| `entity.mention.spacecraft` | New | A named vehicle or hardware: Orion, *Integrity*, Eagle, LRV, Surveyor 3, SLS | "our great spacecraft **Integrity**" |
| `entity.mention.mission` | New | Mission names and numbers | "**Apollo 16**", "**Artemis II**" |
| `entity.mention.crew_member` | Calibrate (person → crew) | Astronaut or controller names, linked to a roster | "**Jeremy**, look at this" |
| `geo.term` | New | Geology and optics vocabulary a kid may not know | **albedo**, **ejecta**, **regolith**, **terminator**, **limb** |
| `geo.color` | New | Color words describing a surface | "distinctly **yellow**", "brownish **tan**" |
| `geo.direction` | New | Compass and relative directions | **northwest**, "**near side**", "**straight up**" |
| `geo.relation` (span) | New | A place located by reference to others; carries the operator | "**halfway between Orientale and Ohm**" → midpoint; "**northwest of Glushko, same latitude as Ohm**" |
| `event.space.*` | New | Mission events said in speech: go/no-go, liftoff, TLI, burn, LOS/AOS, splashdown, landing | "**go for TLI**", "**good burn**" |
| `entity.number.measure` | Calibrate | Distances, sizes, altitudes with units; feeds the claim check | "**930 km** wide" |
| `discourse.assistant.*` intents | Extend | Kid requests: `show_place`, `play_crew`, `tour`, `explain_term`, `who_left`, `quiz_answer` | "show me the rovers", "what does albedo mean" |
| `safety.pii.*`, `safety.child.*` | Keep | Kid's own name, address, phone | "my name is Maya and I live at…" |

### Arc Transcriber (audio, per frame / utterance)

| Tag | Status | Definition | Why it matters |
| --- | --- | --- | --- |
| `speaker.id` + `speaker.role.{crew,capcom,flight,pao,controller}` | Calibrate | Who speaks, by role and, when enrolled, by name | "Christina saw this" instead of "Astronaut 2" |
| `channel.{air_to_ground,loop,studio,phone}` | New | Narrowband radio vs studio | Space audio is mostly band-limited radio |
| `audio_event.quindar_tone` | New | The intro/outro tones on NASA air-to-ground | Turn boundary on radio loops |
| `audio_event.{static,dropout,los}` | New | Noise bursts, packet loss, loss of signal | Don't transcribe noise; mark the blackout |
| `audio_event.{laughter,gasp,cheer,applause}` | Calibrate | Fires near-constantly on crew radio today (laughter p > 0.9) | Awe moments for the app |
| `affect.awe` + `affect.{excited,calm,tense}` | New / calibrate | Emotional tone; awe is the space-specific one | Rank and introduce moments; kid pacing |
| `discourse.assistant.command_complete`, `device_directed` | Keep | When to answer; is it for the app | Endpointing for kid questions |
| `bio_event.{breath,cough}` | Keep | Already in Arc v1.1 | Suit/helmet audio |

---

## 5. Building the real-audio dataset

Label real NASA audio in three passes: machine words, machine tags linked to catalogs, then human review of a sample.
Split by recording, never by sentence, so the test set stays honest. The pipeline already runs in this repo
(`backend/pipeline/`); extending it is mostly new sources and new tag rules.

1. **Words and timing.**
   - Deepgram nova-3 batch (`diarize`, `utterances`, `smart_format`) with keyterms from the gazetteer and hardware
     catalog: up to 100 terms, about 50 used today.
   - Keep Whisper large-v3-turbo as a second opinion; where they disagree on a name, that word goes to review.
   - Store per word: `t0, t1, word, speaker, confidence`.
   - Script: `backend/pipeline/transcribe_deepgram.py`.
2. **Where existing transcripts exist, align them.**
   - The Apollo Flight Journal and Apollo Lunar Surface Journal have human transcripts with mission elapsed time (GET).
   - Fearless Steps has its own human-labeled transcripts and speaker labels.
   - Force-align them to the audio (CTC aligner) and treat them as gold for words and speakers.
3. **Silver tags.**
   - Run Arc Tagger, link every entity span to the gazetteer (rapidfuzz, cutoff 82) and the hardware catalog, and retype
     it (`lunar_feature`, `spacecraft`, `mission`, `crew_member`).
   - Rule lists give `geo.term`, `geo.color` and `geo.direction`.
   - Mission event tags come from aligning the GET event timeline to the audio clock.
   - Arc v1.1 gives audio events and speakers.
   - Every tag keeps its source (`arc`, `gazetteer`, `rules`, `timeline`, `human`) so training can weight it.
4. **Human review.**
   - Review 10% of utterances, plus every utterance with a name disagreement, a `geo.relation` candidate, or a
     low-confidence link.
   - Reviewers fix spans and types in a simple web form, with no free text.
   - `geo.relation` spans are labeled by hand only: there are few, and they're the hardest.
5. **Splits.** By recording and mission, never by utterance:
   - **train:** Apollo + Artemis interviews and loops;
   - **dev:** 10 Artemis II flyby clips;
   - **test:** 10 different Artemis II flyby clips plus the 3-hour lunar surface observation, never trained on.

   The two crew-proposed craters (Integrity, Carroll) and their spoken directions stay in test as the relation probe.
6. **Kid-safety pass.** Unscripted crew audio has occasional adult language ("freaking"). Mark those utterances
   `kid_safe=false` so they're never used as playback moments, but keep them in training: the model should still hear
   them.

**Output format** (one JSONL row per utterance):

```json
{"rec": "art002a000022", "set": "artemis2-flyby", "split": "dev", "t0": 31.2, "t1": 48.9,
 "words": [{"w": "yellow", "t0": 40.1, "t1": 40.4, "spk": "1", "conf": 0.98}],
 "spans": [{"start": 3, "end": 5, "tag": "entity.mention.lunar_feature", "link": "aristarchus", "src": "arc+gazetteer"}],
 "utt": {"act": "statement", "awe": 0.82, "channel": "air_to_ground", "kid_safe": true},
 "audio_events": [{"tag": "laughter", "t0": 45.0, "t1": 46.2, "src": "arc-v1.1"}]}
```

---

## 6. Synthetic data: kid searches, commands and radio speech

No public dataset has children asking about the Moon, so the kid side is synthetic.
- **Size:** about 40,000 generated utterances, about 60 hours once spoken.
- **How:** templates over the gazetteer and catalog plus LLM paraphrase, then spoken by TTS voices and degraded the way
  real rooms and radios are.
- **Labels:** come free with the template; each utterance carries its tags from generation.

| Bucket | Example | Tags it teaches | Utterances |
| --- | --- | --- | --- |
| Show / find a place | "show me the giant bullseye", "where's Tycho" | `show_place`, `lunar_feature`, kid descriptors → place | 8,000 |
| Hardware questions | "who drove the Apollo 16 rover", "what did Surveyor 3 find" | `spacecraft`, `mission`, `who_left`, `crew_member` | 6,000 |
| Crew audio requests | "what did the astronauts say about the yellow part", "play the launch" | `play_crew`, `geo.color`, `event.space.*` | 4,000 |
| Explain a word | "what does albedo mean", "what's ejecta" | `explain_term`, `geo.term` | 3,000 |
| Spatial directions | "go northwest of Glushko", "halfway between Orientale and Ohm" | `geo.direction`, `geo.relation` | 4,000 |
| Self-corrections | "show me Tycho, no wait, Copernicus" | correction span, final entity only | 3,000 |
| Mispronunciations | "Aris-tar-cus", "Oriental", "Vavilof", "Hertz-spring" | name linking under ASR noise | 4,000 |
| Misconceptions | "the moon is made of cheese right", "the dark side never gets sun" | `claim` spans for the fact check | 2,000 |
| Private details (negatives) | "my name is Maya and I live at 42 Oak Street" | `safety.pii.*` | 2,000 |
| Off-topic and chatter | classroom talk not meant for the app | `device_directed = false` | 4,000 |

**Voices.**
- Speak each text with child-range TTS voices: ages 6–12, several accents, and Spanish/Hindi-English code-switch for 10%.
- Mix in about 20% real kid recordings collected with parental consent at the event.
- Use the Steer TTS family locally where it has child voices; otherwise a licensed TTS.

**Acoustics.**
- Classroom babble at 5–15 dB SNR, room reverb (RT60 0.3–0.8 s) and tablet mics.
- The app's own audio leaking back into the mic. This came up in testing: the open mic heard the crew playback.

**Radio speech for the crew side.**
- Turn clean astronaut lines (interviews, podcasts) into air-to-ground audio: band-limit to 300–3,000 Hz, then add
  static, dropouts, quindar tones and 1–2.5 s delays. This teaches `channel.*` and the radio audio events.
- Mission event synthetics: TTS reads CAPCOM call-outs from real timelines ("Orion, Houston, you are go for TLI") over
  loop background.

**Context variants.** Render 30% of utterances with a `last_place` or `playing` context. That way follow-ups like "who
drove it?" and "what's that crater?" learn to resolve against it.

**Generator layout (proposed, in this repo):** `synth/templates/*.yaml` (one per bucket) → `synth/render_text.py` (fills
slots from `backend/data/places.json` + `artifacts.json`, LLM paraphrase ×3) → `synth/speak.py` (TTS, local) →
`synth/degrade.py` (room / radio / leak) → JSONL in the format of section 5 with `src: "synthetic"`.

---

## 7. Context and name lists at runtime

The app passes small, current context to the models; it doesn't bias on whole catalogs. Steer's book-search work measured
this: biasing Arc on a 61,000-title list barely helped, while checking a short candidate list against the audio raised
the right answer from 80% to 84–88%.

| Context | Size | Goes to | How it's used |
| --- | --- | --- | --- |
| Lunar gazetteer (IAU names + kid aliases) | ~9,000 names; ~23 in the app today | Linker (rapidfuzz + phonetic) | Every entity span is linked here; the tagger's type is ignored for lunar names |
| Hardware catalog (landers, rovers, impacts) | ~30 items + aliases ("Eagle", "LRV 2") | Linker, Deepgram keyterms | Same as above, `kind = artifact` |
| Keyterms for the ear | ≤ 100 terms per stream (Deepgram limit), ~50 used | Deepgram nova-3 / Flux | Names in view + names in the clip title first |
| Live candidate list | 10–30 names | Arc `names` / `arc_score` verify | Unsure name → score candidates against the audio; between thresholds → the app asks "Did you mean Vavilov?" |
| Crew roster | 4 Artemis II + Apollo crews | Speaker naming | Turn "speaker 2" into a name when the audio matches an enrolled voice or a name is addressed |
| Conversation context | `last_place`, `playing` (clip + time), `emotion` | Director, tagger | Resolves "who drove it?" and "that crater"; slows down when the kid sounds confused |
| Domain | `assistant` for kids, `news`/`talk` for crew audio, new `space` | Both models | Sets thresholds and FiLM conditioning |

The ask for Arc is to accept this list API natively in both models (`names`, `terms`, `context`). It should also report,
per span, which list entry it linked and with what score.

---

## 8. Training and evaluation plan

Start with the cheapest change that moves each number: lists first, then a `space` domain adapter and new heads, and a full
fine-tune only if those plateau. Each step is gated on the held-out Artemis II test clips, with no regression on the
existing r8 gold sets.

1. **Lists only (in progress for the demo, no training).** Expand the gazetteer from the IAU list, add spoken variants
   and possessives, and feed keyterms to Deepgram. Measure the change in linked mentions on the 60 clips.
2. **Arc Tagger `space` domain adapter.**
   - Train the domain FiLM/adapter and the new definition-keyed tag heads (`lunar_feature`, `spacecraft`, `mission`,
     `geo.*`, `event.space.*`) on the silver + reviewed real transcripts and the synthetic kid set.
   - Keep the Mamba trunk frozen.
   - Question for the Arc team: how far can a new tag get from its definition text alone (frozen bge-small embeddings)
     before any labels?
3. **RELATION head.** A span head for `geo.relation`, plus a small resolver that turns the parse into lat/lon with an
   uncertainty radius. It is trained on the synthetic directions; the crew's two proposed craters are the test.
4. **Arc Transcriber adaptation.**
   - Decoder: context biasing with the lunar list, then a light encoder-adapter fine-tune on band-limited radio speech
     and kid TTS.
   - Event heads: `quindar_tone`, `static/dropout/los` and `channel.*` from the synthetic radio set.
   - Recalibrate `laughter/gasp/cheer` on reviewed crew clips, since they currently fire almost constantly.
   - New `affect.awe`, from a few hundred reviewed examples.
5. **Distill for the edge** (section 9).

| Metric | Baseline (2026-11-13) | Target for v1 |
| --- | --- | --- |
| Lunar-name mention recall (tagger, Artemis test clips) | ~90% | ≥ 97% |
| Correct type on lunar names | ~14% place (75% person) | ≥ 95% `lunar_feature` |
| Link accuracy to the right place | not yet measured on gold | ≥ 95% |
| `geo.relation` resolved within uncertainty radius | 0 (no head) | 2/2 crew craters + ≥ 80% synthetic |
| Kid query → right place first (spoken, 4 voices, 60 queries) | not yet measured | ≥ 85%, ≤ 5% asks |
| Name WER on crew radio audio | not yet measured | report per name |
| Laughter/awe event precision on reviewed crew clips | fires on most frames | ≥ 0.8 |
| Speaker count per clip vs reviewed | undercounts (1–2 vs 3–4) | exact on ≥ 80% |
| End of speech → answer, on device | ~1.2 s with Flux (Head Start measurement) | ≤ 700 ms p50 |

---

## 9. Running it locally

One model host per device loads each model once and serves every app on it. The target is a laptop or tablet with no
network after setup, at under 1.5 GB of RAM for the live path. The host already exists (`model_server/` in this repo,
FastAPI). Head Start uses it in a draft PR (WhissleAI/headstart#1), at about 1 ms extra per tagger call.

| Model | Today (measured on M3 Pro) | On-device target | Path |
| --- | --- | --- | --- |
| Arc Tagger v0.3 | 26 MB int8, native C; 0.1 ms/word batch, ~1–2 ms per streamed word | Same size with the `space` adapter (+ < 2 MB) | Already edge-ready; ship adapter weights per domain |
| Arc v1.1 Mini (audio metadata) | ~1 GB RSS together with the tagger, 6–12 s load; RTF 0.03–0.06 on files, close to 1 live under load | RTF ≤ 0.3 live, metadata ≤ 500 ms behind the words | Quantize; stream smaller chunks; drop unused heads |
| Arc Transcriber (full, Parakeet 0.6B) | ~3.3 GB, MPS; batch only (metadata > 1 s late live) | Batch indexing on the laptop; not on tablets | Use the coming 4-bit Arc Transcriber Edge for the live ear |
| Live words (ear) | Deepgram Flux (cloud) in the demo | Arc Transcriber Edge, offline | The ask for this doc: replace the cloud ear for space use |
| Embeddings (search over moments/images) | EmbeddingGemma 2 (740M) in Head Start, not shared yet | Shared via `/v1/embed` on the host | Same prompts as Head Start's index |

Endpoints the host already serves:
- `GET /health`
- `POST /v1/tag` (Arc Tagger, text or words)
- `WS /v1/tag/stream` (streaming tagger, Head Start's push/poll semantics)
- `POST /v1/meta` (Arc v1.1 metadata for a file)
- `WS /v1/stream` (live audio metadata)

Rules the host already enforces:
- weights load once, per-session state;
- a session cap that fails open (beyond it, words + tagger only);
- no audio stored;
- private details redacted before anything leaves the device.

---

## 10. Asks for the Arc team and open questions

- [ ] **New tags in the ontology** (r9?): the 8 text tags and the audio tags above, with definitions. Confirm names before
      we label anything.
- [ ] **`space` domain** for both models: thresholds and FiLM/adapter, trained per section 8.
- [ ] **New tags from definitions alone**: can a definition-keyed head take a new tag from its definition before any
      labels? This decides how much silver data we need.
- [ ] **Native list API**: `names` / `terms` / `context` accepted by Arc Tagger, plus per-span link output (entry + score).
- [ ] **Emotion**: Arc v1.1 Mini never emits `affect.emotion.*`, and STT-meta-1B has no weights in the local cache. Which
      model should carry emotion and awe on device?
- [ ] **Live speed**: Arc v1.1 Mini runs at RTF ~1 when streamed through the host under load. Is a smaller-chunk or
      quantized build planned?
- [ ] **Arc Transcriber Edge** (4-bit): ETA, and whether it can replace Deepgram as the offline ear.
- [ ] **Speaker naming**: enrollment API for a small roster (4 Artemis II crew, Apollo crews) so diarization yields names.
- [ ] **Licensing check** for training on the Fearless Steps corpus and NASA media (NASA media: free to use, no implied
      endorsement).
- [ ] **Kid data**: consent form and storage rules for any real child recordings collected at events (default: none
      stored).
