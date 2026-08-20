"""
Embedding abstraction — BGE-M3 (local) or API providers.
Switch via EMBEDDING_PROVIDER in .env.

BGE-M3 outputs:
  dense_vecs    : (n, 1024) float32  — semantic similarity
  lexical_weights: list[dict]        — sparse token weights (replaces BM25)
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any

import numpy as np
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.core.metrics import RETRIEVAL_DURATION

log = structlog.get_logger("llm.embeddings")

# Dedicated bounded pool for CPU/GPU-bound local embedding, so a big batch embed can't starve a
# query embed (and neither contends with the reranker or other run_in_executor work on the shared
# default pool). Kept small — the model saturates the device with a couple of workers.
_EMBED_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, settings.EMBED_EXECUTOR_WORKERS), thread_name_prefix="embed")

# Hard per-call ceiling for an external embedding API request (Cohere/OpenAI). Kept short so a
# hung provider can't stall the retrieval hot path; a straggler is retried, then surfaced as an
# error to the caller rather than blocking indefinitely.
_EMBED_API_TIMEOUT = 15

# Transient-error retry mirroring llm/client.py: 3 attempts with exponential backoff. Retrying
# on Exception covers provider 5xx/rate-limit/timeout without needing per-SDK error classes; a
# genuinely fatal error (e.g. bad key) simply exhausts the 3 attempts and reraises.
_embed_api_retry = retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)


class EmbeddingResult:
    def __init__(
        self,
        dense: list[list[float]],
        sparse: list[dict[str, float]] | None = None,
    ):
        self.dense = dense          # shape: (n, dim)
        self.sparse = sparse        # list of {token_id: weight} dicts, or None for API providers


# ── Device selection (GPU when available) ─────────────────────────────────────

def resolve_device(pref: str = "auto") -> str:
    """Resolve a device preference to 'cuda' or 'cpu'. 'auto' → GPU if torch sees one."""
    pref = (pref or "auto").lower()
    if pref == "cpu":
        return "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def load_flag_model(cls, model_name: str, device: str, use_fp16: bool):
    """Construct a FlagEmbedding model on the chosen device, tolerant of the param name
    changing across versions ('devices' vs 'device'), and falling back to auto-detection."""
    common = dict(use_fp16=use_fp16, cache_dir=settings.EMBEDDING_MODEL_CACHE)
    for key in ("devices", "device"):
        try:
            return cls(model_name, **{key: device}, **common)
        except TypeError:
            continue
    return cls(model_name, **common)   # older API: relies on auto-detection


# ── Local BGE-M3 (recommended) ────────────────────────────────────────────────

class LocalBGEM3Embedder:
    """BAAI/bge-m3 via FlagEmbedding — best for Indian languages."""

    def __init__(self) -> None:
        from FlagEmbedding import BGEM3FlagModel

        device = resolve_device(settings.EMBEDDING_DEVICE)
        log.info("loading_embedding_model", model=settings.EMBEDDING_MODEL, device=device)
        self._model = load_flag_model(
            BGEM3FlagModel, settings.EMBEDDING_MODEL, device, settings.EMBEDDING_USE_FP16)
        log.info("embedding_model_loaded", model=settings.EMBEDDING_MODEL, device=device)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        start = time.perf_counter()

        output = self._model.encode(
            texts,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            max_length=8192,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

        duration_ms = (time.perf_counter() - start) * 1000
        RETRIEVAL_DURATION.labels(stage="embed").observe(duration_ms)

        log.info(
            "embeddings_generated",
            count=len(texts),
            provider="local",
            model=settings.EMBEDDING_MODEL,
            duration_ms=round(duration_ms, 2),
        )

        dense = output["dense_vecs"].tolist()
        sparse = [dict(lw) for lw in output["lexical_weights"]]
        return EmbeddingResult(dense=dense, sparse=sparse)

    def embed_query(self, query: str) -> EmbeddingResult:
        # BGE-M3 uses same encoding for queries and passages
        return self.embed([query])


# ── Cohere API embedder ───────────────────────────────────────────────────────

class CohereEmbedder:
    def __init__(self) -> None:
        import cohere
        self._client = cohere.AsyncClientV2(api_key=settings.COHERE_API_KEY)
        self._model = settings.EMBEDDING_MODEL  # embed-multilingual-v3.0

    @_embed_api_retry
    async def embed(self, texts: list[str], input_type: str = "search_document") -> EmbeddingResult:
        # asyncio.wait_for is the hard ceiling (the cohere AsyncClientV2 doesn't take a plain
        # `timeout=` kwarg on embed, so we don't pass one to avoid a TypeError). Retry wraps this.
        response = await asyncio.wait_for(
            self._client.embed(
                texts=texts,
                model=self._model,
                input_type=input_type,
                embedding_types=["float"],
            ),
            timeout=_EMBED_API_TIMEOUT,
        )
        dense = response.embeddings.float_
        return EmbeddingResult(dense=dense, sparse=None)

    async def embed_query(self, query: str) -> EmbeddingResult:
        return await self.embed([query], input_type="search_query")


# ── OpenAI API embedder ───────────────────────────────────────────────────────

class OpenAIEmbedder:
    def __init__(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.EMBEDDING_MODEL  # text-embedding-3-large

    @_embed_api_retry
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        # The OpenAI SDK accepts a per-request `timeout=`; asyncio.wait_for is a hard outer
        # ceiling in case the SDK's own timeout doesn't fire. Retry wraps both.
        response = await asyncio.wait_for(
            self._client.embeddings.create(
                input=texts,
                model=self._model,
                timeout=_EMBED_API_TIMEOUT,
            ),
            timeout=_EMBED_API_TIMEOUT,
        )
        dense = [item.embedding for item in response.data]
        return EmbeddingResult(dense=dense, sparse=None)

    async def embed_query(self, query: str) -> EmbeddingResult:
        return await self.embed([query])


# ── Factory ───────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_embedder() -> LocalBGEM3Embedder | CohereEmbedder | OpenAIEmbedder:
    provider = settings.EMBEDDING_PROVIDER
    if provider == "local":
        return LocalBGEM3Embedder()
    if provider == "cohere":
        return CohereEmbedder()
    if provider == "openai":
        return OpenAIEmbedder()
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider}. Use: local | cohere | openai")


def embed_texts(texts: list[str]) -> EmbeddingResult:
    """Sync wrapper — works for local provider only."""
    embedder = get_embedder()
    if not isinstance(embedder, LocalBGEM3Embedder):
        raise RuntimeError("Use async embed_texts_async for API-based providers")
    return embedder.embed(texts)


def embed_query(query: str) -> EmbeddingResult:
    """Embed a single query (sync, local only)."""
    embedder = get_embedder()
    if not isinstance(embedder, LocalBGEM3Embedder):
        raise RuntimeError("Use async version for API-based providers")
    return embedder.embed_query(query)


async def embed_texts_async(texts: list[str]) -> EmbeddingResult:
    """Async embedding — works for all providers."""
    embedder = get_embedder()
    if isinstance(embedder, LocalBGEM3Embedder):
        # Run CPU-bound embedding in the DEDICATED pool so it never blocks the event loop or
        # contends with the reranker on the default executor.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_EMBED_EXECUTOR, embedder.embed, texts)
    return await embedder.embed(texts)  # type: ignore[union-attr]


# Small bounded cache of recent query embeddings. Embedding a given text is deterministic
# for a fixed model, so reusing the result for an identical query string is always correct.
# This removes the redundant re-embed on the hot path (the orchestrator embeds the query in
# node_embed_query, then hybrid.retrieve embeds the same text again when retrieval_query
# equals the query) at zero quality cost. Keyed by (provider, text); FIFO-evicted.
from collections import OrderedDict as _OrderedDict

_QUERY_EMBED_CACHE: "_OrderedDict[tuple[str, str], EmbeddingResult]" = _OrderedDict()
_QUERY_EMBED_CACHE_MAX = 256


async def embed_query_async(query: str) -> EmbeddingResult:
    """Async single-query embedding — works for all providers. Cached per query text."""
    cache_key = (settings.EMBEDDING_PROVIDER, query)
    cached = _QUERY_EMBED_CACHE.get(cache_key)
    if cached is not None:
        _QUERY_EMBED_CACHE.move_to_end(cache_key)
        return cached

    embedder = get_embedder()
    if isinstance(embedder, LocalBGEM3Embedder):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(_EMBED_EXECUTOR, embedder.embed_query, query)
    else:
        result = await embedder.embed_query(query)  # type: ignore[union-attr]

    _QUERY_EMBED_CACHE[cache_key] = result
    _QUERY_EMBED_CACHE.move_to_end(cache_key)
    if len(_QUERY_EMBED_CACHE) > _QUERY_EMBED_CACHE_MAX:
        _QUERY_EMBED_CACHE.popitem(last=False)
    return result
