"""
Context Assembler — merges all memory tiers into a single context dict.
Target: <35ms total (L0+L1+L2 are sub-ms, L3+L4 run in parallel ~20-30ms).
"""

import asyncio
import time
from dataclasses import dataclass

import structlog

from src.config import settings
from src.core.logging import trace_flow
from src.core.metrics import MEMORY_ASSEMBLY_DURATION
from src.memory.working import get_working_memory
from src.memory.session import get_session, load_profile, semantic_cache_get
from src.memory.episodic import recall_episodes

log = structlog.get_logger("memory.context")


@dataclass
class AssembledContext:
    working_memory: list[dict]          # last N turns as LLM messages
    user_profile: dict                  # user preferences, location, crops etc.
    session: dict                       # current session metadata
    episodic_context: list[dict]        # relevant past session summaries
    user_memories: list[dict]           # long-term learned facts (Claude/GPT-style)
    token_estimate: int                 # rough token count of context
    assembly_ms: float


async def assemble_context(
    session_id: str,
    user_id: str,
    query_embedding: list[float],
    domain: str | None = None,
    correlation_id: str = "",
) -> AssembledContext:
    """
    Fetch and merge all memory tiers in parallel where possible.
    L0 (working memory) is synchronous — zero cost.
    L2 (session + profile) and L4 (episodic) run in parallel.
    """
    start = time.perf_counter()

    # L0 — in-process, instant
    wm = get_working_memory()
    working_turns = wm.to_llm_messages(session_id)

    # L2 + L4 — parallel async fetches
    session_task = asyncio.create_task(get_session(user_id))
    profile_task = asyncio.create_task(load_profile(user_id))
    episodic_task = asyncio.create_task(
        recall_episodes(
            user_id=user_id,
            query_embedding=query_embedding,
            limit=settings.EPISODIC_MEMORY_RECALL_LIMIT,
            domain=domain,
        )
    )
    # Long-term learned memories relevant to this turn (Claude/GPT-style personalization).
    from src.memory.user_memory import recall_memories

    memory_task = asyncio.create_task(
        recall_memories(user_id=user_id, query_embedding=query_embedding)
    )

    session_data, profile_data, episodes, memories = await asyncio.gather(
        session_task, profile_task, episodic_task, memory_task, return_exceptions=True
    )

    # Handle partial failures gracefully
    if isinstance(session_data, Exception):
        log.warning("session_fetch_failed", error=str(session_data))
        session_data = {}
    if isinstance(profile_data, Exception):
        log.warning("profile_fetch_failed", error=str(profile_data))
        profile_data = {}
    if isinstance(episodes, Exception):
        log.warning("episodic_fetch_failed", error=str(episodes))
        episodes = []
    if isinstance(memories, Exception):
        log.warning("memory_fetch_failed", error=str(memories))
        memories = []

    duration_ms = (time.perf_counter() - start) * 1000
    MEMORY_ASSEMBLY_DURATION.observe(duration_ms)

    # Rough token estimate (4 chars ≈ 1 token)
    context_text = " ".join(
        [t.get("content", "") for t in working_turns]
        + [e.get("summary", "") for e in (episodes or [])]
    )
    token_estimate = len(context_text) // 4

    log.info(
        "context_assembled",
        user_id=user_id,
        working_turns=len(working_turns),
        episodes=len(episodes or []),
        memories=len(memories or []),
        token_estimate=token_estimate,
        duration_ms=round(duration_ms, 2),
        correlation_id=correlation_id,
    )
    # Flow trace: the ACTUAL memory content fed into the prompt this turn.
    trace_flow(
        "context_assembled",
        correlation_id=correlation_id,
        user_id=user_id,
        domain=domain,
        working_memory=working_turns,
        user_profile=profile_data or {},
        episodic_context=[e.get("summary", "") for e in (episodes or [])],
        token_estimate=token_estimate,
    )

    return AssembledContext(
        working_memory=working_turns,
        user_profile=profile_data or {},
        session=session_data or {},
        episodic_context=episodes or [],
        user_memories=memories or [],
        token_estimate=token_estimate,
        assembly_ms=duration_ms,
    )
