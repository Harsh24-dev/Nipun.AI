"""
Long-term user memory — Claude/ChatGPT-style persistent facts about the user.

The assistant learns short, salient facts across conversations ("Preparing for UPSC 2026",
"Runs a dairy near Nashik", "Prefers concise answers in Hindi"), stores them durably with an
embedding, and semantically recalls the relevant ones into context on every turn. Memories
are de-duplicated on write (a near-identical existing memory is refreshed, not duplicated)
and are fully user-manageable (list / add / edit / delete) via the /memory API.

Distinct from episodic_memory (whole-session summaries) and user_profiles (fixed structured
columns that drive domain logic). This is the free-form "what I remember about you" store.

Every function is best-effort and never raises into the request path.
"""

from __future__ import annotations

import structlog

from src.config import settings

log = structlog.get_logger("memory.user")


def _vec(embedding: list[float] | None) -> str | None:
    if not embedding:
        return None
    return "[" + ",".join(str(x) for x in embedding) + "]"


async def _embed(text: str) -> list[float] | None:
    """Embed a memory string; None on any failure (memory still stored, recalled by recency)."""
    try:
        from src.llm.embeddings import embed_query_async

        result = await embed_query_async(text)
        return result.dense[0]
    except Exception as exc:
        log.warning("memory_embed_failed", error=str(exc))
        return None


async def add_memory(
    user_id: str,
    content: str,
    kind: str = "fact",
    session_id: str | None = None,
    pinned: bool = False,
    correlation_id: str = "",
) -> dict | None:
    """Store one memory, de-duplicating against existing ones. If a very similar memory
    already exists we refresh it (touch updated_at) instead of inserting a duplicate.
    Returns the stored/updated row as a dict, or None."""
    content = (content or "").strip()
    if not content or len(content) < 3:
        return None
    if kind not in ("fact", "preference", "goal", "context"):
        kind = "fact"
    embedding = await _embed(content)
    try:
        from src.db.postgres import execute, fetch, fetchrow

        # De-dup: is there a near-identical memory already? Prefer semantic match; fall back
        # to case-insensitive exact text when we have no embedding.
        if embedding is not None:
            dup = await fetchrow(
                """
                SELECT id, 1 - (embedding <=> $2::vector) AS similarity
                FROM user_memories
                WHERE user_id = $1::uuid AND embedding IS NOT NULL
                ORDER BY embedding <=> $2::vector
                LIMIT 1
                """,
                user_id, _vec(embedding),
            )
            if dup and float(dup["similarity"]) >= settings.MEMORY_DEDUP_SIMILARITY:
                await execute(
                    "UPDATE user_memories SET updated_at = NOW() WHERE id = $1", dup["id"]
                )
                log.info("memory_deduped", user_id=user_id, similarity=round(float(dup["similarity"]), 3),
                         correlation_id=correlation_id)
                return {"id": str(dup["id"]), "content": content, "kind": kind, "deduped": True}
        else:
            exact = await fetchrow(
                "SELECT id FROM user_memories WHERE user_id = $1::uuid AND lower(content) = lower($2) LIMIT 1",
                user_id, content,
            )
            if exact:
                await execute("UPDATE user_memories SET updated_at = NOW() WHERE id = $1", exact["id"])
                return {"id": str(exact["id"]), "content": content, "kind": kind, "deduped": True}

        row = await fetchrow(
            """
            INSERT INTO user_memories (user_id, content, kind, embedding, source_session, pinned)
            VALUES ($1::uuid, $2, $3, $4::vector, $5, $6)
            RETURNING id, content, kind, pinned, created_at
            """,
            user_id, content, kind, _vec(embedding),
            session_id if session_id else None, pinned,
        )
        # Enforce a soft cap: evict the oldest, unpinned memories beyond the limit.
        await _enforce_cap(user_id)
        log.info("memory_added", user_id=user_id, kind=kind, correlation_id=correlation_id)
        return {
            "id": str(row["id"]), "content": row["content"], "kind": row["kind"],
            "pinned": row["pinned"], "created_at": row["created_at"].isoformat(),
        }
    except Exception as exc:
        log.warning("memory_add_failed", user_id=user_id, error=str(exc), correlation_id=correlation_id)
        return None


async def _enforce_cap(user_id: str) -> None:
    """Keep at most MEMORY_MAX_PER_USER memories per user — evict the oldest UNPINNED first."""
    try:
        from src.db.postgres import execute

        await execute(
            """
            DELETE FROM user_memories
            WHERE id IN (
                SELECT id FROM user_memories
                WHERE user_id = $1::uuid AND pinned = FALSE
                ORDER BY updated_at DESC
                OFFSET $2
            )
            """,
            user_id, settings.MEMORY_MAX_PER_USER,
        )
    except Exception as exc:  # pragma: no cover
        log.debug("memory_cap_skip", error=str(exc))


