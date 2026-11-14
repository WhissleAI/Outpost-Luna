# The local brain: no cloud LLM

Outpost Luna speaks **limited content from structured knowledge**. There is no Claude/Anthropic (or other cloud LLM)
call at runtime; the only external API is NASA's. Two parts replace the LLM:

| Part | Where | Job |
|---|---|---|
| Knowledge cards + templates | `backend/app/knowledge/cards.py` | **What to say.** Every line is filled from a sourced data field. |
| Tiny embedder | `model_server/app/embed.py` (`POST /v1/embed`) | **What the kid means**, when rules and Arc Tagger don't settle it. |

The Director stays rules-first (privacy guard, mission NLU, misconceptions, glossary, Earthrise, sounds, tours, place
linking, crew moments). The brain fills the two places the LLM used to: the guide's line about a place, and the
"nothing matched" fallback. Mission NLU and Academy grading get an embedding fallback too.

## 1. Knowledge cards

Built at startup (cheap, no model calls) from the data the app already ships. **No new facts live in code.**

| Kind | From | Attributes |
|---|---|---|
| `place` (23) | `places.json` + `facts.json` | size, where, when, who, why, what, about |
| `artifact` (36) | `artifacts.json` | story, what (what_it_did), science, who (crew), when (landed), where (status) |
| `term` (25) | `glossary.json` | what |
| `concept` (7) | capcom `TERMS`, `mission/sites.json`, `mission/radiation.json` | what (power, life support, dose, storms, shelter, comm windows, ice) |
| `site` (5) | `mission/sites.json` | what, sun, earth, ice |
| `lesson` (7) | `academy/course.json` facts | about, what |
| `misconception` (3) | glossary + facts lines | misconception (cheese, far side never sunlit, no craters) |

A card: `{id, kind, title, aliases, attributes:{...}, answers:{attribute:[2-3 lines]}, sources:[{title,url}],
questions:{attribute:[canonical phrasings]}, place}`.

- **Answers** are either data sentences verbatim (`facts.json` fact lines, artifact `story`/`what_it_did`/`science`,
  site `notes`, lesson facts) or templates whose slots are data fields (`"{title} is about {diameter_km} km across."`,
  `"{crew} landed it, on {mission}."`, `"{site} gets sunlight about {sunlight_pct}% of the time."`). Estimated
  (crew-proposed) places never get a size: their size line says it is only an estimate.
- **Rotation:** the first line per attribute is the canonical one (the definition, the size); asking again in the same
  session (`ctx.session`) rotates deterministically to the next true line.
- **Claim check stays** as the safety net: place lines are re-read by Arc Tagger (`claims.verify_draft`); a test
  (`test_every_place_template_passes_the_claim_check`) asserts every place template passes. Non-place cards (terms,
  concepts, sites, lessons) carry their card source as the claim source.
- **style_hint:** every `say` decision carries a `style_hint` (explain / story / question / alert) the Steer TTS policy
  can use.

## 2. The embedder

`POST /v1/embed {texts:[...], kind:"query"|"doc"}` → `{vectors:[[384 floats, L2-normalized]], dim, model, ms}`.

- **Model:** `sentence-transformers/all-MiniLM-L6-v2`, ONNX Runtime + `tokenizers` (no torch at runtime), mean
  pooling, int8 dynamic quantization (`model.int8.onnx`, 23 MB; fp32 `model.onnx` is the fallback).
- **Weights:** `cd model_server && uv run python tools/export_embedder.py --int8` (downloads the upstream
  `onnx/model.onnx`, or exports the cached safetensors with torch.onnx; `--int8` needs `uv run --with onnx`). Stored in
  `model_server/models/minilm/` (gitignored).
- **Switch:** `EMBED=on|off` (default on). Fails open: no model → `/v1/embed` 503, the reason in `/health`, and the
  backend answers from rules + card aliases only.
- **Cost (measured, M-series Mac):** load 0.15 s, **+53 MB RSS** in the model server; a single query embed is
  ~4-5 ms over HTTP, search over 1,286 card questions is a numpy dot product (<1 ms).
- **Model-agnostic API:** Head Start's shared `/v1/embed` will serve EmbeddingGemma behind the same request shape
  (`kind` picks its query/document prompt; MiniLM ignores it).
- The backend embeds the card question bank (1,286 phrasings) and the command bank (415 examples) once and caches the
  vectors under `backend/data/cache/` (gitignored, keyed by a hash of the texts). Startup warms both in the background.

## 3. Question → answer (`knowledge/answer.py`)

1. **Entity:** the gazetteer link (aliases + Arc Tagger mentions, from the Director) or a card alias in the words.
   A named place beats generic glossary words in the same question ("how big is Integrity crater").
2. **Attribute rules:** "how big/wide/deep" → size, "when/how old" → when, "who" → who, "where/which side" → where,
   "science/discover" → science, "why/what for" → why, "story/what happened" → story, "what is/mean" → what,
   "tell me" → about.
