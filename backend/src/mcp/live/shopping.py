"""
Shopping / product-finder tool.

Helps a user BUY well: searches the web for a product across India's major retail
platforms, extracts price + rating from the results, ranks the options, and returns a
comparison the user can act on — each option carries the platform to buy from, a WORKING
product/search link, the price, the rating, and WHY that platform is a sound choice
(returns, warranty, delivery, authenticity). Best-effort price-history guidance is
included; a real price-tracker (Keepa-style) can plug in via `PRICE_HISTORY_PROVIDER`.

Contract (same as other live tools): output is untrusted DATA, no credentials handled,
absent keys degrade gracefully. Product discovery reuses the keyless web-search chain, so
it works with no extra API keys; adding a shopping/price API just makes it richer.
"""

from __future__ import annotations

import asyncio
import re

import structlog

from src.mcp.base import MCPTool, ToolResult

log = structlog.get_logger("mcp.live.shopping")

# Curated trust notes for India's major platforms — WHY a user might buy there. Keyed by a
# substring of the result URL's host. This is what turns a raw link into a helpful choice.
_PLATFORMS: dict[str, dict[str, str]] = {
    "amazon.": {"name": "Amazon India",
                "why": "Wide selection, easy 7–10 day returns, genuine-product guarantee, fast delivery."},
    "flipkart.": {"name": "Flipkart",
                  "why": "Strong in electronics & mobiles, no-cost EMI, easy returns, Plus benefits."},
    "myntra.": {"name": "Myntra", "why": "Best for fashion & footwear, try-and-buy, easy 14-day returns."},
    "ajio.": {"name": "AJIO", "why": "Fashion & lifestyle, frequent brand discounts, Reliance-backed."},
    "nykaa.": {"name": "Nykaa", "why": "Authentic beauty & personal care, brand-verified stock."},
    "croma.": {"name": "Croma", "why": "Tata electronics retailer, in-store support, extended warranty options."},
    "reliancedigital.": {"name": "Reliance Digital",
                         "why": "Electronics with ResQ after-sales service and installation support."},
    "tatacliq.": {"name": "Tata CLiQ", "why": "Tata-backed, 100% authentic, good for premium brands."},
    "meesho.": {"name": "Meesho", "why": "Lowest prices on everyday items; check seller ratings before buying."},
    "jiomart.": {"name": "JioMart", "why": "Groceries & essentials, wide India delivery, frequent offers."},
    "vijaysales.": {"name": "Vijay Sales", "why": "Trusted electronics retailer with demo + service support."},
}

_PRICE = re.compile(r"(?:₹|rs\.?\s?|inr\s?)\s?([\d,]{3,})", re.IGNORECASE)
_RATING = re.compile(r"([0-4](?:\.\d)?|5(?:\.0)?)\s*(?:/\s*5|stars?|out of 5|★)", re.IGNORECASE)


def _platform_for(url: str) -> dict | None:
    host = (url or "").lower()
    for key, meta in _PLATFORMS.items():
        if key in host:
            return meta
    return None


def _parse_price(text: str) -> int | None:
    m = _PRICE.search(text or "")
    if not m:
        return None
    try:
        value = int(m.group(1).replace(",", ""))
        return value if 50 <= value <= 5_000_000 else None   # ignore junk matches
    except ValueError:
        return None


def _parse_rating(text: str) -> float | None:
    m = _RATING.search(text or "")
    if not m:
        return None
    try:
        r = float(m.group(1))
        return r if 0 < r <= 5 else None
    except ValueError:
        return None


def rank_products(results: list[dict], budget: int | None = None) -> list[dict]:
    """Turn raw search results into ranked, buy-ready product options.

    Prefers: a recognised trusted platform, then in-budget, then higher rating, then
    lower price. Only results that map to a known retail platform become 'options';
    the rest are kept as supporting references."""
    options: list[dict] = []
    for r in results or []:
        url = r.get("url") or ""
        platform = _platform_for(url)
        if not platform or not url:
            continue
        blob = f"{r.get('title','')} {r.get('content','')}"
        price = _parse_price(blob)
        rating = _parse_rating(blob)
        options.append({
            "title": (r.get("title") or "").strip()[:140],
            "platform": platform["name"],
            "why_platform": platform["why"],
            "url": url,
            "price_inr": price,
            "rating": rating,
            "snippet": (r.get("content") or "").strip()[:240],
            "in_budget": (budget is None or price is None or price <= budget),
        })

    def sort_key(o: dict):
        return (
            0 if o["in_budget"] else 1,
            -(o["rating"] or 0),
            o["price_inr"] if o["price_inr"] is not None else 10**9,
        )

    options.sort(key=sort_key)
    # De-dupe by platform+title so one platform doesn't dominate the top.
    seen, deduped = set(), []
    for o in options:
        key = (o["platform"], o["title"][:40])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(o)
    return deduped


