"""
Time-sensitive Indian public data: weather, mandi (market) prices, and news.

  * WeatherTool — Open-Meteo (fully keyless): geocode a place → current + daily forecast.
  * MandiTool   — Agmarknet via data.gov.in (needs DATA_GOV_IN_API_KEY / AGMARKNET_API_KEY).
  * NewsTool    — GDELT DOC 2.0 (keyless) for recent news; NewsAPI if NEWSAPI_KEY set.
"""

from __future__ import annotations

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult
from src.mcp.live.http import get_json

log = structlog.get_logger("mcp.live.data")

_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 61: "light rain",
    63: "moderate rain", 65: "heavy rain", 80: "rain showers", 95: "thunderstorm",
}


class WeatherTool(MCPTool):
    name = "weather"
    description = "Current weather + forecast for an Indian location (Open-Meteo, keyless)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        place = (params.get("location") or params.get("city") or "").strip()
        if not place:
            return ToolResult(self.name, "error", text="weather requires a 'location'.")
        log.info("weather_call", location=place)
        geo = await get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place, "count": 1, "country": "IN"},
        )
        loc = ((geo or {}).get("results") or [None])[0]
        if not loc:
            return ToolResult(self.name, "unavailable", text=f"Could not locate '{place}'.")
        wx = await get_json(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                    "timezone": "Asia/Kolkata", "forecast_days": 3},
        )
        if not wx:
            return ToolResult(self.name, "unavailable", text=f"Could not fetch weather for {place}.")
        cur = wx.get("current", {})
        cond = _WMO.get(cur.get("weather_code"), "")
        name = f"{loc.get('name')}, {loc.get('admin1', '')}".strip(", ")
        text = (f"Weather in {name}: {cur.get('temperature_2m')}°C, {cond}, "
                f"humidity {cur.get('relative_humidity_2m')}%, wind {cur.get('wind_speed_10m')} km/h.")
        log.info("weather_ok", location=name, temp_c=cur.get("temperature_2m"))
        return ToolResult(self.name, "ok",
                          data={"current": cur, "daily": wx.get("daily", {}), "location": name,
                                "results": [{"title": f"Weather — {name}",
                                "url": "https://open-meteo.com/", "content": text,
                                "source": "Open-Meteo"}]},
                          text=text)


class MandiTool(MCPTool):
    name = "mandi_prices"
    description = "Current mandi (market) prices for a commodity (Agmarknet / data.gov.in)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        commodity = (params.get("commodity") or "").strip()
        state = (params.get("state") or "").strip()
        log.info("mandi_call", commodity=commodity or None, state=state or None)
        key = (settings.DATA_GOV_IN_API_KEY or settings.AGMARKNET_API_KEY or "").strip()
        # A real data.gov.in key is a single hex-ish token; a value with whitespace or a
        # leading '#' is a placeholder/inline-comment, not a key — don't fire a doomed
        # 403 request (which would also leak the junk value into logs via the URL).
        if not key or " " in key or key.startswith("#"):
            log.warning("mandi_unavailable_no_key", configured=bool(key))
            return ToolResult(self.name, "unavailable",
                              text="Mandi price API key (data.gov.in) not configured.")
        api_params = {"api-key": key, "format": "json", "limit": settings.LIVE_MAX_RESULTS}
        if commodity:
            api_params["filters[commodity]"] = commodity
        if state:
            api_params["filters[state]"] = state
        data = await get_json(
            "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070",
            params=api_params,
        )
        records = (data or {}).get("records") or []
        if not records:
            return ToolResult(self.name, "unavailable",
                              text=f"No mandi price records for {commodity or 'that commodity'}.")
        lines = [f"{r.get('commodity')} at {r.get('market')}, {r.get('state')}: "
                 f"₹{r.get('modal_price')}/quintal (min ₹{r.get('min_price')}, max ₹{r.get('max_price')})"
                 for r in records[: settings.LIVE_MAX_RESULTS]]
        text = "Mandi prices — " + "; ".join(lines)
        return ToolResult(self.name, "ok",
                          data={"records": records,
                                "results": [{"title": "Mandi prices (Agmarknet)",
                                "url": "https://agmarknet.gov.in/", "content": text,
                                "source": "Agmarknet / data.gov.in"}]},
                          text=text)


class NewsTool(MCPTool):
    name = "news"
    description = "Recent news headlines on a topic (GDELT keyless / NewsAPI)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        query = (params.get("query") or params.get("topic") or "").strip()
        if not query:
            return ToolResult(self.name, "error", text="news requires a 'query'.")
        log.info("news_call", query=query[:60])

        if settings.NEWSAPI_KEY:
            data = await get_json(
                "https://newsapi.org/v2/everything",
                params={"q": query, "sortBy": "publishedAt", "pageSize": settings.LIVE_MAX_RESULTS,
                        "language": "en", "apiKey": settings.NEWSAPI_KEY},
            )
            arts = (data or {}).get("articles") or []
            if arts:
                results = [{"title": a.get("title", ""), "url": a.get("url", ""),
                            "content": a.get("description") or a.get("title", ""),
                            "source": (a.get("source") or {}).get("name", "NewsAPI")}
                           for a in arts[: settings.LIVE_MAX_RESULTS]]
                text = " | ".join(r["title"] for r in results)
                return ToolResult(self.name, "ok", data={"results": results}, text=text)

        # Keyless GDELT. Scope to India-published sources when asked (India-first app), so a
        # citizen gets locally-relevant news rather than global coverage.
        gdelt_query = query
        if str(params.get("country") or params.get("region") or "").lower() in ("in", "india"):
            if "sourcecountry:" not in gdelt_query.lower():
                gdelt_query = f"{query} sourcecountry:India"
        data = await get_json(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": gdelt_query, "mode": "ArtList", "maxrecords": settings.LIVE_MAX_RESULTS,
                    "format": "json", "sort": "DateDesc"},
        )
        arts = (data or {}).get("articles") or []
        if not arts:
            return ToolResult(self.name, "unavailable", text=f"No recent news found for '{query}'.")
        results = [{"title": a.get("title", ""), "url": a.get("url", ""),
                    "content": f"{a.get('title', '')} — {a.get('domain', '')} ({a.get('seendate', '')})",
                    "source": a.get("domain", "GDELT")}
                   for a in arts[: settings.LIVE_MAX_RESULTS]]
        text = " | ".join(r["title"] for r in results)
        return ToolResult(self.name, "ok", data={"results": results}, text=text)
