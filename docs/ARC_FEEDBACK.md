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
