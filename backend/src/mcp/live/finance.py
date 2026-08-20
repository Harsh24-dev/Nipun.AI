"""
Finance / stock-market data.

Keyless by default via Yahoo Finance public JSON endpoints (chart for a symbol,
predefined screener for market movers). If ALPHA_VANTAGE_API_KEY is set, uses Alpha
Vantage for richer top gainers/losers. Directly answers "highest moving stock",
"price of X", "today's top gainers" style queries with cited, current numbers.

Not investment advice — the finance agent's disclaimer still applies downstream.
"""

from __future__ import annotations

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult
from src.mcp.live.http import get_json

log = structlog.get_logger("mcp.live.finance")

_MOVER_WORDS = ("mover", "gainer", "loser", "highest moving", "top stock", "trending stock",
                "best stock", "market today", "nifty", "sensex", "biggest")


async def _yahoo_quote(symbol: str) -> dict | None:
    data = await get_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"interval": "1d", "range": "5d"},
    )
    result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change_pct = None
    if price is not None and prev:
        change_pct = round((price - prev) / prev * 100, 2)
    return {
        "symbol": meta.get("symbol", symbol),
        "price": price,
        "currency": meta.get("currency", ""),
        "exchange": meta.get("exchangeName", ""),
        "change_pct": change_pct,
        "prev_close": prev,
    }


async def _yahoo_movers(scr_id: str = "day_gainers") -> list[dict] | None:
    data = await get_json(
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved",
        params={"scrIds": scr_id, "count": settings.LIVE_MAX_RESULTS},
    )
    quotes = (((data or {}).get("finance") or {}).get("result") or [{}])[0].get("quotes") or []
    out = []
    for q in quotes[: settings.LIVE_MAX_RESULTS]:
        out.append({
            "symbol": q.get("symbol", ""),
            "name": q.get("shortName") or q.get("longName", ""),
            "price": q.get("regularMarketPrice"),
            "change_pct": q.get("regularMarketChangePercent"),
            "exchange": q.get("fullExchangeName", ""),
        })
    return out or None


async def _alpha_vantage_movers() -> list[dict] | None:
    if not settings.ALPHA_VANTAGE_API_KEY:
        return None
    data = await get_json(
        "https://www.alphavantage.co/query",
        params={"function": "TOP_GAINERS_LOSERS", "apikey": settings.ALPHA_VANTAGE_API_KEY},
    )
    gainers = (data or {}).get("top_gainers") or []
    out = [
        {"symbol": g.get("ticker", ""), "name": g.get("ticker", ""),
         "price": g.get("price"), "change_pct": g.get("change_percentage", "")}
        for g in gainers[: settings.LIVE_MAX_RESULTS]
    ]
    return out or None


class FinanceTool(MCPTool):
    name = "finance"
    description = "Live stock quotes and market movers (Yahoo Finance keyless / Alpha Vantage)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or "").lower()
        symbol = (params.get("symbol") or "").strip().upper()
        log.info("finance_call", symbol=symbol or None, query=query[:60] or None)

        # Explicit symbol → quote.
        if symbol:
            q = await _yahoo_quote(symbol)
            if q and q.get("price") is not None:
                text = (f"{q['symbol']}: {q['price']} {q['currency']} "
                        f"({q['change_pct']:+}% vs prev close {q['prev_close']}) on {q['exchange']}.")
                log.info("finance_quote_ok", symbol=q["symbol"], price=q["price"], change_pct=q["change_pct"])
                return ToolResult(self.name, "ok",
                                  data={"quote": q,
                                        "results": [{"title": f"{q['symbol']} quote", "url":
                                        f"https://finance.yahoo.com/quote/{q['symbol']}",
                                        "content": text, "source": "Yahoo Finance"}]},
                                  text=text)

        # Movers / "highest moving" style queries.
        if not symbol or any(w in query for w in _MOVER_WORDS):
            movers = await _alpha_vantage_movers() or await _yahoo_movers("day_gainers")
            if movers:
                lines = [f"{m['symbol']} ({m.get('name','')}): {m.get('price')} "
                         f"({m.get('change_pct')}%)" for m in movers]
                text = "Top market movers (day gainers): " + "; ".join(lines)
                log.info("finance_movers_ok", count=len(movers))
                return ToolResult(self.name, "ok",
                                  data={"movers": movers,
                                        "results": [{"title": "Top market movers today",
                                        "url": "https://finance.yahoo.com/gainers",
                                        "content": text, "source": "Yahoo Finance"}]},
                                  text=text)

        log.warning("finance_unavailable", symbol=symbol or None, query=query[:60] or None)
        return ToolResult(self.name, "unavailable",
                          text="Could not fetch live market data; falling back to web search.")
