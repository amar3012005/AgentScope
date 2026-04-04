"""Tests for HivemindStatefulClient — agentscope MCP adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import mcp.types
import pytest

from agentscope_blaiq.mcp.hivemind_stateful import HivemindStatefulClient


def _make_client() -> HivemindStatefulClient:
    return HivemindStatefulClient(
        name="hivemind-test",
        rpc_url="http://fake:8050/api/mcp/rpc",
        api_key="test-key",
    )


MOCK_TOOLS_RESPONSE: dict[str, Any] = {
    "tools": [
        {
            "name": "hivemind_recall",
            "description": "Recall memories",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "hivemind_web_search",
            "description": "Web search",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    ],
}


# ── connect / lifecycle ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_fetches_tools() -> None:
    client = _make_client()
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=MOCK_TOOLS_RESPONSE,
    ):
        await client.connect()

    assert client.is_connected
    tools = await client.list_tools()
    assert len(tools) == 2
    assert all(isinstance(t, mcp.types.Tool) for t in tools)
    tool_names = [t.name for t in tools]
    assert "hivemind_recall" in tool_names
    assert "hivemind_web_search" in tool_names


@pytest.mark.asyncio
async def test_connect_twice_raises() -> None:
    client = _make_client()
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=MOCK_TOOLS_RESPONSE,
    ):
        await client.connect()
        with pytest.raises(RuntimeError, match="already connected"):
            await client.connect()


@pytest.mark.asyncio
async def test_close_resets_state() -> None:
    client = _make_client()
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=MOCK_TOOLS_RESPONSE,
    ):
        await client.connect()

    await client.close()
    assert not client.is_connected


@pytest.mark.asyncio
async def test_close_without_connect_raises() -> None:
    client = _make_client()
    with pytest.raises(RuntimeError, match="not connected"):
        await client.close()


@pytest.mark.asyncio
async def test_list_tools_before_connect_raises() -> None:
    client = _make_client()
    with pytest.raises(RuntimeError):
        await client.list_tools()


# ── call_tool ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_tool_delegates() -> None:
    client = _make_client()
    rpc_result = {
        "content": [{"type": "text", "text": '{"memories": []}'}],
    }
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=MOCK_TOOLS_RESPONSE,
    ):
        await client.connect()

    with patch.object(
        client._inner,
        "call_tool",
        new_callable=AsyncMock,
        return_value=rpc_result,
    ):
        result = await client.call_tool("hivemind_recall", {"query": "test", "limit": 5})

    assert result is not None
    assert "content" in result
    content_text = result["content"][0]["text"]
    parsed = json.loads(content_text)
    assert isinstance(parsed, dict)
    assert "memories" in parsed


# ── get_callable_function ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_callable_function() -> None:
    client = _make_client()
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=MOCK_TOOLS_RESPONSE,
    ):
        await client.connect()

    fn = await client.get_callable_function("hivemind_recall")
    assert fn.name == "hivemind_recall"
    assert fn.description == "Recall memories"
    assert "properties" in fn.json_schema


@pytest.mark.asyncio
async def test_get_callable_function_not_found() -> None:
    client = _make_client()
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=MOCK_TOOLS_RESPONSE,
    ):
        await client.connect()

    with pytest.raises(ValueError, match="not found"):
        await client.get_callable_function("nonexistent_tool")


@pytest.mark.asyncio
async def test_callable_function_invocation() -> None:
    client = _make_client()
    rpc_result = {
        "content": [{"type": "text", "text": '{"memories": ["a", "b"]}'}],
    }
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=MOCK_TOOLS_RESPONSE,
    ):
        await client.connect()

    fn = await client.get_callable_function("hivemind_recall")

    with patch.object(
        client._inner,
        "call_tool",
        new_callable=AsyncMock,
        return_value=rpc_result,
    ):
        result = await fn(query="test")

    assert isinstance(result, mcp.types.CallToolResult)
    assert len(result.content) == 1
    text_content = result.content[0]
    assert isinstance(text_content, mcp.types.TextContent)
    parsed = json.loads(text_content.text)
    assert parsed["memories"] == ["a", "b"]


# ── edge cases ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_with_empty_tools() -> None:
    client = _make_client()
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value={"tools": []},
    ):
        await client.connect()

    assert client.is_connected
    tools = await client.list_tools()
    assert tools == []


@pytest.mark.asyncio
async def test_connect_skips_malformed_tools() -> None:
    client = _make_client()
    malformed = {
        "tools": [
            {"name": "good_tool", "description": "works", "inputSchema": {"type": "object"}},
            "not a dict",
            {"no_name_key": True},
        ],
    }
    with patch.object(
        client._inner,
        "tools_list",
        new_callable=AsyncMock,
        return_value=malformed,
    ):
        await client.connect()

    tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "good_tool"
