"""
Spec and validation for user-defined custom agents.

Contract layer for Phase 4 of the multi-agent system. Defines CustomAgentSpec
(the user-facing definition) and the validation/conversion utilities to bring
custom agents into the HarnessRegistry.

No agentscope dependency — pure Python/Pydantic.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from .harness import AgentHarness, RetryPolicy, RetryStrategy
from .registry import HarnessRegistry

# Pattern that agent IDs must satisfy: lowercase alphanumeric + underscores only.
_AGENT_ID_RE = re.compile(r"^[a-z0-9_]+$")


# ============================================================================
# Custom Agent Spec
# ============================================================================


class CustomAgentSpec(BaseModel):
    """
    User-defined agent specification.

    Describes every aspect of a custom agent: identity, I/O contracts,
    tool/workflow permissions, and runtime constraints.  Instances are
    validated by :func:`validate_custom_agent_spec` before being committed
    to the :class:`~.registry.HarnessRegistry`.
    """

    # Identity
    agent_id: str
    """Unique identifier — must be lowercase alphanumeric + underscores, no spaces."""

    display_name: str
    """Human-readable name shown in the UI and logs."""

    prompt: str
    """System prompt injected at the start of every ReAct loop."""

    role: str
    """Short description of the agent's role (used in harness and catalog)."""

    # I/O contracts
    input_schema: dict[str, Any]
    """JSON Schema object describing the required inputs for this agent."""

    output_schema: dict[str, Any]
    """JSON Schema object describing the expected outputs for this agent."""

    # Permissions
    allowed_tools: list[str] = []
    """Tool IDs this agent is permitted to call (must exist in registry)."""

    allowed_workflows: list[str] = []
    """Workflow IDs this agent is permitted to participate in (must exist in registry)."""

    # Optional metadata
    artifact_family: str | None = None
    """Artifact family this agent produces, e.g. ``"email"`` or ``"pitch_deck"``."""

    model_hint: str = "sonnet"
    """
    Preferred model tier for execution.

    Accepted values: ``"haiku"`` (fast/cheap), ``"sonnet"`` (balanced),
    ``"opus"`` (deepest reasoning).
    """

    # Runtime constraints
    max_iterations: int = 6
    """Maximum number of ReAct loop iterations before the agent is aborted."""

    timeout_seconds: int = 120
    """Wall-clock execution timeout in seconds."""

    # Metadata
    tags: list[str] = []
    """Arbitrary metadata tags for filtering and discovery."""

    # ------------------------------------------------------------------ #
    # Pydantic validators
    # ------------------------------------------------------------------ #

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        """Reject empty IDs and IDs that contain spaces or uppercase letters."""
        if not v or not v.strip():
            raise ValueError("agent_id must be non-empty")
        if not _AGENT_ID_RE.match(v):
            raise ValueError(
                "agent_id must be lowercase alphanumeric characters and underscores only "
                f"(no spaces, no uppercase). Got: {v!r}"
            )
        return v

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, v: str) -> str:
        """Reject empty prompts or prompts that are too short to be meaningful."""
        if not v or not v.strip():
            raise ValueError("prompt must be non-empty")
        if len(v.strip()) < 20:
            raise ValueError(
                f"prompt must be at least 20 characters. Got {len(v.strip())} characters."
            )
        return v

    @field_validator("input_schema")
    @classmethod
    def _validate_input_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Require a minimal JSON Schema shape: must have 'type' or 'properties'."""
        if "type" not in v and "properties" not in v:
            raise ValueError(
                "input_schema must be a valid JSON Schema object with a 'type' or 'properties' key"
            )
        return v

    @field_validator("output_schema")
    @classmethod
    def _validate_output_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Require a minimal JSON Schema shape: must have 'type' or 'properties'."""
        if "type" not in v and "properties" not in v:
            raise ValueError(
                "output_schema must be a valid JSON Schema object with a 'type' or 'properties' key"
            )
        return v


# ============================================================================
# Registration result
# ============================================================================


class CustomAgentRegistration(BaseModel):
    """
    Result returned by :meth:`~.user_agent_registry.UserAgentRegistry.register`.

    Carries identity fields alongside validation outcome so callers can
    surface errors to users without raising exceptions.
    """

    agent_id: str
    """ID of the agent that was (or was attempted to be) registered."""

    display_name: str
    """Human-readable display name from the spec."""

    registered_at: datetime
    """UTC timestamp of the registration attempt."""

    harness_valid: bool
    """``True`` if the spec passed all validation checks and was added to the registry."""

    validation_errors: list[str]
    """Non-empty when ``harness_valid`` is ``False``; describes why registration failed."""

    warnings: list[str]
    """
    Non-fatal observations that did not block registration — e.g. empty
    ``allowed_tools``, unusual ``model_hint`` values, very short timeouts.
    """


