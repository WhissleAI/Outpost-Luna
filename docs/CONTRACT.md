# Ask the Moon backend API contract

Backend: FastAPI in `backend/app/` (`main.py`). The Director is `director.py`, the claim check `claims.py`,
Moon Moments `moments.py`. Fact sheet `backend/data/facts.json`, glossary `backend/data/glossary.json`.

## POST /api/ask

Request (`context` and each of its fields optional):

```json
{"text": "what did the astronauts say about Hertzsprung",
 "context": {"last_place": "orientale", "emotion": "confused", "playing": {"clip_id": "hertz", "t": 31.5}}}
```

`emotion` is one of `confused | frustrated | bored | excited`.

Response (always every key):

```jsonc
{"action": "guard" | "fly" | "play" | "say" | "ask" | "view",
 "say": "...",                         // final, claim-checked text the guide speaks ("" allowed)
 "place": "hertzsprung" | null,        // place id from /api/places
 "view": {"lat": 2.6, "lon": -128.7} | null,
 "moment": Moment | null,              // see below
 "ask": {"question": "Did you mean Vavilov?", "options": ["vavilov"]} | null,
 "claims": [{"text": "...", "status": "verified" | "impression" | "removed", "source": "..."}],
 "readout": {"available": true, "act": [...], "intent": [...], "mentions": [...], "numbers": [...],
             "pii": [...], "hard_pii": [...], "complete": true, "ms": 3.1},   // Arc Tagger read-out, as before
 "source": "alias+llm+claimcheck",     // how the decision was made (debug only)
 "corrected": false}                   // kid self-corrected ("Tycho, no wait, Copernicus")
```

What the client does per action:

| action | client |
|---|---|
| `guard` | Speak `say`. Nothing else (no place, nothing sent anywhere) |
| `fly` | Turn the globe to `view`, highlight `place`, speak `say`. If `moment` is set, offer it ("Hear the crew?") |
| `play` | Fly to `view`, speak `say` (one bridge line), then play `moment` audio from `t0` to `t1` |
| `say` | Speak `say`. If `place`/`moment` are set (misconception corrections), fly there and offer the moment |
| `ask` | Speak `say` (= `ask.question`), preview `view`; show `ask.options` as buttons. A tap re-asks with that place name |
| `view` | Turn the globe to `view` (near side 0,0 / far side 0,180), speak `say` |

Client-side behaviours (not actions): WAIT while `readout.complete` is false and the ASR hasn't ended the turn;
NUDGE after 8 s of silence; PAUSE_EXPLAIN when a playing moment passes a `moment.jargon[i].t` (at the next
utterance end, max 1 per 30 s, none in the first 5 s). Send `context.last_place` = the last `place` you got so
"what did the crew say about it?" works, and `context.playing` while a clip is playing.

Claim `status`: `verified` matches the fact sheet (source given); `impression` is a crew experience we can't
check (colors, numbers in crew speech); `removed` was in the LLM draft but failed the check (source says why) and
is NOT in `say`. Show only `verified` in UI if you show claims at all.

### Examples (live, Arc Tagger + Haiku on)

`{"text": "show me Tycho"}` →
```json
{"action":"fly","say":"Tycho is a crater on the Moon's near side, about 85 km wide. Its bright rays stretch over 1,500 km across the Moon!",
 "place":"tycho","view":{"lat":-43.3,"lon":-11.2},"moment":null,"ask":null,
 "claims":[{"text":"Tycho is a crater on the Moon's near side, about 85 km wide.","status":"verified","source":"IAU Gazetteer of Planetary Nomenclature"},
           {"text":"Its bright rays stretch over 1,500 km across the Moon!","status":"verified","source":"NASA LRO / LROC"}],
 "readout":{"...":"..."},"source":"alias+llm+claimcheck","corrected":false}
```

`{"text": "what did the astronauts say about Hertzsprung"}` →
```json
{"action":"play","say":"The crew saw this from Orion. Listen!","place":"hertzsprung","view":{"lat":2.6,"lon":-128.7},
 "moment":{"id":"mare-10","clip_id":"mare","t0":221.94,"t1":245.62,"speaker":"crew","places":["hertzsprung"],
           "text":"But the lighter part of the wedge ... Go to Hertzsprung. ...",
           "jargon":[{"t":231.32,"word":"albedo","explain":"How bright or dark a surface is in sunlight."}],
           "awe":0.0,"claims":[],"kid_safe":true},
 "ask":null,"claims":[],"readout":{"...":"..."},"source":"alias","corrected":false}
```

`{"text": "is the moon made of cheese?"}` →
```json
{"action":"say","say":"Not cheese! The Moon is made of rock and dust. But the crew did say one place looked yellow, like a snowy mountain.",
 "place":"aristarchus","view":{"lat":26,"lon":-51},"moment":{"id":"aristarchus-01","clip_id":"aristarchus","t0":14.22,"t1":31.14,"...":"..."},
 "ask":null,"claims":[{"text":"Not cheese! ...","status":"verified","source":"fact sheet (misconception)"}],"source":"misconception","corrected":false}
```

`{"text": "show me Vavilof"}` →
```json
{"action":"ask","say":"Did you mean Vavilov?","place":"vavilov","view":{"lat":-0.8,"lon":-138.8},"moment":null,
 "ask":{"question":"Did you mean Vavilov?","options":["vavilov"]},"claims":[],"source":"arc+link","corrected":false}
```

`{"text": "my name is Maya and I live at 42 Oak Street"}` →
`{"action":"guard","say":"Let's keep names and addresses private! Ask me about a place on the Moon instead.","place":null,...}`

## Moment

```jsonc
{"id": "hertz-00", "clip_id": "hertz", "t0": 0.0, "t1": 24.68,   // seconds in the clip's audio (/api/clips file)
 "speaker": "crew",                                              // name when diarization is available, else "crew"
 "places": ["hertzsprung"], "text": "...",
 "jargon": [{"t": 3.1, "word": "swirl", "explain": "A bright, curly pattern painted on the Moon's surface."}],
 "awe": 0.0,                                                     // 0..1 from audio_meta.json when present, else 0
 "claims": [{"kind": "color", "text": "yellow", "status": "impression", "source": "crew"}],   // additive
 "kid_safe": true}                                               // additive; unsafe moments are never ranked/played
```

Moments are 8–25 s, cut on Arc utterance boundaries (consecutive utterances merged). An utterance that is itself
longer than 25 s is split at a sentence end, or at its longest pause when the transcript has no punctuation.

## Other endpoints

- `GET /api/moments?place=<id>` → `{"moments": [Moment, ...]}` ranked best first, max 5 (no `place`: all moments).
- `GET /api/moments/<id>` → `Moment` (404 if unknown).
- `GET /api/places` → `{"places": [{id, name, lat, lon, diameter_km, fact, estimated, aliases}]}` (unchanged).
- `GET /api/clips` → `{"clips": [...]}` raw index (unchanged).
- `GET /api/health` → `{"ok", "places", "clips", "moments", "facts", "glossary", "llm", "model_server"}`.

## Deviations from the brief

- `moment` carries two extra keys, `claims` and `kid_safe` (additive).
- The old `/api/ask` keys `text`, `lead`, `clip`, `crew_available` are gone; use `say` and `moment`.
