"""
Web search + web fetch.

WebSearchTool: Tavily first (LLM-native, returns clean citable snippets). If no
TAVILY_API_KEY, falls back to Brave / SerpAPI when those keys exist, then to fully
keyless sources (DuckDuckGo Instant Answer + Wikipedia REST) so search ALWAYS works.

WebFetchTool: fetch one URL and extract readable text for grounding.

Results are returned as `data["results"] = [{title, url, content, source}]` so the
aggregator can turn them into cited knowledge chunks.
"""

from __future__ import annotations

import re

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult
from src.mcp.live.http import get_json, get_text, post_json

log = structlog.get_logger("mcp.live.web")

_MAX = lambda: settings.LIVE_MAX_RESULTS  # noqa: E731

# Nice publisher names for common hosts so a citation reads "Wikipedia", not "en.wikipedia.org".
_KNOWN_HOSTS = {
    "wikipedia.org": "Wikipedia", "britannica.com": "Britannica", "byjus.com": "BYJU'S",
    "khanacademy.org": "Khan Academy", "cuemath.com": "Cuemath", "geeksforgeeks.org": "GeeksforGeeks",
    "youtube.com": "YouTube", "arxiv.org": "arXiv", "nptel.ac.in": "NPTEL", "ncert.nic.in": "NCERT",
    "gov.in": "Government of India", "who.int": "WHO", "mayoclinic.org": "Mayo Clinic",
    "investopedia.com": "Investopedia", "toppr.com": "Toppr", "vedantu.com": "Vedantu",
}


def _source_from_url(url: str, fallback: str = "Web") -> str:
    """The real publisher for a citation, derived from the URL's host — NOT the search engine
    that found it (a source labelled 'Tavily' tells the user nothing; 'Wikipedia' does)."""
    from urllib.parse import urlparse
    try:
        host = urlparse(url or "").netloc.replace("www.", "").lower()
    except Exception:
        host = ""
    if not host:
        return fallback
    for suffix, name in _KNOWN_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    parts = [p for p in host.split(".") if p not in ("com", "org", "net", "in", "co", "edu", "gov", "ac")]
    return parts[-1].capitalize() if parts else host


def _clean_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ── Providers (each returns a list of {title,url,content,source} or None) ──────

async def _tavily(query: str) -> list[dict] | None:
    if not settings.TAVILY_API_KEY:
        return None
    body = {
        "api_key": settings.TAVILY_API_KEY,
        "query": query,
        # "basic" is markedly faster than "advanced" with negligible quality loss for grounding.
        "search_depth": "basic",
        "max_results": _MAX(),
        "include_answer": True,
    }
    data = await post_json("https://api.tavily.com/search", json_body=body)
    if not data:
        return None
    out: list[dict] = []
    if data.get("answer"):
        out.append({"title": "Web summary", "url": "", "content": data["answer"], "source": "Web summary"})
    for r in (data.get("results") or [])[: _MAX()]:
        url = r.get("url", "")
        out.append({
            "title": r.get("title", ""), "url": url,
            "content": r.get("content", ""), "source": _source_from_url(url, "Web"),
        })
    return out or None


async def _brave(query: str) -> list[dict] | None:
    if not settings.BRAVE_API_KEY:
        return None
    data = await get_json(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": _MAX()},
        headers={"X-Subscription-Token": settings.BRAVE_API_KEY, "Accept": "application/json"},
    )
    results = ((data or {}).get("web") or {}).get("results") or []
    out = [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "content": r.get("description", ""), "source": "Brave Search"}
        for r in results[: _MAX()]
    ]
    return out or None


async def _serpapi(query: str) -> list[dict] | None:
    if not settings.SERPAPI_API_KEY:
        return None
    data = await get_json(
        "https://serpapi.com/search.json",
        params={"q": query, "engine": "google", "num": _MAX(), "api_key": settings.SERPAPI_API_KEY},
    )
    results = (data or {}).get("organic_results") or []
    out = [
        {"title": r.get("title", ""), "url": r.get("link", ""),
         "content": r.get("snippet", ""), "source": "Google (SerpAPI)"}
        for r in results[: _MAX()]
    ]
    return out or None


