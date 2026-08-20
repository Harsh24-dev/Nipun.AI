"""
BGE-Reranker-v2-M3 — cross-encoder reranking for Indian languages.
Takes top-N retrieved passages and scores each (query, passage) pair.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import structlog

from src.config import settings
from src.core.metrics import RETRIEVAL_DURATION

log = structlog.get_logger("retrieval.reranker")

# Dedicated bounded pool so cross-encoder reranking runs off the event loop WITHOUT contending
# with local embedding (or other run_in_executor work) on the shared default pool.
_RERANK_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, settings.RERANK_EXECUTOR_WORKERS), thread_name_prefix="rerank")

# Hard ceiling for a single rerank pass. The reranker is a quality boost, not a correctness
# requirement, so a stuck model must not hold the request — on timeout we degrade to upstream
# order (see the except below).
_RERANK_TIMEOUT = 15


@lru_cache(maxsize=1)
def _get_reranker():
    from FlagEmbedding import FlagReranker

    from src.llm.embeddings import load_flag_model, resolve_device

    device = resolve_device(settings.RERANKER_DEVICE)
    log.info("loading_reranker", model=settings.RERANKER_MODEL, device=device)
    reranker = load_flag_model(
        FlagReranker, settings.RERANKER_MODEL, device, settings.EMBEDDING_USE_FP16)
    log.info("reranker_loaded", model=settings.RERANKER_MODEL, device=device)
    return reranker


def _rerank_sync(query: str, passages: list[str]) -> list[float]:
    reranker = _get_reranker()
    pairs = [[query, p] for p in passages]
    scores: list[float] = reranker.compute_score(pairs, normalize=True)
    return scores if isinstance(scores, list) else [scores]


async def rerank(
    query: str,
    passages: list[str],
    top_k: int | None = None,
) -> list[tuple[int, float]]:
    """
    Rerank passages against query.
    Returns list of (original_index, score) sorted by score descending.
    Takes top_k results.
    """
    if not passages:
        return []

    final_k = top_k or settings.RERANKER_TOP_K
    start = time.perf_counter()

    loop = asyncio.get_running_loop()
    try:
        # Hard ceiling so a model hang (stuck load/score) can't block the request forever.
        # A TimeoutError falls through to the same degrade-to-upstream-order fallback below.
        scores = await asyncio.wait_for(
            loop.run_in_executor(_RERANK_EXECUTOR, _rerank_sync, query, passages),
            timeout=_RERANK_TIMEOUT,
        )
    except Exception as exc:
        # The reranker is a QUALITY boost, not a correctness requirement. If the model
        # can't load/score (e.g. a transformers/tokenizer version mismatch), fall back to
        # the upstream retrieval order rather than dropping all results — a degraded rank
        # is far better than an empty answer.
        log.warning("rerank_unavailable_fallback", error=str(exc), input_count=len(passages))
        return [(i, 0.0) for i in range(min(final_k, len(passages)))]

    duration_ms = (time.perf_counter() - start) * 1000
    RETRIEVAL_DURATION.labels(stage="rerank").observe(duration_ms)

    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:final_k]

    log.info(
        "rerank_complete",
        input_count=len(passages),
        output_count=len(ranked),
        top_score=round(ranked[0][1], 4) if ranked else 0,
        duration_ms=round(duration_ms, 2),
    )

    return ranked
