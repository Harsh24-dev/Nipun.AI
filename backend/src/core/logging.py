import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from src.config import settings

# ── Constants ─────────────────────────────────────────────────────────────────

_PII_FIELDS = {"phone", "aadhaar", "pan", "email", "password", "token", "otp"}

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

# Stable identity of THIS process — lets you tell the 2 uvicorn workers apart in a shared
# log file (a request may be served by either). Env WORKER_ID wins if set (e.g. by the
# process manager); otherwise the OS pid. Attached to every structured record as `pid`.
_PID = os.getpid()
_WORKER_ID = os.environ.get("WORKER_ID") or str(_PID)


# ── Process / worker context ──────────────────────────────────────────────────

def add_process_context(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """Stamp every record with the worker identity so logs from the 2 uvicorn workers
    (a request may land on either) can be told apart in the shared files."""
    event_dict.setdefault("pid", _WORKER_ID)
    return event_dict

# ── PII masking ───────────────────────────────────────────────────────────────

def mask_pii(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    for field in _PII_FIELDS:
        if field in event_dict:
            value = str(event_dict[field])
            if field == "phone" and len(value) >= 10:
                event_dict[field] = value[:2] + "X" * (len(value) - 4) + value[-2:]
            else:
                event_dict[field] = "***"
    return event_dict


# ── Callsite helper ───────────────────────────────────────────────────────────
# Fold structlog's callsite keys (filename/func_name/lineno) into one `file:line:func`
# token so a human — or Claude reading the log to debug — can jump straight to the code
# that emitted the line.

def _callsite(event_dict: EventDict) -> str:
    fn  = event_dict.pop("filename", None)
    ln  = event_dict.pop("lineno", None)
    fnc = event_dict.pop("func_name", None)
    # `module`/`pathname` may also be added by CallsiteParameterAdder — drop the noisy ones.
    event_dict.pop("module", None)
    event_dict.pop("pathname", None)
    event_dict.pop("process", None)
    if fn is None and ln is None:
        return ""
    base = f"{fn}:{ln}" if ln is not None else str(fn)
    return f"{base}:{fnc}" if fnc else base


# ── Pipe-delimited renderer ───────────────────────────────────────────────────
# Produces:  2026-07-01 17:30:04 | INFO     | db.postgres  agent.py:42:run | message  key=value

def _pipe_renderer(logger: Any, method: str, event_dict: EventDict) -> str:
    ts        = event_dict.pop("timestamp", "")
    level     = event_dict.pop("level", "info").upper()
    name      = event_dict.pop("logger", event_dict.pop("service", "app"))
    event     = str(event_dict.pop("event", ""))
    caller    = _callsite(event_dict)

    # Exception info rendered inline
    exc_info  = event_dict.pop("exc_info", None)
    exception = event_dict.pop("exception", None)

    # Drop internal structlog keys
    for k in ("_record", "_from_structlog"):
        event_dict.pop(k, None)

    # Remaining fields rendered inline as  key=value
    extras = "  ".join(
        f"{k}={v}"
        for k, v in event_dict.items()
        if v is not None and not str(k).startswith("_")
    )
    message = f"{event}  {extras}".rstrip() if extras else event

    # Name column carries the callsite so every line is traceable back to its code.
    name_col = f"{name} {caller}".rstrip() if caller else name
    line = f"{ts} | {level:<8} | {name_col:<40} | {message}"

    # Append exception traceback if present
    if exception:
        line = f"{line}\n{exception}"

    return line


# ── JSON renderer prep ────────────────────────────────────────────────────────
# Normalizes keys into a stable, machine-parseable schema (ts / level / logger / event /
# caller + all structured fields) so LOG_JSON output drops cleanly into log aggregators.

def _json_prep(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    caller = _callsite(event_dict)
    if "timestamp" in event_dict:
        event_dict["ts"] = event_dict.pop("timestamp")
    if "logger" in event_dict:
        event_dict["logger"] = event_dict.get("logger")
    if caller:
        event_dict["caller"] = caller
    for k in ("_record", "_from_structlog"):
        event_dict.pop(k, None)
    return event_dict


# ── File handler factory ──────────────────────────────────────────────────────

def _rotating(filename: str, level: int) -> logging.handlers.RotatingFileHandler:
    h = logging.handlers.RotatingFileHandler(
        LOG_DIR / filename,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    h.setLevel(level)
    return h


class _PrefixFilter(logging.Filter):
    """Pass only records whose logger name starts with one of the given prefixes —
    used to fan a subsystem's logs (llm.*, retrieval.*, …) into its own file."""

    def __init__(self, prefixes: tuple[str, ...]) -> None:
        super().__init__()
        self._prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self._prefixes)


# Subsystem log files → the logger-name prefixes routed into each. Every record still
# also lands in app.log (the catch-all); these files are focused views for monitoring
# one subsystem at a time. Keyed by filename.
_SUBSYSTEM_ROUTES: dict[str, tuple[str, ...]] = {
    "llm.log":       ("llm.",),
    "retrieval.log": ("retrieval.", "agents.grading"),
    "agents.log":    ("agent.", "agents.", "orchestrator"),
    "safety.log":    ("safety.", "execution."),
    "db.log":        ("db.",),
    # IPA (the live browser-automation agent): every ipa.* logger — agent loop, browser,
    # planner, controller, session, recipes, executors — fans its STRUCTURED records into
    # ipa.debug.log for deep debugging. (The readable per-task story lives in ipa.log, the
    # browser-agent parallel to flow.log — see ipa_console + the ipa_flow logger below.)
    "ipa.debug.log": ("ipa.",),
    # Background/scheduled work and ingestion pipelines get focused views too.
    "tasks.log":     ("tasks.", "task."),
    "ingestion.log": ("ingestion.", "graph."),
}


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Shared pre-processors (run before any renderer)
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_process_context,                          # pid / worker id on every record
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        mask_pii,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),   # renders exc_info into "exception" key
    ]

    # Callsite (file:line:func) — the single most useful field when debugging from logs
    # (human or AI): every record points at the exact line that emitted it. Added near the
    # end so it resolves the caller's frame, not a processor's.
    if settings.LOG_CALLSITE:
        shared.append(
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            )
        )

    # File formatter — JSON lines (machine-parseable, for aggregators) when LOG_JSON,
    # else the readable pipe-delimited format. Both carry the same fields.
    if settings.LOG_JSON:
        file_fmt: logging.Formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _json_prep,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=shared,
        )
    else:
        file_fmt = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _pipe_renderer,
            ],
            foreign_pre_chain=shared,
        )

    # Plain message-only formatter for the clean terminal + flow.log + ipa.log views.
    plain_fmt = logging.Formatter("%(message)s")

    # ── Handlers ──────────────────────────────────────────────────────────────
    app_h = _rotating("app.log", log_level)           # everything
    app_h.setFormatter(file_fmt)

    error_h = _rotating("error.log", logging.ERROR)   # errors only
    error_h.setFormatter(file_fmt)

    access_h = _rotating("access.log", logging.INFO)  # HTTP traffic
    access_h.setFormatter(file_fmt)

    frontend_h = _rotating("frontend.log", logging.DEBUG)  # browser logs
    frontend_h.setFormatter(file_fmt)

    chat_h = _rotating("chat.log", logging.DEBUG)  # complete per-request chat-pipeline trace
    chat_h.setFormatter(file_fmt)

    # ── Root logger — files only, NO console (keeps the terminal clean) ─────────
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(app_h)
    root.addHandler(error_h)

    # ── Subsystem files — focused per-subsystem views, routed by logger name ──────
    # Each also stays in app.log (catch-all); these let you `tail llm.log`,
    # `tail retrieval.log`, etc. to watch one part of the flow in isolation.
    for filename, prefixes in _SUBSYSTEM_ROUTES.items():
        sub_h = _rotating(filename, log_level)
        sub_h.setFormatter(file_fmt)
        sub_h.addFilter(_PrefixFilter(prefixes))
        root.addHandler(sub_h)

    # ── access logger — own file, no console clutter ──────────────────────────
    al = logging.getLogger("access")
    al.setLevel(logging.INFO)
    al.handlers.clear()
    al.addHandler(access_h)
    al.propagate = False

    # ── frontend logger — own file only ───────────────────────────────────────
    fl = logging.getLogger("frontend")
    fl.setLevel(logging.DEBUG)
    fl.handlers.clear()
    fl.addHandler(frontend_h)
    fl.propagate = False

    # ── chat logger — the ONE complete per-request chat-pipeline trace ─────────
    # Every step of a /query (or /ws) request lands here in order: query → language →
    # classification → route/plan → retrieval (chunks+scores) → generation (agent, tokens,
    # latency) → verification → reliability → final card → a single `chat_summary` line.
    # Writes the real bodies to its OWN chat.log only (propagate=False keeps the heavy
    # content out of app.log). app.log still gets the lightweight per-module metadata.
    # This is THE file to monitor the chat flow across all users.
    cll = logging.getLogger("chat")
    cll.setLevel(logging.DEBUG)
    cll.handlers.clear()
    cll.addHandler(chat_h)
    cll.propagate = False

    # ── flow logger — the readable per-request story (query → steps → answer) ──
    # Written to flow.log ONLY (not the terminal). This is THE file to read when you want
    # to understand, at a glance, what a request did end-to-end.
    flow_h = _rotating("flow.log", logging.INFO)
    flow_h.setFormatter(plain_fmt)
    fw = logging.getLogger("flow")
    fw.setLevel(logging.INFO)
    fw.handlers.clear()
    fw.addHandler(flow_h)
    fw.propagate = False

    # ── ipa_flow logger — the readable per-TASK story for the browser agent ────
    # The IPA parallel to flow.log: one scannable block per browser-automation task
    # (goal → each checklist step → each action/hand-off → final result), written to
    # ipa.log ONLY. This is THE file to read to understand what a browser run did
    # end-to-end. The heavy STRUCTURED ipa.* records still fan into ipa.debug.log.
    ipa_h = _rotating("ipa.log", logging.INFO)
    ipa_h.setFormatter(plain_fmt)
    iw = logging.getLogger("ipa_flow")
    iw.setLevel(logging.INFO)
    iw.handlers.clear()
    iw.addHandler(ipa_h)
    iw.propagate = False

    # ── terminal logger — the ONLY thing on the console: API + LLM call heartbeat ──
    # Clean one-liners to stdout (and mirrored to terminal.log). Nothing else prints to the
    # console, so the terminal stays readable while all detail lives in the log files.
    term_console = logging.StreamHandler(sys.stdout)
    term_console.setFormatter(plain_fmt)
    term_file = _rotating("terminal.log", logging.INFO)
    term_file.setFormatter(plain_fmt)
    tl = logging.getLogger("terminal")
    tl.setLevel(logging.INFO)
    tl.handlers.clear()
    tl.addHandler(term_console)
    tl.addHandler(term_file)
    tl.propagate = False

    # Redirect uvicorn.access into our access file (no console)
    uv = logging.getLogger("uvicorn.access")
    uv.handlers.clear()
    uv.addHandler(access_h)
    uv.propagate = False

    # Silence noisy third-party libs. `websockets` / `uvicorn.protocols` emit per-frame DEBUG
    # (TEXT/PING/PONG) that floods the console; LiteLLM prints its own per-call INFO which our
    # clean `LLM …` terminal line replaces.
    for noisy in ("httpx", "httpcore", "asyncio", "watchfiles", "openai", "litellm", "LiteLLM",
                  "websockets", "uvicorn.protocols", "uvicorn.protocols.websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── Structlog ─────────────────────────────────────────────────────────────
    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "nipun", **ctx: Any) -> structlog.BoundLogger:
    return structlog.get_logger(name, **ctx)

