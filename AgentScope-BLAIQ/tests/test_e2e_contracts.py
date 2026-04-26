"""
End-to-end contract tests per workflow family.

Simulates each workflow's node chain through the contract validation layer
WITHOUT needing agentscope runtime.  For every workflow template we:

1. Load the template from registry.
2. Walk each node in DAG (topological) order.
3. For each node: create RuntimeMsg input envelope -> validate schema ->
   create output envelope -> validate handoff to next node.
4. Verify MessageLog captures full replay chain.
5. Inject a failure and verify recovery policy produces the correct action.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from agentscope_blaiq.contracts.harness import (
    Node,
    WorkflowTemplate,
)
from agentscope_blaiq.contracts.hooks import HookAction
from agentscope_blaiq.contracts.messages import (
    MessageLog,
    MsgType,
    RuntimeMsg,
    deserialize_msg,
    make_agent_input,
    make_agent_output,
    make_handoff,
    serialize_msg,
    validate_msg_schema,
)
from agentscope_blaiq.contracts.recovery import (
    DEFAULT_RECOVERY_POLICIES,
    FailureClass,
    RecoveryAction,
    RecoveryEvent,
    RetryBudget,
    classify_failure,
    resolve_recovery,
)
from agentscope_blaiq.contracts.registry import (
    HarnessRegistry,
    get_registry,
    reset_registry,
)

# Enforcement may or may not exist yet -- guard import.
try:
    from agentscope_blaiq.contracts.enforcement import (
        ContractViolationError,
        EnforcementMode,
        enforcement_check,
        set_enforcement_mode,
    )

    _HAS_ENFORCEMENT = True
except ImportError:
    _HAS_ENFORCEMENT = False


# ============================================================================
# Helpers
# ============================================================================


def _walk_workflow_nodes(template: WorkflowTemplate) -> list[Node]:
    """Return nodes in topological (DAG) order.

    Uses a Kahn-style sort based on input_from / output_to edges.
    Nodes whose only input is "start" are considered roots.
    """
    node_map: dict[str, Node] = {n.node_id: n for n in template.nodes}
    # Build in-degree map (ignore "start" as a source).
    in_degree: dict[str, int] = {n.node_id: 0 for n in template.nodes}
    for node in template.nodes:
        for src in node.input_from:
            if src != "start" and src in node_map:
                in_degree[node.node_id] += 1

    queue: list[str] = [nid for nid, deg in in_degree.items() if deg == 0]
    ordered: list[Node] = []

    while queue:
        nid = queue.pop(0)
        ordered.append(node_map[nid])
        for target in node_map[nid].output_to:
            if target in in_degree:
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    queue.append(target)

    return ordered


def _dummy_payload_for_agent(
    agent_id: str,
    registry: HarnessRegistry,
) -> dict[str, Any]:
    """Generate minimal valid payload matching agent's input_schema.

    Fills required keys with dummy values based on JSON-Schema type.
    """
    harness = registry.get_agent(agent_id)
    if harness is None:
        return {"query": "dummy"}

    schema = harness.input_schema
    payload: dict[str, Any] = {}
    required: list[str] = schema.get("required", [])
    properties: dict[str, Any] = schema.get("properties", {})

    _type_defaults: dict[str, Any] = {
        "string": "dummy_value",
        "integer": 1,
        "number": 1.0,
        "boolean": True,
        "array": [],
        "object": {},
    }

    for key in required:
        prop = properties.get(key, {})
        json_type = prop.get("type", "string")
        payload[key] = _type_defaults.get(json_type, "dummy")

    return payload


def _simulate_workflow(
    template: WorkflowTemplate,
    registry: HarnessRegistry,
    workflow_instance_id: str = "wf-test-001",
) -> tuple[MessageLog, list[RuntimeMsg]]:
    """Walk a workflow DAG through the contract layer.

    For each node:
    1. Create AGENT_INPUT envelope.
    2. Validate schema.
    3. Create AGENT_OUTPUT envelope.
    4. If there is a next node, create HANDOFF envelope.

    Returns the MessageLog and the list of output messages (last output per node).
    """
    log = MessageLog()
    ordered_nodes = _walk_workflow_nodes(template)
    outputs: list[RuntimeMsg] = []
    last_output: RuntimeMsg | None = None

    for node in ordered_nodes:
        # --- input ---
        payload = _dummy_payload_for_agent(node.agent_id, registry)
        inp = make_agent_input(
            workflow_id=workflow_instance_id,
            node_id=node.node_id,
            agent_id=node.agent_id,
            payload=payload,
        )
        log.append(inp)

        ok, errors = validate_msg_schema(inp, registry)
        assert ok, f"Input schema validation failed for {node.agent_id}: {errors}"

        # --- output ---
        out_payload = _dummy_output_for_agent(node.agent_id, registry)
        out = make_agent_output(inp, out_payload)
        log.append(out)
        outputs.append(out)
        last_output = out

        # --- handoff to downstream nodes ---
        for target_node_id in node.output_to:
            target_node = _find_node(template, target_node_id)
            if target_node is not None:
                handoff = make_handoff(out, target_node_id, target_node.agent_id)
                log.append(handoff)

    return log, outputs


def _dummy_output_for_agent(
    agent_id: str,
    registry: HarnessRegistry,
) -> dict[str, Any]:
    """Generate minimal valid output payload matching agent's output_schema."""
    harness = registry.get_agent(agent_id)
    if harness is None:
        return {"result": "done"}

    schema = harness.output_schema
    payload: dict[str, Any] = {}
    required: list[str] = schema.get("required", [])
    properties: dict[str, Any] = schema.get("properties", {})

    _type_defaults: dict[str, Any] = {
        "string": "output_value",
        "integer": 42,
        "number": 0.95,
        "boolean": True,
        "array": [],
        "object": {},
    }

    for key in required:
        prop = properties.get(key, {})
        json_type = prop.get("type", "string")
        payload[key] = _type_defaults.get(json_type, "output")

    return payload


