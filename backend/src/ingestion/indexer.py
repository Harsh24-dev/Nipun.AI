"""
Dual-write indexer — writes BGE-M3 dense+sparse vectors to Qdrant
and BM25-tokenised text to Elasticsearch simultaneously.
"""

import asyncio
import time
import uuid

import structlog
from qdrant_client.models import PointStruct, SparseVector

from src.config import settings
from src.core.metrics import DOCUMENTS_INDEXED, INGESTION_DURATION
from src.db.qdrant import get_qdrant
from src.ingestion.chunker import Chunk
from src.ingestion.parser import ParsedDocument
from src.language.constants import collection_name, es_index_name
from src.llm.embeddings import embed_texts_async

log = structlog.get_logger("ingestion.indexer")


async def _ensure_es_index(domain: str) -> None:
    from elasticsearch import AsyncElasticsearch
    es = AsyncElasticsearch(hosts=[settings.elasticsearch_url])
    try:
        index = es_index_name(domain)
        exists = await es.indices.exists(index=index)
        if not exists:
            await es.indices.create(
                index=index,
                body={
                    "mappings": {
                        # NOTE: index-time field `boost` was removed in Elasticsearch 8.x
                        # (it makes indices.create return 400). Relevance weighting is done
                        # at QUERY time instead — see the multi_match `title^3/section^3/
                        # keywords^2` boosts in retrieval/hybrid.py.
                        "properties": {
                            "title":    {"type": "text"},
                            "section":  {"type": "text"},
                            "content":  {"type": "text"},
                            "keywords": {"type": "text"},
                            "language": {"type": "keyword"},
                            "source":   {"type": "keyword"},
                            "domain":   {"type": "keyword"},
                            "date":     {"type": "date", "ignore_malformed": True},
                        }
                    },
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                },
            )
            log.info("es_index_created", index=index)
    finally:
        await es.close()


async def index_document(doc: ParsedDocument, chunks: list[Chunk]) -> int:
    """
    Embed all chunks with BGE-M3 and dual-write to Qdrant + Elasticsearch.
    Returns number of chunks indexed.
    """
    if not chunks:
        return 0

    start = time.perf_counter()
    texts = [c.text for c in chunks]

    log.info("indexing_start", title=doc.title, domain=doc.domain, chunks=len(chunks))

    # Step 1: Embed (BGE-M3 dense + sparse)
    embed_result = await embed_texts_async(texts)

    # Step 2: Parallel write to Qdrant + Elasticsearch
    qdrant_task = asyncio.create_task(_write_qdrant(doc, chunks, embed_result))
    es_task = asyncio.create_task(_write_elasticsearch(doc, chunks))

    qdrant_count, es_count = await asyncio.gather(qdrant_task, es_task, return_exceptions=True)

    if isinstance(qdrant_count, Exception):
        log.error("qdrant_write_failed", error=str(qdrant_count), doc=doc.title)
    if isinstance(es_count, Exception):
        log.warning("es_write_failed", error=str(es_count), doc=doc.title)

    duration_ms = (time.perf_counter() - start) * 1000
    DOCUMENTS_INDEXED.labels(domain=doc.domain, language=doc.language).inc(len(chunks))
    INGESTION_DURATION.labels(domain=doc.domain, stage="dual_write").observe(duration_ms)

    log.info(
        "indexing_complete",
        title=doc.title,
        domain=doc.domain,
        language=doc.language,
        chunks=len(chunks),
        duration_ms=round(duration_ms, 2),
    )
    return len(chunks)


async def _write_qdrant(doc: ParsedDocument, chunks: list[Chunk], embed_result) -> int:
    start = time.perf_counter()
    client = get_qdrant()
    coll = collection_name(doc.domain, doc.language)

    points = []
    for i, (chunk, dense_vec) in enumerate(zip(chunks, embed_result.dense)):
        sparse_dict = embed_result.sparse[i] if embed_result.sparse else {}
        sparse_indices = [int(k) for k in sparse_dict.keys()]
        sparse_values = list(sparse_dict.values())

        # Rich metadata (author/subject/level/book_id/license/visibility/kind) from the
        # source spec improves both citation quality and metadata-filtered retrieval.
        md = doc.metadata or {}
        payload = {
            "text": chunk.text,
            "title": doc.title,
            "source": md.get("source") or doc.title,
            "source_url": doc.source_url,
            "section": chunk.section or md.get("section"),
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "domain": doc.domain,
            "language": doc.language,
            "author": md.get("author", ""),
            "subject": md.get("subject", ""),
            "level": md.get("level", ""),
            "book_id": md.get("book_id", ""),
            "publication_year": md.get("publication_year"),
            "license": md.get("license", ""),
            "visibility": md.get("visibility", "public"),
            "kind": md.get("kind", "document"),
            "active": True,
        }
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": dense_vec,
                    "sparse": SparseVector(indices=sparse_indices, values=sparse_values),
                },
                payload={k: v for k, v in payload.items() if v not in (None, "")},
            )
        )

    batch_size = 100
    for i in range(0, len(points), batch_size):
        await client.upsert(collection_name=coll, points=points[i : i + batch_size])

    duration_ms = (time.perf_counter() - start) * 1000
    INGESTION_DURATION.labels(domain=doc.domain, stage="qdrant_write").observe(duration_ms)
    log.info("qdrant_write_complete", collection=coll, points=len(points), duration_ms=round(duration_ms, 2))
    return len(points)


async def _write_elasticsearch(doc: ParsedDocument, chunks: list[Chunk]) -> int:
    from elasticsearch import AsyncElasticsearch, helpers

    await _ensure_es_index(doc.domain)

    es = AsyncElasticsearch(hosts=[settings.elasticsearch_url])
    try:
        actions = [
            {
                "_index": es_index_name(doc.domain),
                "_source": {
                    "title": doc.title,
                    "section": chunk.section or "",
                    "content": chunk.text,
                    "language": doc.language,
                    "source": doc.source_url,
                    "domain": doc.domain,
                    "keywords": [],
                },
            }
            for chunk in chunks
        ]
        await helpers.async_bulk(es, actions)
        return len(actions)
    finally:
        await es.close()