def get_access_logger() -> structlog.BoundLogger:
    return structlog.get_logger("access")

def get_frontend_logger() -> structlog.BoundLogger:
    return structlog.get_logger("frontend")

def get_terminal_logger() -> logging.Logger:
    """Plain stdlib logger for the clean console heartbeat (API + LLM calls)."""
    return logging.getLogger("terminal")

def get_chat_logger() -> structlog.BoundLogger:
    """Dedicated logger for the complete per-request chat-pipeline trace (→ chat.log)."""
    return structlog.get_logger("chat")

def get_ipa_logger(name: str = "ipa") -> structlog.BoundLogger:
    """Structured logger for the browser-automation agent. Any `ipa.*` name fans into
    ipa.debug.log (and app.log). Pass a submodule name, e.g. get_ipa_logger("ipa.browser")."""
    return structlog.get_logger(name)

def get_ipa_flow_logger() -> logging.Logger:
    """Plain stdlib logger for the readable per-task browser-run story (→ ipa.log)."""
    return logging.getLogger("ipa_flow")


# Backward-compatible alias — callers still import get_flow_logger; it now returns the
# chat-pipeline logger (chat.log). Kept so existing imports keep working.
get_flow_logger = get_chat_logger


# ── Chat-flow tracing ──────────────────────────────────────────────────────────
# One helper the whole codebase uses to record the ACTUAL data at each step:
# the query text, LLM prompts + generated responses, retrieved chunks, agent
# output, and the final card — everything needed to replay a request end-to-end.

