"""
Tests for HarnessToolAdapter: schema validation, permission enforcement,
Toolkit registration, and build_toolkit_from_harnesses factory.
"""

from __future__ import annotations

import pytest

from agentscope_blaiq.contracts.harness import ToolHarness

try:
    from agentscope_blaiq.runtime.adapters.tool_adapter import (
        HarnessToolAdapter,
        build_toolkit_from_harnesses,
    )
    _ADAPTER_AVAILABLE = True
except ImportError:
    _ADAPTER_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="runtime adapters not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_harness(**overrides) -> ToolHarness:
    defaults = dict(
        tool_id="test_tool",
        owner_agent="test_agent",
        purpose="Used for testing the harness adapter.",
        description="A test tool",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        output_schema={"type": "object"},
    )
    defaults.update(overrides)
    return ToolHarness(**defaults)


def _sync_fn(**kwargs):
    return {"result": f"ok: {kwargs}"}


# ---------------------------------------------------------------------------
# TestHarnessToolAdapter — basic wrapping
# ---------------------------------------------------------------------------

class TestHarnessToolAdapter:
    def test_adapter_wraps_callable(self):
        harness = _make_tool_harness()
        adapter = HarnessToolAdapter(harness, _sync_fn)
        assert adapter is not None

    async def test_valid_input_calls_fn(self):
        harness = _make_tool_harness()
        adapter = HarnessToolAdapter(harness, _sync_fn)
        result = await adapter._validated_fn(query="hello", limit=5)
        assert result["result"].startswith("ok:")

    async def test_missing_required_field_raises(self):
        harness = _make_tool_harness()
        adapter = HarnessToolAdapter(harness, _sync_fn)
        with pytest.raises(Exception):
            await adapter._validated_fn(limit=5)  # missing required "query"

    async def test_extra_fields_pass_through(self):
        harness = _make_tool_harness()
        adapter = HarnessToolAdapter(harness, _sync_fn)
        result = await adapter._validated_fn(query="hello", extra_field="ignored")
        assert "result" in result

    async def test_wrong_type_rejected(self):
        harness = _make_tool_harness()
        adapter = HarnessToolAdapter(harness, _sync_fn)
        with pytest.raises(Exception):
            await adapter._validated_fn(query=123)  # query must be string


# ---------------------------------------------------------------------------
# TestHarnessToolAdapterNoSchema — tools without strict schemas
# ---------------------------------------------------------------------------

class TestHarnessToolAdapterNoSchema:
    async def test_no_schema_allows_any_input(self):
        harness = _make_tool_harness(input_schema={"type": "object"})
        adapter = HarnessToolAdapter(harness, _sync_fn)
        # No required fields, anything passes
        result = await adapter._validated_fn(anything="goes")
        assert "result" in result


# ---------------------------------------------------------------------------
# TestBuildToolkitFromHarnesses — factory
# ---------------------------------------------------------------------------

class TestBuildToolkitFromHarnesses:
    def test_builds_toolkit_with_matching_fns(self):
        harness = _make_tool_harness(tool_id="my_tool")
        toolkit = build_toolkit_from_harnesses(
            tool_harnesses=[harness],
            tool_fns={"my_tool": _sync_fn},
        )
        assert toolkit is not None

    def test_unmatched_harness_skipped(self):
        harness = _make_tool_harness(tool_id="my_tool")
        # No matching fn provided — should not raise, just skip
        toolkit = build_toolkit_from_harnesses(
            tool_harnesses=[harness],
            tool_fns={},
        )
        assert toolkit is not None

    def test_unmatched_fn_skipped(self):
        harness = _make_tool_harness(tool_id="real_tool")
        toolkit = build_toolkit_from_harnesses(
            tool_harnesses=[harness],
            tool_fns={"real_tool": _sync_fn, "ghost_tool": _sync_fn},
        )
        assert toolkit is not None

    def test_multiple_tools_registered(self):
        harnesses = [
            _make_tool_harness(tool_id="tool_a"),
            _make_tool_harness(tool_id="tool_b"),
        ]
        fns = {
            "tool_a": lambda **kw: {"r": "a"},
            "tool_b": lambda **kw: {"r": "b"},
        }
        toolkit = build_toolkit_from_harnesses(tool_harnesses=harnesses, tool_fns=fns)
        assert toolkit is not None
