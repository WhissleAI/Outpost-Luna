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

index:           ## Rebuild the crew index with Arc Tagger (needs `make models` running)
	cd backend && uv run python -m pipeline.build_index

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

.PHONY: help setup data transcribe index dev models backend frontend test build health
