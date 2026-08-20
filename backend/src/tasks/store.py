"""
Durable service-task store — lets a form-assist / booking task be TRACKED to completion.

The agent fills the form and hands the payment/OTP steps to the user; this store keeps the
task so it can be followed through submitted → in_progress → completed (e.g. "handle my
trip until it's done"). Credentials are NEVER persisted — `filled` is scrubbed on write.

All calls are best-effort: if Postgres is unavailable they degrade to no-ops / empty lists
so the assistant still works, just without cross-session tracking.
"""

from __future__ import annotations

import json

import structlog

from src.execution.guards import scan_for_credentials

log = structlog.get_logger("tasks.store")

_STATUSES = {"gathering", "filled", "awaiting_user", "submitted",
             "in_progress", "completed", "cancelled", "failed"}


def _scrub(filled: dict) -> dict:
    """Drop any field whose key or value looks like a credential — defence in depth."""
    clean = {}
    for k, v in (filled or {}).items():
        if any(s in k.lower() for s in ("otp", "pin", "password", "card", "cvv", "aadhaar", "pan", "account")):
            continue
        if scan_for_credentials(f"{k} {v}"):
            continue
        clean[k] = v
    return clean


async def create_task(
    user_id: str, service: str, title: str, filled: dict,
    remaining_steps: list[str], session_id: str | None = None, status: str = "filled",
) -> str | None:
    """Persist a new service task; returns its id (or None if the store is unavailable)."""
    status = status if status in _STATUSES else "filled"
    try:
        from src.db.postgres import fetchval

        return str(await fetchval(
            """
            INSERT INTO service_tasks (user_id, session_id, service, title, status, filled, remaining_steps)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7::jsonb)
            RETURNING id
            """,
            user_id, session_id, service, title, status,
            json.dumps(_scrub(filled)), json.dumps(remaining_steps or []),
        ))
    except Exception as exc:
        log.debug("service_task_create_skipped", error=str(exc), service=service)
        return None


async def update_status(task_id: str, status: str, tracking: dict | None = None) -> bool:
    if status not in _STATUSES:
        return False
    try:
        from src.db.postgres import execute

        if tracking is not None:
            await execute(
                "UPDATE service_tasks SET status=$2, tracking=tracking||$3::jsonb, updated_at=NOW() "
                "WHERE id=$1::uuid",
                task_id, status, json.dumps(tracking),
            )
        else:
            await execute(
                "UPDATE service_tasks SET status=$2, updated_at=NOW() WHERE id=$1::uuid",
                task_id, status,
            )
        return True
    except Exception as exc:
        log.debug("service_task_update_skipped", error=str(exc), task_id=task_id)
        return False


async def list_active(user_id: str) -> list[dict]:
    """Open tasks for a user (for a 'my tasks' view / follow-up reminders)."""
    try:
        from src.db.postgres import fetch

        rows = await fetch(
            """
            SELECT id, service, title, status, remaining_steps, tracking, due_at, updated_at
            FROM service_tasks
            WHERE user_id = $1::uuid AND status NOT IN ('completed','cancelled','failed')
            ORDER BY updated_at DESC
            """,
            user_id,
        )
        return [dict(r) for r in rows]
    except Exception as exc:
        log.debug("service_task_list_skipped", error=str(exc), user_id=user_id)
        return []
