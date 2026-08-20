.PHONY: help infra infra-down backend frontend worker beat \
        migrate seed ingest download-models \
        test test-backend lint fmt check eval eval-offline calibrate build-graph \
        logs ps clean

# ── Default ───────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Bharat AI — Developer Commands"
	@echo ""
	@echo "  SETUP"
	@echo "    make setup          First-time setup: copy .env, install deps"
	@echo "    make download-models  Download BGE-M3 + reranker models (~3GB)"
	@echo ""
	@echo "  INFRASTRUCTURE (Docker — databases only)"
	@echo "    make infra          Start Postgres, Redis, Qdrant, Elasticsearch"
	@echo "    make infra-full     Start infra + Prometheus + Grafana"
	@echo "    make infra-down     Stop all infra containers"
	@echo "    make logs           Tail all infra logs"
	@echo "    make ps             Show running containers"
	@echo ""
	@echo "  DEV SERVERS (run natively, hot-reload)"
	@echo "    make backend        Run FastAPI with uvicorn (port 8000)"
	@echo "    make frontend       Run Next.js dev server (port 3000)"
	@echo "    make worker         Run Celery worker (ingestion tasks)"
	@echo "    make beat           Run Celery beat (scheduled jobs)"
	@echo ""
	@echo "  DATABASE"
	@echo "    make migrate        Run all pending DB migrations"
	@echo "    make seed           Seed sample legal + scheme data"
	@echo "    make ingest         Ingest domain corpora (DOMAIN=legal, or all)"
	@echo ""
	@echo "  QUALITY"
	@echo "    make test           Run pytest + frontend tests"
	@echo "    make eval           Run the v3 golden-set eval harness"
	@echo "    make calibrate      Measure reliability-score calibration (ECE, band precision)"
	@echo "    make lint           Ruff + mypy + eslint"
	@echo "    make fmt            Auto-format Python (ruff) + frontend (prettier)"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────
setup:
	@if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env && echo "✓ backend/.env created — fill in your API keys"; fi
	cd backend && uv sync
	cd frontend && npm install
	@echo "✓ Dependencies installed"

download-models:
	@echo "Downloading BGE-M3 (~2.2GB) and reranker (~600MB)..."
	mkdir -p backend\models
	cd backend && uv run python -c "\
	from FlagEmbedding import BGEM3FlagModel, FlagReranker; \
	import os; cache = os.getenv('EMBEDDING_MODEL_CACHE', './models'); \
	print('Downloading BGE-M3...'); BGEM3FlagModel('BAAI/bge-m3', cache_dir=cache, use_fp16=False); \
	print('Downloading reranker...'); FlagReranker('BAAI/bge-reranker-v2-m3', cache_dir=cache, use_fp16=False); \
	print('Done.')"

# ── Infrastructure (Docker for DBs only) ──────────────────────────────────────
# Compose reads its variables (POSTGRES_PASSWORD, etc.) from backend/.env — the same
# file the backend uses — so there is ONE source of truth and no root-level .env.
COMPOSE := docker compose --env-file backend/.env

infra:
	$(COMPOSE) up -d postgres redis qdrant elasticsearch
	@echo "✓ Infra started — Postgres:5432, Redis:6379, Qdrant:6333, ES:9200"
	@echo "  Run 'make migrate' to apply DB migrations"

infra-full:
	$(COMPOSE) up -d
	@echo "✓ Full infra started (includes Prometheus:9090, Grafana:3001)"

infra-down:
	$(COMPOSE) down
	@echo "✓ All containers stopped"

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

# ── Dev servers (native, not Docker) ──────────────────────────────────────────
backend:
	cd backend && uv run uvicorn src.main:app \
		--host 0.0.0.0 \
		--port 8000 \
		--reload \
		--reload-dir src \
		--log-level debug

frontend:
	cd frontend && npm run dev

worker:
	cd backend && uv run celery -A src.worker.celery_app worker \
		--loglevel=info \
		--queues=ingestion.document,ingestion.realtime \
		--concurrency=4

beat:
	cd backend && uv run celery -A src.worker.celery_app beat \
		--loglevel=info \
		--scheduler celery.beat:PersistentScheduler

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	cd backend && uv run python -m src.db.migrate

seed:
	cd backend && uv run python scripts/seed_legal.py
	cd backend && uv run python scripts/seed_schemes.py

# Per-domain ingestion agents. Usage: make ingest DOMAIN=legal  (or all domains if unset)
# Add --online by hand for official URLs: uv run python -m src.ingestion.run --all --online
ingest:
	cd backend && uv run python -m src.ingestion.run $(if $(DOMAIN),--domain $(DOMAIN),--all)

# ── Quality ───────────────────────────────────────────────────────────────────
test:
	cd backend && uv run pytest -v --tb=short
	cd frontend && npm test -- --passWithNoTests

test-backend:
	cd backend && uv run pytest -v --tb=short -x

lint:
	cd backend && uv run ruff check src/ tests/
	cd backend && uv run mypy src/ --ignore-missing-imports
	cd frontend && npm run lint

fmt:
	cd backend && uv run ruff format src/ tests/
	cd frontend && npm run format

check: lint test
	@echo "✓ All checks passed"

# ── Evaluation (v3 golden sets) ───────────────────────────────────────────────
eval:
	cd backend && uv run python -m src.eval.run

eval-offline:
	cd backend && uv run python -m src.eval.run --offline

calibrate:
	cd backend && uv run python -m src.eval.calibration

# ── Knowledge graph (Phase 4) ─────────────────────────────────────────────────
build-graph:
	cd backend && uv run python scripts/build_graph.py

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/.next frontend/out
	@echo "✓ Build artifacts cleaned"
