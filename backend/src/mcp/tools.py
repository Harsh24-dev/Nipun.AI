"""
Concrete MCP tools.

These wrap official/live sources. Where an API key/network is required and absent, the
tool returns `unavailable` (never fabricates). Time-sensitive facts (mandi price,
weather, live case citations) come from these tools at query time, not the static index.
"""

from __future__ import annotations

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult

log = structlog.get_logger("mcp.tools")


class IndianKanoonTool(MCPTool):
    name = "indiankanoon"
    description = "Search Indian case law / statutes on IndianKanoon (live legal citations)."

    async def _call(self, params: dict) -> ToolResult:
        query = params.get("query", "")
        if not settings.INDIANKANOON_API_KEY:
            return ToolResult(self.name, "unavailable",
                              text="IndianKanoon API key not configured; cannot fetch live citations.")
        # Real HTTP call would go here (httpx). Kept as a guarded stub until keys exist.
        return ToolResult(self.name, "unavailable", text=f"(live search for '{query}' requires configured API access)")


class AgmarknetTool(MCPTool):
    name = "agmarknet"
    description = "Fetch current mandi (market) prices for a commodity from Agmarknet."

    async def _call(self, params: dict) -> ToolResult:
        commodity = params.get("commodity", "")
        state = params.get("state", "")
        if not (settings.DATA_GOV_IN_API_KEY or settings.AGMARKNET_API_KEY):
            return ToolResult(self.name, "unavailable",
                              text="Agmarknet API key not configured; showing MSP guidance only.")
        return ToolResult(self.name, "unavailable",
                          text=f"(live mandi price for {commodity} in {state} requires configured API access)")


class IMDWeatherTool(MCPTool):
    name = "imd_weather"
    description = "Fetch weather/forecast for a location from IMD open data."

    async def _call(self, params: dict) -> ToolResult:
        location = params.get("location", "")
        if not settings.IMD_API_KEY:
            return ToolResult(self.name, "unavailable",
                              text="IMD API key not configured; cannot fetch live weather.")
        return ToolResult(self.name, "unavailable",
                          text=f"(live weather for {location} requires configured API access)")


class DigiLockerTool(MCPTool):
    name = "digilocker"
    description = "Retrieve a user's issued documents from DigiLocker (with user consent)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        # Never accepts credentials (enforced by base.call). Real integration requires the
        # user's consented OAuth flow — not raw credentials.
        return ToolResult(self.name, "unavailable",
                          text="DigiLocker access requires the user's consented OAuth session.")


# ── Live-data tools (web + credible sources) ──────────────────────────────────
from src.mcp.live.apps import DriveTool, GmailTool
from src.mcp.live.data import MandiTool, NewsTool, WeatherTool
from src.mcp.live.finance import FinanceTool
from src.mcp.live.jobs import JobSearchTool
from src.mcp.live.knowledge import WikipediaTool
from src.mcp.live.research import BooksTool, ScholarTool
from src.mcp.live.shopping import ShoppingTool
from src.mcp.live.web import WebFetchTool, WebSearchTool
from src.mcp.live.youtube import YouTubeTool

# ── Registry ──────────────────────────────────────────────────────────────────
_TOOLS: dict[str, MCPTool] = {
    t.name: t for t in (
        # Legacy guarded stubs.
        IndianKanoonTool(), AgmarknetTool(), IMDWeatherTool(), DigiLockerTool(),
        # Live web + credible-source tools.
        WebSearchTool(), WebFetchTool(),
        FinanceTool(),
        WeatherTool(), MandiTool(), NewsTool(),
        ScholarTool(), BooksTool(),
        JobSearchTool(),
        YouTubeTool(),
        WikipediaTool(),
        ShoppingTool(),
        GmailTool(), DriveTool(),
    )
}


def get_tool(name: str) -> MCPTool | None:
    return _TOOLS.get(name)


def list_tools() -> list[dict]:
    return [{"name": t.name, "description": t.description, "read_only": t.read_only} for t in _TOOLS.values()]
