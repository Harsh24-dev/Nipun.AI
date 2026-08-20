"""
Domain ingestion runner — `make ingest DOMAIN=legal` / `python -m src.ingestion.run`.

Pulls each domain's ingestion source agent(s), runs the offline seed pack (and, with
--online, the official URLs) through the parse→chunk→index pipeline into Qdrant + ES.

    uv run python -m src.ingestion.run --domain legal
    uv run python -m src.ingestion.run --all
    uv run python -m src.ingestion.run --all --online
"""

from __future__ import annotations

import argparse
import asyncio

import structlog

from src.core.logging import setup_logging, trace_flow
from src.ingestion.pipeline import ingest_spec
from src.ingestion.sources import get_sources, registered_domains

log = structlog.get_logger("ingestion.run")


async def ingest_domain(domain: str, online: bool = False) -> dict:
    """Ingest all sources for one domain. Returns a summary dict."""
    sources = get_sources(domain)
    if not sources:
        log.warning("no_ingestion_sources", domain=domain)
        return {"domain": domain, "indexed": 0, "skipped": 0, "failed": 0, "note": "no sources"}

    log.info("domain_ingestion_start", domain=domain, online=online, source_agents=len(sources))
    trace_flow(
        "ingestion_domain_start",
        domain=domain,
        online=online,
        source_agents=[getattr(s, "name", type(s).__name__) for s in sources],
    )

    indexed = skipped = failed = chunks = 0
    for source in sources:
        agent_name = getattr(source, "name", type(source).__name__)
        specs = source.discover(online=online)
        # Which files/URLs THIS source agent is about to ingest, with full detail.
        log.info("source_agent_discovered", domain=domain, agent=agent_name, documents=len(specs))
        trace_flow(
            "ingestion_source_agent",
            domain=domain,
            agent=agent_name,
            document_count=len(specs),
            documents=[
                {"title": s.title, "source": s.source, "source_url": s.source_url,
                 "language": s.language, "section": s.section,
                 "kind": "inline" if s.is_inline() else "file_or_url"}
                for s in specs
            ],
        )
        for spec in specs:
            try:
                result = await ingest_spec(spec)
                trace_flow(
                    "ingestion_document_result",
                    domain=domain,
                    agent=agent_name,
                    title=spec.title,
                    source=spec.source or spec.source_url or "(inline)",
                    status=result.get("status"),
                    chunks=result.get("chunks", 0),
                    reason=result.get("reason"),
                )
                if result["status"] == "success":
                    indexed += 1
                    chunks += result.get("chunks", 0)
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                log.error("ingest_spec_failed", domain=domain, agent=agent_name, title=spec.title, error=str(exc))
                trace_flow("ingestion_document_failed", domain=domain, agent=agent_name,
                           title=spec.title, source=spec.source or spec.source_url, error=str(exc))

    summary = {"domain": domain, "indexed": indexed, "skipped": skipped, "failed": failed, "chunks": chunks}
    log.info("domain_ingested", **summary)
    trace_flow("ingestion_domain_complete", **summary)
    return summary


async def _run(domains: list[str], online: bool) -> list[dict]:
    from src.db.postgres import close_postgres, init_postgres
    from src.db.qdrant import init_qdrant

    await init_postgres()
    await init_qdrant()
    try:
        return [await ingest_domain(d, online=online) for d in domains]
    finally:
        await close_postgres()


def main() -> None:
    parser = argparse.ArgumentParser(description="Nipun.AI per-domain ingestion")
    parser.add_argument("--domain", help="single domain to ingest")
    parser.add_argument("--all", action="store_true", help="ingest all registered domains")
    parser.add_argument("--online", action="store_true", help="also pull official URLs (needs network)")
    args = parser.parse_args()

    if args.all:
        domains = registered_domains()
    elif args.domain:
        domains = [args.domain]
    else:
        parser.error("specify --domain <name> or --all")

    setup_logging()
    summaries = asyncio.run(_run(domains, online=args.online))

    print("\n" + "=" * 68)
    print("  Nipun.AI — ingestion summary")
    print("=" * 68)
    print(f"  {'domain':<12} {'indexed':>8} {'skipped':>8} {'failed':>7} {'chunks':>8}")
    print("-" * 68)
    for s in summaries:
        print(f"  {s['domain']:<12} {s['indexed']:>8} {s['skipped']:>8} {s['failed']:>7} {s.get('chunks', 0):>8}")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
