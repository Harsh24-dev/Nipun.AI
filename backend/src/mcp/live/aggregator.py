"""
Live-knowledge aggregator.

`gather_live_knowledge()` is the single entry point the orchestrator uses. It picks
the right tools for a query (by domain / intent / keywords), runs them concurrently,
and returns their output as CITED knowledge chunks (same shape as retrieved chunks)
so the normal grade → generate → verify path can ground and cite the answer.

Tool output is DATA: any embedded-instruction attempts (surfaced by the guards) are
dropped from the grounding text, never executed.
"""

from __future__ import annotations

import asyncio
import re

import structlog

from src.config import settings
from src.core.logging import trace_flow
from src.mcp.base import ToolResult

log = structlog.get_logger("mcp.live.aggregator")

# Keywords that mean "this needs fresh/live data the static index won't have".
_LIVE_WORDS = (
    "today", "now", "current", "currently", "latest", "live", "right now", "this week",
    "this month", "recent", "price", "rate", "stock", "share", "market", "weather",
    "forecast", "news", "breaking", "trending", "aaj", "abhi", "आज", "अभी", "भाव",
)
_RESEARCH_WORDS = ("research", "paper", "study", "findings", "journal", "arxiv", "book",
                   "books", "syllabus", "reskill", "re-skill", "upskill", "course", "learn",
                   "prepare for", "become a", "career", "exam", "textbook")
_JOB_WORDS = ("job", "jobs", "vacancy", "vacancies", "opening", "openings", "hiring",
              "recruitment", "naukri", "internship", "apply for", "job portal",
              "job opportunity", "walk-in", "placement", "career opportunity")
# Learning / "explain this concept" cues — such queries answer best when grounded in real
# study material (books + papers) alongside the web, not the web alone.
_LEARN_WORDS = ("explain", "understand", "concept", "theory of", "topic", "study", "learn",
                "meaning of", "introduction to", "basics of", "fundamentals", "how does",
                "difference between", "revise", "notes on", "teach me")


def needs_live_data(query: str, domain: str, intent: str) -> bool:
    """True when a query is time-sensitive or research/book-oriented enough that we
    should pull live sources even if the static index returned something."""
    q = (query or "").lower()
    if (any(w in q for w in _LIVE_WORDS) or any(w in q for w in _RESEARCH_WORDS)
            or any(w in q for w in _JOB_WORDS) or any(w in q for w in _LEARN_WORDS)):
        return True
    return domain in ("finance", "farming", "travel", "career", "student", "jobs")


# Citizen-service domains where the answer must be India-specific (laws, schemes, prices, jobs,
# offices, procedures). For these we bias the web/news search to Indian sources. Knowledge
# domains (student/career/general — often global tech/science) are left global so a question
# like "how does RAG work" isn't wrongly narrowed to India.
_INDIA_DOMAINS = frozenset({
    "scheme", "governance", "legal", "farming", "finance", "jobs", "documents", "booking", "health",
})
_INDIA_MENTIONED = re.compile(
    r"\b(india|indian|bharat|भारत|नौकरी|योजना)\b", re.IGNORECASE)


# Shopping / price / deal intents — an Indian user wants Indian stores and ₹ prices, not US
# results in USD. Scope these to India regardless of domain (they usually classify as general/
# student), so "best laptop deal" returns Amazon.in / Flipkart, not Best Buy.
_SHOPPING_TERMS = re.compile(
    r"\b(buy|deal|deals|price|prices|pricing|cost|cheapest|order|purchase|discount|offer|"
    r"under\s*[₹rs]|available now|best.*(laptop|phone|mobile|tv|fridge|ac))\b", re.IGNORECASE)


def _india_scoped(query: str, domain: str) -> str:
    """Append 'India' to a search query so results are locally relevant (Indian sources, ₹
    prices), unless the user already named India or a place. Applies to India-specific domains
    AND to any shopping/price/deal query (which usually classify as general/student)."""
    if _INDIA_MENTIONED.search(query or ""):
        return query
    if domain in _INDIA_DOMAINS or _SHOPPING_TERMS.search(query or ""):
        return f"{query} India".strip()
    return query


