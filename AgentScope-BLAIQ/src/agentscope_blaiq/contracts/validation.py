"""
Validation functions for harnesses and workflows.

Enforces contract discipline. All validation is synchronous and stateless.
"""

from __future__ import annotations

from typing import Optional

from .harness import AgentHarness, ToolHarness, WorkflowTemplate


def validate_agent_harness(harness: AgentHarness) -> tuple[bool, list[str]]:
    """
    Validate an agent harness. Returns (is_valid, errors).

    Rules:
    - agent_id must be non-empty
    - input_schema and output_schema must be dicts (can be empty but not None)
    - allowed_tools must all exist (checked separately in registry validation)
    - timeout_seconds must be > 0
    - max_retries must be >= 0
    - if requires_approval, approval_gate must be set
    """
    errors = []

    if not harness.agent_id or not harness.agent_id.strip():
        errors.append("agent_id must be non-empty")

    if not isinstance(harness.input_schema, dict):
        errors.append("input_schema must be a dict")

    if not isinstance(harness.output_schema, dict):
        errors.append("output_schema must be a dict")

    if harness.timeout_seconds <= 0:
        errors.append(f"timeout_seconds must be > 0, got {harness.timeout_seconds}")

    if harness.max_retries < 0:
        errors.append(f"max_retries must be >= 0, got {harness.max_retries}")

    if harness.requires_approval and not harness.approval_gate:
        errors.append("if requires_approval=True, approval_gate must be set")

    return len(errors) == 0, errors


def validate_tool_harness(tool: ToolHarness) -> tuple[bool, list[str]]:
    """
    Validate a tool harness. Returns (is_valid, errors).

    Rules:
    - tool_id must be non-empty
    - owner_agent must be non-empty
    - input_schema and output_schema must be dicts
    - timeout_seconds must be > 0
    - max_parallel_calls must be >= 1
    - allowed_agents must be non-empty
    - if requires_approval, approval_agent must be set
    """
    errors = []

    if not tool.tool_id or not tool.tool_id.strip():
        errors.append("tool_id must be non-empty")

    if not tool.owner_agent or not tool.owner_agent.strip():
        errors.append("owner_agent must be non-empty")

    if not isinstance(tool.input_schema, dict):
        errors.append("input_schema must be a dict")

    if not isinstance(tool.output_schema, dict):
        errors.append("output_schema must be a dict")

    if tool.timeout_seconds <= 0:
        errors.append(f"timeout_seconds must be > 0, got {tool.timeout_seconds}")

    if tool.max_parallel_calls < 1:
        errors.append(f"max_parallel_calls must be >= 1, got {tool.max_parallel_calls}")

    if not tool.allowed_agents:
        errors.append("allowed_agents must be non-empty")

    if tool.requires_approval and not tool.approval_agent:
        errors.append("if requires_approval=True, approval_agent must be set")

    return len(errors) == 0, errors


