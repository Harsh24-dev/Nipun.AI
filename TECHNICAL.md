# Nipun.AI — Full-Stack Technical Reference

> India-first, sovereign, multi-agent AI assistant — **backend + frontend**.
> Backend: FastAPI + LangGraph (agentic RAG) + BGE-M3 hybrid retrieval + LiteLLM + a
> live browser-automation agent (IPA, Playwright).
> Frontend: Vite + React 18 + react-router + TanStack Query + Tailwind + shadcn/ui.
> Audience: a developer new to this codebase. Every claim below was read from the
> current source under `backend/src/` and `frontend/src/` — file paths and identifiers
> are real. When a value is a tunable, its `.env` key and default are given.
> Last updated: July 2026 (audited against `demo_ver_0.11`).

---

## Table of Contents

1. [What this system is](#1-what-this-system-is)
2. [Big-picture architecture](#2-big-picture-architecture)
3. [Tech stack & infrastructure](#3-tech-stack--infrastructure)
4. [Directory map](#4-directory-map)
5. [The end-to-end request lifecycle](#5-the-end-to-end-request-lifecycle)
6. [Application startup (`main.py`)](#6-application-startup-mainpy)
7. [Configuration system (`config.py`)](#7-configuration-system-configpy)
8. [Auth, dependencies & RBAC](#8-auth-dependencies--rbac)
9. [Language system](#9-language-system)
10. [LLM multi-client layer](#10-llm-multi-client-layer)
11. [Embeddings & reranking](#11-embeddings--reranking)
12. [Hybrid retrieval pipeline](#12-hybrid-retrieval-pipeline)
13. [Memory architecture](#13-memory-architecture)
14. [The LangGraph orchestrator (the heart)](#14-the-langgraph-orchestrator-the-heart)
15. [Routing, planning & mission control](#15-routing-planning--mission-control)
16. [Clarification (ask-back)](#16-clarification-ask-back)
17. [Domain agents](#17-domain-agents)
17a. [General agentic task executor (`agentic.py`)](#17a-general-agentic-task-executor-agenticpy)
18. [Safety, verification & reliability](#18-safety-verification--reliability)
19. [Adaptive-explanation synthesis & deliverables](#19-adaptive-explanation-synthesis--deliverables)
20. [MCP tools & live data](#20-mcp-tools--live-data)
21. [Task execution (PREPARE→CONFIRM)](#21-task-execution-prepareconfirm)
21a. [Task-automation subsystem (`tasks/`)](#21a-task-automation-subsystem-tasks)
21b. [IPA — live browser automation](#21b-ipa--live-browser-automation)
22. [Research (RLM) & GraphRAG](#22-research-rlm--graphrag)
23. [A2A (agent-to-agent)](#23-a2a-agent-to-agent)
24. [Ingestion pipeline](#24-ingestion-pipeline)
25. [Background jobs (Celery)](#25-background-jobs-celery)
26. [Database schema](#26-database-schema)
27. [Vector & search stores](#27-vector--search-stores)
28. [Observability (logging, metrics, metering)](#28-observability-logging-metrics-metering)
29. [Evaluation harness](#29-evaluation-harness)
30. [API reference](#30-api-reference)
31. [The `response_card` contract](#31-the-response_card-contract)
32. [Environment variables](#32-environment-variables)
33. [Development workflow](#33-development-workflow)
34. [Production deployment](#34-production-deployment)
35. [Performance targets](#35-performance-targets)
36. [Extending the platform](#36-extending-the-platform)
37. [Security model](#37-security-model)
38. [Frontend reference (Vite + React)](#38-frontend-reference-vite--react)
39. [Architecture & data-flow deep dive (formats at every stage)](#39-architecture--data-flow-deep-dive-formats-at-every-stage)

---

## 1. What this system is

**Nipun.AI** is a grounded, multilingual assistant for Indian citizens. It answers
questions across **13 domains** (legal, farming, student, health, scheme, finance,
booking, career, governance, jobs, travel, documents, general) in **7 languages**
(`en, hi, pa, ta, te, mr, gu`) plus their romanised code-switched variants (Hinglish,
Tamilish, etc.).

Design principles baked into the backend:

- **Grounded-or-abstain.** Every factual claim is meant to be backed by a retrieved,
  cited source. When evidence is thin, the answer is delivered *with a reliability score*
  (or, optionally, an abstention) — never a confident fabrication.
- **Config over code.** Providers, models, thresholds, and feature flags all live in
  `.env` and `config.py`. You can swap Claude→GPT, turn safety on/off, or change RAG loop
  depth without touching code.
- **Safety first, at the edges.** A crisis pre-screen runs *before* retrieval; disclaimers
  and safety filtering run *after* generation, centrally (never trusted to the prompt).
- **Deterministic where it matters.** Response language, safety keyword rules, routing,
  and RBAC are rules-first; the LLM is used only where judgment is genuinely needed.
- **Observable.** Correlation IDs, structured logs, a full per-request chat-pipeline trace
  (`chat.log`), per-request token/latency metering, and ~40 Prometheus metrics.

---

## 2. Big-picture architecture

```
Client (Web / Mobile / API)
      │  POST /query (REST)  ·  WS /ws/{session_id} (streaming)
      ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI gateway (src/main.py)                                    │
│  Correlation-ID · JWT auth · RBAC · rate limits · PII-masked logs │
│  Redis-ZSET global backpressure (MAX_INFLIGHT_QUERIES)            │
│  Prometheus /metrics · per-request metering                       │
└───────────────────────────────┬─────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  LangGraph orchestrator (src/agents/orchestrator.py)              │
│                                                                   │
│  understand → [safe_response] → embed → assemble_context →        │
│  clarify_check → plan_route ─┬─► generate_simple ──────► finalize │
│                              ├─► task_execute ─────────► END      │
│                              ├─► multi_hop ────────────► finalize │
│                              └─► retrieve → grade ⇄ (live_augment │
│                                    / rewrite loop) → generate →   │
│                                    cite_claims → verify_claims →   │
│                                    (re-loop) → finalize            │
└───┬───────────┬───────────┬───────────┬───────────┬─────────────┘
    ▼           ▼           ▼           ▼           ▼
 LLM layer   Memory tiers Retrieval  Safety/synth  Task/IPA
 (LiteLLM,   (L0 in-proc, (BGE-M3    verification  agentic.py
 3 tiers +   Redis,       dense+     MCP live      + ipa/ live
 per-tier    pgvector)    sparse, ES tools /       browser agent
 breaker)                 BM25, RRF, execution     (Playwright)
                          reranker,
                          Neo4j graph)
    ▼           ▼           ▼           ▼           ▼
 Anthropic /  Redis +    Qdrant (14 collections,  Postgres
 OpenAI /     Postgres   1024-d dense+sparse) ·   task_recipes ·
 Google                  Elasticsearch · Neo4j    headless Chromium
```

The orchestrator is **not** the old fixed 5-node pipeline. It is a routed, looping graph:
a query is classified, routed to one of five strategies, and (on the RAG path) can loop
retrieve→grade→rewrite up to `RAG_MAX_LOOPS` times, then generate→**cite_claims** (answer-first
retro-citation)→verify→(re-loop)→finalize. The `task_execution` route can hand off to the **IPA
live browser agent** (`ipa/`), a server-side Playwright agent that actually performs the task
(book/apply/fill) with live WebSocket streaming and human-in-the-loop hand-off at login/OTP/payment.

---

## 3. Tech stack & infrastructure

### Backend — Python ≥3.12

| Concern | Choice | Why |
| --- | --- | --- |
| Web framework | **FastAPI** | Async, Pydantic v2, auto-OpenAPI, native WebSocket |
| Orchestration | **LangGraph** (`StateGraph`) | Stateful, routed, looping agent graph |
| LLM abstraction | **LiteLLM** | One API for Anthropic/OpenAI/Google/Groq/Mistral/Cohere/Ollama; swap via `.env` |
| Embeddings / rerank | **FlagEmbedding** (BGE-M3, BGE-reranker-v2-m3) | Best Indic retrieval; dense **and** learned-sparse output |
| Vector DB | **Qdrant** (`qdrant-client`, async) | Dense + sparse hybrid, int8 quantization |
| Exact search | **Elasticsearch** (async) | BM25 for section IDs / scheme codes |
| Graph (optional) | **Neo4j** | GraphRAG for multi-hop relational queries |
| Relational DB | **PostgreSQL + pgvector** (`asyncpg`) | Users, sessions, logs, episodic + user memory |
| Cache / broker | **Redis** (`redis.asyncio`) | Session/profile cache, semantic cache, rate limits, Celery |
| Task queue | **Celery + Redis** | Async ingestion, scheduled data refresh |
| Auth | **python-jose** (JWT HS256) + **bcrypt** | Stateless tokens |
| Language ID | **lingua** + Unicode script analysis | Fast, offline detection |
| Logging | **structlog** | JSON logs + PII masking + flow tracing |
| Metrics | **prometheus-client** + instrumentator | `/metrics` scrape |
| Resilience | **tenacity** | Exponential backoff on LLM errors |
| HTTP | **httpx** (async) | External/live-data calls |
| Browser automation | **Playwright** (async Chromium, lazy import) | The IPA live-task agent (`ipa/`) |
| File deliverables | **python-docx**, **python-pptx**, **matplotlib**, **Pillow** (lazy) | Generate downloadable DOCX/PPTX + PNG charts (`synthesis/`) |
| Package mgr | **uv** | Fast, locked deps |

All heavy/optional libraries (Playwright, python-docx/pptx, matplotlib, FlagEmbedding) are
**imported lazily**, so the app boots and answers text queries even if they are not installed.

### Infra services (docker-compose)

Dev compose (`docker-compose.yml`) runs **infra only** — the backend and frontend run natively
on the host (Prometheus scrapes `host.docker.internal:8000`). Prod (`docker-compose.prod.yml`)
containerises everything (see §34).

| Service | Image | Port | Notes |
| --- | --- | --- | --- |
| PostgreSQL + pgvector | `pgvector/pgvector:pg16` | 5432 | mounts `infrastructure/scripts/init-db.sql` |
| Redis | `redis:7-alpine` | 6379 | `--maxmemory 2gb allkeys-lru`, AOF |
| Qdrant | `qdrant/qdrant:v1.18.0` | 6333 / 6334 | HTTP / gRPC |
| Elasticsearch | `elasticsearch:8.16.0` | 9200 | single-node, security off (dev) |
| Neo4j (optional) | `neo4j:5.25-community` | 7687 / 7474 | apoc plugin |
| Prometheus / Grafana | `prom/prometheus:v2.55.0`, `grafana/grafana:11.3.0` | 9090 / 3001 | behind the `monitoring` Compose profile (dev) |

### Frontend — Node / Vite

| Concern | Choice |
| --- | --- |
| Framework | **React 18.2** (JSX, not TypeScript — type-checked via `jsconfig.json` `checkJs`) |
| Build tool | **Vite 6** (`@vitejs/plugin-react`); dev proxy `/api-backend/*` → `VITE_API_BASE_URL` |
| Routing | **react-router-dom 6** |
| Server state | **@tanstack/react-query 5** (provider mounted; most fetches go direct through `api.js`) |
| Styling | **Tailwind CSS 3.4** + `tailwindcss-animate`; 4-axis CSS-variable theming (palette/preset/motif/region) |
| Components | **shadcn/ui** ("new-york") on **Radix UI**; **lucide-react** icons; **framer-motion** |
| Forms | **react-hook-form** + **zod** |
| Content | **react-markdown**; **react-leaflet** (maps); hand-rolled SVG for charts/diagrams |

> **Note:** `frontend/README.md`, `AGENTS.md`, `CLAUDE.md` are **stale Base44 boilerplate**. The
> live app targets this FastAPI backend via `src/lib/api.js`. Treat `api.js` + `vite.config.ts` as
> the source of truth, not those files. Full frontend reference in **§38**.

**Why Qdrant *and* Elasticsearch:** Qdrant carries BGE-M3 dense+sparse vectors (learned
sparse understands that खेत/खेती are related). Elasticsearch is used *only* for exact-match
identifiers — `Section 302`, `PM-KISAN`, `WP-12345/2024` — where literal token match wins.

---

## 4. Directory map

```
backend/src/
├── config.py                 # Pydantic Settings — ALL config from .env (one big class)
├── main.py                   # FastAPI app, lifespan startup/shutdown, middleware, routers, Win Proactor fix
│
├── core/
│   ├── logging.py            # structlog setup, PII masking, trace_flow(), subsystem log files
│   ├── metrics.py            # ~40 Prometheus metric definitions
│   ├── metering.py           # per-request token+latency meter (contextvars)
│   ├── concurrency.py        # [NEW] global in-flight backpressure gate (Redis ZSET, fail-open)
│   ├── flow_console.py       # [NEW] human-readable per-request flow story → flow.log + terminal
│   ├── ipa_console.py        # [NEW] IPA browser-run narration → ipa.log
│   └── runtime_context.py    # [NEW] runtime_prompt_header(): real IST date/year + user grounding
│
├── llm/
│   ├── client.py             # LiteLLM wrapper: call_llm / stream_llm, retry, LLMResponse
│   ├── router.py             # tier routing fast|primary|fallback + auto-fallback
│   └── embeddings.py         # BGE-M3 local / Cohere / OpenAI; dense+sparse; thread pool
│
├── language/
│   ├── constants.py          # LANGUAGES, CODE_SWITCHED, SUPPORTED_DOMAINS (13)
│   └── detector.py           # detect_language, resolve_response_language, language_directive
│
├── db/
│   ├── postgres.py           # asyncpg pool (min 5)
│   ├── redis.py              # async client + json/incr helpers
│   ├── qdrant.py             # 13 domain collections + user_documents (auto-created)
│   ├── neo4j.py              # optional graph driver (no-op if GRAPH_ENABLED=false)
│   ├── migrate.py            # runs migrations/*.sql in order
│   └── migrations/           # 001…008 .sql
│
├── memory/
│   ├── working.py            # L0 in-process deque per session (+ transient facts)
│   ├── session.py            # L1 semantic cache + L2 Redis session/profile + profile load/persist
│   ├── episodic.py           # L4 pgvector session summaries + ANN recall
│   ├── user_memory.py        # long-term learned facts (fact|preference|goal|context)
│   ├── context.py            # assembles all tiers into AssembledContext
│   └── conversation_store.py # durable turn persistence (sessions + conversation_logs)
│
├── retrieval/
│   ├── hybrid.py             # dense+sparse Qdrant, ES BM25, RRF fusion, user-doc retrieval
│   └── reranker.py           # BGE-reranker-v2-m3 cross-encoder
│
├── agents/
│   ├── orchestrator.py       # THE LangGraph state machine (13 nodes) + process_query()
│   ├── agentic.py            # [NEW] ReAct JSON-action task agent (run_agentic_task)
│   ├── base.py               # BaseAgent abstract contract + execute()
│   ├── registry.py           # domain → agent instance (13)
│   ├── controller.py         # Mission controller (route → mode → capability pipeline)
│   ├── planner.py            # classify_route, generate/select Plan, decompose, synthesize
│   ├── grading.py            # grade_documents + rewrite_query
│   ├── clarify.py            # ask-back clarification (LLM expert intake PRIMARY, slot registry fallback)
│   ├── capabilities.py       # pluggable capability catalogue (manifest)
│   ├── memory_extractor.py   # learn durable profile facts + memories from a turn
│   ├── reasoning.py          # reasoning/quality directives + optional reflect/critic
│   └── domains/              # legal, farming, scheme, student, finance, health, career,
│                             #   booking, governance, jobs, travel, documents, general
│
├── safety/
│   ├── prescreen.py          # crisis/harm intake classifier (rules + optional LLM)
│   ├── resources.py          # official crisis resources (config-driven, verified only)
│   ├── handlers.py           # safe-path response cards
│   ├── gate.py               # VerificationSafetyGate — pre-delivery choke point
│   ├── verification.py       # claim extraction + entailment → confidence
│   ├── scoring.py            # multi-signal reliability score + bands
│   └── corroboration.py      # cross-source independent agreement
│
├── synthesis/
│   ├── explanation.py        # ExplanationPlan: depth/format/modality; enrich_card
│   ├── preferences.py        # learn per-user preferences from feedback
│   ├── deliverable.py        # [NEW] generate_deliverable → downloadable PPTX/DOCX card
│   ├── filegen.py            # [NEW] DOCX/PPTX byte builders + matplotlib PNG charts/diagrams
│   ├── file_store.py         # [NEW] Redis-backed 24h download store (/files/{id})
│   ├── inline_media.py       # [NEW] resolve [[embed]]/img markers → inline images/charts/SVG
│   └── resources.py          # [NEW] study resources + shared image library + promote_media_card
│
├── mcp/
│   ├── base.py               # MCPTool ABC + ToolResult (guarded, untrusted output)
│   ├── tools.py              # tool registry (built at import)
│   └── live/                 # aggregator, selector(LLM tool pick), http, web, finance, data,
│                             #   research, apps, shopping, jobs[NEW], knowledge[NEW], youtube[NEW]
│
├── execution/
│   ├── executor.py           # PREPARE → CONFIRM → EXECUTE → AUDIT (ACTION_HANDLERS empty by design)
│   ├── circuit_breaker.py    # per-session tool/agent rate limiting (Redis bucket)
│   └── guards.py             # credential firewall + prompt-injection surfacing
│
├── tasks/                    # [EXPANDED] task-automation subsystem (§21a)
│   ├── store.py              # durable service_tasks (bookings/forms, credentials scrubbed)
│   ├── assistants.py         # read-only preview assistants + select_assistant router
│   ├── career.py             # resume builder/tailor, learning plan, job-application form
│   ├── job_apply.py          # run_job_application (find openings + prepare, hand off)
│   ├── forms.py              # FieldSpec/FormAssistant (RTI, train, doctor, bail, document)
│   ├── form_analyzer.py      # deterministic HTML form-field extraction + sensitivity flags
│   └── dynamic_fill.py       # fill_form_on_site: fetch→analyze→LLM-map→hand off
│
├── ipa/                      # [NEW] live browser-automation agent (§21b)
│   ├── schemas.py            # TaskPlan, ChecklistStep, AgentAction, RunStatus, event()
│   ├── planner.py            # plan_task → TaskPlan (surface web|app|device)
│   ├── controller.py         # run_in_worker: daemon thread + ProactorEventLoop dispatch
│   ├── agent.py              # web run_task loop; replay; fill-and-hand-off (never auto-submit)
│   ├── browser.py            # Playwright Chromium; set-of-marks perceive(); act()
│   ├── targets.py            # India-first trusted-site catalog + trust gate
│   ├── recipes.py            # reusable HOW recipes (task_recipes table, no personal data)
│   ├── compare.py            # gather_options across trusted sources (comparable goals)
│   ├── session.py            # TaskSession run state, event queue, control flags, Redis mirror
│   └── executors/            # app.py (in-app safe actions), device.py (sandboxed file R/W, off)
│
├── research/rlm.py           # bounded long-document inspector
├── a2a/card.py               # signed agent cards + M2M tokens
├── graph/                    # schema/data/build/retrieval for Neo4j GraphRAG
├── eval/                     # golden sets (7×15), metrics, run, calibration
├── ingestion/                # parser, chunker, indexer, pipeline, sources/, books, tasks
├── worker/celery_app.py      # Celery app + beat schedule
└── api/
    ├── deps.py               # get_current_user, require_admin, rate_limit_check
    ├── rbac.py               # role hierarchy, require_roles, assert_owner
    ├── schemas.py            # ResponseCard + shared models (CardType: 23 values)
    └── routers/              # health, auth, profile, memory, sessions, query, feedback,
                              #   admin, documents, files[NEW], logs, tasks, task_agent[NEW/IPA], a2a
```

**Frontend (`frontend/src/`):**

```
frontend/src/
├── main.jsx / App.jsx        # mount; provider tree + route table + guards + ErrorBoundary
├── index.css                 # Tailwind entry + shadcn HSL vars + .prose card styling
├── lib/
│   ├── api.js                # FastAPI client: Bearer auth, every endpoint, WS helpers
│   ├── AppContext.jsx        # global state (token/user/profile/session), localStorage, theming effect
│   ├── query-client.js       # TanStack QueryClient
│   ├── parseCard.js          # normalize backend response_card → flat view model
│   ├── cardRegistry.js       # DEAD stub — real map lives in ResponseCardRenderer
│   ├── i18n.js               # custom UI-string dictionary + getGreeting (7 langs)
│   └── theme/                # palettes(13), presets(5), motifs(8), regions(36), ThemeStyles
├── pages/                    # Landing, Home, Workspace, Onboarding, NipunLogin/Signup/Reset,
│                             #   NipunSettings, AdminDashboard, AdminMonitoring, AdminUsers
├── components/
│   ├── workspace/            # Composer, RightRail, WorkspaceSidebar, ResponseCardRenderer,
│   │   ├── cards/            #   CARD_MAP components (Answer, Plan, Clarify, StepAction, …)
│   │   ├── InlineContent.jsx #   interleave markdown + rich embeds
│   │   └── ResourcesSection.jsx, ThinkingIndicator.jsx, RightRail.jsx
│   ├── task/                 # TaskRunnerHost, TaskRunner, BrowserView, ChecklistPanel,
│   │                         #   OptionsPanel, TaskControls  (drives the IPA agent UI)
│   ├── nipun/                # AuthShell, NipunLogo
│   └── ui/                   # shadcn/ui + Radix primitives
└── hooks/ · utils/
```

---

## 5. The end-to-end request lifecycle

Take the query **"Section 302 mein bail kaise milti hai?"** on `POST /query`.

1. **Gateway** (`main.py` middleware): assign/echo a **correlation ID**, validate JWT →
   `user_id`; the LLM rate-limit (`rate:llm:{user_id}`, 20/min) is enforced in the query
   router. `begin_request(correlation_id)` starts the per-request meter.
2. **`process_query()`** (`orchestrator.py`) resolves the **response language**
   deterministically (`resolve_response_language`), initialises `OrchestratorState`, and
   invokes the compiled graph with `recursion_limit=50`.
3. **`node_understand`** — one merged fast-LLM call does safety refine + domain/intent/
   complexity classification + entity extraction (after a zero-latency crisis keyword scan).
   Here: `domain=legal`, `complexity=multi_step`, `entities=["Section 302"]`.
4. If the safety tag is not `normal` → **`node_safe_response`** returns a supportive/official
   card and ends. Otherwise continue.
5. **`node_embed_query`** — dense BGE-M3 embedding of the query.
6. **`node_assemble_context`** — L0 working memory + (parallel) L2 session/profile, L4
   episodic recall, and long-term user memories.
7. **`node_clarify_check`** — if required slots are missing (e.g. state, matter type), return
   a `clarify` form and short-circuit to finalize. Otherwise continue.
8. **`node_plan_route`** — mission controller + route classifier choose one of
   `simple_answer | agentic_rag | multi_hop | research | task_execution` and (for non-trivial
   routes) generate/select a Plan.
9. **RAG path** (`agentic_rag`/`research`): **retrieve** (Qdrant dense+sparse ⨁ ES exact — the
   latter only when an identifier regex hits — → RRF → rerank; corpus retrieval + live web run in
   parallel) → **grade_documents** → optionally **live_augment** (web/live tools) and/or
   **rewrite_query** and loop → **generate** (domain agent) → **cite_claims** (answer-first: extract
   claims, web-search to back any the corpus didn't) → **verify_claims** → maybe loop → **finalize**.
10. **`node_finalize`** — reliability scoring + corroboration + safety gate (disclaimers /
    abstention), compose `speech_text`, persist the turn to working memory, record metrics.
11. `process_query()` persists the turn durably (`conversation_store`) and fires a
    background job to extract durable profile facts / memories. Returns the `response_card`.

**Latency budget (targets):** classify ~200ms · embed ~50ms · context <35ms · retrieval
<150ms · rerank ~80ms · first LLM token 400–800ms → **~0.8–1.2s to first token**.

> For the **exact data shape at every stage** (request → state → chunks → prompt → LLM JSON →
> card → response), every API flow, and the response-generation flow, see **§39**.

---

## 6. Application startup (`main.py`)

`FastAPI(title="Nipun.AI API", version="0.1.0", docs_url="/docs", redoc_url="/redoc", lifespan=…)`.

**Windows event-loop fix (module top, before uvicorn):** on `win32` it forces
`WindowsProactorEventLoopPolicy()` — required because the IPA Playwright agent launches Chromium
as a subprocess, which a `SelectorEventLoop` cannot do (raises an empty `NotImplementedError`).

`lifespan` runs this **ordered** startup (steps logged `[n/6]`):

1. **[1/6]** `init_postgres()` — asyncpg pool (min 5).
2. **[2/6]** `init_redis()` — async Redis client.
3. **[3/6]** `init_qdrant()` — creates the 13 domain collections + `user_documents` (14 total;
   recreating any whose dense dim no longer matches `EMBEDDING_DIM`).
4. `init_neo4j()` — no-op unless `GRAPH_ENABLED=true` (runs between 3 and 4, unnumbered).
5. **[4/6]** `get_embedder()` — loads BGE-M3 locally if `EMBEDDING_PROVIDER=local`; else logs remote.
6. **[5/6]** `get_detector()` — warms the language detector.
7. **[6/6]** `_ensure_default_admin()` — bootstraps the first admin unless `BOOTSTRAP_ADMIN_ENABLED`
   is false. **Refuses to seed the publicly-known default when `APP_ENV != "development"`** (raises).
   Idempotent `ON CONFLICT (email) DO NOTHING` (handles the two-worker race). Raises a clear
   "run `make migrate`" error if the `users` table is missing. **Default dev admin (change/disable
   for prod): `admin@gmail.com` / `admin2402`.**

**Middleware (registration order — outermost first):**
- **CORS** — dev (`APP_ENV=="development"`): `allow_origin_regex` matching any localhost/127.0.0.1/
  LAN-IP on any port, `allow_credentials=True` (regex, not `*`, so credentials stay valid). Prod:
  `allow_origins=CORS_ALLOW_ORIGINS` (empty ⇒ no cross-origin browser access — set it).
- **Prometheus** — `Instrumentator(...).expose(app, endpoint="/metrics")`, excluding `/health`,`/metrics`.
- **`request_middleware`** — correlation-ID + access log. Generates/echoes `X-Correlation-ID`, binds
  structlog context, times the request, buffers request/response bodies **only when `LOG_FLOW_CONTENT`
  is on** (else skipped for latency/memory), emits `flow_console.api_call`. This try/except is the
  **sole global error boundary** (there are no `@app.exception_handler`s): any unhandled exception
  increments `ERRORS_TOTAL{error_code="unhandled"}` and returns a 500 `{"error":{"code":"INTERNAL_ERROR",…,"correlation_id"}}`.

**Routers (mount order; no global prefix — routers define their own paths):** `health · auth ·
profile · memory (prefix "/memory") · sessions · query · feedback · admin · documents · files ·
logs · tasks · task_agent · a2a`. Two WebSocket endpoints live in routers: `/ws/{session_id}`
(query streaming, in `query.py`) and `/ws/task/{task_id}` (IPA live browser run, in `task_agent.py`).

**Shutdown (after `yield`):** `close_neo4j()` → `close_http_client()` (MCP live HTTP) →
`close_elasticsearch()` → `close_postgres()` → `close_redis()`.

---

## 7. Configuration system (`config.py`)

One `Settings(BaseSettings)` class reads `.env` (or `../.env`); env vars win; extra keys
ignored. Grouped, with the important keys and defaults:

- **App:** `APP_ENV`, `APP_PORT` (8000), `DEBUG` (False), `SECRET_KEY` (≥32 chars).
- **LLM tiers (primary/fast/fallback):** provider/model/max_tokens/temperature per tier —
  see §10. Plus per-provider API keys.
- **Embeddings:** `EMBEDDING_PROVIDER` (`local`), `EMBEDDING_MODEL` (`BAAI/bge-m3`),
  `EMBEDDING_DIM` (1024, auto-corrected to match the model), `EMBEDDING_BATCH_SIZE` (32),
  `EMBEDDING_USE_FP16` (True), `EMBEDDING_MODEL_CACHE` (`./backend/models`).
- **Reranker:** `RERANKER_MODEL` (`BAAI/bge-reranker-v2-m3`), `RERANKER_TOP_K` (5),
  `RERANKER_CANDIDATES` (30).
- **Databases:** Postgres (`POSTGRES_*`, pool size, computed `postgres_dsn`), Redis
  (`REDIS_*`, computed `redis_url`), Qdrant (`QDRANT_*` + quantization), Elasticsearch
  (`ELASTICSEARCH_*`), Neo4j (`GRAPH_ENABLED` False, `NEO4J_*`, `GRAPH_ONLY_FOR_MULTIHOP`).
- **Cache TTLs (s):** session 7d, profile 30d, LLM response 1h, mandi 6h, weather 4h, law 30d.
- **Memory:** `WORKING_MEMORY_MAX_TURNS` (20), `EPISODIC_MEMORY_RECALL_LIMIT` (5),
  `SEMANTIC_CACHE_SIMILARITY_THRESHOLD` (0.92); long-term `MEMORY_*` (enabled, recall 6,
  cap 200, dedup 0.90, max-new-per-turn 4).
- **Retrieval:** dense/sparse top-k (100/100), final top-k (5), `RETRIEVAL_RRF_K` (60),
  slow-query warn (150ms), `CROSS_LINGUAL_RETRIEVAL` (True).
- **Auth:** `JWT_SECRET_KEY` (≥32), `JWT_ALGORITHM` (HS256), expiry 24h / refresh 30d.
- **Rate limits:** general 60/min, LLM 20/min, action 5/min.
- **Safety & verification:** `SAFETY_PRESCREEN_ENABLED` (True), `..._USE_LLM`,
  `CONFIDENCE_ABSTAIN_THRESHOLD` (0.5), `ABSTAIN_ON_LOW_CONFIDENCE` (False),
  reliability thresholds (high/warn/low), corroboration (`_ENABLED`, min sources,
  agreement), verify flags (`VERIFY_CLAIMS_USE_LLM`, min evidence chars, floors).
- **RAG loop:** `RAG_MAX_LOOPS` (3), `RAG_SUFFICIENCY_MIN_CHUNKS`, `RAG_GRADE_USE_LLM`.
- **Clarify / reasoning:** `CLARIFY_ENABLED`, `CLARIFY_MAX_FIELDS` (4), `CLARIFY_USE_LLM` (True),
  `CLARIFY_LLM_DOMAINS` (12); `REASONING_USE_PLAN`, `REASONING_REFLECT_ENABLED` (False),
  `CRITIC_ENABLED` (False), `CRITIC_DOMAINS` (`health,legal,finance`).
- **Citation agent (answer-first):** `CITATION_AGENT_ENABLED` (True), `CITATION_MAX_CLAIMS` (6) —
  after generation, extract claims and web-search to back any the corpus didn't (the `cite_claims` node).
- **Execution / tools:** `EXECUTION_ENABLED` (False — master switch for real actions),
  `TASK_PREVIEW_ENABLED`, `EXECUTION_CONFIRM_TTL` (600, PREPARE→CONFIRM token life),
  `CIRCUIT_BREAKER_TOOL_CALLS_PER_MIN` (20) / `..._AGENT_CALLS_PER_MIN` (30);
  `WEB_TOOLS_ENABLED`, `LLM_TOOL_SELECTION` (True), `LIVE_AUGMENT_ENABLED`, `LIVE_AUGMENT_TIMEOUT`,
  `LIVE_AUGMENT_MIN_CHUNKS` (2), live timeouts/keys.
- **IPA (live browser agent):** `IPA_ENABLED` (True — routes browser-automatable tasks to the live
  agent), `IPA_CONSOLE_ENABLED` (True), `IPA_HUMAN_WAIT_TIMEOUT` (600). Device surface:
  `DEVICE_EXECUTION_ENABLED` (False — sandboxed file R/W only), `DEVICE_SANDBOX_DIR`.
- **Backpressure / timeouts:** `MAX_INFLIGHT_QUERIES` (64 — Redis-ZSET global cap, 0 disables),
  `INFLIGHT_SLOT_TTL` (40), `REQUEST_HARD_TIMEOUT` (25); executor pools embed 2 / rerank 2.
- **Books / uploads:** `BOOKS_INGEST_ENABLED` (True), `BOOKS_AUTO_INGEST` (False), `BOOKS_INGEST_MAX`,
  `BOOKS_MAX_DOWNLOAD_MB` (30); `UPLOAD_MAX_MB` (20), `USER_DOC_QUOTA` (50). Generated deliverables use
  a Redis file store with a 24h TTL (no dedicated env key).
- **A2A / RLM:** `A2A_ENABLED` (False), signing/trusted/TTL; `RLM_MAX_DEPTH`,
  `RLM_MAX_SUBCALLS`, `RLM_CHUNK_CHARS`.
- **Observability:** `LOG_LEVEL`, `LOG_FLOW_ENABLED`, `LOG_FLOW_CONTENT`,
  `LOG_CONTENT_MAX_CHARS`, `METERING_ENABLED`, `METRICS_IN_RESPONSE`.

Two `@model_validator`s: one syncs `EMBEDDING_DIM` to the model's true size; one strips
inline comments / invalid external API keys so tools cleanly report "not configured".

---

## 8. Auth, dependencies & RBAC

**JWT-only, Bearer tokens.** `api/deps.py`:

- `validate_token(token)` — decodes with `JWT_SECRET_KEY`/HS256; requires `sub` (user_id);
  returns `{user_id, language}`; 401 `INVALID_TOKEN` on failure.
- `get_current_user(...)` — the auth dependency. In `DEBUG=True`, a missing token yields an
  **anonymous admin** (`00000000-…-0001`) for local convenience; otherwise 401 `MISSING_TOKEN`.
- `require_admin(...)` — looks up the DB role; 403 `FORBIDDEN` unless `admin`.
- `rate_limit_check(...)` — general limit via `incr_with_expiry("rate:general:{uid}", 60)`;
  429 `RATE_LIMITED` past `RATE_LIMIT_PER_MINUTE`.

**RBAC** (`api/rbac.py`): role hierarchy `user(10) < moderator(20) < admin(30)`.
`require_roles(*roles)` gates endpoints; `assert_owner(owner_id, user)` raises **404** (not
403 — avoids leaking existence) unless the caller owns the resource or is admin. Ownership is
double-guarded: at the API layer *and* at the Qdrant layer (`owner_id` payload filter), so
even an endpoint bug can't leak another user's document chunks.

---

## 9. Language system

**Supported:** `en, hi, pa, ta, te, mr, gu` (see `language/constants.py → LANGUAGES`), plus
code-switched tags `hi+en, pa+en, ta+en, te+en, mr+en, gu+en`.

**Detection** (`detector.py`) is two-stage: fast character-level script counting first
(first 500 chars), lingua-py only for the Hindi-vs-Marathi Devanagari ambiguity.
Unambiguous scripts (Gurmukhi→pa, Tamil→ta, Telugu→te, Gujarati→gu) return immediately.
≥10% Latin **and** ≥10% Indic → `{lang}+en`. Threshold `_SCRIPT_THRESHOLD=0.10`.

**Response language is authoritative and never an LLM guess.** `resolve_response_language(query)`:

1. **In-text request** — "answer in Tamil", "मुझे तमिल में बताओ" via `detect_requested_language()`
   (guards against false positives like "schemes in **Tamil Nadu**").
2. Otherwise **detected query language**, normalised to a base code (`hi+en`→`hi`).

There is **no `language` field on the API.** The orchestrator sets `state["language"]`, every
generation prompt is prefixed with a mandatory `language_directive(language)`, `node_finalize`
forces `card["language"]` and composes `card["speech_text"]` (clean plain text for TTS), and
all fallback/greeting/error strings are localised via `fallback_message()`.

---

## 10. LLM multi-client layer

### Tiers (`.env`)

| Tier | Purpose | Default provider/model | max_tokens | temp |
| --- | --- | --- | --- | --- |
| **primary** | complex reasoning, drafting, actions | anthropic / `claude-sonnet-4-6` | 4096 | 0.3 |
| **fast** | classification, simple/streamed | google / `gemini/gemini-1.5-flash` | 1024 | 0.1 |
| **fallback** | when primary/fast fail | openai / `gpt-4o-mini` | 2048 | 0.3 |

### `client.py`

- `call_llm(messages, provider, model, …)` — async single completion, wrapped with tenacity
  `@retry` on `APIConnectionError`/`RateLimitError` (3 attempts, exp backoff 2→30s). Returns
  `LLMResponse(content, model, provider, input_tokens, output_tokens)`. Records
  `LLM_DURATION`, `LLM_TOKENS`, `LLM_ERRORS` and flow traces.
- `stream_llm(...)` — async generator yielding delta tokens (no retry).
- `_resolve_model_string(provider, model)` — adds provider prefixes where LiteLLM needs them
  (`gemini/`, `groq/`, `mistral/`, `cohere/`, `ollama/`; none for anthropic/openai).
- Global LiteLLM config sets per-provider keys, `drop_params=True`.

### `router.py`

- `select_tier(complexity, has_tools)` — `has_tools or complexity in {action, multi_step}`
  → **primary**; else **fast**.
- `route_completion(messages, complexity="simple", …, override_tier=None)` — picks the tier, calls
  `call_llm`, and on exception **auto-falls-forward one hop** (fast→primary→fallback; fallback failure
  re-raises), logging `llm_tier_fallback`. `node_generate` forces `override_tier="primary"`.
- **Per-tier circuit breaker (fail-open):** `_BREAKER_THRESHOLD=3` consecutive failures trips a tier
  for `_BREAKER_COOLDOWN=30s` (monotonic clock); an open breaker skips straight to the fallback tier
  and **never rejects** the request.
- `route_stream(...)` — streaming variant (used by the WebSocket path); no tools/fallback.

---

## 11. Embeddings & reranking

### Embeddings (`llm/embeddings.py`)

`EmbeddingResult(dense: list[list[float]], sparse: list[dict[str,float]] | None)`.

- **LocalBGEM3Embedder** — `BGEM3FlagModel`; returns dense (n×1024) **and** sparse
  (`{token_id: weight}`). CPU-bound `encode()` runs via `loop.run_in_executor` so it never
  blocks the event loop.
- **CohereEmbedder / OpenAIEmbedder** — dense only (`sparse=None`); hybrid search then
  degrades to dense-only.
- `get_embedder()` is `@lru_cache`d (singleton). Public async wrappers `embed_texts_async` /
  `embed_query_async` work for all providers; sync `embed_texts` / `embed_query` are local-only.

### Reranker (`retrieval/reranker.py`)

- `rerank(query, passages, top_k=RERANKER_TOP_K)` — builds `[query, passage]` pairs, scores
  with `FlagReranker.compute_score(pairs, normalize=True)` in a dedicated thread pool
  (`RERANK_EXECUTOR_WORKERS=2`, 15s timeout), returns `[(original_index, score), …]` sorted desc,
  truncated to top-k (default 5). Reranks the top **`RERANKER_CANDIDATES=14`** by RRF (not 30).
- Model is `@lru_cache`d. On load/score failure it **degrades gracefully** to upstream order
  (score 0.0) and logs `rerank_unavailable_fallback`.

---

## 12. Hybrid retrieval pipeline

`retrieval/hybrid.py`, `retrieve()`:

```
embed query (dense + sparse)
   │
   ├── _has_identifiers(query)?  → ONLY THEN run ES exact search (parallel gather)
   │      patterns: Section\s+\d+, धारा\s+\d+, IPC/CrPC\s+\d+, PM-\w+, [A-Z]{2,}-\d{4,}
   ├── _qdrant_hybrid_search():  dense QueryRequest (using="dense", top_k=100)
   │                             + sparse QueryRequest (using="sparse", top_k=100)
   │                             (int8 quantization + rescore oversampling ×2.0)
   ├── _elasticsearch_exact_search(): multi_match title^3, section^3, keywords^2, content^1
   ├── _compute_rrf_scores(dense, sparse, k=60):  score += 1/(k + rank + 1)  → top 14 candidates
   └── rerank(query, passages, top_k=5)  → RetrievedChunk[]
```

**ES fires only for identifier queries** — a purely conceptual query ("how to get bail") uses
Qdrant dense+sparse alone. RRF sums the dense and sparse ranked lists with **equal weight** (no
per-list weighting); there are no float score cutoffs — candidate selection is purely rank-based.

`RetrievedChunk(chunk_id, text, source, source_url, section, domain, language,
relevance_score, retrieval_method, metadata)`.

- **Adaptive weighting** is implicit in how the two ranked lists feed RRF: identifier-heavy
  queries lean on sparse/exact; conceptual queries lean on dense.
- **Cross-lingual** (`CROSS_LINGUAL_RETRIEVAL=True`, default): no language filter — BGE-M3
  embeds all languages into one shared space, so an English query can surface a Hindi chunk.
  Set False to scope Qdrant/ES to the query language.
- `retrieve_user_document(...)` runs the same pipeline but **always** applies the `owner_id`
  filter (plus optional `document_id`/`session_id`) — RBAC enforced at the vector layer.

**Query-type adaptive behaviour** (conceptual, *emergent* — the RRF weights are NOT literally set;
the fusion is equal-weight and the effect comes from which lists have strong hits + whether ES fires):

| Query type | Effective lean |
| --- | --- |
| Identifier present ("Section 438 CrPC") | sparse + ES exact dominate |
| Conceptual ("how to get bail") | dense dominates (ES doesn't fire) |
| Mixed ("438 CrPC anticipatory bail") | dense + sparse + ES all contribute |

Key settings: `RETRIEVAL_DENSE_TOP_K`/`SPARSE_TOP_K` (100), `RERANKER_CANDIDATES` (14),
`RERANKER_TOP_K`/`RETRIEVAL_FINAL_TOP_K` (5), `RETRIEVAL_RRF_K` (60),
`RETRIEVAL_SLOW_QUERY_MS` (150 — warn threshold).

**`RetrievedChunk` (dataclass):** `chunk_id, text, source, source_url, section, domain,
language, relevance_score` (final reranker score), `retrieval_method`
(`dense|sparse|hybrid|exact|cross_lingual|user_doc`), `metadata` (full Qdrant payload).

---

## 13. Memory architecture

```
L0  Working memory   in-process deque per session (max 20 turns) + transient facts   <1ms
L1  Semantic cache   Redis; cosine ≥ 0.92 → reuse prior answer; TTL 1h; ≤100/user     ~1ms
L2  Session/Profile  Redis; session 7d, profile 30d (backed by Postgres)              ~1ms
L3  Knowledge        Qdrant (BGE-M3) — the retrieval corpus                          15–25ms
L4  Episodic         Postgres+pgvector session summaries, ANN recall                  ~20ms
+   User memory      Postgres+pgvector long-term facts (fact|preference|goal|context)
```

- **`working.py` (L0)** — thread-safe `deque[ConversationTurn]` per session; `to_llm_messages`
  yields `[{role, content}]`; also stores transient per-session `facts` (clarification answers)
  that are **not** persisted.
- **`session.py` (L1/L2)** — `semantic_cache_get/set` (key `sem_cache:{uid}`, threshold 0.92);
  `get/set/update/invalidate_profile`, `get/set_session`. `load_profile` reads Redis, falls
  back to a Postgres `users ⨝ user_profiles` join, warms the cache. `persist_profile_facts`
  writes whitelisted learnable facts (state/district/occupation, interests[], soil_type,
  land_size_acres, current_crops[], active_schemes[]) with COALESCE/union so it never clobbers
  explicit edits.
- **`episodic.py` (L4)** — `save_episode`, `recall_episodes(user, query_embedding, limit=5)`
  (ANN `embedding <=> query`, returns `similarity = 1 - distance`), `list_recent_episodes`.
- **`user_memory.py`** — Claude/ChatGPT-style durable memory. `add_memory` (semantic dedup at
  0.90, soft cap 200, evict oldest unpinned), `recall_memories` (all pinned + top-similar,
  default 6), list/update/delete/clear, `format_for_prompt`.
- **`context.py`** — `assemble_context()` gathers L0 synchronously then L2+L4+user-memory in
  parallel (`asyncio.gather`, exceptions → empty defaults), returns `AssembledContext`
  (working_memory, user_profile, session, episodic_context, user_memories, token_estimate,
  assembly_ms). Target **<35ms**.
- **`conversation_store.py`** — `persist_turn()` upserts the session (title from first query,
  bumps `turn_count`) and appends user+assistant rows to `conversation_logs`. Best-effort:
  never fails the request.

---

## 14. The LangGraph orchestrator (the heart)

`agents/orchestrator.py`. A `StateGraph(OrchestratorState)`, compiled once, invoked with
`recursion_limit=50`. Every node is `async` and traced.

### `OrchestratorState` (the shared dict)

Input/session: `query, session_id, user_id, correlation_id, document_id, doc_scope, filters`.
Safety/lang: `safety_tag, safety_confidence, language`. Classification: `domain, intent,
complexity, entities, wants_details, is_followup`. Clarify: `clarifications, needs_clarification`.
Context: `context, query_embedding`. Routing: `route, plan, mission`. RAG loop: `retrieval_query`
(the *standalone* context-resolved rewrite used for retrieval), `knowledge_pool, knowledge,
rag_loops, live_augmented, sufficient, query_variants, confidence, unsupported_claims,
supported_claims, abstained`. Citation agent: `extracted_claims, citations, citation_coverage`.
Output: `response_card, streaming_done, error`.

Every node is wrapped by a **`@traced_node`** decorator that attributes LLM token usage to the
node's step name, times it, and emits `node_enter`/`node_exit`/`node_metrics` flow logs — giving a
fully replayable per-node trace (also feeds `flow_console`).

### Nodes & routing

| Node | Does | Routes to |
| --- | --- | --- |
| **understand** | deterministic crisis/abuse rule-scan (SAFETY FLOOR, no LLM) → one merged fast-LLM call: subtle safety refine + domain/intent/complexity/entities + **route** + **`standalone_query`** (context-resolved rewrite for retrieval) + **`is_followup`** + **`wants_details`**; classifies the latest message *in context* of working memory | `safe_response` if tag≠normal, else `embed_query` |
| **safe_response** | templated crisis/official card (`build_safe_card`) | END |
| **embed_query** | dense BGE-M3 query vector | `assemble_context` |
| **assemble_context** | L0 + parallel L2/L4/user-memory | `clarify_check` |
| **clarify_check** | skipped if already answered / `!wants_details` / (task route with `IPA_ENABLED`); else `plan_clarification()` may build a `clarify` form | `finalize` if `needs_clarification`, else `plan_route` |
| **plan_route** | `decide_mission()` (reuses the route intake already chose); for research/multi_hop/task only, `generate_plans`+`select_plan`+`persist_plan` | by `route` (below) |
| **generate_simple** | single fast-LLM answer, no retrieval; `confidence=1.0` (not abstainable) | `finalize` |
| **task_execute** | full lifecycle to the PREPARE/CONFIRM boundary; with `IPA_ENABLED` returns an **`agent_task`** card that hands off to the live browser agent; never auto-executes | END |
| **multi_hop** | `decompose_query` → per-subquery grounded answer (+ GraphRAG fuse + live) → `synthesize` | `finalize` |
| **retrieve** | corpus/user-doc retrieval **and** live web **in parallel** (`asyncio.gather`); dedups into `knowledge_pool` | `grade_documents` |
| **grade_documents** | `grade_documents()` keeps relevant chunks, sets `sufficient` | live_augment / rewrite_query / generate |
| **live_augment** | `gather_live_knowledge()` (web/live tools) folded into pool | `grade_documents` (re-grade) |
| **rewrite_query** | `rewrite_query()` reformulates; bumps `rag_loops` | `retrieve` (loop) |
| **generate** | domain agent builds prompt (runtime header + agent rules + memory + reasoning/quality/synthesis/readability directives) → `route_completion(override_tier="primary")` → card; resolves inline media, gathers study resources; optional reflect/critic | `cite_claims` |
| **cite_claims** | **answer-first, cite-after**: `extract_claims` → `find_citations` web-searches any claim retrieval didn't back → folds found sources into `knowledge`/pool, merges per-claim sources onto the card, sets `citation_coverage`; carries `extracted_claims` forward | `verify_claims` |
| **verify_claims** | `verify_claims()` grounds claims (reusing `extracted_claims`) → confidence, supported/unsupported | `rewrite_query` only if `confidence<0.5` AND unsupported AND loops left, else `finalize` |
| **finalize** | corroboration + reliability score + safety gate (disclaimers/abstain) + speech_text + plan/mission + persist L0 + metrics | END |

### The five routes

- **simple_answer** — greeting/small-talk: no retrieval, conversational reply.
- **agentic_rag** — normal grounded factual answer with the retrieve⇄grade⇄rewrite loop.
- **multi_hop** — decompose into sub-questions, RAG each (optionally graph-fused), synthesize.
- **research** — like agentic_rag but with explicit multi-step planning.
- **task_execution** — return a PREPARE-only action preview; never auto-executes.

### `process_query()` (entry point)

```python
async def process_query(query, session_id, user_id, correlation_id=None,
                        document_id=None, filters=None, clarifications=None,
                        on_early_card=None) -> dict
```

Resolves language, starts metering, hydrates working memory (folding any `clarifications` in and
seeding `retrieval_query`), initialises the state, then:

- **REST path** (no `on_early_card`): `orchestrator.ainvoke(state, {"recursion_limit": 50})`.
- **Streaming path** (WebSocket passes `on_early_card`): `orchestrator.astream(..., stream_mode="values")`
  delivers the **first draft `response_card`** (right after `generate`) via `on_early_card`, while
  `cite_claims`+`verify_claims`+`finalize` keep running; the finalized delta is sent to the client
  later as a **`card_patch`** frame (merges deferred sources/reliability into the shown card in place).

Post-run (both): `persist_turn` (durable) and a **background** `learn_and_persist` (fire-and-forget
profile/memory learning), per-request metrics, and a consolidated `chat_summary` trace. Callers
never pass a language — it is resolved and enforced entirely inside the orchestrator. Returns the
final `state["response_card"]`.

---

## 15. Routing, planning & mission control

- **`controller.py` — Mission controller.** `decide_mission()` maps `route → mode`
  (simple_answer→answer, agentic_rag→inform, multi_hop/research→research, task_execution→task)
  and returns a `Mission(mode, route, capabilities, rationale)` with a default capability
  pipeline per mode (e.g. inform = understand→clarifier→memory→retriever→grader→live_data→
  reasoner→verifier).
- **`planner.py`.** `classify_route()` (rules first, fast-LLM fallback);
  `generate_plans()`→1–3 candidate `Plan`s (steps, rationale, reliability, est_cost);
  `select_plan()` scores `reliability − 0.05·steps − 0.10·cost`; `decompose_query()` splits
  multi-hop queries into 2–4 sub-questions; `synthesize()` merges grounded sub-answers.
  Selected plans persist to `task_history.plan` and are folded into the generation prompt via
  `reasoning_directive(plan)` so the answer actually follows the plan.
- **`grading.py`.** `grade_documents()` (fast-LLM relevance marking, keyword-overlap fallback,
  always keeps ≥1 chunk as a floor) and `rewrite_query()` (adds synonyms/official terms/section
  numbers; never injects a stale year; falls back to original on failure).
- **`capabilities.py`.** A single catalogue of every capability (classifier, clarifier,
  planner, retriever, grader, live_tool, reasoner, domain expert, synthesizer, verifier,
  memory, task_assistant, executor), auto-built from the domain registry + task assistants.
  Exposed via `GET /agents`.
- **`memory_extractor.py`.** After the answer is sent, a background fast-LLM pass extracts
  whitelisted **profile facts** (merged into `user_profiles`) and free-form **memories**
  (stored in `user_memories`, deduped) — capped by `MEMORY_MAX_NEW_PER_TURN`.
- **`reasoning.py`.** `reasoning_directive(plan)` and `quality_directive(domain, complexity)`
  bake reviewer/critic concerns into the generation prompt at zero extra cost;
  `reflect_and_improve` (opt-in `REASONING_REFLECT_ENABLED`, multi_step/action) and
  `critique_answer` (opt-in `CRITIC_ENABLED`, health/legal/finance) are optional extra passes.

---

## 16. Clarification (ask-back)

`agents/clarify.py`. Philosophy: ask for the few details that materially change the answer,
**at answer time via a form**, and **do not** persist them (they live in the turn's working
memory only).

`plan_clarification()` is the entry point (called by `node_clarify_check`). **The fast-LLM expert
intake is PRIMARY for all domains** — `llm_intake` uses per-domain `_EXPERT_PERSONAS` (senior
physician, SEBI advisor, senior advocate, agronomist…) to decide whether a form is warranted and
which fields matter; it can return a card, `None` (answer directly), or an "LLM unavailable"
sentinel. The deterministic **slot registry** (`assess_clarification` — `Slot` objects with
`satisfied_by(query, profile, answered, history)`; e.g. farming(crop) needs
location/land_size/soil_type/water_source, finance(loan) needs purpose/amount/tenure/income) is the
**FALLBACK** when the LLM is unavailable/errored or `CLARIFY_USE_LLM` is off. Either way it returns a
`clarify` card with only the missing fields (capped at `CLARIFY_MAX_FIELDS`=4), skipping anything
already satisfied by profile / prior answers / query text (`_looks_informational` also prevents
interrupting "what is X" questions). Sending back the original query with `clarifications: {}`
(empty) means "asked and skipped" — the backend answers generally instead of re-asking.

---

## 17. Domain agents

`agents/base.py` — `BaseAgent` (abstract): `build_system_prompt(context, profile, language)`
and `build_response_card(llm_output, language)`; shared `execute()` and `parse_card()`.
Agents are **stateless singletons** in `agents/registry.py`:

| Domain | Agent | Notes |
| --- | --- | --- |
| legal | LegalAgent | section+act citations; NALSA 15100; never invents case law |
| farming | FarmingAgent | state+season; local units; MSP + mandi; mention KVK |
| scheme | SchemeAgent | full-profile eligibility (PM-KISAN/Ayushman/PMAY) |
| student | StudentAgent | NCERT/exams; adaptive explanation; self-checks; code_editor |
| finance | FinanceAgent | never OTP/PIN; scam warnings; SEBI disclaimer |
| health | HealthAgent | informational only — never diagnoses/doses |
| career | CareerAgent | roadmaps, comparison tables, timelines |
| booking | BookingAgent | PREPARE only, never executes; no credentials |
| governance | GovernanceAgent | RTI, CPGRAMS, certificates |
| jobs | JobsAgent | MGNREGA/NCS; job-fee scam warnings |
| travel | TravelAgent | IRCTC/RTC; itinerary options; PREPARE only |
| documents | DocumentsAgent | Aadhaar/PAN/DigiLocker; never asks for full IDs/OTP |
| general | GeneralAgent | fallback |

`get_agent(domain)` returns the mapped agent or `general`. Disclaimers are attached
**centrally by the safety gate**, never inside agent prompts.

### Per-agent prompt rules (what each agent is instructed to do)

**LegalAgent** — cardTypes `step_action, answer, document, clarify`:
1. Every claim must cite section + act name (e.g. "Section 437 CrPC").
2. Respond in the user's language with simple words.
3. Never give a definitive legal opinion — recommend consulting a lawyer.
4. Draft complete documents (bail application, RTI, legal notice) in `summary` when asked.
5. Always mention the NALSA free legal-aid helpline **15100**.
6. Do **not** invent case law.

**FarmingAgent** — cardTypes `plan, answer, price_table, scheme_list, weather, clarify`:
1. Advice specific to the user's state and current season (Kharif Jun–Sep, Rabi Oct–Mar, Zaid otherwise).
2. Quantities in regional units (bigha/acre/hectare).
3. Always mention eligible government schemes.
4. Mention the nearest KVK for technical advice.
5. Price query → give both MSP and current mandi price.

**SchemeAgent** — cardTypes `scheme_list`:
1. Find **all** schemes the user is eligible for based on the full profile JSON.
2. Always check PM-KISAN (farmers), Ayushman Bharat (health), PM Awas Yojana (housing).
3. Match by state, occupation, income, age, gender.

**StudentAgent** — cardTypes `answer, step_action, plan, scheme_list, code_editor, clarify`:
explain concepts and problem-solving, build study plans/exam strategies pitched to the
learner's level; scholarships via `scheme_list`.

**FinanceAgent** — cardTypes `answer, step_action, plan, scheme_list, clarify`:
1. Never ask for or store OTP, PIN, or password.
2. Always warn about scams.
3. Disclaimer: "Consult a SEBI-registered advisor for investments."

**HealthAgent** — cardTypes `answer, step_action, scheme_list, clarify`:
never diagnoses, never names medications/doses; recommend a licensed professional; emergencies
→ direct to official help; source-grounded only.

**CareerAgent** — cardTypes `answer, timeline, comparison_table, step_action, clarify`:
practical roadmaps, realistic timelines, no guaranteed jobs/salaries; Socratic for mentoring.

**JobsAgent** — cardTypes `answer, step_action, scheme_list, clarify`:
official portals (NCS/Sarkari), clear eligibility, warn that genuine govt jobs never charge fees.

**TravelAgent** — cardTypes `plan, timeline, step_action, answer, clarify`:
PREPARE only (no auto-booking), 2–3 itinerary options (budget/balanced/comfort), cost grounded,
required documents, warn about unsafe links.

**BookingAgent** — cardTypes `step_action, answer, clarify`:
PREPARE only; never handle OTP/PIN/card/bank/Aadhaar/PAN; exact preview steps + costs.

**DocumentsAgent** — cardTypes `step_action, answer, clarify`:
exact portal + required docs; never ask to share full Aadhaar/PAN/OTP; cite the issuing
authority (UIDAI, Income Tax Dept, Passport Seva, DigiLocker).

**GovernanceAgent** — cardTypes `step_action, answer, clarify`:
exact procedure + correct portal; cite the rule (e.g. RTI Act 2005); surface NALSA 15100; never
fabricate procedures.

**GeneralAgent** — cardTypes `answer, step_action, clarify, code_editor`: concise fallback.

> **Note:** the 13 domain agents do **no** code-level tool-calling/retrieval — "knowledge" is injected
> as pre-formatted text and tool-style behaviour (apply-to-jobs, form-fill, bookings) is described in
> prompts and carried out by the separate confirmation/IPA flows. Health, Booking and Governance were
> promoted from stubs to full experts in `demo_ver_0.11`.

---

## 17a. General agentic task executor (`agentic.py`)

`agents/agentic.py` is a **tool-calling ReAct (reason→act→observe) task agent** — *not* an
alternative to the whole orchestrator. It is invoked **inside** the task route
(`node_task_execute` → `plan_task` branch) as `run_agentic_task(...)` to actually *accomplish* an
open-ended task instead of emitting a static "Step 1/2/3" template.

- **Portable JSON action loop** (provider-agnostic — works on Gemini too, not provider
  function-calling). Each model turn returns exactly one JSON object: `{"thought","tool","tool_input"}`
  to call a tool, or `{"thought","final":{…card…}}` to finish.
- **Tools** come from the **live MCP registry** (`mcp.tools._TOOLS`) filtered to `read_only`, so any
  newly-registered read-only tool is automatically available (hints for web_search, web_fetch,
  job_search, scholar, books, weather, mandi_prices, finance, news). A special `generate_file` action
  builds a PPTX/DOCX via `generate_deliverable`.
- **Control flow** (`run_agentic_task`, default `max_steps=4`): build system+task prompt →
  `route_completion(override_tier="primary")` → `_parse_action` → if `final` return the card (merging
  tool sources); if `generate_file` build + return; else `await tool.call(...)`, render a compact
  observation, append it as an OBSERVATION message, repeat. On unknown tool / out of steps, ask the
  model to finalize.
- **Safety:** tools are read-only and their output is untrusted DATA; the agent never handles
  credentials; anything that moves money/submits/books is described as a step for the user to confirm
  — the PREPARE→CONFIRM→EXECUTE boundary is unchanged. Returns `None` on total failure so the caller
  can fall back to `_compile_task_preview` then a static template. **Never raises.**

---

## 18. Safety, verification & reliability

`src/safety/`. Two touch points: **intake pre-screen** (before retrieval) and the
**verification/safety gate** (before delivery).

- **`prescreen.py`** — `prescreen(query)` → `PreScreenResult(tag, confidence, method,
  matched_keywords)`, tag ∈ `normal | self_harm | medical_emergency | child_safety |
  fraud_scam | harmful_instructions`. High-recall keyword rules (English + Devanagari),
  optionally refined by a fast LLM (`SAFETY_PRESCREEN_USE_LLM`). False positives fail safe.
- **`resources.py` / `handlers.py`** — official crisis resources are **config-driven**; the
  system never hardcodes unverified helpline numbers (only NALSA **15100** is baked in).
  `build_safe_card(tag, language)` returns a supportive card with verified pointers.
- **`gate.py` — `VerificationSafetyGate` (singleton `gate`).** The single pre-delivery choke
  point: `safety_filter` (non-normal tag → safe card), `verify_claims`, `decide_abstain`
  (`confidence < CONFIDENCE_ABSTAIN_THRESHOLD`), `apply_disclaimers` (legal→lawyer+NALSA,
  finance→SEBI + never-share-OTP, health→licensed professional, scheme→verify on portal), and
  `finalize()`. Default mode is **deliver-with-score** (answer always shown, stamped with a
  reliability band); the old hard block is opt-in via `ABSTAIN_ON_LOW_CONFIDENCE`.
- **`verification.py`** — `verify_claims(draft_text, knowledge)`: fast-LLM extracts atomic
  claims, checks each against cited evidence (token-overlap fallback), returns
  `confidence = supported/total` (floored by `VERIFY_PARTIAL_SUPPORT_FLOOR`). No-evidence is
  treated as "unverifiable" (`VERIFY_NO_EVIDENCE_CONFIDENCE`), not "refuted".
- **`scoring.py`** — `score_answer(...)` → `ReliabilityScore(score, band, label, warn,
  applicable, signals, reasons)`. Six weighted signals: grounding 0.38, corroboration 0.22,
  source authority 0.16 (`.gov.in/.nic.in/.rbi/.sebi/who.int/.ac.in` etc. score highest), evidence
  strength 0.14, coverage 0.10, **citation 0.12** — **weights are renormalized over the applicable
  signals only**. Guards: hallucination veto (evidence present but grounding≤0 → cap 0.30),
  unverifiable cap (no evidence/source → 0.60), corroboration lift (multiple independents agree →
  floor 0.72). Bands from `RELIABILITY_HIGH/WARN/LOW_THRESHOLD` (0.75/0.5/0.3): high/medium/low/very_low;
  greetings → `not_applicable`.
- **`corroboration.py`** — `corroborate(claims, knowledge)`: counts **independent publishers**
  per claim (registrable domain via `independence_key`), maps 0/1/2/≥3 independents → 0/0.5/0.8/1.0,
  and marks "strong" when independents ≥ `CORROBORATION_MIN_SOURCES` and agreement ≥ threshold.

---

## 19. Adaptive-explanation synthesis & deliverables

`src/synthesis/explanation.py`. Before writing prose, `build_explanation_plan(query, domain,
profile, language)` produces an `ExplanationPlan`:

- **LearnerProfile** — persona (student / professional / mentee / general), prior knowledge,
  goal, reading level — inferred from L2/L4 memory (assumptions logged when thin).
- **depth** — quick | working | mastery. **teaching_format** — analogy | worked_example |
  concrete_first | socratic | contrast | plain. **modality** — prose by default, escalating to
  `comparison_table` / `step_cards` / `timeline` / `map` / `interactive_widget` / `diagram`
  only when a visual carries meaning (rejected visuals are logged).

It's deterministic (no LLM). `synthesis_directive` steers generation; `modality_directive` supplies
the card JSON schemas; `layout_directive` supplies the inline block vocabulary
(`[[keypoints:]]`, `[[callout:]]`, `[[stats:]]`, `[[chart:]]`, `[[diagram:]]`, `![](img://…)`).
`enrich_card` attaches `key_takeaway`, `explain_differently`
(`["simpler","deeper","with_example","in_<lang>"]`), and for students an `understanding_check`.
`preferences.py`'s `learn_preferences(user_id)` reads the last 100 `feedback` rows joined to
`task_history` cards and upserts a `{modality, goal, preferred_length}` vector into
`user_profiles.preferences`; `POST /explain-differently` logs clicks.

### Downloadable deliverables & inline media (NEW)

- **`deliverable.py` — `generate_deliverable(topic, fmt, owner_id, …)`** produces a **downloadable
  PPTX or DOCX** (`fmt ∈ {pptx, docx}`). Flow: fast structured JSON spec (4–7 sections, bullets +
  speaker notes + optional chart/image) → parallel image fetch → `filegen.build` (bytes) →
  `file_store.store_file` (link) → returns a `document` card with an inline outline, a `preview`
  (title + per-section slides) and a `download {url:/files/{id}, filename, format, mime}`. Returns
  `None` (fall back to text) if the libs are missing.
- **`filegen.py`** — pure byte builders: **DOCX and PPTX only** (no PDF/XLSX/CSV), plus matplotlib
  PNG charts (bar/line/pie, accent `#C2703D`) and flow diagrams. `build(fmt, spec)`,
  `libraries_available()`. All heavy libs (python-docx, python-pptx, matplotlib, Pillow) lazy.
- **`file_store.py`** — **Redis-backed** cross-worker download store, key `nipun:genfile:{fid}`,
  **TTL 24h**. `store_file(owner_id, filename, mime, data)` → uuid file_id; `get_file(id)`. Ownership
  is carried in the record and enforced by the `/files/{id}` route.
- **`inline_media.py`** — resolves visual markers **in place** in the Markdown `summary`: inline
  images (real or generated), chart PNG data-URIs, native SVG diagrams, file embeds, and rich blocks
  (keypoints/callouts/stats/swatches). Caps `_MAX_INLINE=4`, `_MAX_EMBEDS=2`; unresolvable markers
  are dropped, never shown broken.
- **`resources.py`** — `gather_study_resources` (videos + articles) plus the shared image library
  (`best_image`, `generate_image_bytes` — DALL·E 3 if keyed else keyless Pollinations.ai; providers
  SerpAPI → Google CSE → Openverse → Wikipedia) and `promote_media_card` (upgrades an answer to a
  video/browser/book card when explicitly requested and backed by a real URL).

---

## 20. MCP tools & live data

`src/mcp/`. Uniform tool interface; **tool output is untrusted DATA** (scanned for injected
instructions), **credentials are never accepted**.

- **`base.py`** — `MCPTool` ABC with `call(params)` that asserts no credentials, runs `_call`,
  and wraps text via `wrap_untrusted` (surfacing `suspected_instructions`). `ToolResult(tool,
  status, data, text, suspected_instructions)`, `status ∈ ok|unavailable|error|blocked`.
- **`tools.py`** — registry `_TOOLS` built at import by instantiating every tool class, keyed on
  `.name`: `web_search, web_fetch, finance, weather, mandi_prices, news, scholar, books, shopping,
  gmail, google_drive`, plus NEW `job_search, wikipedia, youtube`, plus four legacy guarded stubs that
  always return `unavailable` (`indiankanoon, agmarknet, imd_weather, digilocker`). `get_tool`, `list_tools`.
  Tool catalogue by id:

  | tool id | fetches |
  | --- | --- |
  | `web_search` | Tavily → Google CSE → Brave → SerpAPI → DuckDuckGo → Wikipedia (first non-empty) |
  | `web_fetch` | any http(s) URL, HTML-stripped, first 6000 chars |
  | `finance` | Yahoo Finance (keyless) + Alpha Vantage (if key) |
  | `weather` | Open-Meteo geocode + forecast (keyless, India) |
  | `mandi_prices` | Agmarknet via data.gov.in (`DATA_GOV_IN_API_KEY`) |
  | `news` | NewsAPI (if key) else GDELT DOC 2.0 (keyless) |
  | `scholar` | Semantic Scholar + arXiv + PubMed |
  | `books` | Open Library + Google Books (+ optional Celery ingest) |
  | `job_search` **[NEW]** | Remotive + Arbeitnow + `site:`-scoped search over Indian portals (naukri, linkedin/jobs, indeed.co.in, foundit, instahyre, ncs.gov.in) |
  | `wikipedia` **[NEW]** | MediaWiki API (user-language edition then en), plain-text intros |
  | `youtube` **[NEW]** | video discovery + **transcripts** (youtube-transcript-api) as grounding |
  | `shopping` | reuses web_search; ranks products across 11 Indian platforms |
  | `gmail` / `google_drive` | consent-gated, read-only (OAuth token) |

- **`live/selector.py`** — `select_tools_llm(query, domain, intent)` (fast-tier LLM picks 1–3 tools
  from a fixed catalog; strict-JSON, only catalog names honored, `None` on failure). Gated by
  `LLM_TOOL_SELECTION`; deterministic `_select_tools` (keyword/domain triggers, `web_search` always
  India-scoped) is the fallback.
- **`live/aggregator.py`** — `needs_live_data(query, domain, intent)`; `gather_live_knowledge()` is
  the single entry point: `_pick_tools` → concurrent fan-out with a global wall-clock cap
  (`LIVE_AUGMENT_TIMEOUT`, stragglers cancelled, partials kept) → surfaces (never executes) suspected
  injections → `_to_chunks` normalizes each `ok` result into cited knowledge chunks
  (`retrieval_method="live_tool"`, descending `relevance_score`) feeding the grade→generate→verify path.
- **`live/*`** — `http` (never-raises helpers), `web` (the fallback chain above), `finance`, `data`
  (Open-Meteo/Agmarknet/news), `research` (Semantic Scholar/arXiv/PubMed, Open Library/Google Books),
  `jobs`/`youtube`/`knowledge` (the new tools), `apps` (consent-gated Gmail/Drive), `shopping` (ranked
  product comparison over trusted Indian platforms).

Exposed via `GET /tools` and `POST /tools/call` (read-only tools only).

---

## 21. Task execution (PREPARE→CONFIRM)

`src/execution/`. Nothing side-effecting runs without an explicit confirm, and only if
`EXECUTION_ENABLED=true` **and** a handler is registered (the registry ships empty by design).

- **`executor.py`** — `prepare(action, params, user, session, cid)` validates + builds a
  human-readable preview + mints a token (does **not** execute); `execute(token, …)` runs the
  handler only after checks (token valid, owned, unexpired per `EXECUTION_CONFIRM_TTL`,
  `EXECUTION_ENABLED`, handler exists); `reject(token)`. Every phase writes an append-only
  `task_audit` row (payloads redacted).
- **`circuit_breaker.py`** — per-session sliding window; `CIRCUIT_BREAKER_TOOL_CALLS_PER_MIN`
  / `..._AGENT_CALLS_PER_MIN`; raises `CircuitOpenError` (surfaced as 429).
- **`guards.py`** — `scan_for_credentials` / `assert_no_credentials` block Aadhaar/PAN/card/
  OTP/CVV/PIN/password in any tool or action payload; `wrap_untrusted` flags prompt-injection
  attempts in external content.

API: `POST /tasks/prepare` → `POST /tasks/confirm` / `POST /tasks/reject`. Read-only previews
via `GET /tasks` + `POST /tasks/preview`. Durable multi-step "do X until done" tracking lives
in `tasks/store.py` (`service_tasks` table, credentials scrubbed).

The **credential firewall** (`guards.scan_for_credentials` / `assert_no_credentials`) is enforced at
every boundary: MCP tool calls, task previews, executor PREPARE, form filling, and IPA planning. It
blocks Aadhaar/PAN/card/OTP/CVV/PIN/password (banking-qualified `PIN` so "pin code" is fine; card
false-positive guard needs ≥13 digits) and logs **types only, never values**. Prompt-injection is
*surfaced* not blocked: `wrap_untrusted(source, text)` flags "ignore previous instructions"-style
content as DATA so it is never executed.

---

## 21a. Task-automation subsystem (`tasks/`)

Two notions of "task" plus a durable store. Universal safety model: **preview → confirm**; the agent
never handles login/password/OTP/PIN/card/CVV/Aadhaar/PAN or the final submit.

- **`store.py`** — durable Postgres `service_tasks` (`service, status, filled(jsonb),
  remaining_steps, tracking, due_at`; statuses `gathering→filled→awaiting_user→submitted→in_progress→
  completed/cancelled/failed`). `_scrub(filled)` drops credential-bearing fields — **credentials are
  never persisted.** `create_task`, `update_status` (jsonb tracking merge), `list_active`.
- **`assistants.py`** — read-only preview assistants + the router. `TaskAssistant` ABC (`run` calls
  `assert_no_credentials`, sets `preview_only=True` + disclaimer). Concrete: `FindDeals`,
  `BuildItinerary`, `AssembleITRDraft`, `PrepareBillPayment`, `DynamicFormAssistant`, `PlanTask`.
  **`select_assistant(domain, intent, query, context)`** is a data-driven precedence router (URL+fill →
  `form_dynamic`; bill → bill-payment; itr → itr-draft; apply+job → `form_job_application`; resume/cv →
  tailor/build; reskill → learning-plan; rti/train/doctor/bail/document → forms; travel/buy →
  itinerary/deals; fallback `plan_task`).
- **`career.py`** — `ResumeBuilder`, `TailorResume`, `LearningPlanBuilder` (strict-JSON LLM), and the
  `JOB_APPLICATION_FORM` (`form_job_application`) with autofill FieldSpecs + user-only steps for
  login/upload/submit/OTP. `register_career_assistants()` runs at import.
- **`job_apply.py`** — active flow `run_job_application(query, profile, answers, …)`: `_infer_target`
  (LLM → role/skills/location/level) → FIND via the `job_search` MCP tool → PREPARE non-credential
  fields → returns a `step_action` card with up to 6 openings + a fixed hand-off + `filled_form`.
- **`forms.py`** — `FieldSpec`/`FormAssistant` (`form_{service}`); `ready = specs_satisfied AND
  _live_verified` (prevents false-ready hand-off). Instances: `RTI_FORM`, `DOCTOR_APPOINTMENT_FORM`,
  `TRAIN_BOOKING_FORM`, `BAIL_APPLICATION_FORM`, `DOCUMENT_APPLICATION_FORM`.
- **`form_analyzer.py`** — deterministic `HTMLParser` form extraction: `extract_form_fields(html)` →
  `[{name,id,type,label,placeholder,required,options,sensitive}]`; label resolution `<label for>` →
  aria-label → placeholder → title → name; `is_sensitive_field` / `_SENSITIVE`.
- **`dynamic_fill.py`** — `fill_form_on_site(url, profile, answers, query)`: FETCH → ANALYZE
  (split safe/sensitive) → MAP (strict-JSON LLM) → HAND OFF (skip credential-flagged, compute missing,
  `ready = not missing`). Returns a `step_action` card. Never raises.

`tasks/__init__.py` merges both families (`get_assistant = preview or form`,
`list_assistants = preview + form`). `api/routers/tasks.py` exposes them (see §30);
`api/routers/task_agent.py` is the separate live-IPA router (§21b).

---

## 21b. IPA — live browser automation

`src/ipa/` is a server-side **browser-use / "set-of-marks" agent** that *actually executes* tasks
(book/apply/fill/search-and-act) in a real headless Chromium, with live WebSocket streaming and
human-in-the-loop hand-off at login/OTP/payment/final-submit. Gated by `IPA_ENABLED` (default True).
Canonical loop: **plan → perceive → decide → act → verify.**

**Entry:** the orchestrator's `task_execution` route (with `IPA_ENABLED`) returns an `agent_task`
card carrying the goal; the frontend "Start" button then calls `POST /task/start` → opens
`WS /ws/task/{task_id}`.

- **`schemas.py`** — stdlib dataclasses: `RunStatus` (`planning, awaiting_input, comparing,
  awaiting_choice, running, paused, needs_human, done, failed, stopped`), `StepStatus`,
  `ChecklistStep`, `FormField` (password excluded), `TaskPlan{goal, start_url, steps, form_fields,
  surface(web|app|device), actions, target}`, `AgentAction{type(click|type|select|scroll|navigate|
  wait|done|ask_human|press|fail), index, text, thought}`, and `event(kind, task_id, **data)` (the WS
  envelope). No result model — the terminal `RunStatus` + a final `done` event are the result.
- **`planner.py`** — `plan_task(goal, profile, …) → TaskPlan`. One primary-tier LLM call, grounded on
  `targets.candidates(goal)` + a recipe seed. Chooses the surface (web default), emits a 3–9 step
  checklist + a consolidated form (credential field names hard-filtered). Never raises (5-step web
  fallback).
- **`controller.py`** — `run_in_worker(session)` spawns a daemon thread with its own
  **`ProactorEventLoop`** (the Windows/uvicorn Playwright fix). `execute()` dispatches by surface:
  web → `_compare_and_choose` then `agent.run_task`; app → `executors/app`; device → `executors/device`.
- **`agent.py`** — the web loop (never raises). Fast-path `_try_replay` uses a proven recipe
  (`success_count ≥ 2`, no per-step LLM). Else per step: sensitive → hand off; else ≤7 LLM decisions
  (batched actions, text-first with a vision fallback) → `browser.act` → stream events. **Fill-and-
  hand-off, never auto-submit** is enforced LLM-independently: `_is_final_submit` reads DOM form
  descriptors (`in_form`/`form_method`/`submits`; non-GET submit/Enter/post-fill click → hand off),
  `_is_sensitive_target` is a multilingual keyword backstop, `_is_auth_page` hands off any page with a
  visible password/OTP field. Hand-off waits up to `IPA_HUMAN_WAIT_TIMEOUT` (600s). On success:
  `recipes.save_recipe` + profile learning.
- **`browser.py`** — `BrowserSession` (lazy Playwright async Chromium, headless, anti-automation flags,
  en-IN, 1280×800). `perceive()` runs `_MARK_JS` tagging visible interactives with `data-ipa-index`
  and numbered overlay boxes (**set-of-marks**), returns descriptors incl. form context (cap 120);
  JPEG screenshots (clean → user, marked → vision LLM). `act(type, index, text)` via the stable
  `[data-ipa-index]` selector. User remote-control methods (`user_click/type/key/scroll`) drive the
  same server browser during hand-off.
- **`targets.py`** — India-first ranked `CATALOG` keyed by category (train→IRCTC, flight, hotel,
  bus→redBus, jobs→Naukri, shopping→Amazon.in/Flipkart, food→Zomato/Swiggy, grocery→Blinkit/BigBasket,
  movies→BookMyShow, bills→BBPS, govt→UMANG/DigiLocker…). `is_trusted` is a **trust gate** — a host
  must match `TRUSTED_HOSTS` or it is dropped.
- **`recipes.py`** — reusable HOW recipes (site + checklist + generalized action trace) with **no
  personal data** (typed values stored as the field *name*). Postgres `task_recipes`. `save_recipe`
  (dedupe by keyword Jaccard ≥0.7 → bump `success_count`), `find_recipe` (best overlap ≥0.34). An
  IRCTC "Lucknow→Shimla" run teaches a later "Pune→Goa" run.
- **`compare.py`** — for comparable goals (flight/hotel/bus/shopping/food/…, "cheapest/best/vs"),
  `gather_options` India-first-searches trusted sources, LLM-ranks 3–4, re-applies the trust gate.
  Official single-source goals (train/bills/government) are excluded.
- **`session.py`** — `TaskSession` (run state, `main_loop`/`agent_loop`/`browser` handles, event queue
  maxsize 256 + rolling 400 history, **plain-bool control flags** polled by the agent thread — atomic
  under the GIL). In-memory `_SESSIONS` + Redis mirror `nipun:task:{task_id}` (TTL 3600s); persisting
  a `running` status blocks duplicate launches across workers.
- **`executors/app.py`** — applies `plan.actions` from an allowlist `{navigate, set_setting,
  update_profile, open_url}`; backend decides, client applies, streamed as `app_action`. Safe by
  construction. **`executors/device.py`** — OFF by default (`DEVICE_EXECUTION_ENABLED=False`);
  allowlist `{write_file, read_file, list_dir}`, every path through a `_safe_path` sandbox
  (`DEVICE_SANDBOX_DIR`) that rejects `..`/absolute/symlink escape. No shell, no installs.

> **Deployment note:** the live Playwright page + Proactor thread live only in the uvicorn worker that
> launched the run — a browser can't cross processes, so `/ws/task/{task_id}` needs **sticky routing by
> `task_id`** (or a single worker). Narration goes to `ipa.log` via `core/ipa_console.py`. Full WS
> protocol in §30.

---

## 22. Research (RLM) & GraphRAG

- **RLM** (`research/rlm.py`) — `research(question, document)` chunks a long document
  (`RLM_CHUNK_CHARS`), inspects up to `RLM_MAX_SUBCALLS` chunks with bounded fast-LLM
  sub-queries ("extract facts relevant to Q; else NONE"), then reduces the notes into a final
  answer. Returns `ResearchResult(answer, sub_calls, chunks_inspected, truncated)`. It's a
  constrained inspector, not an arbitrary code sandbox.
- **GraphRAG** (`src/graph/` + `db/neo4j.py`, optional, `GRAPH_ENABLED`) — a Neo4j relational
  tier. `graph/schema.py` holds authoritative allowlists (VALID_ACTS, VALID_MINISTRIES);
  `graph/build.py` builds legal (`Section-belongs_to-Act`, `-related_to-`, `-amended_by-`) and
  scheme (`Scheme-requires-Criterion`, `-administered_by-Ministry`, `-excludes-`) graphs;
  `graph/retrieval.py` `graph_search` + `rrf_fuse` run **only** on the multi-hop route and
  fuse graph pseudo-chunks with vector results. Degrades to a validated dry-run without Neo4j.

---

## 23. A2A (agent-to-agent)

`src/a2a/card.py` (optional, `A2A_ENABLED`). Specialists expose a **signed Agent Card** at
`/.well-known/agent.json`. `sign_card`/`verify_card` use HMAC-SHA256 over the whole card and
require the `agent_id` to be in `A2A_TRUSTED_AGENTS` (defeats card-inflation injection).
`issue_m2m_token`/`verify_m2m_token` mint short-lived (`A2A_TOKEN_TTL`) OAuth2-style M2M JWTs
(`scope="a2a"`) for calling trusted specialists.

---

## 24. Ingestion pipeline

Flow: **parse → chunk → dedup → embed → dual-write → record**.

- **`parser.py`** — `parse_pdf` (pypdf), `parse_html` (BeautifulSoup+lxml, strips
  script/style/nav/footer/header/aside/form), `parse_text`. `_clean_text` collapses whitespace
  and strips page numbers. Dedup key `source_hash = SHA-256(content)[:16]`.
- **`chunker.py`** — hierarchical: paragraphs → ~512-token chunks with ~50-token overlap;
  oversize paragraphs split by sentence; hard 6000-char ceiling. Detects section headers
  (Section/धारा/…, Chapter, Article, numbered clauses) and carries `section`, `chunk_index`,
  `page_number`, `token_estimate`.
- **`indexer.py`** — embeds via BGE-M3, then **dual-writes in parallel**:
  - **Qdrant** — `PointStruct` (dense + sparse) + rich payload (text, title, source,
    source_url, section, domain, language, subject, level, book_id, visibility, `active`,
    and for user docs `owner_id`/`document_id`/`session_id`); batches of 100.
  - **Elasticsearch** — `async_bulk` into `es_index_name(domain)`, field boosts title^3,
    section^3, keywords^2, content^1.
- **`pipeline.py`** — `ingest_spec(spec)`: resolve (inline/URL/PDF/file) → detect language →
  optional archive → **dedup** against `document_index` → chunk → index → record. Returns a
  status dict (`success | skipped | ...`).
- **`sources/`** — one `BaseIngestionSource` per domain, each with `seed_documents()` (curated
  offline pack — also the corpus the golden sets check against) and `official_sources()`
  (public URLs, pulled only with `--online`). CLI: `python -m src.ingestion.run --all [--online]`.
- **`user_docs.py` / `admin_docs.py`** — private user uploads (owner-tagged, into
  `user_documents`) vs. shared public corpus (admin). Auto-classify domain/subject/level.
- **`books.py`** — open-access books from Gutenberg / Internet Archive / OpenAlex.

---

## 25. Background jobs (Celery)

`worker/celery_app.py`: Redis broker/backend, `timezone="Asia/Kolkata"`, `task_acks_late`
(re-queue on crash), `worker_prefetch_multiplier=1` (embedding is heavy), JSON serialization,
per-task queues (`ingestion.document`, `ingestion.realtime`). Lifecycle signals log start/
finish/retry/failure and flow-trace each task.

**Beat schedule:**

| Job | Cadence | Task |
| --- | --- | --- |
| update mandi prices | every 6h (:00) | `update_realtime_data("mandi_prices")` (Agmarknet — TODO) |
| update weather | every 4h (:30) | `update_realtime_data("weather")` (IMD — TODO) |
| daily document scan | 02:00 IST | `batch_reindex(domain="all")` (TODO) |

Tasks (`ingestion/tasks.py`): `process_document` (reuses `ingest_spec`), `ingest_domain`,
`ingest_books_topic`, `ingest_book_url`, `update_realtime_data`, `batch_reindex`.

---

## 26. Database schema

Migrations `db/migrations/001…010.sql`, run in order by `db/migrate.py` (`make migrate`). There is
**no migration-tracking table** — every file re-runs on each `make migrate`, so all are written
idempotently (`IF NOT EXISTS` / `ON CONFLICT`).

- **001_init** — extensions (`vector`, `uuid-ossp`); `users`, `user_profiles`, `sessions`,
  `conversation_logs` (**partitioned by quarter** on `created_at`, 90-day cleanup helper),
  `episodic_memory` (`embedding vector(1024)`), `task_history`, `document_index` (dedup on
  `UNIQUE(source_url, source_hash)`), `feedback`.
- **002_auth** — `users`: `name`, `email` (UNIQUE), `password_hash`; `phone` now optional.
- **003_profile_admin** — `users`: `role` (`user|admin`), `is_active`, `bio`, `interests[]`,
  `ai_model` (`auto`), `theme` (`saffron`); `sessions.title`; `idx_users_role`.
- **004_agentic** — `task_history.plan JSONB`; append-only **`task_audit`** (tool, phase
  `prepare|confirm|execute|reject|audit`, redacted payload/result).
- **005_user_documents** — **`user_documents`** (owner_id, session_id, mime, source_hash,
  language, domain, subject, level, status `processing|ready|failed`, chunk_count, size_bytes,
  visibility, error, metadata; `UNIQUE(owner_id, source_hash)`); enriches `document_index`
  (book_id, author, subject, level, publication_year, visibility, metadata).
- **006_service_tasks** — **`service_tasks`** (service, status lifecycle
  `gathering→filled→awaiting_user→submitted→in_progress→completed/cancelled/failed`, `filled`
  JSONB with credentials scrubbed, `remaining_steps`, `tracking`, `due_at`).
- **007_profile_prefs** — `users` UI/onboarding prefs: `ui_preset`, `motif`, `text_scale`,
  `high_contrast`, `voice_enabled`, `festive_accents`, `age_band`, `gender`, `languages_known[]`.
- **008_user_memory** — **`user_memories`** (content, kind `fact|preference|goal|context`,
  `embedding vector` — **dimension-agnostic** bare `vector`, sequential cosine scan, no ANN;
  `source_session`, `pinned` never auto-evicted).
- **009_onboarding** *(NEW — no new table)* — `users.onboarded BOOLEAN NOT NULL DEFAULT FALSE`, the
  server-side source of truth for onboarding completion (replaces per-browser localStorage; enables
  cross-device sync). Backfill marks existing profiled users (`state` or `age_band` present) onboarded.
- **010_task_recipes** *(NEW)* — **`task_recipes`** — reusable IPA browser-agent recipes, shareable
  across users with **no personal data/credentials** (action values are field-name placeholders):
  `host, goal, keywords, start_url, steps(jsonb), trace(jsonb), form_fields(jsonb), created_by,
  success_count, created_at, updated_at`; indexes on `host` and `updated_at DESC`.

Core tables at a glance:

- **users** — identity + role + profile scalars + UI prefs; indexes on phone/email/role.
- **user_profiles** — extended farming/lifestyle (`preferences` JSONB, land/soil/crops/schemes,
  last_lat/lon).
- **sessions** — one per conversation (`turn_count`, `title`, language, domain).
- **conversation_logs** — durable transcript (partitioned, indexed by session/user+time).
- **episodic_memory / user_memories** — pgvector semantic recall.
- **task_history / task_audit / service_tasks** — planning + action audit + durable tasks.
- **document_index** — ingestion dedup + rich metadata.
- **feedback** — `rating ∈ {-1, 1}` + comment, linked to a task/correlation id.

---

## 27. Vector & search stores

**Qdrant** (`db/qdrant.py`): **one collection per domain** (all 7 languages share it — BGE-M3
is cross-lingual) for the 13 `SUPPORTED_DOMAINS`, **plus one shared `user_documents`
collection** ⇒ **14 collections total**. Each: dense size = `EMBEDDING_DIM` (1024, COSINE) +
sparse; `indexing_threshold=10000`; int8 quantization (`QDRANT_QUANTIZATION_ENABLED`) with
rescore oversampling ×2.0. Payload indexes: corpus → `source, language, subject, level,
book_id, visibility, active`; user docs → `owner_id, document_id, session_id, language,
subject, level, active`. On startup any collection whose dense dim ≠ `EMBEDDING_DIM` is
recreated. `language` is a payload field, not part of the collection name.

**Elasticsearch**: one index per domain `nipun_ai_{domain}` (or `{domain}_{lang}` depending on
`es_index_name`); fields `title^3, section^3, content, keywords^2, language, source, domain,
date`; 1 shard / 0 replicas (dev). Used only for exact-identifier BM25.

---

## 28. Observability (logging, metrics, metering)

- **`core/logging.py`** — structlog to rotating files (10MB×5) via `setup_logging()`. Base files:
  `app.log` (INFO+ catch-all), `error.log`, `access.log`, `frontend.log` (browser logs via
  `POST /logs`), `flow.log` (the `flow_console` story), and **`chat.log`** — the complete
  per-request chat-pipeline trace via `trace_flow(step, correlation_id, **data)` (query →
  classification → route/plan → chunks+scores → generation → citation → verification → reliability →
  final card → one `chat_summary` line), gated by `LOG_FLOW_ENABLED` / **`LOG_FLOW_CONTENT`
  (default False — bodies off for security)** / `LOG_CONTENT_MAX_CHARS`. **Subsystem views** route by
  logger-name prefix (each record also stays in `app.log`): `llm.log`, `retrieval.log`, `agents.log`,
  `safety.log` (`safety.*`+`execution.*`), `db.log`, plus NEW `ipa.debug.log` (`ipa.*`), `tasks.log`,
  `ingestion.log`; dedicated non-propagating loggers back `access`/`frontend`/`chat`/`flow`/`ipa_flow`
  (IPA narration → `ipa.log`)/`terminal`. `mask_pii` redacts phone/aadhaar/pan/email/password/token/otp
  on every line; bodies are `redact()`-ed. Console shows WARNING+ only.
- **`core/flow_console.py` / `core/ipa_console.py`** (NEW) — human-readable narration driven by the
  orchestrator's `traced_node` wrapper (no per-node wiring). `flow_console` writes the query-flow story
  (`query_start`/`node_flow`/`query_end`) to `flow.log` + a terminal heartbeat (gated by
  `FLOW_CONSOLE_ENABLED`/`TERMINAL_ENABLED`); `ipa_console` writes the browser-run story
  (`task_start`/`step`/`action`/`handoff`/`task_end`) to `ipa.log` (`IPA_CONSOLE_ENABLED`).
- **`core/metrics.py`** — ~40 Prometheus metrics, e.g. `nipun_queries_total{domain,language,
  status,agent}`, `nipun_llm_tokens_total{model,provider,direction}`, `nipun_llm_duration_ms`,
  `nipun_retrieval_duration_ms{stage}`, `nipun_memory_assembly_ms`, `nipun_agent_calls_total`,
  `nipun_safety_prescreen_total{tag,method}`, `nipun_safety_gate_total{outcome}`,
  `nipun_abstentions_total`, `nipun_reliability_score` / `_band_total`,
  `nipun_rag_loops_per_query`, `nipun_claims_unsupported_ratio`, `nipun_documents_graded_total`,
  `nipun_plan_route_total{route,method}`, `nipun_tool_calls_total{tool,status}`,
  `nipun_task_lifecycle_total{phase,task}`, `nipun_circuit_breaker_trips_total`,
  `nipun_credential_blocks_total`, `nipun_a2a_card_verifications_total`, `nipun_eval_*{domain}`.
  Latency buckets: 25…10000ms.
- **`core/metering.py`** — a `RequestMeter` bound via `contextvars` so concurrent requests
  don't mix. `begin_request()`, `record_llm/record_step`, `summary()` (total latency + tokens
  + per-step breakdown). When `METRICS_IN_RESPONSE`, the summary can ride along on the card.

### Full metric catalogue

Latency histogram buckets (ms): **25, 50, 100, 200, 500, 1000, 2000, 5000, 10000**.

**Request / system:**

| Metric | Type | Labels |
| --- | --- | --- |
| `nipun_queries_total` | Counter | domain, language, status, agent |
| `nipun_request_duration_ms` | Histogram | endpoint, status_code |
| `nipun_ws_connections` | Gauge | — |
| `nipun_active_sessions` | Gauge | — |
| `nipun_errors_total` | Counter | service, error_code |
| `nipun_queue_depth` | Gauge | queue_name |

**Cache / LLM / retrieval / memory / ingestion / agent:**

| Metric | Type | Labels |
| --- | --- | --- |
| `nipun_cache_hits_total` / `_misses_total` | Counter | service, cache_type |
| `nipun_llm_tokens_total` | Counter | model, provider, direction (input/output) |
| `nipun_llm_duration_ms` | Histogram | model, provider |
| `nipun_llm_errors_total` | Counter | model, provider, error_type |
| `nipun_retrieval_duration_ms` | Histogram | stage (embed/dense/sparse/rrf/rerank/total) |
| `nipun_retrieval_total` | Counter | domain, language, method |
| `nipun_memory_assembly_ms` | Histogram | (buckets 5,10,20,35,50,100,200) |
| `nipun_documents_indexed_total` | Counter | domain, language |
| `nipun_ingestion_duration_ms` | Histogram | domain, stage |
| `nipun_agent_calls_total` | Counter | agent, domain, status |
| `nipun_agent_duration_ms` | Histogram | agent, domain |

**Safety / RAG / planning / synthesis / tools / A2A / eval:**

| Metric | Type | Labels |
| --- | --- | --- |
| `nipun_safety_prescreen_total` | Counter | tag, method |
| `nipun_safety_gate_total` | Counter | outcome (answered/abstained/safe_redirect/disclaimer_attached) |
| `nipun_abstentions_total` | Counter | domain |
| `nipun_reliability_score` | Histogram | (buckets 0,0.2,0.3,0.4,0.5,0.6,0.7,0.75,0.85,1.0) |
| `nipun_reliability_band_total` | Counter | band (high/medium/low/very_low/not_applicable) |
| `nipun_rag_loops_per_query` | Histogram | (buckets 0–5) |
| `nipun_claims_unsupported_ratio` | Histogram | (0,0.1,0.25,0.5,0.75,1.0) |
| `nipun_verification_latency_ms` | Histogram | — |
| `nipun_documents_graded_total` | Counter | verdict (relevant/irrelevant) |
| `nipun_plan_route_total` | Counter | route, method |
| `nipun_plans_generated` | Histogram | (1,2,3) |
| `nipun_subquestions_per_query` | Histogram | (1–5) |
| `nipun_explanation_modality_total` / `_depth_total` | Counter | modality / depth |
| `nipun_explain_differently_clicks_total` | Counter | mode |
| `nipun_tool_calls_total` | Counter | tool, status (ok/unavailable/error/blocked) |
| `nipun_task_lifecycle_total` | Counter | phase (prepare/confirm/execute/reject), task |
| `nipun_circuit_breaker_trips_total` | Counter | kind (tool/agent) |
| `nipun_credential_blocks_total` | Counter | type |
| `nipun_a2a_card_verifications_total` | Counter | outcome |
| `nipun_eval_precision_at_k` / `_ndcg_at_10` / `_faithfulness` / `_abstention_correctness` / `_citation_validity` | Gauge | domain |

### Prometheus alert rules (`monitoring/prometheus/alerts.yml`)

| Alert | Condition | For | Severity |
| --- | --- | --- | --- |
| HighLatencyP99 | p99 > 3000ms | 5m | critical |
| HighErrorRate | error rate > 5% | 2m | critical |
| HighQueueDepth | queue depth > 1000 | 10m | warning |
| LLMErrors | LLM error rate > 0.1/5m | 3m | warning |
| SlowRetrieval | retrieval p95 > 500ms | 5m | warning |

### Log files & key events

Rotating files (10MB × 5 backups) under `backend/logs/` — base files + subsystem views:

| File | Level | Purpose |
| --- | --- | --- |
| `app.log` | INFO+ | all application events (catch-all) |
| `error.log` | ERROR+ | errors only |
| `access.log` | INFO | HTTP request traffic |
| `frontend.log` | DEBUG | browser logs via `POST /logs` |
| `chat.log` | — | **the complete per-request chat-pipeline trace** via `trace_flow()`, ending in one `chat_summary` line per request |
| `flow.log` | — | `flow_console` human-readable query-flow story |
| `llm.log` | INFO+ | subsystem view — `llm.*` (client, router, embeddings) |
| `retrieval.log` | INFO+ | subsystem view — `retrieval.*` + document grading |
| `agents.log` | INFO+ | subsystem view — `agent.*`, `agents.*`, `orchestrator` |
| `safety.log` | INFO+ | subsystem view — `safety.*`, `execution.*` (guards) |
| `db.log` | INFO+ | subsystem view — `db.*` (postgres/redis/qdrant/neo4j) |
| `ipa.log` / `ipa.debug.log` | — / INFO+ | IPA run narration / structured `ipa.*` records |
| `tasks.log` | INFO+ | subsystem view — task-automation |
| `ingestion.log` | INFO+ | subsystem view — ingestion pipeline |
| `terminal.log` | — | terminal heartbeat mirror |

Subsystem files are routed by logger-name prefix and **also** appear in `app.log`; a new
subsystem/agent/service lands in the right file automatically by naming its logger
`<subsystem>.<module>` — no logging-config change needed.

**`chat_summary`** (one line per request, in `chat.log`) is the at-a-glance monitor across all
users: `user_id, session_id, query, language, domain, route, card_type, reliability_band/score,
rag_loops, abstained, total_latency_ms, llm_calls, input/output/total_tokens`. Grep it (or ship
it to a dashboard) to watch throughput, latency, token spend, and answer quality system-wide.

**PII masking:** phone → `98XXXXXX10`; aadhaar/pan/email/password/token/otp → `***`; API
request/response bodies are recursively `redact()`-ed before logging.
**Representative events:** `query_received`, `intent_classified`, `context_assembled`,
`knowledge_retrieved`, `knowledge_graded`, `agent_generation_input`, `agent_card_generated`,
`llm_request`/`llm_response` (tagged with `step`), `llm_tier_fallback`, `reliability_scored`,
`corroboration_measured`, `credential_guard_blocked`, `chat_summary`, `cache_hit/miss`,
`ingestion_job_started/complete`, `episode_saved`.

---

## 29. Evaluation harness

`src/eval/` (`make eval` / `python -m src.eval.run`). Per-domain JSONL golden sets in
`src/eval/golden/` (`GoldenExample`: query, relevant_doc_ids, key_facts, expected_citation,
should_abstain, reference_answer). `metrics.py` has infra-free functions: `precision_at_k`,
`recall_at_k`, `ndcg_at_k`, `citation_present/wellformed`, `abstention_correct`,
`faithfulness_from_facts`. `run.py` runs **offline** metrics (citation format, abstention
sanity) always, and **live** metrics (retrieval precision/nDCG, LLM-judge faithfulness,
abstention correctness, citation validity) only when Qdrant + an LLM key are present — live
metrics are **skipped, not faked**. Results publish to `nipun_eval_*{domain}` gauges.
`calibration.py` reports ECE / Brier / per-band precision and can suggest reliability
thresholds. Golden domains: legal, finance, health, scheme, farming, student, career.

---

## 30. API reference

No global version prefix. All `/query`-style endpoints take **no language field** — the
response language is resolved from the query text and returned on `response_card.language`
(with `response_card.speech_text` for TTS).

| Method | Path | Auth | Rate | Purpose |
| --- | --- | --- | --- | --- |
| GET | `/health` | — | — | Per-dependency health (200/**207** degraded) |
| GET | `/livez` · `/readyz` | — | — | Liveness / readiness (`/readyz` **503** if a dep is degraded) |
| POST | `/auth/signup` · `/auth/login` | — | — | Returns Bearer JWT |
| POST | `/auth/reset-password` | — | — | Direct reset — **403 unless `APP_ENV=development`** |
| GET/PATCH | `/profile` | JWT | 60/min | Get / update profile |
| GET/POST | `/memory` | JWT | 60/min | List / add long-term memory |
| PATCH/DELETE | `/memory/{id}` · DELETE `/memory` | JWT | 60/min | Edit/pin, forget one, clear all |
| GET/POST | `/sessions` | JWT | 60/min | List / create sessions |
| GET | `/sessions/{id}` · `/sessions/{id}/messages` | JWT | 60/min | Metadata / transcript |
| PATCH/DELETE | `/sessions/{id}` | JWT | 60/min | Rename / delete (purges its doc chunks) |
| POST | `/query` | JWT | 20/min (LLM) | Query → `response_card` |
| WS | `/ws/{session_id}` | JWT (in first msg) | — | Streamed tokens |
| POST | `/feedback` · `/explain-differently` | JWT | 60/min | Rating / re-explain signal |
| POST/GET | `/documents` | JWT | 60/min | Upload / list private docs |
| GET/DELETE | `/documents/{id}` · POST `/documents/{id}/query` | JWT (owner) | 60/min | Metadata / delete / doc-scoped query |
| POST | `/admin/documents` | Admin | 60/min | Upload to shared public corpus |
| POST | `/admin/init` | — | — | One-time first admin (409 if exists) |
| GET/PATCH/DELETE | `/admin/users[/{id}][...]` | Admin | 60/min | User management |
| GET | `/tools` · `/agents` | JWT | 60/min | Tool catalogue / capability manifest |
| POST | `/tools/call` · `/tools/ingest-books` | JWT | 60/min | Call read-only tool / ingest books |
| GET/POST | `/tasks` · `/tasks/preview` | JWT | 60/min | Read-only task assistants |
| POST | `/tasks/prepare` · `/tasks/confirm` · `/tasks/reject` | JWT | 5/min (prepare) | Guarded action lifecycle |
| GET | `/files/{file_id}` | JWT (owner) | 60/min | Download a generated deliverable (pptx/docx); non-owner/expired → 404 |
| POST | `/task/start` | JWT | 60/min | Plan an IPA browser task → `task_id`+`plan` (idempotent per `(user,goal)` 120s) |
| WS | `/ws/task/{task_id}` | WS-token | — | Live IPA run: streams screenshots/steps; receives controls |
| POST | `/logs` | — | — | Frontend log ingestion |
| GET | `/.well-known/agent.json` | — | — | Signed A2A card (if `A2A_ENABLED`) |
| GET | `/metrics` | — | — | Prometheus (block at nginx in prod) |

**Chat WebSocket (`/ws/{session_id}`):** connect → send `{"token": jwt}` (bad → error + close
**1008**) → ownership check → send `{"query": ...}` → receive `thinking` → `token`* (fast-tier stream)
→ `card` (first structured draft) → **`card_patch`** (deferred citation/reliability merged in) →
`done` (or `error`). If `ABSTAIN_ON_LOW_CONFIDENCE`, no early streaming — a single final `card`.

**IPA task WebSocket (`/ws/task/{task_id}`):** accept → `{"token":...}` (fail → close **1008**) →
ownership check → replays current `plan` + `history` (reconnect-friendly) → two loops: `pump_events`
(server→client: `status`/`step`/`screenshot`/`action`/`app_action`/`options`/`needs_human`/`done`)
and `read_controls` (client→server: `answers` [first submit launches the run], `pause`/`resume`/`stop`,
`choose_option`, `human_done`, and remote `user_click`/`user_type`/`user_key`/`user_scroll` during
hand-off). Requires **sticky routing by `task_id`** (the browser lives in one worker).

### Request/response examples

**`GET /health`** → 200 (207 if any check degraded):
```json
{ "status": "ok", "service": "nipun-ai-gateway", "version": "0.1.0",
  "checks": { "postgres": {"status":"ok","latency_ms":3.2},
              "redis": {"status":"ok","latency_ms":0.8},
              "qdrant": {"status":"ok","latency_ms":12.1} } }
```

**`POST /auth/signup`** `{ "name":"Ravi Kumar", "email":"ravi@example.com", "password":"abc123" }`
→ 200 `{ "token":"<jwt>", "user":{ "id":"uuid","email":"...","name":"..." } }` (409 if email exists).
**`POST /auth/login`** `{email,password}` → same shape (401 on bad credentials).
**`POST /auth/reset-password`** `{email,new_password}` → `{ "message":"Password updated." }` (404 if unknown).
JWT payload: `{ sub, email, name, iat, exp }` (exp = now + `JWT_EXPIRY_HOURS`, default 24h).

**`POST /query`** (headers: `Authorization: Bearer <jwt>`, optional `X-Correlation-ID`):
```json
{ "query": "Section 302 mein bail kaise milti hai",
  "session_id": "uuid",                      // optional; new one created + returned if omitted
  "document_id": "uuid",                      // optional; answer grounded ONLY in this owned doc
  "clarifications": { "matter_type":"criminal", "state":"Maharashtra" } }  // optional, this-turn only
```
→ 200:
```json
{ "correlation_id":"abc-123", "session_id":"uuid",
  "response_card": { "cardType":"step_action", "language":"hi",
    "title":"Section 302 में Bail की प्रक्रिया", "summary":"…",
    "steps":[{"title":"...","desc":"...","status":"pending"}],
    "sources":[{"text":"Section 437 CrPC","url":""}],
    "disclaimer":"यह सामान्य कानूनी जानकारी है...",
    "confidence":0.75, "abstained":false,
    "speech_text":"Section 302 में Bail की प्रक्रिया …", "correlation_id":"abc-123" } }
```
→ 429 (LLM limit): `{ "detail": { "code":"LLM_RATE_LIMITED", "message", "message_en", "correlation_id" } }`.
There is **no `language` field** — see §9.

**`WS /ws/{session_id}`** event stream:
```json
{"type":"thinking","correlation_id":"..."}
{"type":"token","content":"bail "}
{"type":"card","data":{ ...response_card }}
{"type":"done","correlation_id":"..."}
{"type":"error","code":"...","message":"..."}
```

**`POST /admin/init`** — one-time; creates the first admin (409 if one exists). The startup
bootstrap creates a **default admin** if none exists: **`admin@gmail.com` / `admin2402`** —
change before any public deploy.

**`GET /metrics`** — Prometheus text format; block at nginx in production (internal only).

---

## 31. The `response_card` contract

Every card carries: `cardType`, `language` (authoritative, for TTS voice), `speech_text`
(clean plain text to read aloud), `title`, `summary?`, `sources[]?`, `disclaimer?`,
`correlation_id`, and verification fields `confidence?`, `abstained?`, `safety_tag?`,
plus adaptive-explanation fields `key_takeaway?`, `explain_differently?`,
`understanding_check?`, `depth?`, `teaching_format?`, `plan?`, `mission?`, `metrics?`.
(`plan`/`mission` are surfaced by `finalize` on non-trivial routes for transparency.)

Core `cardType`s and their payloads:

| cardType | Key fields |
| --- | --- |
| `answer` | `summary`, `key_takeaway?`, `sources[]` |
| `step_action` | `steps[]:{title,desc,duration?,status}` |
| `plan` | `plan_cols[]`, `plan_rows[]`, `plan{}` |
| `price_table` | `prices[]:{crop,price,change,rate}` |
| `weather` | `weather:{temp,condition,forecast[],alerts?}` |
| `scheme_list` | `schemes[]:{name,eligible,benefit,criteria,link?}` |
| `clarify` | `form:{fields[],submitLabel,allowSkip?,skipLabel?}`, `options[]` |
| `code_editor` | `code`, `codeLanguage` |
| `document` | `sources[]`, `url?`, `download{url,filename,format,mime}?`, `preview?` (deliverables) |
| `agent_task` | `goal`, `title` — the "Start" launcher that hands off to the IPA browser agent |
| `video` / `book` / `browser` / `whiteboard` | media cards (`video_url` / `book` / `url`) |
| `error` | `summary` (localised) |

The `CardType` enum in `api/schemas.py` has **23 values** (answer, step_action, plan, document,
price_table, weather, scheme_list, clarify, whiteboard, browser, mindmap, timeline, code_editor,
error, diagram, illustrative_diagram, comparison_table, map, interactive_widget, video, book — plus
`agent_task` emitted at runtime). The model uses `extra="allow"`, so the adaptive layer may also emit
`diagram`, `comparison_table`, `map`, `interactive_widget`, `mindmap`, `timeline`, inline `[[embed]]`
markers, etc. **Render known keys, ignore the rest** (unknown types fall back to the answer renderer).

---

## 32. Environment variables

Everything is in `backend/.env.example`. Must-set-for-any-run: `SECRET_KEY`, `JWT_SECRET_KEY`
(≥32 chars), `POSTGRES_PASSWORD`, and at least one LLM key. Optional live-data keys simply make
the matching tool available; missing keys make it report `unavailable` rather than error.

**App:** `APP_NAME` (`Nipun.AI`), `APP_ENV` (development/staging/production), `APP_PORT` (8000),
`DEBUG` (False — True bypasses auth to an anonymous admin), `SECRET_KEY` (required, ≥32).

**LLM tiers:**

| Variable | Default |
| --- | --- |
| `LLM_PRIMARY_PROVIDER` / `_MODEL` | `anthropic` / `claude-sonnet-4-6` |
| `LLM_PRIMARY_MAX_TOKENS` / `_TEMPERATURE` | `4096` / `0.3` |
| `LLM_FAST_PROVIDER` / `_MODEL` | `google` / `gemini/gemini-1.5-flash` |
| `LLM_FAST_MAX_TOKENS` / `_TEMPERATURE` | `1024` / `0.1` |
| `LLM_FALLBACK_PROVIDER` / `_MODEL` | `openai` / `gpt-4o-mini` |
| `LLM_FALLBACK_MAX_TOKENS` / `_TEMPERATURE` | `2048` / `0.3` |

**API keys (all default `""`):** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
`GROQ_API_KEY`, `MISTRAL_API_KEY`, `COHERE_API_KEY`.

**Embeddings / reranker:** `EMBEDDING_PROVIDER` (`local`), `EMBEDDING_MODEL` (`BAAI/bge-m3`),
`EMBEDDING_DIM` (1024), `EMBEDDING_BATCH_SIZE` (32), `EMBEDDING_USE_FP16` (True),
`EMBEDDING_MODEL_CACHE` (`./backend/models`); `RERANKER_MODEL` (`BAAI/bge-reranker-v2-m3`),
`RERANKER_TOP_K` (5), `RERANKER_CANDIDATES` (30).

**PostgreSQL:** `POSTGRES_HOST` (localhost), `_PORT` (5432), `_DB` (nipun_ai), `_USER` (nipun),
`_PASSWORD` (required, ≥8), `_POOL_SIZE` (20), `_MAX_OVERFLOW` (10). Computed:
`postgresql+asyncpg://…` (async) + `postgresql://…` (sync, for Alembic).

**Redis:** `REDIS_HOST` (localhost), `_PORT` (6379), `_PASSWORD` (""), `_DB` (0),
`_MAX_CONNECTIONS` (50).

**Cache TTLs (s):** `CACHE_SESSION_TTL` (604800/7d), `CACHE_PROFILE_TTL` (2592000/30d),
`CACHE_LLM_RESPONSE_TTL` (3600/1h), `CACHE_TRANSLATION_TTL` (604800), `CACHE_MANDI_PRICES_TTL`
(21600/6h), `CACHE_WEATHER_TTL` (14400/4h), `CACHE_LAW_SECTION_TTL` (2592000/30d).

**Qdrant:** `QDRANT_HOST` (localhost), `_PORT` (6333), `_API_KEY` (""),
`QDRANT_QUANTIZATION_ENABLED` (True), `_ALWAYS_RAM` (True), `QDRANT_RESCORE_OVERSAMPLING` (2.0).
**Elasticsearch:** `ELASTICSEARCH_HOST` (localhost), `_PORT` (9200), `_USERNAME` (""),
`_PASSWORD` (""). **Neo4j:** `GRAPH_ENABLED` (False), `NEO4J_URI/_USER/_PASSWORD`,
`GRAPH_ONLY_FOR_MULTIHOP` (True).

**Memory:** `WORKING_MEMORY_MAX_TURNS` (20), `EPISODIC_MEMORY_RECALL_LIMIT` (5),
`SEMANTIC_CACHE_SIMILARITY_THRESHOLD` (0.92); `MEMORY_ENABLED` (True), `MEMORY_RECALL_LIMIT`
(6), `MEMORY_MAX_PER_USER` (200), `MEMORY_DEDUP_SIMILARITY` (0.90), `MEMORY_MAX_NEW_PER_TURN`
(4), `PROFILE_MEMORY_ENABLED` (True).

**Retrieval:** `RETRIEVAL_DENSE_TOP_K` (100), `_SPARSE_TOP_K` (100), `_FINAL_TOP_K` (5),
`RETRIEVAL_RRF_K` (60), `RETRIEVAL_SLOW_QUERY_MS` (150), `CROSS_LINGUAL_RETRIEVAL` (True).

**Auth / rate limits:** `JWT_SECRET_KEY` (required, ≥32), `JWT_ALGORITHM` (HS256),
`JWT_EXPIRY_HOURS` (24), `JWT_REFRESH_EXPIRY_DAYS` (30); `RATE_LIMIT_PER_MINUTE` (60),
`RATE_LIMIT_LLM_PER_MINUTE` (20), `RATE_LIMIT_ACTION_PER_MINUTE` (5).

**Languages / Celery / external APIs:** `SUPPORTED_LANGUAGES` (`en,hi,pa,ta,te,mr,gu`),
`DEFAULT_LANGUAGE` (hi); `CELERY_BROKER_URL` (`redis://localhost:6379/1`),
`CELERY_RESULT_BACKEND` (`redis://localhost:6379/2`); `AI4BHARAT_API_KEY/_BASE`,
`DATA_GOV_IN_API_KEY`, `IMD_API_KEY`.

**Safety / verification:** `SAFETY_PRESCREEN_ENABLED` (True), `_USE_LLM`,
`CONFIDENCE_ABSTAIN_THRESHOLD` (0.5), `ABSTAIN_ON_LOW_CONFIDENCE` (False),
`RELIABILITY_HIGH/WARN/LOW_THRESHOLD`, `CORROBORATION_ENABLED` (True), `_MIN_SOURCES`,
`_AGREEMENT_THRESHOLD`, `VERIFY_CLAIMS_USE_LLM` (True), `VERIFY_MIN_EVIDENCE_CHARS`,
`VERIFY_NO_EVIDENCE_CONFIDENCE`, `VERIFY_PARTIAL_SUPPORT_FLOOR`; crisis helplines
`CRISIS_HELPLINE_MENTAL_HEALTH`, `_EMERGENCY`, `NALSA_LEGAL_AID_HELPLINE` (15100).

**RAG / clarify / reasoning:** `RAG_MAX_LOOPS` (3), `RAG_SUFFICIENCY_MIN_CHUNKS` (1),
`RAG_GRADE_USE_LLM` (True); `CLARIFY_ENABLED`, `CLARIFY_MAX_FIELDS` (4), `CLARIFY_USE_LLM`,
`CLARIFY_LLM_DOMAINS`; `REASONING_USE_PLAN` (True), `REASONING_REFLECT_ENABLED` (False),
`CRITIC_ENABLED` (False), `CRITIC_DOMAINS`; `CITATION_AGENT_ENABLED` (True), `CITATION_MAX_CLAIMS` (6).

**IPA / backpressure (new):** `IPA_ENABLED` (True), `IPA_CONSOLE_ENABLED` (True),
`IPA_HUMAN_WAIT_TIMEOUT` (600), `DEVICE_EXECUTION_ENABLED` (False), `DEVICE_SANDBOX_DIR`;
`LLM_TOOL_SELECTION` (True), `LIVE_AUGMENT_TIMEOUT`, `LIVE_AUGMENT_MIN_CHUNKS` (2);
`MAX_INFLIGHT_QUERIES` (64), `INFLIGHT_SLOT_TTL` (40), `REQUEST_HARD_TIMEOUT` (25);
`BOOTSTRAP_ADMIN_ENABLED` (True), `BOOTSTRAP_ADMIN_EMAIL/_PASSWORD/_NAME` (dev-only default admin);
`FLOW_CONSOLE_ENABLED` (True), `TERMINAL_ENABLED` (True), `CORS_ALLOW_ORIGINS` (prod origins).

**Execution / tools / books / uploads / A2A / RLM / eval / observability:** `EXECUTION_ENABLED`
(False), `TASK_PREVIEW_ENABLED`, `CIRCUIT_BREAKER_TOOL_CALLS_PER_MIN`, `_AGENT_CALLS_PER_MIN`,
`EXECUTION_CONFIRM_TTL`; `WEB_TOOLS_ENABLED` (True), `LIVE_AUGMENT_ENABLED`, `LIVE_HTTP_TIMEOUT`
(15), `LIVE_MAX_RESULTS` (5), and live keys (`TAVILY_API_KEY`, `BRAVE_API_KEY`, `SERPAPI_API_KEY`,
`ALPHA_VANTAGE_API_KEY`, `NEWSAPI_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `GOOGLE_BOOKS_API_KEY`,
`PUBMED_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID/_SECRET`, `GOOGLE_APPS_ENABLED`); `BOOKS_*`;
`UPLOAD_MAX_MB` (20), `USER_DOC_QUOTA` (50); `A2A_ENABLED` (False), `A2A_SIGNING_SECRET`,
`A2A_TRUSTED_AGENTS`, `A2A_TOKEN_TTL` (300); `RLM_MAX_DEPTH` (3), `RLM_MAX_SUBCALLS` (12),
`RLM_CHUNK_CHARS` (4000); `EVAL_GOLDEN_DIR`, `EVAL_RETRIEVAL_TOP_K`, `EVAL_USE_LLM_FAITHFULNESS`;
`LOG_LEVEL` (INFO), `PROMETHEUS_PORT` (9090), `LOG_FLOW_ENABLED`, `LOG_FLOW_CONTENT`,
`LOG_CONTENT_MAX_CHARS`, `METERING_ENABLED`, `METRICS_IN_RESPONSE`.

---

## 33. Development workflow

```bash
# 1. Configure
cp backend/.env.example backend/.env    # fill SECRET_KEY, JWT_SECRET_KEY, POSTGRES_PASSWORD, an LLM key

# 2. Install deps (Python 3.12+)
cd backend && uv sync

# 3. Start infra
make infra            # Postgres, Redis, Qdrant, Elasticsearch (+ Neo4j / monitoring via infra-full)

# 4. Migrate
make migrate          # runs db/migrations/*.sql in order

# 5. Download models (~3GB, once)
make download-models  # BAAI/bge-m3 + BAAI/bge-reranker-v2-m3 → backend/models/

# 6. Seed a corpus (optional but recommended)
make ingest           # all domains' offline seed packs (add DOMAIN=legal / --online for URLs)

# 7. Run
make backend          # FastAPI :8000 (hot reload)
make worker           # Celery worker
make beat             # Celery beat
```

### All Makefile targets

| Target | Purpose |
| --- | --- |
| `make setup` | First-time: copy .env, uv sync, npm install |
| `make download-models` | BGE-M3 + reranker → backend/models/ |
| `make infra` / `infra-full` / `infra-down` | Start core infra / + Prometheus+Grafana / stop all |
| `make logs` / `ps` | Tail compose logs / list containers |
| `make backend` | FastAPI dev server (:8000, hot reload) |
| `make frontend` | Vite dev server (React, :3000 → proxies `/api-backend` to :8000) |
| `make worker` / `beat` | Celery worker / beat scheduler |
| `make migrate` | Run DB migrations |
| `make seed` / `ingest [DOMAIN=…] [--online]` | Seed sample data / ingest corpus |
| `make build-graph` | Build Neo4j legal + scheme graphs |
| `make eval` / `eval-offline` | Golden-set evaluation |
| `make test` / `test-backend` | pytest (+ frontend) / backend only (`asyncio_mode=auto`) |
| `make lint` / `fmt` / `check` | ruff+mypy+eslint / format / lint+test |
| `make clean` | Remove `__pycache__`, `*.pyc`, build artifacts |

On Windows there is also a `dev.ps1` helper.

### Adding a new language

1. Add to `LANGUAGES` in `language/constants.py`; add its Unicode range to the script map.
2. Add the lingua `Language.*` entry in `detector.py`; update `SCRIPT_TO_LANG`.
3. Collections are cross-lingual, so no new Qdrant collections are needed.

---

## 34. Production deployment

**Docker Compose (current model):**
```bash
git clone <repo> /opt/nipun-ai && cd /opt/nipun-ai
cp backend/.env.example backend/.env      # fill production values
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
curl http://localhost:8000/health
```

`docker-compose.prod.yml` adds: a one-shot `migrate` job (backend gates on its success),
`backend` (FastAPI, `replicas ${BACKEND_REPLICAS:-1}`, `UVICORN_WORKERS` default 2, non-root),
`celery-worker` (concurrency 4), `celery-beat`, `frontend` (Vite build, :3000), `nginx` (80/443),
all `restart: always`; Prometheus + Grafana always on (`profiles: []`). Scaling >1 backend replica
requires removing `container_name` so nginx load-balances via the `backend` DNS alias. Prod turns on
secrets (redis `--requirepass`, qdrant API key, neo4j password, ES security + `ELASTIC_PASSWORD`).

**Nginx key config:** rate-limit zones `general` (100/min) and `llm` (20/min); WebSocket
upgrade with 3600s timeout; gzip for json/text; routes `/` → backend, `/ws/` → backend (WS),
static → frontend; `/metrics` → deny (403). Security headers: `X-Frame-Options DENY`,
`X-Content-Type-Options nosniff`, `Referrer-Policy no-referrer`, `X-XSS-Protection`.

**Production checklist:**
- [ ] `DEBUG=false`, `APP_ENV=production`
- [ ] Strong `SECRET_KEY`, `JWT_SECRET_KEY` (64+ random chars)
- [ ] `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `QDRANT_API_KEY`, `ELASTICSEARCH_PASSWORD` set
- [ ] CORS restricted to the production domain (default is currently permissive)
- [ ] `EMBEDDING_USE_FP16=false` if the server has no GPU
- [ ] `make download-models` before first start
- [ ] **Change the default admin `admin@gmail.com` / `admin2402`**
- [ ] `/metrics` blocked at nginx; SSL configured

**Scaling strategy:**

| Component | How to scale |
| --- | --- |
| FastAPI backend | Add replicas + nginx upstream load-balance |
| Celery workers | Add `celery-worker` containers / raise `--concurrency` |
| Postgres | Read replica for `recall_episodes()` + analytics |
| Redis | Sentinel (HA) or Cluster for >100k sessions |
| Qdrant | `replication_factor=2` at collection creation |
| Embedding | GPU host for BGE-M3 (~10× faster than CPU) |

---

## 35. Performance targets

| Metric | Target | Approach |
| --- | --- | --- |
| First token latency | <1.5s | fast model for classify; parallel context + retrieval |
| Complete response | <4s | Sonnet streaming; BGE-M3 on GPU |
| Cache hit (L1) | <50ms | Redis semantic cache (cosine ≥0.92) |
| Retrieval (total) | <150ms | parallel Qdrant + ES, BGE reranker |
| Memory assembly | <35ms | parallel L2+L4 fetch, L0 synchronous |
| Language detection | <5ms | script analysis (<500-char sample) |
| Embedding (32 chunks) | 50ms GPU / 400ms CPU | BGE-M3 FP16 |
| Health check | <100ms | parallel DB pings |

---

## 36. Extending the platform

- **New domain agent:** create `agents/domains/<x>.py` subclassing `BaseAgent` (implement
  `build_system_prompt` + `build_response_card`), add it to `SUPPORTED_DOMAINS`
  (`language/constants.py`) and to `REGISTRY` (`agents/registry.py`). Its Qdrant collection is
  auto-created on next startup. Add an ingestion source under `ingestion/sources/`.
- **New MCP tool:** subclass `MCPTool` (`mcp/base.py`), implement `_call`, register in
  `mcp/tools.py`, and (if it's live data) wire selection into `mcp/live/aggregator.py`.
- **New router:** add `api/routers/<x>.py` and `app.include_router(...)` in `main.py`.
- **New action:** register a handler in `execution/executor.py`'s `ACTION_HANDLERS` and set
  `EXECUTION_ENABLED=true` — it will only run through PREPARE→CONFIRM with a full audit trail.
- **New language:** add to `LANGUAGES`/script maps in `language/constants.py` and the lingua
  detector; collections are cross-lingual so no new collections are needed.

---

## 37. Security model

- **Auth:** JWT HS256 (24h access / 30d refresh). `DEBUG=true` allows an anonymous-admin
  fallback — **dev only, never production**. Admin actions re-check the DB role.
- **Rate limits (Redis sliding window):** 60/min general, 20/min LLM, 5/min actions.
- **RBAC:** `require_roles` + `assert_owner` (404 to avoid existence leaks); Qdrant `owner_id`
  filter as a second guard on private documents.
- **Input:** query ≤2000 chars; Pydantic v2 validation; asyncpg parameterized queries (no SQL
  injection); bcrypt password hashing.
- **Untrusted content & credentials:** all tool/web/PDF output is wrapped and scanned for
  injected instructions; Aadhaar/PAN/card/OTP/CVV/PIN/password are blocked in any tool/action
  payload; execution is confirm-gated and audited.
- **PII in logs:** `mask_pii` redacts phone/aadhaar/pan/email/password/token/otp everywhere.
- **Data retention:** `conversation_logs` auto-deleted after 90 days; account deactivation is a
  soft delete (`is_active=false`).
- **Prod checklist:** `DEBUG=false`; strong secrets; DB/Redis/Qdrant/ES auth on; tighten CORS;
  block `/metrics` at nginx; **change the default admin `admin@gmail.com` / `admin2402`**;
  container runs as non-root.

---

## 38. Frontend reference (Vite + React)

The web client lives in `frontend/` (package `nipun-frontend`): **React 18 + Vite 6 +
react-router 6 + TanStack Query + Tailwind + shadcn/ui**. JSX (not TS) but type-checked via
`jsconfig.json` (`checkJs`). Path alias `@/` → `src/`. Dev proxy (`vite.config.ts`):
`/api-backend/*` → `VITE_API_BASE_URL` (default `http://localhost:8000`, `ws:true`). Scripts:
`dev`, `build`, `lint`, `typecheck`, `preview`.

> The `README.md`/`AGENTS.md`/`CLAUDE.md` in `frontend/` are **stale Base44 boilerplate** — ignore
> them. `src/lib/api.js` + `vite.config.ts` are the source of truth.

### App shell, routing & guards (`App.jsx`)

Provider tree: `QueryClientProvider` → `AppProvider` → `Router` → (`ThemeStyles`, `ScrollToTop`,
`ErrorBoundary`[`AuthenticatedApp` + **`TaskRunnerHost`** mounted app-wide]) + `Toaster`.

| Path | Component | Guard |
| --- | --- | --- |
| `/` | `Landing` | public |
| `/login` · `/signup` | `NipunLogin` · `NipunSignup` | `PublicOnlyRoute` (→ `/home` if authed+onboarded) |
| `/reset-password` | `NipunResetPassword` | public |
| `/onboarding` | `Onboarding` | protected |
| `/home` | `Home` | protected |
| `/workspace` · `/workspace/:sessionId` | `Workspace` | protected |
| `/settings` | `NipunSettings` | protected |
| `/admin` · `/admin/users` · `/admin/monitoring` | Admin* | protected + `adminOnly` |
| `*` | → `/` | — |

`NipunProtectedRoute` redirects to `/login` if unauthenticated, waits for `profileHydrated`, sends
un-onboarded users to `/onboarding`, and (with `adminOnly`) sends non-admins to `/home`.

### Global state (`lib/AppContext.jsx`, `useApp()`)

Holds `token, user, profile, activeSessionId, profileHydrated` + derived `isAuthenticated`,
`hasOnboarded`. **localStorage keys:** `nipun_token`, `nipun_user`, `nipun_profile`,
`nipun_onboarded_<userId>`. On mount it seeds from localStorage; when a token exists it fetches
`GET /profile` (keeps only preference keys) and sets `profileHydrated` (prevents premature onboarding
redirects on fresh devices). `hasOnboarded` = user AND (local flag OR server `profile.onboarded` OR
profile "looks filled"), self-healing by writing `onboarded:true` back once. A theming effect applies
`applyPreset`/`applyPalette`/`applyMotif`/`applyTextScale` on any profile change. **There is no
language state** — the backend returns `response_card.language` per turn; use it for direction/voice,
never send it.

### API client (`lib/api.js`)

`BASE_URL = VITE_API_BASE_URL || http://localhost:8000`. Token from `localStorage.nipun_token`, sent
as `Authorization: Bearer`. `request()` wraps a 60s `AbortController` timeout, JSON/FormData bodies,
returns `null` on 204, and on **401 `MISSING_TOKEN`/`INVALID_TOKEN` calls `clearAuth()`** (wipes
storage → `/login`); errors carry `.status/.code/.correlationId`. Profile keys are translated
camelCase↔snake_case (`uiPreset↔ui_preset`, `textScale↔text_scale`, `ageBand↔age_band`,
`languagesKnown↔languages_known`, …). Grouped methods map 1:1 to the backend (§30):
`auth.{signup,login,resetPassword}` · `profile.{get,update}` ·
`sessions.{list,create,get,getMessages,update,delete}` · `query.send` · `feedback.send` ·
`explain.differently` · `documents.{upload,list,get,delete,query}` · `tools.{list,call,ingestBooks}` ·
`tasks.{list,preview,prepare,confirm,reject}` · `admin.{init,getUsers,getUser,updateUser,deleteUser,
getUserSessions,resetUserPassword,uploadDocument}` · `files.download` · `health.check` · `logs.send`.
**WebSockets:** `createWebSocket(sessionId)` → `/ws/{sessionId}` (chat), and `taskAgent.start(goal)`
(POST `/task/start`) + `createTaskWebSocket(taskId)` → `/ws/task/{taskId}` (IPA).

### Pages (`src/pages/`)

- **Landing** — public marketing (auto-rotating mock-chat carousel, features, DPDPA trust). No API.
- **Home** — authed "ask anything" hub: central box → `query.send` → navigates `/workspace/:id`;
  recent conversations via `sessions.list(6,0)` with inline rename/delete; example chips + greeting.
- **Workspace** *(main app — see below)*.
- **Onboarding** — 7-step wizard (You → Location → Age → About → Interests → Languages → Look); only
  name required, every step skippable; persists via `updateProfileRemote`, sets `onboarded` → `/home`.
- **NipunLogin / NipunSignup / NipunResetPassword** — in `AuthShell`; OTP disabled (signup logs in
  directly → `/onboarding`); reset is email + new password (no token flow).
- **NipunSettings** — 4 tabs: Profile (batch save), Appearance (preset/palette/motif/accessibility,
  each saves immediately), Documents (pointer to workspace), Account (email, reset, logout).
- **AdminDashboard / AdminMonitoring / AdminUsers** — `admin.getUsers` + `health.check`; KPI cards,
  health blocks, user table (edit/deactivate/reset-password). Several metric panels are placeholders
  (the `/metrics` endpoint is not wired into the UI).

### Workspace (`pages/Workspace.jsx`) — the main app

Three columns: `WorkspaceSidebar` | chat | `RightRail`. **Message flow (`handleSend`):** push user
bubble → **WebSocket-first** (`/ws/:sessionId`: `thinking`/`token`→`streamText`/`card`→append/
**`card_patch`**→merge deferred sources+reliability in place/`done`/`error`) → **REST fallback**
(`query.send`; a returned new `session_id` navigates to `/workspace/:id`). **Clarify** re-sends the
original query + `clarifications:{field:value}` over **REST only** (the stream doesn't accept
clarifications). Also: history load on `sessionId` change (`sessions.get`+`getMessages`, re-parsing
stored JSON cards), auto-scroll, title rename, `Cmd/Ctrl+N` new chat, `documentScope` to narrow a
query to one uploaded doc. Streaming text renders live through `ReactMarkdown` matching `AnswerCard`.

- **Composer** — auto-grow textarea (Enter send / Shift+Enter newline), attach + mic (gated on
  `voiceEnabled`), model chip (Auto/Speed/Deep from `ai_model`), document-scope pill.
- **RightRail** — 3 tabs: Documents (`documents.list`/`upload`/delete), Tools (`tools.list`),
  Tasks (`tasks.list`).
- **WorkspaceSidebar** — conversation list (`sessions.list(50,0)`), new/search/rename/delete,
  collapsible to a 48px icon rail.
- **ResourcesSection** ("Learn & explore" — videos/pictures/articles from `card.resources`),
  **ThinkingIndicator** (multi-stage narration), **InlineContent** (splits `summary` on `[[embed:id]]`
  and renders each embed inline via `EMBED_MAP`).

### Response-card rendering

**Pipeline:** backend `response_card` (or WS `card`/`card_patch`) → **`parseResponseCard()`**
(`lib/parseCard.js`, normalizes snake/camel into one flat view model) → **`ResponseCardRenderer`**.
`cardRegistry.js` is a **dead stub** — the live registry is `CARD_MAP` + `resolveCard()` inside
`ResponseCardRenderer.jsx`. `resolveCard` normalizes the type and falls back to **`AnswerCard`** for
unknown types (→ `TextFallback` if there's no summary — never a blank box). Renderer chrome wraps
every card: type label + icon, language chip, `CardErrorBoundary` (degrades a throwing card to
`TextFallback`), `ResourcesSection`, sources row, disclaimer, a hover footer (read-aloud if
`voiceEnabled`, thumbs → `feedback.send`, copy), a **reliability circle** (score %, band,
click-to-explain popover — "deliver-with-score", the answer is always shown), and "Rephrase" chips →
`explain.differently` + re-query.

### Clarify forms

`cardType==="clarify"`: render `form.fields[]`
(`{name,label,type:text|number|select|multiselect,options?,required,placeholder?}`) with
`form.submitLabel` and, if present, a Skip. Submit → re-send the **original** query +
`clarifications:{field:value}` (REST). Skip → re-send with `clarifications:{}` (empty = "asked &
skipped" → the backend answers generally and won't re-ask).

### `cardType` → component map (real `CARD_MAP`)

Every card also has `language`, usually `speech_text`, `title`, `summary`, `sources[]`,
`disclaimer?`, `confidence?`, `reliability?`, `correlation_id`.

| cardType | Component | File |
| --- | --- | --- |
| `answer` | AnswerCard (delegates to `InlineContent` if `embeds`) | `cards/AnswerCard.jsx` |
| `agent_task` | AgentTaskCard ("Start" → `startTask(goal)`) | `cards/AgentTaskCard.jsx` |
| `step_action` | StepActionCard (filled/missing fields, portal, Confirm/Cancel → `tasks.confirm/reject`) | `cards/StepActionCard.jsx` |
| `plan` | PlanCard (table or numbered steps) | `cards/PlanCard.jsx` |
| `price_table` | PriceTableCard (up/down/flat trends) | `cards/PriceTableCard.jsx` |
| `weather` | WeatherCard | `cards/WeatherCard.jsx` |
| `scheme_list` | SchemeListCard (eligible badges) | `cards/SchemaListCard.jsx` |
| `clarify` | ClarifyCard (form) | `cards/ClarifyCard.jsx` |
| `code_editor` | CodeEditorCard (read-only + copy) | `cards/CodeEditorCard.jsx` |
| `document` | DocumentCard (deliverable download via `files.download` + `DeliverablePreview`) | `cards/GenericCards.jsx` |
| `mindmap` · `timeline` · `comparison_table` · `diagram`/`illustrative_diagram` · `map` · `interactive_widget` | Mindmap/Timeline/ComparisonTable/Diagram/Map(react-leaflet)/InteractiveWidget (EMI/SIP calc) | `cards/GenericCards.jsx` |
| `video` · `browser` · `whiteboard` · `book` | Video/Browser/Whiteboard/Book | `cards/MediaCards.jsx` |
| `error` | ErrorCard | `cards/ErrorCard.jsx` |
| *(unknown)* | AnswerCard → `TextFallback` | — |

Charts/mindmaps/diagrams are **hand-rolled SVG** — recharts is a dependency but not used by cards.
`cards/RichBlocks.jsx` supplies inline blocks (`KeyPointsCard`, `CalloutCard`, `StatsCard`,
`SwatchesCard`) used by `InlineContent`'s `EMBED_MAP`. Cross-cutting affordances are applied by the
renderer chrome (reliability circle, disclaimer footnote, sources, rephrase chips, read-aloud).

### Task Runner UI (`src/components/task/`) — drives the IPA agent

- **`TaskRunnerHost`** (mounted once at root) listens for the `window` event `nipun:start-task`;
  the exported `startTask(goal)` dispatches it (called by `AgentTaskCard`). Renders `<TaskRunner>`.
- **`TaskRunner`** — modal in three phases: **planning** (`taskAgent.start(goal)` → `/task/start`),
  **form** (consolidated `form_fields` + `ChecklistPanel`, else auto-start), **running** (opens
  `/ws/task/:taskId`, sends `{token}` + `{action:"answers"}`, handles `status`/`step`/`screenshot`/
  `action`/`app_action`/`options`/`needs_human`/`done`/`error`).
- **`BrowserView`** — live screenshot (1280×800) + address bar; when interactive (needs_human/paused)
  forwards `user_click`/`user_type`/`user_key`/`user_scroll` to the same server browser (login/OTP/
  checkout done by the human).
- **`ChecklistPanel`** (progress spine, colour-coded, `sensitive` steps flagged "you"),
  **`OptionsPanel`** (compared options with "Best pick" → `choose_option`), **`TaskControls`**
  ("I've done it — continue" `human_done`, Pause/Resume, Stop).

### Theming (4-axis CSS variables) & i18n

Driven by the profile in `AppContext`, applied to `document.documentElement`:
**palettes** (`theme/palettes.js`, 13 — light: taj/sky/mint/sugam/shaant/hc-light; dark: saffron
[brand default]/indigo/emerald/obsidian/yuva/hc-dark), **presets** (`theme/presets.js`, 5 —
sugam/sampann[default]/nova/yuva/shaant; density+type+motion, text scale S/M/L/XL = 14/16/18/20px),
**motifs** (`theme/motifs.js`, 8 cultural SVG background patterns), **regions** (`theme/regions.js`,
36 states/UTs → default palette/motif suggestions). `ThemeStyles.jsx` injects the global `<style>`;
`index.css` maps Tailwind tokens to shadcn HSL vars (`darkMode:["class"]`). **i18n** (`lib/i18n.js`)
is a lightweight custom dictionary — `t(key, lang)` + `getGreeting(lang)` for the same 7 languages;
answer content-language is driven by the backend, not this file.

### Voice flow (ASR in, TTS out — same language both ways)

```
[mic] user speaks (Hindi) → client ASR → transcript
  → POST /query { query: transcript }        (no language field)
  → response_card.language="hi", response_card.speech_text="…Hindi…"
  → TTS: speak(speech_text) with a Hindi voice; also render the card text
```

To switch language the user just says it ("answer in Tamil") — no API flag. Use
`response_card.language` for the TTS voice and read `speech_text` (plain text, no markdown/JSON).

### Standard error envelope

Protected endpoints on error return
`{ "error": { "code":"INVALID_TOKEN|FORBIDDEN|NOT_FOUND|RATE_LIMITED|…", "message", "correlation_id" } }`.
Rate limit (429) uses `{ "detail": { "code":"LLM_RATE_LIMITED", "message", "message_en",
"correlation_id" } }`. Show `message` (already localised where applicable); keep
`correlation_id` for support.

---

## 39. Architecture & data-flow deep dive (formats at every stage)

This section is the single place that shows **what the data looks like at each hop** — the
exact dicts/JSON the code passes around — plus every API flow and the response-generation
flow. Read it alongside §5 (lifecycle) and §14 (orchestrator).

### 39.1 Layered architecture (who calls whom)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. EDGE            nginx (prod) → rate-limit zones, WS upgrade, TLS         │
├──────────────────────────────────────────────────────────────────────────┤
│ 2. GATEWAY         FastAPI (main.py): correlation-id + access-log mw,       │
│                    CORS, Prometheus, routers (api/routers/*)                │
│                    per-route deps: get_current_user · rate_limit · rbac     │
├──────────────────────────────────────────────────────────────────────────┤
│ 3. ORCHESTRATION   process_query() → LangGraph (agents/orchestrator.py)     │
│                    nodes call the services below                            │
├───────────┬───────────┬───────────┬───────────┬───────────┬───────────────┤
│ 4a LLM    │ 4b MEMORY │ 4c RETRIE │ 4d SAFETY │ 4e SYNTH  │ 4f TOOLS/EXEC │
│ llm/*     │ memory/*  │ retrieval/│ safety/*  │ synthesis/│ mcp/* exec/*  │
│ (LiteLLM) │           │ * graph/* │           │ *         │ research/ a2a │
├───────────┴───────────┴───────────┴───────────┴───────────┴───────────────┤
│ 5. DATA            Postgres(+pgvector) · Redis · Qdrant · Elasticsearch ·   │
│                    Neo4j(opt) · local model files (BGE-M3, reranker)        │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Layer 2** never talks to Layer 5 directly (except health checks) — everything funnels
  through Layer 3 so auth/metering/tracing wrap all work.
- **Layer 3** is the only place that decides routing/looping; Layer 4 services are stateless
  and reusable (retrieval is called by the RAG path *and* multi-hop, etc.).
- **Layer 4/5 clients are singletons** created at startup (`main.py` lifespan) — asyncpg pool,
  Redis client, Qdrant client, embedder, reranker, language detector.

### 39.2 The universal call contract

Every layer-3/4 call carries a **`correlation_id`** (generated at the gateway) and every step
emits `trace_flow(step, correlation_id, **payload)` into `chat.log` and updates the
`RequestMeter`. So one query produces a linear, replayable trace:

```
http_query_received → understand → embed → context_assembled → clarify_check →
plan_route → retrieval_results → documents_graded → [live_tools] → [rewrite] →
llm_request/llm_response (generate) → claims_cited → claims_verified → finalize →
http_query_response
```

### 39.3 REST `/query` — full flow with formats

**(1) Wire in — `QueryRequest`:**
```json
{ "query": "5 ekad kali mitti me kaunsi fasal lagayein?",
  "session_id": "550e8400-…",            // optional
  "document_id": null,                    // optional (doc-scoped answer)
  "clarifications": null }                // optional {field: value}, this-turn only
```
Validation: `query` 1–2000 chars. Headers: `Authorization: Bearer <jwt>`,
optional `X-Correlation-ID`.

**(2) Gateway (`routers/query.py`):** `correlation_id = header or uuid4()`;
`session_id = body or uuid4()`; `user_id = user["user_id"]`; LLM rate check
`incr_with_expiry("rate:llm:{user_id}", 60)` → 429 if over 20. Then `await process_query(...)`.

**(3) `process_query` prep:** resolves the language, starts the `RequestMeter`, and — if
`clarifications` were sent — calls `remember_facts(session_id, clarifications)` (kept in-process
for the session, not persisted) **and seeds the retrieval query** with the clarification values:
`retrieval_query = "<query> <clarification values>"` (so retrieval benefits from them without
polluting the displayed query). Then it builds the initial `OrchestratorState` (dict) — the
object that flows through and is mutated by every node:
```python
{ "query": "...", "session_id": "...", "user_id": "...", "correlation_id": "...",
  "document_id": None, "doc_scope": False, "filters": None,           # filters = corpus routing
  "language": "hi",            # resolve_response_language() — authoritative, set up front
  "safety_tag": "normal", "safety_confidence": 1.0,
  "domain": "general", "intent": "query", "complexity": "simple", "entities": [],
  "clarifications": None, "needs_clarification": False,   # None = "not asked"; {} = "asked & skipped"
  "context": {}, "query_embedding": [],
  "route": "agentic_rag", "plan": None, "mission": None,  # route default overwritten by plan_route
  "retrieval_query": "<query [+ clarification terms]>", "knowledge_pool": [], "knowledge": [],
  "rag_loops": 0, "live_augmented": False, "sufficient": False, "query_variants": [],
  "confidence": 0.0, "unsupported_claims": [], "supported_claims": [], "abstained": False,
  "response_card": None, "streaming_done": False, "error": None }
```
The graph is invoked as `orchestrator.ainvoke(initial_state, {"recursion_limit": 50})`.

**(4) Nodes mutate the state.** Representative writes (see §14 for all):
- `understand` → `domain, intent, complexity, entities, safety_tag, safety_confidence`.
- `embed_query` → `query_embedding: [0.0123, -0.09, …]` (1024 floats).
- `assemble_context` → `context` (see 39.6 for its shape).
- `plan_route` → `route ∈ {simple_answer,agentic_rag,multi_hop,research,task_execution}`,
  `plan`, `mission`.
- `retrieve` → appends to `knowledge_pool` (chunk dicts, 39.7).
- `grade_documents` → `knowledge` (kept chunks) + `sufficient`.
- `generate` → `response_card` (raw card dict from the domain agent).
- `verify_claims` → `confidence, supported_claims, unsupported_claims`.
- `finalize` → final `response_card` (adds reliability, disclaimer, speech_text), `abstained`.

**(5) Wire out — `QueryResponse`:**
```json
{ "correlation_id": "…", "session_id": "…", "response_card": { … see §31 / 39.8 … } }
```
Field order in code is `correlation_id, response_card, session_id`.

### 39.4 WebSocket `/ws/{session_id}` — streaming flow

```
client ── connect ──►  server: accept(), WS_CONNECTIONS.inc()
client ── {"token": jwt} ──►  validate_token(); on fail → {"type":"error","code":"UNAUTHORIZED"} + close(1008)
loop:
  client ── {"query": "..."} ──►
     resolved_language = resolve_response_language(query)
     ◄── {"type":"thinking","correlation_id":cid}
     route_stream(system=You are Nipun AI…+language_directive, user=query, complexity="simple")
        ◄── {"type":"token","content":"..."}   (many)
     response_card = process_query(query, session_id, user_id, cid, on_early_card=…)  # full pass
     ◄── {"type":"card","data": first_draft_card}        # emitted right after `generate`
     ◄── {"type":"card_patch","data": {sources, reliability, …}}  # deferred cite+verify+finalize
     ◄── {"type":"done","correlation_id":cid}
on disconnect/exception → {"type":"error","message":...}; finally WS_CONNECTIONS.dec()
```

Note the two-phase design: tokens are streamed by the **fast tier** for instant UX; the first
structured **card** is delivered via `on_early_card` as soon as `generate` finishes, and the
answer-first citation + verification + finalize results arrive as a later **`card_patch`** that the
client merges in place. All phases use the same resolved language. (If `ABSTAIN_ON_LOW_CONFIDENCE`
is on, early streaming is skipped and only one final `card` is sent.)

### 39.5 Other API flows (sequence, in brief)

- **Auth** (`/auth/signup|login|reset-password`): body → bcrypt verify/hash → `_create_token`
  (`{sub,email,name,iat,exp}`, HS256) → `{token, user:{id,email,name}}`. No orchestrator.
- **Sessions** (`/sessions*`): CRUD on the `sessions` + `conversation_logs` tables, all scoped
  `WHERE user_id=$1`. DELETE also calls `delete_session_documents(user_id, session_id)` to purge
  that session's Qdrant chunks.
- **Documents upload** (`POST /documents`): multipart → size/quota/MIME checks → insert row
  `status='processing'` → `ingest_user_document(...)` (parse→chunk→embed→Qdrant upsert with
  `owner_id/document_id/session_id` payload) → update `status='ready', chunk_count, domain,
  subject, level`. **Doc-scoped query** (`/documents/{id}/query` or `/query {document_id}`) sets
  `doc_scope=True` so `retrieve` calls `retrieve_user_document()` (owner-filtered, no web).
- **Tasks** (`/tasks/*`): `preview` runs a read-only assistant → `{card}`; `prepare` →
  `{token, preview, expires_at}` (circuit-breaker guarded, 429 on trip); `confirm` executes
  only if `EXECUTION_ENABLED` + handler exists → `{status, message, result}`; `reject` discards.
  Every phase writes a redacted `task_audit` row.
- **Tools** (`/tools`, `/tools/call`): list/invoke read-only `MCPTool`s → `{tool, status, text,
  data, suspected_instructions}`.
- **Memory** (`/memory*`): CRUD on `user_memories` (owner-scoped), embeddings for dedup/recall.
- **Feedback** (`/feedback`): insert rating → best-effort `learn_preferences(user_id)`.
- **Admin** (`/admin/*`): `require_roles("admin")`; user management + shared-corpus upload.

### 39.6 `AssembledContext` (the memory bundle) — format

`assemble_context()` returns this (also stored on `state["context"]`):
```python
{ "working_memory": [ {"role":"user","content":"..."},
                       {"role":"assistant","content":"..."} ],   # L0, last ≤20 turns
  "user_profile":  { "name":"Ravi", "state":"Maharashtra", "occupation":"farmer",
                     "land_size_acres":5, "soil_type":"black",
                     "current_crops":["cotton"], "active_schemes":["PM-KISAN"] },  # L2
  "session":       { "id":"...", "language":"hi", "domain":"farming", "turn_count":3 }, # L2
  "episodic_context": [ {"summary":"asked about cotton MSP last week",
                          "domain":"farming","similarity":0.81} ],                  # L4
  "user_memories": [ {"content":"Preparing for Rabi sowing","kind":"goal","pinned":false} ],
  "token_estimate": 640, "assembly_ms": 22.4 }
```

### 39.7 Knowledge chunk — format (the retrieval currency)

`retrieve` accumulates these dicts into `knowledge_pool`; `grade_documents` keeps the good ones
into `knowledge`; `generate` renders them as `[Source: …]` blocks and as `sources[]` on the card:
```python
{ "chunk_id": "farming::soil_crops::7",
  "text": "Black cotton soil suits cotton, soybean, sorghum … ",
  "source": "ICAR crop guide",
  "source_url": "https://icar.gov.in/…",
  "section": "Soil-crop suitability",
  "domain": "farming", "language": "en",
  "relevance_score": 0.87,               # final reranker score
  "retrieval_method": "hybrid",          # dense|sparse|hybrid|exact|cross_lingual|user_doc|live_tool
  "metadata": { …full Qdrant payload… } }
```
Live-tool chunks look the same but carry `"retrieval_method":"live_tool"`, `"live":true`, and a
descending `relevance_score` by rank.

### 39.8 Response-generation flow (inside `node_generate`)

```
get_agent(domain)                        # e.g. FarmingAgent
   │
   ▼ knowledge_text = "\n\n".join( "[{source}]\n{text}" for chunk in state["knowledge"] )
   ▼ agent_context  = { **state["context"], "knowledge": knowledge_text }   # knowledge folded in
   ▼ explanation_plan = build_explanation_plan(query, domain, {**profile, **session_facts}, language)
   │
   ▼ system_prompt = concatenation, in THIS order:
   ├─ runtime_prompt_header(profile, language, extra=session_facts)  # real IST date/year, location,
   │                                                                  # language enforcement, "text=facts"
   ├─ agent.build_system_prompt(agent_context, profile, language)    # domain rules + the knowledge blocks
   ├─ format_for_prompt(context["user_memories"])                    # long-term memory
   ├─ reasoning_directive(plan)      # if REASONING_USE_PLAN — follow the chosen plan
   │   + quality_directive(domain, complexity)   # bakes reviewer/critic concerns in-prompt
   ├─ synthesis_directive(explanation_plan)      # depth / teaching_format / modality (§19)
   └─ _READABILITY_DIRECTIVE          # how to write `summary`: answer-first, plain Markdown, grounded
   │
   ▼ messages = [system] + context["working_memory"] turns + [{"role":"user","content": query}]
   ▼ route_completion(messages, complexity)   # picks tier (§10), calls LiteLLM
   │
   ▼ LLM returns TEXT that is a JSON object, e.g.:
     { "cardType":"plan", "title":"5 एकड़ काली मिट्टी के लिए फसल योजना",
       "summary":"…", "plan_cols":["फसल","मौसम","पानी"], "plan_rows":[{…}],
       "sources":[{"text":"ICAR crop guide","url":"https://…"}] }
   │
   ▼ agent.build_response_card(llm_text, language)   # parse_card: strip ```json fences,
   │                                                  # json.loads, coerce to card dict
   ▼ (optional) reflect_and_improve / critique_answer  # opt-in (REASONING_REFLECT_ENABLED / CRITIC_ENABLED)
   ▼ enrich_card(...)  → key_takeaway, explain_differently, understanding_check
   ▼ resolve_inline_media(...) → inline images/charts/SVG; gather_study_resources; promote_media_card
   ▼ backfill card["sources"] from graded knowledge if the model omitted them
   → state["response_card"] = card  →  cite_claims (answer-first retro-citation) → verify_claims → finalize
```

> A legacy `_build_system_prompt()` still exists in `orchestrator.py`, but the live path uses
> the **domain agent's** `build_system_prompt` (above); the knowledge is passed *into* the agent
> context, not appended as a separate top-level block.

**`node_finalize` then layers on** (order matters):
1. `corroborate(all_claims, knowledge_pool)` then `score_answer(...)` → `ReliabilityScore`
   (conversational/clarify/error cards are scored `not_applicable`).
2. `gate.finalize(card, domain, language, …)` → `safety_filter` (non-normal tag ⇒ safe card),
   attach `confidence`/`reliability`/`low_confidence`, `apply_disclaimers` (central).
3. Force `card["language"] = language`; compose `card["speech_text"]` (plain text for TTS);
   set `card["correlation_id"]`.
4. Surface transparency fields on non-trivial routes: `card["plan"]` and `card["mission"]`
   (the plan/mission the orchestrator actually followed) if not already present.
5. Append the turn to L0 working memory; observe `nipun_rag_loops_per_query`, increment
   `nipun_queries_total{status=success|abstained}`.

### 39.9 Final `response_card` — the exact schema (`api/schemas.py`)

Typed base (`extra="allow"`, so agents may add domain-specific keys, `correlation_id`,
`speech_text`, `metrics`):

| Field | Type | When |
| --- | --- | --- |
| `cardType` | enum | always (`answer` default) — 23 values: answer, step_action, plan, document, price_table, weather, scheme_list, clarify, whiteboard, browser, mindmap, timeline, code_editor, error, diagram, illustrative_diagram, comparison_table, map, interactive_widget, video, book (+ runtime `agent_task`) |
| `language` | str | always (authoritative, forced in finalize) |
| `title` | str | always |
| `summary` | str? | most |
| `steps[]` | `{title,desc,duration?,status:pending\|active\|done}` | step_action |
| `plan_cols[]` / `plan_rows[]` | `list[str]` / `list[dict]` | plan |
| `prices[]` | `{crop,price,change:up\|down\|flat,rate}` | price_table |
| `weather` | `{temp,condition,forecast:[{day,temp,condition}],alerts?}` | weather |
| `schemes[]` | `{name,eligible,benefit,criteria,link?}` | scheme_list |
| `options[]` | `list[str]` | clarify |
| `form` | `{submitLabel, fields:[{name,label,type:text\|number\|select\|multiselect,options?,required,placeholder?}]}` | clarify |
| `code` / `codeLanguage` | str | code_editor |
| `mindmap_nodes[]` | `{id,label,x,y,connections[]}` | mindmap |
| `url` | str? | document/browser |
| `disclaimer` | str? | legal/finance/health/scheme (added centrally) |
| `sources[]` | `{text,url?}` | grounded answers |
| `confidence` | float? | calibrated reliability 0..1 |
| `abstained` | bool? | grounded-or-abstain fired |
| `safety_tag` | str? | safe-path cards |
| `reliability` | dict? | `{score,band,label,warn,applicable,signals,reasons,unsupported_claims}` |
| `low_confidence` | bool? | mirror of `reliability.warn` |
| `key_takeaway` | str? | adaptive synthesis |
| `explain_differently[]` | `["simpler","deeper","with_example","in_<lang>"]` | adaptive |
| `understanding_check` | str? | students |
| `depth` / `teaching_format` | str? | adaptive |
| `diagram` / `map_data` / `widget` | dict? | declarative visual specs |
| `plan` / `mission` | dict (extra) | non-trivial routes — the plan/mission the orchestrator followed |
| `speech_text` | str (extra) | always (TTS read-out, set in finalize) |
| `correlation_id` | str (extra) | always |

> **Note on `clarify`:** the typed `ClarifyForm` model is `{submitLabel, fields[]}`. "Skip"
> is not a form field — the client expresses skip by re-sending the original query with
> `clarifications: {}` (empty object), which the backend reads as "asked & skipped".

### 39.10 Error formats (what clients must handle)

- **Auth / not-found / forbidden:** `{"error": {"code","message","correlation_id"}}` — codes
  `MISSING_TOKEN`, `INVALID_TOKEN`, `FORBIDDEN`, `NOT_FOUND`, `RATE_LIMITED`.
- **LLM rate limit (429):** `{"detail": {"code":"LLM_RATE_LIMITED","message","message_en","correlation_id"}}`
  (`message` is localised, `message_en` is the English fallback).
- **Validation (422):** FastAPI's standard field-error body.
- **Unhandled (500):** JSON with the `correlation_id` (from the gateway middleware) so any
  failure is traceable in `chat.log`/`error.log`.

### 39.11 Ingestion data flow (write path) — format

```
source (PDF/HTML/URL/text)
  → parse   → ParsedDocument{ title, text, domain, language, source_url, metadata }
  → dedup   → source_hash = sha256(text)[:16]; skip if in document_index
  → chunk   → Chunk{ text, chunk_index, section?, page_number?, token_estimate }  (≈512 tok, 50 overlap)
  → embed   → EmbeddingResult{ dense:[[1024]…], sparse:[{token_id:weight}…] }
  → dual-write (parallel):
       Qdrant  PointStruct{ id, vector:{dense:[…], sparse:{indices,values}},
                            payload:{ text,title,source,source_url,section,chunk_index,
                                      domain,language,subject,level,book_id,visibility,active,
                                      [owner_id,document_id,session_id for user docs] } }   (batches of 100)
       ES      { title, section, content, keywords, language, source, domain, date }  (async_bulk)
  → record  → INSERT document_index(source_url, source_hash, domain, language, title, chunk_count, …)
```

### 39.12 End-to-end example (one farming query, condensed)

```
POST /query {"query":"5 ekad kali mitti me kaunsi fasal?","session_id":"S1"}
 → cid=C1; rate ok
 → understand: domain=farming, complexity=multi_step, entities=["kali mitti"], safety=normal, language=hi
 → embed: query_embedding=[…1024…]
 → assemble_context: profile{state:MH,land:5,soil:black}, working_memory[…]
 → clarify_check: slots satisfied by profile → no form
 → plan_route: route=agentic_rag, plan{steps:[retrieve,generate]}
 → retrieve: Qdrant(farming) dense+sparse + RRF + rerank → 5 chunks (ICAR crop guide…)
 → grade_documents: 4 kept, sufficient=true
 → generate: FarmingAgent → LLM JSON {cardType:"plan",title:"…",plan_rows:[…],sources:[…]}
 → verify_claims: confidence=0.86, unsupported=[]
 → finalize: reliability{band:"high"}, disclaimer(scheme? no), speech_text="…", persist L0
 → 200 {correlation_id:C1, session_id:S1, response_card:{cardType:"plan", language:"hi", …,
        confidence:0.86, reliability:{band:"high"}, speech_text:"…", correlation_id:C1}}
```

---

*Everything above reflects the current source under `backend/src/` and `frontend/src/` (audited
against `demo_ver_0.11`). When you change behaviour, update the matching section — this file is the
contract juniors read first.*
