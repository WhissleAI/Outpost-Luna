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
