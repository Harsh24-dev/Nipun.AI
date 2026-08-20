"""
Research papers, books, and study/re-skilling material.

  * ScholarTool — latest research + findings across arXiv (keyless), Crossref (keyless),
    Semantic Scholar (keyless tier), and PubMed (keyless) for medical/health topics.
  * BooksTool   — best available books on a subject/career via Open Library (keyless)
    and Google Books. Includes a curated career→subject seed map so a query like
    "books to become a doctor" expands into strong search terms.

All return cited results the assistant grounds recommendations in — never invented ISBNs.
"""

from __future__ import annotations

import asyncio

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult
from src.mcp.live.http import get_json

log = structlog.get_logger("mcp.live.research")

# Career → strong book/subject search seeds (India-aware where relevant).
_CAREER_SEEDS: dict[str, str] = {
    "doctor": "NEET biology human physiology Harrison medicine anatomy",
    "medical": "medical entrance NEET physiology pathology pharmacology",
    "engineer": "JEE physics mathematics engineering mechanics HC Verma",
    "engineering": "engineering mathematics data structures algorithms GATE",
    "teacher": "pedagogy CTET B.Ed educational psychology teaching methods",
    "advocate": "law CLAT constitution of India IPC CrPC jurisprudence",
    "lawyer": "law bare acts constitution contract law legal reasoning",
    "law": "constitution of India IPC CrPC contract act legal studies",
    "agro": "agronomy agriculture ICAR soil science crop production",
    "agriculture": "agronomy horticulture ICAR JRF soil science",
    "civil services": "UPSC NCERT polity Laxmikanth economy geography history",
    "upsc": "UPSC NCERT Laxmikanth polity economy general studies",
    "ca": "chartered accountant accounting taxation cost accounting ICAI",
    "nurse": "nursing fundamentals anatomy physiology community health",
    "data science": "machine learning statistics python data science",
    "management": "MBA management marketing finance operations strategy",
}


def _expand_career(query: str) -> str:
    q = query.lower()
    seeds = [seed for key, seed in _CAREER_SEEDS.items() if key in q]
    return (query + " " + " ".join(seeds)).strip() if seeds else query


# ── Research providers ────────────────────────────────────────────────────────

async def _arxiv(query: str) -> list[dict]:
    import re
    xml = await get_json(  # arXiv returns Atom XML; get_json will fail → use text path
        "https://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "start": 0,
                "max_results": settings.LIVE_MAX_RESULTS, "sortBy": "submittedDate",
                "sortOrder": "descending"},
    )
    # arXiv is XML, not JSON; get_json returns None. Fetch as text instead.
    if xml is None:
        from src.mcp.live.http import get_text
        xml = await get_text(
            "https://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "start": 0,
                    "max_results": settings.LIVE_MAX_RESULTS, "sortBy": "submittedDate",
                    "sortOrder": "descending"},
        )
    if not isinstance(xml, str):
        return []
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
    out = []
    for e in entries[: settings.LIVE_MAX_RESULTS]:
        title = re.search(r"<title>(.*?)</title>", e, re.S)
        summ = re.search(r"<summary>(.*?)</summary>", e, re.S)
        link = re.search(r'<id>(.*?)</id>', e, re.S)
        if title:
            out.append({
                "title": title.group(1).strip().replace("\n", " "),
                "url": link.group(1).strip() if link else "",
                "content": (summ.group(1).strip().replace("\n", " ")[:400] if summ else ""),
                "source": "arXiv",
            })
    return out


async def _semantic_scholar(query: str) -> list[dict]:
    headers = {"x-api-key": settings.SEMANTIC_SCHOLAR_API_KEY} if settings.SEMANTIC_SCHOLAR_API_KEY else None
    data = await get_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": query, "limit": settings.LIVE_MAX_RESULTS,
                "fields": "title,abstract,year,url,authors"},
        headers=headers,
    )
    papers = (data or {}).get("data") or []
    return [
        {"title": p.get("title", ""), "url": p.get("url", ""),
         "content": (p.get("abstract") or "")[:400] + f" ({p.get('year','')})",
         "source": "Semantic Scholar"}
        for p in papers[: settings.LIVE_MAX_RESULTS] if p.get("title")
    ]


async def _pubmed(query: str) -> list[dict]:
    ids_data = await get_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmode": "json",
                "retmax": settings.LIVE_MAX_RESULTS, "sort": "date"},
    )
    ids = (((ids_data or {}).get("esearchresult") or {}).get("idlist")) or []
    if not ids:
        return []
    summ = await get_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
    )
    result = (summ or {}).get("result") or {}
    out = []
    for pid in ids:
        p = result.get(pid) or {}
        if p.get("title"):
            out.append({
                "title": p.get("title", ""),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                "content": f"{p.get('title','')} — {p.get('fulljournalname','')} ({p.get('pubdate','')})",
                "source": "PubMed",
            })
    return out


