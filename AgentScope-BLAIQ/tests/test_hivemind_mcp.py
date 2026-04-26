import httpx

import pytest

from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient


def test_extract_tool_payload_parses_json_string_text():
    payload = {
        "content": [
            {
                "type": "text",
                "text": '{"results":[{"id":"mem-1","title":"Deck brief","content":"Enterprise deck context"}],"metadata":{"requestId":"abc"}}',
            }
        ]
    }

    extracted = HivemindMCPClient._extract_tool_payload(payload)

    assert extracted["results"][0]["id"] == "mem-1"
    assert extracted["metadata"]["requestId"] == "abc"


@pytest.mark.asyncio
async def test_rpc_timeout_is_wrapped_with_context(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("agentscope_blaiq.runtime.hivemind_mcp.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    client = HivemindMCPClient(rpc_url="https://example.com/rpc", api_key="test", timeout_seconds=3)

    with pytest.raises(Exception) as excinfo:
        await client.tools_list()

    assert "HIVE-MIND RPC calling tools/list" in str(excinfo.value)
    assert "timed out after" in str(excinfo.value)
