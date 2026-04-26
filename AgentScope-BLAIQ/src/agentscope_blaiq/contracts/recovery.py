"""
Failure classification and recovery policy contracts.

Pure dataclasses and enums that define how the workflow engine classifies
failures and determines recovery actions.  No runtime imports, no agentscope
dependency -- everything is self-contained so the engine, hooks, and tests
can import without side-effects.

Usage::

    from agentscope_blaiq.contracts.recovery import (
        FailureClass,
        RecoveryAction,
        RetryBudget,
        RecoveryEvent,
        DEFAULT_RECOVERY_POLICIES,
        classify_failure,
        resolve_recovery,
    )

    fc = classify_failure(error, {"tool_id": "tavily_search"})
    budget = RetryBudget(workflow_id="wf-123")
    action = resolve_recovery(fc, budget, node_id="research")
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .hooks import HookAction


# ============================================================================
# Enums
# ============================================================================


class FailureClass(str, Enum):
    """Categorises what went wrong during agent or tool execution."""

    MISSING_REQUIREMENTS = "missing_requirements"
    """One or more required input fields are absent."""

    WEAK_EVIDENCE = "weak_evidence"
    """Research returned thin or insufficient results."""

    SCHEMA_MISMATCH = "schema_mismatch"
    """Output does not match the declared output schema."""

    GOVERNANCE_FAILURE = "governance_failure"
    """Governance approval was rejected."""

    TOOL_FAILURE = "tool_failure"
    """A tool raised an exception during execution."""

    AGENT_TIMEOUT = "agent_timeout"
    """An agent exceeded its configured timeout_seconds."""

    AGENT_ERROR = "agent_error"
    """An agent raised a non-timeout exception."""

    UNKNOWN = "unknown"
    """Unclassified failure."""


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class RecoveryAction:
    """Prescribes what the engine should do in response to a classified failure.

    Attributes:
        action: The hook action that drives engine behaviour.
        reason: Human-readable explanation for the recovery decision.
        retry_same_node: When True the engine should re-dispatch the same node.
        rerun_upstream: Optional node_id of an upstream node to re-run
            (e.g. ``"research"`` when evidence is too thin).
        escalate_to_hitl: When True the engine should pause for human review.
        block_workflow: When True the workflow should be halted immediately.
    """

    action: HookAction
    reason: str
    retry_same_node: bool
    rerun_upstream: str | None
    escalate_to_hitl: bool
    block_workflow: bool


@dataclass
class RetryBudget:
    """Per-workflow retry budget tracker.

    Tracks both total retries across all nodes and per-node retry counts so the
    engine can make informed decisions about whether further retries are
    worthwhile.

    Attributes:
        workflow_id: Identifier for the workflow this budget belongs to.
        max_total_retries: Maximum retries allowed across all nodes combined.
        max_per_node_retries: Maximum retries allowed for any single node.
    """

    workflow_id: str
    max_total_retries: int = 10
    max_per_node_retries: int = 3
    _node_attempts: dict[str, int] = field(default_factory=dict)
    _total_attempts: int = 0

    def can_retry(self, node_id: str) -> bool:
        """Return True if the budget allows another retry for *node_id*.

        Args:
            node_id: The node requesting a retry.

        Returns:
            True when both the per-node and total budgets have capacity.
        """
        if self._total_attempts >= self.max_total_retries:
            return False
        return self._node_attempts.get(node_id, 0) < self.max_per_node_retries

    def record_attempt(self, node_id: str) -> None:
        """Record a retry attempt for *node_id*.

        Args:
            node_id: The node that was retried.
        """
        self._node_attempts[node_id] = self._node_attempts.get(node_id, 0) + 1
        self._total_attempts += 1

    def is_exhausted(self) -> bool:
        """Return True if the total retry budget has been fully consumed."""
        return self._total_attempts >= self.max_total_retries

    def remaining(self, node_id: str) -> int:
        """Return how many retries remain for *node_id*.

        Takes the minimum of per-node remaining and total remaining so the
        caller never exceeds either limit.

        Args:
            node_id: The node to check.

        Returns:
            Non-negative integer of remaining retries.
        """
        per_node_remaining = self.max_per_node_retries - self._node_attempts.get(
            node_id, 0
        )
        total_remaining = self.max_total_retries - self._total_attempts
        return max(0, min(per_node_remaining, total_remaining))

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of the budget state.

        Returns:
            Dict with total/per-node attempt counts and remaining budget.
        """
        return {
            "workflow_id": self.workflow_id,
            "total_attempts": self._total_attempts,
            "max_total_retries": self.max_total_retries,
            "max_per_node_retries": self.max_per_node_retries,
            "node_attempts": dict(self._node_attempts),
            "total_remaining": max(0, self.max_total_retries - self._total_attempts),
            "exhausted": self.is_exhausted(),
        }