async def recall_memories(
    user_id: str,
    query_embedding: list[float] | None,
    limit: int | None = None,
) -> list[dict]:
    """Return the memories most relevant to this turn: all pinned ones, plus the top
    semantically-similar memories (or most-recent when we have no query embedding).
    Best-effort — returns [] on any failure."""
    if not settings.MEMORY_ENABLED:
        return []
    limit = limit or settings.MEMORY_RECALL_LIMIT
    try:
        from src.db.postgres import fetch

        if query_embedding:
            rows = await fetch(
                """
                SELECT id, content, kind, pinned,
                       CASE WHEN embedding IS NULL THEN 0
                            ELSE 1 - (embedding <=> $2::vector) END AS similarity
                FROM user_memories
                WHERE user_id = $1::uuid
                ORDER BY pinned DESC,
                         CASE WHEN embedding IS NULL THEN 1 ELSE embedding <=> $2::vector END
                LIMIT $3
                """,
                user_id, _vec(query_embedding), limit,
            )
        else:
            rows = await fetch(
                """
                SELECT id, content, kind, pinned, 0 AS similarity
                FROM user_memories
                WHERE user_id = $1::uuid
                ORDER BY pinned DESC, updated_at DESC
                LIMIT $2
                """,
                user_id, limit,
            )
        return [
            {"id": str(r["id"]), "content": r["content"], "kind": r["kind"],
             "pinned": r["pinned"], "similarity": float(r["similarity"])}
            for r in rows
        ]
    except Exception as exc:
        log.warning("memory_recall_failed", user_id=user_id, error=str(exc))
        return []


async def list_memories(user_id: str) -> list[dict]:
    try:
        from src.db.postgres import fetch

        rows = await fetch(
            """
            SELECT id, content, kind, pinned, created_at, updated_at
            FROM user_memories WHERE user_id = $1::uuid
            ORDER BY pinned DESC, updated_at DESC
            """,
            user_id,
        )
        return [
            {"id": str(r["id"]), "content": r["content"], "kind": r["kind"],
             "pinned": r["pinned"], "created_at": r["created_at"].isoformat(),
             "updated_at": r["updated_at"].isoformat()}
            for r in rows
        ]
    except Exception as exc:
        log.warning("memory_list_failed", user_id=user_id, error=str(exc))
        return []


async def update_memory(user_id: str, memory_id: str, content: str | None = None,
                        pinned: bool | None = None) -> bool:
    """Edit a memory's text and/or pin state (re-embeds when text changes). Owner-scoped."""
    try:
        from src.db.postgres import execute

        if content is not None:
            content = content.strip()
            embedding = await _embed(content) if content else None
            result = await execute(
                """
                UPDATE user_memories
                SET content = $3, embedding = $4::vector,
                    pinned = COALESCE($5, pinned), updated_at = NOW()
                WHERE id = $1 AND user_id = $2::uuid
                """,
                memory_id, user_id, content, _vec(embedding), pinned,
            )
        else:
            result = await execute(
                "UPDATE user_memories SET pinned = COALESCE($3, pinned), updated_at = NOW() "
                "WHERE id = $1 AND user_id = $2::uuid",
                memory_id, user_id, pinned,
            )
        return result.endswith("1")
    except Exception as exc:
        log.warning("memory_update_failed", user_id=user_id, error=str(exc))
        return False


async def delete_memory(user_id: str, memory_id: str) -> bool:
    try:
        from src.db.postgres import execute

        result = await execute(
            "DELETE FROM user_memories WHERE id = $1 AND user_id = $2::uuid",
            memory_id, user_id,
        )
        return result.endswith("1")
    except Exception as exc:
        log.warning("memory_delete_failed", user_id=user_id, error=str(exc))
        return False


async def clear_memories(user_id: str) -> int:
    """Forget everything (user-initiated). Returns rows deleted."""
    try:
        from src.db.postgres import execute

        result = await execute("DELETE FROM user_memories WHERE user_id = $1::uuid", user_id)
        return int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0
    except Exception as exc:
        log.warning("memory_clear_failed", user_id=user_id, error=str(exc))
        return 0


def format_for_prompt(memories: list[dict]) -> str:
    """Render recalled memories as a compact prompt block, or '' when there are none."""
    items = [m.get("content", "").strip() for m in memories if m.get("content")]
    items = [i for i in items if i]
    if not items:
        return ""
    lines = "\n".join(f"- {i}" for i in items)
    return (
        "\n\nWHAT YOU REMEMBER ABOUT THIS USER (from past conversations — use it to "
        "personalize and avoid re-asking; do not recite it back verbatim):\n" + lines + "\n"
    )