def validate_workflow_template(workflow: WorkflowTemplate) -> tuple[bool, list[str]]:
    """
    Validate a workflow template. Returns (is_valid, errors).

    Rules:
    - workflow_id must be non-empty
    - nodes must be non-empty
    - all node_ids must be unique
    - all input_from and output_to references must exist or be 'start'
    - forms a valid DAG (no cycles)
    - allowed_agents must be non-empty
    - all required_handoffs must have valid node references
    """
    errors = []

    if not workflow.workflow_id or not workflow.workflow_id.strip():
        errors.append("workflow_id must be non-empty")

    if not workflow.nodes:
        errors.append("nodes must be non-empty")
        return False, errors

    # Check node IDs are unique
    node_ids = [node.node_id for node in workflow.nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append("node_ids must be unique")

    # Build node ID set for validation
    node_id_set = set(node_ids)

    # Check input/output references
    for node in workflow.nodes:
        for input_ref in node.input_from:
            if input_ref != "start" and input_ref not in node_id_set:
                errors.append(
                    f"Node {node.node_id}: input_from '{input_ref}' does not exist"
                )
        for output_ref in node.output_to:
            if output_ref != "end" and output_ref not in node_id_set:
                errors.append(
                    f"Node {node.node_id}: output_to '{output_ref}' does not exist"
                )

    # Check for cycles using DFS
    if not _has_cycle(workflow.nodes):
        pass  # No cycle, good
    else:
        errors.append("Workflow contains a cycle (not a DAG)")

    if not workflow.allowed_agents:
        errors.append("allowed_agents must be non-empty")

    # Check required_handoffs
    for src, dst in workflow.required_handoffs:
        if src not in node_id_set:
            errors.append(f"required_handoff: source node '{src}' does not exist")
        if dst not in node_id_set:
            errors.append(f"required_handoff: destination node '{dst}' does not exist")

    return len(errors) == 0, errors


def _has_cycle(nodes: list) -> bool:
    """Check if workflow has a cycle using DFS."""
    # Build adjacency list
    graph = {node.node_id: node.output_to for node in nodes}

    visited = set()
    rec_stack = set()

    def dfs(node_id: str) -> bool:
        visited.add(node_id)
        rec_stack.add(node_id)

        for neighbor in graph.get(node_id, []):
            if neighbor == "end":
                continue
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(node_id)
        return False

    for node_id in graph:
        if node_id not in visited:
            if dfs(node_id):
                return True

    return False


def check_agent_tool_compatibility(
    agent: AgentHarness, tool: ToolHarness
) -> tuple[bool, Optional[str]]:
    """
    Check if an agent can use a tool. Returns (is_compatible, error_msg).

    Rules:
    - tool must be in agent.allowed_tools
    - agent must be in tool.allowed_agents
    """
    if tool.tool_id not in agent.allowed_tools:
        return False, f"Agent '{agent.agent_id}' does not have '{tool.tool_id}' in allowed_tools"

    if agent.agent_id not in tool.allowed_agents:
        return False, f"Tool '{tool.tool_id}' does not allow agent '{agent.agent_id}'"

    return True, None


def check_workflow_agent_compatibility(
    workflow: WorkflowTemplate, agent: AgentHarness
) -> tuple[bool, Optional[str]]:
    """
    Check if an agent can be used in a workflow. Returns (is_compatible, error_msg).

    Rules:
    - agent must be in workflow.allowed_agents
    - all nodes using this agent in the workflow must have tools allowed by the agent
    """
    if agent.agent_id not in workflow.allowed_agents:
        return False, f"Agent '{agent.agent_id}' not in workflow allowed_agents"

    # Check nodes using this agent have compatible tools
    for node in workflow.nodes:
        if node.agent_id == agent.agent_id:
            for tool_id in node.required_tools:
                if tool_id not in agent.allowed_tools:
                    return False, (
                        f"Node '{node.node_id}' requires tool '{tool_id}' "
                        f"but agent '{agent.agent_id}' doesn't allow it"
                    )

    return True, None


def check_workflow_artifact_family_coverage(
    workflow: WorkflowTemplate, artifact_families: list[str]
) -> tuple[bool, list[str]]:
    """
    Check if workflow covers all required artifact families.
    Returns (all_covered, missing_families).

    A workflow covers a family if at least one of its agents lists it in artifact_families.
    """
    covered = set()
    # This check requires agent harnesses, so we keep it simple here
    # Real implementation would pass in agent harnesses and check coverage
    missing = [fam for fam in artifact_families if fam not in covered]
    return len(missing) == 0, missing


def validate_all_harnesses(
    agents: dict[str, AgentHarness],
    tools: dict[str, ToolHarness],
    workflows: dict[str, WorkflowTemplate],
) -> list[str]:
    """
    Validate all harnesses and their cross-references.
    Returns list of all errors found.
    """
    errors = []

    # Validate agents
    for agent_id, agent in agents.items():
        is_valid, agent_errors = validate_agent_harness(agent)
        if not is_valid:
            errors.extend([f"Agent '{agent_id}': {e}" for e in agent_errors])

    # Validate tools
    for tool_id, tool in tools.items():
        is_valid, tool_errors = validate_tool_harness(tool)
        if not is_valid:
            errors.extend([f"Tool '{tool_id}': {e}" for e in tool_errors])

    # Validate workflows
    for workflow_id, workflow in workflows.items():
        is_valid, workflow_errors = validate_workflow_template(workflow)
        if not is_valid:
            errors.extend([f"Workflow '{workflow_id}': {e}" for e in workflow_errors])

    # Cross-reference checks
    for agent_id, agent in agents.items():
        # Check allowed_tools exist
        for tool_id in agent.allowed_tools:
            if tool_id not in tools:
                errors.append(f"Agent '{agent_id}': allowed_tool '{tool_id}' not found")

        # Check dependencies exist
        for dep_agent_id in agent.dependencies:
            if dep_agent_id not in agents:
                errors.append(f"Agent '{agent_id}': dependency '{dep_agent_id}' not found")

    for tool_id, tool in tools.items():
        # Check owner_agent exists
        if tool.owner_agent not in agents:
            errors.append(f"Tool '{tool_id}': owner_agent '{tool.owner_agent}' not found")

        # Check allowed_agents exist
        for agent_id in tool.allowed_agents:
            if agent_id not in agents:
                errors.append(f"Tool '{tool_id}': allowed_agent '{agent_id}' not found")

    for workflow_id, workflow in workflows.items():
        # Check all agents exist
        for node in workflow.nodes:
            if node.agent_id not in agents:
                errors.append(
                    f"Workflow '{workflow_id}', node '{node.node_id}': "
                    f"agent '{node.agent_id}' not found"
                )

            # Check all tools exist
            for tool_id in node.required_tools:
                if tool_id not in tools:
                    errors.append(
                        f"Workflow '{workflow_id}', node '{node.node_id}': "
                        f"tool '{tool_id}' not found"
                    )

        # Check allowed_agents exist
        for agent_id in workflow.allowed_agents:
            if agent_id not in agents:
                errors.append(f"Workflow '{workflow_id}': allowed_agent '{agent_id}' not found")

        # Check approval gates exist
        for approval_gate in workflow.approval_gates:
            if approval_gate not in agents:
                errors.append(
                    f"Workflow '{workflow_id}': approval_gate '{approval_gate}' not found"
                )

    return errors
