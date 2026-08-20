"""
LLM-driven tool selection — the brain decides WHICH MCP data-source tools to call for a query,
instead of a keyword table. Given the query (with its domain/intent) and a catalog of tools with
"when to use" notes, a fast LLM returns the relevant tools + a focused search string for each.

Grounded and safe: only tools in the catalog are honoured, and the caller falls back to the
deterministic keyword selector if the LLM is unavailable — so live augmentation never breaks.
"""

from __future__ import annotations

import json

import structlog

from src.llm.router import route_completion

log = structlog.get_logger("mcp.live.selector")

# The selectable tools and WHEN each helps — this grounds the LLM's choice in what actually exists.
_TOOL_CATALOG: dict[str, str] = {
    "web_search": "General current, credible web information. The safe default for almost any "
                  "factual, current, how-to, price, or comparison question.",
    "wikipedia": "Encyclopedic background on a concept, place, person, event, or organisation.",
    "news": "Latest news, current affairs, or a breaking/recent event.",
    "finance": "Stock / share / index / mutual-fund market data and prices.",
    "weather": "Current weather or forecast for a specific location.",
    "mandi_prices": "Indian agricultural commodity (mandi) prices for a crop.",
    "scholar": "Academic research papers, studies, or scientific findings on a topic.",
    "books": "Textbook / book references for a subject, syllabus, or exam.",
    "youtube": "Educational explainer videos (their transcripts) to learn/understand a concept.",
    "job_search": "Currently-open job vacancies / recruitment listings.",
}

_SELECT_SYSTEM = """You decide which DATA-SOURCE TOOLS to call to best answer an Indian user's
query. Pick ONLY tools that materially help — usually 1 to 3, never all of them. `web_search` is a
safe default for most factual/current questions. Skip tools irrelevant to THIS query (e.g. do not
pick `weather` unless it's about weather, `finance` unless about markets, `job_search` unless about
jobs).

Available tools:
{catalog}

Respond STRICT JSON only:
{{"tools": [{{"name": "<tool>", "query": "<a focused search string for that tool>"}}]}}
Special params: weather → {{"name":"weather","location":"<place>"}};
mandi_prices → {{"name":"mandi_prices","commodity":"<crop>"}}."""


def _clean_json(text: str) -> str:
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1].split("```")[0].replace("json", "", 1).strip()
    if not t.startswith("{"):
        s, e = t.find("{"), t.rfind("}")
        if s != -1 and e > s:
            t = t[s:e + 1]
    return t


async def select_tools_llm(
    query: str, domain: str, intent: str, correlation_id: str = "",
) -> list[tuple[str, dict]] | None:
    """Ask a fast LLM which tools to call. Returns [(tool_name, params)] or None on failure
    (caller then falls back to the deterministic keyword selector)."""
    try:
        catalog = "\n".join(f"- {n}: {d}" for n, d in _TOOL_CATALOG.items())
        resp = await route_completion(
            messages=[
                {"role": "system", "content": _SELECT_SYSTEM.format(catalog=catalog)},
                {"role": "user", "content": f"Domain: {domain}. Intent: {intent}.\nQUERY: {query}"},
            ],
            override_tier="fast", correlation_id=correlation_id,
        )
        data = json.loads(_clean_json(resp.content))
    except Exception as exc:
        log.warning("tool_select_llm_failed", error=str(exc), correlation_id=correlation_id)
        return None

    out: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for t in (data.get("tools", []) if isinstance(data, dict) else []):
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if name not in _TOOL_CATALOG or name in seen:
            continue
        seen.add(name)
        if name == "weather":
            params = {"location": t.get("location") or t.get("query") or query}
        elif name == "mandi_prices":
            params = {"commodity": t.get("commodity") or ""}
        else:
            params = {"query": t.get("query") or query}
        out.append((name, params))
    if out:
        log.info("tool_select_llm", tools=[n for n, _ in out], correlation_id=correlation_id)
    return out or None
