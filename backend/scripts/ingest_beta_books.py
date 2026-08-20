"""
Beta-test corpus: ingest real, openly-licensed full-text books per domain so every
domain has substantive content to retrieve against. Uses the existing book pipeline
(Gutenberg / Internet Archive / OpenAlex) via `ingest_books_for_topic`.

    NIPUN_ARCHIVE_CORPUS=1 uv run python -m scripts.ingest_beta_books
    NIPUN_ARCHIVE_CORPUS=1 uv run python -m scripts.ingest_beta_books --max 3

Each ingested book is also archived to data/corpus_raw/ (when NIPUN_ARCHIVE_CORPUS=1)
so the same corpus can be reproduced in production.
"""

from __future__ import annotations

import argparse
import asyncio

import structlog

from src.core.logging import setup_logging

log = structlog.get_logger("ingest_beta_books")

# One or more search topics per domain, chosen to surface substantive open full-text.
DOMAIN_TOPICS: dict[str, list[str]] = {
    "legal": ["Indian Penal Code", "constitution of India"],
    "finance": ["personal finance", "principles of economics"],
    "health": ["human physiology", "hygiene and public health"],
    "scheme": ["rural development India", "public welfare administration"],
    "farming": ["agriculture crop production", "principles of agriculture"],
    "student": ["elementary mathematics", "general science textbook"],
    "career": ["how to succeed at work", "self improvement"],
    "governance": ["public administration India", "local self government"],
    "jobs": ["how to get a job", "employment and skills"],
    "travel": ["geography of India", "India travel and description"],
    "documents": ["letter writing and applications", "official correspondence"],
    "general": ["general knowledge", "encyclopedia of India"],
}


async def _run(max_books: int, only: list[str] | None) -> None:
    from src.db.postgres import close_postgres, init_postgres
    from src.db.qdrant import init_qdrant
    from src.ingestion.books import ingest_books_for_topic

    await init_postgres()
    await init_qdrant()
    results: list[dict] = []
    try:
        for domain, topics in DOMAIN_TOPICS.items():
            if only and domain not in only:
                continue
            for topic in topics:
                try:
                    summary = await ingest_books_for_topic(
                        topic, domain=domain, language="en", max_books=max_books)
                    results.append({"domain": domain, "topic": topic,
                                    "discovered": summary.get("discovered", 0),
                                    "ingested": summary.get("ingested", 0),
                                    "chunks": summary.get("chunks", 0)})
                    log.info("topic_done", domain=domain, topic=topic,
                             ingested=summary.get("ingested", 0), chunks=summary.get("chunks", 0))
                except Exception as exc:
                    log.error("topic_failed", domain=domain, topic=topic, error=str(exc))
                    results.append({"domain": domain, "topic": topic,
                                    "discovered": 0, "ingested": 0, "chunks": 0})
    finally:
        await close_postgres()

    print("\n" + "=" * 72)
    print("  Beta book ingestion summary")
    print("=" * 72)
    print(f"  {'domain':<11} {'topic':<34} {'disc':>5} {'ing':>5} {'chunks':>7}")
    print("-" * 72)
    tot_ing = tot_ch = 0
    for r in results:
        print(f"  {r['domain']:<11} {r['topic'][:34]:<34} {r['discovered']:>5} {r['ingested']:>5} {r['chunks']:>7}")
        tot_ing += r["ingested"]
        tot_ch += r["chunks"]
    print("-" * 72)
    print(f"  {'TOTAL':<11} {'':<34} {'':>5} {tot_ing:>5} {tot_ch:>7}")
    print("=" * 72 + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2, help="max books per topic")
    ap.add_argument("--only", nargs="*", help="restrict to these domains")
    args = ap.parse_args()
    setup_logging()
    asyncio.run(_run(args.max, args.only))


if __name__ == "__main__":
    main()
