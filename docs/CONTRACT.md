# Outpost Luna backend API contract

Backend: FastAPI in `backend/app/` (`main.py`). The Director is `director.py`, the claim check `claims.py`,
Moon Moments `moments.py`. Fact sheet `backend/data/facts.json`, glossary `backend/data/glossary.json`.

## POST /api/ask

Request (`context` and each of its fields optional):

```json
{"text": "what did the astronauts say about Hertzsprung",
 "context": {"last_place": "orientale", "playing": {"clip_id": "hertz", "t": 31.5}}}
```

There is no affect field (D6, `docs/BRAIN.md` §6a): an old client's `emotion` is ignored.

Response (always every key):

```jsonc
{"action": "guard" | "fly" | "play" | "say" | "ask" | "view" | "tour",
 "say": "...",                         // final, claim-checked text the guide speaks ("" allowed)
 "place": "hertzsprung" | null,        // place id from /api/places
 "view": {"lat": 2.6, "lon": -128.7} | null,
 "moment": Moment | null,              // see below
 "ask": {"question": "Did you mean Vavilov?", "options": ["vavilov"]} | null,
 "claims": [{"text": "...", "status": "verified" | "impression" | "removed", "source": "..."}],
 "readout": {"available": true, "act": [...], "intent": [...], "mentions": [...], "numbers": [...],
             "pii": [...], "hard_pii": [...], "complete": true, "ms": 3.1},   // Arc Tagger read-out, as before
 "source": "alias+llm+claimcheck",     // how the decision was made (debug only)
 "corrected": false,                   // kid self-corrected ("Tycho, no wait, Copernicus")
 "places": ["apollo15_lrv", ...]}      // ONLY on action "tour" (additive): artifact ids, oldest first
```

`readout` also carries `pii_spans: [{"type", "text"}]` (additive): the words behind each PII tag. The guard ignores
hard-PII spans that are Moon words (Arc tags "Moon" in "Apollo 16 Moon buggy" as a street address): a span is
ignored when it names a gazetteer place/artifact, or is only gazetteer/hardware words with no digits. Real addresses,
phones, emails and "my name is…" are still guarded.

What the client does per action:

| action | client |
|---|---|
| `guard` | Speak `say`. Nothing else (no place, nothing sent anywhere) |
| `fly` | Turn the globe to `view`, highlight `place`, speak `say`. If `moment` is set, offer it ("Hear the crew?") |
| `play` | Fly to `view`, speak `say` (one bridge line), then play `moment` audio from `t0` to `t1` |
| `say` | Speak `say`. If `place`/`moment` are set (misconception corrections), fly there and offer the moment |
| `ask` | Speak `say` (= `ask.question`), preview `view`; show `ask.options` as buttons. A tap re-asks with that place name |
| `view` | Turn the globe to `view` (near side 0,0 / far side 0,180), speak `say` |
| `tour` | Show/highlight every artifact in `places` (ids from `/api/places`), speak `say`. `place`/`view` are null |

### Hardware on the Moon (artifacts)

- Naming or tapping an artifact (the frontend sends `text` = the artifact's `name`; aliases like "Eagle",
  "Challenger", "LRV 2", "Apollo 16 moon buggy", "Surveyor three", "where did Apollo 11 land" also work) → `fly`,
  `say` = the artifact's first-person `story`, claim-checked sentence by sentence against facts.json (the story
  verbatim if nothing survives). `moment` = its first `voices` clip when it has one (offer "Hear Charlie Duke?").
- "who left this here" / "who drove it" with `context.last_place` = an artifact (or naming one) → `play` its
  `voices` moment (`say` = crew names + "Listen to <who>!"), else `fly` with `say` = the crew names, or `say`
  "No one! … robot spacecraft" for robotic hardware.
- "show me the rovers" / "landers" / "crash sites" / "instruments" / "what's left on the Moon" / "show me the
  hardware" → `tour`. "who drove the rovers" → `tour` whose `say` lists every crew.
- Mission sounds ("play the launch", "what did liftoff sound like", "play the splashdown", "the go/no-go poll",
  "translunar injection", "Apollo 13 distance record", "loud and clear", "can I hear Charlie Duke / Jim Lovell") →
  `play` a moment from the NASA Artemis Audio Library `voices` clips (`source: "sounds"`).
- Voice moments for artifacts have ids `<clip_id>-voice-<artifact_id>` (e.g. `duke-voice-apollo16_lrv`) and resolve
  at `GET /api/moments/<id>`. Their `t0`/`t1` are the artifact's `voices` span.

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
- `GET /api/places` → `{"places": [...]}`. Every item: `{id, name, lat, lon, diameter_km, fact, estimated, aliases,
  kind}` with `kind: "feature" | "artifact"`.
  - **Features** (landforms, places.json) have exactly the old fields plus `kind: "feature"`.
  - **Artifacts** (hardware, `backend/data/artifacts.json`) also carry:
    `type: "lander"|"rover"|"impact"|"instrument"|"memorial"` (use it for marker colour and the card label;
    artifacts.json stores it as `kind`, the API renames it to `type` so `kind` stays the place kind),
    `mission`, `agency` ("NASA", "USSR", "CNSA"), `landed` (UTC date "YYYY-MM-DD" of landing/impact/deployment),
    `status`, `story` (first person, kid level), `what_it_did`, `science`, `crew: [names]` ([] = robotic),
    `sources: [{title, url}]` (every number in story/science is on one of these pages),
    `voices: [{clip_id, t0, t1, who, why}]` (a real person's voice in a `/api/clips` clip; `who` is their name),
    `image: null` (reserved: a local `/media/img/artifacts/<id>.jpg` when one is added). For artifacts `fact` = `story`
    and `diameter_km` = 0.
- `GET /api/clips` → `{"clips": [...]}` raw index (unchanged).
- `GET /api/health` → `{"ok", "places", "artifacts", "clips", "moments", "facts", "glossary", "llm", "model_server"}`.
- `GET /api/clips` now includes 14 `set: "voices"` clips (NASA Artemis Audio Library: Charlie Duke, Jim Lovell,
  liftoff, go/no-go poll, full send, good burn, TLI, Apollo 13 record, splashdown, loud and clear, 4 crew interviews),
  with `who` set on single-speaker clips; their moments use `who` as `speaker`.

## Deviations from the brief

- `places` appears only on `tour` responses (other responses keep exactly the old key set).
- Artifacts' hardware kind is `type` in the API (artifacts.json `kind`); `image` is always null for now.
- `moment` carries two extra keys, `claims` and `kid_safe` (additive).
- The old `/api/ask` keys `text`, `lead`, `clip`, `crew_available` are gone; use `say` and `moment`.
