"""
Dispatch validation for the contract layer.

Validates agent dispatches against harness contracts BEFORE execution.
Pure validation — no execution logic, no side effects, no engine modification.

Usage:
    from agentscope_blaiq.contracts.dispatch import validate_dispatch, DispatchResult

    result = validate_dispatch("research", input_data, registry)
    if not result.ok:
        logger.warning("Dispatch blocked: %s", result.errors)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import jsonschema

from .harness import AgentHarness, ToolHarness, canonicalize_workflow_template_id
from .registry import HarnessRegistry

logger = logging.getLogger("agentscope_blaiq.contracts.dispatch")
_RESEARCH_HANDOFF_AGENT_IDS = {"research", "deep_research", "finance_research"}


@dataclass
class DispatchResult:
    """Result of a dispatch validation check."""
    ok: bool
    agent_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def validate_dispatch(
    agent_id: str,
    input_data: dict[str, Any],
    registry: HarnessRegistry,
    *,
    workflow_id: Optional[str] = None,
    tools_requested: Optional[list[str]] = None,
    strict: bool = False,
) -> DispatchResult:
    """
    Validate an agent dispatch against its harness contract.

    Args:
        agent_id: Agent being dispatched.
        input_data: Data being sent to the agent.
        registry: Loaded harness registry.
        workflow_id: Current workflow (if known). Checks agent is allowed.
        tools_requested: Tools the agent intends to use. Checks compatibility.
        strict: If True, warnings become errors.

    Returns:
        DispatchResult with ok=True if dispatch is safe, errors otherwise.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Agent harness must exist
    harness = registry.get_agent(agent_id)
    if harness is None:
        return DispatchResult(
            ok=False,
            agent_id=agent_id,
            errors=[f"No harness found for agent '{agent_id}'"],
        )

    # 2. Validate input against input_schema (if schema defined)
    input_errors = _validate_input_schema(harness, input_data)
    errors.extend(input_errors)

    canonical_workflow_id = canonicalize_workflow_template_id(workflow_id)

    # 3. Validate workflow compatibility (if workflow_id provided)
    if canonical_workflow_id is not None:
        workflow_errors = _validate_workflow_compatibility(harness, canonical_workflow_id, registry)
        errors.extend(workflow_errors)

    # 4. Validate tool access (if tools_requested provided)
    if tools_requested:
        tool_errors = _validate_tool_access(harness, tools_requested, registry)
        errors.extend(tool_errors)

    # 5. Check required context keys present in input
    context_warnings = _check_required_context(harness, input_data)
    if strict:
        errors.extend(context_warnings)
    else:
        warnings.extend(context_warnings)

    ok = len(errors) == 0
    result = DispatchResult(ok=ok, agent_id=agent_id, errors=errors, warnings=warnings)

    if not ok:
        logger.warning(
            "Dispatch validation FAILED for agent '%s': %s",
            agent_id, errors,
        )
    elif warnings:
        logger.info(
            "Dispatch validation PASSED with warnings for agent '%s': %s",
            agent_id, warnings,
        )

    return result