# ============================================================================
# Validation
# ============================================================================


def validate_custom_agent_spec(
    spec: CustomAgentSpec,
    registry: HarnessRegistry,
) -> tuple[bool, list[str]]:
    """
    Validate a :class:`CustomAgentSpec` against the current registry state.

    Checks performed:

    1. ``agent_id`` must not shadow a built-in agent already present in the registry.
    2. Every tool listed in ``allowed_tools`` must exist in the registry.
    3. Every workflow listed in ``allowed_workflows`` must exist in the registry.
    4. ``input_schema`` must have a ``"type"`` key or a ``"properties"`` key.
    5. ``output_schema`` must have a ``"type"`` key or a ``"properties"`` key.

    Note: Pydantic field validators enforce the syntactic constraints (non-empty
    ``agent_id``, prompt length, etc.) at construction time.  This function
    enforces *cross-registry* semantic constraints that require a live registry.

    Args:
        spec:     The custom agent specification to validate.
        registry: The registry to check for conflicts and referenced IDs.

    Returns:
        A ``(is_valid, errors)`` tuple.  ``is_valid`` is ``True`` iff ``errors``
        is empty.
    """
    errors: list[str] = []

    # 1. No shadowing of built-in agents.
    if registry.get_agent(spec.agent_id) is not None:
        errors.append(
            f"agent_id '{spec.agent_id}' conflicts with a built-in agent. "
            "Custom agents cannot override built-ins."
        )

    # 2. All allowed tools must exist.
    for tool_id in spec.allowed_tools:
        if registry.get_tool(tool_id) is None:
            errors.append(
                f"allowed_tools references unknown tool '{tool_id}'. "
                "Register the tool harness before adding this agent."
            )

    # 3. All allowed workflows must exist.
    for workflow_id in spec.allowed_workflows:
        if registry.get_workflow(workflow_id) is None:
            errors.append(
                f"allowed_workflows references unknown workflow '{workflow_id}'. "
                "Register the workflow template before adding this agent."
            )

    # 4. input_schema structural check (belt-and-suspenders — Pydantic already
    #    validates this at construction, but the registry layer re-checks in
    #    case a spec object was mutated after construction).
    if "type" not in spec.input_schema and "properties" not in spec.input_schema:
        errors.append(
            "input_schema must be a valid JSON Schema object with a 'type' or 'properties' key"
        )

    # 5. output_schema structural check.
    if "type" not in spec.output_schema and "properties" not in spec.output_schema:
        errors.append(
            "output_schema must be a valid JSON Schema object with a 'type' or 'properties' key"
        )

    return len(errors) == 0, errors


# ============================================================================
# Conversion
# ============================================================================


def spec_to_harness(spec: CustomAgentSpec) -> AgentHarness:
    """
    Convert a :class:`CustomAgentSpec` into an :class:`~.harness.AgentHarness`.

    The resulting harness is suitable for storage in a
    :class:`~.registry.HarnessRegistry` via :meth:`~.registry.HarnessRegistry.add_agent`.

    Mapping rules:

    * ``agent_id``, ``role``, ``input_schema``, ``output_schema``,
      ``allowed_tools``, ``allowed_workflows``, and ``timeout_seconds`` map
      directly.
    * ``display_name`` and ``prompt`` are combined into ``description``
      (``"<display_name>: <prompt>"``) so harness consumers can surface them.
    * ``artifact_family`` is stored as a single-element ``artifact_families``
      list when non-``None``, otherwise an empty list.
    * A default exponential :class:`~.harness.RetryPolicy` is applied with
      ``max_attempts=3``.
    * ``max_iterations`` is stored as a custom extra field via model
      ``description`` metadata comment; it cannot be natively expressed in
      :class:`AgentHarness`, so it is embedded in the description string.

    Args:
        spec: The validated custom agent specification.

    Returns:
        An :class:`~.harness.AgentHarness` ready to be added to the registry.
    """
    artifact_families: list[str] = (
        [spec.artifact_family] if spec.artifact_family is not None else []
    )

    description = (
        f"{spec.display_name}: {spec.prompt} "
        f"[model_hint={spec.model_hint}, max_iterations={spec.max_iterations}]"
    )

    return AgentHarness(
        agent_id=spec.agent_id,
        role=spec.role,
        description=description,
        input_schema=spec.input_schema,
        output_schema=spec.output_schema,
        allowed_tools=list(spec.allowed_tools),
        allowed_workflows=list(spec.allowed_workflows),
        artifact_families=artifact_families,
        timeout_seconds=spec.timeout_seconds,
        retry_policy=RetryPolicy(
            strategy=RetryStrategy.exponential,
            max_attempts=3,
            initial_delay_seconds=1.0,
            max_delay_seconds=30.0,
        ),
        max_retries=3,
    )
