"""
Hybrid Retrieval Pipeline — BGE-M3 dense+sparse in Qdrant + Elasticsearch exact-match.

Flow:
  1. Embed query with BGE-M3 (dense + sparse vectors)
  2. Parallel: Qdrant hybrid search + Elasticsearch exact-match
  3. RRF fusion of both result lists
  4. BGE-reranker-v2-m3 reranks top candidates
  5. Return top-K with citations
"""

import asyncio
import re
import time
from dataclasses import dataclass, field

import structlog
from elasticsearch import AsyncElasticsearch
from qdrant_client.models import (
    QuantizationSearchParams,
    QueryRequest,
    SearchParams,
    SparseVector,
)

from src.config import settings
from src.core.logging import trace_flow
from src.core.metrics import RETRIEVAL_DURATION, RETRIEVAL_TOTAL
from src.db.qdrant import get_qdrant
from src.language.constants import collection_name, es_index_name
from src.llm.embeddings import embed_query_async

log = structlog.get_logger("retrieval.hybrid")

# Pooled Elasticsearch client — reused across queries instead of constructing (and closing)
# a new AsyncElasticsearch on every exact-match search. Created lazily; closed on shutdown.
_es_client: AsyncElasticsearch | None = None


def _get_es() -> AsyncElasticsearch:
    global _es_client
    if _es_client is None:
        _es_client = AsyncElasticsearch(
            hosts=[settings.elasticsearch_url],
            basic_auth=(settings.ELASTICSEARCH_USERNAME, settings.ELASTICSEARCH_PASSWORD)
            if settings.ELASTICSEARCH_USERNAME else None,
        )
    return _es_client


async def close_elasticsearch() -> None:
    """Close the pooled Elasticsearch client (called on app shutdown)."""
    global _es_client
    if _es_client is not None:
        await _es_client.close()
    _es_client = None


# ── Exact-match identifier patterns ──────────────────────────────────────────
_IDENTIFIER_PATTERNS = [
    re.compile(r"\bSection\s+\d+[A-Z]?\b", re.IGNORECASE),
    re.compile(r"\bधारा\s+\d+\b"),
    re.compile(r"\bPM[-\s]\w+\b"),
    re.compile(r"\bIPC\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bCrPC\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{2,}-\d{4,}\b"),       # case numbers like WP-12345
]


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source: str
    source_url: str
    section: str | None
    domain: str
    language: str
    relevance_score: float
    retrieval_method: str   # "dense" | "sparse" | "hybrid" | "exact"
    metadata: dict = field(default_factory=dict)


def _has_identifiers(query: str) -> bool:
    return any(p.search(query) for p in _IDENTIFIER_PATTERNS)


