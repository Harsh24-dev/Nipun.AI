# Nipun.AI

Nipun.AI is a grounded, multilingual AI assistant built for Indian users. It answers questions across many everyday domains (legal, farming, student, health, government schemes, finance, careers, travel, documents, and more) in several Indian languages and their romanized, code-switched variants such as Hinglish.

The core design principle is **grounded-or-abstain**: every factual claim is meant to be backed by a retrieved, cited source, and when the evidence is weak the answer comes with a reliability score rather than a confident guess. On top of retrieval, the system can plan and execute multi-step tasks, including driving a real browser to complete web actions.

This repository contains both the backend and the frontend. A detailed, file-by-file technical reference lives in [`TECHNICAL.md`](./TECHNICAL.md).

> Note on history: this is a clean, single-history snapshot of the project. Runtime secrets are never committed. Copy `backend/.env.example` to `backend/.env` and supply your own API keys.

## What it does

- **Multilingual, grounded answers.** Detects the user's language, retrieves supporting evidence, generates an answer, attaches citations, and verifies claims before responding.
- **Agentic orchestration.** A LangGraph state machine routes each query: simple answers go straight to generation, factual questions go through retrieval and grading with a rewrite loop, and actionable requests go through task planning and execution.
- **Hybrid retrieval.** Dense plus sparse retrieval using BGE-M3 embeddings, BM25 exact match, reciprocal-rank fusion, and a reranking step, over a vector store and a full-text store, with an optional knowledge-graph path.
- **Multi-provider LLM layer.** A unified client (LiteLLM) with primary, fast, and fallback tiers and a per-provider circuit breaker, so you can switch between Google, Anthropic, OpenAI, Groq, Mistral, Cohere, or a local Ollama model from configuration alone.
- **Tiered memory.** In-process, Redis, and Postgres-backed memory tiers for short-term context and longer-term recall.
- **Live task execution.** A browser-automation agent (IPA) built on Playwright can perceive a page and carry out real web tasks, gated behind an explicit prepare-and-confirm step.
- **Safety by construction.** A crisis pre-screen runs before retrieval, and disclaimers plus safety filtering run centrally after generation rather than being left to the prompt.
- **Deliverables.** Can generate downloadable documents and slide decks with charts and images.

## Architecture at a glance

```
Client (web / API)
   |  REST /query      WebSocket /ws/{session_id} (streaming)
   v
FastAPI gateway
   correlation IDs, JWT auth, RBAC, rate limiting, PII-masked logs,
   Redis-based backpressure, Prometheus metrics, per-request metering
   |
   v
LangGraph orchestrator
   understand -> safety pre-screen -> embed -> assemble context ->
   clarify check -> plan/route
        -> simple generation
        -> task execution
        -> multi-hop
        -> retrieve -> grade (rewrite / live-augment loop) ->
           generate -> cite claims -> verify claims -> finalize
   |
   +-- LLM layer (LiteLLM, 3 tiers, circuit breaker)
   +-- Memory (in-process, Redis, Postgres)
   +-- Retrieval (BGE-M3 dense + sparse, BM25, RRF, reranker, graph)
   +-- Safety and synthesis (verification, disclaimers, deliverables)
   +-- Task and IPA (agentic executor, Playwright browser agent)
```

For the full request lifecycle, node-by-node orchestrator behavior, database schema, API reference, and the response contract, see [`TECHNICAL.md`](./TECHNICAL.md).

## Tech stack

**Backend**
- FastAPI and Uvicorn, async throughout, with WebSocket streaming
- LangGraph and LangChain-core for agent orchestration
- LiteLLM as the unified multi-provider LLM client
- BGE-M3 embeddings (FlagEmbedding, PyTorch, Transformers) for multilingual retrieval
- Qdrant (vector store), Elasticsearch (exact match), Neo4j (knowledge graph)
- PostgreSQL (async SQLAlchemy, pgvector, Alembic migrations) and Redis
- Celery for background jobs
- Playwright for the live browser-automation agent
- structlog, Prometheus, and OpenTelemetry for observability
- Pydantic and pydantic-settings for configuration and validation

**Frontend**
- React 18 with Vite
- React Router and TanStack Query
- Tailwind CSS with Radix UI (shadcn/ui) components
- React Hook Form

**Infrastructure**
- Docker and Docker Compose (development and production compose files)
- Nginx reverse proxy
- Prometheus and Grafana for monitoring

## Repository layout

```
nipun/
├── backend/
│   ├── src/
│   │   ├── agents/         # orchestrator, planner, reasoning, controller, citation, grading, memory
│   │   ├── api/            # dependencies, RBAC, request/response schemas
│   │   ├── core/           # logging, metrics, metering, concurrency, runtime context
│   │   ├── db/             # postgres, redis, qdrant, neo4j clients and migrations
│   │   ├── eval/           # evaluation and calibration harness
│   │   ├── a2a/            # agent-to-agent card
│   │   └── config.py       # central configuration
│   ├── scripts/            # ingestion, graph build, seeding, recall checks
│   ├── tests/
│   ├── pyproject.toml
│   └── .env.example
├── frontend/               # React + Vite single-page app
├── infrastructure/         # nginx and deployment scripts
├── monitoring/             # Prometheus and Grafana configuration
├── docker-compose.yml
├── docker-compose.prod.yml
└── TECHNICAL.md            # full technical reference
```

## Getting started

Prerequisites: Docker and Docker Compose, plus at least one LLM provider API key (Google Gemini works out of the box and has a free tier).

```bash
# 1. Configure environment
cp backend/.env.example backend/.env
# edit backend/.env: set SECRET_KEY and at least GOOGLE_API_KEY (or another provider)

# 2. Start the stack (API, databases, vector/search stores, frontend)
docker compose up --build

# 3. One-time browser binary for the automation agent (optional feature)
#    playwright install chromium
```

The `.env.example` file documents every variable, marking each as required, recommended, or optional, and the app degrades gracefully when optional features are not configured. See the Environment Variables and Development Workflow sections of [`TECHNICAL.md`](./TECHNICAL.md) for details.

## Security notes

- No real secrets are committed. All keys are read from `backend/.env`, which is gitignored.
- Authentication uses JWT, with role-based access control enforced server-side.
- Logs are PII-masked, and safety filtering is applied centrally rather than trusted to the model prompt.

## What this project demonstrates

- Designing an agentic RAG system end to end: routing, retrieval, grading, generation, citation, and verification as an explicit state machine.
- Building a provider-agnostic LLM layer with tiered fallback and circuit breaking.
- Hybrid multilingual retrieval across vector, full-text, and graph stores.
- Production concerns done properly: async APIs, observability, rate limiting, RBAC, Docker-based deployment, and an evaluation harness.
- Integrating live browser automation as a guarded, confirmable capability.

This is a personal project.
