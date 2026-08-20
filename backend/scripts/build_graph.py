"""
Build the legal + scheme knowledge graphs into Neo4j (Phase 4).

Requires Neo4j running and GRAPH_ENABLED=true. Without them it runs a dry-run and
prints the accepted/rejected validation counts.

    uv run python scripts/build_graph.py
"""

from __future__ import annotations

import asyncio

from src.core.logging import setup_logging
from src.db.neo4j import close_neo4j, init_neo4j
from src.graph.build import build_all


async def main() -> None:
    setup_logging()
    await init_neo4j()
    try:
        reports = await build_all()
    finally:
        await close_neo4j()

    print("\n" + "=" * 60)
    print("  Knowledge graph build")
    print("=" * 60)
    for r in reports:
        print(f"  {r.graph:<8}  accepted={r.accepted}  rejected={r.rejected}  written={r.written}")
        if r.rejects:
            print(f"           rejects: {', '.join(r.rejects)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
