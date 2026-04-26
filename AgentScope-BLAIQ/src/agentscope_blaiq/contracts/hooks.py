"""
Hook intercepts for contract-driven multi-agent workflows.

Hooks fire at workflow boundaries and return structured decisions — they do NOT
execute any work, call agents, or produce side effects.  Every function in this
module is a pure decision function: given context, return a decision.

Usage::

    from agentscope_blaiq.contracts.hooks import (
        HookType, HookAction, HookContext, HookDecision,
        HookResult, HookRegistry,
        evaluate_pre_node, evaluate_post_node,
    )

    registry = HookRegistry()
    registry.register(HookType.PRE_NODE, evaluate_pre_node)

    ctx = HookContext(
        hook_type=HookType.PRE_NODE,
        node_id="research",
        agent_id="research_agent",
        input_data={"query": "climate change"},
    )
    result = registry.evaluate(ctx)
    if not result.final_action == HookAction.BLOCK:
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .dispatch import validate_dispatch, validate_handoff
from .registry import HarnessRegistry


# ============================================================================
# Enums
# ============================================================================


class HookType(str, Enum):
    """
    Identifies when in the workflow lifecycle a hook fires.

    - PRE_NODE: fired immediately before an agent node is dispatched.
    - POST_NODE: fired immediately after an agent node returns output.
    - MISSING_INPUT: fired when one or more required input fields are absent.
    - RETRY_REPLAN: fired when a node fails or its output fails validation.
    - GOVERNANCE_GATE: fired when a governance approval step is required.
    """

    PRE_NODE = "pre_node"
    POST_NODE = "post_node"
    MISSING_INPUT = "missing_input"
    RETRY_REPLAN = "retry_replan"
    GOVERNANCE_GATE = "governance_gate"
    # Phase 2: dispatch-boundary and planner-guard hooks
    PRE_DISPATCH = "pre_dispatch"
    POST_DISPATCH = "post_dispatch"
    PLANNER_GUARD = "planner_guard"


class HookAction(str, Enum):
    """
    Decision returned by a hook evaluator.

    Severity order (highest to lowest):
    BLOCK > ESCALATE > REPLAN > RETRY > WARN > PROCEED

    - PROCEED: continue execution normally.
    - BLOCK: halt execution immediately; surface the error.
    - WARN: continue but log a warning.
    - RETRY: retry the same node (optionally with modified input).
    - REPLAN: trigger replanning from the strategist agent.
    - ESCALATE: escalate to HITL review or governance gate.
    """

    PROCEED = "proceed"
    BLOCK = "block"
    WARN = "warn"
    RETRY = "retry"
    REPLAN = "replan"
    ESCALATE = "escalate"


# Priority order used when aggregating decisions (index 0 = most severe).
_ACTION_SEVERITY: list[HookAction] = [
    HookAction.BLOCK,
    HookAction.ESCALATE,
    HookAction.REPLAN,
    HookAction.RETRY,
    HookAction.WARN,
    HookAction.PROCEED,
]


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class HookContext:
    """
    Immutable context bundle passed to every hook evaluator.

    Fields
    ------
    hook_type:
        The lifecycle point at which the hook was fired.
    workflow_id:
        Optional identifier for the running workflow instance.
    node_id:
        Identifier for the current graph node being evaluated.
    agent_id:
        Identifier for the agent assigned to this node.
    input_data:
        Data that will be (or was) sent to the agent.
    output_data:
        Data returned by the agent (None for PRE_NODE hooks).
    error:
        Error message string if the node raised an exception.
    attempt_number:
        How many times this node has been attempted so far (0-indexed).
    metadata:
        Arbitrary key/value pairs for hook-specific context (e.g. approval_gates).
    """

    hook_type: HookType
    node_id: str
    agent_id: str
    input_data: dict[str, Any]
    workflow_id: str | None = None
    output_data: dict[str, Any] | None = None
    error: str | None = None
    attempt_number: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookDecision:
    """
    Structured decision returned by a single hook evaluator.

    Fields
    ------
    action:
        The recommended action for the orchestrator to take.
    reason:
        Human-readable explanation for the decision.
    replacement_input:
        If action is RETRY, an optional modified input dict to use instead of
        the original.  None means retry with the original input unchanged.
    errors:
        Validation errors or blocking reasons accumulated during evaluation.
    warnings:
        Non-blocking notes that should be logged.
    """

    action: HookAction
    reason: str
    replacement_input: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Return True when the decision does not block execution."""
        return self.action is not HookAction.BLOCK


