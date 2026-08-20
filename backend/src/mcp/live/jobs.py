"""
Job search across popular portals — for students and working professionals.

Keyless-first, like the other live tools: it never fabricates openings and degrades
gracefully when a source is down.

  * Remotive (keyless)  — real, currently-open remote roles worldwide (great for tech,
    design, marketing, support and other remote-friendly fields).
  * Arbeitnow (keyless) — an open job-board API (visa-friendly / remote roles).
  * Portal-scoped web search — routes the query through the existing WebSearchTool with
    `site:` filters for the portals Indians actually use (Naukri, LinkedIn Jobs, Indeed,
    Foundit, Instahyre, TimesJobs) and the government National Career Service (ncs.gov.in),
    so results are real listing pages the user can open and apply on.

Returns `data["results"] = [{title, url, content, source}]` — the same shape the aggregator
turns into cited knowledge chunks, so the jobs/career agent can ground and cite matches.
"""

from __future__ import annotations

import asyncio

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult
from src.mcp.live.http import get_json

log = structlog.get_logger("mcp.live.jobs")

# Portals Indian job-seekers actually apply on. Kept as data so adding a portal is one line.
_INDIA_JOB_PORTALS: list[str] = [
    "naukri.com",
    "linkedin.com/jobs",
    "indeed.co.in",
    "foundit.in",
    "instahyre.com",
    "timesjobs.com",
    "ncs.gov.in",           # National Career Service (government)
]


async def _remotive(query: str) -> list[dict]:
    """Keyless Remotive API — currently-open remote roles."""
    data = await get_json(
        "https://remotive.com/api/remote-jobs",
        params={"search": query, "limit": settings.LIVE_MAX_RESULTS},
    )
    jobs = (data or {}).get("jobs") or []
    out: list[dict] = []
    for j in jobs[: settings.LIVE_MAX_RESULTS]:
        company = j.get("company_name", "")
        location = j.get("candidate_required_location", "Remote")
        jtype = j.get("job_type", "")
        out.append({
            "title": f"{j.get('title', '')} — {company}",
            "url": j.get("url", ""),
            "content": f"{j.get('title', '')} at {company} ({location}"
                       f"{', ' + jtype if jtype else ''}). Category: {j.get('category', '')}. "
                       f"Apply on Remotive.",
            "source": "Remotive",
        })
    return out


async def _arbeitnow(query: str) -> list[dict]:
    """Keyless Arbeitnow job-board API — remote / visa-friendly roles."""
    data = await get_json("https://www.arbeitnow.com/api/job-board-api")
    jobs = (data or {}).get("data") or []
    q = query.lower()
    out: list[dict] = []
    for j in jobs:
        hay = f"{j.get('title', '')} {j.get('description', '')} {' '.join(j.get('tags', []) or [])}".lower()
        if q and not any(term in hay for term in q.split()):
            continue
        company = j.get("company_name", "")
        loc = j.get("location", "Remote" if j.get("remote") else "")
        out.append({
            "title": f"{j.get('title', '')} — {company}",
            "url": j.get("url", ""),
            "content": f"{j.get('title', '')} at {company} ({loc}). "
                       f"Tags: {', '.join((j.get('tags') or [])[:6])}.",
            "source": "Arbeitnow",
        })
        if len(out) >= settings.LIVE_MAX_RESULTS:
            break
    return out


async def _portal_search(query: str) -> list[dict]:
    """Route the query through the existing web-search tool, scoped to Indian job portals,
    so results are real listing pages the user can open and apply on."""
    from src.mcp.tools import get_tool

    web = get_tool("web_search")
    if web is None:
        return []
    sites = " OR ".join(f"site:{p}" for p in _INDIA_JOB_PORTALS)
    scoped = f"{query} jobs ({sites})"
    result = await web.call({"query": scoped})
    if result.status != "ok":
        return []
    out: list[dict] = []
    for r in (result.data.get("results") or [])[: settings.LIVE_MAX_RESULTS]:
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "source": r.get("source", "Job portal"),
        })
    return out


class JobSearchTool(MCPTool):
    name = "job_search"
    description = "Find current job openings across popular portals (Naukri, LinkedIn, Indeed, NCS, remote boards)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or params.get("role") or params.get("title") or "").strip()
        if not query:
            return ToolResult(self.name, "error", text="job_search requires a 'query'/'role'.")

        location = (params.get("location") or "").strip()
        search = f"{query} {location}".strip()

        results: list[dict] = []
        # Portal-scoped web search (India-relevant, apply-ready listing pages) plus keyless
        # remote boards, all queried concurrently. Each is best-effort: one bad provider never
        # sinks the search (gather with return_exceptions, failures skipped).
        sources = (_portal_search, _remotive, _arbeitnow)
        gathered = await asyncio.gather(
            *[src(search if src is _portal_search else query) for src in sources],
            return_exceptions=True,
        )
        for source, res in zip(sources, gathered):
            if isinstance(res, Exception):
                log.debug("job_source_failed", source=source.__name__, error=str(res))
                continue
            results += res

        # De-dup by URL (fall back to title), cap.
        seen, deduped = set(), []
        for r in results:
            key = (r.get("url") or r.get("title", ""))[:120]
            if key and key not in seen:
                seen.add(key)
                deduped.append(r)
        deduped = deduped[: settings.LIVE_MAX_RESULTS]

        if not deduped:
            return ToolResult(self.name, "unavailable",
                              text=f"No live job openings found for '{query}'"
                                   f"{' in ' + location if location else ''}.")
        text = " | ".join(r["title"] for r in deduped[:6])
        log.info("job_search_ok", results=len(deduped), query=query[:60], location=location[:30])
        return ToolResult(self.name, "ok",
                          data={"results": deduped, "query": query, "location": location}, text=text)
