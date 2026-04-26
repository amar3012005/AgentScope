from __future__ import annotations

import json
from typing import Any

_EXECUTED_TOOL_EVENT_TYPES = {
    "tool_call",
    "tool_result",
    "tool_error",
    "tool_call_started",
    "tool_call_finished",
    "tool_call_failed",
}


def normalize_tool_event_type(event_type: str | None) -> str:
    return {
        "tool_call": "tool_call_started",
        "tool_result": "tool_call_finished",
        "tool_error": "tool_call_failed",
    }.get(event_type or "", event_type or "tool_call_started")


def tool_event_status(event_type: str) -> str:
    return {
        "tool_call_started": "running",
        "tool_call_finished": "complete",
        "tool_call_failed": "error",
    }.get(event_type, "running")


def extract_tool_detail(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    detail = data.get("detail")
    if isinstance(detail, dict):
        return detail
    if isinstance(data, dict):
        return data
    return {}


def normalize_executed_tool_event(record: Any) -> dict[str, Any]:
    payload = json.loads(record.payload_json)
    event_type = normalize_tool_event_type(record.event_type or payload.get("type"))
    detail = extract_tool_detail(payload)
    data = payload.get("data") or {}
    return {
        "sequence": record.sequence,
        "event_type": event_type,
        "thread_id": record.thread_id,
        "run_id": record.run_id or payload.get("run_id"),
        "agent_name": record.agent_name,
        "node_id": data.get("node_id") or detail.get("node_id"),
        "tool_id": detail.get("tool_id") or data.get("tool_id"),
        "call_id": detail.get("call_id") or data.get("call_id"),
        "status": tool_event_status(event_type),
        "timestamp": payload.get("timestamp") or record.created_at.isoformat(),
        "duration_ms": detail.get("duration_ms"),
        "input_hash": detail.get("input_hash"),
        "input_preview": detail.get("input_preview"),
        "output_summary": detail.get("output_summary"),
        "error_code": detail.get("error_code"),
        "payload": payload,
    }


def normalize_plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    task_graph = plan.get("task_graph") or {}
    graph_nodes = task_graph.get("nodes") or []
    required_tools_per_node = plan.get("required_tools_per_node") or {}
    node_assignments = plan.get("node_assignments") or {}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for node in graph_nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("node_id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        normalized.append(
            {
                "node_id": node_id,
                "agent_name": node.get("agent_id") or node.get("assigned_to") or node_assignments.get(node_id),
                "assigned_to": node.get("assigned_to") or node_assignments.get(node_id),
                "depends_on": node.get("depends_on") or [],
                "required_tools": list(required_tools_per_node.get(node_id) or node.get("required_tools") or []),
                "required_capabilities": list(node.get("required_capabilities") or []),
                "parallel_group": node.get("parallel_group"),
                "requires_approval": bool(node.get("requires_approval", False)),
                "source": "workflow_plan",
            }
        )

    for node_id, tools in required_tools_per_node.items():
        if node_id in seen:
            continue
        seen.add(node_id)
        normalized.append(
            {
                "node_id": node_id,
                "agent_name": node_assignments.get(node_id),
                "assigned_to": node_assignments.get(node_id),
                "depends_on": [],
                "required_tools": list(tools or []),
                "required_capabilities": [],
                "parallel_group": None,
                "requires_approval": False,
                "source": "workflow_plan.required_tools_per_node",
            }
        )

    return normalized


def build_tool_drift(plan_nodes: list[dict[str, Any]], executed_events: list[dict[str, Any]]) -> dict[str, Any]:
    planned_pairs = {
        (node["node_id"], tool_id)
        for node in plan_nodes
        for tool_id in node.get("required_tools", [])
        if node.get("node_id") and tool_id
    }
    executed_pairs = {
        (event.get("node_id"), event.get("tool_id"))
        for event in executed_events
        if event.get("node_id") and event.get("tool_id")
    }
    matched = sorted(planned_pairs & executed_pairs)
    planned_only = sorted(planned_pairs - executed_pairs)
    executed_only = sorted(executed_pairs - planned_pairs)
    incomplete_plan = any(
        not node.get("required_tools") and node.get("required_capabilities")
        for node in plan_nodes
    )
    return {
        "matched": [{"node_id": node_id, "tool_id": tool_id} for node_id, tool_id in matched],
        "planned_only": [{"node_id": node_id, "tool_id": tool_id} for node_id, tool_id in planned_only],
        "executed_only": [{"node_id": node_id, "tool_id": tool_id} for node_id, tool_id in executed_only],
        "summary": {
            "planned_tool_count": len(planned_pairs),
            "executed_tool_count": len(executed_pairs),
            "matched_count": len(matched),
            "planned_only_count": len(planned_only),
            "executed_only_count": len(executed_only),
            "plan_incomplete": incomplete_plan,
        },
    }
