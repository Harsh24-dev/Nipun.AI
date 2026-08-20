"""
Neo4j async client (GraphRAG).

Guarded/optional: if the `neo4j` driver isn't installed or GRAPH_ENABLED is off, the
graph tier degrades to a no-op and the rest of the system runs unchanged. The graph
path is only used for multi-hop/relational queries (the router decides).
"""

from __future__ import annotations

import structlog

from src.config import settings

log = structlog.get_logger("db.neo4j")

_driver = None
_available: bool | None = None


def graph_available() -> bool:
    """True only if enabled, the driver is importable, and a connection was made."""
    return bool(_available)


async def init_neo4j() -> None:
    global _driver, _available
    if not settings.GRAPH_ENABLED:
        _available = False
        log.info("neo4j_disabled")
        return
    try:
        from neo4j import AsyncGraphDatabase

        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        await _driver.verify_connectivity()
        _available = True
        log.info("neo4j_connected", uri=settings.NEO4J_URI)
    except Exception as exc:
        _available = False
        _driver = None
        log.warning("neo4j_unavailable", error=str(exc))


def get_neo4j():
    if _driver is None:
        raise RuntimeError("Neo4j not initialised or unavailable.")
    return _driver


async def close_neo4j() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def run_write(cypher: str, **params) -> None:
    driver = get_neo4j()
    async with driver.session() as session:
        await session.run(cypher, **params)


async def run_read(cypher: str, **params) -> list[dict]:
    driver = get_neo4j()
    async with driver.session() as session:
        result = await session.run(cypher, **params)
        return [dict(record) async for record in result]
