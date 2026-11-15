# Outpost Luna: Junior Astronaut Mission Trainer

A voice-first Moon mission trainer, built for NASA Space Apps 2026 (Nov 14–15) on the challenge **"Build a Junior
Astronaut Mission Trainer"**. Inspired by NASA's Artemis program and built on NASA open data. Not affiliated with or
endorsed by NASA. (Formerly `ask-the-moon`.)

**One story.** Artemis II flew its crew around the Moon in April 2026. Artemis III, the first landing near the south
pole, hasn't happened yet. The kid trains to help run **Outpost Luna**, a south-pole base for the crews who come after.
1. **Flight School (Academy).** The kid picks a call sign (kept on the device, never sent). Short lessons in tracks
   (Foundations, Outpost systems, Field skills) with CAPCOM as mentor: a story beat, 2–4 voice/tap steps, a patch.
   Taught with real Artemis II crew audio and the hardware left on the Moon.
2. **Check ride.** The first solo shift, in a simplified cockpit on the real simulator with the real May 2024 storm.
   Passing earns the Mission Commander patch.
3. **Mission.** Command Outpost Luna for 10 days from inside the cabin: the NASA Moon globe through the window
   (ORBIT / SITE / ROVER views), an instrument panel below (display units, guarded hab levers, shield knob, caution &
   warning with master alarm, PTT Houston, END SHIFT). Real Sun and Earth positions (JPL Horizons) and real solar
   storms (NASA DONKI). Flight School lessons come back as events ("Remember Lesson 4? That's a solar storm").
4. **Debrief, then replay.** What happened, which lessons came back, the real data behind each event; fly it again or
   try another site.

Story copy lives in `frontend/src/story.js`. Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA.

The **Moon library** (the original explorer: 3D Moon, 36 pieces of hardware with sources, Artemis II crew moments) is a
small button inside the app, used by the lessons.

## Download for Mac
**[Download Outpost Luna for Mac](https://www.dropbox.com/scl/fi/o7ywoe58gs7afy10fgolr/Outpost-Luna-0.1.0-arm64.dmg?rlkey=q3n2qkq2atguhbnnehkzqnff7&dl=1)** (Dropbox; mirror: [GitHub Releases](https://github.com/WhissleAI/Outpost-Luna/releases/latest)) (Apple silicon, 647 MB,
about 1.5 GB once installed). Signed and notarized by Whissle LLC. Open the DMG, drag Outpost Luna to Applications, open
it. It runs with no internet, no account and no keys: every model and the NASA crew audio are inside the app. The NASA
video files download once when the computer is online; the NASA YouTube clips need a connection. Each release lists the
DMG's SHA-256.

Windows: build it from source with one command ([docs/BUILD_WINDOWS.md](docs/BUILD_WINDOWS.md)). Website:
<https://whissleai.github.io/Outpost-Luna/> (source in `site/`, published with `scripts/publish_site.sh`).

## Layout: three services

| Part | Stack | Port | Owns |
|---|---|---|---|
| `frontend/` | Vite 5, three.js 0.160 (npm) | 5173 (dev) | Globe, voice in/out (Web Speech), crew player, missions. No model or data logic |
| `backend/` | FastAPI, pydantic-settings, httpx, rapidfuzz, numpy; uv | 8100 | Places (gazetteer), crew index, `/api/ask` (the turn resolver, first version of the Director), NASA media, and the built frontend |
| `model_server/` | FastAPI, pydantic-settings; uv | 8200 | **The only process that loads models.** Arc Tagger v0.3 (native int8, a pool of handles per domain) and Arc v1.1 Mini audio metadata (`ARC_META=mini|off`; `POST /v1/meta`, `WS /v1/stream`: act, intent, device_directed, command_complete, speaker, audio/bio events, awe). Measured on M3 Pro (machine under load avg ~13 from other jobs): Arc load 6-12 s, process RSS ~0.35 GB idle / 0.9 GB peak with both models; `/v1/meta` RTF 0.03-0.06 (a 344 s clip in 14 s); live stream RTF 0.25-0.4 in-process, 0.9-1.1 through the server with 1-4 real-time sessions, metadata lag p50 1.2-1.4 s (Head Start measured RTF 0.10 on an idle machine). Emotion: off (no local model, see docs/REVAMP.md §10). Embeddings next |

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
make data       # download NASA media (Moon map + 74 crew clips, ~0.5 GB; backend/pipeline/fetch_media.py)
make dev        # model server + backend + frontend together → http://localhost:5173
make index      # rebuild the crew index with Arc Tagger (model server must be running)
make test       # model_server + backend tests
make build      # frontend → frontend/dist, then served by the backend at http://localhost:8100
make health     # check all three
make models | backend | frontend   # run one part on its own
make desktop-mac   # the offline desktop app (Electron + embedded Python + every model) -> desktop/dist/*.dmg
```

## Desktop app (offline)

One installer that runs with no internet: Electron, an embedded Python, the backend, the model server, every model and
the NASA audio. Built locally from a fresh clone, no keys or tokens. Details: [docs/DESKTOP.md](docs/DESKTOP.md).

### Build Mac

Needs Xcode command line tools, Node 22+, uv, CMake, ~6 GB free.

```bash
bash desktop/scripts/build-mac.sh     # -> desktop/dist/Outpost Luna-<version>-arm64.dmg
```

### Build Windows (untested; the first build will validate it)

Needs Node 22+, uv, CMake, Git, VS 2022 Build Tools (C++) or LLVM, ~6 GB free. Step-by-step:
[docs/BUILD_WINDOWS.md](docs/BUILD_WINDOWS.md).

```powershell
powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1   # -> desktop\dist\Outpost Luna Setup <version>.exe
```

Requirements: uv, Node 20+, macOS for the Arc Tagger build that is used now. By default it is Head Start's
`libarctag.dylib` and `models/arctag`; override with `ARCTAG_LIB` / `ARCTAG_MODEL_DIR` in `.env`. No cloud LLM:
questions the rules can't place go to the local brain (knowledge cards + the model server's tiny embedder; one-time
`cd model_server && uv run python tools/export_embedder.py --int8`). See [docs/LOCAL_BRAIN.md](docs/LOCAL_BRAIN.md).

## How a question is answered (`POST /api/ask`)

1. The model server tags the text with Arc Tagger (`assistant` domain), giving acts, mentions, PII and numbers in
   about 1–15 ms.
2. Private details (street address, phone, email, a name after "my name is") → `guard`. Nothing is looked up or
   stored.
3. Self-corrections ("Tycho, wait no, I mean Copernicus") → only the words after the correction are used.
4. A place is found by alias in the gazetteer, or by fuzzy-linking a tagger mention (rapidfuzz: "Oriental" →
   Orientale).
5. "What did the astronauts say…" → `play`: the crew clip that mentions the place most, from its first mention.
6. Otherwise the local brain: the nearest knowledge card + attribute (embedder), "Did you mean A or B?", or an honest
   "I don't know that one yet".

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
1. Add a row (with its URL) to `backend/data/clips_manifest.json`; `make data` (`backend/pipeline/fetch_media.py`) fetches it.
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
