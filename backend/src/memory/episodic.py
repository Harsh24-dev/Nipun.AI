"""
L4 — Episodic Memory (Postgres + pgvector).
Stores LLM-generated summaries of past sessions, searchable by vector similarity.
"""

import time
from uuid import UUID

import structlog

from src.db.postgres import execute, fetch, fetchrow
from src.core.metrics import MEMORY_ASSEMBLY_DURATION

log = structlog.get_logger("memory.episodic")


async def save_episode(
    user_id: str,
    session_id: str,
    summary: str,
    embedding: list[float],
    domain: str | None = None,
    language: str = "en",
) -> None:
    """Save a session summary with its embedding for future recall."""
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    await execute(
        """
        INSERT INTO episodic_memory (user_id, session_id, summary, embedding, domain, language)
        VALUES ($1::uuid, $2::uuid, $3, $4::vector, $5, $6)
        """,
        user_id, session_id, summary, embedding_str, domain, language,
    )
    log.info("episode_saved", user_id=user_id, domain=domain, summary_length=len(summary))


async def recall_episodes(
    user_id: str,
    query_embedding: list[float],
    limit: int = 5,
    domain: str | None = None,
) -> list[dict]:
    """
    Retrieve the most semantically relevant past episodes.
    Uses pgvector cosine distance for ANN search.
    """
    start = time.perf_counter()

    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    if domain:
        rows = await fetch(
            """
            SELECT id, summary, domain, language, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM episodic_memory
            WHERE user_id = $2::uuid AND domain = $3
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            embedding_str, user_id, domain, limit,
        )
    else:
        rows = await fetch(
            """
            SELECT id, summary, domain, language, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM episodic_memory
            WHERE user_id = $2::uuid
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            embedding_str, user_id, limit,
        )

    duration_ms = (time.perf_counter() - start) * 1000
    MEMORY_ASSEMBLY_DURATION.observe(duration_ms)

    results = [
        {
            "id": str(row["id"]),
            "summary": row["summary"],
            "domain": row["domain"],
            "language": row["language"],
            "created_at": row["created_at"].isoformat(),
            "similarity": float(row["similarity"]),
        }
        for row in rows
    ]

    log.info(
        "episodes_recalled",
        user_id=user_id,
        domain=domain,
        count=len(results),
        duration_ms=round(duration_ms, 2),
    )
    return results


async def list_recent_episodes(user_id: str, days: int = 7) -> list[dict]:
    rows = await fetch(
        """
        SELECT id, summary, domain, language, created_at
        FROM episodic_memory
        WHERE user_id = $1::uuid AND created_at > NOW() - ($2 || ' days')::interval
        ORDER BY created_at DESC
        LIMIT 20
        """,
        user_id, str(days),
    )
    return [
        {
            "id": str(row["id"]),
            "summary": row["summary"],
            "domain": row["domain"],
            "language": row["language"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