class ScholarTool(MCPTool):
    name = "scholar"
    description = "Latest research papers and findings (arXiv, Semantic Scholar, PubMed)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or params.get("topic") or "").strip()
        if not query:
            return ToolResult(self.name, "error", text="scholar requires a 'query'.")
        medical = any(w in query.lower() for w in ("disease", "clinical", "patient", "medical",
                                                   "health", "drug", "therapy", "cancer"))
        # Query providers concurrently — they're independent. One provider failing (or being
        # slow) must not sink the others, so gather with return_exceptions and skip failures.
        provider_coros = [_semantic_scholar(query), _arxiv(query)]
        if medical:
            provider_coros.append(_pubmed(query))
        results: list[dict] = []
        for res in await asyncio.gather(*provider_coros, return_exceptions=True):
            if isinstance(res, Exception):
                log.debug("scholar_source_failed", error=str(res))
                continue
            results += res
        # Dedup by title, cap.
        seen, deduped = set(), []
        for r in results:
            key = r["title"].lower()[:80]
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        deduped = deduped[: settings.LIVE_MAX_RESULTS]
        if not deduped:
            return ToolResult(self.name, "unavailable", text=f"No research papers found for '{query}'.")
        text = " | ".join(r["title"] for r in deduped)
        return ToolResult(self.name, "ok", data={"results": deduped}, text=text)


class BooksTool(MCPTool):
    name = "books"
    description = "Best available books on a subject/career (Open Library, Google Books)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or params.get("subject") or params.get("career") or "").strip()
        if not query:
            return ToolResult(self.name, "error", text="books requires a 'query'/'subject'/'career'.")
        expanded = _expand_career(query)

        results: list[dict] = []
        # Open Library + Google Books are independent lookups — fetch them concurrently.
        # (Google Books params are assembled first so both calls can be issued together.)
        gb_params = {"q": expanded, "maxResults": settings.LIVE_MAX_RESULTS, "country": "IN"}
        if settings.GOOGLE_BOOKS_API_KEY:
            gb_params["key"] = settings.GOOGLE_BOOKS_API_KEY
        ol, gb = await asyncio.gather(
            get_json(
                "https://openlibrary.org/search.json",
                params={"q": expanded, "limit": settings.LIVE_MAX_RESULTS, "fields":
                        "title,author_name,first_publish_year,key,edition_count"},
            ),
            get_json("https://www.googleapis.com/books/v1/volumes", params=gb_params),
            return_exceptions=True,
        )
        if isinstance(ol, Exception):
            log.debug("openlibrary_failed", error=str(ol))
            ol = None
        if isinstance(gb, Exception):
            log.debug("google_books_failed", error=str(gb))
            gb = None
        # Open Library (keyless) — sorted by editions/popularity.
        for d in ((ol or {}).get("docs") or [])[: settings.LIVE_MAX_RESULTS]:
            authors = ", ".join((d.get("author_name") or [])[:2])
            results.append({
                "title": d.get("title", ""),
                "url": f"https://openlibrary.org{d.get('key','')}",
                "content": f"{d.get('title','')} by {authors} ({d.get('first_publish_year','')}), "
                           f"{d.get('edition_count',0)} editions.",
                "source": "Open Library",
            })
        # Google Books (keyless tier, key raises quota) — already fetched above.
        for item in ((gb or {}).get("items") or [])[: settings.LIVE_MAX_RESULTS]:
            v = item.get("volumeInfo", {})
            results.append({
                "title": v.get("title", ""),
                "url": v.get("infoLink", ""),
                "content": f"{v.get('title','')} by {', '.join(v.get('authors', [])[:2])} — "
                           f"{(v.get('description') or '')[:200]}",
                "source": "Google Books",
            })
        # Opt-in: enqueue background download+local-embed of the top open books so
        # future queries can answer from the actual book content (not just titles).
        if settings.BOOKS_AUTO_INGEST and settings.BOOKS_INGEST_ENABLED:
            try:
                from src.ingestion.tasks import ingest_books_topic
                ingest_books_topic.delay(query, None, "en", None)
                log.info("books_auto_ingest_enqueued", query=query[:60])
            except Exception as exc:
                log.debug("books_auto_ingest_skipped", error=str(exc))

        if not results:
            return ToolResult(self.name, "unavailable", text=f"No books found for '{query}'.")
        text = " | ".join(r["title"] for r in results[:6])
        return ToolResult(self.name, "ok",
                          data={"results": results, "expanded_query": expanded}, text=text)
