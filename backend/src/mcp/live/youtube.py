"""
YouTube as a GROUNDING source — not just a link, but the video's actual words.

For learning/explain questions, a good YouTube explainer often covers a topic more clearly
than a web page. This tool finds relevant videos and fetches their TRANSCRIPTS, returning
them as cited knowledge chunks — so the answer can be grounded in, and cite, what a credible
video actually says (e.g. "YouTube — Khan Academy: Photosynthesis").

Keyless-first: video discovery uses SerpAPI's YouTube engine when a key exists, otherwise the
existing web-search tool scoped to youtube.com. Transcript fetching (youtube-transcript-api)
is blocking network I/O, so it runs in a worker thread and degrades gracefully — a video with
transcripts disabled is simply skipped, never fabricated.
"""

from __future__ import annotations

import asyncio
import re

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult

log = structlog.get_logger("mcp.live.youtube")

_YT_ID = re.compile(r"(?:v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([\w-]{11})")


def _video_id(url: str) -> str | None:
    m = _YT_ID.search(url or "")
    return m.group(1) if m else None


async def _search_videos(query: str, limit: int) -> list[dict]:
    """Return [{title, url, id}] for the top relevant videos."""
    out: list[dict] = []
    seen: set[str] = set()

    # Preferred: SerpAPI YouTube engine (relevance/popularity ranked).
    if settings.SERPAPI_API_KEY:
        from src.mcp.live.http import get_json
        data = await get_json("https://serpapi.com/search.json",
                              params={"engine": "youtube", "search_query": query,
                                      "api_key": settings.SERPAPI_API_KEY})
        for v in ((data or {}).get("video_results") or []):
            vid = _video_id(v.get("link", ""))
            if vid and vid not in seen:
                seen.add(vid)
                out.append({"title": v.get("title", ""), "url": v.get("link", ""), "id": vid})
            if len(out) >= limit:
                return out

    # Keyless fallback 1: scrape YouTube's own search-results page for video IDs + titles.
    if len(out) < limit:
        for v in await _scrape_youtube_search(query, limit):
            if v["id"] not in seen:
                seen.add(v["id"])
                out.append(v)
            if len(out) >= limit:
                return out

    # Keyless fallback 2: web search scoped to YouTube (works when a web provider returns links).
    if len(out) < limit:
        from src.mcp.tools import get_tool
        web = get_tool("web_search")
        if web is not None:
            res = await web.call({"query": f"{query} explained site:youtube.com"})
            if res.status == "ok":
                for r in (res.data.get("results") or []):
                    vid = _video_id(r.get("url", ""))
                    if vid and vid not in seen:
                        seen.add(vid)
                        out.append({"title": r.get("title", ""), "url": r.get("url", ""), "id": vid})
                    if len(out) >= limit:
                        break
    return out


# YouTube embeds its results as JSON in the page; pull videoId + the paired title run.
_SCRAPE_RE = re.compile(r'"videoId":"([\w-]{11})".*?"text":"([^"]{3,100})"')


async def _scrape_youtube_search(query: str, limit: int) -> list[dict]:
    """Keyless video discovery — fetch the YouTube results page and extract videoIds/titles."""
    from urllib.parse import quote_plus

    from src.mcp.live.http import get_text
    try:
        html = await get_text(
            f"https://www.youtube.com/results?search_query={quote_plus(query)}&hl=en",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Accept-Language": "en-US,en;q=0.9"},
        )
    except Exception as exc:
        log.debug("youtube_scrape_failed", error=str(exc))
        return []
    if not html:
        return []
    out, seen = [], set()
    for vid, title in _SCRAPE_RE.findall(html):
        if vid in seen:
            continue
        seen.add(vid)
        out.append({"title": title.encode().decode("unicode_escape", "ignore"),
                    "url": f"https://www.youtube.com/watch?v={vid}", "id": vid})
        if len(out) >= limit:
            break
    return out


def _fetch_transcript(video_id: str) -> str | None:
    """Blocking transcript fetch (run in a thread). Prefers English/Hindi; None if unavailable."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en", "hi", "en-IN"])
        text = " ".join(seg.get("text", "") for seg in fetched.to_raw_data())
        return " ".join(text.split()) or None
    except Exception as exc:
        log.debug("transcript_unavailable", video_id=video_id, error=str(exc))
        return None


class YouTubeTool(MCPTool):
    name = "youtube"
    description = "Find educational YouTube videos and use their transcripts as grounding (with citations)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or params.get("topic") or "").strip()
        if not query:
            return ToolResult(self.name, "error", text="youtube requires a 'query'.")
        max_videos = min(int(params.get("max_videos", 3)), settings.LIVE_MAX_RESULTS)

        videos = await _search_videos(query, max_videos)
        if not videos:
            return ToolResult(self.name, "unavailable", text=f"No videos found for '{query}'.")

        # Fetch transcripts concurrently (each blocking call in its own thread), each bounded by
        # a hard timeout so a slow/hanging transcript fetch can't stall the tool. A timeout raises
        # TimeoutError, which return_exceptions captures and the loop below skips (degrade to no
        # transcript for that video) — same graceful path as the existing except in _fetch_transcript.
        transcripts = await asyncio.gather(
            *[
                asyncio.wait_for(
                    asyncio.to_thread(_fetch_transcript, v["id"]),
                    timeout=settings.LIVE_HTTP_TIMEOUT,
                )
                for v in videos
            ],
            return_exceptions=True,
        )
        results: list[dict] = []
        for v, tr in zip(videos, transcripts):
            if not isinstance(tr, str) or not tr:
                continue
            results.append({
                "title": v["title"] or "YouTube video",
                "url": v["url"],
                # Cap the transcript so it grounds without flooding the prompt.
                "content": tr[:3000],
                "source": f"YouTube — {v['title'][:60]}" if v["title"] else "YouTube",
            })
        if not results:
            return ToolResult(self.name, "unavailable",
                              text=f"Found videos for '{query}' but none had usable transcripts.")
        text = " | ".join(r["title"] for r in results)
        log.info("youtube_grounding", videos=len(videos), with_transcript=len(results), query=query[:60])
        return ToolResult(self.name, "ok", data={"results": results}, text=text)
