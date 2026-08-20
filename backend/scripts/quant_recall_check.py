"""
TurboQuant recall check.

Compares int8-quantized search (with full-precision rescoring, as configured) against
exact full-precision search, over the eval-set queries, and prints recall overlap@k.
Use this to confirm quantization does not regress recall before trusting it in prod.

Requires: running Qdrant with SEEDED collections + an embedding provider. Run:
    uv run python scripts/quant_recall_check.py --domain legal --language hi --k 10
"""

from __future__ import annotations

import argparse
import asyncio

from qdrant_client.models import QuantizationSearchParams, QueryRequest, SearchParams

from src.db.qdrant import get_qdrant, init_qdrant
from src.eval.datasets import load_domain
from src.language.constants import collection_name
from src.llm.embeddings import embed_query_async


async def _search(collection: str, dense: list[float], k: int, exact: bool) -> list[str]:
    client = get_qdrant()
    if exact:
        params = SearchParams(exact=True)  # brute-force full precision — the ground truth
    else:
        params = SearchParams(
            quantization=QuantizationSearchParams(rescore=True, oversampling=2.0)
        )
    res = await client.query_batch_points(
        collection_name=collection,
        requests=[QueryRequest(query=dense, using="dense", limit=k, with_payload=False, params=params)],
    )
    return [str(h.id) for h in res[0].points]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="legal")
    parser.add_argument("--language", default="hi")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    await init_qdrant()
    collection = collection_name(args.domain, args.language)
    examples = load_domain(args.domain) or []
    queries = [e.query for e in examples] or ["सामान्य कानूनी सवाल"]

    overlaps: list[float] = []
    for q in queries:
        emb = await embed_query_async(q)
        dense = emb.dense[0]
        quant_ids = set(await _search(collection, dense, args.k, exact=False))
        exact_ids = set(await _search(collection, dense, args.k, exact=True))
        if exact_ids:
            overlaps.append(len(quant_ids & exact_ids) / len(exact_ids))

    avg = sum(overlaps) / len(overlaps) if overlaps else 0.0
    print("\n" + "=" * 64)
    print(f"  TurboQuant recall check  |  collection={collection}  k={args.k}")
    print(f"  queries={len(overlaps)}   mean recall@{args.k} (quant vs exact) = {avg:.4f}")
    print("  (1.0 = quantized search returns exactly the full-precision top-k)")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