def _find_node(template: WorkflowTemplate, node_id: str) -> Node | None:
    """Find a node by ID in a workflow template."""
    for n in template.nodes:
        if n.node_id == node_id:
            return n
    return None


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def registry() -> HarnessRegistry:
    """Provide a fresh, fully loaded registry for each test."""
    reset_registry()
    hr = get_registry()
    # get_registry already loads builtins, but be explicit:
    hr.load_builtin_workflows()
    return hr


# ============================================================================
# TestTextArtifactE2E
# ============================================================================


class TestTextArtifactE2E:
    """Walk text_artifact_v1: strategist -> research -> hitl_verification -> research_final_recall -> content_director -> text_buddy -> governance."""

    def test_full_dag_walk(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        ordered = _walk_workflow_nodes(template)
        expected_ids = ["strategist", "research", "hitl_verification", "research_final_recall", "content_director", "text_buddy", "governance"]
        assert [n.node_id for n in ordered] == expected_ids

    def test_envelopes_and_validation(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)
        # 7 nodes x (input + output) = 14, plus 6 handoffs = 20
        assert len(log) >= 14

        # Every output should have a parent_msg_id linking to its input.
        for out in outputs:
            assert out.parent_msg_id is not None
            assert out.msg_type == MsgType.AGENT_OUTPUT

    def test_handoff_links(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        log, _ = _simulate_workflow(template, registry)

        handoffs = [
            m for m in log.messages if isinstance(m, RuntimeMsg) and m.msg_type == MsgType.HANDOFF
        ]
        # text_artifact_v1 has 6 handoffs (strategist->research, research->hitl, hitl->final_recall, final_recall->content_director, content_director->text_buddy, text_buddy->governance)
        assert len(handoffs) == 6

        handoff_pairs = [(h.parent_msg_id is not None, h.node_id) for h in handoffs]
        target_nodes = {h.node_id for h in handoffs}
        assert "research" in target_nodes
        assert "hitl_verification" in target_nodes
        assert "research_final_recall" in target_nodes
        assert "content_director" in target_nodes
        assert "text_buddy" in target_nodes
        assert "governance" in target_nodes

    def test_message_log_chain(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)

        # Trace chain from the last output back to root.
        last_out = outputs[-1]
        chain = log.get_chain(last_out.msg_id)
        assert len(chain) >= 2  # at least input + output for the last node

        # The first message in the chain should be an earlier message.
        assert chain[0].msg_id != last_out.msg_id

    def test_schema_mismatch_recovery(self, registry: HarnessRegistry) -> None:
        """Inject SCHEMA_MISMATCH at text_buddy, verify recovery -> RETRY."""
        fc = classify_failure(
            ValueError("output schema mismatch"),
            {"agent_id": "text_buddy"},
        )
        assert fc == FailureClass.SCHEMA_MISMATCH

        budget = RetryBudget(workflow_id="wf-test")
        action = resolve_recovery(fc, budget, node_id="text_buddy")
        assert action.action == HookAction.RETRY
        assert action.retry_same_node is True


# ============================================================================
# TestVisualArtifactE2E
# ============================================================================


class TestVisualArtifactE2E:
    """Walk visual_artifact_v1: strategist -> research -> hitl_verification -> research_final_recall -> content_director -> vangogh -> governance."""

    def test_full_dag_walk(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("visual_artifact_v1")
        assert template is not None

        ordered = _walk_workflow_nodes(template)
        expected_ids = ["strategist", "research", "hitl_verification", "research_final_recall", "content_director", "vangogh", "governance"]
        assert [n.node_id for n in ordered] == expected_ids

    def test_envelopes_and_validation(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("visual_artifact_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)
        # 7 nodes x (input + output) = 14, plus 6 handoffs = 20
        assert len(log) >= 14
        assert len(outputs) == 7

    def test_handoff_count(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("visual_artifact_v1")
        assert template is not None

        log, _ = _simulate_workflow(template, registry)
        handoffs = [
            m for m in log.messages if isinstance(m, RuntimeMsg) and m.msg_type == MsgType.HANDOFF
        ]
        assert len(handoffs) == 6

    def test_governance_failure_recovery(self, registry: HarnessRegistry) -> None:
        """Inject GOVERNANCE_FAILURE at governance node, verify -> BLOCK."""
        fc = classify_failure(
            RuntimeError("governance check failed"),
            {"governance_rejected": True},
        )
        assert fc == FailureClass.GOVERNANCE_FAILURE

        budget = RetryBudget(workflow_id="wf-test")
        action = resolve_recovery(fc, budget, node_id="governance")
        assert action.action == HookAction.BLOCK
        assert action.block_workflow is True


# ============================================================================
# TestResearchE2E
# ============================================================================


class TestResearchE2E:
    """Walk research_v1: research -> {deep_research + text_buddy} (fanout/merge)."""

    def test_full_dag_walk(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("research_v1")
        assert template is not None

        ordered = _walk_workflow_nodes(template)
        node_ids = [n.node_id for n in ordered]

        # research must come first, text_buddy last (merge point)
        assert node_ids[0] == "research"
        assert node_ids[-1] == "text_buddy"
        # deep_research is in the middle
        assert "deep_research" in node_ids

    def test_parallel_group_handling(self, registry: HarnessRegistry) -> None:
        """Verify research and deep_research share a parallel_group."""
        template = registry.get_workflow("research_v1")
        assert template is not None

        research_node = _find_node(template, "research")
        deep_node = _find_node(template, "deep_research")
        assert research_node is not None
        assert deep_node is not None
        assert research_node.parallel_group == "research_phase"
        assert deep_node.parallel_group == "research_phase"

    def test_fanout_merge_structure(self, registry: HarnessRegistry) -> None:
        """Verify fanout from research and merge at text_buddy."""
        template = registry.get_workflow("research_v1")
        assert template is not None

        research_node = _find_node(template, "research")
        text_buddy_node = _find_node(template, "text_buddy")
        assert research_node is not None
        assert text_buddy_node is not None

        # research fans out to both deep_research and text_buddy
        assert "deep_research" in research_node.output_to
        assert "text_buddy" in research_node.output_to

        # text_buddy merges from research and deep_research
        assert "research" in text_buddy_node.input_from
        assert "deep_research" in text_buddy_node.input_from

    def test_envelopes_and_validation(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("research_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)
        assert len(outputs) == 3  # research, deep_research, text_buddy

    def test_weak_evidence_recovery(self, registry: HarnessRegistry) -> None:
        """Inject WEAK_EVIDENCE failure, verify -> RETRY with rerun_upstream='research'."""
        fc = classify_failure(
            ValueError("insufficient evidence"),
            {"weak_evidence": True},
        )
        assert fc == FailureClass.WEAK_EVIDENCE

        budget = RetryBudget(workflow_id="wf-test")
        action = resolve_recovery(fc, budget, node_id="deep_research")
        assert action.action == HookAction.RETRY
        assert action.rerun_upstream == "research"


# ============================================================================
# TestFinanceE2E
# ============================================================================


class TestFinanceE2E:
    """Walk finance_v1: finance_research -> data_science -> text_buddy -> governance."""

    def test_full_dag_walk(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("finance_v1")
        assert template is not None

        ordered = _walk_workflow_nodes(template)
        expected_ids = ["finance_research", "data_science", "text_buddy", "governance"]
        assert [n.node_id for n in ordered] == expected_ids

    def test_envelopes_and_validation(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("finance_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)
        assert len(outputs) == 4

    def test_tool_failure_idempotent_recovery(self, registry: HarnessRegistry) -> None:
        """Inject TOOL_FAILURE with idempotent=True, verify -> RETRY."""
        fc = classify_failure(
            RuntimeError("tool crashed"),
            {"tool_id": "hivemind_recall"},
        )
        assert fc == FailureClass.TOOL_FAILURE

        budget = RetryBudget(workflow_id="wf-test")
        action = resolve_recovery(
            fc, budget, node_id="finance_research", tool_idempotent=True,
        )
        assert action.action == HookAction.RETRY
        assert action.retry_same_node is True

    def test_tool_failure_non_idempotent_recovery(self, registry: HarnessRegistry) -> None:
        """Inject TOOL_FAILURE with idempotent=False, verify -> BLOCK."""
        fc = classify_failure(
            RuntimeError("tool crashed"),
            {"tool_id": "sandbox_execute"},
        )
        assert fc == FailureClass.TOOL_FAILURE

        budget = RetryBudget(workflow_id="wf-test")
        action = resolve_recovery(
            fc, budget, node_id="data_science", tool_idempotent=False,
        )
        assert action.action == HookAction.BLOCK
        assert action.block_workflow is True


# ============================================================================
# TestDirectAnswerE2E
# ============================================================================


class TestDirectAnswerE2E:
    """Walk direct_answer_v1: research -> text_buddy (minimal, no governance)."""

    def test_full_dag_walk(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("direct_answer_v1")
        assert template is not None

        ordered = _walk_workflow_nodes(template)
        expected_ids = ["research", "text_buddy"]
        assert [n.node_id for n in ordered] == expected_ids

    def test_no_governance_node(self, registry: HarnessRegistry) -> None:
        """Verify direct_answer_v1 has no governance node."""
        template = registry.get_workflow("direct_answer_v1")
        assert template is not None

        node_ids = {n.node_id for n in template.nodes}
        assert "governance" not in node_ids
        assert template.approval_gates == []

    def test_envelopes_and_validation(self, registry: HarnessRegistry) -> None:
        template = registry.get_workflow("direct_answer_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)
        assert len(outputs) == 2

        # Single handoff: research -> text_buddy
        handoffs = [
            m for m in log.messages if isinstance(m, RuntimeMsg) and m.msg_type == MsgType.HANDOFF
        ]
        assert len(handoffs) == 1
        assert handoffs[0].node_id == "text_buddy"

    def test_agent_timeout_recovery(self, registry: HarnessRegistry) -> None:
        """Inject AGENT_TIMEOUT, verify -> RETRY."""
        fc = classify_failure(TimeoutError("agent timed out"), {})
        assert fc == FailureClass.AGENT_TIMEOUT

        budget = RetryBudget(workflow_id="wf-test")
        action = resolve_recovery(fc, budget, node_id="research")
        assert action.action == HookAction.RETRY
        assert action.retry_same_node is True

    def test_asyncio_timeout_classified(self) -> None:
        """asyncio.TimeoutError also classifies as AGENT_TIMEOUT."""
        fc = classify_failure(asyncio.TimeoutError(), {})
        assert fc == FailureClass.AGENT_TIMEOUT


# ============================================================================
# TestRecoveryBudgetExhaustion
# ============================================================================


class TestRecoveryBudgetExhaustion:
    """Verify retry budget exhaustion upgrades to ESCALATE."""

    def test_budget_exhaustion_upgrades_to_escalate(self) -> None:
        budget = RetryBudget(
            workflow_id="wf-budget-test",
            max_per_node_retries=2,
            max_total_retries=10,
        )
        # Exhaust the per-node budget for "text_buddy"
        budget.record_attempt("text_buddy")
        budget.record_attempt("text_buddy")
        assert not budget.can_retry("text_buddy")
        assert budget.remaining("text_buddy") == 0

        action = resolve_recovery(
            FailureClass.SCHEMA_MISMATCH,
            budget,
            node_id="text_buddy",
        )
        assert action.action == HookAction.ESCALATE
        assert action.escalate_to_hitl is True
        assert "exhausted" in action.reason.lower()

    def test_total_budget_exhaustion(self) -> None:
        budget = RetryBudget(
            workflow_id="wf-total-test",
            max_per_node_retries=5,
            max_total_retries=3,
        )
        budget.record_attempt("node_a")
        budget.record_attempt("node_b")
        budget.record_attempt("node_c")
        assert budget.is_exhausted()
        assert not budget.can_retry("node_d")

        action = resolve_recovery(
            FailureClass.AGENT_TIMEOUT,
            budget,
            node_id="node_d",
        )
        assert action.action == HookAction.ESCALATE

    def test_budget_summary(self) -> None:
        budget = RetryBudget(
            workflow_id="wf-summary",
            max_per_node_retries=3,
            max_total_retries=10,
        )
        budget.record_attempt("research")
        budget.record_attempt("research")

        summary = budget.summary()
        assert summary["workflow_id"] == "wf-summary"
        assert summary["total_attempts"] == 2
        assert summary["node_attempts"]["research"] == 2
        assert summary["exhausted"] is False
        assert summary["total_remaining"] == 8

    def test_recovery_event_creation(self) -> None:
        action = DEFAULT_RECOVERY_POLICIES[FailureClass.SCHEMA_MISMATCH]
        event = RecoveryEvent.create(
            workflow_id="wf-evt",
            node_id="text_buddy",
            agent_id="text_buddy",
            failure_class=FailureClass.SCHEMA_MISMATCH,
            recovery_action=action,
            attempt_number=1,
            budget_remaining=2,
            error_message="output mismatch",
        )
        assert event.workflow_id == "wf-evt"
        assert event.failure_class == FailureClass.SCHEMA_MISMATCH
        assert event.recovery_action.action == HookAction.RETRY
        assert event.event_id  # non-empty UUID
        assert event.timestamp  # non-empty ISO timestamp


# ============================================================================
# TestEnforcementModeToggle
# ============================================================================


@pytest.mark.skipif(not _HAS_ENFORCEMENT, reason="enforcement.py not available")
class TestEnforcementModeToggle:
    """Test advisory vs enforced contract violation modes."""

    def test_advisory_mode_logs_no_raise(self, caplog: pytest.LogCaptureFixture) -> None:
        """ADVISORY mode logs but does not raise."""
        set_enforcement_mode(EnforcementMode.ADVISORY)

        with caplog.at_level(logging.WARNING, logger="agentscope_blaiq.contracts.enforcement"):
            enforcement_check(
                ok=False,
                errors=["test error"],
                context="test_advisory",
            )
            # Should not raise -- just log.

        assert any("contract_violation" in record.message for record in caplog.records)

    def test_enforced_mode_raises(self) -> None:
        """ENFORCED mode raises ContractViolationError."""
        set_enforcement_mode(EnforcementMode.ENFORCED)

        with pytest.raises(ContractViolationError) as exc_info:
            enforcement_check(
                ok=False,
                errors=["schema mismatch", "missing field"],
                context="test_enforced",
            )

        assert len(exc_info.value.errors) == 2
        assert exc_info.value.context == "test_enforced"
        assert "schema mismatch" in str(exc_info.value)

    def test_enforced_mode_no_raise_on_ok(self) -> None:
        """ENFORCED mode does not raise when ok=True."""
        set_enforcement_mode(EnforcementMode.ENFORCED)
        # Should not raise
        enforcement_check(ok=True, errors=[], context="test_ok")

    def test_advisory_warnings_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Warnings are logged at info level in advisory mode."""
        set_enforcement_mode(EnforcementMode.ADVISORY)

        with caplog.at_level(logging.INFO, logger="agentscope_blaiq.contracts.enforcement"):
            enforcement_check(
                ok=True,
                errors=[],
                context="test_warnings",
                warnings=["non-critical issue"],
            )

        assert any("contract_warnings" in record.message for record in caplog.records)

    def teardown_method(self) -> None:
        """Reset to advisory after each test."""
        if _HAS_ENFORCEMENT:
            set_enforcement_mode(EnforcementMode.ADVISORY)


# ============================================================================
# TestMessageReplayIntegrity
# ============================================================================


class TestMessageReplayIntegrity:
    """Build a full message chain, serialize, deserialize, verify integrity."""

    def test_round_trip_serialization(self, registry: HarnessRegistry) -> None:
        """Serialize via to_replay_log, deserialize via from_replay_log, verify chain."""
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)
        original_count = len(log)

        # Serialize
        replay_data = log.to_replay_log()
        assert len(replay_data) == original_count
        assert all(isinstance(d, dict) for d in replay_data)

        # Deserialize
        restored_log = MessageLog.from_replay_log(replay_data)
        assert len(restored_log) == original_count

        # Verify each message round-trips correctly.
        for orig, restored in zip(log.messages, restored_log.messages):
            orig_dict = serialize_msg(orig)
            restored_dict = serialize_msg(restored)
            assert orig_dict == restored_dict

    def test_chain_integrity_preserved(self, registry: HarnessRegistry) -> None:
        """Verify get_chain works after round-trip."""
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)

        # Serialize and restore.
        restored_log = MessageLog.from_replay_log(log.to_replay_log())

        # Trace chain from last output.
        last_out = outputs[-1]
        original_chain = log.get_chain(last_out.msg_id)
        restored_chain = restored_log.get_chain(last_out.msg_id)

        assert len(original_chain) == len(restored_chain)
        for orig, rest in zip(original_chain, restored_chain):
            assert serialize_msg(orig) == serialize_msg(rest)

    def test_get_by_workflow_filters(self, registry: HarnessRegistry) -> None:
        """Verify get_by_workflow returns only messages for the target workflow."""
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        log, _ = _simulate_workflow(template, registry, workflow_instance_id="wf-alpha")

        # Add a message from a different workflow.
        other_msg = make_agent_input(
            workflow_id="wf-beta",
            node_id="research",
            agent_id="research",
            payload={"query": "other"},
        )
        log.append(other_msg)

        alpha_msgs = log.get_by_workflow("wf-alpha")
        beta_msgs = log.get_by_workflow("wf-beta")

        # All workflow messages should be from wf-alpha.
        assert all(
            isinstance(m, RuntimeMsg) and m.workflow_id == "wf-alpha"
            for m in alpha_msgs
        )
        assert len(beta_msgs) == 1
        assert len(alpha_msgs) > 0

    def test_get_by_node_filters(self, registry: HarnessRegistry) -> None:
        """Verify get_by_node returns only messages for the target node."""
        template = registry.get_workflow("text_artifact_v1")
        assert template is not None

        log, _ = _simulate_workflow(template, registry)

        research_msgs = log.get_by_node("research")
        assert len(research_msgs) >= 2  # at least input + output

        governance_msgs = log.get_by_node("governance")
        assert len(governance_msgs) >= 2

    def test_empty_log_round_trip(self) -> None:
        """Empty log serializes and deserializes to empty."""
        log = MessageLog()
        replay = log.to_replay_log()
        assert replay == []

        restored = MessageLog.from_replay_log(replay)
        assert len(restored) == 0

    def test_tool_messages_serialize(self) -> None:
        """ToolCallMsg and ToolResultMsg round-trip correctly."""
        from agentscope_blaiq.contracts.messages import ToolCallMsg, ToolResultMsg

        call = ToolCallMsg(
            tool_id="hivemind_recall",
            agent_id="research",
            args={"query": "test"},
            workflow_id="wf-tool",
            node_id="research",
        )
        result = ToolResultMsg(
            call_id=call.call_id,
            tool_id="hivemind_recall",
            result={"data": [1, 2, 3]},
            ok=True,
        )

        log = MessageLog()
        log.append(call)
        log.append(result)

        replay = log.to_replay_log()
        restored = MessageLog.from_replay_log(replay)
        assert len(restored) == 2

        restored_call = restored.messages[0]
        restored_result = restored.messages[1]
        assert isinstance(restored_call, ToolCallMsg)
        assert isinstance(restored_result, ToolResultMsg)
        assert restored_call.call_id == call.call_id
        assert restored_result.result == {"data": [1, 2, 3]}


# ============================================================================
# TestClassifyFailure (additional coverage)
# ============================================================================


class TestClassifyFailure:
    """Verify all failure classification branches."""

    def test_missing_requirements(self) -> None:
        fc = classify_failure(None, {"missing_keys": ["brand_voice", "tone"]})
        assert fc == FailureClass.MISSING_REQUIREMENTS

    def test_agent_error(self) -> None:
        fc = classify_failure(RuntimeError("crash"), {"agent_id": "vangogh"})
        assert fc == FailureClass.AGENT_ERROR

    def test_unknown_fallback(self) -> None:
        fc = classify_failure(RuntimeError("something weird"), {})
        assert fc == FailureClass.UNKNOWN

    def test_governance_rejected(self) -> None:
        fc = classify_failure(None, {"governance_rejected": True})
        assert fc == FailureClass.GOVERNANCE_FAILURE

    def test_weak_evidence_from_context(self) -> None:
        fc = classify_failure(None, {"weak_evidence": True})
        assert fc == FailureClass.WEAK_EVIDENCE

    def test_tool_failure_from_context(self) -> None:
        fc = classify_failure(RuntimeError("error"), {"tool_id": "hivemind_recall"})
        assert fc == FailureClass.TOOL_FAILURE


# ============================================================================
# TestWorkflowTemplateStructure
# ============================================================================


class TestWorkflowTemplateStructure:
    """Validate structural invariants across all workflow templates."""

    @pytest.mark.parametrize(
        "workflow_id",
        [
            "text_artifact_v1",
            "visual_artifact_v1",
            "direct_answer_v1",
            "research_v1",
            "finance_v1",
        ],
    )
    def test_all_workflows_load(
        self, registry: HarnessRegistry, workflow_id: str,
    ) -> None:
        template = registry.get_workflow(workflow_id)
        assert template is not None
        assert template.workflow_id == workflow_id
        assert len(template.nodes) > 0

    @pytest.mark.parametrize(
        "workflow_id",
        [
            "text_artifact_v1",
            "visual_artifact_v1",
            "direct_answer_v1",
            "research_v1",
            "finance_v1",
        ],
    )
    def test_all_agents_registered(
        self, registry: HarnessRegistry, workflow_id: str,
    ) -> None:
        """Every agent_id in a workflow's nodes must exist in the registry."""
        template = registry.get_workflow(workflow_id)
        assert template is not None

        for node in template.nodes:
            harness = registry.get_agent(node.agent_id)
            assert harness is not None, (
                f"Agent '{node.agent_id}' in workflow '{workflow_id}' "
                f"not found in registry"
            )

    @pytest.mark.parametrize(
        "workflow_id",
        [
            "text_artifact_v1",
            "visual_artifact_v1",
            "direct_answer_v1",
            "research_v1",
            "finance_v1",
        ],
    )
    def test_topological_walk_covers_all_nodes(
        self, registry: HarnessRegistry, workflow_id: str,
    ) -> None:
        """Topological walk should visit every node exactly once."""
        template = registry.get_workflow(workflow_id)
        assert template is not None

        ordered = _walk_workflow_nodes(template)
        assert len(ordered) == len(template.nodes)
        assert {n.node_id for n in ordered} == {n.node_id for n in template.nodes}

    @pytest.mark.parametrize(
        "workflow_id",
        [
            "text_artifact_v1",
            "visual_artifact_v1",
            "direct_answer_v1",
            "research_v1",
            "finance_v1",
        ],
    )
    def test_simulate_workflow_no_validation_errors(
        self, registry: HarnessRegistry, workflow_id: str,
    ) -> None:
        """Full simulation should produce no schema validation errors."""
        template = registry.get_workflow(workflow_id)
        assert template is not None

        log, outputs = _simulate_workflow(template, registry)
        assert len(outputs) == len(template.nodes)