@dataclass
class HookResult:
    """
    Aggregated result from running all registered evaluators for a hook type.

    The ``final_action`` is the most severe action across all decisions
    (BLOCK > ESCALATE > REPLAN > RETRY > WARN > PROCEED).

    Fields
    ------
    decisions:
        All individual decisions returned by registered evaluators.
    final_action:
        The winning (most severe) action.
    all_errors:
        Union of error lists from every decision.
    all_warnings:
        Union of warning lists from every decision.
    """

    decisions: list[HookDecision]
    final_action: HookAction
    all_errors: list[str]
    all_warnings: list[str]


# ============================================================================
# Type alias
# ============================================================================

#: A callable that takes a HookContext and returns a HookDecision.
HookEvaluator = Callable[[HookContext], HookDecision]


# ============================================================================
# Registry
# ============================================================================


class HookRegistry:
    """
    Manages registered HookEvaluator callables keyed by HookType.

    Each HookType may have zero or more evaluators.  When ``evaluate`` is
    called, all evaluators registered for the hook type are run in insertion
    order and their decisions are aggregated into a single HookResult.
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._evaluators: dict[HookType, list[HookEvaluator]] = {
            hook_type: [] for hook_type in HookType
        }

    def register(self, hook_type: HookType, evaluator: HookEvaluator) -> None:
        """
        Register a hook evaluator for a given hook type.

        Args:
            hook_type: The lifecycle point this evaluator should run at.
            evaluator: Callable(HookContext) -> HookDecision.
        """
        self._evaluators[hook_type].append(evaluator)

    def evaluate(self, ctx: HookContext) -> HookResult:
        """
        Run all evaluators registered for ``ctx.hook_type`` and aggregate results.

        If no evaluators are registered the result is a clean PROCEED.

        Args:
            ctx: Context bundle for this hook invocation.

        Returns:
            HookResult with the most severe action and collected errors/warnings.
        """
        evaluators = self._evaluators.get(ctx.hook_type, [])

        if not evaluators:
            return HookResult(
                decisions=[],
                final_action=HookAction.PROCEED,
                all_errors=[],
                all_warnings=[],
            )

        decisions: list[HookDecision] = [ev(ctx) for ev in evaluators]
        return _aggregate_decisions(decisions)


# ============================================================================
# Built-in evaluators
# ============================================================================


def evaluate_pre_node(
    ctx: HookContext,
    harness_registry: HarnessRegistry,
) -> HookDecision:
    """
    Evaluate whether an agent node is safe to dispatch.

    Uses ``validate_dispatch`` from the contracts.dispatch layer to check
    input data against the agent's harness contract.

    - Returns BLOCK with errors if dispatch validation fails.
    - Returns WARN if validation passes but warnings are present.
    - Returns PROCEED if validation is clean.

    Args:
        ctx: Hook context for the PRE_NODE event.
        harness_registry: Loaded harness registry used by validate_dispatch.

    Returns:
        HookDecision with the appropriate action.
    """
    result = validate_dispatch(
        agent_id=ctx.agent_id,
        input_data=ctx.input_data,
        registry=harness_registry,
        workflow_id=ctx.workflow_id,
    )

    if not result.ok:
        return HookDecision(
            action=HookAction.BLOCK,
            reason=f"Dispatch validation failed for agent '{ctx.agent_id}'",
            errors=result.errors,
            warnings=result.warnings,
        )

    if result.warnings:
        return HookDecision(
            action=HookAction.WARN,
            reason=f"Dispatch validation passed with warnings for agent '{ctx.agent_id}'",
            warnings=result.warnings,
        )

    return HookDecision(
        action=HookAction.PROCEED,
        reason=f"Dispatch validation passed for agent '{ctx.agent_id}'",
    )


def evaluate_post_node(
    ctx: HookContext,
    harness_registry: HarnessRegistry,  # noqa: ARG001 — reserved for future output schema checks
) -> HookDecision:
    """
    Evaluate the output produced by an agent node.

    - Returns RETRY if output_data is None (node produced no output).
    - Returns PROCEED if output_data is present.

    Args:
        ctx: Hook context for the POST_NODE event (output_data may be None).
        harness_registry: Reserved for future output schema validation.

    Returns:
        HookDecision with the appropriate action.
    """
    if ctx.output_data is None:
        return HookDecision(
            action=HookAction.RETRY,
            reason=f"Agent '{ctx.agent_id}' returned no output on node '{ctx.node_id}'",
            errors=[f"output_data is None for node '{ctx.node_id}'"],
        )

    return HookDecision(
        action=HookAction.PROCEED,
        reason=f"Node '{ctx.node_id}' produced output successfully",
    )


def evaluate_missing_input(ctx: HookContext) -> HookDecision:
    """
    Evaluate whether required input fields are present.

    Looks for a ``required_keys`` list in ``ctx.metadata``.  If absent, the
    check is skipped and PROCEED is returned.  Any keys listed in
    ``required_keys`` that are missing from ``ctx.input_data`` trigger an
    ESCALATE decision so a human operator or governance gate can supply them.

    Args:
        ctx: Hook context for the MISSING_INPUT event.

    Returns:
        HookDecision — ESCALATE if keys are missing, PROCEED otherwise.
    """
    required_keys: list[str] = ctx.metadata.get("required_keys", [])
    missing = [k for k in required_keys if k not in ctx.input_data]

    if missing:
        return HookDecision(
            action=HookAction.ESCALATE,
            reason=(
                f"Required input fields missing for node '{ctx.node_id}': {missing}"
            ),
            errors=[f"Missing required input key: '{k}'" for k in missing],
        )

    return HookDecision(
        action=HookAction.PROCEED,
        reason=f"All required input fields present for node '{ctx.node_id}'",
    )


def evaluate_retry_replan(ctx: HookContext) -> HookDecision:
    """
    Evaluate whether a failed node should be retried or trigger a full replan.

    Policy:
    - attempt_number == 0 → PROCEED (not yet retried; caller should retry first).
    - 1 <= attempt_number < 3 → RETRY the same node.
    - attempt_number >= 3 → REPLAN from the strategist agent.

    Args:
        ctx: Hook context for the RETRY_REPLAN event, with attempt_number set.

    Returns:
        HookDecision — PROCEED, RETRY, or REPLAN.
    """
    if ctx.attempt_number >= 3:
        return HookDecision(
            action=HookAction.REPLAN,
            reason=(
                f"Node '{ctx.node_id}' has failed {ctx.attempt_number} times; "
                "triggering full replan from strategist"
            ),
        )

    if ctx.attempt_number >= 1:
        return HookDecision(
            action=HookAction.RETRY,
            reason=(
                f"Node '{ctx.node_id}' failed on attempt {ctx.attempt_number}; "
                "retrying same node"
            ),
        )

    return HookDecision(
        action=HookAction.PROCEED,
        reason=f"No retries needed for node '{ctx.node_id}' (attempt 0)",
    )


def evaluate_governance_gate(ctx: HookContext) -> HookDecision:
    """
    Evaluate whether a governance approval is required before this node proceeds.

    Checks ``ctx.metadata["approval_gates"]``, which should be a list of node
    IDs that require approval.  If ``ctx.node_id`` is in that list, the
    decision is ESCALATE so the orchestrator can pause for human review.

    Args:
        ctx: Hook context for the GOVERNANCE_GATE event.

    Returns:
        HookDecision — ESCALATE if governance approval needed, PROCEED otherwise.
    """
    approval_gates: list[str] = ctx.metadata.get("approval_gates", [])

    if ctx.node_id in approval_gates:
        return HookDecision(
            action=HookAction.ESCALATE,
            reason=(
                f"Node '{ctx.node_id}' requires governance approval "
                f"(workflow_id='{ctx.workflow_id}')"
            ),
        )

    return HookDecision(
        action=HookAction.PROCEED,
        reason=f"No governance gate required for node '{ctx.node_id}'",
    )


# ============================================================================
# Phase 2: Dispatch-boundary and planner-guard evaluators
# ============================================================================


def evaluate_pre_dispatch(
    ctx: HookContext,
    harness_registry: HarnessRegistry,
) -> HookDecision:
    """Validate an agent dispatch against harness contracts.

    Replaces the inline ``validate_dispatch`` call in the engine's
    ``_pre_dispatch_check``.  Advisory-only during Phase 2 rollout — WARN
    rather than BLOCK so production execution is never halted by a missing
    harness entry.

    Args:
        ctx: PRE_DISPATCH context; ``agent_id`` is the agent being dispatched.
        harness_registry: Loaded harness registry.

    Returns:
        HookDecision — WARN on validation failure, PROCEED on success.
    """
    result = validate_dispatch(
        agent_id=ctx.agent_id,
        input_data=ctx.input_data,
        registry=harness_registry,
        workflow_id=ctx.workflow_id,
    )
    if not result.ok:
        return HookDecision(
            action=HookAction.WARN,
            reason=f"Pre-dispatch check failed for agent '{ctx.agent_id}'",
            errors=result.errors,
            warnings=result.warnings,
        )
    if result.warnings:
        return HookDecision(
            action=HookAction.WARN,
            reason=f"Pre-dispatch warnings for agent '{ctx.agent_id}'",
            warnings=result.warnings,
        )
    return HookDecision(
        action=HookAction.PROCEED,
        reason=f"Pre-dispatch OK for agent '{ctx.agent_id}'",
    )


def evaluate_pre_handoff(
    ctx: HookContext,
    harness_registry: HarnessRegistry,
) -> HookDecision:
    """Validate an agent-to-agent handoff against harness contracts.

    Replaces the inline ``validate_handoff`` call in the engine's
    ``_pre_handoff_check``.  Advisory-only (WARN, never BLOCK).

    ``ctx.metadata`` must contain:
        ``to_agent_id`` (str): the receiving agent.

    Args:
        ctx: PRE_DISPATCH context; ``agent_id`` is the *sending* agent.
        harness_registry: Loaded harness registry.

    Returns:
        HookDecision — WARN on validation failure, PROCEED on success.
    """
    to_agent_id: str = (ctx.metadata or {}).get("to_agent_id", "unknown")
    result = validate_handoff(
        from_agent_id=ctx.agent_id,
        to_agent_id=to_agent_id,
        output_data=ctx.output_data or {},
        registry=harness_registry,
        workflow_id=ctx.workflow_id,
    )
    if not result.ok:
        return HookDecision(
            action=HookAction.WARN,
            reason=f"Handoff check failed {ctx.agent_id} → {to_agent_id}",
            errors=result.errors,
            warnings=result.warnings,
        )
    if result.warnings:
        return HookDecision(
            action=HookAction.WARN,
            reason=f"Handoff warnings {ctx.agent_id} → {to_agent_id}",
            warnings=result.warnings,
        )
    return HookDecision(
        action=HookAction.PROCEED,
        reason=f"Handoff OK {ctx.agent_id} → {to_agent_id}",
    )


def evaluate_planner_guard(ctx: HookContext) -> HookDecision:
    """Validate a planner's routing intent before dispatch.

    Moves route/assignment/tool-availability validation OUT of the strategist
    so the planner produces intent and this hook decides if it is executable.

    ``ctx.input_data`` must contain:
        ``node_assignments`` (dict): node_id -> agent_id.
        ``required_tools_per_node`` (dict, optional): node_id -> [tool_id].
        ``route`` (str, optional): route string for sanity checks.

    ``ctx.metadata`` may contain:
        ``known_agent_ids`` (list[str]): agents currently reachable.

    Returns:
        HookDecision — BLOCK if assignments reference unknown agents,
        WARN on missing tools, PROCEED when clean.
    """
    node_assignments: dict[str, str] = (ctx.input_data or {}).get("node_assignments", {})
    required_tools: dict[str, list[str]] = (ctx.input_data or {}).get("required_tools_per_node", {})
    known_ids: list[str] = list((ctx.metadata or {}).get("known_agent_ids", []))

    errors: list[str] = []
    warnings: list[str] = []

    if known_ids:
        for node_id, agent_id in node_assignments.items():
            if agent_id and agent_id not in known_ids:
                errors.append(
                    f"Node '{node_id}' assigned to unknown agent '{agent_id}'"
                )

    for node_id, tools in required_tools.items():
        if tools and not known_ids:
            warnings.append(
                f"Node '{node_id}' requires tools {tools!r} but catalog is empty"
            )

    if errors:
        return HookDecision(
            action=HookAction.BLOCK,
            reason="Planner guard: routing references unknown agents",
            errors=errors,
            warnings=warnings,
        )
    if warnings:
        return HookDecision(
            action=HookAction.WARN,
            reason="Planner guard: tool availability warnings",
            warnings=warnings,
        )
    return HookDecision(
        action=HookAction.PROCEED,
        reason="Planner guard: routing is valid",
    )


# ============================================================================
# Internal helpers
# ============================================================================


def _aggregate_decisions(decisions: list[HookDecision]) -> HookResult:
    """
    Aggregate a list of HookDecision objects into a single HookResult.

    The ``final_action`` is the most severe action across all decisions,
    following the priority order:
    BLOCK > ESCALATE > REPLAN > RETRY > WARN > PROCEED

    Args:
        decisions: Non-empty list of decisions from evaluators.

    Returns:
        HookResult with the winning action and merged errors/warnings.
    """
    all_errors: list[str] = []
    all_warnings: list[str] = []
    actions_seen: set[HookAction] = set()

    for decision in decisions:
        all_errors.extend(decision.errors)
        all_warnings.extend(decision.warnings)
        actions_seen.add(decision.action)

    # Pick the highest-severity action observed.
    final_action = HookAction.PROCEED
    for action in _ACTION_SEVERITY:
        if action in actions_seen:
            final_action = action
            break

    return HookResult(
        decisions=decisions,
        final_action=final_action,
        all_errors=all_errors,
        all_warnings=all_warnings,
    )
