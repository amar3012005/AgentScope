from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agentscope_blaiq.contracts.tool_telemetry import (
    build_tool_drift,
    normalize_executed_tool_event,
    normalize_plan_nodes,
)
from agentscope_blaiq.runtime.agent_base import BaseAgent


class _DummyAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="DummyAgent", role="research", sys_prompt="You are a dummy.")


def test_tool_wrapper_emits_started_finished_and_failed_events():
    agent = _DummyAgent()
    captured: list[tuple[str, str, str, dict | None]] = []

    async def sink(message: str, kind: str, visibility: str, detail: dict | None = None) -> None:
        captured.append((message, kind, visibility, detail))

    agent.set_log_sink(sink)

    async def happy_tool(value: str) -> dict[str, str]:
        return {"value": value}

    wrapped = agent.instrument_tool("demo_tool", happy_tool)
    result = asyncio.run(wrapped(value="hello"))

    assert result == {"value": "hello"}
    assert [item[1] for item in captured] == ["tool_call_started", "tool_call_finished"]
    assert captured[0][3]["tool_id"] == "demo_tool"
    assert captured[0][3]["input_hash"]
    assert captured[1][3]["output_summary"]["kind"] == "dict"
    assert captured[1][3]["duration_ms"] >= 0

    captured.clear()

    async def failing_tool(value: str) -> None:
        raise RuntimeError("boom")

    wrapped_fail = agent.instrument_tool("demo_tool", failing_tool)
    with pytest.raises(RuntimeError):
        asyncio.run(wrapped_fail(value="hello"))

    assert [item[1] for item in captured] == ["tool_call_started", "tool_call_failed"]
    assert captured[-1][3]["error_code"] == "RuntimeError"


def test_normalize_legacy_tool_events_to_canonical_runtime_types():
    record = SimpleNamespace(
        sequence=1,
        event_type="tool_call",
        thread_id="thread-1",
        run_id="run-1",
        agent_name="research",
        payload_json=json.dumps(
            {
                "type": "tool_call",
                "run_id": "run-1",
                "thread_id": "thread-1",
                "agent_name": "research",
                "data": {
                    "detail": {
                        "tool_id": "hivemind_recall",
                        "node_id": "research",
                        "call_id": "call-1",
                    }
                },
            }
        ),
        created_at=SimpleNamespace(isoformat=lambda: "2026-04-23T00:00:00+00:00"),
    )

    normalized = normalize_executed_tool_event(record)

    assert normalized["event_type"] == "tool_call_started"
    assert normalized["tool_id"] == "hivemind_recall"
    assert normalized["node_id"] == "research"
    assert normalized["status"] == "running"


def test_normalize_plan_and_drift_split_planned_vs_executed_tools():
    plan = {
        "workflow_template_id": "visual_artifact_v1",
        "workflow_mode": "hybrid",
        "artifact_family": "pitch_deck",
        "required_tools_per_node": {
            "research": ["hivemind_recall", "hivemind_query_with_ai"],
            "content_director": ["render_brief_generation"],
        },
        "task_graph": {
            "nodes": [
                {
                    "node_id": "research",
                    "agent_id": "research",
                    "assigned_to": "research",
                    "depends_on": [],
                    "required_capabilities": ["memory_retrieval"],
                    "parallel_group": None,
                    "requires_approval": False,
                },
                {
                    "node_id": "content_director",
                    "agent_id": "content_director",
                    "assigned_to": "content_director",
                    "depends_on": ["research"],
                    "required_capabilities": [],
                    "parallel_group": None,
                    "requires_approval": False,
                },
            ]
        },
    }
    plan_nodes = normalize_plan_nodes(plan)

    assert plan_nodes[0]["required_tools"] == ["hivemind_recall", "hivemind_query_with_ai"]
    assert plan_nodes[0]["required_capabilities"] == ["memory_retrieval"]

    executed_events = [
        {
            "node_id": "research",
            "tool_id": "hivemind_recall",
        }
    ]
    drift = build_tool_drift(plan_nodes, executed_events)

    assert drift["summary"]["planned_tool_count"] == 3
    assert drift["summary"]["executed_tool_count"] == 1
    assert drift["summary"]["matched_count"] == 1
    assert drift["summary"]["planned_only_count"] == 2
    assert drift["summary"]["executed_only_count"] == 0
