"""
MCP tool framework.

Every external capability is an MCP tool with a uniform interface. Tool OUTPUTS are
treated as untrusted DATA (wrapped via the guards), never as instructions. Tools that
need an API key/network report `unavailable` and degrade gracefully.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import structlog

from src.core.metrics import TOOL_CALLS_TOTAL
from src.execution.guards import assert_no_credentials, wrap_untrusted

log = structlog.get_logger("mcp.base")


@dataclass
class ToolResult:
    tool: str
    status: str                      # ok | unavailable | error | blocked
    data: dict = field(default_factory=dict)
    text: str = ""                   # human-readable summary
    suspected_instructions: list[str] = field(default_factory=list)


class MCPTool(ABC):
    name: str = "base_tool"
    description: str = ""
    read_only: bool = True           # read-only tools are safe to call without confirmation

    @abstractmethod
    async def _call(self, params: dict) -> ToolResult:
        ...

    async def call(self, params: dict) -> ToolResult:
        # Guard: never let credentials flow into a tool / third-party form.
        try:
            assert_no_credentials(params)
        except Exception as exc:
            TOOL_CALLS_TOTAL.labels(tool=self.name, status="blocked").inc()
            log.warning("tool_call_blocked", tool=self.name, error=str(exc))
            return ToolResult(tool=self.name, status="blocked", text=str(exc))

        try:
            result = await self._call(params)
        except Exception as exc:
            TOOL_CALLS_TOTAL.labels(tool=self.name, status="error").inc()
            log.warning("tool_call_error", tool=self.name, error=str(exc))
            return ToolResult(tool=self.name, status="error", text=str(exc))

        # Treat the tool's textual output as untrusted DATA; surface any embedded instructions.
        if result.text:
            wrapped = wrap_untrusted(self.name, result.text)
            result.suspected_instructions = wrapped.suspected_instructions
        TOOL_CALLS_TOTAL.labels(tool=self.name, status=result.status).inc()
        return result
