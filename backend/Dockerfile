# ── Stage 1: dependency install ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN pip install uv

WORKDIR /app
# Copy BOTH the manifest and the lockfile — `--frozen` requires uv.lock to be present.
COPY pyproject.toml uv.lock ./
# Install dependencies only (the app runs via PYTHONPATH, so the project package itself
# doesn't need to be built here — avoids needing src/ or README in the builder stage).
RUN uv sync --no-dev --frozen --no-install-project

# ── Stage 2: production image ─────────────────────────────────────────────────
FROM python:3.12-slim AS runner

# Non-root user for security
RUN useradd --create-home --uid 1001 bharat
USER bharat
WORKDIR /home/bharat/app

# Copy installed packages from builder
COPY --from=builder /app/.venv .venv
ENV PATH="/home/bharat/app/.venv/bin:$PATH"

# Copy source
COPY --chown=bharat:bharat src/ src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/home/bharat/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# Worker count is configurable via UVICORN_WORKERS (default 2). Shell form so the env var
# expands at runtime; `exec` keeps uvicorn as PID 1 for correct signal handling / graceful shutdown.
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
