# Ask the Moon

A voice-first 3D Moon explorer for kids, built for NASA Space Apps 2026 (Nov 14–15). A kid says "show me the giant
bullseye" and the Moon turns to Mare Orientale. They ask what the astronauts said, and real Artemis II crew audio
plays while the globe follows each place the crew mentions.

## Layout: three services

| Part | Stack | Port | Owns |
|---|---|---|---|
| `frontend/` | Vite 5, three.js 0.160 (npm) | 5173 (dev) | Globe, voice in/out (Web Speech), crew player, missions. No model or data logic |
| `backend/` | FastAPI, pydantic-settings, httpx, rapidfuzz, Anthropic SDK; uv | 8100 | Places (gazetteer), crew index, `/api/ask` (the turn resolver, first version of the Director), NASA media, and the built frontend |
| `model_server/` | FastAPI, pydantic-settings; uv | 8200 | **The only process that loads models.** Arc Tagger v0.3 now (native int8, a pool of handles per domain); Arc audio metadata and embeddings next |

```
browser ──► frontend (Vite :5173) ──/api, /media──► backend (:8100) ──/v1/tag──► model_server (:8200)
                                                       │                           └─ Arc Tagger v0.3 (native C)
                                                       ├─ data/places.json      (gazetteer)
                                                       ├─ data/index/clips.json (crew words + tags, built by `make index`)
                                                       └─ data/media/           (NASA audio + LRO Moon map)
```

The backend fails open: if the model server is down, `/api/ask` still answers from the gazetteer, and the read-out
says "rules only". The model server is a plain FastAPI app, so it can later run unchanged as a Ray Serve deployment
(`@serve.ingress(app)`) with its own replicas. Head Start can point at it instead of loading its own copy.

## Commands

```bash
make setup      # uv sync (backend, model_server) + npm install (frontend)
make data       # download NASA media (Moon map + crew clips, ~18 MB)
make dev        # model server + backend + frontend together → http://localhost:5173
make index      # rebuild the crew index with Arc Tagger (model server must be running)
make test       # model_server + backend tests
make build      # frontend → frontend/dist, then served by the backend at http://localhost:8100
make health     # check all three
make models | backend | frontend   # run one part on its own
```

Requirements: uv, Node 20+, macOS for the Arc Tagger build that is used now. By default it is Head Start's
`libarctag.dylib` and `models/arctag`; override with `ARCTAG_LIB` / `ARCTAG_MODEL_DIR` in `.env`. Optional:
`ANTHROPIC_API_KEY` in `.env` turns on the LLM fallback for questions the gazetteer can't place.

## How a question is answered (`POST /api/ask`)

1. The model server tags the text with Arc Tagger (`assistant` domain), giving acts, mentions, PII and numbers in
   about 1–15 ms.
2. Private details (street address, phone, email, a name after "my name is") → `guard`. Nothing is looked up or
   stored.
3. Self-corrections ("Tycho, wait no, I mean Copernicus") → only the words after the correction are used.
4. A place is found by alias in the gazetteer, or by fuzzy-linking a tagger mention (rapidfuzz: "Oriental" →
   Orientale).
5. "What did the astronauts say…" → `play`: the crew clip that mentions the place most, from its first mention.
6. Otherwise the LLM fallback (if configured), or "I don't know that one yet".

The response carries the tagger read-out, which the UI shows under each answer.

## Crew index (`make index`)

`backend/pipeline/build_index.py` sends each clip's words to the model server (`news` domain).
- **Places:** entity spans are linked to the gazetteer. Spans that don't link are dropped, because the tagger finds
  lunar names well but types them as person or organization.
- **Numbers:** number spans become NUMBER tags.
- **Boundaries:** utterance ends and speaker changes are saved for cutting crew moments.
- **Rule lists:** color, geology word, direction and awe tags are still small rule lists until a lunar tagger domain
  exists.
- **Provenance:** each tag records its source (`arc`, `gazetteer`, `rules`).

Current build: 28 places linked from Arc Tagger spans, 4 from the gazetteer fallback, 15 numbers, 22 tagger spans
left unlinked.

New clips:
1. Add the URL to `backend/pipeline/fetch_media.sh` and a row to `backend/data/clips_manifest.json`.
2. Run `make data`, `make transcribe` (mlx-whisper; Deepgram is the plan) and `make index`.

## Roadmap

`docs/REVAMP.md` covers the v2 plan:
- Deepgram for the words;
- Arc audio metadata, and emotion from the Whissle metadata model;
- a claim-checked fact sheet;
- the Director, which decides when the guide talks and when the astronauts do;
- narration.

`backend/pipeline/probe_tagger.py` reproduces the tagger measurements the plan cites.

## Caveats

- Integrity and Carroll are names the crew proposed, not IAU-approved names. Their locations are estimates from the
  crew's spoken directions.
- NASA media is used under NASA's media guidelines and must not imply NASA endorsement.

Data: [NASA Artemis Audio Library](https://www.nasa.gov/artemisaudio/),
[NASA SVS CGI Moon Kit](https://svs.gsfc.nasa.gov/4720/).
