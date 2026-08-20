"""
Qdrant client — manages collections for BGE-M3 dense + sparse vectors.
One collection per domain+language: e.g. legal_hi, farming_mr, scheme_ta
"""

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

from src.config import settings
from src.language.constants import LANGUAGES, SUPPORTED_DOMAINS

log = structlog.get_logger("db.qdrant")

_client: AsyncQdrantClient | None = None

# Private per-user upload space — a SINGLE collection for all users and languages.
# RBAC is enforced by ALWAYS filtering on owner_id (a user can never retrieve another
# user's chunks); owner_id is a tenant-partition key for on-disk locality.
USER_DOCS_COLLECTION = "user_documents"

# Payload keys we allow as retrieval filters (metadata routing / isolation).
_FILTER_KEYS = ("owner_id", "document_id", "session_id", "book_id", "domain", "subject",
                "level", "author", "visibility", "language", "active")

# Indexed payload fields per collection (enable fast filtered ANN / routing).
_CORPUS_INDEXES = (("source", "keyword"), ("language", "keyword"), ("subject", "keyword"),
                   ("level", "keyword"), ("book_id", "keyword"), ("visibility", "keyword"),
                   ("active", "bool"))
_USERDOC_INDEXES = (("owner_id", "keyword"), ("document_id", "keyword"),
                    ("session_id", "keyword"), ("language", "keyword"),
                    ("subject", "keyword"), ("level", "keyword"), ("active", "bool"))


def user_collection_name(lang: str | None = None) -> str:
    """The single private user-documents collection (language is a payload field)."""
    return USER_DOCS_COLLECTION


def build_filter(filters: dict | None) -> Filter | None:
    """Turn a {field: value | [values]} dict into a Qdrant `must` Filter.
    Only whitelisted metadata keys are honoured. Returns None if nothing to filter."""
    if not filters:
        return None
    must = []
    for key, value in filters.items():
        if key not in _FILTER_KEYS or value in (None, "", []):
            continue
        if isinstance(value, (list, tuple, set)):
            must.append(FieldCondition(key=key, match=MatchAny(any=list(value))))
        else:
            must.append(FieldCondition(key=key, match=MatchValue(value=value)))
    return Filter(must=must) if must else None


def _quantization_config() -> ScalarQuantization | None:
    """
    TurboQuant: int8 scalar quantization keeps ~4x less memory. Search fetches an
    oversampled candidate set from the quantized index, then rescores the top ones
    against full-precision vectors — recall stays close to un-quantized. Toggle via
    QDRANT_QUANTIZATION_ENABLED (default on).
    """
    if not settings.QDRANT_QUANTIZATION_ENABLED:
        return None
    return ScalarQuantization(
        scalar=ScalarQuantizationConfig(
            type=ScalarType.INT8,
            always_ram=settings.QDRANT_QUANTIZATION_ALWAYS_RAM,
        )
    )


async def init_qdrant() -> None:
    global _client
    log.debug(f"Connecting to Qdrant  host={settings.QDRANT_HOST}  port={settings.QDRANT_PORT}")
    _client = AsyncQdrantClient(
        url=f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}",
        api_key=settings.QDRANT_API_KEY or None,
        timeout=30,
    )
    await _ensure_collections()
    log.info(f"Qdrant connected  host={settings.QDRANT_HOST}  port={settings.QDRANT_PORT}")


def get_qdrant() -> AsyncQdrantClient:
    if _client is None:
        raise RuntimeError("Qdrant not initialised. Call init_qdrant() first.")
    return _client


async def _create_collection(name: str, indexes) -> None:
    """Create one hybrid (dense+sparse) collection + its payload indexes (idempotent)."""
    client = get_qdrant()
    quant = _quantization_config()
    await client.create_collection(
        collection_name=name,
        vectors_config={"dense": VectorParams(size=settings.EMBEDDING_DIM,
                                              distance=Distance.COSINE, on_disk=False)},
        sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
        optimizers_config={"indexing_threshold": 10000},
        quantization_config=quant,
    )
    for field, ftype in indexes:
        try:
            await client.create_payload_index(name, field, ftype)
        except Exception as exc:   # index may already exist on a partially-created collection
            log.debug("payload_index_skipped", collection=name, field=field, error=str(exc))
    log.info(f"Collection created  name={name}  quantization={'int8' if quant else 'off'}")


async def _dense_dim(name: str) -> int | None:
    """Current dense-vector size of an existing collection, or None if unknown."""
    try:
        info = await get_qdrant().get_collection(name)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            dense = vectors.get("dense")
            return getattr(dense, "size", None)
        return getattr(vectors, "size", None)
    except Exception as exc:  # pragma: no cover - best-effort probe
        log.debug("collection_dim_probe_failed", collection=name, error=str(exc))
        return None


async def _ensure_one(name: str, indexes) -> str:
    """Create the collection, or RECREATE it if its dense dimension no longer matches the
    configured embedder (a stale dim silently breaks all vector search). Returns the action."""
    client = get_qdrant()
    dim = await _dense_dim(name)
    if dim is None:
        await _create_collection(name, indexes)
        return "created"
    if dim != settings.EMBEDDING_DIM:
        log.warning("collection_dim_mismatch_recreating", collection=name,
                    existing_dim=dim, expected_dim=settings.EMBEDDING_DIM)
        await client.delete_collection(name)
        await _create_collection(name, indexes)
        return "recreated"
    return "ok"


async def _ensure_collections() -> None:
    """One collection PER DOMAIN (all languages inside) + one shared user_documents
    collection. Collections whose dense dimension no longer matches the embedder are
    recreated so vector search cannot silently fail on a dimension mismatch."""
    total = len(SUPPORTED_DOMAINS) + 1
    log.info(f"Qdrant collection check  expected={total}  embedding_dim={settings.EMBEDDING_DIM}")

    created = recreated = 0
    for domain in SUPPORTED_DOMAINS:
        action = await _ensure_one(domain, _CORPUS_INDEXES)
        created += action == "created"
        recreated += action == "recreated"

    action = await _ensure_one(USER_DOCS_COLLECTION, _USERDOC_INDEXES)
    created += action == "created"
    recreated += action == "recreated"

    log.info(f"Qdrant setup complete  created={created}  recreated={recreated}  total={total}")


# ── Vector writes / deletes ────────────────────────────────────────────────────

async def upsert_points(collection: str, points: list[PointStruct], batch_size: int = 100) -> int:
    """Upsert points into any collection in batches. Returns the count written."""
    client = get_qdrant()
    for i in range(0, len(points), batch_size):
        await client.upsert(collection_name=collection, points=points[i:i + batch_size])
    return len(points)


async def delete_by_filter(collection: str, filters: dict) -> None:
    """Delete all points in a collection matching a metadata filter (e.g. a user's doc)."""
    flt = build_filter(filters)
    if flt is None:
        return
    client = get_qdrant()
    await client.delete(collection_name=collection, points_selector=FilterSelector(filter=flt))
    log.info("qdrant_points_deleted", collection=collection, filters=filters)