def _price_history_note(product: str) -> str:
    return (
        "Tip: prices swing on sale events (Amazon Great Indian Festival, Flipkart Big "
        "Billion Days, end-of-season). If it's not urgent, check a price-history tool "
        "(e.g. a Keepa-style tracker) before buying — a lower recent price often returns."
    )


class ShoppingTool(MCPTool):
    name = "shopping"
    description = ("Find the best product to buy across Indian platforms — compares price, "
                   "ratings and reviews, with working buy links and why each platform is trustworthy.")
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        product = (params.get("product") or params.get("query") or "").strip()
        if not product:
            return ToolResult(self.name, "error", text="shopping requires a 'product' to search for.")
        budget = params.get("budget")
        try:
            budget = int(str(budget).replace(",", "").replace("₹", "").strip()) if budget else None
        except (TypeError, ValueError):
            budget = None

        from src.mcp.tools import get_tool

        # Two angled searches: buy/price intent + reviews — run concurrently, merged for ranking.
        web = get_tool("web_search")
        merged: list[dict] = []
        if web is not None:
            queries = (f"{product} price buy India", f"{product} review rating best")
            responses = await asyncio.gather(
                *[web.call({"query": q}) for q in queries],
                return_exceptions=True,
            )
            for res in responses:
                if isinstance(res, Exception):
                    log.debug("shopping_search_failed", error=str(res))
                    continue
                if res.status == "ok":
                    merged.extend(res.data.get("results", []))

        options = rank_products(merged, budget=budget)
        if not options:
            log.info("shopping_no_platform_matches", product=product[:60])
            return ToolResult(
                self.name, "unavailable",
                data={"results": merged[:5], "products": []},
                text=(f"I couldn't identify specific store listings for '{product}'. "
                      f"Try adding a brand or model, and I'll compare buy options."),
            )

        top = options[:5]
        lines = [
            f"{o['platform']}: {o['title']}"
            + (f" — ₹{o['price_inr']:,}" if o['price_inr'] else "")
            + (f", {o['rating']}★" if o['rating'] else "")
            for o in top
        ]
        text = "Buy options — " + " | ".join(lines)
        log.info("shopping_ok", product=product[:60], options=len(top),
                 platforms=[o["platform"] for o in top])
        return ToolResult(
            self.name, "ok",
            data={
                "product": product,
                "budget": budget,
                "products": top,
                "price_history_note": _price_history_note(product),
                # Supporting references (reviews/guides) for grounding + citations.
                "results": merged[:6],
            },
            text=text,
        )


def build_shopping_card(product: str, options: list[dict], language: str = "en",
                        price_history_note: str = "") -> dict:
    """Render ranked buy options into a comparison card with working links + reasons."""
    rows = [
        {
            "Product": o["title"] or product,
            "Platform": o["platform"],
            "Price": f"₹{o['price_inr']:,}" if o.get("price_inr") else "See link",
            "Rating": f"{o['rating']}★" if o.get("rating") else "—",
            "Why here": o["why_platform"],
            "Buy": o["url"],
        }
        for o in options
    ]
    best = options[0] if options else None
    return {
        "cardType": "comparison_table",
        "language": language,
        "title": f"Best ways to buy: {product}",
        "summary": (
            (f"Top pick: {best['platform']} — {best['why_platform']} " if best else "")
            + "Compare the options below. Prices and ratings are from live search; open the "
            + "link to confirm the current price before buying. "
            + (price_history_note or "")
        ),
        "plan_cols": ["Product", "Platform", "Price", "Rating", "Why here", "Buy"],
        "plan_rows": rows,
        "options": [f"Buy on {o['platform']}" for o in options],
        "sources": [{"text": o["platform"], "url": o["url"]} for o in options],
        "disclaimer": ("Prices/stock change constantly — always confirm on the retailer's page. "
                       "We never ask for your card, OTP, or password; you pay directly on the store."),
    }