def _compute_rrf_scores(
    dense_results: list[tuple[str, float]],
    sparse_results: list[tuple[str, float]],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion — merges two ranked lists."""
    scores: dict[str, float] = {}
    for rank, (chunk_id, _) in enumerate(dense_results):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank + 1)
    for rank, (chunk_id, _) in enumerate(sparse_results):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank + 1)
    return scores


async def _qdrant_hybrid_search(
    query_dense: list[float],
    query_sparse: dict[str, float],
    collection: str,
    top_k: int,
    query_filter=None,
) -> list[tuple[str, float, dict]]:
    """Run dense+sparse hybrid search using query_batch_points (qdrant-client 1.7+).
    `query_filter` (a Qdrant Filter) scopes the search — used for RBAC (owner_id) and
    metadata routing (book_id/subject/level). Returns [] if the collection is missing."""
    start = time.perf_counter()
    client = get_qdrant()

    sparse_indices = [int(k) for k in query_sparse]
    sparse_values = list(query_sparse.values())

    # With int8 quantization enabled, rescore the oversampled candidate set against
    # full-precision dense vectors so recall stays close to un-quantized search.
    dense_params = None
    if settings.QDRANT_QUANTIZATION_ENABLED:
        dense_params = SearchParams(
            quantization=QuantizationSearchParams(
                rescore=True,
                oversampling=settings.QDRANT_RESCORE_OVERSAMPLING,
            )
        )

    requests = [
        QueryRequest(
            query=query_dense,
            using="dense",
            limit=top_k,
            with_payload=True,
            params=dense_params,
            filter=query_filter,
        ),
    ]
    # Only add sparse search if we have sparse vectors (API embedders return None)
    if sparse_indices:
        requests.append(
            QueryRequest(
                query=SparseVector(indices=sparse_indices, values=sparse_values),
                using="sparse",
                limit=top_k,
                with_payload=True,
                filter=query_filter,
            )
        )

    try:
        batch_results = await client.query_batch_points(
            collection_name=collection,
            requests=requests,
        )
    except Exception as exc:
        # A missing/empty language collection must not fail the whole cross-lingual search.
        log.debug("qdrant_collection_search_skipped", collection=collection, error=str(exc))
        return []

    duration_ms = (time.perf_counter() - start) * 1000
    RETRIEVAL_DURATION.labels(stage="dense").observe(duration_ms)
    log.debug("qdrant_search_complete", collection=collection, duration_ms=round(duration_ms, 2))

    # Merge results from all requests: last-write-wins on score ties, keep highest
    seen: dict[str, tuple[float, dict]] = {}
    for response in batch_results:
        for hit in response.points:
            cid = str(hit.id)
            if cid not in seen or hit.score > seen[cid][0]:
                seen[cid] = (hit.score, hit.payload or {})

    return [(cid, score, payload) for cid, (score, payload) in seen.items()]


async def _elasticsearch_exact_search(
    query: str,
    domain: str,
    language: str,
    top_k: int,
) -> list[tuple[str, float, dict]]:
    """BM25 keyword search in Elasticsearch — best for identifiers."""
    start = time.perf_counter()

    es = _get_es()   # pooled client — do NOT close per call
    index = es_index_name(domain)
    # Cross-lingual: don't restrict identifier matches to the query language (an
    # English "Section 302" should match even when the question is in Hindi).
    bool_query: dict = {
        "must": {
            "multi_match": {
                "query": query,
                "fields": ["title^3", "section^3", "content^1", "keywords^2"],
                "type": "best_fields",
            }
        }
    }
    if not settings.CROSS_LINGUAL_RETRIEVAL:
        bool_query["filter"] = [{"term": {"language": language.split('+')[0]}}]
    response = await es.search(index=index, body={"query": {"bool": bool_query}, "size": top_k})

    duration_ms = (time.perf_counter() - start) * 1000
    RETRIEVAL_DURATION.labels(stage="sparse").observe(duration_ms)
    log.info("es_search_complete", index=index, duration_ms=round(duration_ms, 2))

    hits = response["hits"]["hits"]
    return [
        (
            hit["_id"],
            hit["_score"],
            hit["_source"],
        )
        for hit in hits
    ]


async def retrieve(
    query: str,
    language: str,
    domain: str,
    top_k: int | None = None,
    correlation_id: str = "",
    filters: dict | None = None,
) -> list[RetrievedChunk]:
    """
    Full hybrid retrieval pipeline.
    Returns top_k chunks after embedding, dual-search, RRF, and reranking.

    One collection per domain holds ALL languages, so retrieval is a SINGLE ANN search
    that is cross-lingual by construction (BGE-M3 shares one embedding space; the reranker
    is multilingual) — a query in one language can be answered from documents in another.
    `filters` scopes results by rich metadata (book_id / subject / level). When
    CROSS_LINGUAL_RETRIEVAL is off, a `language` filter restricts to the query language.
    """
    from src.db.qdrant import build_filter

    start = time.perf_counter()
    final_k = top_k or settings.RETRIEVAL_FINAL_TOP_K
    use_exact = _has_identifiers(query)
    collection = collection_name(domain)

    eff_filters = dict(filters or {})
    if not settings.CROSS_LINGUAL_RETRIEVAL:
        eff_filters["language"] = language.split("+")[0]
    query_filter = build_filter(eff_filters)

    log.info(
        "retrieval_start",
        query_preview=query[:80],
        domain=domain,
        language=language,
        collection=collection,
        cross_lingual=settings.CROSS_LINGUAL_RETRIEVAL,
        use_exact=use_exact,
        filters=eff_filters or None,
        correlation_id=correlation_id,
    )

    # Step 1: Embed query (dense + sparse from BGE-M3)
    embed_result = await embed_query_async(query)
    dense_vec = embed_result.dense[0]
    sparse_vec: dict[str, float] = embed_result.sparse[0] if embed_result.sparse else {}

    # Step 2: ONE hybrid search over the domain collection (all languages), plus optional
    # ES exact-match for identifiers (Section 302, PM-KISAN, …).
    qdrant_task = asyncio.create_task(
        _qdrant_hybrid_search(dense_vec, sparse_vec, collection,
                              top_k=settings.RETRIEVAL_DENSE_TOP_K, query_filter=query_filter)
    )
    if use_exact:
        es_task = asyncio.create_task(
            _elasticsearch_exact_search(query, domain, language, top_k=settings.RETRIEVAL_SPARSE_TOP_K)
        )
        qdrant_hits, es_hits = await asyncio.gather(qdrant_task, es_task, return_exceptions=True)
    else:
        qdrant_hits = await qdrant_task
        es_hits = []

    if isinstance(qdrant_hits, Exception):
        log.warning("qdrant_search_failed", error=str(qdrant_hits))
        qdrant_hits = []
    if isinstance(es_hits, Exception):
        log.warning("es_search_failed", error=str(es_hits))
        es_hits = []

    # Step 3: RRF fusion
    qdrant_ranked = [(h[0], h[1]) for h in qdrant_hits]
    es_ranked = [(h[0], h[1]) for h in es_hits]
    rrf_scores = _compute_rrf_scores(qdrant_ranked, es_ranked, k=settings.RETRIEVAL_RRF_K)

    # Merge payloads
    all_payloads: dict[str, dict] = {}
    for cid, score, payload in qdrant_hits:
        all_payloads[cid] = payload
    for cid, score, payload in es_hits:
        if cid not in all_payloads:
            all_payloads[cid] = payload

    # Sort by RRF score, take reranker candidates
    sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)  # type: ignore
    candidate_ids = sorted_ids[:settings.RERANKER_CANDIDATES]

    # Step 4: Rerank
    from src.retrieval.reranker import rerank

    candidate_texts = [all_payloads.get(cid, {}).get("text", "") for cid in candidate_ids]
    reranked = await rerank(query=query, passages=candidate_texts, top_k=final_k)

    # Step 5: Build result objects (each chunk reports its OWN language, not the query's).
    results: list[RetrievedChunk] = []
    for rank_idx, score in reranked:
        cid = candidate_ids[rank_idx]
        payload = all_payloads.get(cid, {})
        results.append(
            RetrievedChunk(
                chunk_id=cid,
                text=payload.get("text", ""),
                source=payload.get("source", ""),
                source_url=payload.get("source_url", ""),
                section=payload.get("section"),
                domain=domain,
                language=payload.get("language", language),
                relevance_score=score,
                retrieval_method="cross_lingual" if settings.CROSS_LINGUAL_RETRIEVAL else "hybrid",
                metadata=payload,
            )
        )

    total_ms = (time.perf_counter() - start) * 1000
    RETRIEVAL_TOTAL.labels(domain=domain, language=language, method="hybrid").inc()
    RETRIEVAL_DURATION.labels(stage="total").observe(total_ms)

    # Flow trace: which documents/sources were actually returned, with scores + language.
    trace_flow(
        "retrieval_results",
        correlation_id=correlation_id,
        query=query,
        domain=domain,
        query_language=language,
        collection=collection,
        qdrant_hits=len(qdrant_hits),
        es_hits=len(es_hits),
        final=[
            {"chunk_id": r.chunk_id, "source": r.source, "source_url": r.source_url,
             "section": r.section, "lang": r.language, "score": round(r.relevance_score, 4),
             "method": r.retrieval_method, "text": (r.text or "")[:300]}
            for r in results
        ],
    )

    if total_ms > settings.RETRIEVAL_SLOW_QUERY_MS:
        log.warning(
            "slow_retrieval",
            domain=domain,
            total_ms=round(total_ms, 2),
            correlation_id=correlation_id,
        )
    else:
        log.info(
            "retrieval_complete",
            domain=domain,
            language=language,
            candidates=len(candidate_ids),
            final_count=len(results),
            total_ms=round(total_ms, 2),
            correlation_id=correlation_id,
        )

    return results


async def retrieve_user_document(
    query: str,
    owner_id: str,
    language: str = "en",
    document_id: str | None = None,
    session_id: str | None = None,
    top_k: int | None = None,
    correlation_id: str = "",
) -> list[RetrievedChunk]:
    """Retrieve ONLY from a user's private uploaded documents.

    RBAC is enforced at the vector layer: the owner_id filter is ALWAYS applied, so a
    user can never retrieve another user's chunks — a bug in an endpoint cannot leak
    data. `document_id` scopes to a single uploaded doc ("answer from this doc only");
    `session_id` scopes to the docs uploaded in one chat session. All languages live in
    the single user_documents collection, so an English/Tamil upload can answer a
    Hindi/Marathi question in one cross-lingual search.
    """
    from src.db.qdrant import build_filter, user_collection_name

    if not owner_id:
        return []
    start = time.perf_counter()
    final_k = top_k or settings.RETRIEVAL_FINAL_TOP_K

    flt = build_filter({"owner_id": owner_id, "document_id": document_id,
                        "session_id": session_id, "active": True})

    embed_result = await embed_query_async(query)
    dense_vec = embed_result.dense[0]
    sparse_vec: dict[str, float] = embed_result.sparse[0] if embed_result.sparse else {}

    # Single search over the shared user_documents collection (owner-filtered).
    hits = await _qdrant_hybrid_search(dense_vec, sparse_vec, user_collection_name(),
                                       top_k=settings.RETRIEVAL_DENSE_TOP_K, query_filter=flt)

    all_payloads = {cid: payload for cid, _score, payload in hits}
    ranked = sorted(hits, key=lambda h: h[1], reverse=True)[: settings.RERANKER_CANDIDATES]
    candidate_ids = [cid for cid, _s, _p in ranked]

    from src.retrieval.reranker import rerank

    candidate_texts = [all_payloads.get(cid, {}).get("text", "") for cid in candidate_ids]
    reranked = await rerank(query=query, passages=candidate_texts, top_k=final_k)

    results = []
    for rank_idx, score in reranked:
        cid = candidate_ids[rank_idx]
        payload = all_payloads.get(cid, {})
        results.append(RetrievedChunk(
            chunk_id=cid, text=payload.get("text", ""),
            source=payload.get("title") or payload.get("source", "Your document"),
            source_url=payload.get("source_url", ""), section=payload.get("section"),
            domain="user_documents", language=payload.get("language", language),
            relevance_score=score, retrieval_method="user_doc", metadata=payload,
        ))

    trace_flow("user_doc_retrieval", correlation_id=correlation_id, owner_id=owner_id,
               document_id=document_id, session_id=session_id,
               results=len(results), sources=[r.source for r in results])
    log.info("user_doc_retrieval_complete", owner_id=owner_id, document_id=document_id,
             results=len(results), total_ms=round((time.perf_counter() - start) * 1000, 2),
             correlation_id=correlation_id)
    return results
