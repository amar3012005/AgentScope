"""Wrap HIVE-MIND JSON-RPC as an agentscope StatefulClientBase.

This is a thin adapter that makes :class:`HivemindMCPClient` (httpx-based
JSON-RPC) compatible with agentscope's ``toolkit.register_mcp_client()``
mechanism.  Because HIVE-MIND exposes a custom JSON-RPC endpoint rather
than standard MCP SSE/stdio transport, we override the lifecycle methods
(``connect``, ``close``, ``list_tools``, ``get_callable_function``) to
delegate to the inner client.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types

from agentscope.mcp._stateful_client_base import StatefulClientBase
from agentscope.mcp._mcp_function import MCPToolFunction

from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient

logger = logging.getLogger(__name__)


class _HivemindToolFunction(MCPToolFunction):
    """MCPToolFunction subclass that delegates execution to
    :class:`HivemindMCPClient` instead of a real ``ClientSession``.
    """

    def __init__(
        self,
        mcp_name: str,
        tool: mcp.types.Tool,
        inner_client: HivemindMCPClient,
        wrap_tool_result: bool = True,
    ) -> None:
        # MCPToolFunction requires exactly one of client_gen / session.
        # We pass a dummy session and immediately override __call__.
        # Using object.__new__ to avoid the parent's validation.
        self.mcp_name = mcp_name
        self.name = tool.name
        self.description = tool.description
        self.json_schema = _extract_input_schema(tool)
        self.wrap_tool_result = wrap_tool_result
        self.timeout = None
        self.client_gen = None
        self.session = None
        self._inner = inner_client

    async def __call__(self, **kwargs: Any) -> Any:
        """Call the HIVE-MIND tool via JSON-RPC."""
        raw = await self._inner.call_tool(self.name, kwargs)
        payload = self._inner._extract_tool_payload(raw)
        if self.wrap_tool_result:
            return mcp.types.CallToolResult(
                content=[
                    mcp.types.TextContent(
                        type="text",
                        text=json.dumps(payload, default=str),
                    ),
                ],
            )
        return payload


def _extract_input_schema(tool: mcp.types.Tool) -> dict[str, Any]:
    """Pull a JSON-schema dict from an ``mcp.types.Tool``."""
    schema = dict(tool.inputSchema) if tool.inputSchema else {}
    # Ensure required top-level keys expected by agentscope
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


class HivemindStatefulClient(StatefulClientBase):
    """AgentScope MCP adapter for HIVE-MIND JSON-RPC.

    Usage::

        client = HivemindStatefulClient(
            name="hivemind",
            rpc_url="http://localhost:8050/api/mcp/rpc",
            api_key="...",
        )
        await client.connect()
        toolkit.register_mcp_client(client)
    """

    def __init__(
        self,
        name: str,
        rpc_url: str,
        api_key: str,
        timeout_seconds: int = 45,
        poll_interval_seconds: float = 1.0,
        poll_attempts: int = 10,
    ) -> None:
        super().__init__(name=name)
        self._inner = HivemindMCPClient(
            rpc_url=rpc_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            poll_attempts=poll_attempts,
        )

    # ------------------------------------------------------------------
    # Lifecycle overrides — no real transport to manage
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Discover tools from HIVE-MIND and mark as connected."""
        if self.is_connected:
            raise RuntimeError(
                "The MCP server is already connected. Call close() "
                "before connecting again.",
            )
        raw = await self._inner.tools_list()
        tools_data = raw.get("tools", [])
        self._cached_tools = [
            mcp.types.Tool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
            )
            for t in tools_data
            if isinstance(t, dict) and "name" in t
        ]
        # Set a sentinel so parent's _validate_connection doesn't fail
        # on the ``self.session`` check.  We have no real MCP session.
        self.session = True  # type: ignore[assignment]
        self.is_connected = True
        logger.info(
            "HivemindStatefulClient connected — discovered %d tools",
            len(self._cached_tools),
        )

    async def close(self, ignore_errors: bool = True) -> None:
        """Mark as disconnected. No transport to tear down."""
        if not self.is_connected:
            raise RuntimeError(
                "The MCP server is not connected. Call connect() before closing.",
            )
        self._cached_tools = None
        self.session = None
        self.is_connected = False
        logger.info("HivemindStatefulClient closed.")

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[mcp.types.Tool]:
        """Return the cached tool list discovered during ``connect()``."""
        self._validate_connection()
        return self._cached_tools or []

    # ------------------------------------------------------------------
    # Tool invocation
    # ------------------------------------------------------------------

    async def get_callable_function(
        self,
        func_name: str,
        wrap_tool_result: bool = True,
        execution_timeout: float | None = None,
    ) -> _HivemindToolFunction:
        """Return a callable that delegates to HIVE-MIND JSON-RPC."""
        self._validate_connection()

        if self._cached_tools is None:
            await self.list_tools()

        target_tool: mcp.types.Tool | None = None
        for tool in self._cached_tools:
            if tool.name == func_name:
                target_tool = tool
                break

        if target_tool is None:
            raise ValueError(
                f"Tool '{func_name}' not found in the HIVE-MIND server",
            )

        return _HivemindToolFunction(
            mcp_name=self.name,
            tool=target_tool,
            inner_client=self._inner,
            wrap_tool_result=wrap_tool_result,
        )

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Convenience: call a HIVE-MIND tool and return structured result."""
        self._validate_connection()
        raw = await self._inner.call_tool(name, arguments or {})
        payload = self._inner._extract_tool_payload(raw)
        return {
            "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        }
