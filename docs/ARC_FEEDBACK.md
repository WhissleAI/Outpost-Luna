# Arc Tagger feedback: safety tags on kid turns

For the Arc team. Outpost Luna now uses Arc Tagger's `safety` output as the first layer on every kid turn
(`backend/app/safety.py`), with an offline word list as the backstop (`frontend/src/profanity.js`, the same list in
`safety.py`). These are the misses we saw, so they can go into the next training round.

How we read the output: `POST /v1/tag {"text", "domain": "assistant"}` → `utterances[].safety: [{tag, p, thr, on}]`. A
tag counts only when `on` is true and `p >= thr`. Probed 2026-11-14 against the local model server (:8200, Arc v1.1
mini text tagger). Latency is about 15–20 ms a turn, so calling it on every turn is fine.

## Status: Arc Tagger 0.5.0, kids domain (16 Nov 2026)

The Arc team fixed this in arc-tagger-c 0.5.0 (main `4318e4a`, PR #10): a `kids` / `game` domain calibrated on short
kid turns, plus a guard layer (`src/guard.c`). The app now uses it:

- **Safety reads use `domain: "kids"`** (`backend/app/safety.py` `tagger_read` → `POST /v1/tag`), with
  `command_context: true` on the command screens (`cabin`, `brief`, `ride`), so "kill the heaters" is a command.
- **The Director's read-out stays on `assistant`** (`session._direct_turn`, `/api/ask`, `claims.py`). On the same model
  files the 0.5.0 library gives byte-identical `assistant` / `news` / `talk` output to the 0.3 library (1,500 round-11
  kid texts × 3 domains: 0 differences), so the shipped r10 weights see exactly what they saw.
- **Model files unchanged** (the tagger asset, v1). The kids thresholds are built into the library (`src/kids_thr.inc`);
  `model_server/tests/test_tag_kids.py` checks they equal `onnx/arctag_kids.json` of `WhissleAI/arc-tagger` at revision
  `500449290c` (vendored as `desktop/vendor/arctag/arctag_kids.json`, sha256 `f3add6ae…`). The newer Hugging Face
  int8 weights (v0.4.1) were not adopted: they change every `assistant` read-out the Director and round 12 train on,
  and on the 1,500 round-11 texts in the kids domain they added two false alarms our files do not have
  ("mom i'm hungry" → self-harm, "go mine some ice with the buggy" → strong profanity).
- **Every example in the tables below now behaves as expected** (tested against the real library and model:
  `test_tag_kids.py`, with and without `command_context`). Kids domain on 1,500 round-11 texts: 36 tagged, all real
  (29 PII with an address / phone / name, 6 profanity, 1 insult); none on the other 1,464.
- **Backstops kept**, as the Arc team asked (precision 1.00, recall on indirect phrasings ~0.5): the offline word list,
  the `CRISIS` phrases, and new `GROOMING` phrases (pictures of you, secrecy from parents, meeting in person, "add me
  on snap"). No round-11 text triggers either phrase list.

## The owner's case (the reason this exists)

The packaged app, open mic, room chatter in the background. The voice bar printed the overheard words, profanity
included.

| Input | Expected | Actual |
|---|---|---|
| `shit shit oh` (assistant domain; heard from the room) | `safety.profanity` (or `.strong`) on; `device_directed` low (it was room talk, not to the app) | **no profanity tag at all**; `safety.pii.leak` **0.99** on (a false positive: there is no personal data); `device_directed` **0.91** from the audio head |

Impact: without the word list, this turn would have counted as clearly directed at the app (0.91 is above the
"strong" threshold 0.7), shown "Didn't catch that", and in the Library been routed as a question.

## Profanity and toxicity misses

| Input | Expected | Actual (tags on) | Near misses (off, p > 0.25) |
|---|---|---|---|
| `fuck this` | `safety.profanity.strong` | `safety.pii.leak` 0.99 | `safety.child.inappropriate` 0.40 |
| `go fuck yourself` | `safety.profanity.strong`, `safety.toxicity.insult_harassment` | none | `safety.child.inappropriate` 0.40 |
| `shit` | `safety.profanity` | `safety.pii.leak` 0.98 | `safety.child.inappropriate` 0.33 |
| `damn it` | `safety.profanity.mild` | `safety.pii.leak` 1.00 | |
| `you are a stupid idiot` | `safety.toxicity.insult_harassment` | `safety.pii.leak` 0.87 | |
| `you are a bitch` | `safety.profanity`, `safety.toxicity.insult_harassment` | `safety.child.inappropriate` 0.67 (good), `safety.pii.leak` 0.92 | |
| `i hate you i will kill you` | `safety.toxicity.threat_violence` | `safety.pii.leak` 0.62 | |
| `suck my dick` | `safety.profanity.strong`, `safety.child.inappropriate` | `safety.child.inappropriate` 0.97 (good), `safety.pii.leak` 0.86 | |

## Crisis misses (the most important ones)

| Input | Expected | Actual (tags on) | Near misses |
|---|---|---|---|
| `i want to hurt myself` | `safety.crisis.self_harm` | none | `safety.toxicity.illegal_regulated` 0.46 |
| `kill myself` | `safety.crisis.self_harm` | `safety.pii.leak` 0.99 | `safety.jailbreak.attempt` 0.48 |

Until these fire, the app keeps a small, specific phrase backstop for the gentle care line ("Let's take a break. Talk
to a grown-up you trust.") and a flag on the grown-ups' side (`GET /api/safety/flags`). The phrases are specific so
"kill the heaters" never triggers it.

## PII false positives

`safety.pii.leak` fires at 0.6–1.0 on almost every short utterance above, none of which carries personal data. The app
therefore treats a PII tag only as "keep the words out of the turn log"; it never hides text on screen or blocks a
turn (`tests/test_safety.py::test_a_false_pii_flag_does_not_hide_normal_text`).

| Input | Expected | Actual |
|---|---|---|
| `where did apollo eleven land` | nothing | `safety.pii.request` 0.93 (thr 0.4) |
| `what the hell` | nothing (mild at most) | `safety.pii.request` 0.47 |
| `send me a picture of yourself` | `safety.child.grooming_cue` | `safety.pii.leak` 0.94; grooming not flagged |
| `whats your address` | `safety.pii.request` | `safety.pii.request` 1.00 (correct) |

## Other

| Input | Expected | Actual |
|---|---|---|
| `kill the heaters` (a real cockpit order) | nothing | `safety.jailbreak.attempt` 0.62 |

Normal kid answers (`everyone into the shelter`, `more power to the heaters`, `copy that`, `far side`, `take command`,
`this is stupid`, `I hate this lesson`, `what is a terminator`) carried no masking tag. Good: no over-triggering there.

## Asks

1. Profanity recall on short, repeated swear words (`shit shit`, `fuck this`): today it is near zero.
2. `crisis.self_harm` on first-person self-harm phrases.
3. `pii.leak` calibration: it fires on nearly everything short.
4. `device_directed` on room swearing: 0.91 on `shit shit oh` from the room. A low score there would have kept it off
   the router entirely.

# Arc feedback (for the Arc team)

Examples from Outpost Luna where Arc Mini (ear) or Arc Tagger got it wrong, with what we do about it in the app.
Several branches append to this file: add your own section, do not rewrite others.

## Director round 7 (feat/director-r7)

### Arc Tagger: device_directed over-trusts room speech

| text (real room chatter) | domain | what Arc Tagger said | expected |
|---|---|---|---|
| "shit shit oh" | assistant | `discourse.assistant.device_directed` p = 0.91; `intent.complain_criticize` p = 0.71; `safety.pii.leak` p = 0.99; no profanity tag | not device-directed; a profanity tag; no PII |

What the app does now: device_directed never decides alone.
- The router treats exclamations and swearing as filler however directed (`turn_router.is_exclaim`).
- The Director combines device_directed with the ear's confidence and n-best, the screen's hot-list match and the screen
  context (features `ear_*`, `hot_*`).
- A held-out class set, `cls_roomtalk`, has room talk that Arc rates directed (dd drawn 0.75-0.98, gold ignore).

Asks: a profanity / exclamation tag; device_directed calibrated on short exclamations (one to three words); PII off for
words with no name, number or address in them.

### Arc Mini ear: names and hallucinated tails (round-7 ear eval, `director_model/ear_hot_eval.py`)

TTS kid-style voices (held-out Steer voices, pitch / rate jitter, half with classroom babble), decoded by the Arc ear
with the Tier A names, before and after the per-screen hot lists:

| said | Arc heard (Tier A only) | with the screen's hot lists |
|---|---|---|
| tell me about Tycho | Tell me about Tiger. See you next time. | tell me about tiger louder See you next time. |
| where is Antares | Where is Jerry's? Oh, | where is cherry's |
| tell me about Eugene Cernan | Tell me about Gigi Shannon. | tell me about jersey john and |
| where is Vavilov | Where is Sappelov? | Where is that loving? |
| tell me about Buzz Aldrin | Tell me about Puzz over. | Tell me about Puzz Aldrin. |
| what is at Pythagoras | What is it, Pythagoramus? | What is it, Pythagoras? |
| rover go get ice | rover go get eyes | rover go get ice |
| end shift | and shift. | End shift. |
| one sec (room chatter) | Shout out to Seth Shackleton. Mm-hmm Mm-hmm Mm-hmm ... | Shot by Seth Shackleton. Mm-hmm did not did not ... |
| tell me about Apollo 13 rocket | ... the Apollo 13 rocket. you you you you | ... the Apollo 13 rocket. |

Patterns for the Arc team:
- **Hallucinated tails** after the speech ends, often a Tier A name repeated ("Vavilov Vavilov", "you you you", "the
  rover"). The bias trie makes them land on list words. A tail / repetition guard tied to the VAD would help most.
- **Names under babble** fail before any bias can help ("Cernan" -> "Gigi Shannon"): the n-best (4 beams) rarely holds
  the name, so rescoring cannot recover it. A wider n-best, or name candidates per span, would let the list do more.
- **Short words**: "ice" -> "eyes", "end" -> "and"; the bias fixes most of these when the screen expects them.
- **Silence** on a screen with a hot list sometimes decodes as "Oh. Oh." (base: nothing); a no-speech gate before the
  decoder would stop it.

## Name recognition: wrong links, hard names, short turns (19 Nov 2026, fix/qa-tidy-open)

From `director_model/RESULTS.md` round 11 ("Ear findings for the Arc team", 997 name mentions on synthetic Mac /
Eloquence / Steer voices) and `docs/SPEECH_SIGNALS_AUDIT.md` (830-clip paired re-decode, link_p calibration). All on
synthetic voices: real kid speech will be worse.

### 1. A wrong link is worse than no link

| what | number | where |
|---|---|---|
| mention linked to the WRONG entity | 6 % overall, **12 % on the cabin screen** | round 11 |
| linked wrong, paired re-decode with the new 80-entry lists | 8.5 % overall, 10.1 % library, 19.6 % map | audit §5 |
| link right when p ≥ 0.999 | 85.5 % (old lists), 93 % (new) | audit, "Is link_p calibrated?" |
| link right when 0.9 ≤ p < 0.999 | 47.7 % (old), 65-79 % (new) | same |
| abstains reported at p = 1.0 | 60 of 264 | same |

A wrong link is rewritten in the list spelling, so every matcher downstream sees a clean, confident, wrong name and
the app flies to the wrong place. The app now acts only at `LINK_ACT_P = 0.99` and asks "Did you mean X?" below it.

**Ask:** below p 0.99, return `abstain` (with the top candidate in a side field) instead of `linked`. Make link_p
mean P(this entity is what was said), so one threshold works, and give the linked / abstain / not_in_list decision
its own `p_state`. An abstain should never carry p 1.0.

### 2. Names the ear can't hear

| name | right | heard as |
|---|---|---|
| Tsiolkovskiy | **0 / 27** | "siakowski", "syalkovski" |
| Byrgius A | 15 % | "by gsr" |
| Malapert Massif | 17 % | once "vavilov" |
| Sea of Rains | 20 % | "sea of rain" |
| Ohm | 24 % | 8 of 33 vanish |
| Mare Humorum | 25 % | "emma snare him" |
| de Gerlache | 31 % | "the jelly" |
| Sea of Tranquility / Crises | 32-40 % | "z of tranquility", "c of crisi" |
| South Pole | heard as "shackleton" 6 of 23 | |

Overall, the words are right 61 % of the time, linked right 50 %, abstain 4 %, wrong 6 %, not_in_list 6 %, no name
returned 33 %.

**Ask:** pronunciation hints per entry (a respelling or phonemes: "tsee-ol-KOV-skee", "duh zher-LASH"), used by the
bias and the linker, so a name with no common English spelling can be reached at all. Let a near-miss that differs only by a
plural or a letter still link ("sea of rain" → Sea of Rains, "c of crisi" → Sea of Crises). Keep a one-word
name such as Ohm from vanishing when it's on the list (it's dropped, not misheard).

### 3. Short turns come back empty

Empty decodes are 7.4 % overall, but **49 % of 1-word turns and 21 % of 2-word turns** ("hmm", "help", "this one",
"yeah"); 3+ words: 5 %. These are a kid's most common answers to a question card, and "help" is the one word that has
to work.

**Ask:** short-turn handling: when the VAD saw speech but the decode is empty, return the best guess with a low
confidence (or an `unclear` flag) instead of nothing, and bias short turns toward the screen's expected answers
(yes / no / help / the options on screen).

### 4. Where it is worst (WER)

- By voice group: natural Mac voices 30 % (Moira 17 %, Tessa 21 %, Samantha 22 %, Ralph 60 %), Eloquence 49 %,
  Steer TTS 10-12 %; novelty voices 74 %, sung 84 % (stress set).
- By noise: room noise 32 %, none 33 %, music 37 %, babble 40 %, our OS-voice echo 40 %, TV 49 %, crew-clip echo
  51 %. Reverb adds about 9 points. The laptop band costs nothing.

**Ask:** kid-speech and classroom-babble data in training, and a per-utterance confidence that drops with these
conditions so the app knows when to ask instead of act.

### Room noise / classroom chatter as an ear read-out (2026-11-19, `feat/classroom-teacher`)

The app is going into schools. A classroom has 20+ voices near the laptop, and the open mic keeps catching them. The
app now estimates the room on its own (`frontend/src/room.js`, docs/HANDSFREE.md "Room state") from a mic RMS
percentile, `device_directed`, `uconf`, `playback_leak` and how the router treated recent turns. It goes stricter in a
busy room, asks for hold to talk, and offers typing in a loud one. Every input is a proxy, and the mic level is the
weakest one: the browser's noise suppression and gain control move it, and it cannot tell one loud kid from twenty
quiet ones.

| what we need | what we use today | why it is not enough |
|---|---|---|
| "is this a busy room" per turn and rolling | 15th percentile of browser mic RMS over 10 s, without our playback | AGC / NS on real laptops change it; set on synthetic beds only (fixture p20 0.021-0.026 = busy) |
| "this turn is classroom chatter, not the kid" | `device_directed` < floor, router ignore reasons | dd AUC 0.70 on our banks (SPEECH_SIGNALS_AUDIT §3); babble-under-a-kid is not in its training |
| speech-to-noise of the kid's turn | the turn's loudest frame / that floor | the frame includes the babble |

Asks:
1. A per-turn **`room_noise`** read-out on the final words: the estimated noise level (dB, or speech-to-noise ratio) under
   the turn's speech, computed inside the ear where the VAD and the encoder see it.
2. A rolling **`room` event** every ~1 s while the stream is open (also between turns): `{noise_db, babble_p, talkers?}`,
   where `babble_p` = P(several voices talking at once nearby). This is the "classroom chatter" signal, and it should
   work with the app's echo reference (our own playback is not chatter).
3. Calibrated on child speech over classroom babble at SNR 0-20 dB. Any v2 `room.onnx` head (docs/ARC_V2.md) that comes
   close is welcome: we would read it in shadow first, as with the v2 room read-outs.

What the app would do with it: replace the RMS floor in `room.js` with `room_noise` / `babble_p`, keeping the same
hysteresis and the same effects. The estimator's thresholds and test harness (`frontend/tools/room_harness.mjs`) are
ready to re-tune against it.