def _select_tools(query: str, domain: str, intent: str) -> list[tuple[str, dict]]:
    """Return (tool_name, params) pairs to run for this query. web_search is always
    included as the credible-grounding baseline."""
    q = (query or "").lower()
    is_india = domain in _INDIA_DOMAINS
    # India-first: for citizen-service domains, ground the web search in Indian sources.
    picks: list[tuple[str, dict]] = [("web_search", {"query": _india_scoped(query, domain)})]

    # Wikipedia as a broad, citeable knowledge baseline for ANY informational topic — always
    # pulled unless the query is a pure transaction (booking/payment/job-apply), where it adds
    # nothing. Runs in parallel with web_search, so it grounds answers on any subject the user
    # asks about without slowing the response.
    _transactional = domain in ("booking", "jobs") or any(
        w in q for w in ("book ", "pay ", "recharge", "apply for", "fill the form"))
    if not _transactional:
        picks.append(("wikipedia", {"query": query}))

    if domain == "finance" or any(w in q for w in ("stock", "share", "market", "nifty", "sensex", "mutual fund")):
        picks.append(("finance", {"query": query}))
    if "weather" in q or "forecast" in q or "rain" in q or domain == "travel":
        picks.append(("weather", {"location": _guess_location(query)}))
    if domain == "farming" or "mandi" in q or "भाव" in q or "crop price" in q:
        picks.append(("mandi_prices", {"commodity": _guess_commodity(query)}))
    if any(w in q for w in ("news", "latest", "breaking", "current affairs", "trending")):
        # Scope news to Indian sources for citizen-service topics; global otherwise.
        news_params = {"query": query}
        if is_india:
            news_params["country"] = "India"
        picks.append(("news", news_params))
    if any(w in q for w in ("research", "paper", "study", "findings", "journal", "arxiv")):
        picks.append(("scholar", {"query": query}))
    if any(w in q for w in ("book", "books", "textbook", "syllabus", "become a", "career", "reskill", "upskill", "course")):
        picks.append(("books", {"query": query}))
        picks.append(("scholar", {"query": query}))
    # Learning / "explain this" queries already ground well on Wikipedia + web (added above).
    # Only pull the SLOWER book/paper tools when the ask is genuinely research/exam-oriented — a
    # basic "explain quadrilaterals" must not wait on Google Books + Semantic Scholar (frequently
    # rate-limited, seconds of retry). YouTube grounding (transcript fetch) is dropped from the
    # hot path entirely: video LINKS still appear via study-resources, without the slow transcript
    # download. Both changes cut several seconds off a typical explain query.
    if (any(w in q for w in _LEARN_WORDS) or domain == "student") and any(w in q for w in _RESEARCH_WORDS):
        picks.append(("books", {"query": query}))
        picks.append(("scholar", {"query": query}))
    # Job discovery: real, currently-open roles across popular portals + remote boards.
    if domain == "jobs" or any(w in q for w in _JOB_WORDS):
        picks.append(("job_search", {"query": query, "location": _guess_location(query)}))

    # De-dup while preserving order.
    seen, out = set(), []
    for name, params in picks:
        if name not in seen:
            seen.add(name)
            out.append((name, params))
    return out


def _guess_location(query: str) -> str:
    import re
    m = re.search(r"\b(?:in|at|for)\s+([A-Z][a-zA-Z]+)", query)
    return m.group(1) if m else query


def _guess_commodity(query: str) -> str:
    for c in ("wheat", "rice", "onion", "potato", "tomato", "cotton", "sugarcane", "maize", "soybean"):
        if c in query.lower():
            return c
    return ""


