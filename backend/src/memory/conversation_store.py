"""
Durable conversation persistence (Postgres).

Writes each completed turn to the `sessions` + `conversation_logs` tables so the
history endpoints (`GET /sessions`, `GET /sessions/{id}/messages`) have data to
return. The pipeline previously kept turns ONLY in in-process working memory
(`memory/working.py`), so nothing survived the request — the session the client
was handed back never existed in the DB, and every follow-up read 404'd (empty
session list + a chat window that opened blank).

All writes are best-effort: a persistence failure must never break the answer the
user already received, so callers wrap this and swallow errors.
"""

import json

import structlog

from src.db.postgres import get_pool

log = structlog.get_logger("memory.conversation_store")

_TITLE_MAX = 60


def _derive_title(query: str) -> str:
    """A short, human-readable session title from the first user query."""
    title = " ".join((query or "").split())
    if len(title) > _TITLE_MAX:
        title = title[: _TITLE_MAX - 1].rstrip() + "…"
    return title or "New conversation"


def _assistant_content(card: dict) -> str:
    """Serialize the assistant's response card for storage.

    We keep the FULL card as JSON so rich cards (steps, schemes, sources) survive a
    reload — the frontend parses this back into a ResponseCard. Falls back to the
    plain summary text if the card can't be serialized."""
    try:
        return json.dumps(card, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(card.get("summary") or card.get("title") or "")


async def persist_turn(
    session_id: str,
    user_id: str,
    query: str,
    card: dict,
    language: str,
    domain: str | None,
) -> None:
    """Upsert the session and append both the user and assistant messages.

    Idempotent-ish per turn: the session row is created on the first turn and its
    `turn_count` is incremented on each subsequent turn. Safe to call for every
    completed `process_query` (REST and WebSocket both funnel through here).

    All three writes — the session upsert (which bumps `turn_count`) and the two
    conversation_logs inserts — run inside ONE transaction on a SINGLE connection so
    they commit atomically. Previously they were three independent statements: a retry
    after a partial failure could double-increment `turn_count` and duplicate rows, and
    a mid-sequence failure could orphan the user message (persisted without its reply).
    A transaction makes the turn all-or-nothing."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            # 1) Ensure the session row exists (create on first turn, else bump turn_count).
            #    `title` is only set on creation — later turns keep the original/renamed title.
            await conn.execute(
                """
                INSERT INTO sessions (id, user_id, title, language, domain, turn_count, started_at)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, 1, NOW())
                ON CONFLICT (id) DO UPDATE
                SET turn_count = sessions.turn_count + 1,
                    language   = EXCLUDED.language,
                    domain     = COALESCE(EXCLUDED.domain, sessions.domain)
                """,
                session_id, user_id, _derive_title(query), language, domain,
            )
            # 2) Append the user message, then the assistant message (order = created_at ASC).
            await conn.execute(
                """
                INSERT INTO conversation_logs (session_id, user_id, role, content, language, domain)
                VALUES ($1::uuid, $2::uuid, 'user', $3, $4, $5)
                """,
                session_id, user_id, query, language, domain,
            )
            await conn.execute(
                """
                INSERT INTO conversation_logs (session_id, user_id, role, content, language, domain)
                VALUES ($1::uuid, $2::uuid, 'assistant', $3, $4, $5)
                """,
                session_id, user_id, _assistant_content(card), language, domain,
            )
    log.info("turn_persisted", session_id=session_id, user_id=user_id, domain=domain)