@dataclass
class RecoveryEvent:
    """Structured log entry emitted whenever a recovery action is taken.

    Attributes:
        event_id: Unique identifier for this event (UUID4).
        workflow_id: Workflow instance this event belongs to (may be None).
        node_id: The node that failed.
        agent_id: The agent assigned to the failed node.
        failure_class: Classification of the failure.
        recovery_action: The recovery action that was chosen.
        attempt_number: Which attempt this failure occurred on (0-indexed).
        budget_remaining: Retries remaining for this node after this event.
        error_message: Original error message, if any.
        timestamp: ISO 8601 timestamp of when the event was recorded.
    """

    event_id: str
    workflow_id: str | None
    node_id: str
    agent_id: str
    failure_class: FailureClass
    recovery_action: RecoveryAction
    attempt_number: int
    budget_remaining: int
    error_message: str | None
    timestamp: str

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str | None,
        node_id: str,
        agent_id: str,
        failure_class: FailureClass,
        recovery_action: RecoveryAction,
        attempt_number: int,
        budget_remaining: int,
        error_message: str | None = None,
    ) -> RecoveryEvent:
        """Factory that auto-populates event_id and timestamp.

        Args:
            workflow_id: Workflow instance identifier.
            node_id: The failed node identifier.
            agent_id: The agent assigned to the node.
            failure_class: Classified failure type.
            recovery_action: Chosen recovery action.
            attempt_number: Current attempt number.
            budget_remaining: Remaining retries for this node.
            error_message: Original error message.

        Returns:
            A fully populated RecoveryEvent.
        """
        return cls(
            event_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            node_id=node_id,
            agent_id=agent_id,
            failure_class=failure_class,
            recovery_action=recovery_action,
            attempt_number=attempt_number,
            budget_remaining=budget_remaining,
            error_message=error_message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ============================================================================
# Default recovery policies
# ============================================================================

DEFAULT_RECOVERY_POLICIES: dict[FailureClass, RecoveryAction] = {
    FailureClass.MISSING_REQUIREMENTS: RecoveryAction(
        action=HookAction.ESCALATE,
        reason="Required input fields missing — escalate to HITL or re-research",
        retry_same_node=False,
        rerun_upstream=None,
        escalate_to_hitl=True,
        block_workflow=False,
    ),
    FailureClass.WEAK_EVIDENCE: RecoveryAction(
        action=HookAction.RETRY,
        reason="Evidence too thin — retry research with narrower scope",
        retry_same_node=False,
        rerun_upstream="research",
        escalate_to_hitl=False,
        block_workflow=False,
    ),
    FailureClass.SCHEMA_MISMATCH: RecoveryAction(
        action=HookAction.RETRY,
        reason="Output schema mismatch — retry same agent with tighter context",
        retry_same_node=True,
        rerun_upstream=None,
        escalate_to_hitl=False,
        block_workflow=False,
    ),
    FailureClass.GOVERNANCE_FAILURE: RecoveryAction(
        action=HookAction.BLOCK,
        reason="Governance approval rejected — block or fix upstream",
        retry_same_node=False,
        rerun_upstream=None,
        escalate_to_hitl=False,
        block_workflow=True,
    ),
    FailureClass.TOOL_FAILURE: RecoveryAction(
        action=HookAction.RETRY,
        reason="Tool failed — retry only if idempotent",
        retry_same_node=True,
        rerun_upstream=None,
        escalate_to_hitl=False,
        block_workflow=False,
    ),
    FailureClass.AGENT_TIMEOUT: RecoveryAction(
        action=HookAction.RETRY,
        reason="Agent exceeded timeout — retry with same input",
        retry_same_node=True,
        rerun_upstream=None,
        escalate_to_hitl=False,
        block_workflow=False,
    ),
    FailureClass.AGENT_ERROR: RecoveryAction(
        action=HookAction.REPLAN,
        reason="Agent error after retries — trigger replan from strategist",
        retry_same_node=False,
        rerun_upstream=None,
        escalate_to_hitl=False,
        block_workflow=False,
    ),
    FailureClass.UNKNOWN: RecoveryAction(
        action=HookAction.ESCALATE,
        reason="Unclassified failure — escalate for human review",
        retry_same_node=False,
        rerun_upstream=None,
        escalate_to_hitl=True,
        block_workflow=False,
    ),
}


# ============================================================================
# Classification
# ============================================================================


def classify_failure(
    error: BaseException | None,
    context: dict[str, Any] | None = None,
) -> FailureClass:
    """Inspect an exception and optional context dict to classify the failure.

    Classification rules (evaluated in priority order):

    1. ``asyncio.TimeoutError`` or ``"timeout"`` in the error string
       -> ``AGENT_TIMEOUT``
    2. ``jsonschema.ValidationError`` or ``"schema"`` in the error string
       -> ``SCHEMA_MISMATCH``
    3. Context contains ``governance_rejected=True``
       -> ``GOVERNANCE_FAILURE``
    4. Context contains ``weak_evidence=True`` **or** error mentions
       ``"insufficient"`` -> ``WEAK_EVIDENCE``
    5. Context contains ``missing_keys`` (non-empty)
       -> ``MISSING_REQUIREMENTS``
    6. Context contains ``tool_id``
       -> ``TOOL_FAILURE``
    7. Context contains ``agent_id`` (implies an agent-level error)
       -> ``AGENT_ERROR``
    8. Otherwise -> ``UNKNOWN``

    Args:
        error: The exception that was raised, or None.
        context: Optional dict with extra classification hints (e.g.
            ``tool_id``, ``governance_rejected``, ``weak_evidence``,
            ``missing_keys``, ``agent_id``).

    Returns:
        The most appropriate FailureClass for the error.
    """
    ctx = context or {}
    error_str = str(error).lower() if error is not None else ""

    # 1. Timeout
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return FailureClass.AGENT_TIMEOUT
    if "timeout" in error_str:
        return FailureClass.AGENT_TIMEOUT

    # 2. Schema mismatch
    _is_validation_error = (
        error is not None
        and type(error).__name__ == "ValidationError"
        and "jsonschema" in type(error).__module__
    ) if error is not None else False
    if _is_validation_error or "schema" in error_str:
        return FailureClass.SCHEMA_MISMATCH

    # 3. Governance
    if ctx.get("governance_rejected"):
        return FailureClass.GOVERNANCE_FAILURE

    # 4. Weak evidence
    if ctx.get("weak_evidence") or "insufficient" in error_str:
        return FailureClass.WEAK_EVIDENCE

    # 5. Missing requirements
    if ctx.get("missing_keys"):
        return FailureClass.MISSING_REQUIREMENTS

    # 6. Tool failure
    if ctx.get("tool_id"):
        return FailureClass.TOOL_FAILURE

    # 7. Agent error (context has agent_id — implies agent-level failure)
    if ctx.get("agent_id"):
        return FailureClass.AGENT_ERROR

    # 8. Fallback
    return FailureClass.UNKNOWN


# ============================================================================
# Resolution
# ============================================================================


def resolve_recovery(
    failure_class: FailureClass,
    budget: RetryBudget,
    node_id: str,
    *,
    tool_idempotent: bool | None = None,
    custom_policies: dict[FailureClass, RecoveryAction] | None = None,
) -> RecoveryAction:
    """Determine the final recovery action for a classified failure.

    Resolution logic:

    1. Look up the policy in *custom_policies* (if provided), falling back to
       ``DEFAULT_RECOVERY_POLICIES``.
    2. If the budget is exhausted for *node_id*, upgrade the action to
       ``ESCALATE``.
    3. For ``TOOL_FAILURE``: if the tool is **not** idempotent, upgrade the
       action to ``BLOCK`` (retrying a non-idempotent tool is unsafe).

    Args:
        failure_class: The classified failure type.
        budget: The retry budget for the current workflow.
        node_id: The node that experienced the failure.
        tool_idempotent: Whether the failed tool is idempotent. Only relevant
            for ``TOOL_FAILURE``; ignored for other failure classes.
        custom_policies: Optional override mapping. Entries here take
            precedence over ``DEFAULT_RECOVERY_POLICIES``.

    Returns:
        The final RecoveryAction the engine should execute.
    """
    policies = {**DEFAULT_RECOVERY_POLICIES, **(custom_policies or {})}
    base_action = policies.get(failure_class, DEFAULT_RECOVERY_POLICIES[FailureClass.UNKNOWN])

    # Budget exhaustion check — upgrade to ESCALATE
    if not budget.can_retry(node_id) and base_action.action in (
        HookAction.RETRY,
        HookAction.REPLAN,
    ):
        return RecoveryAction(
            action=HookAction.ESCALATE,
            reason=(
                f"Retry budget exhausted for node '{node_id}' — "
                f"original action was {base_action.action.value}; escalating"
            ),
            retry_same_node=False,
            rerun_upstream=None,
            escalate_to_hitl=True,
            block_workflow=False,
        )

    # Tool idempotency check — non-idempotent tools must not be retried
    if (
        failure_class is FailureClass.TOOL_FAILURE
        and tool_idempotent is not None
        and not tool_idempotent
    ):
        return RecoveryAction(
            action=HookAction.BLOCK,
            reason=(
                "Tool is not idempotent — retrying could cause side-effects; "
                "blocking workflow"
            ),
            retry_same_node=False,
            rerun_upstream=None,
            escalate_to_hitl=False,
            block_workflow=True,
        )

    return base_action
