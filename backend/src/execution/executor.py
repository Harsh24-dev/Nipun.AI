"""
PREPARE → CONFIRM → EXECUTE → AUDIT.

Nothing money-moving, submitting, booking, or irreversible executes without explicit UI
confirmation. Every step is written to an append-only audit trail (task_audit). Real
action handlers are registered ONE integration at a time; until then EXECUTE is a no-op
guarded by EXECUTION_ENABLED — the machinery exists but performs no external action.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

from src.config import settings
from src.core.metrics import TASK_LIFECYCLE_TOTAL
from src.execution.circuit_breaker import breaker
from src.execution.guards import assert_no_credentials

log = structlog.get_logger("execution.executor")

# Registry of REAL action handlers. Empty by design — add one integration at a time,
# each returning a JSON-serialisable result. Presence here + EXECUTION_ENABLED are the
# only ways a real action can run.
ACTION_HANDLERS: dict[str, Callable[[dict], Awaitable[dict]]] = {}


@dataclass
class PreparedAction:
    token: str
    action: str
    params: dict
    preview: str
    user_id: str
    session_id: str
    correlation_id: str
    created_at: float
    expires_at: float


# Prepared actions awaiting confirmation. Backed by Redis so a token minted on ONE worker
# can be confirmed/rejected on ANY worker (the app runs multiple uvicorn workers); the
# in-process dict is a same-worker fast path AND the graceful fallback when Redis is down.
_PREPARED: dict[str, PreparedAction] = {}
_PREP_KEY = "nipun:prepared:{token}"


def _to_dict(p: PreparedAction) -> dict:
    return {
        "token": p.token, "action": p.action, "params": p.params, "preview": p.preview,
        "user_id": p.user_id, "session_id": p.session_id, "correlation_id": p.correlation_id,
        "created_at": p.created_at, "expires_at": p.expires_at,
    }


async def _store_prepared(p: PreparedAction) -> None:
    _PREPARED[p.token] = p   # same-worker fast path / fallback
    try:
        from src.db.redis import set_json
        ttl = max(1, int(p.expires_at - time.time()))
        await set_json(_PREP_KEY.format(token=p.token), _to_dict(p), ttl=ttl)
    except Exception as exc:   # Redis absent/down → in-process only (single-worker still works)
        log.debug("prepared_redis_store_skipped", error=str(exc))


async def _load_prepared(token: str) -> PreparedAction | None:
    p = _PREPARED.get(token)
    if p is not None:
        return p
    try:
        from src.db.redis import get_json
        data = await get_json(_PREP_KEY.format(token=token))
        if data:
            return PreparedAction(**data)
    except Exception as exc:
        log.debug("prepared_redis_load_skipped", error=str(exc))
    return None


async def _drop_prepared(token: str) -> None:
    _PREPARED.pop(token, None)
    try:
        from src.db.redis import delete
        await delete(_PREP_KEY.format(token=token))
    except Exception as exc:
        log.debug("prepared_redis_drop_skipped", error=str(exc))


async def _audit(user_id: str, correlation_id: str, tool: str, phase: str,
                 payload: dict | None = None, result: dict | None = None, status: str = "ok") -> None:
    TASK_LIFECYCLE_TOTAL.labels(phase=phase, task=tool).inc()
    try:
        import json

        from src.db.postgres import execute

        await execute(
            """
            INSERT INTO task_audit (user_id, correlation_id, tool, phase, payload, result, status)
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
            """,
            user_id, correlation_id, tool, phase,
            json.dumps(payload or {}), json.dumps(result or {}), status,
        )
    except Exception as exc:
        # The audit trail is append-only and safety-relevant: a swallowed write silently loses an
        # action record. Keep it best-effort (do NOT change control flow — a failing audit must not
        # block/undo a user-confirmed action) but make the loss LOUD so it is caught, not hidden.
        log.error("audit_write_failed", error=str(exc), error_type=type(exc).__name__,
                  tool=tool, phase=phase, status=status,
                  user_id=user_id, correlation_id=correlation_id)


def _redact(params: dict) -> dict:
    """Never persist raw sensitive values in the audit trail."""
    redacted = {}
    for k, v in (params or {}).items():
        if any(s in k.lower() for s in ("otp", "pin", "password", "card", "cvv", "aadhaar", "pan", "account")):
            redacted[k] = "***"
        else:
            redacted[k] = v
    return redacted


async def prepare(action: str, params: dict, user_id: str, session_id: str, correlation_id: str) -> PreparedAction:
    """Validate + build a confirmation preview. Does NOT perform the action."""
    await breaker.check_async(session_id, "tool")
    assert_no_credentials(params)   # raises CredentialError if credentials present

    token = str(uuid.uuid4())
    now = time.time()
    preview = f"Ready to '{action}' with: {_redact(params)}. Confirm to proceed — nothing has been done yet."
    prepared = PreparedAction(
        token=token, action=action, params=params, preview=preview,
        user_id=user_id, session_id=session_id, correlation_id=correlation_id,
        created_at=now, expires_at=now + settings.EXECUTION_CONFIRM_TTL,
    )
    await _store_prepared(prepared)
    await _audit(user_id, correlation_id, action, "prepare", payload=_redact(params))
    log.info("action_prepared", action=action, token=token, correlation_id=correlation_id)
    return prepared


async def reject(token: str) -> None:
    prepared = await _load_prepared(token)
    await _drop_prepared(token)
    if prepared:
        await _audit(prepared.user_id, prepared.correlation_id, prepared.action, "reject")


@dataclass
class ExecutionResult:
    status: str                      # executed | disabled | not_found | expired | no_handler
    result: dict = field(default_factory=dict)
    message: str = ""


async def execute(token: str, user_id: str, correlation_id: str) -> ExecutionResult:
    """Execute a prepared action ONLY after explicit confirmation (this call = confirm)."""
    prepared = await _load_prepared(token)
    if not prepared:
        return ExecutionResult(status="not_found", message="No such prepared action (or already used).")
    if prepared.user_id != user_id:
        return ExecutionResult(status="not_found", message="Prepared action does not belong to this user.")
    if time.time() > prepared.expires_at:
        await _drop_prepared(token)
        await _audit(user_id, correlation_id, prepared.action, "reject", status="expired")
        return ExecutionResult(status="expired", message="Confirmation window expired; please prepare again.")

    await _audit(user_id, correlation_id, prepared.action, "confirm", payload=_redact(prepared.params))

    if not settings.EXECUTION_ENABLED:
        await _drop_prepared(token)
        return ExecutionResult(status="disabled",
                               message="Execution is disabled; this build only prepares and previews actions.")

    handler = ACTION_HANDLERS.get(prepared.action)
    if handler is None:
        await _drop_prepared(token)
        return ExecutionResult(status="no_handler", message=f"No execution handler registered for '{prepared.action}'.")

    await breaker.check_async(prepared.session_id, "tool")   # may raise CircuitOpenError (handled by caller)
    # Always consume the token and audit the outcome, even if the handler raises — otherwise a
    # failing handler would leave the prepared token live (replayable) with no error record.
    try:
        result = await handler(prepared.params)
    except Exception as exc:
        await _drop_prepared(token)
        await _audit(user_id, correlation_id, prepared.action, "execute", status="error",
                     result={"error": str(exc)})
        log.error("action_execution_failed", action=prepared.action,
                  error=str(exc), correlation_id=correlation_id)
        return ExecutionResult(status="error", message="The action failed to execute.")
    await _drop_prepared(token)
    await _audit(user_id, correlation_id, prepared.action, "execute", result=result)
    log.info("action_executed", action=prepared.action, correlation_id=correlation_id)
    return ExecutionResult(status="executed", result=result)
