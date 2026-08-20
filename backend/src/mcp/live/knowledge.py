"""
Encyclopedic knowledge base — Wikipedia as a broad, citeable grounding source for ANY topic.

Wikipedia covers virtually any subject a user might ask about and is keyless, so it's an
excellent always-available baseline to ground answers in (and cite) — complementing web search
(current/fresh) and the domain corpus (India-specific). This tool searches Wikipedia for the
query and returns the most relevant articles' actual text as cited knowledge chunks, so the
answer is grounded in real encyclopedic content, not the model's memory.
"""

from __future__ import annotations

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult
from src.mcp.live.http import get_json

log = structlog.get_logger("mcp.live.knowledge")

# Multiple language editions so a question asked in Hindi can still be grounded (falls back to
# English, which has the widest coverage).
_WIKI_HOSTS = {"hi": "hi.wikipedia.org", "en": "en.wikipedia.org"}


async def _search_titles(host: str, query: str, limit: int) -> list[str]:
    data = await get_json(
        f"https://{host}/w/api.php",
        params={"action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": limit},
    )
    hits = (((data or {}).get("query") or {}).get("search")) or []
    return [h.get("title", "") for h in hits if h.get("title")]


async def _extracts(host: str, titles: list[str]) -> list[dict]:
    """Plain-text intro extracts for the given article titles, with page URLs."""
    if not titles:
        return []
    data = await get_json(
        f"https://{host}/w/api.php",
        params={"action": "query", "prop": "extracts|info", "explaintext": 1,
                "exintro": 1, "inprop": "url", "redirects": 1,
                "titles": "|".join(titles[:4]), "format": "json"},
    )
    pages = (((data or {}).get("query") or {}).get("pages")) or {}
    out: list[dict] = []
    for p in pages.values():
        extract = (p.get("extract") or "").strip()
        if len(extract) < 80:
            continue
        out.append({
            "title": p.get("title", ""),
            "url": p.get("fullurl", ""),
            "content": extract[:3000],
            "source": f"Wikipedia — {p.get('title', '')}",
        })
    return out


class WikipediaTool(MCPTool):
    name = "wikipedia"
    description = "Ground answers in Wikipedia article text for any topic (keyless, cited)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or params.get("topic") or "").strip()
        if not query:
            return ToolResult(self.name, "error", text="wikipedia requires a 'query'.")
        lang = (params.get("language") or "en").split("+")[0].split("-")[0]
        limit = min(int(params.get("limit", 3)), settings.LIVE_MAX_RESULTS)

        results: list[dict] = []
        # Try the user's language edition first (if not English), then always English.
        for host in dict.fromkeys([_WIKI_HOSTS.get(lang), _WIKI_HOSTS["en"]]):
            if not host:
                continue
            titles = await _search_titles(host, query, limit)
            results.extend(await _extracts(host, titles))
            if results:
                break
        # De-dup by title, cap.
        seen, deduped = set(), []
        for r in results:
            key = r["title"].lower()
            if key and key not in seen:
                seen.add(key)
                deduped.append(r)
        deduped = deduped[:limit]
        if not deduped:
            return ToolResult(self.name, "unavailable", text=f"No Wikipedia article for '{query}'.")
        text = " | ".join(r["title"] for r in deduped)
        log.info("wikipedia_grounding", articles=len(deduped), query=query[:60])
        return ToolResult(self.name, "ok", data={"results": deduped}, text=text)
