# Ask the Moon: one set of commands for all three parts.
#   frontend/      Vite + three.js           :5173  (dev)
#   backend/       FastAPI app API            :8100
#   model_server/  FastAPI, owns the models   :8200
SHELL := /bin/bash
.DEFAULT_GOAL := help

help:            ## List commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

setup:           ## Install all dependencies (uv + npm)
	cd model_server && uv sync
	cd backend && uv sync
	cd frontend && npm install

data:            ## Download NASA media (Moon map + crew clips)
	bash backend/pipeline/fetch_media.sh

transcribe:      ## Word-timed transcripts for any new clips (mlx-whisper)
	bash backend/pipeline/transcribe.sh

transcribe-dg:   ## Diarized nova-3 transcripts for any new clips (Deepgram; needs DEEPGRAM_API_KEY)
	cd backend && uv run python -m pipeline.transcribe_deepgram

index:           ## Rebuild the crew index with Arc Tagger (needs `make models` running)
	cd backend && uv run python -m pipeline.build_index

meta:            ## Arc audio metadata + awe peaks for every crew clip -> backend/data/index/audio_meta.json (needs `make models`)
	cd backend && uv run python -m pipeline.build_audio_meta

dev:             ## Run model server, backend and frontend together (Ctrl-C stops all)
	uvx honcho@2.0.0 -f Procfile.dev start

models:          ## Run only the model server
	cd model_server && uv run uvicorn app.main:app --host 127.0.0.1 --port 8200

backend:         ## Run only the backend
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload

frontend:        ## Run only the frontend dev server
	cd frontend && npm run dev

test:            ## Run all tests
	cd model_server && uv run pytest -q
	cd backend && uv run pytest -q

build:           ## Build the frontend into frontend/dist (served by the backend at :8100)
	cd frontend && npm run build

health:          ## Check that all three are up
	@curl -s localhost:8200/health | python3 -m json.tool | head -20
	@curl -s localhost:8100/api/health | python3 -m json.tool | head -20
	@curl -s -o /dev/null -w "frontend :5173 -> %{http_code}\n" localhost:5173/

DM_PORT ?= 8290
DM_DATA ?= director_model/data/ds
DM_RUN ?= director_model/runs/latest
DM_SIZE ?= m
EMBED_MODEL_DIR ?= $(CURDIR)/model_server/models/minilm

DM_REAL_BUDGET ?= 3500
DM_REAL_PROCS ?= 6

director-real-ear: ## Render (in memory, no audio on disk) the generator's kid turns with Steer TTS + decode them with the REAL Arc ear (cached; NEW_EAR=1 re-decodes)
	@if [ "$(NEW_EAR)" = "1" ]; then rm -rf director_model/cache/real_ear/dec; fi
	uv run --project backend python director_model/real_ear.py jobs --budget $(DM_REAL_BUDGET)
	cd model_server && EAR_PARTIAL_EVERY_S=0.9 uv run python ../director_model/real_ear.py decode --procs $(DM_REAL_PROCS) --threads 2
	uv run --project backend python director_model/real_ear.py stats

director-retrain: director-real-ear ## Rebuild the learned Director: real Arc decodes, refit ASR errors, regenerate sessions, train, evaluate, export (director_model/RETRAIN.md)
	cd model_server && (EMBED_MODEL_DIR=$(EMBED_MODEL_DIR) STEER_TTS=off ARC_EAR=off ARC_META=off \
	  uv run uvicorn app.main:app --host 127.0.0.1 --port $(DM_PORT) > /tmp/director-ms.log 2>&1 & echo $$! > /tmp/director-ms.pid)
	until curl -sf localhost:$(DM_PORT)/health >/dev/null; do sleep 2; done
	uv run --project backend python director_model/ear_errors.py build
	MODEL_SERVER_URL=http://127.0.0.1:$(DM_PORT) uv run --project backend python director_model/gen_sessions.py \
	  --out $(DM_DATA) $(DM_GEN_ARGS); st=$$?; kill $$(cat /tmp/director-ms.pid); test $$st = 0
	python3 director_model/train.py --data $(DM_DATA) --out $(DM_RUN) --size $(DM_SIZE)
	python3 director_model/evaluate.py --data $(DM_DATA) --run $(DM_RUN)
	python3 director_model/export.py --run $(DM_RUN) --data $(DM_DATA) --eval $(DM_RUN)/eval.json
	cd backend && uv run pytest -q tests/test_director_model.py

# ---- Desktop app (docs/DESKTOP.md): one offline installer, Electron + embedded Python + every model ----
desktop-python:  ## Desktop: embedded CPython + backend/model-server deps + app code -> desktop/resources
	uv run --no-project python desktop/scripts/build_python.py

desktop-models:  ## Desktop: gather every model file into desktop/resources/models (DESKTOP_MODELS_FROM=hf in CI)
	python3 desktop/scripts/gather_models.py --from $(or $(DESKTOP_MODELS_FROM),local)

desktop-arctag:  ## Desktop: build libarctag (dylib/so/dll) from desktop/vendor/arctag -> desktop/resources/native
	cmake -S desktop/vendor/arctag -B desktop/build/arctag -DCMAKE_BUILD_TYPE=Release
	cmake --build desktop/build/arctag --config Release
	mkdir -p desktop/resources/native
	cp desktop/build/arctag/libarctag.* desktop/resources/native/ 2>/dev/null || cp desktop/build/arctag/Release/arctag.dll desktop/resources/native/

desktop-mac:     ## Desktop: build the macOS arm64 .dmg (unsigned / ad-hoc) -> desktop/dist
	test -d backend/data/media || { echo "backend/data/media missing: make data"; exit 1; }
	$(MAKE) desktop-python desktop-models desktop-arctag
	cd desktop && npm ci --no-audit --no-fund && npx electron-builder --mac dmg --arm64

desktop-run:     ## Desktop: run the shell against desktop/resources without packaging (dev)
	cd desktop && node node_modules/electron/install.js && npx electron .

desktop-clean:   ## Desktop: remove build outputs (resources, build caches, dist)
	rm -rf desktop/resources desktop/build desktop/dist

.PHONY: help setup data transcribe transcribe-dg index meta dev models backend frontend test build health director-real-ear director-retrain
