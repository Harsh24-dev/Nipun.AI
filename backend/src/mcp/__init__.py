"""MCP tool layer — external capabilities as uniform, guarded tools."""

from src.mcp.base import MCPTool, ToolResult
from src.mcp.tools import get_tool, list_tools
from src.mcp.live import gather_live_knowledge

__all__ = ["MCPTool", "ToolResult", "get_tool", "list_tools", "gather_live_knowledge"]