async def _google_cse(query: str) -> list[dict] | None:
    """Google Programmable Search (Custom Search JSON API) — high-quality, broad web results.
    Active only when GOOGLE_API_KEY + GOOGLE_CSE_ID are configured; otherwise skipped."""
    if not (settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID):
        return None
    data = await get_json(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": settings.GOOGLE_API_KEY, "cx": settings.GOOGLE_CSE_ID,
                "q": query, "num": _MAX(), "safe": "active"},
    )
    items = (data or {}).get("items") or []
    out = [
        {"title": it.get("title", ""), "url": it.get("link", ""),
         "content": it.get("snippet", ""), "source": it.get("displayLink", "Google")}
        for it in items[: _MAX()]
    ]
    return out or None


async def _duckduckgo(query: str) -> list[dict] | None:
    """Keyless DuckDuckGo Instant Answer API (no key required)."""
    data = await get_json(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
    )
    if not data:
        return None
    out: list[dict] = []
    if data.get("AbstractText"):
        out.append({
            "title": data.get("Heading", query), "url": data.get("AbstractURL", ""),
            "content": data["AbstractText"], "source": data.get("AbstractSource", "DuckDuckGo"),
        })
    for topic in (data.get("RelatedTopics") or []):
        if isinstance(topic, dict) and topic.get("Text"):
            out.append({
                "title": topic.get("Text", "")[:80], "url": topic.get("FirstURL", ""),
                "content": topic.get("Text", ""), "source": "DuckDuckGo",
            })
        if len(out) >= _MAX():
            break
    return out or None


async def _wikipedia(query: str) -> list[dict] | None:
    """Keyless Wikipedia REST — search then summarize the top page."""
    search = await get_json(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": 3},
    )
    hits = (((search or {}).get("query") or {}).get("search")) or []
    titles = [h.get("title", "") for h in hits if h.get("title")][:_MAX()]
    # Fetch the top page summaries CONCURRENTLY (was a serial loop of up to 3 HTTP calls,
    # which could stack into a long wall-time inside this one "parallel" tool).
    import asyncio

    summaries = await asyncio.gather(*[
        get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{t.replace(' ', '_')}")
        for t in titles
    ], return_exceptions=True)
    out: list[dict] = []
    for title, summary in zip(titles, summaries):
        if isinstance(summary, Exception) or not summary or not summary.get("extract"):
            continue
        out.append({
            "title": title,
            "url": (summary.get("content_urls", {}).get("desktop", {}) or {}).get("page", ""),
            "content": summary["extract"], "source": "Wikipedia",
        })
    return out or None


class WebSearchTool(MCPTool):
    name = "web_search"
    description = "Search the web for current, credible information (Tavily → keyless fallback)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or "").strip()
        if not query:
            return ToolResult(self.name, "error", text="web_search requires a 'query'.")

        provider_chain = [_tavily, _google_cse, _brave, _serpapi, _duckduckgo, _wikipedia]
        for provider in provider_chain:
            results = await provider(query)
            if results:
                used = results[0]["source"]
                summary = " ".join(r["content"] for r in results[:3])[:600]
                log.info("web_search_ok", provider=used, results=len(results), query=query[:60])
                return ToolResult(
                    self.name, "ok",
                    data={"results": results, "provider": used, "query": query},
                    text=summary,
                )
        return ToolResult(self.name, "unavailable",
                          text="No web source returned results for this query.")


class WebFetchTool(MCPTool):
    name = "web_fetch"
    description = "Fetch a specific URL and extract readable text for grounding."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        url = (params.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(self.name, "error", text="web_fetch requires an http(s) 'url'.")
        log.info("web_fetch_call", url=url[:120])
        html = await get_text(url)
        if not html:
            log.warning("web_fetch_failed", url=url[:120])
            return ToolResult(self.name, "unavailable", text=f"Could not fetch {url}.")
        text = _clean_html(html)[:6000]
        return ToolResult(
            self.name, "ok",
            data={"results": [{"title": url, "url": url, "content": text, "source": url}]},
            text=text[:600],
        )
