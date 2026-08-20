"""Session management — CRUD for conversation sessions."""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.db.postgres import execute, fetch, fetchrow

log = structlog.get_logger("api.sessions")
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class SessionOut(BaseModel):
    id: str
    title: str | None
    language: str
    domain: str | None
    turn_count: int
    started_at: str
    ended_at: str | None


class CreateSessionRequest(BaseModel):
    title: str | None = Field(None, max_length=200)
    language: str = Field("hi", description="ISO 639-1 language code")
    domain: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(None, max_length=200)
    language: str | None = None
    domain: str | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    language: str | None
    domain: str | None
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_session(row: Any) -> SessionOut:
    return SessionOut(
        id=str(row["id"]),
        title=row["title"],
        language=row["language"],
        domain=row["domain"],
        turn_count=row["turn_count"],
        started_at=row["started_at"].isoformat(),
        ended_at=row["ended_at"].isoformat() if row["ended_at"] else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/sessions",
    response_model=list[SessionOut],
    summary="List sessions",
    description="Return all conversation sessions for the authenticated user, newest first.",
    tags=["sessions"],
)
async def list_sessions(
    user: dict = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
) -> list[SessionOut]:
    rows = await fetch(
        """
        SELECT id, title, language, domain, turn_count, started_at, ended_at
        FROM sessions
        WHERE user_id = $1::uuid
        ORDER BY started_at DESC
        LIMIT $2 OFFSET $3
        """,
        user["user_id"], limit, offset,
    )
    log.info("sessions_listed", user_id=user["user_id"], count=len(rows), limit=limit, offset=offset)
    return [_row_to_session(r) for r in rows]


@router.post(
    "/sessions",
    response_model=SessionOut,
    status_code=201,
    summary="Create session",
    description="Start a new conversation session.",
    tags=["sessions"],
)
async def create_session(
    req: CreateSessionRequest,
    user: dict = Depends(get_current_user),
) -> SessionOut:
    session_id = str(uuid.uuid4())
    await execute(
        """
        INSERT INTO sessions (id, user_id, title, language, domain, turn_count, started_at)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, 0, NOW())
        """,
        session_id, user["user_id"], req.title, req.language, req.domain,
    )
    row = await fetchrow(
        "SELECT id, title, language, domain, turn_count, started_at, ended_at FROM sessions WHERE id = $1::uuid",
        session_id,
    )
    log.info("session_created", session_id=session_id, user_id=user["user_id"])
    return _row_to_session(row)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionOut,
    summary="Get session",
    description="Get metadata for a single session.",
    tags=["sessions"],
)
async def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> SessionOut:
    row = await fetchrow(
        """
        SELECT id, title, language, domain, turn_count, started_at, ended_at
        FROM sessions WHERE id = $1::uuid AND user_id = $2::uuid
        """,
        session_id, user["user_id"],
    )
    if not row:
        log.warning("session_not_found", session_id=session_id, user_id=user["user_id"])
        raise HTTPException(status_code=404, detail="Session not found.")
    log.debug("session_fetched", session_id=session_id, user_id=user["user_id"])
    return _row_to_session(row)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageOut],
    summary="Get session messages",
    description="Return the full conversation history for a session.",
    tags=["sessions"],
)
async def get_session_messages(
    session_id: str,
    user: dict = Depends(get_current_user),
    limit: int = 100,
) -> list[MessageOut]:
    exists = await fetchrow(
        "SELECT id FROM sessions WHERE id = $1::uuid AND user_id = $2::uuid",
        session_id, user["user_id"],
    )
    if not exists:
        log.warning("session_messages_not_found", session_id=session_id, user_id=user["user_id"])
        raise HTTPException(status_code=404, detail="Session not found.")

    rows = await fetch(
        """
        SELECT id, role, content, language, domain, created_at
        FROM conversation_logs
        WHERE session_id = $1::uuid
        ORDER BY created_at ASC
        LIMIT $2
        """,
        session_id, limit,
    )
    log.info("session_messages_fetched", session_id=session_id, count=len(rows))
    return [
        MessageOut(
            id=str(r["id"]),
            role=r["role"],
            content=r["content"],
            language=r["language"],
            domain=r["domain"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionOut,
    summary="Update session",
    description="Rename a session or change its language/domain.",
    tags=["sessions"],
)
async def update_session(
    session_id: str,
    req: UpdateSessionRequest,
    user: dict = Depends(get_current_user),
) -> SessionOut:
    row = await fetchrow(
        "SELECT id FROM sessions WHERE id = $1::uuid AND user_id = $2::uuid",
        session_id, user["user_id"],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Session not found.")

    updates = []
    params: list[Any] = []
    idx = 1
    if req.title is not None:
        updates.append(f"title = ${idx}")
        params.append(req.title)
        idx += 1
    if req.language is not None:
        updates.append(f"language = ${idx}")
        params.append(req.language)
        idx += 1
    if req.domain is not None:
        updates.append(f"domain = ${idx}")
        params.append(req.domain)
        idx += 1

    if updates:
        params.append(session_id)
        await execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ${idx}::uuid",
            *params,
        )

    updated = await fetchrow(
        "SELECT id, title, language, domain, turn_count, started_at, ended_at FROM sessions WHERE id = $1::uuid",
        session_id,
    )
    return _row_to_session(updated)


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Delete session",
    description="Delete a session and all its conversation history.",
    tags=["sessions"],
)
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> None:
    row = await fetchrow(
        "SELECT id FROM sessions WHERE id = $1::uuid AND user_id = $2::uuid",
        session_id, user["user_id"],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Purge any docs uploaded in this session from Qdrant BEFORE the DB cascade removes
    # their rows — otherwise their vectors would be orphaned in the index.
    try:
        from src.ingestion.user_docs import delete_session_documents

        await delete_session_documents(user["user_id"], session_id)
    except Exception as exc:
        log.warning("session_doc_purge_failed", session_id=session_id, error=str(exc))

    await execute("DELETE FROM sessions WHERE id = $1::uuid", session_id)
    log.info("session_deleted", session_id=session_id, user_id=user["user_id"])
