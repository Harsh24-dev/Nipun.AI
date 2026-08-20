"""
Frontend log ingestion — receives batched log entries from the browser
and writes them to logs/frontend.log via the "frontend" stdlib logger.
"""

from typing import Any, Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
_log = structlog.get_logger("frontend")


class LogEntry(BaseModel):
    level: Literal["debug", "info", "warn", "error"]
    message: str
    context: dict[str, Any] = {}
    timestamp: str
    url: str | None = None
    component: str | None = None


class LogBatch(BaseModel):
    entries: list[LogEntry]
    session_id: str | None = None
    user_id: str | None = None


@router.post("/logs", include_in_schema=False)
async def ingest_frontend_logs(batch: LogBatch) -> dict:
    for entry in batch.entries:
        level = entry.level if entry.level != "warn" else "warning"
        fn = getattr(_log, level, _log.info)
        fn(
            entry.message,
            source="frontend",
            url=entry.url,
            component=entry.component,
            session_id=batch.session_id,
            user_id=batch.user_id,
            client_ts=entry.timestamp,
            **entry.context,
        )
    return {"received": len(batch.entries)}