def _to_chunks(tool_name: str, result: ToolResult) -> list[dict]:
    """Turn a tool's structured results into knowledge-chunk dicts for grounding."""
    chunks: list[dict] = []
    for i, r in enumerate(result.data.get("results", []) or []):
        text = (r.get("content") or "").strip()
        if not text:
            continue
        chunks.append({
            "chunk_id": f"{tool_name}:{i}",
            "text": text,
            "source": r.get("source") or tool_name,
            "source_url": r.get("url", ""),
            "section": r.get("title", ""),
            "relevance_score": 1.0 - i * 0.02,
            "retrieval_method": "live_tool",
            "live": True,
        })
    # Some tools only fill `text` (no results list) — keep it as one chunk.
    if not chunks and result.status == "ok" and result.text:
        chunks.append({
            "chunk_id": f"{tool_name}:0", "text": result.text,
            "source": tool_name, "source_url": "", "section": "",
            "relevance_score": 0.9, "retrieval_method": "live_tool", "live": True,
        })
    return chunks


async def _pick_tools(query: str, domain: str, intent: str, correlation_id: str) -> list[tuple[str, dict]]:
    """Choose which tools to call: LLM-decided when enabled (the brain picks per prompt), else the
    deterministic keyword selector. India-scopes web/news queries so results stay locally relevant."""
    if settings.LLM_TOOL_SELECTION:
        from src.mcp.live.selector import select_tools_llm
        picks = await select_tools_llm(query, domain, intent, correlation_id)
        if picks:
            scoped: list[tuple[str, dict]] = []
            for name, params in picks:
                if name == "web_search" and params.get("query"):
                    params = {**params, "query": _india_scoped(params["query"], domain)}
                elif name == "news" and domain in _INDIA_DOMAINS:
                    params = {**params, "country": "India"}
                scoped.append((name, params))
            return scoped
    return _select_tools(query, domain, intent)


async def gather_live_knowledge(
    query: str, domain: str, intent: str = "", correlation_id: str = "",
) -> list[dict]:
    """Run the selected live tools and return cited knowledge chunks (may be empty)."""
    if not settings.WEB_TOOLS_ENABLED:
        return []

    from src.mcp.tools import get_tool

    selected = await _pick_tools(query, domain, intent, correlation_id)
    trace_flow("live_tools_selected", correlation_id=correlation_id, domain=domain,
               tools=[name for name, _ in selected])

    async def _run(name: str, params: dict) -> tuple[str, ToolResult | None]:
        tool = get_tool(name)
        if tool is None:
            return name, None
        return name, await tool.call(params)

    # Overall wall-clock cap on the fan-out: run every tool concurrently but stop waiting after
    # LIVE_AUGMENT_TIMEOUT. Tools that finished contribute their chunks; stragglers are cancelled
    # and dropped, so one slow upstream can't blow the latency budget (partial results are kept —
    # strictly better than discarding everything, and the RAG loop still has static + parametric
    # knowledge to fall back on).
    tasks = [asyncio.create_task(_run(n, p)) for n, p in selected]
    pairs: list = []
    if tasks:
        done, pending = await asyncio.wait(tasks, timeout=settings.LIVE_AUGMENT_TIMEOUT)
        for t in pending:
            t.cancel()
        if pending:
            log.warning("live_tools_timed_out", dropped=len(pending), completed=len(done),
                        timeout_s=settings.LIVE_AUGMENT_TIMEOUT, correlation_id=correlation_id)
        for t in done:
            try:
                pairs.append(t.result())
            except Exception:
                continue

    knowledge: list[dict] = []
    used: list[str] = []
    for pair in pairs:
        if isinstance(pair, Exception) or pair is None:
            continue
        name, result = pair
        if result is None:
            continue
        if result.suspected_instructions:
            log.warning("live_tool_suspected_injection", tool=name,
                        suspects=result.suspected_instructions, correlation_id=correlation_id)
        if result.status == "ok":
            chunks = _to_chunks(name, result)
            knowledge.extend(chunks)
            if chunks:
                used.append(name)

    trace_flow("live_knowledge_gathered", correlation_id=correlation_id,
               tools_used=used, chunks=len(knowledge),
               sources=[k["source"] for k in knowledge])
    log.info("live_knowledge_gathered", tools_used=used, chunks=len(knowledge),
             correlation_id=correlation_id)
    return knowledge
