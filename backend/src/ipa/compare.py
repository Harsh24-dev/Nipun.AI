"""
Compare options across sources, then surface only the FEW BEST, TRUSTED ones.

For a booking/shopping task the agent should NOT blindly commit to one site. It first gathers
evidence across reputable sources (via the existing web_search tool — Tavily API — plus any
category API), has an LLM extract and rank concrete options on price / rating / reliability, and
returns the top few. Every option is passed through the trust gate, so a fake or unknown site is
never shown — protecting the user's confidence in the app. The user picks one; the agent then
executes on that option.

API-first: where a category has a direct API/tool in the app (weather, finance, jobs…), prefer it
over scraping. Otherwise reputable web sources are compared. New booking APIs plug in here.
"""

from __future__ import annotations

import json

from src.core.logging import get_ipa_logger
from src.ipa.targets import detect_category, is_trusted
from src.llm.router import route_completion

log = get_ipa_logger("ipa.compare")

# Categories where multiple genuine providers exist and a comparison helps. Official single-source
# tasks (train→IRCTC, bills, government) are NOT compared — there is one authoritative site.
_COMPARABLE = {"flight", "hotel", "bus", "shopping", "food", "grocery", "movies"}


def is_comparable(goal: str) -> bool:
    cat = detect_category(goal)
    q = (goal or "").lower()
    if cat in _COMPARABLE:
        log.debug("is_comparable", result=True, reason="category", category=cat)
        return True
    keyword = any(w in q for w in ("compare", "cheapest", "best price", "best option", "which is better",
                                   "reviews", "top rated", "vs ", "recommend the best"))
    log.debug("is_comparable", result=keyword, reason="keyword", category=cat)
    return keyword


_EXTRACT_SYSTEM = """From the search evidence, extract the BEST concrete options for the user's
task and rank them. Use ONLY facts present in the evidence — never invent prices, ratings, or
sites. Prefer official/reputable providers, better price, and better reviews/reliability.

Respond STRICT JSON only:
{"options": [
  {"name": "provider/product name", "provider": "site it's on", "url": "https URL on that site",
   "price": "e.g. ₹1,250 or 'varies'", "rating": "e.g. 4.3/5 or ''",
   "reliability": "high|medium|unknown", "why": "one line why it's a good pick",
   "pros": ["..."], "cons": ["..."]}
] }
Return the 3-4 BEST options, best first. If the evidence has no credible options, return
{"options": []}."""


def _clean_json(text: str) -> str:
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1].split("```")[0].replace("json", "", 1).strip()
    if not t.startswith("{"):
        s, e = t.find("{"), t.rfind("}")
        if s != -1 and e > s:
            t = t[s:e + 1]
    return t


async def gather_options(goal: str, answers: dict, correlation_id: str = "") -> list[dict]:
    """Return the few best, TRUSTED options for a task (may be empty). Never raises."""
    detail = " ".join(str(v) for v in (answers or {}).values() if v)
    query = f"{goal} {detail}".strip()
    log.info("gather_options_start", goal=(goal or "")[:120], correlation_id=correlation_id)
    # India-first unless a place is already named — an Indian user wants ₹ prices and Indian stores.
    import re as _re
    place = " in India" if not _re.search(r"\b(india|indian|usa|uk|dubai|us\b)\b", query.lower()) else ""
    evidence: list[dict] = []
    try:
        from src.mcp.tools import get_tool
        web = get_tool("web_search")
        if web is None:
            log.warning("compare_web_tool_unavailable", correlation_id=correlation_id)
        else:
            res = await web.call({"query": f"best {query}{place} — price, reviews, reliability, compare"})
            log.debug("compare_search_result", status=res.status, correlation_id=correlation_id)
            if res.status == "ok":
                results = res.data.get("results") or []
                for r in results:
                    url = r.get("url", "")
                    if is_trusted(url):     # only reputable sources feed the comparison
                        evidence.append({"title": r.get("title", ""), "url": url,
                                         "content": (r.get("content") or "")[:600],
                                         "source": r.get("source", "")})
                    else:
                        log.debug("compare_source_dropped", reason="untrusted", url=url,
                                  correlation_id=correlation_id)
                log.info("compare_evidence_collected", raw=len(results), trusted=len(evidence),
                         correlation_id=correlation_id)
    except Exception as exc:
        log.warning("compare_search_failed", error=str(exc), error_type=type(exc).__name__,
                    correlation_id=correlation_id)

    if not evidence:
        log.info("gather_options_no_evidence", correlation_id=correlation_id)
        return []

    try:
        ev_text = "\n\n".join(f"[{e['source']}] {e['title']}\n{e['url']}\n{e['content']}" for e in evidence[:8])
        resp = await route_completion(
            messages=[{"role": "system", "content": _EXTRACT_SYSTEM},
                      {"role": "user", "content": f"TASK: {query}\n\nEVIDENCE:\n{ev_text}"}],
            override_tier="primary", correlation_id=correlation_id,
        )
        data = json.loads(_clean_json(resp.content))
        options = data.get("options", []) if isinstance(data, dict) else []
        log.debug("compare_extracted", count=len(options), correlation_id=correlation_id)
    except Exception as exc:
        log.warning("compare_extract_failed", error=str(exc), error_type=type(exc).__name__,
                    correlation_id=correlation_id)
        return []

    # Final trust gate + dedupe + cap. An option with an untrusted or missing URL is dropped.
    clean, seen = [], set()
    for o in options:
        if not isinstance(o, dict):
            continue
        url = str(o.get("url", "")).strip()
        if not is_trusted(url) or url in seen:
            log.debug("compare_option_dropped", url=url, trusted=is_trusted(url),
                      duplicate=url in seen, correlation_id=correlation_id)
            continue
        seen.add(url)
        clean.append({
            "name": str(o.get("name", ""))[:80], "provider": str(o.get("provider", ""))[:40],
            "url": url, "price": str(o.get("price", ""))[:40], "rating": str(o.get("rating", ""))[:20],
            "reliability": o.get("reliability") if o.get("reliability") in ("high", "medium", "unknown") else "unknown",
            "why": str(o.get("why", ""))[:160],
            "pros": [str(p)[:80] for p in (o.get("pros") or [])][:3],
            "cons": [str(c)[:80] for c in (o.get("cons") or [])][:3],
        })
        if len(clean) >= 4:
            break
    log.info("compare_options", count=len(clean), correlation_id=correlation_id)
    return clean
