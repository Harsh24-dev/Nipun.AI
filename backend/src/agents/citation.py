"""
Citation agent — answer-first, cite-after attribution.

The retrieval-first pipeline only lets the model state what the static index already
contains. The citation agent flips that for the claims the model actually made: it takes
the answer's atomic claims, and for every claim NOT already backed by retrieved knowledge
it runs a targeted web search to FIND a credible source, then attaches that source. The
newly-found chunks are folded back into the knowledge pool so the existing
verify_claims → corroborate → score_answer path can ground and score the answer — now
including the sources we went and fetched.

It also reports a `coverage` number: the fraction of the answer's claims we could back
with at least one credible source. That is the "score based on citations" surfaced on the
reliability card, and it is what lets the assistant answer beyond the DB without collapsing
to "I don't have a reliable source".

Everything here is best-effort and never raises: on any failure the answer is returned
unchanged (no new citations, coverage computed from whatever was already grounded).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog

from src.config import settings
from src.core.logging import trace_flow
from src.safety.verification import claim_overlap

log = structlog.get_logger("agents.citation")


@dataclass
class CitationResult:
    new_chunks: list[dict] = field(default_factory=list)   # sources found, as knowledge chunks
    citations: list[dict] = field(default_factory=list)    # per-claim {claim, backed, sources[]}
    coverage: float = 0.0                                  # fraction of claims backed by a source
    claims_total: int = 0
    claims_backed: int = 0
    assessable: bool = False                               # False when there were no claims to cite


def _covered_by_existing(claim: str, knowledge: list[dict]) -> bool:
    """True when a claim is already entailed by the retrieved knowledge pool — no need to
    spend a web search finding a citation for it."""
    for k in knowledge:
        if claim_overlap(claim, k.get("text") or "") >= settings.CITATION_COVERED_OVERLAP:
            return True
    return False


async def _search_claim(claim: str, index: int, correlation_id: str) -> tuple[str, list[dict]]:
    """Web-search ONE claim and return (claim, supporting-source chunks). A returned result
    counts as support only when it overlaps the claim enough (CITATION_MATCH_OVERLAP) — a
    search that returns off-topic pages must not be treated as a citation."""
    from src.mcp.tools import get_tool

    tool = get_tool("web_search")
    if tool is None:
        return claim, []
    try:
        result = await tool.call({"query": claim})
    except Exception as exc:
        log.warning("citation_search_failed", claim=claim[:60], error=str(exc),
                    correlation_id=correlation_id)
        return claim, []
    if result is None or result.status != "ok":
        return claim, []
    if result.suspected_instructions:
        log.warning("citation_search_suspected_injection", claim=claim[:60],
                    suspects=result.suspected_instructions, correlation_id=correlation_id)

    chunks: list[dict] = []
    results = (result.data or {}).get("results", []) or []
    for j, r in enumerate(results[: settings.CITATION_RESULTS_PER_CLAIM]):
        text = (r.get("content") or "").strip()
        if not text or claim_overlap(claim, text) < settings.CITATION_MATCH_OVERLAP:
            continue
        chunks.append({
            "chunk_id": f"cite:{index}:{j}",
            "text": text,
            "source": r.get("source") or "Web",
            "source_url": r.get("url", ""),
            "section": r.get("title", ""),
            "relevance_score": 1.0 - j * 0.05,
            "retrieval_method": "citation_agent",
            "live": True,
            "cited_claim": claim,
        })
    return claim, chunks


async def find_citations(
    claims: list[str],
    knowledge: list[dict],
    correlation_id: str = "",
) -> CitationResult:
    """Find a credible source for each claim the model made.

    claims    — the answer's atomic claims (from verification.extract_claims).
    knowledge — the FULL knowledge pool already retrieved (static + live); claims it
                already backs are counted as covered without a new search.

    Returns the sources found (as knowledge chunks to fold into the pool), a per-claim
    citation map, and the coverage fraction. Never raises."""
    claims = [c for c in (claims or []) if isinstance(c, str) and c.strip()]
    if not claims:
        return CitationResult(assessable=False)

    knowledge = knowledge or []
    # Split claims into those already grounded vs. those needing a citation search.
    already, to_search = [], []
    for c in claims:
        (already if _covered_by_existing(c, knowledge) else to_search).append(c)

    # Bound cost: only search the first N uncited claims (the answer's load-bearing facts
    # come first). Any claim beyond the cap that wasn't already grounded stays "unbacked".
    searchable = to_search[: settings.CITATION_MAX_CLAIMS]
    overflow = to_search[settings.CITATION_MAX_CLAIMS:]

    found: dict[str, list[dict]] = {}
    if searchable and settings.WEB_TOOLS_ENABLED:
        pairs = await asyncio.gather(
            *[_search_claim(c, i, correlation_id) for i, c in enumerate(searchable)],
            return_exceptions=True,
        )
        for pair in pairs:
            if isinstance(pair, Exception):
                continue
            claim, chunks = pair
            if chunks:
                found[claim] = chunks

    # Assemble per-claim citations + dedup the new chunks by (url, text-prefix).
    citations: list[dict] = []
    new_chunks: list[dict] = []
    seen: set[str] = set()
    for c in claims:
        if c in already:
            citations.append({"claim": c, "backed": True, "via": "retrieved", "sources": []})
            continue
        chunks = found.get(c, [])
        srcs = []
        for ch in chunks:
            key = ch.get("source_url") or (ch.get("text") or "")[:80]
            if key not in seen:
                seen.add(key)
                new_chunks.append(ch)
            srcs.append({"text": ch.get("source", "Web"), "url": ch.get("source_url", "")})
        citations.append({
            "claim": c, "backed": bool(chunks),
            "via": "searched" if chunks else "unbacked", "sources": srcs,
        })

    backed = sum(1 for ct in citations if ct["backed"])
    coverage = backed / len(claims) if claims else 0.0
    result = CitationResult(
        new_chunks=new_chunks, citations=citations, coverage=coverage,
        claims_total=len(claims), claims_backed=backed, assessable=True,
    )
    log.info(
        "citations_found",
        claims=len(claims), pre_grounded=len(already), searched=len(searchable),
        overflow=len(overflow), newly_backed=len(found), new_sources=len(new_chunks),
        coverage=round(coverage, 3), correlation_id=correlation_id,
    )
    trace_flow(
        "citations_found",
        correlation_id=correlation_id,
        claims_total=len(claims),
        claims_backed=backed,
        coverage=round(coverage, 3),
        pre_grounded=len(already),
        searched=len(searchable),
        new_sources=len(new_chunks),
        citations=citations,
    )
    return result
