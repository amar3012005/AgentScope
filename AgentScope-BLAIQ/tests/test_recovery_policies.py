"""Comprehensive tests for agentscope_blaiq.contracts.recovery module."""

from __future__ import annotations

import asyncio

import pytest

from agentscope_blaiq.contracts.hooks import HookAction
from agentscope_blaiq.contracts.recovery import (
    DEFAULT_RECOVERY_POLICIES,
    FailureClass,
    RecoveryAction,
    RecoveryEvent,
    RetryBudget,
    classify_failure,
    resolve_recovery,
)


# ============================================================================
# FailureClass
# ============================================================================


class TestFailureClass:
    """Verify all 8 FailureClass enum members exist with correct values."""

    EXPECTED_MEMBERS: dict[str, str] = {
        "MISSING_REQUIREMENTS": "missing_requirements",
        "WEAK_EVIDENCE": "weak_evidence",
        "SCHEMA_MISMATCH": "schema_mismatch",
        "GOVERNANCE_FAILURE": "governance_failure",
        "TOOL_FAILURE": "tool_failure",
        "AGENT_TIMEOUT": "agent_timeout",
        "AGENT_ERROR": "agent_error",
        "UNKNOWN": "unknown",
    }

    def test_has_exactly_eight_members(self) -> None:
        assert len(FailureClass) == 8

    @pytest.mark.parametrize(
        ("name", "value"),
        EXPECTED_MEMBERS.items(),
        ids=EXPECTED_MEMBERS.keys(),
    )
    def test_member_value(self, name: str, value: str) -> None:
        member = FailureClass[name]
        assert member.value == value

    def test_is_str_enum(self) -> None:
        assert isinstance(FailureClass.UNKNOWN, str)


# ============================================================================
# RecoveryAction
# ============================================================================


class TestRecoveryAction:
    """RecoveryAction dataclass construction and field access."""

    def test_all_fields_populated(self) -> None:
        action = RecoveryAction(
            action=HookAction.RETRY,
            reason="testing",
            retry_same_node=True,
            rerun_upstream="research",
            escalate_to_hitl=False,
            block_workflow=False,
        )
        assert action.action is HookAction.RETRY
        assert action.reason == "testing"
        assert action.retry_same_node is True
        assert action.rerun_upstream == "research"
        assert action.escalate_to_hitl is False
        assert action.block_workflow is False

    def test_rerun_upstream_none(self) -> None:
        action = RecoveryAction(
            action=HookAction.BLOCK,
            reason="blocked",
            retry_same_node=False,
            rerun_upstream=None,
            escalate_to_hitl=False,
            block_workflow=True,
        )
        assert action.rerun_upstream is None


# ============================================================================
# RetryBudget
# ============================================================================


class TestRetryBudget:
    """RetryBudget lifecycle: can_retry, record_attempt, limits, summary."""

    def test_can_retry_initially(self) -> None:
        budget = RetryBudget(workflow_id="wf-1")
        assert budget.can_retry("node-a") is True

    def test_record_attempt_increments(self) -> None:
        budget = RetryBudget(workflow_id="wf-1")
        budget.record_attempt("node-a")
        assert budget.remaining("node-a") == 2  # 3 per-node max, 1 used

    def test_per_node_limit_enforced(self) -> None:
        budget = RetryBudget(workflow_id="wf-1")
        for _ in range(3):
            budget.record_attempt("node-a")
        assert budget.can_retry("node-a") is False
        # Other nodes are still fine
        assert budget.can_retry("node-b") is True

    def test_total_limit_enforced(self) -> None:
        budget = RetryBudget(workflow_id="wf-1")
        # Exhaust total budget across many nodes
        for i in range(10):
            budget.record_attempt(f"node-{i}")
        assert budget.can_retry("fresh-node") is False

    def test_is_exhausted_when_total_exceeded(self) -> None:
        budget = RetryBudget(workflow_id="wf-1")
        for i in range(10):
            budget.record_attempt(f"n-{i}")
        assert budget.is_exhausted() is True

    def test_is_exhausted_false_initially(self) -> None:
        budget = RetryBudget(workflow_id="wf-1")
        assert budget.is_exhausted() is False

    def test_remaining_counts(self) -> None:
        budget = RetryBudget(workflow_id="wf-1")
        assert budget.remaining("node-a") == 3
        budget.record_attempt("node-a")
        assert budget.remaining("node-a") == 2
        budget.record_attempt("node-a")
        assert budget.remaining("node-a") == 1
        budget.record_attempt("node-a")
        assert budget.remaining("node-a") == 0

    def test_remaining_capped_by_total(self) -> None:
        budget = RetryBudget(workflow_id="wf-1", max_total_retries=2)
        budget.record_attempt("node-a")
        # per-node: 2 left, total: 1 left -> min is 1
        assert budget.remaining("node-a") == 1

    def test_summary_returns_dict(self) -> None:
        budget = RetryBudget(workflow_id="wf-42")
        budget.record_attempt("alpha")
        budget.record_attempt("alpha")
        budget.record_attempt("beta")

        s = budget.summary()
        assert isinstance(s, dict)
        assert s["workflow_id"] == "wf-42"
        assert s["total_attempts"] == 3
        assert s["max_total_retries"] == 10
        assert s["max_per_node_retries"] == 3
        assert s["node_attempts"] == {"alpha": 2, "beta": 1}
        assert s["total_remaining"] == 7
        assert s["exhausted"] is False