def validate_tool_call(
    agent_id: str,
    tool_id: str,
    tool_input: dict[str, Any],
    registry: HarnessRegistry,
    *,
    workflow_id: Optional[str] = None,
) -> DispatchResult:
    """
    Validate a tool call against both agent and tool harness contracts.

    Args:
        agent_id: Agent making the call.
        tool_id: Tool being called.
        tool_input: Data being sent to the tool.
        registry: Loaded harness registry.
        workflow_id: Current workflow (if known).

    Returns:
        DispatchResult with ok=True if tool call is safe.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Agent harness must exist
    agent_harness = registry.get_agent(agent_id)
    if agent_harness is None:
        return DispatchResult(
            ok=False,
            agent_id=agent_id,
            errors=[f"No harness for agent '{agent_id}'"],
        )

    # 2. Tool harness must exist
    tool_harness = registry.get_tool(tool_id)
    if tool_harness is None:
        return DispatchResult(
            ok=False,
            agent_id=agent_id,
            errors=[f"No harness for tool '{tool_id}'"],
        )

    # 3. Tool must be in agent's allowed_tools
    if tool_id not in agent_harness.allowed_tools:
        errors.append(
            f"Agent '{agent_id}' not allowed to use tool '{tool_id}'"
        )

    # 4. Agent must be in tool's allowed_agents
    if agent_id not in tool_harness.allowed_agents:
        errors.append(
            f"Tool '{tool_id}' does not allow agent '{agent_id}'"
        )

    canonical_workflow_id = canonicalize_workflow_template_id(workflow_id)

    # 5. Workflow compatibility
    if canonical_workflow_id is not None and tool_harness.allowed_workflows:
        if canonical_workflow_id not in tool_harness.allowed_workflows:
            errors.append(
                f"Tool '{tool_id}' not allowed in workflow '{canonical_workflow_id}'"
            )

    # 6. Validate tool input against schema
    if tool_harness.input_schema:
        schema_errors = _validate_json_schema(tool_input, tool_harness.input_schema)
        for err in schema_errors:
            errors.append(f"Tool '{tool_id}' input: {err}")

    ok = len(errors) == 0
    result = DispatchResult(ok=ok, agent_id=agent_id, errors=errors, warnings=warnings)

    if not ok:
        logger.warning(
            "Tool call validation FAILED: agent '%s' -> tool '%s': %s",
            agent_id, tool_id, errors,
        )

    return result


def validate_handoff(
    from_agent_id: str,
    to_agent_id: str,
    output_data: dict[str, Any],
    registry: HarnessRegistry,
    *,
    workflow_id: Optional[str] = None,
) -> DispatchResult:
    """
    Validate a handoff between two agents.

    Checks:
    - Source agent's output matches its output_schema
    - Target agent's input requirements are met
    - Both agents are allowed in the workflow

    Args:
        from_agent_id: Agent producing output.
        to_agent_id: Agent receiving input.
        output_data: Data being passed.
        registry: Loaded harness registry.
        workflow_id: Current workflow (if known).

    Returns:
        DispatchResult for the receiving agent.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Both harnesses must exist
    from_harness = registry.get_agent(from_agent_id)
    to_harness = registry.get_agent(to_agent_id)

    if from_harness is None:
        return DispatchResult(
            ok=False,
            agent_id=to_agent_id,
            errors=[f"No harness for source agent '{from_agent_id}'"],
        )
    if to_harness is None:
        return DispatchResult(
            ok=False,
            agent_id=to_agent_id,
            errors=[f"No harness for target agent '{to_agent_id}'"],
        )

    # 2. Validate output against source's output_schema
    if from_harness.output_schema:
        schema_errors = _validate_json_schema(output_data, from_harness.output_schema)
        for err in schema_errors:
            errors.append(f"Source '{from_agent_id}' output: {err}")

    # 3. Validate output as input for target's input_schema
    if to_harness.input_schema:
        schema_errors = _validate_json_schema(output_data, to_harness.input_schema)
        for err in schema_errors:
            warnings.append(f"Target '{to_agent_id}' input: {err}")

    canonical_workflow_id = canonicalize_workflow_template_id(workflow_id)

    # 4. Workflow compatibility
    if canonical_workflow_id is not None:
        if from_harness.allowed_workflows and canonical_workflow_id not in from_harness.allowed_workflows:
            errors.append(f"Source '{from_agent_id}' not allowed in workflow '{canonical_workflow_id}'")
        if to_harness.allowed_workflows and canonical_workflow_id not in to_harness.allowed_workflows:
            errors.append(f"Target '{to_agent_id}' not allowed in workflow '{canonical_workflow_id}'")

        workflow_template = registry.get_workflow(canonical_workflow_id)
        if workflow_template is not None and workflow_template.required_handoffs:
            handoff = (
                _canonical_handoff_agent_id(from_agent_id),
                _canonical_handoff_agent_id(to_agent_id),
            )
            if handoff not in workflow_template.required_handoffs:
                errors.append(
                    f"Handoff '{from_agent_id}' -> '{to_agent_id}' is not allowed in workflow '{canonical_workflow_id}'"
                )

    ok = len(errors) == 0
    return DispatchResult(ok=ok, agent_id=to_agent_id, errors=errors, warnings=warnings)


# ============================================================================
# Internal helpers
# ============================================================================

def _validate_input_schema(harness: AgentHarness, input_data: dict[str, Any]) -> list[str]:
    """Validate input_data against harness.input_schema."""
    if not harness.input_schema:
        return []
    return _validate_json_schema(input_data, harness.input_schema)


def _canonical_handoff_agent_id(agent_id: str) -> str:
    """Map runtime research variants to the canonical workflow handoff node."""
    if agent_id in _RESEARCH_HANDOFF_AGENT_IDS:
        return "research"
    return agent_id


def _validate_json_schema(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Validate data against a JSON schema. Returns list of error messages."""
    if not schema:
        return []
    try:
        jsonschema.validate(instance=data, schema=schema)
        return []
    except jsonschema.ValidationError as e:
        return [e.message]
    except jsonschema.SchemaError as e:
        return [f"Invalid schema: {e.message}"]
    except Exception as e:
        return [f"Schema validation error: {str(e)}"]


def _validate_workflow_compatibility(
    harness: AgentHarness, workflow_id: str, registry: HarnessRegistry
) -> list[str]:
    """Check agent is allowed in the given workflow."""
    errors = []

    # Check agent allows this workflow
    if harness.allowed_workflows and workflow_id not in harness.allowed_workflows:
        errors.append(
            f"Agent '{harness.agent_id}' not allowed in workflow '{workflow_id}'"
        )

    # Check workflow allows this agent (if workflow template exists)
    workflow = registry.get_workflow(workflow_id)
    if workflow is not None:
        if harness.agent_id not in workflow.allowed_agents:
            # Role-based fallback: check if agent's role is accepted
            agent_role = harness.role if harness.role else harness.agent_id
            if hasattr(workflow, 'allowed_roles') and workflow.accepts_role(agent_role):
                pass  # Role-based match — allowed
            else:
                errors.append(
                    f"Workflow '{workflow_id}' does not allow agent '{harness.agent_id}'"
                )

    return errors


def _validate_tool_access(
    harness: AgentHarness, tools_requested: list[str], registry: HarnessRegistry
) -> list[str]:
    """Check all requested tools are allowed by the agent harness."""
    errors = []
    for tool_id in tools_requested:
        if tool_id not in harness.allowed_tools:
            errors.append(
                f"Agent '{harness.agent_id}' not allowed to use tool '{tool_id}'"
            )
        tool = registry.get_tool(tool_id)
        if tool is not None and harness.agent_id not in tool.allowed_agents:
            errors.append(
                f"Tool '{tool_id}' does not allow agent '{harness.agent_id}'"
            )
    return errors


def _check_required_context(harness: AgentHarness, input_data: dict[str, Any]) -> list[str]:
    """Check required context keys are present in input data."""
    warnings = []
    for key in harness.required_context:
        if key not in input_data:
            warnings.append(f"Required context '{key}' missing from input")
    return warnings
