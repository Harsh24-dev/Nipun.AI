"""
Live-data MCP tools — fetch accurate, current information from the internet and
credible sources so the assistant can ground answers it can't find in the static
index (stock prices, weather, mandi rates, news, research papers, books, etc.).

Every tool here follows the Phase-6 contract:
  * output is untrusted DATA (wrapped by MCPTool.call), never instructions;
  * an absent API key → `unavailable`, never fabricated data;
  * no tool ever handles raw credentials (enforced by the base guard).

The orchestrator calls `gather_live_knowledge()` (aggregator) to turn tool output
into cited knowledge chunks for grounding + verification.
"""

from src.mcp.live.aggregator import gather_live_knowledge

__all__ = ["gather_live_knowledge"]