_flow_log = get_chat_logger()


def preview(value: Any, limit: int | None = None) -> str:
    """Render any value as a compact, truncated, single-string preview for logs.

    dicts/lists are JSON-encoded; long strings are cut to LOG_CONTENT_MAX_CHARS
    with a `…(+N chars)` marker so we never dump megabytes into a log line.
    """
    limit = limit if limit is not None else settings.LOG_CONTENT_MAX_CHARS
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    text = text.replace("\n", "\\n")
    # When truncation is disabled, capture the full value (used for debugging / replay
    # where losing any detail is unacceptable). Otherwise cap the line length.
    if not settings.LOG_FLOW_TRUNCATE:
        return text
    if len(text) > limit:
        return f"{text[:limit]}...(+{len(text) - limit} chars)"
    return text


# Keys whose values must never be written to a log, even in full-content mode.
_SENSITIVE_KEYS = {
    "password", "current_password", "new_password", "token", "access_token",
    "refresh_token", "otp", "pin", "cvv", "secret", "secret_key", "authorization",
    "api_key", "aadhaar", "pan", "card_number", "account_number",
}


def redact(obj: Any) -> Any:
    """Recursively redact sensitive values in a parsed JSON structure so request/response
    bodies can be logged in full without leaking credentials."""
    if isinstance(obj, dict):
        return {k: ("***" if str(k).lower() in _SENSITIVE_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def trace_body(raw: bytes | None) -> Any:
    """Turn a raw request/response body into a redacted, log-safe value: parsed+redacted
    JSON when possible, else a plain (redaction-free) string preview."""
    if not raw:
        return None
    try:
        return redact(json.loads(raw))
    except (ValueError, TypeError):
        try:
            return raw.decode("utf-8", "replace")
        except Exception:
            return f"<{len(raw)} bytes>"


def trace_flow(step: str, correlation_id: str = "", **data: Any) -> None:
    """Record one step of the request flow with its real payload.

    Gated by LOG_FLOW_ENABLED. When LOG_FLOW_CONTENT is off, values are replaced
    by their type/length so the flow shape is still visible without bodies.
    Never raises — tracing must never break the request path.
    """
    if not settings.LOG_FLOW_ENABLED:
        return
    try:
        fields: dict[str, Any] = {}
        for key, val in data.items():
            if settings.LOG_FLOW_CONTENT:
                fields[key] = preview(val)
            elif val is None:
                fields[key] = None
            elif isinstance(val, (str, bytes, list, tuple, dict)):
                fields[key] = f"<{type(val).__name__} len={len(val)}>"
            else:
                fields[key] = val
        _flow_log.info(step, correlation_id=correlation_id, **fields)
    except Exception:  # pragma: no cover - tracing must be best-effort
        pass