3. One entity whose card has that attribute → answer from the template, no embedding (`source: card+rules`).
4. Otherwise the embedder's nearest canonical question (entity cards get +0.10):

| Cosine | Behaviour |
|---|---|
| ≥ 0.62 (`ACCEPT`) | answer (fly to the place if the card has one) |
| 0.55–0.62 (`ASK_FLOOR`–`ACCEPT`) | "Did you mean how big Tycho is or where Tycho is?" with tap-able options that send the canonical question (a label's own "?" is dropped in the spoken line) |
| 0.48–0.55 (`ASK`–`ASK_FLOOR`) | "I don't know that one yet." Here the top two are near-ties between unrelated cards ("weirdest thing about moon dust": storm shelter 0.507 vs the no-craters myth 0.506) |
| 0.30–0.48 | "I don't know that one yet. Want to hear about {nearest card}?" |
| < 0.30 | "I don't know that one yet. Try: ..." |

## 4. Mission commands (`mission/nlu.py`)

Rules first, unchanged. When they find nothing: nearest example in `data/mission/command_bank.json` (415 phrasings
generated by `backend/tools/gen_command_bank.py` from the NLU rule tables + contract command types + kid-style shapes
like "the plants look sad"). The example gives the **shape**; slots are re-read from the kid's words (load synonyms,
Arc/word numbers, task words, query words; "need/more" vs "less" picks the sign) and `valid()` checks the schema.
Guards: cosine ≥ 0.55, the top two examples must agree on the command unless 0.03 apart, and a negated sentence never
borrows a positive example.

## 5. Academy

Keyword rules first, unchanged. For keyword steps, a paraphrased readback passes when the mission NLU reads **the
same Command** from it as from the quoted order ("okay I'll make the radiation protection forty percent" =
"set the shields to 40 percent"); groups holding a number or a radio protocol word (roger, copy, say again) must
still be heard exactly. Steps without a quoted order fall back to embedder similarity ≥ 0.72 (conservative: MiniLM
scores "the rover is staying home" closer to "Send the rover for ice" than a true paraphrase).

## 6. Measured accuracy (`backend/tools/eval_brain.py`)

Run against the live model server: `MODEL_SERVER_URL=http://127.0.0.1:8270 uv run python tools/eval_brain.py`.

**80 kid questions** (`tests/eval/kid_questions.json`: Moon library places and hardware, glossary, mission concepts
and sites, Academy facts, misconceptions, 10 off-topic):

| Metric | Result |
|---|---|
| Top-1 card+attribute correct (all 80) | 61 (76%) |
| In-scope (70) answered correctly | 87%; 89% counting "Did you mean" with the right option |
| Wrong answers | 7 (9%) |
| Ask rate | 1 (1%; the other ask, 0.523 and wrong, is now under `ASK_FLOOR`) |
| "I don't know" rate | 11 (14%): the 10 off-topic questions, plus that sub-floor ask; 0 off-topic questions answered |

Typical misses: "what's the biggest crater" → the no-craters misconception card; "who drove the first moon car" →
the Apollo 16 rover story; "what science did the Apollo 12 experiments do" (the gazetteer links Intrepid, not
ALSEP); "what did LCROSS find when it crashed" ("when" read as the attribute).

**40 held-out mission commands the rules miss** (`tests/eval/commands_heldout.json`, e.g. "the veggies are hungry for
electrons", "strengthen the force field", "rover, home time"):

| | Correct | Wrong command fired | Nothing |
|---|---|---|---|
| Rules | 0/40 | 0 | 40 |
| Rules + embedder | 15/40 (38%) | 3 | 22 |

The threshold is deliberately high: doing nothing ("say that again") is better than a wrong order. Wrong fires seen:
"park the buggy back in the garage" → collect ice, "the crew feels sleepy and stuffy" → heaters, "the rover should
drive somewhere new" → return.

**Latency:** questions answered by rules: ~0.1 ms. Embedder path: median 4.9 ms, p95 9 ms (HTTP embed + search).
Command fallback: median ~4 ms.

## 7. What the app can't answer (by design)

- Anything not in the data: no open-domain chat, homework, jokes, other planets' trivia. The kid hears "I don't know that one yet" plus a nearby card to explore.
- No free composition: it never combines two facts into a new claim, compares places ("is Tycho bigger than
  Copernicus?") or does arithmetic. Each answer is one card line.
- Follow-ups use the Director's `last_place` context only; there is no conversational memory beyond that.
- Paraphrase understanding is MiniLM-sized: odd metaphors ("I'm turning into a popsicle") often miss. The Arc Tagger
  `space` domain + list context (ARC_SPACE_DATA_PLAN) should take over entity and attribute detection and leave the
  embedder only for these.
