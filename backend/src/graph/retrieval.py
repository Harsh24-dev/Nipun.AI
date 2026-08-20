"""
Graph retrieval + fusion.

Used ONLY for multi-hop / relational queries (the router decides). Fetches related
nodes from the legal/scheme graphs as pseudo-chunks and fuses them with the vector
results via RRF (matching the hybrid-retrieval pattern), after which the caller reranks.
"""

from __future__ import annotations

import re

import structlog

from src.db.neo4j import graph_available, run_read

log = structlog.get_logger("graph.retrieval")

_SECTION_RE = re.compile(r"\b(?:section|dhara|धारा)\s*(\d+[A-Z]?)\b", re.IGNORECASE)
_SCHEME_HINTS = ("scheme", "yojana", "pm-kisan", "ayushman", "awas", "mgnrega", "sukanya")


def _extract_sections(query: str) -> list[str]:
    return _SECTION_RE.findall(query)


async def graph_search(query: str, domain: str, entities: list[str] | None = None) -> list[dict]:
    """Return related graph nodes as pseudo-chunks. Empty when the graph is unavailable."""
    if not graph_available():
        return []
    chunks: list[dict] = []
    try:
        if domain == "legal" or _extract_sections(query):
            for sec in _extract_sections(query) or []:
                rows = await run_read(
                    """
                    MATCH (s:Section {id: $sec})-[:BELONGS_TO]->(a:Act)
                    OPTIONAL MATCH (s)-[:RELATED_TO]->(r:Section)
                    RETURN s.id AS section, s.title AS title, a.name AS act,
                           collect(DISTINCT r.id) AS related
                    """,
                    sec=sec,
                )
                for row in rows:
                    related = ", ".join(row.get("related") or [])
                    text = (f"Section {row['section']} {row['act']}: {row.get('title','')}. "
                            f"Related sections: {related or 'none'}.")
                    chunks.append(_pseudo_chunk(text, f"Section {row['section']} {row['act']}", "graph:legal"))
        if domain in ("scheme", "farming", "health") or any(h in query.lower() for h in _SCHEME_HINTS):
            rows = await run_read(
                """
                MATCH (sc:Scheme)-[:ADMINISTERED_BY]->(m:Ministry)
                OPTIONAL MATCH (sc)-[:REQUIRES]->(c:Criterion)
                RETURN sc.name AS scheme, sc.benefit AS benefit, m.name AS ministry,
                       collect(DISTINCT c.text) AS criteria
                """,
            )
            for row in rows:
                crit = "; ".join(row.get("criteria") or [])
                text = (f"{row['scheme']} (administered by {row['ministry']}): {row.get('benefit','')}. "
                        f"Eligibility: {crit or 'see official portal'}.")
                chunks.append(_pseudo_chunk(text, row["scheme"], "graph:scheme"))
    except Exception as exc:
        log.warning("graph_search_failed", error=str(exc))
        return []
    log.info("graph_search_complete", domain=domain, results=len(chunks))
    return chunks


def _pseudo_chunk(text: str, source: str, method: str) -> dict:
    return {
        "chunk_id": f"{method}:{source}",
        "text": text,
        "source": source,
        "source_url": "",
        "section": source,
        "relevance_score": 0.0,
        "retrieval_method": method,
    }


def rrf_fuse(vector_chunks: list[dict], graph_chunks: list[dict], k: int = 60) -> list[dict]:
    """
    Reciprocal Rank Fusion of vector + graph result lists. Returns chunks ordered by
    fused score (caller reranks). Keyed by chunk_id (falls back to text prefix).
    """
    def key(c: dict) -> str:
        return c.get("chunk_id") or (c.get("text") or "")[:80]

    scores: dict[str, float] = {}
    by_key: dict[str, dict] = {}
    for rank, c in enumerate(vector_chunks):
        kk = key(c)
        scores[kk] = scores.get(kk, 0.0) + 1.0 / (k + rank + 1)
        by_key.setdefault(kk, c)
    for rank, c in enumerate(graph_chunks):
        kk = key(c)
        scores[kk] = scores.get(kk, 0.0) + 1.0 / (k + rank + 1)
        by_key.setdefault(kk, c)

    ordered = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [by_key[kk] for kk in ordered]
