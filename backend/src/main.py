import asyncio
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Windows: force the Proactor event loop BEFORE uvicorn creates its loop. The IPA browser agent
# (Playwright) launches Chromium as a SUBPROCESS, which a SelectorEventLoop cannot do — it raises
# NotImplementedError (an empty error), which is exactly what made task execution fail on launch.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.responses import Response

from src.config import settings
from src.core.logging import get_logger, get_access_logger, setup_logging, trace_body, trace_flow
from src.core.metrics import ERRORS_TOTAL

# Paths that produce noise / binary and should NOT have their bodies traced.
_UNTRACED_PATHS = ("/metrics", "/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico")

setup_logging()
log = get_logger("gateway")
access_log = get_access_logger()

# Dev-only default credentials; override via BOOTSTRAP_ADMIN_* env in staging/production.
_DEFAULT_ADMIN = {
    "name": settings.BOOTSTRAP_ADMIN_NAME,
    "email": settings.BOOTSTRAP_ADMIN_EMAIL,
    "password": settings.BOOTSTRAP_ADMIN_PASSWORD,
}


async def _ensure_default_admin() -> None:
    import uuid
    import bcrypt
    import asyncpg
    from src.db.postgres import fetchval, execute

    if not settings.BOOTSTRAP_ADMIN_ENABLED:
        log.info("Admin bootstrap disabled (BOOTSTRAP_ADMIN_ENABLED=false) — skipping.")
        return

    # Refuse to seed a publicly-known default admin in ANY non-development environment
    # (production AND staging) — a guaranteed backdoor. Development may keep the default.
    if settings.APP_ENV != "development" and settings.BOOTSTRAP_ADMIN_PASSWORD == "admin2402":
        raise RuntimeError(
            f"Refusing to create the default admin outside development (APP_ENV={settings.APP_ENV}). "
            "Set BOOTSTRAP_ADMIN_EMAIL and a strong BOOTSTRAP_ADMIN_PASSWORD in the environment, "
            "or set BOOTSTRAP_ADMIN_ENABLED=false and create the admin manually."
        )

    log.debug("Checking for existing admin account in database...")
    try:
        existing = await fetchval("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    except asyncpg.exceptions.UndefinedTableError:
        log.error(
            "Database schema is not initialised — the 'users' table is missing. "
            "Run migrations first:  make migrate  (or: uv run python -m src.db.migrate)"
        )
        raise RuntimeError("Database not migrated — run `make migrate` before starting the app.") from None
    if existing:
        log.info(f"Admin account already exists  admin_id={existing}")
        return

    log.info(f"No admin found — creating default admin  email={_DEFAULT_ADMIN['email']}")
    user_id = str(uuid.uuid4())
    password_hash = bcrypt.hashpw(_DEFAULT_ADMIN["password"].encode(), bcrypt.gensalt()).decode()
    # Idempotent: both uvicorn workers can race past the check-then-insert above, and
    # `email` is unique — ON CONFLICT DO NOTHING makes the loser a harmless no-op instead
    # of crashing the worker on a duplicate-key error.
    await execute(
        """
        INSERT INTO users (id, name, email, password_hash, role, language, created_at, updated_at)
        VALUES ($1::uuid, $2, $3, $4, 'admin', 'en', NOW(), NOW())
        ON CONFLICT (email) DO NOTHING
        """,
        user_id,
        _DEFAULT_ADMIN["name"],
        _DEFAULT_ADMIN["email"],
        password_hash,
    )
    log.info(f"Default admin created  user_id={user_id}  name={_DEFAULT_ADMIN['name']}  email={_DEFAULT_ADMIN['email']}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from src.db.postgres import init_postgres, close_postgres
    from src.db.redis import init_redis, close_redis
    from src.db.qdrant import init_qdrant
    from src.llm.embeddings import get_embedder
    from src.language.detector import get_detector

    log.info("=" * 60)
    log.info("Nipun.AI Gateway — Starting up")
    log.info(f"env={settings.APP_ENV}  port={settings.APP_PORT}  log_level={settings.LOG_LEVEL}")
    log.info("=" * 60)

    log.info("[1/6] Connecting to PostgreSQL...")
    await init_postgres()

    log.info("[2/6] Connecting to Redis...")
    await init_redis()

    log.info("[3/6] Connecting to Qdrant (vector store)...")
    await init_qdrant()

    # Optional GraphRAG tier — no-op unless GRAPH_ENABLED and Neo4j is up.
    from src.db.neo4j import init_neo4j
    await init_neo4j()

    if settings.EMBEDDING_PROVIDER == "local":
        log.info(f"[4/6] Loading embedding model  model={settings.EMBEDDING_MODEL}  dim={settings.EMBEDDING_DIM}")
        get_embedder()
        log.info(f"[4/6] Embedding model ready  model={settings.EMBEDDING_MODEL}")
    else:
        log.info(f"[4/6] Embedding provider={settings.EMBEDDING_PROVIDER} (remote — skip local load)")

    log.info("[5/6] Loading language detector...")
    get_detector()
    log.info("[5/6] Language detector ready")

    log.info("[6/6] Bootstrapping default admin account...")
    await _ensure_default_admin()

    log.info("=" * 60)
    log.info("Nipun.AI Gateway — Ready to serve requests")
    log.info(f"Docs at http://localhost:{settings.APP_PORT}/docs")
    log.info("=" * 60)
    yield

    log.info("Nipun.AI Gateway — Shutting down...")
    from src.db.neo4j import close_neo4j
    from src.mcp.live.http import close_http_client
    from src.retrieval.hybrid import close_elasticsearch

    await close_neo4j()
    await close_http_client()
    await close_elasticsearch()
    await close_postgres()
    await close_redis()
    log.info("Nipun.AI Gateway — Stopped cleanly")


_DESCRIPTION = """
## Nipun.AI — India-first Multilingual AI Assistant

A production-grade backend for conversational AI optimised for Indian languages and rural use-cases.

### Authentication
All protected endpoints require a **Bearer JWT** in the `Authorization` header.
In `DEBUG` mode an anonymous fallback user is provided automatically.

### Supported languages
`en` · `hi` · `pa` · `ta` · `te` · `mr` · `gu`

### Rate limits
| Scope | Limit |
|-------|-------|
| General | 60 req / min / user |
| LLM inference | 20 req / min / user |
| Action endpoints | 5 req / min / user |

### Real-time streaming
Use the **WebSocket** endpoint `/ws/{session_id}` for token-by-token streaming.
Send the JWT in the first JSON message: `{"token": "<jwt>"}`.
"""

_TAGS: list[dict] = [
    {
        "name": "health",
        "description": "Liveness and dependency health checks. No authentication required.",
    },
    {
        "name": "auth",
        "description": (
            "Email/password authentication. Sign up, log in, verify email OTP, "
            "and reset forgotten passwords. Returns a Bearer JWT for all protected endpoints."
        ),
    },
    {
        "name": "profile",
        "description": "Get and update the authenticated user's profile (name, language, interests, theme, etc.).",
    },
    {
        "name": "sessions",
        "description": "Create, list, rename, and delete conversation sessions. Fetch full message history.",
    },
    {
        "name": "admin",
        "description": (
            "Admin-only user management. "
            "Initialise the first admin, list/update/deactivate users, view their sessions, and force password resets."
        ),
    },
    {
        "name": "query",
        "description": (
            "Submit a natural-language query and receive a structured response card. "
            "Supports both REST (single response) and WebSocket (streaming tokens)."
        ),
    },
    {
        "name": "feedback",
        "description": "Submit thumbs-up / thumbs-down ratings and optional comments on responses.",
    },
    {
        "name": "documents",
        "description": (
            "Upload your own files (PDF/TXT/MD/HTML/DOCX) and ask questions grounded in them. "
            "Documents are **private to you** (RBAC-isolated at the API and vector layers) and, "
            "when uploaded inside a chat session, are used only for that session and deleted with it. "
            "Admins can also upload into the shared corpus via `POST /admin/documents`."
        ),
    },
    {
        "name": "tasks",
        "description": (
            "MCP tools + task assistants. Call read-only live-data tools (web search, finance, "
            "weather, mandi, news, research, books) via `POST /tools/call`, ingest open books "
            "with `POST /tools/ingest-books`, and PREPARE→CONFIRM→EXECUTE guarded actions."
        ),
    },
    {
        "name": "a2a",
        "description": "Agent-to-agent discovery — signed Agent Cards at `/.well-known/agent.json`.",
    },
]

app = FastAPI(
    title="Nipun.AI API",
    version="0.1.0",
    description=_DESCRIPTION,
    openapi_tags=_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
    swagger_ui_parameters={"persistAuthorization": True},
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Dev: accept any localhost / 127.0.0.1 / LAN-IP origin on any port so the Vite dev server
# works on :3000, a fallback port, or the machine's network IP. Using a regex (not "*") keeps
# `allow_credentials=True` valid — browsers reject wildcard origin WITH credentials.
# Prod: only the explicit origins in CORS_ALLOW_ORIGINS (empty → no cross-origin browser access).
_is_dev = settings.APP_ENV == "development"
if _is_dev:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|(?:\d{1,3}\.){3}\d{1,3})(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── Prometheus metrics ────────────────────────────────────────────────────────
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

# ── Correlation ID + request logging middleware ───────────────────────────────
@app.middleware("http")
async def request_middleware(request: Request, call_next):
    import uuid
    import structlog.contextvars

    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        correlation_id=correlation_id,
        method=request.method,
        path=request.url.path,
    )

    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    do_trace = not any(path.startswith(p) for p in _UNTRACED_PATHS)
    # Buffering the request/response body only pays off when full-content tracing is ON. With it
    # OFF (the default) we skip the body reads entirely — otherwise every request paid to buffer
    # its whole body + drain-and-rebuild its response for nothing (a real latency/memory cost).
    trace_content = do_trace and settings.LOG_FLOW_CONTENT

    # Capture the request body up-front ONLY when content tracing is on. Starlette caches it, so
    # downstream handlers can still read it normally. Query params are cheap and always captured.
    req_body = None
    if do_trace:
        if trace_content:
            try:
                req_body = await request.body()
            except Exception:
                req_body = None
        trace_flow(
            "api_request",
            correlation_id=correlation_id,
            method=request.method,
            path=path,
            query_params=dict(request.query_params),
            client_ip=client_ip,
            body=trace_body(req_body),
        )

    start = time.perf_counter()
    try:
        response = await call_next(request)
        ms = round((time.perf_counter() - start) * 1000, 2)
        access_log.info(
            f"{request.method} {request.url.path}  status={response.status_code}  duration_ms={ms}  ip={client_ip}  correlation_id={correlation_id}"
        )
        from src.core.flow_console import api_call
        api_call(request.method, request.url.path, response.status_code, ms)

        # Capture the response body by draining its iterator, then rebuild an identical
        # Response so the client still receives it unchanged. Only JSON bodies are traced;
        # streaming/binary responses are passed through untouched to avoid breaking them.
        # Gated on content tracing: without it we never touch the body iterator, so streaming
        # responses stream and normal responses avoid a full buffer+rebuild on every request.
        if trace_content and "application/json" in response.headers.get("content-type", ""):
            try:
                chunks = [section async for section in response.body_iterator]
                resp_body = b"".join(
                    c if isinstance(c, bytes) else c.encode("utf-8") for c in chunks
                )
                trace_flow(
                    "api_response",
                    correlation_id=correlation_id,
                    method=request.method,
                    path=path,
                    status=response.status_code,
                    duration_ms=ms,
                    body=trace_body(resp_body),
                )
                headers = dict(response.headers)
                headers.pop("content-length", None)   # recomputed from the new body
                headers["X-Correlation-ID"] = correlation_id
                return Response(
                    content=resp_body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type=response.media_type,
                )
            except Exception as trace_exc:   # never let tracing break the response
                log.warning("api_response_trace_failed", path=path, error=str(trace_exc))

        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as exc:
        ms = round((time.perf_counter() - start) * 1000, 2)
        ERRORS_TOTAL.labels(service="gateway", error_code="unhandled").inc()
        log.exception(
            "unhandled_request_exception",
            method=request.method,
            path=request.url.path,
            error=str(exc),
            error_type=type(exc).__name__,
            duration_ms=ms,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Something went wrong. Please try again.",
                    "correlation_id": correlation_id,
                }
            },
        )


# ── Routers ───────────────────────────────────────────────────────────────────
from src.api.routers import (  # noqa: E402
    a2a,
    admin,
    auth,
    documents,
    feedback,
    files,
    health,
    logs,
    memory,
    profile,
    query,
    sessions,
    task_agent,
    tasks,
)

app.include_router(health.router, tags=["health"])
app.include_router(auth.router, tags=["auth"])
app.include_router(profile.router, tags=["profile"])
app.include_router(memory.router)                  # long-term user memory (view/add/edit/delete)
app.include_router(sessions.router, tags=["sessions"])
app.include_router(query.router, tags=["query"])
app.include_router(feedback.router, tags=["feedback"])
app.include_router(admin.router, tags=["admin"])
app.include_router(documents.router, tags=["documents"])  # user uploads (RBAC-isolated)
app.include_router(files.router, tags=["files"])   # download generated deliverables (pptx/docx)
app.include_router(logs.router)
app.include_router(tasks.router, tags=["tasks"])   # tools + task execution
app.include_router(task_agent.router, tags=["task-agent"])  # IPA browser agent (live run)
app.include_router(a2a.router, tags=["a2a"])       # /.well-known/agent.json