# ============================================================================
# RecoveryEvent
# ============================================================================


class TestRecoveryEvent:
    """RecoveryEvent construction and factory method."""

    @pytest.fixture()
    def sample_action(self) -> RecoveryAction:
        return RecoveryAction(
            action=HookAction.RETRY,
            reason="test",
            retry_same_node=True,
            rerun_upstream=None,
            escalate_to_hitl=False,
            block_workflow=False,
        )

    def test_all_fields_populated(self, sample_action: RecoveryAction) -> None:
        event = RecoveryEvent(
            event_id="ev-1",
            workflow_id="wf-1",
            node_id="research",
            agent_id="agent-1",
            failure_class=FailureClass.AGENT_TIMEOUT,
            recovery_action=sample_action,
            attempt_number=0,
            budget_remaining=3,
            error_message="timed out",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert event.event_id == "ev-1"
        assert event.workflow_id == "wf-1"
        assert event.node_id == "research"
        assert event.agent_id == "agent-1"
        assert event.failure_class is FailureClass.AGENT_TIMEOUT
        assert event.recovery_action is sample_action
        assert event.attempt_number == 0
        assert event.budget_remaining == 3
        assert event.error_message == "timed out"
        assert event.timestamp == "2026-01-01T00:00:00+00:00"

    def test_create_factory_auto_populates(
        self, sample_action: RecoveryAction
    ) -> None:
        event = RecoveryEvent.create(
            workflow_id="wf-2",
            node_id="draft",
            agent_id="agent-2",
            failure_class=FailureClass.SCHEMA_MISMATCH,
            recovery_action=sample_action,
            attempt_number=1,
            budget_remaining=2,
            error_message="bad schema",
        )
        # Auto-generated fields
        assert event.event_id  # non-empty UUID string
        assert event.timestamp  # non-empty ISO timestamp
        # Passed-through fields
        assert event.workflow_id == "wf-2"
        assert event.node_id == "draft"
        assert event.error_message == "bad schema"

    def test_create_factory_error_message_defaults_none(
        self, sample_action: RecoveryAction
    ) -> None:
        event = RecoveryEvent.create(
            workflow_id=None,
            node_id="n",
            agent_id="a",
            failure_class=FailureClass.UNKNOWN,
            recovery_action=sample_action,
            attempt_number=0,
            budget_remaining=0,
        )
        assert event.error_message is None
        assert event.workflow_id is None


# ============================================================================
# DEFAULT_RECOVERY_POLICIES
# ============================================================================


class TestDefaultPolicies:
    """Validate default policy map is complete and uses correct actions."""

    EXPECTED_ACTIONS: dict[FailureClass, HookAction] = {
        FailureClass.MISSING_REQUIREMENTS: HookAction.ESCALATE,
        FailureClass.WEAK_EVIDENCE: HookAction.RETRY,
        FailureClass.SCHEMA_MISMATCH: HookAction.RETRY,
        FailureClass.GOVERNANCE_FAILURE: HookAction.BLOCK,
        FailureClass.TOOL_FAILURE: HookAction.RETRY,
        FailureClass.AGENT_TIMEOUT: HookAction.RETRY,
        FailureClass.AGENT_ERROR: HookAction.REPLAN,
        FailureClass.UNKNOWN: HookAction.ESCALATE,
    }

    def test_all_failure_classes_have_entries(self) -> None:
        for fc in FailureClass:
            assert fc in DEFAULT_RECOVERY_POLICIES, f"Missing policy for {fc}"

    @pytest.mark.parametrize(
        ("fc", "expected_action"),
        EXPECTED_ACTIONS.items(),
        ids=[fc.name for fc in EXPECTED_ACTIONS],
    )
    def test_action_type(
        self, fc: FailureClass, expected_action: HookAction
    ) -> None:
        assert DEFAULT_RECOVERY_POLICIES[fc].action is expected_action


# ============================================================================
# classify_failure
# ============================================================================


class TestClassifyFailure:
    """Verify classification heuristics in priority order."""

    def test_timeout_error_classifies_as_agent_timeout(self) -> None:
        assert (
            classify_failure(asyncio.TimeoutError())
            is FailureClass.AGENT_TIMEOUT
        )

    def test_builtin_timeout_error(self) -> None:
        assert (
            classify_failure(TimeoutError("connection timeout"))
            is FailureClass.AGENT_TIMEOUT
        )

    def test_timeout_in_message(self) -> None:
        assert (
            classify_failure(RuntimeError("request timeout after 30s"))
            is FailureClass.AGENT_TIMEOUT
        )

    def test_schema_keyword_classifies_as_schema_mismatch(self) -> None:
        assert (
            classify_failure(ValueError("output schema invalid"))
            is FailureClass.SCHEMA_MISMATCH
        )

    def test_governance_context(self) -> None:
        assert (
            classify_failure(None, {"governance_rejected": True})
            is FailureClass.GOVERNANCE_FAILURE
        )

    def test_weak_evidence_context(self) -> None:
        assert (
            classify_failure(None, {"weak_evidence": True})
            is FailureClass.WEAK_EVIDENCE
        )

    def test_insufficient_in_error_message(self) -> None:
        assert (
            classify_failure(RuntimeError("insufficient results"))
            is FailureClass.WEAK_EVIDENCE
        )

    def test_missing_keys_context(self) -> None:
        assert (
            classify_failure(None, {"missing_keys": ["title", "body"]})
            is FailureClass.MISSING_REQUIREMENTS
        )

    def test_tool_id_context(self) -> None:
        assert (
            classify_failure(RuntimeError("boom"), {"tool_id": "tavily"})
            is FailureClass.TOOL_FAILURE
        )

    def test_agent_id_context_gives_agent_error(self) -> None:
        assert (
            classify_failure(RuntimeError("crash"), {"agent_id": "writer"})
            is FailureClass.AGENT_ERROR
        )

    def test_generic_exception_no_context_returns_unknown(self) -> None:
        assert classify_failure(RuntimeError("something")) is FailureClass.UNKNOWN

    def test_none_error_no_context_returns_unknown(self) -> None:
        assert classify_failure(None) is FailureClass.UNKNOWN

    def test_none_error_empty_context_returns_unknown(self) -> None:
        assert classify_failure(None, {}) is FailureClass.UNKNOWN


# ============================================================================
# resolve_recovery
# ============================================================================


class TestResolveRecovery:
    """Resolution logic: default lookup, budget exhaustion, idempotency."""

    def test_uses_default_policy(self) -> None:
        budget = RetryBudget(workflow_id="wf")
        action = resolve_recovery(
            FailureClass.SCHEMA_MISMATCH, budget, node_id="draft"
        )
        assert action.action is HookAction.RETRY
        assert action.retry_same_node is True

    def test_escalate_when_budget_exhausted(self) -> None:
        budget = RetryBudget(workflow_id="wf", max_per_node_retries=1)
        budget.record_attempt("draft")  # exhaust per-node budget
        action = resolve_recovery(
            FailureClass.SCHEMA_MISMATCH, budget, node_id="draft"
        )
        assert action.action is HookAction.ESCALATE
        assert action.escalate_to_hitl is True
        assert "exhausted" in action.reason.lower()

    def test_escalate_when_total_budget_exhausted(self) -> None:
        budget = RetryBudget(workflow_id="wf", max_total_retries=2)
        budget.record_attempt("a")
        budget.record_attempt("b")
        action = resolve_recovery(
            FailureClass.AGENT_TIMEOUT, budget, node_id="c"
        )
        assert action.action is HookAction.ESCALATE

    def test_tool_failure_upgrades_to_block_when_not_idempotent(self) -> None:
        budget = RetryBudget(workflow_id="wf")
        action = resolve_recovery(
            FailureClass.TOOL_FAILURE,
            budget,
            node_id="search",
            tool_idempotent=False,
        )
        assert action.action is HookAction.BLOCK
        assert action.block_workflow is True
        assert "not idempotent" in action.reason.lower()

    def test_tool_failure_stays_retry_when_idempotent(self) -> None:
        budget = RetryBudget(workflow_id="wf")
        action = resolve_recovery(
            FailureClass.TOOL_FAILURE,
            budget,
            node_id="search",
            tool_idempotent=True,
        )
        assert action.action is HookAction.RETRY

    def test_custom_policies_override_defaults(self) -> None:
        custom = {
            FailureClass.UNKNOWN: RecoveryAction(
                action=HookAction.BLOCK,
                reason="custom block",
                retry_same_node=False,
                rerun_upstream=None,
                escalate_to_hitl=False,
                block_workflow=True,
            ),
        }
        budget = RetryBudget(workflow_id="wf")
        action = resolve_recovery(
            FailureClass.UNKNOWN,
            budget,
            node_id="x",
            custom_policies=custom,
        )
        assert action.action is HookAction.BLOCK
        assert action.reason == "custom block"

    def test_block_action_not_escalated_even_when_budget_exhausted(self) -> None:
        """BLOCK and ESCALATE actions should not be upgraded by budget logic."""
        budget = RetryBudget(workflow_id="wf", max_per_node_retries=0)
        action = resolve_recovery(
            FailureClass.GOVERNANCE_FAILURE, budget, node_id="gov"
        )
        # BLOCK is not in (RETRY, REPLAN), so budget check doesn't apply
        assert action.action is HookAction.BLOCK

    def test_replan_escalated_when_budget_exhausted(self) -> None:
        """REPLAN should also be upgraded to ESCALATE on exhaustion."""
        budget = RetryBudget(workflow_id="wf", max_per_node_retries=0)
        action = resolve_recovery(
            FailureClass.AGENT_ERROR, budget, node_id="writer"
        )
        assert action.action is HookAction.ESCALATE
