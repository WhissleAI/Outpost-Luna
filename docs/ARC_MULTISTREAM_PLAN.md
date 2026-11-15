# Arc as a multi-stream model: audio + telemetry + events + state, on-device

2026-11-13 · Whissle · For the Arc modelling team (Arc Transcriber, Arc Tagger) and the Outpost Luna app team.

**In one paragraph.** Arc today hears one audio stream (or reads one word stream) and outputs a transcript plus tags.
Next, it should also read the streams that sit next to the audio in any operations room: numeric telemetry, discrete
events, app/game state, context lists and the conversation so far, across one or more audio channels. It should mask
whichever streams are missing and output tags that use all of them. The driving product is **Outpost Luna → Junior
Astronaut Mission Trainer** (NASA Space Apps 2026): kids 7–12 command a lunar south-pole outpost by voice while real
data drives the world (power, life support, radiation dose, solar storms from DONKI, Sun/Earth positions from JPL
Horizons). The broader target is space operations: crew + mission-control loops + spacecraft telemetry. Everything
runs on-device.

**Builds on, does not repeat:** [`ARC_SPACE_DATA_PLAN.md`](ARC_SPACE_DATA_PLAN.md) (vocabulary tiers, space tags, app
intents, synthetic kid data, list-context fine-tuning, known issues #1–#19), [`NASA_DATASETS.md`](NASA_DATASETS.md)
(verified inventory), [`MISSION_CONTRACT.md`](MISSION_CONTRACT.md) (the game's State, telemetry, Command, Event),
[`REVAMP.md`](REVAMP.md) (model host, Director, one timeline).

**Conventions.** *Measured* numbers cite their source. *Target* numbers are labelled "target". **UNVERIFIED** marks
anything not opened today. "Today" = what runs in `model_server/` on 2026-11-13. "Proposed" = not built.

Contents:
1. Goal and why multi-stream
2. Input streams spec
3. Masking and missing streams
4. Outputs and capabilities
5. Datasets
6. Synthetic expansion
7. Training recipe
8. Evaluation
9. The app side: what we pass to Arc, exactly
10. The Director's understanding
11. Effort and phasing
12. Asks and open questions

---

## 1. Goal and why multi-stream

### 1.1 What audio alone gets wrong

Each row is a case where the words are the same and the right output depends on a non-audio stream.

| Utterance (kid or crew) | Audio-only reading | What the other stream says | Right reading | Stream needed |
| --- | --- | --- | --- | --- |
| "It's dropping! Do something!" | `act=statement`, no referent | `power_pct` falling 3 %/shift, `dose_rate` flat | referent = `resources.power_pct`; suggest allocate | telemetry trend |
| same words | same | `dose_rate_msv_h` 0.06 → 0.9, storm active | referent = dose rate; suggest shelter | telemetry + event |
| "Go." | `command_request`, unknown | Director just asked "Rover ready, go or no-go?" (`pending=poll`) | `discourse.radio.go` answering the poll | conversation state |
| same "Go." | | no pending poll; rover idle | ambiguous → ask | conversation state |
| "Houston, we've had a problem" | `device_directed`? | `comm=closed`, next window 5 h | `addressee=houston`, queue the call; Director says "No link for 5 hours" | state |
| "Houston says we should shelter" | could look like a call | (team chatter) | `addressee=team`, not a command | multi-speaker + state |
| "Fifty to shields" vs "fifteen to shields" | ASR word confusion | free power = 20 % (both legal?) — 50 needs confirm | number with confidence; low-conf + risky → confirm readback | state (budget) |
| Kid shouts, high arousal | `affect.stress` high | `alerts=[]`, kid just won a mini-game | excitement, not panic | alarm state |
| Calm voice "um, the dose thing is red" | low arousal | `alerts=["dose_rate_high"]` | urgent content in calm voice; act now | alarm state |
| "Put it all in heaters" | allocate heaters 100 % | it is lunar night, `sun_elev_deg=-3`, life support at 18 % | risky (starves life support) → `needs_confirm` | state |
| Speaker on CAPCOM loop vs FLIGHT loop (Apollo) | diarization guesses | channel id of the source tape | `speaker.role=capcom` | audio channel metadata |
| "Sun's going down" | statement | Horizons `sun_elev_deg` crosses 0 in 0.3 h | `event.mission.sunset` grounded, not a misconception | ephemeris |
| "The storm is over, turn off shelter" | command | DONKI GST still active in sim | contradiction → Director fact-check | event stream |

### 1.2 Goal

| Goal | Concretely | Target |
| --- | --- | --- |
| One model reads N streams | audio 1..N channels, external words, telemetry, events, state, lists, dialogue state | proposed |
| Missing streams are normal | every stream can be absent, late or stale; output degrades gracefully | audio-only no regression (§3.3) |
| Tags use all streams | commands with slots, grounded referents, grounded events, addressee, role, calibrated urgency | §4 |
| On-device | one host per device (`model_server/`), < 1.5 GB RAM live path (ARC_SPACE_DATA_PLAN §12) | target |
| Kid-safe | kid audio never leaves the device; only tags and redacted text may | hard rule |

### 1.3 Where it lives in Arc

Two models already exist; both get the same **stream pack** (encoders + fusion), trained once and shared.

| Model | Today (sources) | Trunk / conditioning today | Multi-stream role |
| --- | --- | --- | --- |
| **Arc Tagger** v0.3 | text-only, ~10 M params, 26 MB int8, ~0.1 ms/word batch (ARC_SPACE_DATA_PLAN §2, §12) | word channel → 6-layer Mamba-3 trunk; **global KV-memory attention layers**, domain FiLM, adapters; definition-keyed heads; T0/T1/T2 tiers (HF model card) | **First home** (phase 1). Commands, slots, referents, radio phraseology, grounded events are mostly lexical + state. Cheapest to train and iterate |
| **Arc Mini** v1.1 | audio, ~71 MB download, 100 ms outputs; external words; names/terms/topic/prev context; per-domain masks (arc_transcriber README) | audio trunk + decoder with context (`kb`, `kb_type`, `dom`, `prev`) | **Second home** (phase 2). Audio-dependent outputs: affect vs alarm, addressee (device/team/houston), speaker role by channel, multi-channel |
| Arc Transcriber (full) | Parakeet-TDT 0.6B + adapters, ~3.3 GB, metadata > 1 s late live (Head Start PROGRESS "Deepgram Flux ear + Arc metadata") | | Batch only: Apollo replay labelling (§6.3). Not on the live path |

The fusion point is the KV memory the Tagger already has: stream tokens are written to a **stream memory**, and the
trunk reads it through the existing global-memory attention plus new gated cross-attention adapters. A compact state
summary also drives FiLM, the same way domains do today.

---

## 2. Input streams spec

### 2.1 Stream kinds

| # | Stream | Exists in Arc today? | Schema (wire, §9) | Rate | Typical size | Encoder (proposed) |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | **Audio**, 1..N channels | 1 channel (16 kHz mono) | binary PCM16 LE frames; per-channel header (§9.2) | 16 kHz; 80–100 ms chunks | 1–4 channels device; 5–30 Apollo loops | existing audio trunk per channel + channel embedding |
| S2 | **External words** (Deepgram Flux / nova-3 / Verbit) | **yes** (`transcript="external"`, `add_words`) | `{"w","t0","t1","conf?","spk?","final?"}` | ~240 ms updates (Flux `Update`) | 2–4 words/s | existing word channel |
| S3 | **Telemetry** (numeric, irregular) | no | `{"ts","ch","v","unit?","q?"}` | 0.1–10 Hz per channel; sim ~1 Hz (MISSION_CONTRACT) | 6–40 channels app; 337 ISS ids in ISS Mimic | token = (channel, value bucket, Δ bucket, Δt bucket, staleness) |
| S4 | **Discrete events** | no (Arc emits events; does not read them) | `{"ts","kind","sev?","id","phase","src?"}` | sparse, 0–10/min | 10 kinds (MISSION_CONTRACT Event) | token = kind + severity + phase + age |
| S5 | **App/game state snapshot** | no (`topic`/`domain` only) | `{"ts","state":{path: value}}` (flattened) | on change; full snapshot ≤ 1/s | 20–60 keys | key-value tokens into slot table |
| S6 | **Context lists** (names, terms) | **yes** (`names`, `terms`, `topic`, `kb`/`kb_type`) | `{"names":[{name,kind,aliases,group}]}` | on change | 10–100 entries (ARC_SPACE_DATA_PLAN §10) | existing list mechanism; new kinds `load`, `vehicle`, `task`, `site`, `role`, `crew` |
| S7 | **Conversation context** | partly (`previous_text`, `auto_prev`) | `{"ts","who":"director|capcom|kid","text","pending?":{…}}` | per turn | last 3–5 turns | prev-text channel (exists) + **dialogue-state tokens** (pending confirm/poll, last command) |

### 2.2 One timeline

| Rule | Spec |
| --- | --- |
| Master clock | **Session audio sample clock**: `ts` = seconds since session start = samples / 16,000 on audio channel 0 |
| Other clocks | Each non-audio message carries `ts` in the session clock. The client maps its own clock with an offset measured at connect (`{"t":"sync"}` round trip, §9) and re-measured every 30 s |
| Mission time | The sim's `mission_time_h` is a **value** (state key), not the clock. Sim time is compressed (~1 s frames, MISSION_CONTRACT); the model sees wall/session time for alignment and mission time for meaning |
| Comm delay | `comm_delay_s` (2.6 s Moon round trip in the contract) is a state value. CAPCOM audio is stamped when it is **played**, not when it was "sent" |
| Telemetry interpolation (model input) | **Zero-order hold** (last value), causal: the model never sees a value before its `ts`. Linear interpolation is only used to build training labels |
| Out-of-order / late | Insert at true `ts`. Affects outputs from arrival onward; T2 utterance read-outs re-read the memory at the endpoint, so a late value can still change the final label |
| Staleness | per channel: `age = now − ts_last`; `stale = age > 3 × expected_period` (target rule) |

### 2.3 Latency budget (targets)

| Path | Budget (target) | Why |
| --- | --- | --- |
| Audio chunk → Arc live read-out | ≤ 150 ms p50 | Arc Mini CPU per 100 ms chunk ~10 ms p50 today (Head Start PROGRESS); fusion must add ≤ 5 ms |
| Telemetry/event arrival → usable at T0 | ≤ 200 ms after its `ts` | so "it's dropping" sees the frame that prompted it |
| State change → used | next word / next 100 ms chunk | |
| End of speech → command emitted (T2) | ≤ 300 ms p50 | `command_complete` lands +160–300 ms after the last word today (Head Start PROGRESS) |
| End of speech → sim acted + readback starts | ≤ 700 ms p50 | ARC_SPACE_DATA_PLAN §11 target |
| Stream pack compute per step | ≤ 1 ms Tagger, ≤ 5 ms Arc Mini (target) | Tagger engine ~0.55 ms/word today (ARC_TAGGER.md, old tagger) |

### 2.4 Encoding into the model

```text
               ┌──────────── stream memory M (K slots, ring + slot table) ────────────┐
S3 telemetry ─►│ tel-token: E_ch[ch] + E_val[bucket(v|ch)] + E_dv[trend] + E_dt[log Δt] + E_age │
S4 events    ─►│ ev-token : E_kind + E_sev + E_phase{onset,active,end} + E_age               │
S5 state     ─►│ kv-token : E_key[hash(path)] + (E_num[bucket] | E_cat[value] | E_bool)      │
S7 dialogue  ─►│ dlg-token: E_pending{confirm,poll,none} + E_cmdtype + slot embeds           │
mask/absent  ─►│ E_absent[stream] when a stream is missing (one token per missing stream)   │
               └──────────────────────────────────────────────────────────────────────────────┘
                     │ read by: (a) existing global KV-memory attention (Tagger)
                     │          (b) new gated cross-attention adapter every 2 trunk layers, gate g init 0
                     │          (c) FiLM from a pooled state summary z = pool(M) (alarm level, phase, comm)
S1 audio ─► audio trunk (per channel, + E_chan[role]) ─┐
S2 words ─► word channel (BPE) ────────────────────────┼─► trunk (Mamba-3 in Tagger) ─► heads (§4)
S6 lists ─► existing names/terms/kb mechanism ─────────┘                 └─► pointer head over M (referents)
```

| Choice | Proposed | Alternatives to ablate (§7.5) |
| --- | --- | --- |
| Value encoding | per-channel quantile buckets (32), fit on sim + real ranges; plus sign of Δ over the last 30 s (↓ ↓↓ = ↑ ↑↑) | Fourier features of normalised value; 16 / 64 buckets |
| Δt encoding | log-spaced buckets of time since sample: 0–0.2, 0.2–1, 1–5, 5–30, 30–120, >120 s | continuous sinusoidal |
| Channel identity | learned `E_ch` for known channels + **definition-keyed** fallback: embed the channel's text definition ("battery state of charge, percent") with the same frozen encoder the Tagger uses for tag definitions (bge-small, HF card) | learned only |
| Token budget | change-triggered (deadband per channel, e.g. 1 % for power) and capped at 20 tokens/s total; slot table always holds the latest value per channel | uniform 1 Hz |
| Memory | ring of K = 64 recent tokens + slot table (one slot per state key/channel, ≤ 64) | K = 32 / 128 |
| Fusion | KV memory + gated cross-attn (g = 0 at init) + FiLM | FiLM only; cross-attn only; concat-to-input |
| Lists | unchanged: `names` with kinds, list-context training as ARC_SPACE_DATA_PLAN §10 | |

Why gates start at 0: at initialisation the model is bit-identical to today's Arc on audio-only input, so regression
is measurable from step 0.

### 2.5 Existing API vs new

| Capability | Arc Mini / Transcriber today | Arc Tagger today | New |
| --- | --- | --- | --- |
| Name list linking | `names` (`name`, `kind`, `aliases`, `group`), snap + linker candidates | gazetteer link done in app | new kinds (`load`, `vehicle`, `task`, `site`, `role`) |
| Decoder context | `terms`, `topic`, `previous_text`, `auto_prev` (`kb`, `kb_type`, `dom`, `prev`) | — | dialogue-state tokens |
| Domain conditioning | `--domain` list incl. `assistant`, `assistant_noisy` | domain FiLM: `talk`, `meeting`, `court`, `assistant`, `sports`, `news` | `space_ops` and `mission_kids` domains (ARC_SPACE_DATA_PLAN asks for `space`) |
| External words | `transcript="external"`, Deepgram/Verbit adapters | `push_words` with `revise_from` | unchanged |
| Output masks | per-domain `masks` (e.g. bio events off in `assistant`) | thresholds per domain | **input** availability masks (§3) |
| Events out | `command_complete`, audio/bio events, speaker change | speaker change, turn yield, sports/legal/meeting events | grounded mission events, radio acts, referents |
| Multi-channel audio | no (mono) | — | 1..N channels with role metadata |
| Telemetry, events, state in | no | no | **new** |

---

## 3. Masking and missing streams

### 3.1 Availability mask

Every step carries `m ∈ {0,1}^S` (one bit per stream) and, for S3, a per-channel `fresh` bit. A missing stream
contributes exactly one `E_absent[stream]` token to memory, never zeros (so "no telemetry" ≠ "telemetry says 0").

| Situation | Mask behaviour |
| --- | --- |
| Stream never connected (plain Outpost Luna explorer, no mission) | `m_s = 0` for S3–S5; model = today's Arc + lists |
| Stream disconnects mid-session | last values kept in slot table with `stale` flag; after `3 × period` → `m_s = 0` |
| Late frame | inserted at true `ts` (§2.2) |
| Channel never seen in training | definition-keyed embedding (§2.4); if no definition, dropped |
| Audio missing, words present (text chat, Tagger only) | S1 masked; Tagger path unchanged |
| Words missing (no cloud ear, offline) | Arc's own decoder (`transcript="builtin"`) |

### 3.2 Modality dropout (training)

| Curriculum stage | Per-stream drop p | All-non-audio dropped | Stale injection | Delay injection | Contradiction examples |
| --- | --- | --- | --- | --- | --- |
| A (stage 7.1) | 0.1 | 0.1 | 0 | 0 | 0 |
| B (stage 7.3) | 0.3 | 0.2 | 10 % of channels frozen 30–300 s | 0–1 s jitter | 5 % |
| C (stage 7.3 end, 7.4) | 0.5 | 0.3 | 20 % | 0–3 s, 2 % out of order | 10 % |

### 3.3 Graceful degradation targets (all targets)

| Streams available | Command exact match (synthetic spoken, §8) | Referent accuracy | Audio-only metrics vs today |
| --- | --- | --- | --- |
| all | ≥ 0.92 | ≥ 0.90 | — |
| audio + words + state (no telemetry) | ≥ 0.90 | ≥ 0.75 | — |
| audio + words + lists only | ≥ 0.85 | n/a (falls back to "ask") | — |
| audio only (any domain, r8 gold sets) | — | — | **no regression**: ≤ 0.5 pt abs drop in Tagger T0 macro AP; WER Δ ≤ +0.2 abs; `command_complete` premature rate unchanged |

### 3.4 Stale telemetry and asynchronous arrival

- The model gets `E_age` per token, so it can learn "old power value" vs "fresh".
- Outputs that rely on telemetry carry `grounded_on: [{stream, ch, ts, age_s}]` so the Director can refuse to act on
  stale data (rule: no risky action on data older than 10 s; target).
- Training contradictions (§6.5) teach the model to prefer speech when telemetry is stale and telemetry when speech is
  vague.

### 3.5 Privacy masking

| Data | On device | May leave the device | How |
| --- | --- | --- | --- |
| Kid audio | yes, in memory only | **never** | host stores no audio (REVAMP §4.2 rules); training uploads exclude any kid audio unless a signed consent record exists for that recording |
| Kid words | yes | only redacted (Tagger PII spans masked) | existing `redacted_text` |
| Tags, commands, telemetry, events | yes | yes (no PII) | |
| Speaker embeddings for role enrolment | session only | never | wiped at session end |
| Cloud ear (Deepgram) | — | audio goes to Deepgram today | **demo only**; the on-device target is Arc Transcriber Edge (ARC_SPACE_DATA_PLAN §12). Flag in UI while a cloud ear is on |

A per-stream `upload_mask` travels with the session config (§9) so the host can enforce it, not the app.

---

## 4. Outputs and capabilities

Existing tags from ARC_SPACE_DATA_PLAN §5 stay. New families below. Tier: T0 = as the word arrives, T1 = ≤ 3 words
later, T2 = at utterance end (Arc Tagger card).

### 4.1 Mission command intents and slots

Intent family `intent.mission.*` maps 1:1 onto MISSION_CONTRACT `Command.type`.

| Intent | Contract command | Slots | Examples |
| --- | --- | --- | --- |
| `allocate` | `{"type":"allocate","to","amount":{kind,value},"from"}` | `load` (shields, life_support, greenhouse, science, rover, comms, heaters), `amount.kind` (percent, delta, all, half, little, none), `amount.value`, `from` | "put 30 percent into shields", "more to heaters", "take 10 from science" |
| `dispatch` | `{"type":"dispatch","vehicle","task","target"}` | `vehicle` (rover), `task` (collect_ice, repair_array, explore, return), `target` (site/place id from list) | "send the rover to get ice at Shackleton" |
| `shelter` | `{"type":"shelter","on"}` | `on` bool | "everyone into the shelter", "we can come out now" |
| `query` | `{"type":"query","what"}` | `what` (power, oxygen, life_support, dose, storm, comms, all) | "how much power do we have" |
| `call_houston` | `{"type":"call_houston","text"}` | `text` (the message span) | "Houston, we need help with the array" |
| `confirm` | `{"type":"confirm"}` | — (requires `pending=confirm`) | "yes", "confirm", "do it" |
| `cancel` | `{"type":"cancel"}` | — | "no", "wait, cancel that", "abort" |
| `end_shift` | `{"type":"end_shift"}` | — | "end shift", "next", "we're done for now" |

Structure modifiers (span tags, any intent):

| Tag | Read-out | Meaning | Example |
| --- | --- | --- | --- |
| `cmd.boundary` | per-word event | start of a new command in a compound utterance | "shields to 40 **and** send the rover home" |
| `cmd.negation` | span | negated target or action | "**don't** touch life support", "anything **but** the rover" |
| `cmd.condition` | span + parse `{ch, op, threshold, unit}` | standing rule; emitted as a rule, not an action | "**if power drops below 20**, turn off science" |
| `cmd.correction` | span | self-correction; the later value wins | "forty, no, thirty" |
| `cmd.amount` | span + `{kind, value, unit}` | uses Arc's number value + unit (`entity.number.percent`/`measure`/`count`) | "half", "a little", "**25 percent**", "**3 millisieverts**" |
| `cmd.number_conf` | per number | P(value correct) combining ASR conf + acoustic + state plausibility | "fifteen" vs "fifty" |

Output per utterance (T2, with a running guess at T0):

```json
{"t":"command","utt":{"t0":12.4,"t1":14.1},
 "commands":[
   {"type":"allocate","to":"shields","amount":{"kind":"percent","value":40},"p":0.94,
    "slots_p":{"to":0.98,"amount.value":0.91},"negated":false},
   {"type":"dispatch","vehicle":"rover","task":"return","target":null,"p":0.88}],
 "rules":[{"if":{"ch":"resources.power_pct","op":"<","value":20},"then":{"type":"allocate","to":"science","amount":{"kind":"none"}},"p":0.81}],
 "grounded_on":[{"stream":"state","key":"loads.shields","age_s":0.4}],
 "risky_hint":0.73, "tier":"T2"}
```

`risky_hint` is a model prior only; the sim's `needs_confirm` is the authority (MISSION_CONTRACT).

### 4.2 Radio phraseology

| Tag | Read-out | Tier | Example |
| --- | --- | --- | --- |
| `discourse.radio.{copy,roger,wilco,affirm,negative}` | utterance | T1 | "copy that", "roger" |
| `discourse.radio.say_again` | utterance | T1 | "say again?", "come again" |
| `discourse.radio.stand_by` | utterance | T1 | "stand by" |
| `discourse.radio.{go,no_go}` | utterance, answer to a poll | T1 | "Power is go", "no-go for EVA" |
| `discourse.radio.callsign` | span | T0 | "**Houston**, **Base Artemis**" |
| `discourse.radio.{over,out}` | event | T0 | "over" |
| `discourse.radio.readback` + `readback_match` ∈ [0,1] + `mismatch_slots` | utterance, vs last CAPCOM/Director line (S7) | T2 | CAPCOM: "set shields to forty"; kid: "shields forty" → 0.97; "shields fourteen" → `mismatch_slots=["amount.value"]` |

### 4.3 Event tags aligned to telemetry

Two read-outs per kind. **Mention**: speech refers to the event (exists as `event.space.*` style). **Grounded**: the
mention links to an active event id from S4 or a telemetry crossing in S3.

| Kind | Ground truth source | Mention example | Grounded output |
| --- | --- | --- | --- |
| `solar_storm`, `storm_end` | sim event from DONKI (GST/CME/SEP) | "is the storm here?" | `{"kind":"solar_storm","event_id":"ev-17","p":0.93}` |
| `comm_open`, `comm_closed` | sim state `comm`, Horizons Earth elevation | "can we talk to Houston?" | links to `env.next_comm_window_h` |
| `low_power` | `power_pct` < threshold | "we're running out of juice" | links to `resources.power_pct` |
| `dose_alert` | `dose_rate_msv_h` > threshold | "the radiation is red" | links to `alerts.dose_rate_high` |
| `sunset`, `sunrise` | Horizons `sun_elev_deg` crossing 0 | "it's getting dark" | links to `env.sun_elev_deg` |
| `rover_back`, `failure` | sim events | "the rover's back!" | event id |
| Apollo: `go_no_go`, `tli`, `landing`, `los`, `aos`, `master_alarm` | AiRT TOC milestones (§5) | "go for landing" | milestone id |

Also a **telemetry-side** event head (no speech needed): emits `event.mission.*` from S3/S4 alone at T0, so the model
can be scored against telemetry truth (§8) and the app gets one event vocabulary.

### 4.4 Telemetry-grounded resolution

| Input span | Candidates (from memory M + lists) | Output |
| --- | --- | --- |
| "it", "that", "the bar", "the red one", "this thing" | state keys + active events + list entries | `{"span":[3,4],"ref":"resources.power_pct","p":0.88,"alt":[{"ref":"resources.dose_msv","p":0.07}]}` |
| "the rover" | `rover` state | `{"ref":"rover","state":{"busy":true,"task":"collect_ice"}}` |
| "there" | last place (S7) + dispatch targets in list | place id |

Implementation: a pointer head = attention over memory tokens + list entries, trained with cross-entropy on the
referent index (§7.4). Cues it should learn: trend direction ("dropping" → channel with negative Δ), alarm salience,
recency of Director mention.

### 4.5 Team, speaker roles, affect, addressee

| Output | Read-out | Tier | Uses streams | Definition |
| --- | --- | --- | --- | --- |
| `speaker.id` (enrolled, session-local) | per segment | T1 | S1 | 2–4 kids on one device; enrolment = "I'm power officer" turn (role assignment intent) |
| `speaker.role.mission.{commander,power,life,comms}` | per speaker | T2 | S1 + S5 (`roles` from `/start`) + S7 | role gating input (§10) |
| `speaker.role.{capcom,flight,eecom,…}` (Apollo) | per channel/segment | T1 | S1 channel metadata | channel → role prior |
| `addressee.{device,team,houston,other}` | utterance | T0 running, T2 final | S1, S2, S5 (`comm`), S7 | replaces binary `device_directed` in mission mode; `device_directed` = P(device) is kept for compatibility |
| `affect.urgency`, `affect.stress`, `affect.excited`, `affect.confused` | utterance | T2 | S1 + S5 alarms | raw (from voice) **and** `affect.urgency_vs_alarm` ∈ {calm_under_alarm, matched, alarmed_without_cause} |
| `discourse.assistant.command_complete` | event | T0 | S1, S2, S7 | existing; pending-poll state should make "Go." complete instantly |

### 4.6 Per-output tier and targets

| Output | Tier | Precision target | Recall target | Other target |
| --- | --- | --- | --- | --- |
| `intent.mission.*` | T2 (running T0) | ≥ 0.95 top-1 | — | exact command match ≥ 0.92 (§8) |
| Slots (load, vehicle, task, target, what) | T1 | ≥ 0.97 | ≥ 0.95 | |
| `cmd.amount` value | T1 | — | — | value accuracy ≥ 0.97; ≥ 0.99 when `number_conf` ≥ 0.9 |
| `cmd.boundary` (compound) | T1 | ≥ 0.9 | ≥ 0.9 | |
| `cmd.negation` | T1 | ≥ 0.95 | ≥ 0.95 | negation never dropped silently: 0 executed-negated actions in eval |
| `cmd.condition` parse | T2 | ≥ 0.9 exact rule | — | |
| Radio acts | T1 | ≥ 0.9 | ≥ 0.85 | |
| `readback_match` | T2 | — | — | mismatch detection AUC ≥ 0.95 |
| Grounded events | T1 | ≥ 0.9 | ≥ 0.85 | F1 vs telemetry truth ≥ 0.9 (telemetry-side head) |
| Referent | T2 | ≥ 0.9 top-1 | — | |
| `addressee` | T2 | — | — | AUC(device vs rest) ≥ 0.95 |
| Speaker role (mission) | T2 | ≥ 0.9 | — | |
| `affect.urgency_vs_alarm` | T2 | ≥ 0.8 | — | |
| `command_complete` | T0 | — | — | premature ≤ 5 / 100 turns (Head Start eager+Arc: 11.2 / 100, measured) |

---

## 5. Datasets

### 5.1 All usable data

Verified = opened today (2026-11-13) or in NASA_DATASETS.md (same date). New rows are **bold**.

| Source | Modality | What it teaches | Labels | Licence | Download | Verified |
| --- | --- | --- | --- | --- | --- | --- |
| **Real aligned audio + events** | | | | | | |
| Apollo in Real Time, A11 | utterances + milestones; audio on site/IA | speech ↔ events alignment, roles, radio acts | `A11_merged_utterances.csv` 14,895 lines `GET\|type\|speaker\|text`; **`A11_TOC.csv` 274 milestones `GET\|level\|title`** | repo has no licence file; source audio PD | `curl -LO https://raw.githubusercontent.com/bfeist/apolloinrealtime.org/main/mission-data/11/MISSION_DATA/A11_TOC.csv` | yes |
| **Apollo in Real Time, A13** | utterances, **Flight Director loop transcript**, TOC, TEC | **an emergency on the FD loop**: urgency vs alarm, roles, go/no-go | `A13_utterances.csv` 12,979 lines; **`flight-director-loop.txt` 4,267 turns `[GET start - end] ROLE`, GET 55:46:46–62:06:54** (covers the accident); `A13_TOC.csv` 380 milestones; `A13_TEC_raw.txt` | as above | `curl -LO https://raw.githubusercontent.com/bfeist/apolloinrealtime.org/main/mission-data/13/MISSION_DATA/flight-director-loop.txt` | yes |
| **Apollo in Real Time, A17** | utterances + TOC + bookmarks | long surface ops, EVA events | `A17 master TEC and PAO utterances.csv` 36,089 lines; `Mission TOC.csv` | as above | `curl -LO "https://raw.githubusercontent.com/bfeist/apolloinrealtime.org/main/mission-data/17/MISSION_DATA/Mission%20TOC.csv"` | yes |
| Apollo MOCR audio (IA `A11_T*`, `apolloaudiocollection`) | multichannel audio | speaker role by channel, radio robustness | channel number = console loop; filename has wall-clock span | PD | `ia download Apollo13Audio --glob="*.mp3"` | yes (NASA_DATASETS) |
| Apollo Flight/Lunar Surface Journals | transcripts + clips | text, GET, role class | GET per utterance, `cc`/`onboard`/`pao` | UNVERIFIED terms | scrape `apollojournals.org` | yes (NASA_DATASETS) |
| Fearless Steps FS-1..4 | A11/A13/A8 MOCR audio | gold diarization/ASR on loops | SAD, SD, SID, ASR, topics | NASA media guidelines | email FearlessSteps@utdallas.edu | yes (gated) |
| Artemis audio library + Horizons −1024 events | audio + event times | modern Orion comms aligned to TLI/flyby/splashdown | MET/UTC event list | NASA media guidelines | NASA_DATASETS §4, §7 | yes |
| **Real telemetry, no audio** | | | | | | |
| **ISS live telemetry (Lightstreamer, adapter `ISSLIVE`)** | numeric, irregular, live | real spacecraft channel behaviour: rates, gaps, staleness, signal loss | ID + `TimeStamp` + `Value` (+ `Status.Class` on `TIME_000001`); ISS Mimic subscribes to 337 ids; meanings in `Telemetry/ISS_Public_Telemetry.xlsx` | public NASA stream; ISS Mimic code MIT | `pip install lightstreamer-client-lib`; `LightstreamerClient("https://push.lightstreamer.com","ISSLIVE")`, MERGE subscription, fields `TimeStamp,Value` (as in `ISS-Mimic/Mimic/Pi/iss_telemetry.py`). **No archive: record it yourself** | yes (repo + endpoint 200); historical archive UNVERIFIED |
| **OSDR Environmental Data App** | ISS cabin temperature, CO2, RH, radiation dose (GCR, SAA) per mission | realistic life-support and dose curves | per-mission time series (Rodent Research RR-1…RR-n listed) | NASA (PD) | UI at `https://visualization.osdr.nasa.gov/eda/`; bulk API endpoint UNVERIFIED | page yes; download path UNVERIFIED |
| **LRO CRaTER dose rates (lunar orbit)** | daily dose rates, lunar-shadow corrected | real lunar radiation levels and storm spikes for the sim | L30 daily dose-rate tables | NASA/UNH (PD, credit) | `https://crater-products.sr.unh.edu/` → "Dose/Dose Rates" (L30); PDS PPI LRO CRaTER | yes (page) |
| DONKI (GST, CME, SEP, IPS…) | events JSON | real storm times/severity driving the sim | type, start, instruments, links | PD | `curl "https://api.nasa.gov/DONKI/GST?startDate=2024-05-01&endDate=2024-05-31&api_key=$NASA_KEY"` | yes (NASA_DATASETS); DEMO_KEY rate-limited today (429) |
| **NOAA SWPC GOES proton flux** | 5-min numeric, ≥1/≥10/≥100 MeV | real SEP-driven dose-rate curves (storm onset shape) | `time_tag, satellite, flux, energy` | NOAA (PD) | `curl https://services.swpc.noaa.gov/json/goes/primary/integral-protons-7-day.json` (7 days only) | yes |
| **JPL Horizons, observer from a lunar site** | Sun/Earth az/el time series | sunset/sunrise and comm windows (Earth elevation) at the outpost | Az/El per step | PD | `curl "https://ssd.jpl.nasa.gov/api/horizons.api?format=json&COMMAND='10'&CENTER='coord@301'&COORD_TYPE=GEODETIC&SITE_COORD='0,-89.5,0'&MAKE_EPHEM=YES&EPHEM_TYPE=OBSERVER&START_TIME='2026-01-01'&STOP_TIME='2026-01-02'&STEP_SIZE='6h'&QUANTITIES='4'"` (`COMMAND='399'` for Earth). Returned Sun elev 1.77°–1.80° | yes |
| Artemis II OEM (AROW) / Horizons −1023 (Artemis I) | ephemeris + events | phase timeline for Artemis audio | state vectors, events | NASA | NASA_DATASETS §7 | yes; **Artemis I mission data releases beyond Horizons: UNVERIFIED** |
| **Mars 2020 MEDA (PDS4)** | env telemetry: pressure, temperature, wind, RH, radiation/dust sensors | out-of-domain telemetry channels for definition-keyed channel embeddings | PDS4 labels, sol | PD | `wget -r -np https://atmos.nmsu.edu/PDS/data/PDS4/Mars2020/mars2020_meda/data_derived_env/` (or `meda_derived.tar.gz` one level up) | yes (listing) |
| **Mars 2020 MOXIE bundle** | oxygen-production telemetry | life-support-like channel ("oxygen made per hour") | PDS4 | PD | `https://atmos.nmsu.edu/PDS/data/PDS4/Mars2020/moxie_bundle.tar.gz` | listing yes; contents UNVERIFIED |
| **MSL REMS** | env telemetry | as MEDA | PDS3 | PD | `https://atmos.nmsu.edu/PDS/data/mslrem_1001/DATA/` | yes (listing) |
| **Synthetic** | | | | | | |
| Mission sim timelines (§6) | telemetry + events + state | everything above, aligned | perfect | ours | `backend/app/mission` once merged | sim not merged yet |
| Kid / CAPCOM TTS on sim timelines (§6) | audio + words + labels | commands, slots, roles, affect, addressee | perfect | ours (TTS licence per voice) | `synth/` (proposed) | — |

### 5.2 Pairing: what is aligned and what is not

| Pair | Alignment exists? | How we pair |
| --- | --- | --- |
| Apollo speech ↔ Apollo milestones | yes, GET (1 s) | AiRT GET; force-align words (ARC_SPACE_DATA_PLAN §8) |
| Apollo speech ↔ Apollo telemetry | **no public telemetry** found | synthesize event + state streams from TOC milestones, FD-loop content and AFJ commentary (§6.3) |
| Artemis II speech ↔ events | yes, MET/UTC via Horizons −1024 | event tokens at event times |
| ISS telemetry ↔ speech | no (ISS A/G audio not public as a dataset; NASA_DATASETS §10) | none; use ISS telemetry to train the telemetry encoder's priors (rates, gaps), not speech fusion |
| DONKI / GOES / CRaTER / Horizons ↔ kid speech | no | **the sim joins them**: real data → sim timeline → scripted speech → TTS (§6) |

Conclusion: real aligned multi-stream data is Apollo-only and narrow. The bulk is synthetic, with real data as the
world that drives it.

---

## 6. Synthetic expansion

### 6.1 The mission sim as a data generator

The sim (MISSION_CONTRACT; branch `wt-moon-mission-sim`, contract committed, implementation pending) is
deterministic given `(site, seed, roles, command script)`. We run it headless.

```text
for seed in 1..N_MISSIONS:
    site  ~ sites (GET /api/mission/sites)
    storm ~ DONKI events (real dates) with severity; dose-rate shape from GOES/CRaTER
    sun, earth ~ Horizons for the site over the mission window
    policy ~ {careful, greedy, random, panicky, scripted-mistakes}       # who "plays"
    run 40 shifts: at each decision point sample 0–4 commands from policy, record
        telemetry frames (1 s), events, State after each command, needs_confirm/readback
    → timeline.jsonl (one line per frame/event/command; schema §6.6)
```

| Knob | Values | Why |
| --- | --- | --- |
| `N_MISSIONS` | 10,000 (target) | 400,000 shifts; covers storm × night × low-power combos |
| Sites | all from `/api/mission/sites` | different sun/comm patterns |
| Storm source | real DONKI GST/SEP dates (e.g. May 2024 named in the contract) + synthetic jitter | "real NASA data drives events" |
| Policies | 5 above | produces both good and bad states; bad states produce urgent speech |
| Frame rate | 1 Hz sim frames (contract) + event-triggered | matches `/ws/mission` |

### 6.2 Dialogue scripting and TTS

1. **Pick moments** from timelines: decision points, alarms, storm onsets, comm windows, confirmations.
2. **Script** per moment, conditioned on State: templates (exact slots) for 70 %, LLM paraphrase for 30 % with a
   validator that re-parses the text into the gold Command and rejects mismatches. Kid wording seeded from ARISS
   question lists (ARC_SPACE_DATA_PLAN §3.2).
3. **Speakers:** 2–4 kid voices per session (child TTS, ages 7–12, several accents; ARC_SPACE_DATA_PLAN §9.4), one
   adult CAPCOM voice, the Director's voice as app playback.
4. **Acoustics:** classroom babble 5–15 dB SNR, RT60 0.3–0.8 s, tablet mic; CAPCOM through radio degradation
   (300–3,000 Hz, static, dropouts, quindar; ARC_SPACE_DATA_PLAN §9.3) **plus the `comm_delay_s` from State**.
5. **Words stream:** run Deepgram (or a simulated ASR-error channel) on the render so S2 has real error patterns,
   including number confusions.
6. **Labels come free:** gold Command(s), slots, referent key, addressee, role, event ids, `pending` state.

### 6.3 Buckets (targets)

| Bucket | Example (State condition) | Teaches | Utterances |
| --- | --- | --- | --- |
| Commands with numbers | "put 30 percent in shields" | allocate + amount | 15,000 |
| Amount words | "half to heaters", "a little more to comms", "nothing to science" | `amount.kind` | 6,000 |
| Dispatch | "send the rover for ice at the crater rim" | dispatch slots + list target | 6,000 |
| Shelter on/off | "everybody in the shelter!" (storm active) | shelter | 3,000 |
| Queries | "how much oxygen is left?" | query.what | 8,000 |
| Compound | "shields to 40 and bring the rover home" | `cmd.boundary` | 6,000 |
| Negation | "don't turn off life support", "not the rover, the heaters" | `cmd.negation` | 4,000 |
| Conditional / standing rule | "if power goes under 20, turn science off" | `cmd.condition` | 4,000 |
| Confirm / cancel in pending state | Director: "All power to heaters?" kid: "yeah" / "no wait" | confirm/cancel + S7 | 6,000 |
| Self-corrections | "forty, no, thirty to shields" | `cmd.correction` | 4,000 |
| Telemetry-grounded vague | "it's dropping, fix it!" (power falling) | referent | 8,000 |
| Readbacks (correct + wrong) | CAPCOM "shields forty", kid "shields fourteen" | `readback_match` | 6,000 |
| CAPCOM lines | "Base, Houston, storm arrives in two hours, recommend shelter" (radio + delay) | roles, radio acts, addressee | 8,000 |
| Houston calls (open vs closed comm) | "Houston, do you copy?" with `comm=closed` | `addressee=houston`, comm state | 3,000 |
| Team chatter | "no, you do the rover, I'm power" | `addressee=team`, roles | 12,000 |
| Urgency: panic under alarm / calm under alarm / excited without alarm | | `affect.urgency_vs_alarm` | 6,000 |
| Misheard numbers | fifteen/fifty, thirteen/thirty in the S2 words, plausibility from State | `number_conf` | 6,000 |
| End shift | "next", "we're done, end shift" | end_shift | 2,000 |
| Role assignment / role-gated | "I'm the comms officer", power kid tries a comms action | roles | 3,000 |
| Mismatch negatives (§6.5) | "storm's over" while active | trust calibration | 6,000 |
| Radio phraseology (kid style) | "copy", "say again", "roger roger" | radio acts | 4,000 |
| **Total** | | | **~132,000 utterances** |

At ~2.4 s average (target; ARC_SPACE_DATA_PLAN §9 uses ~2.5 s) ≈ **88 h** of speech. Plus **600 full rendered
sessions × 12 min ≈ 120 h** of continuous multi-speaker audio with telemetry, for endpointing, addressee and role
under real turn-taking. Plus on-the-fly augmentation (not counted).

### 6.4 Apollo replays

| Step | Input | Output |
| --- | --- | --- |
| 1. Align utterances to audio | AiRT utterances (GET) + IA MOCR/A-G reels (wall-clock in filename) | coarse alignment at 1 s; refine with CTC forced alignment (ARC_SPACE_DATA_PLAN §8) |
| 2. Channel → role | IA channel number + AiRT channel list (FLIGHT, CAPCOM, EECOM, GNC, FIDO, RETRO, GUIDO, SURGEON, INCO, NETWORK; NASA_DATASETS §2) | `speaker.role` prior per channel (S1 metadata) |
| 3. Event stream from GET timelines | `*_TOC.csv` milestones (274 A11, 380 A13), Horizons/AFJ event times | S4 tokens: `{kind, phase, ts}` |
| 4. "Telemetry-like" state stream | hand-authored state curves per mission phase, keyed to milestones (e.g. A13 after 55:54:53: master alarm on, O2 tank 2 → 0, fuel cells degrading; from the Apollo 13 mission report, **UNVERIFIED** source not opened today) | S3/S5 tokens, coarse (labelled `src=reconstructed`) |
| 5. Labels | radio acts, go/no-go polls, roles, urgency (FD loop around the accident vs. routine hours) via LLM + rules, 10 % human-checked | silver labels |
| 6. Hold out | A13 FD loop GET 55:30–58:00 + 2 A17 EVA hours | real test set (§8) |

### 6.5 Negative and mismatch examples

| Type | Construction | Desired behaviour |
| --- | --- | --- |
| Speech contradicts fresh telemetry | "storm's over" while S4 storm active | grounded event = `solar_storm active`; flag `discourse.claim` contradicted → Director fact-check |
| Speech contradicts stale telemetry | same, but S3/S4 stale 5 min | trust speech, lower `p`, `grounded_on.age_s` large |
| Telemetry says crisis, speech is chatter | alarm on, kids talk about lunch | `addressee=team`, no command; urgency stays raw |
| Vague speech, two changing channels | power ↓ and dose ↑ | referent `p` split; Director asks |
| Wrong readback | CAPCOM 40 → kid 14 | `readback_match` low |
| State-implausible number | "put 150 percent in shields" | amount parsed, `number_conf` low, `risky_hint` high |
| Shuffled pairing | real speech with another session's telemetry | model must not hallucinate grounding (referent `p` low) |

Target mix: 10 % of training examples at curriculum stage C (§3.2).

### 6.6 Record format (one JSONL line per item)

```json
{"session":"sim-00042-s3","seed":42,"site":"shackleton_rim","split":"train","src":"synthetic",
 "audio":[{"ch":0,"role":"device_mic","path":"…/s3.ch0.flac"},{"ch":1,"role":"capcom_loop","path":"…/s3.ch1.flac"}],
 "words":[{"w":"shields","t0":12.41,"t1":12.80,"spk":"k1","conf":0.97}],
 "telemetry":[{"ts":12.0,"ch":"resources.power_pct","v":31.5},{"ts":12.0,"ch":"resources.dose_rate_msv_h","v":0.06}],
 "events":[{"ts":3.2,"kind":"solar_storm","id":"ev-17","phase":"onset","src":{"title":"DONKI GST 2024-05-10"}}],
 "state":[{"ts":12.0,"state":{"comm":"closed","shelter":false,"loads.shields":20,"pending":null}}],
 "dialogue":[{"ts":9.0,"who":"director","text":"Storm coming. What do you want to do?","pending":null}],
 "labels":{"utts":[{"t0":12.4,"t1":14.1,"spk":"k1","role":"power","addressee":"device",
   "commands":[{"type":"allocate","to":"shields","amount":{"kind":"percent","value":40}}],
   "referents":[],"radio":[],"affect":{"urgency":0.7,"vs_alarm":"matched"},"grounded_events":["ev-17"]}]}}
```

---

## 7. Training recipe

### 7.1 Stage 1: stream encoders + fusion, trunk frozen

| Item | Spec |
| --- | --- |
| Trainable | stream encoders (S3–S5, S7), memory, gated cross-attn adapters, FiLM-from-state, new heads |
| Frozen | trunk, word channel, audio trunk, existing heads |
| Data | synthetic §6 (text-path first: Tagger on rendered words; then Arc Mini on audio) |
| Params added (target) | ≤ 1.5 M Tagger (≤ 15 % of 10 M), ≤ 5 M Arc Mini |
| Check | audio-only outputs identical (gates at 0 → drift only from gate growth); per-head dev metrics |

### 7.2 Stage 2: list context

Apply ARC_SPACE_DATA_PLAN §10 unchanged, with the new list kinds (`load`, `vehicle`, `task`, `site`, `role`).
Mission target places come from the sim site list, so dispatch targets are always in a list.

### 7.3 Stage 3: modality-dropout curriculum

Unfreeze the top third of the trunk + adapters. Run curriculum stages A → B → C (§3.2). Mix 30 % audio-only batches
from the existing r8 training mix with the distillation loss below.

### 7.4 Stage 4: real aligned Apollo

Fine-tune on the Apollo replays (§6.4) for roles-by-channel, radio acts, go/no-go, grounded events and urgency.
Low LR (0.1× stage 3), adapters + heads only, 1–2 epochs. Kid mission heads frozen (Apollo has no kid commands).

### 7.5 Stage 5: distill and quantize

| Step | Spec |
| --- | --- |
| Teacher | stage-4 model (and Arc Transcriber full for audio labels on Apollo) |
| Student | Tagger int8 (native C, same path as v0.3: ARC_TAGGER.md) + Arc Mini int8 |
| Quantize | stream encoders int8; memory/attention float (as the native backend does today) |
| Parity | `check_parity.py`-style golden outputs per stream combination |
| Budget (target) | Tagger + pack ≤ 32 MB on disk; Arc Mini live ≤ 1.1 GB RSS; per-step pack compute in §2.3 |

### 7.6 Losses per output

| Output | Loss | Weight (start) |
| --- | --- | --- |
| `intent.mission.*` | CE (utterance) | 1.0 |
| Slots (load, vehicle, task, target, what, on) | BIO + type CE (span head v2 style) | 1.0 |
| `cmd.amount` value | Arc number head (existing) + CE over amount.kind | 1.0 |
| `cmd.boundary`, `cmd.negation`, `cmd.correction` | BCE per word / span | 0.5 |
| `cmd.condition` | span BIO + CE on (ch, op) + bucketed threshold CE | 0.5 |
| Referent pointer | CE over memory + list slots, with "none" class | 1.0 |
| Grounded events | BCE per kind + pointer CE to event id | 0.5 |
| Telemetry-side events | BCE vs sim truth | 0.3 |
| Radio acts, `readback_match` | BCE; readback via contrastive pair to S7 line | 0.5 |
| Addressee | CE (4-way) | 1.0 |
| Roles | CE per speaker | 0.5 |
| Affect + `vs_alarm` | BCE, label smoothing 0.1; temperature-calibrated on dev | 0.3 |
| **Audio-only preservation** | KL(student ‖ frozen today-Arc) on all existing heads, on audio-only batches | 1.0 |

### 7.7 Keeping audio-only performance

1. Zero-init gates (identity at start).
2. Distillation KL on 30 % audio-only batches (above).
3. Never update existing heads in stages 1–2.
4. **Gate:** each checkpoint re-runs r8 gold sets and the ARC_SPACE_DATA_PLAN §11 Artemis test clips; reject on any
   regression beyond §3.3.

### 7.8 Ablations

| # | Ablation | Question |
| --- | --- | --- |
| A1 | audio/words only vs +state vs +telemetry vs +events vs all | which stream buys which metric |
| A2 | FiLM only vs cross-attn only vs both vs KV memory only | cheapest fusion that hits targets |
| A3 | buckets 16/32/64 vs Fourier features | value encoding |
| A4 | change-triggered vs uniform 1 Hz tokens | token budget vs accuracy |
| A5 | memory K = 32/64/128 | latency vs referent accuracy |
| A6 | learned channel ids vs definition-keyed vs both, tested on unseen channels (MEDA/REMS/ISS) | generalisation to new telemetry |
| A7 | synthetic only vs + Apollo stage 4 | does real Apollo help kids or only space ops |
| A8 | dropout curriculum vs fixed p = 0.3 | robustness to missing streams |
| A9 | Tagger-only fusion vs Arc Mini fusion vs both | where each output should live |
| A10 | template-only vs template + LLM paraphrase | wording diversity vs label noise |

---

## 8. Evaluation

### 8.1 Test sets

| Set | Contents | Size (target) | Streams |
| --- | --- | --- | --- |
| SIM-HO | held-out seeds **and** held-out sites, unseen TTS voices | 500 sessions, ~5,000 commands | all |
| SIM-HO-masked | SIM-HO with each stream masked in turn | same | each subset |
| APOLLO-RT | A13 FD loop GET 55:30–58:00 + 2 A17 EVA hours + 2 A11 landing hours (held out of stage 4) | ~6 h | audio, words, events, reconstructed state |
| KIDS-LIVE | real kid mission sessions recorded **with parental consent**, on-device, labelled in-house | 40 sessions × 15 min (target), 2–4 kids each | all |
| R8-GOLD + ARTEMIS | existing r8 gold sets + ARC_SPACE_DATA_PLAN §8 Artemis test clips | existing | audio/words only (regression) |

### 8.2 Metrics and targets

| Metric | Definition | Target (SIM-HO) | Target (KIDS-LIVE) |
| --- | --- | --- | --- |
| Command exact match | all commands in the utterance equal gold (type + every slot) | ≥ 0.92 | ≥ 0.85 |
| Slot accuracy | per slot | ≥ 0.97 | ≥ 0.93 |
| Number accuracy | `amount.value` equal | ≥ 0.97 | ≥ 0.93 |
| **Wrong actions / 50 commands** | executed (after any confirm) and ≠ intended | ≤ 1 | ≤ 1 |
| Missed confirms | risky command executed without confirm | 0 | 0 |
| Referent top-1 | | ≥ 0.90 | ≥ 0.80 |
| Event tag F1 vs telemetry truth | grounded + telemetry-side heads vs sim events | ≥ 0.90 | — |
| `device_directed` / addressee AUC | device vs team/houston/other | ≥ 0.95 | ≥ 0.92 |
| Readback mismatch AUC | | ≥ 0.95 | ≥ 0.90 |
| Latency end of speech → command | VAD end → `{"t":"command"}` | ≤ 300 ms p50 | ≤ 400 ms p50 |
| Latency end of speech → action | → sim acted + readback audio starts | ≤ 700 ms p50, ≤ 1.2 s p90 | same |
| Audio-only regression | §3.3 | none beyond §3.3 | — |
| APOLLO-RT role accuracy | per segment | ≥ 0.9 | — |
| APOLLO-RT radio acts F1 | | ≥ 0.8 | — |

Baselines to report beside every target: (a) today's Tagger + the Director's regex rules (no streams), (b) an LLM
command parser over the same words with State in the prompt (cloud; quality ceiling, not deployable).

---

## 9. The app side: what we pass to Arc, exactly

`docs/STREAMS.md` (being written by another agent) will hold the short factual description of what is wired. It was
not present in this branch when this was written; the "Today" column below was read from `model_server/app/`
(`routes_meta.py`, `arcmeta.py`, `tag_stream.py`) on 2026-11-13.

### 9.1 What works today

| Endpoint | Direction | Message | Status |
| --- | --- | --- | --- |
| `WS /v1/stream?domain=assistant` | client → host | binary PCM16 LE mono 16 kHz; host buffers ≥ 2,560 bytes (80 ms) before a step | **today** |
| | client → host | `{"t":"words","words":[{"w","t0","t1"}]}` (also accepts `word`/`start`/`end`; other fields dropped by `norm_words`) | **today** |
| | client → host | `{"t":"end_turn"}`, `{"t":"stop"}` | **today** |
| | host → client | `{"t":"emotion","available":false,"reason":…}` once (Arc v1.1 Mini has no emotion read-out) | **today** |
| | host → client | `{"t":"arc","available":bool,"model":"arc-v1.1 mini","domain":…}` once; `available:false` when `META_MAX_SESSIONS` (4) is reached, fail-open | **today** |
| | host → client | `{"t":"arc","at","command_complete","device_directed","speaker","act","intent","utt_open","audio_events":[{label,t0,t1,p}],"bio_events","cc_events":[{t,p}],"rtf"}` on change; `"final":true` on stop | **today** |
| `POST /v1/meta` | batch | `audio` file + `words` JSON + `domain` + `events` → utterances with act/intent/device_directed/awe | **today** |
| `WS /v1/tag/stream` | Tagger | `{"op":"push","words",…}`, `endpoint`, `poll`, `tag_text`, … | **today** |
| `{"t":"context"}`, `{"t":"telemetry"}`, `{"t":"event"}`, `{"t":"state"}`, `{"t":"dialogue"}`, `{"t":"sync"}`, multi-channel audio | | | **proposed** |

### 9.2 Proposed additions (all JSON text frames unless noted)

```jsonc
// once, first text frame (proposed). Unknown fields ignored by today's host.
{"t":"config","session":"m-123","domain":"mission_kids",
 "audio":[{"ch":0,"role":"device_mic","sr":16000},{"ch":1,"role":"app_playback","sr":16000,"echo_ref":true}],
 "streams":["words","telemetry","event","state","dialogue","context"],
 "telemetry_channels":[{"ch":"resources.power_pct","unit":"%","period_s":1,"def":"battery state of charge"},
                       {"ch":"resources.dose_rate_msv_h","unit":"mSv/h","period_s":1,"def":"crew radiation dose rate"}],
 "upload_mask":{"audio":false,"words":"redacted","tags":true},
 "outputs":["command","referent","event","radio","addressee","role","affect"]}

// multi-channel audio (proposed): binary frame = 1-byte channel id + PCM16 LE payload. Channel 0 alone = today's format.

{"t":"sync","client_ts":1731500000.123}                      // host replies {"t":"sync","client_ts":…,"session_ts":12.48}

{"t":"context","names":[{"name":"Shackleton rim","kind":"site","aliases":["the rim"]},
                        {"name":"shields","kind":"load"},{"name":"rover","kind":"vehicle"}],
 "terms":["millisievert","regolith"],"topic":"lunar outpost mission"}

{"t":"telemetry","ts":12.0,"frames":[{"ch":"resources.power_pct","v":31.5},{"ch":"resources.dose_rate_msv_h","v":0.06},
                                     {"ch":"env.sun_elev_deg","v":1.8},{"ch":"env.earth_elev_deg","v":-0.4}]}

{"t":"event","ts":3.2,"id":"ev-17","kind":"solar_storm","phase":"onset","sev":3,
 "src":{"title":"DONKI GST","url":"https://api.nasa.gov/DONKI/GST"},"real_date":"2024-05-10"}

{"t":"state","ts":12.0,"state":{"comm":"closed","comm_delay_s":2.6,"shelter":false,"rover.busy":true,
 "rover.task":"collect_ice","loads.shields":20,"alerts":["dose_rate_high"],"roles":{"k1":"power","k2":"comms"},
 "mission_time_h":66}}

{"t":"dialogue","ts":9.0,"who":"director","text":"All power to heaters. Confirm?",
 "pending":{"kind":"confirm","command":{"type":"allocate","to":"heaters","amount":{"kind":"all"}}}}
```

Mapping from MISSION_CONTRACT: the `/ws/mission/{mid}` frame splits into `telemetry` (power, life_support, dose_msv,
dose_rate, sun_elev_deg, earth_elev_deg) and `state` (comm, loads, alerts); contract `Event` → `event`
(`t_h` → `mission_time_h` in state; `ts` = session time when the app received it).

### 9.3 What comes back (proposed)

```jsonc
{"t":"arc", …today's fields…, "addressee":{"device":0.91,"team":0.06,"houston":0.02,"other":0.01},
 "speaker":"k1","role":"power","affect":{"urgency":0.72,"stress":0.4,"vs_alarm":"matched"}}

{"t":"command","utt":{"t0":12.4,"t1":14.1},"tier":"T2","commands":[…§4.1…],"rules":[…],
 "grounded_on":[{"stream":"telemetry","ch":"resources.power_pct","age_s":0.4}],"risky_hint":0.73}

{"t":"command","tier":"T0","running":true,"commands":[{"type":"allocate","to":"shields","p":0.62}]}   // speculation

{"t":"referent","span":{"t0":12.9,"t1":13.0,"text":"it"},"ref":"resources.power_pct","p":0.88,"alt":[…]}

{"t":"event","kind":"sunset","grounded":true,"source":"telemetry","ch":"env.sun_elev_deg","p":0.95,"ts":20.1}

{"t":"radio","act":"readback","readback_match":0.31,"mismatch_slots":["amount.value"],"ref_dialogue_ts":9.0}

{"t":"streams","available":{"audio":[0],"words":true,"telemetry":true,"event":true,"state":true},"stale":["env.earth_elev_deg"]}
```

Rule: every message keeps `at`/`ts` in session time; every field is optional; clients ignore unknown fields (today's
Head Start/Outpost Luna clients already fail open).

---

## 10. The Director's understanding

The Director (`backend/app/director.py`, rules over the Tagger read-out today; REVAMP §3.5) becomes mission-aware.
Arc gives probabilities; the Director owns policy and the sim owns truth.

| Director decision | Arc outputs used | Rule (proposed) |
| --- | --- | --- |
| **Act on a command** | `command` (T2), `addressee.device`, `role`, `number_conf`, `grounded_on.age_s` | act if `p ≥ 0.85` and `addressee.device ≥ 0.8` and all `age_s ≤ 10`; else ask |
| **Speculate** | `command` T0 running | pre-compute the sim result (no side effect); show a ghost bar; commit on T2 |
| **State-aware resolution** | `referent`, list links | fill missing slots from the referent ("give it more" → allocate to `ref`); if referent `p < 0.7` → "Power or radiation?" |
| **Confirm risky actions** | sim `needs_confirm`, `risky_hint`, `number_conf` | confirm if sim says so, **or** `number_conf < 0.9` on any amount, **or** `cmd.negation` present with low `p`. Readback uses parsed slots: "Forty percent to shields. Confirm?" |
| **Resolve confirm/cancel** | `intent confirm/cancel`, `radio.affirm/negative`, S7 pending | only valid while `pending=confirm`; timeout 10 s → cancel (target) |
| **Role gating** | `speaker.role.mission`, roles in state | a power command from the comms kid: "That's the Power Officer's call. Power, what do you think?" Commander may override |
| **Emotion pacing** | `affect.*`, `vs_alarm` | `alarmed_without_cause` → reassure + show the bar; `calm_under_alarm` → raise salience (sound + "This is important"); `confused` → simpler line, one option |
| **CAPCOM phrasing** | radio acts, `readback_match` | CAPCOM style lines ("Base, Houston, copy forty to shields"); wrong readback → "Say again, I heard fourteen" |
| **Comm delay** | `addressee.houston`, state `comm`, `comm_delay_s` | `comm=closed` → "No link to Houston for 5 hours; message queued"; open → reply after `delay_ms` (contract `action:"houston"`) |
| **Standing rules** | `rules` (from `cmd.condition`) | store rule; evaluate on every telemetry frame; announce when fired; max 3 active (target) |
| **Fact checks vs telemetry** | grounded events, `discourse.claim`, contradictions | "The storm's over" while active → "The sensors still show the storm. Stay in the shelter 2 more hours." |
| **Team chatter** | `addressee.team` | do nothing; never answer chatter (Head Start: `device_directed` alone separates chatter poorly, ARC_SPACE_DATA_PLAN fix #18) |
| **End shift** | `end_shift` | only when no pending confirm; summarise the shift |
| **Explorer (non-mission) turns** | existing tags | unchanged (REVAMP §3.5) |

---

## 11. Effort and phasing

Estimates are targets for planning, not measured.

| Horizon | Arc team | App team | Dependency |
| --- | --- | --- | --- |
| **Week 1** | Freeze tag names (§4) as an ontology extension; stream-pack design review; record 1 week of ISS Lightstreamer telemetry for encoder priors | Merge the mission sim; headless runner emitting §6.6 timelines; Director mission rules on **today's** Tagger + regex (no streams) as the baseline | sim merged |
| **Week 2** | Template generator + validator for §6.3 text; Tagger stage 1 on text (rendered words, no audio) | `{"t":"telemetry"|"event"|"state"|"dialogue"|"context"}` accepted and logged by the host (ignored by the model) — wire format live | week 1 |
| **Month 1** | TTS rendering pipeline (kid voices, radio, delay); Tagger stages 1–3 on synthetic; ablations A1–A5; int8 Tagger + pack | Host forwards streams to the Tagger pack; `{"t":"command"}` + referent wired into the Director behind a flag; latency harness | TTS voices; host change |
| **Month 2** | Arc Mini stage 1–3 (addressee, affect vs alarm, multi-channel); Apollo replay alignment (§6.4) | KIDS-LIVE consent form + on-device recorder; 10 pilot sessions | consent approval |
| **Quarter** | Stage 4 (Apollo), stage 5 (distill, quantize), A6–A10; Arc Transcriber Edge integration for offline words | Offline-only mode (no cloud ear); full KIDS-LIVE eval; space-ops demo on Apollo 13 FD loop replay | Arc Transcriber Edge ETA |

### 11.1 Risks

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Synthetic-to-real gap on kid speech | high | commands fail on real kids | 20 % real kid re-recordings (ARC_SPACE_DATA_PLAN §9.4); KIDS-LIVE gate |
| Model leans on telemetry and ignores speech | medium | wrong actions | mismatch + shuffled-pairing negatives (§6.5); A1 ablation |
| Audio-only regression | medium | breaks Head Start / Steer | zero-init gates + KL + gate (§7.7) |
| Fusion too slow on device | low–medium | latency | change-triggered tokens, K ≤ 64, Tagger-first (A2, A4, A5) |
| Apollo "telemetry" is reconstructed, not real | certain | stage 4 teaches coarse state only | label `src=reconstructed`; weight low; report APOLLO-RT separately |
| Sim not merged on time | medium | no generator | generator only needs the contract; stub sim from MISSION_CONTRACT |
| Licences (AiRT repo, FS, journals) | medium | can't redistribute labels | ask Ben Feist / UTD (open asks in ARC_SPACE_DATA_PLAN §13); train-only use until answered |
| Kid privacy | low (by design) | trust | §3.5 enforced in the host; no audio stored |
| Cloud ear in the demo (Deepgram) | certain today | audio leaves device | UI flag; offline mode in the quarter plan |

---

## 12. Asks and open questions

- [ ] Arc team: accept the stream-pack design (§2.4) or propose the fusion point you prefer; confirm the Tagger's global KV-memory layers can take external tokens.
- [ ] Ontology: approve `intent.mission.*`, `cmd.*`, `discourse.radio.*`, `addressee.*`, `affect.urgency_vs_alarm`, grounded `event.mission.*` (with ARC_SPACE_DATA_PLAN §5/§6 as one r9 extension).
- [ ] Domains: `mission_kids` and `space_ops` (in addition to the `space` domain already asked for).
- [ ] Definition-keyed channel embeddings: can the frozen bge-small definition encoder be reused for telemetry channels?
- [ ] Arc Mini: is a per-step memory read ≤ 5 ms feasible inside the 100 ms chunk budget?
- [ ] Multi-channel audio in Arc Mini: shared trunk with channel embedding, or N independent streams + cross-channel head?
- [ ] Echo reference channel (`app_playback`) as an input (ARC_SPACE_DATA_PLAN fix #17) — same mechanism as multi-channel?
- [ ] `command_complete` with dialogue state: should a pending poll shorten the hold for one-word answers ("Go.")?
- [ ] Who owns the command composer: a model head emitting full Commands (§4.1) or the app composing from slots? (Proposal: model emits; app validates against the sim.)
- [ ] Mission sim: merge date for `backend/app/mission`; headless mode with seed → timeline JSONL.
- [ ] TTS: which child voices are licensed for training data generation (Steer TTS family?).
- [ ] KIDS-LIVE: consent form, on-device-only storage, retention; who labels.
- [ ] Licences: Apollo in Real Time CSVs (no licence file), Fearless Steps labelled packages, journal commentary.
- [ ] Apollo 13 state reconstruction: which source (mission report) and who authors the curves.
- [ ] OSDR EDA: find the bulk download endpoint (UI only verified today).
- [ ] ISS telemetry: is a historical archive available anywhere, or do we record our own (start in week 1)?
- [ ] DONKI: get a real `api.nasa.gov` key (DEMO_KEY returned 429 today; FLR 404 per NASA_DATASETS).
- [ ] `docs/STREAMS.md`: reconcile §9.1 with it when it lands.
