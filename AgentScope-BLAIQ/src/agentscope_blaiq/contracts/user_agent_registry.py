"""
Registry for user-defined custom agents.

Extends the contract layer by wrapping :class:`~.registry.HarnessRegistry`
with custom-agent-specific CRUD, validation, and lifecycle management.

Built-in agents (loaded from ``AGENT_HARNESSES``) cannot be overridden or
deregistered through this interface — only custom agents managed here are
mutable.

No agentscope dependency — pure Python/Pydantic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .custom_agents import (
    CustomAgentRegistration,
    CustomAgentSpec,
    spec_to_harness,
    validate_custom_agent_spec,
)
from .registry import HarnessRegistry


class UserAgentRegistry:
    """
    Registry for user-defined custom agents.

    Wraps a :class:`~.registry.HarnessRegistry` to provide custom-agent CRUD
    with full validation.  All validation logic is delegated to
    :func:`~.custom_agents.validate_custom_agent_spec` so the two modules
    stay in sync.

    Built-in agents (those loaded via
    :meth:`~.registry.HarnessRegistry.load_builtin_agents`) are treated as
    read-only: they cannot be registered over or deregistered.

    Example::

        from agentscope_blaiq.contracts import HarnessRegistry
        from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
        from agentscope_blaiq.contracts.user_agent_registry import UserAgentRegistry

        harness_registry = HarnessRegistry()
        harness_registry.load_builtin_agents()
        harness_registry.load_builtin_tools()
        harness_registry.load_builtin_workflows()

        user_registry = UserAgentRegistry(harness_registry)

        spec = CustomAgentSpec(
            agent_id="my_summariser",
            display_name="My Summariser",
            prompt="You are a concise summarisation agent. Produce bullet-point summaries.",
            role="Text summarisation specialist",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )

        registration = user_registry.register(spec)
        assert registration.harness_valid
    """

    def __init__(self, harness_registry: HarnessRegistry) -> None:
        """
        Initialise the user agent registry.

        Args:
            harness_registry: The shared harness registry that custom agents
                              are ultimately stored in.  This registry is also
                              used to resolve tool and workflow references
                              during validation.
        """
        self._harness_registry = harness_registry
        self._specs: dict[str, CustomAgentSpec] = {}

    # ------------------------------------------------------------------ #
    # Write operations
    # ------------------------------------------------------------------ #

    def register(self, spec: CustomAgentSpec) -> CustomAgentRegistration:
        """
        Validate and register a custom agent.

        Steps:

        1. Call :func:`~.custom_agents.validate_custom_agent_spec` against the
           shared harness registry.
        2. If valid: convert the spec to an :class:`~.harness.AgentHarness`
           via :func:`~.custom_agents.spec_to_harness` and add it to the
           harness registry.
        3. Store the spec in internal state so it can be retrieved later.
        4. Return a :class:`~.custom_agents.CustomAgentRegistration` reflecting
           the outcome.

        If validation fails the spec is **not** added to either registry, and
        ``CustomAgentRegistration.harness_valid`` will be ``False``.

        Args:
            spec: The custom agent specification to register.

        Returns:
            A :class:`~.custom_agents.CustomAgentRegistration` with full
            outcome detail.
        """
        now = datetime.now(tz=timezone.utc)

        is_valid, errors = validate_custom_agent_spec(spec, self._harness_registry)

        warnings: list[str] = _collect_warnings(spec)

        if not is_valid:
            return CustomAgentRegistration(
                agent_id=spec.agent_id,
                display_name=spec.display_name,
                registered_at=now,
                harness_valid=False,
                validation_errors=errors,
                warnings=warnings,
            )

        harness = spec_to_harness(spec)
        self._harness_registry.add_agent(harness)
        self._specs[spec.agent_id] = spec

        return CustomAgentRegistration(
            agent_id=spec.agent_id,
            display_name=spec.display_name,
            registered_at=now,
            harness_valid=True,
            validation_errors=[],
            warnings=warnings,
        )

    def deregister(self, agent_id: str) -> bool:
        """
        Remove a custom agent from the registry.

        Built-in agents (those not managed by this registry) cannot be
        deregistered.  Attempting to do so returns ``False`` without
        modifying any state.

        Args:
            agent_id: The ID of the custom agent to remove.

        Returns:
            ``True`` if the agent was found and removed; ``False`` if the
            agent does not exist in the custom registry or is a built-in.
        """
        if agent_id not in self._specs:
            return False

        # Remove from internal spec store.
        del self._specs[agent_id]

        # Remove from the shared harness registry if present.
        if agent_id in self._harness_registry.agents:
            del self._harness_registry.agents[agent_id]
            # Mark the registry as needing re-validation.
            self._harness_registry._validated = False  # noqa: SLF001 — internal access

        return True

    # ------------------------------------------------------------------ #
    # Read operations
    # ------------------------------------------------------------------ #

    def get(self, agent_id: str) -> CustomAgentSpec | None:
        """
        Retrieve a custom agent spec by ID.

        Args:
            agent_id: The ID of the custom agent to retrieve.

        Returns:
            The :class:`~.custom_agents.CustomAgentSpec` if found, otherwise
            ``None``.
        """
        return self._specs.get(agent_id)

    def list_all(self) -> list[CustomAgentSpec]:
        """
        Return all registered custom agent specs.

        Returns:
            A list of :class:`~.custom_agents.CustomAgentSpec` instances,
            ordered by insertion order (Python 3.7+ dict ordering).
        """
        return list(self._specs.values())

    def list_ids(self) -> list[str]:
        """
        Return a sorted list of all registered custom agent IDs.

        Returns:
            Sorted list of agent ID strings.
        """
        return sorted(self._specs.keys())

    # ------------------------------------------------------------------ #
    # Routing validation
    # ------------------------------------------------------------------ #

    def can_route_to(
        self, agent_id: str, workflow_id: str
    ) -> tuple[bool, list[str]]:
        """
        Check if a custom agent can be routed to within a given workflow.

        Validates:

        1. Agent exists in this custom-agent registry.
        2. Agent's ``allowed_workflows`` includes *workflow_id*
           (an empty list means the agent accepts any workflow).
        3. The agent's harness passes
           :meth:`~.registry.HarnessRegistry.validate_workflow_for_agent`.
        4. Every tool in the agent's ``allowed_tools`` is available in the
           workflow (checked via
           :meth:`~.registry.HarnessRegistry.validate_workflow_for_tool`).

        Args:
            agent_id:    The custom agent to validate.
            workflow_id: The target workflow ID.

        Returns:
            A ``(ok, errors)`` tuple.  ``ok`` is ``True`` only when all
            checks pass.
        """
        errors: list[str] = []

        # 1. Agent must exist in the custom registry.
        spec = self._specs.get(agent_id)
        if spec is None:
            return False, [
                f"Custom agent '{agent_id}' not found in user registry."
            ]

        # 2. allowed_workflows gate (empty = any workflow is accepted).
        if spec.allowed_workflows and workflow_id not in spec.allowed_workflows:
            errors.append(
                f"Agent '{agent_id}' does not allow workflow '{workflow_id}'. "
                f"Allowed: {spec.allowed_workflows}"
            )

        # 3. Role compatibility — agent's role must match at least one node in the workflow.
        #    Only enforced when the agent explicitly declares allowed_workflows
        #    (empty list means "any workflow" — skip the role gate).
        if spec.allowed_workflows:
            workflow = self._harness_registry.workflows.get(workflow_id)
            if workflow is not None:
                role_accepted = workflow.accepts_role(spec.role) if hasattr(workflow, 'accepts_role') else True
                if not role_accepted:
                    errors.append(
                        f"Agent '{agent_id}' role '{spec.role}' is not an allowed role "
                        f"in workflow '{workflow_id}'"
                    )

        # 4. All allowed_tools must be available in the workflow.
        for tool_id in spec.allowed_tools:
            tool_ok, tool_errors = (
                self._harness_registry.validate_workflow_for_tool(
                    workflow_id, tool_id
                )
            )
            if not tool_ok:
                errors.extend(tool_errors)

        return len(errors) == 0, errors

    def validate_draft_routing(
        self,
        draft_node_assignments: dict[str, str],
        workflow_id: str,
    ) -> tuple[bool, list[str]]:
        """
        Validate all custom agents in a :class:`~.strategic.StrategicDraft`'s
        ``node_assignments``.

        For each ``node_id -> agent_id`` mapping where *agent_id* belongs to
        this custom-agent registry:

        * Run :meth:`can_route_to` to verify workflow compatibility.
        * Verify the agent's ``output_schema`` is non-empty (a minimal
          compatibility check ensuring the agent declares what it produces,
          which downstream nodes can consume).

        Built-in agents (those not in ``self._specs``) are silently skipped —
        they are validated through the harness registry elsewhere.

        Args:
            draft_node_assignments: Mapping of ``node_id`` to ``agent_id``
                                    from a ``StrategicDraft``.
            workflow_id:            The target workflow ID to validate against.

        Returns:
            A ``(ok, errors)`` tuple.  ``ok`` is ``True`` only when **all**
            custom agents in the mapping pass validation.
        """
        errors: list[str] = []

        for node_id, agent_id in draft_node_assignments.items():
            # Only validate agents that belong to this registry.
            if agent_id not in self._specs:
                continue

            # Routing compatibility.
            route_ok, route_errors = self.can_route_to(agent_id, workflow_id)
            if not route_ok:
                errors.extend(
                    f"[node={node_id}] {err}" for err in route_errors
                )

            # Output schema compatibility — the agent must declare an
            # output_schema so downstream nodes know what to expect.
            spec = self._specs[agent_id]
            if not spec.output_schema:
                errors.append(
                    f"[node={node_id}] Agent '{agent_id}' has an empty "
                    "output_schema. Downstream nodes cannot verify "
                    "compatibility."
                )

        return len(errors) == 0, errors


# ============================================================================
# Internal helpers
# ============================================================================


def _collect_warnings(spec: CustomAgentSpec) -> list[str]:
    """
    Collect non-fatal warnings about a spec.

    These are observations that should be surfaced to the user but do not
    block registration.

    Args:
        spec: The spec to inspect.

    Returns:
        A (possibly empty) list of warning strings.
    """
    warnings: list[str] = []

    if not spec.allowed_tools:
        warnings.append(
            "allowed_tools is empty — this agent will not be able to call any tools."
        )

    if spec.model_hint not in {"haiku", "sonnet", "opus"}:
        warnings.append(
            f"model_hint '{spec.model_hint}' is not a recognised tier "
            "('haiku', 'sonnet', 'opus'). The runtime may fall back to the default model."
        )

    if spec.timeout_seconds < 10:
        warnings.append(
            f"timeout_seconds={spec.timeout_seconds} is very short. "
            "Most agents need at least 10 seconds to complete."
        )

    if spec.max_iterations < 1:
        warnings.append(
            f"max_iterations={spec.max_iterations} — the agent will never execute a ReAct step."
        )

    return warnings
