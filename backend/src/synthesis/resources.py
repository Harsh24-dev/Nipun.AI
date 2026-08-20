"""
Study resources — turn a text answer into something you can SEE and explore.

For learning / "explain" questions, a wall of prose is not how most people study. This
gathers, from keyless sources, a small set of:
  * videos   — educational YouTube results for the topic (embedded by the frontend),
  * articles — the best reference links (reused from the answer's own sources + web search),
  * images   — openly-licensed pictures/diagrams (Openverse) to illustrate the concept.

All best-effort and read-only: any source can fail and the answer still stands. Returned as
a compact `resources` block the card carries, so the UI can render a "Learn & explore" strip.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import structlog

from src.config import settings

log = structlog.get_logger("synthesis.resources")

_LEARN_RE = re.compile(
    r"\b(explain|understand|study|learn|teach|what is|what are|how does|how do|why is|why do|"
    r"concept|topic|revise|revision|notes|diagram|graph|video|picture|illustrat|example of|"
    r"meaning of|introduction to|basics of)\b", re.IGNORECASE,
)
_YT_RE = re.compile(r"(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)", re.IGNORECASE)


def wants_study_resources(query: str, domain: str, persona: str = "general") -> bool:
    """True when the query is a learn/understand question that visuals + resources aid."""
    if not settings.WEB_TOOLS_ENABLED:
        return False
    if _LEARN_RE.search(query or ""):
        return True
    return domain in ("student", "general", "career") and persona in ("student", "general", "professional_reskilling")


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


# Signals used to RANK educational resources (best-first). Without a paid API we can't read
# real view/like counts, so we score on the strongest keyless proxies for quality + relevance:
# how well the title matches the query, instructional-quality cues, and reputable teachers.
_QUALITY_HINTS = ("explained", "explain", "tutorial", "for beginners", "beginner",
                  "introduction", "intro", "guide", "basics", "fundamentals", "in minutes",
                  "crash course", "lecture", "step by step", "full course", "masterclass")
_TRUSTED_SOURCES = ("khan academy", "khanacademy", "mit", "stanford", "harvard", "freecodecamp",
                    "3blue1brown", "ted-ed", "ted ed", "nptel", "byju", "crashcourse",
                    "simplilearn", "ibm", "google", "microsoft", "wikipedia", "britannica",
                    "geeksforgeeks", "cuemath", "vedantu", "unacademy")
_CLICKBAIT = ("shorts", "#shorts", "reaction", "prank", "gone wrong", "tier list", "meme")


def _relevance_quality_score(title: str, source: str, query_terms: set) -> int:
    """Rank score for a video/article: query relevance + quality cues + source reputation."""
    hay = f"{title} {source}".lower()
    score = sum(3 for t in query_terms if t in hay)          # relevance: query terms present
    score += sum(2 for h in _QUALITY_HINTS if h in hay)      # instructional-quality cues
    score += sum(4 for s in _TRUSTED_SOURCES if s in hay)    # reputable teacher/publisher
    score -= sum(3 for c in _CLICKBAIT if c in hay)          # de-rank low-quality/clickbait
    return score


async def _videos(query: str) -> list[dict]:
    """Top educational videos for the topic (web-search scoped to YouTube), ranked best-first
    by query relevance + instructional-quality cues + reputable channels."""
    from src.mcp.tools import get_tool

    web = get_tool("web_search")
    if web is None:
        return []
    # No real topic word (e.g. a bare follow-up like "explain it again") → don't fetch
    # videos at all. Without a topic term the relevance gate below is a no-op and any video
    # passes, which is exactly how an unrelated result slips into the citations.
    terms = set(_topic_terms(query))
    if not terms:
        return []
    result = await web.call({"query": f"{query} explained site:youtube.com"})
    if result.status != "ok":
        return []
    cand: list[dict] = []
    seen: set[str] = set()
    for r in (result.data.get("results") or []):
        url, title = r.get("url", ""), r.get("title", "")
        if not _YT_RE.search(url) or url in seen:
            continue
        # Relevance gate: the video title should relate to the topic (skip off-topic results).
        if terms and title and not any(t in title.lower() for t in terms):
            continue
        seen.add(url)
        cand.append({"title": title or "Video", "url": url,
                     "_score": _relevance_quality_score(title, "", terms)})
    # Best-first, then drop the internal score and keep the top few.
    cand.sort(key=lambda v: v["_score"], reverse=True)
    return [{"title": v["title"], "url": v["url"]} for v in cand[:3]]


# Filler words to strip so the image search uses the actual TOPIC, not the casual phrasing —
# "explain photosynthesis simply" → "photosynthesis". Prevents loosely-tagged, random images.
_FILLER = {
    "explain", "explanation", "understand", "understanding", "tell", "me", "about", "what",
    "is", "are", "was", "were", "the", "a", "an", "of", "in", "on", "for", "to", "how", "does",
    "do", "why", "please", "simple", "simply", "in", "detail", "topic", "concept", "give",
    "with", "graphs", "graph", "chart", "picture", "images", "image", "video", "and", "or",
    "study", "learn", "notes", "meaning", "define", "definition", "this", "that", "can", "you",
    # Follow-up / filler words — without these, "explain it again" leaves only "again" as the
    # topic term and matches a video literally titled "AGAIN - Meaning and Pronunciation".
    "again", "more", "further", "elaborate", "once", "bit", "little", "some", "it", "them",
    "detail", "details", "deeper", "briefly", "short", "shorter", "simpler", "example",
}


def _topic_terms(query: str) -> list[str]:
    """Content words of the query (topic), lower-cased, filler removed."""
    words = re.findall(r"[a-zA-Zऀ-ॿ]+", (query or "").lower())
    return [w for w in words if w not in _FILLER and len(w) > 2]


async def _serpapi_images(topic: str, terms: list[str]) -> list[dict]:
    """Google Images via SerpAPI (uses SERPAPI_API_KEY) — broad, well-ranked topical images."""
    if not settings.SERPAPI_API_KEY:
        return []
    from src.mcp.live.http import get_json
    data = await get_json(
        "https://serpapi.com/search.json",
        params={"engine": "google_images", "q": topic, "ijn": 0,
                "api_key": settings.SERPAPI_API_KEY},
    )
    out: list[dict] = []
    for r in ((data or {}).get("images_results") or []):
        thumb = r.get("thumbnail")
        if not thumb:
            continue
        out.append({
            "title": r.get("title", "") or topic,
            "url": r.get("original") or thumb,
            "thumbnail": thumb,
            "link": r.get("link", "") or r.get("source", ""),
            "source": r.get("source", "Google Images"),
        })
        if len(out) >= 4:
            break
    return out


async def _google_cse_images(topic: str, terms: list[str]) -> list[dict]:
    """Google Images via the Custom Search JSON API (GOOGLE_API_KEY + GOOGLE_CSE_ID)."""
    if not (settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID):
        return []
    from src.mcp.live.http import get_json
    data = await get_json(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": settings.GOOGLE_API_KEY, "cx": settings.GOOGLE_CSE_ID,
                "q": topic, "searchType": "image", "num": 5, "safe": "active"},
    )
    out: list[dict] = []
    for it in ((data or {}).get("items") or []):
        img = it.get("image", {}) or {}
        thumb = img.get("thumbnailLink") or it.get("link")
        if not thumb:
            continue
        out.append({
            "title": it.get("title", "") or topic,
            "url": it.get("link") or thumb,
            "thumbnail": thumb,
            "link": img.get("contextLink", "") or it.get("link", ""),
            "source": it.get("displayLink", "Google Images"),
        })
        if len(out) >= 4:
            break
    return out


async def _wikipedia_images(topic: str, terms: list[str]) -> list[dict]:
    """Keyless topical fallback — the lead image of the best-matching Wikipedia page(s)."""
    from src.mcp.live.http import get_json
    search = await get_json(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": topic,
                "format": "json", "srlimit": 5},
    )
    hits = (((search or {}).get("query") or {}).get("search")) or []
    # The PRIMARY topic word must appear in the page TITLE. Matching "any term anywhere in the
    # description" was too loose: for "explain geometry of quadrilaterals" the generic word
    # "geometry" matched Leonhard Euler's page and pulled his PORTRAIT into the answer. Requiring
    # the topic noun in the title keeps the image about the actual subject, never a tangential
    # person/place page.
    primary = terms[0] if terms else ""
    out: list[dict] = []
    for h in hits:
        title = h.get("title", "")
        if not title:
            continue
        if primary and primary not in title.lower():
            continue
        summ = await get_json(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}"
        )
        thumb = ((summ or {}).get("thumbnail") or {}).get("source")
        if not thumb:
            continue
        # Skip person pages (a portrait is almost never a good concept illustration).
        descr = ((summ or {}).get("description") or "").lower()
        if any(w in descr for w in ("born ", "mathematician", "physicist", "politician", "actor",
                                    "philosopher", "scientist", "economist", "author", "singer")):
            continue
        page = (((summ or {}).get("content_urls") or {}).get("desktop") or {}).get("page", "")
        out.append({
            "title": title,
            "url": ((summ or {}).get("originalimage") or {}).get("source") or thumb,
            "thumbnail": thumb,
            "link": page or f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
            "source": "Wikipedia",
        })
        if len(out) >= 3:
            break
    return out


async def _openverse_images(topic: str, terms: list[str]) -> list[dict]:
    """KEYLESS, query-based image search via Openverse (openly-licensed media). Unlike the old
    Wikipedia lead-image matching, Openverse ranks by relevance to the ACTUAL query, so results
    stay on-topic (no more Euler-for-geometry). A light title/tag relevance gate drops any stray
    result. This is what brings real photos back WITHOUT needing a paid API key."""
    from src.mcp.live.http import get_json
    data = await get_json(
        "https://api.openverse.org/v1/images/",
        params={"q": topic, "page_size": 8, "mature": "false"},
        headers={"User-Agent": "NipunAI/1.0 (citizen-assistance)"},
    )
    term_set = set(terms)
    out: list[dict] = []
    for r in ((data or {}).get("results") or []):
        thumb = r.get("thumbnail") or r.get("url")
        if not thumb:
            continue
        hay = (f"{r.get('title', '')} " + " ".join(t.get("name", "") for t in (r.get("tags") or []))).lower()
        if term_set and not any(t in hay for t in term_set):
            continue     # keep it on-topic
        out.append({
            "title": r.get("title", "") or topic,
            "url": r.get("url") or thumb,
            "thumbnail": thumb,
            "link": r.get("foreign_landing_url") or r.get("url", ""),
            "source": r.get("source", "Openverse"),
        })
        if len(out) >= 4:
            break
    return out


async def _images(query: str) -> list[dict]:
    """Topical images for a query, best-source-first: Google Images (SerpAPI/CSE) when a key is
    configured, then KEYLESS Openverse (openly-licensed, query-ranked → on-topic). All providers
    search the ACTUAL query, so images are relevant — no more loose Wikipedia lead-image matching
    that pulled in wrong pictures. Returns [] only when the topic is too vague or nothing fits."""
    terms = _topic_terms(query)
    if len(terms) < 1:
        return []
    topic = " ".join(terms[:6])
    for provider in (_serpapi_images, _google_cse_images, _openverse_images):
        try:
            imgs = await provider(topic, terms)
            if imgs:
                return imgs
        except Exception as exc:
            log.debug("image_provider_failed", provider=provider.__name__, error=str(exc))
    return []


# ── Shared image helpers (used by inline media + deliverable generation) ───────

async def best_image(query: str) -> dict | None:
    """The single most relevant online image for a topic (Google-first chain), or None."""
    imgs = await _images(query)
    return imgs[0] if imgs else None


async def _download(url: str) -> bytes | None:
    if not url:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and r.content:
                return r.content
    except Exception as exc:
        log.debug("image_download_failed", url=url[:80], error=str(exc))
    return None


async def _pollinations_image(prompt: str) -> tuple[bytes, str] | None:
    """FREE, keyless image generation via Pollinations.ai — returns the image bytes directly."""
    from urllib.parse import quote
    try:
        import httpx
        url = (f"https://image.pollinations.ai/prompt/{quote(prompt[:400])}"
               f"?width=1024&height=768&nologo=true")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.content and r.headers.get("content-type", "").startswith("image"):
                mime = "image/png" if r.content[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
                log.info("image_generated", provider="pollinations", prompt=prompt[:60])
                return r.content, mime
    except Exception as exc:
        log.debug("pollinations_failed", error=str(exc))
    return None


async def generate_image_bytes(prompt: str) -> tuple[bytes, str] | None:
    """Generate an image when none exists online — e.g. a specific illustration the user needs.
    Uses OpenAI DALL·E if a key is set (best quality); otherwise falls back to Pollinations.ai,
    which is FREE and keyless. Returns (bytes, mime) or None."""
    if settings.OPENAI_API_KEY:
        try:
            import base64

            import litellm
            resp = await litellm.aimage_generation(
                model="dall-e-3", prompt=prompt[:900], size="1024x1024",
                response_format="b64_json", api_key=settings.OPENAI_API_KEY,
            )
            log.info("image_generated", provider="openai", prompt=prompt[:60])
            return base64.b64decode(resp.data[0]["b64_json"]), "image/png"
        except Exception as exc:
            log.debug("openai_image_failed", error=str(exc))
    # Free keyless fallback.
    return await _pollinations_image(prompt)


async def image_bytes_for(query: str, allow_generate: bool = True) -> tuple[bytes, str] | None:
    """Best real image bytes for a topic; if none is available online AND generation is allowed
    and configured, generate one. Returns (bytes, mime) or None."""
    img = await best_image(query)
    if img:
        data = await _download(img.get("thumbnail") or img.get("url"))
        if data:
            mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            return data, mime
    if allow_generate:
        return await generate_image_bytes(query)
    return None


def _articles(knowledge_pool: list[dict], query: str) -> list[dict]:
    """Best reference links to read more — reuse the answer's own retrieved sources, but keep
    ONLY the ones actually about the topic (a source's title/text must share a topic word),
    so a loosely-matched book/paper from an ambiguous keyword search never leaks in."""
    terms = set(_topic_terms(query))
    out: list[dict] = []
    seen_hosts: set[str] = set()
    for k in knowledge_pool or []:
        url = k.get("source_url") or ""
        if not url.startswith(("http://", "https://")):
            continue
        host = _host(url)
        if not host or host in seen_hosts or _YT_RE.search(url):
            continue
        # Relevance gate: the source must clearly relate to the topic (skip when we can't tell).
        hay = f"{k.get('section','')} {k.get('source','')} {(k.get('text') or '')[:200]}".lower()
        if terms and not any(t in hay for t in terms):
            continue
        seen_hosts.add(host)
        title = k.get("section") or k.get("source") or host
        out.append({
            "title": title,
            "url": url,
            "source": k.get("source") or host,
            "_score": _relevance_quality_score(title, k.get("source") or host, terms),
        })
    # Rank best-first (relevance + reputable publisher), then drop the score and cap at 5.
    out.sort(key=lambda a: a["_score"], reverse=True)
    return [{"title": a["title"], "url": a["url"], "source": a["source"]} for a in out[:5]]


# ── Media-card promotion (present the answer AS a video / web page / book) ─────
# When the user PRIMARILY asked to watch a video, open a site, or read a book — and we have a
# REAL resource for it — present the answer as that media card so the frontend's Video/Browser/
# Book renderers light up. URLs are ONLY ever taken from real gathered resources / the answer's
# own retrieved sources, NEVER invented by the model. The `summary` text is preserved untouched,
# so the answer is unchanged; only the presentation is upgraded. No-op when nothing real matches.
_VIDEO_INTENT = re.compile(
    r"\b(video|watch|youtube|clip|lecture video|show me a video|play (a|the) video)\b", re.IGNORECASE)
_BROWSER_INTENT = re.compile(
    r"\b(open (the )?(website|site|page|portal)|official (site|website|portal|page)|"
    r"show (me )?the (website|site|page|portal)|live site|web ?page|visit (the )?site)\b", re.IGNORECASE)
_BOOK_INTENT = re.compile(
    r"\b(book|textbook|e-?book|novel|chapters?|read (a|the) book|full text of)\b", re.IGNORECASE)


def _first_real_url(sources, knowledge_pool) -> str | None:
    """First genuine http(s) URL from the answer's own sources, else its retrieved knowledge."""
    for s in (sources or []):
        url = s.get("url") if isinstance(s, dict) else None
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    for k in (knowledge_pool or []):
        url = (k or {}).get("source_url") or ""
        if isinstance(url, str) and url.startswith(("http://", "https://")) and not _YT_RE.search(url):
            return url
    return None


def _book_from_pool(knowledge_pool, title_hint: str) -> dict | None:
    """Assemble a book card from real book-sourced retrieved chunks (grouped into chapters by their
    source/section). Returns None unless there's genuine book content to show."""
    chapters: list[dict] = []
    book_title = ""
    for k in (knowledge_pool or []):
        text = (k or {}).get("text") or ""
        src = (k.get("source") or "")
        # Treat a chunk as book content when it carries a section (chapter) and real prose.
        if len(text) < 120:
            continue
        section = k.get("section") or ""
        if section or "book" in (k.get("retrieval_method", "") + src).lower():
            book_title = book_title or src
            chapters.append({"title": section or (src or "Excerpt"), "content": text[:1500]})
        if len(chapters) >= 4:
            break
    if not chapters:
        return None
    return {"title": book_title or title_hint or "Reader", "chapters": chapters}


def promote_media_card(card: dict, query: str, resources: dict | None = None,
                       knowledge_pool: list[dict] | None = None) -> dict:
    """Upgrade a plain answer card to a video / browser / book card when the user asked for that
    medium AND real media backs it. Only ever runs on a plain `answer` card, so a purposeful card
    (scheme_list, step_action, clarify, error, a diagram/table the model chose…) is never
    overridden. Best-effort and side-effect-free on the text."""
    if not isinstance(card, dict) or card.get("cardType") not in (None, "", "answer"):
        return card
    q = query or ""
    resources = resources or {}
    pool = knowledge_pool or []

    if _VIDEO_INTENT.search(q):
        vids = resources.get("videos") or []
        if vids and vids[0].get("url"):
            card["cardType"] = "video"
            card["url"] = vids[0]["url"]
            if not card.get("title"):
                card["title"] = vids[0].get("title") or "Video"
            log.info("media_card_promoted", to="video", url=vids[0]["url"][:80])
            return card

    if _BROWSER_INTENT.search(q):
        url = _first_real_url(card.get("sources"), pool)
        if url:
            card["cardType"] = "browser"
            card["url"] = url
            log.info("media_card_promoted", to="browser", url=url[:80])
            return card

    if _BOOK_INTENT.search(q):
        book = _book_from_pool(pool, card.get("title", ""))
        if book:
            card["cardType"] = "book"
            card["book"] = book
            log.info("media_card_promoted", to="book", chapters=len(book.get("chapters", [])))
            return card

    return card


async def gather_study_resources(
    query: str, domain: str, knowledge_pool: list[dict], correlation_id: str = "",
) -> dict | None:
    """Collect the supplementary 'explore more' resources — VIDEOS + read-more article LINKS.
    (Images are placed INLINE in the answer where they help, not gathered here.) Best-effort;
    returns None when nothing useful was found so the caller simply omits the section."""
    try:
        videos = await _videos(query)
    except Exception as exc:   # pragma: no cover - defensive
        log.debug("study_resources_failed", error=str(exc), correlation_id=correlation_id)
        videos = []
    videos = videos if isinstance(videos, list) else []
    articles = _articles(knowledge_pool, query)

    if not (videos or articles):
        return None
    resources = {"videos": videos, "articles": articles}
    log.info("study_resources_gathered", videos=len(videos), articles=len(articles),
             correlation_id=correlation_id)
    return resources
