"""
Tests for Phase 3: Orchestration hooks and dispatch enforcement.

Validates:
  - Blocked dispatch scenarios
  - Invalid handoff detection
  - Tool permission failures
  - Workflow mismatch enforcement
  - Approval gate behavior
  - Hook evaluation and aggregation
  - Engine dispatch guard integration
"""

import pytest

from agentscope_blaiq.contracts.dispatch import validate_dispatch, validate_handoff, validate_tool_call
from agentscope_blaiq.contracts.hooks import (
    HookAction,
    HookContext,
    HookDecision,
    HookRegistry,
    HookResult,
    HookType,
    evaluate_governance_gate,
    evaluate_missing_input,
    evaluate_post_node,
    evaluate_pre_node,
    evaluate_retry_replan,
)
from agentscope_blaiq.contracts.registry import HarnessRegistry
from agentscope_blaiq.contracts.workflows import WORKFLOW_TEMPLATES


@pytest.fixture
def registry() -> HarnessRegistry:
    """Full registry with agents, tools, and workflows."""
    reg = HarnessRegistry()
    reg.load_builtin_agents()
    reg.load_builtin_tools()
    reg.load_builtin_workflows()
    return reg


# ============================================================================
# Blocked Dispatch
# ============================================================================

class TestBlockedDispatch:
    """Dispatch is blocked when harness contracts are violated."""

    def test_unknown_agent_blocked(self, registry: HarnessRegistry):
        """Unknown agent yields BLOCK hook decision."""
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="unknown",
            agent_id="nonexistent_agent",
            input_data={},
        )
        decision = evaluate_pre_node(ctx, registry)
        assert decision.action == HookAction.BLOCK
        assert any("nonexistent_agent" in e for e in decision.errors)

    def test_missing_required_input_blocked(self, registry: HarnessRegistry):
        """Missing required input field blocks dispatch."""
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="strategist",
            agent_id="strategist",
            input_data={},  # strategist requires user_request
        )
        decision = evaluate_pre_node(ctx, registry)
        assert decision.action == HookAction.BLOCK
        assert any("user_request" in e for e in decision.errors)

    def test_valid_dispatch_proceeds(self, registry: HarnessRegistry):
        """Valid dispatch input returns PROCEED."""
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="research",
            agent_id="research",
            input_data={"query": "market analysis"},
        )
        decision = evaluate_pre_node(ctx, registry)
        assert decision.action in (HookAction.PROCEED, HookAction.WARN)

    def test_workflow_mismatch_blocked(self, registry: HarnessRegistry):
        """Agent dispatched in wrong workflow is blocked."""
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="text_buddy",
            agent_id="text_buddy",
            input_data={"evidence_pack": {}, "artifact_family": "email"},
            workflow_id="visual_artifact_v1",  # text_buddy not in visual workflow
        )
        decision = evaluate_pre_node(ctx, registry)
        assert decision.action == HookAction.BLOCK
        assert any("not allowed in workflow" in e for e in decision.errors)

    def test_valid_workflow_agent_proceeds(self, registry: HarnessRegistry):
        """Agent dispatched in correct workflow proceeds."""
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="strategist",
            agent_id="strategist",
            input_data={"user_request": "Build a pitch deck"},
            workflow_id="visual_artifact_v1",
        )
        decision = evaluate_pre_node(ctx, registry)
        assert decision.action in (HookAction.PROCEED, HookAction.WARN)


# ============================================================================
# Invalid Handoff Detection
# ============================================================================

class TestInvalidHandoff:
    """Handoffs are blocked when output schema doesn't match contracts."""

    def test_missing_evidence_pack_blocked(self, registry: HarnessRegistry):
        """Handoff from research missing evidence_pack is blocked."""
        result = validate_handoff(
            from_agent_id="research",
            to_agent_id="content_director",
            output_data={},  # Missing evidence_pack
            registry=registry,
        )
        assert not result.ok
        assert any("evidence_pack" in e.lower() or "output" in e.lower() for e in result.errors)

    def test_valid_handoff_passes(self, registry: HarnessRegistry):
        """Research -> content_director with valid evidence_pack passes."""
        result = validate_handoff(
            from_agent_id="research",
            to_agent_id="content_director",
            output_data={"evidence_pack": {"findings": []}, "artifact_family": "pitch_deck"},
            registry=registry,
        )
        assert result.ok

    def test_strategist_to_research_handoff_with_alias_workflow_passes(self, registry: HarnessRegistry):
        """Canonical strategist -> research handoff passes for research variants and alias workflow IDs."""
        result = validate_handoff(
            from_agent_id="strategist",
            to_agent_id="deep_research",
            output_data={
                "workflow_id": "visual_artifact_v1",
                "query": "market analysis",
                "source_scope": "web_and_docs",
                "workflow_plan": {},
                "task_graph": {},
                "missing_requirements": [],
            },
            registry=registry,
            workflow_id="visual_artifact",
        )
        assert result.ok

    def test_unknown_source_agent_blocked(self, registry: HarnessRegistry):
        """Handoff from unknown agent is blocked."""
        result = validate_handoff(
            from_agent_id="ghost_agent",
            to_agent_id="research",
            output_data={},
            registry=registry,
        )
        assert not result.ok

    def test_unknown_target_agent_blocked(self, registry: HarnessRegistry):
        """Handoff to unknown agent is blocked."""
        result = validate_handoff(
            from_agent_id="research",
            to_agent_id="ghost_agent",
            output_data={},
            registry=registry,
        )
        assert not result.ok

    def test_workflow_mismatch_in_handoff(self, registry: HarnessRegistry):
        """Handoff between agents in different workflows is blocked."""
        result = validate_handoff(
            from_agent_id="text_buddy",
            to_agent_id="vangogh",
            output_data={"artifact": {}},
            registry=registry,
            workflow_id="text_artifact_v1",
        )
        assert not result.ok
        assert any("not allowed in workflow" in e for e in result.errors)


# ============================================================================
# Tool Permission Failures
# ============================================================================

class TestToolPermissionFailures:
    """Tool calls are blocked when agent-tool permissions fail."""

    def test_governance_cannot_use_hivemind_recall(self, registry: HarnessRegistry):
        """Governance agent cannot use hivemind_recall (not in allowed_tools)."""
        result = validate_tool_call(
            agent_id="governance",
            tool_id="hivemind_recall",
            tool_input={"query": "test"},
            registry=registry,
        )
        assert not result.ok
        assert any("not allowed to use" in e for e in result.errors)

    def test_strategist_cannot_use_web_search(self, registry: HarnessRegistry):
        """Strategist cannot use hivemind_web_search directly."""
        result = validate_tool_call(
            agent_id="strategist",
            tool_id="hivemind_web_search",
            tool_input={},
            registry=registry,
        )
        assert not result.ok

    def test_research_can_use_hivemind_recall(self, registry: HarnessRegistry):
        """Research agent can use hivemind_recall."""
        result = validate_tool_call(
            agent_id="research",
            tool_id="hivemind_recall",
            tool_input={"query": "test"},
            registry=registry,
        )
        assert result.ok

    def test_unknown_tool_blocked(self, registry: HarnessRegistry):
        """Call to unknown tool is blocked."""
        result = validate_tool_call(
            agent_id="research",
            tool_id="nonexistent_tool",
            tool_input={},
            registry=registry,
        )
        assert not result.ok
        assert any("No harness" in e for e in result.errors)

    def test_vangogh_can_use_artifact_contract(self, registry: HarnessRegistry):
        """Vangogh can use artifact_contract tool."""
        result = validate_tool_call(
            agent_id="vangogh",
            tool_id="artifact_contract",
            tool_input={},
            registry=registry,
        )
        assert result.ok

    def test_text_buddy_cannot_use_artifact_contract(self, registry: HarnessRegistry):
        """Text buddy cannot use artifact_contract (visual-only tool)."""
        result = validate_tool_call(
            agent_id="text_buddy",
            tool_id="artifact_contract",
            tool_input={},
            registry=registry,
        )
        assert not result.ok

    def test_tool_workflow_scope_violation(self, registry: HarnessRegistry):
        """Text_buddy using apply_brand_voice in visual workflow fails."""
        result = validate_tool_call(
            agent_id="text_buddy",
            tool_id="apply_brand_voice",
            tool_input={},
            registry=registry,
            workflow_id="visual_artifact_v1",
        )
        assert not result.ok
        assert any("not allowed in workflow" in e for e in result.errors)


# ============================================================================
# Approval Gate Behavior
# ============================================================================

class TestApprovalGateBehavior:
    """Governance gate hooks escalate correctly."""

    def test_governance_node_triggers_escalate(self):
        """Governance node with approval_gates triggers ESCALATE."""
        ctx = HookContext(
            hook_type=HookType.GOVERNANCE_GATE,
            node_id="governance",
            agent_id="governance",
            input_data={"artifact": {}},
            workflow_id="visual_artifact_v1",
            metadata={"approval_gates": ["governance"]},
        )
        decision = evaluate_governance_gate(ctx)
        assert decision.action == HookAction.ESCALATE
        assert "governance" in decision.reason

    def test_non_governance_node_proceeds(self):
        """Non-governance node without approval_gates proceeds."""
        ctx = HookContext(
            hook_type=HookType.GOVERNANCE_GATE,
            node_id="research",
            agent_id="research",
            input_data={"query": "test"},
            metadata={"approval_gates": ["governance"]},
        )
        decision = evaluate_governance_gate(ctx)
        assert decision.action == HookAction.PROCEED

    def test_empty_approval_gates_proceeds(self):
        """No approval_gates in metadata always proceeds."""
        ctx = HookContext(
            hook_type=HookType.GOVERNANCE_GATE,
            node_id="governance",
            agent_id="governance",
            input_data={"artifact": {}},
            metadata={},  # No approval_gates key
        )
        decision = evaluate_governance_gate(ctx)
        assert decision.action == HookAction.PROCEED

    def test_direct_answer_workflow_no_governance(self, registry: HarnessRegistry):
        """direct_answer_v1 has no approval gates."""
        template = WORKFLOW_TEMPLATES["direct_answer_v1"]
        assert len(template.approval_gates) == 0

    def test_visual_artifact_workflow_has_governance(self, registry: HarnessRegistry):
        """visual_artifact_v1 has governance approval gate."""
        template = WORKFLOW_TEMPLATES["visual_artifact_v1"]
        assert "governance" in template.approval_gates


# ============================================================================
# Hook Post-Node Behavior
# ============================================================================

class TestPostNodeHooks:
    """POST_NODE hooks validate agent output."""

    def test_none_output_triggers_retry(self, registry: HarnessRegistry):
        """Agent returning None output triggers RETRY."""
        ctx = HookContext(
            hook_type=HookType.POST_NODE,
            node_id="research",
            agent_id="research",
            input_data={"query": "test"},
            output_data=None,  # No output
        )
        decision = evaluate_post_node(ctx, registry)
        assert decision.action == HookAction.RETRY

    def test_valid_output_proceeds(self, registry: HarnessRegistry):
        """Agent returning output proceeds."""
        ctx = HookContext(
            hook_type=HookType.POST_NODE,
            node_id="research",
            agent_id="research",
            input_data={"query": "test"},
            output_data={"findings": [], "citations": []},
        )
        decision = evaluate_post_node(ctx, registry)
        assert decision.action == HookAction.PROCEED


# ============================================================================
# Missing Input Detection
# ============================================================================

class TestMissingInputDetection:
    """MISSING_INPUT hooks escalate on absent required keys."""

    def test_missing_required_key_escalates(self):
        """Missing required_keys trigger ESCALATE."""
        ctx = HookContext(
            hook_type=HookType.MISSING_INPUT,
            node_id="research",
            agent_id="research",
            input_data={},  # Missing query
            metadata={"required_keys": ["query", "context"]},
        )
        decision = evaluate_missing_input(ctx)
        assert decision.action == HookAction.ESCALATE
        assert any("query" in e for e in decision.errors)
        assert any("context" in e for e in decision.errors)

    def test_all_required_keys_present_proceeds(self):
        """All required keys present proceed."""
        ctx = HookContext(
            hook_type=HookType.MISSING_INPUT,
            node_id="research",
            agent_id="research",
            input_data={"query": "test", "context": "blaiq"},
            metadata={"required_keys": ["query", "context"]},
        )
        decision = evaluate_missing_input(ctx)
        assert decision.action == HookAction.PROCEED

    def test_no_required_keys_metadata_proceeds(self):
        """No required_keys in metadata always proceeds."""
        ctx = HookContext(
            hook_type=HookType.MISSING_INPUT,
            node_id="research",
            agent_id="research",
            input_data={},
            metadata={},  # No required_keys
        )
        decision = evaluate_missing_input(ctx)
        assert decision.action == HookAction.PROCEED


# ============================================================================
# Retry/Replan Policy
# ============================================================================

class TestRetryReplanPolicy:
    """RETRY_REPLAN hooks enforce retry vs replan policy."""

    def test_first_attempt_proceeds(self):
        """Attempt 0 proceeds without retry."""
        ctx = HookContext(
            hook_type=HookType.RETRY_REPLAN,
            node_id="research",
            agent_id="research",
            input_data={},
            attempt_number=0,
        )
        decision = evaluate_retry_replan(ctx)
        assert decision.action == HookAction.PROCEED

    def test_second_attempt_retries(self):
        """Attempt 1 triggers RETRY."""
        ctx = HookContext(
            hook_type=HookType.RETRY_REPLAN,
            node_id="research",
            agent_id="research",
            input_data={},
            attempt_number=1,
        )
        decision = evaluate_retry_replan(ctx)
        assert decision.action == HookAction.RETRY

    def test_third_attempt_retries(self):
        """Attempt 2 still retries."""
        ctx = HookContext(
            hook_type=HookType.RETRY_REPLAN,
            node_id="research",
            agent_id="research",
            input_data={},
            attempt_number=2,
        )
        decision = evaluate_retry_replan(ctx)
        assert decision.action == HookAction.RETRY

    def test_fourth_attempt_replans(self):
        """Attempt 3+ triggers REPLAN."""
        ctx = HookContext(
            hook_type=HookType.RETRY_REPLAN,
            node_id="research",
            agent_id="research",
            input_data={},
            attempt_number=3,
        )
        decision = evaluate_retry_replan(ctx)
        assert decision.action == HookAction.REPLAN


# ============================================================================
# HookRegistry Aggregation
# ============================================================================

class TestHookRegistryAggregation:
    """HookRegistry aggregates multiple evaluators correctly."""

    def test_empty_registry_proceeds(self):
        """Empty registry returns PROCEED."""
        reg = HookRegistry()
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="research",
            agent_id="research",
            input_data={},
        )
        result = reg.evaluate(ctx)
        assert result.final_action == HookAction.PROCEED
        assert result.decisions == []

    def test_single_block_blocks(self):
        """Single BLOCK decision makes final_action BLOCK."""
        reg = HookRegistry()
        reg.register(
            HookType.PRE_NODE,
            lambda ctx: HookDecision(action=HookAction.BLOCK, reason="test block", errors=["bad"]),
        )
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="research",
            agent_id="research",
            input_data={},
        )
        result = reg.evaluate(ctx)
        assert result.final_action == HookAction.BLOCK
        assert "bad" in result.all_errors

    def test_block_overrides_proceed(self):
        """BLOCK overrides PROCEED in aggregation."""
        reg = HookRegistry()
        reg.register(HookType.PRE_NODE, lambda ctx: HookDecision(action=HookAction.PROCEED, reason="ok"))
        reg.register(HookType.PRE_NODE, lambda ctx: HookDecision(action=HookAction.BLOCK, reason="blocked"))
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="research",
            agent_id="research",
            input_data={},
        )
        result = reg.evaluate(ctx)
        assert result.final_action == HookAction.BLOCK

    def test_severity_order_replan_over_retry(self):
        """REPLAN overrides RETRY."""
        reg = HookRegistry()
        reg.register(HookType.RETRY_REPLAN, lambda ctx: HookDecision(action=HookAction.RETRY, reason="retry"))
        reg.register(HookType.RETRY_REPLAN, lambda ctx: HookDecision(action=HookAction.REPLAN, reason="replan"))
        ctx = HookContext(
            hook_type=HookType.RETRY_REPLAN,
            node_id="research",
            agent_id="research",
            input_data={},
        )
        result = reg.evaluate(ctx)
        assert result.final_action == HookAction.REPLAN

    def test_warnings_collected_across_evaluators(self):
        """Warnings from multiple evaluators are all collected."""
        reg = HookRegistry()
        reg.register(HookType.PRE_NODE, lambda ctx: HookDecision(action=HookAction.WARN, reason="w1", warnings=["warn1"]))
        reg.register(HookType.PRE_NODE, lambda ctx: HookDecision(action=HookAction.WARN, reason="w2", warnings=["warn2"]))
        ctx = HookContext(
            hook_type=HookType.PRE_NODE,
            node_id="research",
            agent_id="research",
            input_data={},
        )
        result = reg.evaluate(ctx)
        assert "warn1" in result.all_warnings
        assert "warn2" in result.all_warnings

    def test_hook_decision_bool(self):
        """HookDecision __bool__ returns False only for BLOCK."""
        assert bool(HookDecision(action=HookAction.PROCEED, reason="ok"))
        assert bool(HookDecision(action=HookAction.WARN, reason="ok"))
        assert bool(HookDecision(action=HookAction.RETRY, reason="ok"))
        assert bool(HookDecision(action=HookAction.REPLAN, reason="ok"))
        assert bool(HookDecision(action=HookAction.ESCALATE, reason="ok"))
        assert not bool(HookDecision(action=HookAction.BLOCK, reason="blocked"))


# ============================================================================
# Engine Dispatch Guard (unit-level)
# ============================================================================

# NOTE: engine.py requires full production stack (agentscope, sqlalchemy, redis).
# These tests use __new__ to bypass __init__ and test only the contract methods.

@pytest.fixture
def engine_instance():
    """Engine instance bypassing full init (no DB/redis required)."""
    try:
        from agentscope_blaiq.workflows.engine import WorkflowEngine
        from agentscope_blaiq.contracts.registry import HarnessRegistry
    except ImportError:
        pytest.skip("agentscope production stack not available")

    class _FakeAgentRegistry:
        harness_registry = HarnessRegistry()

    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine._harness_registry = None
    engine.registry = _FakeAgentRegistry()
    return engine


class TestEngineDispatchGuard:
    """WorkflowEngine._pre_dispatch_check logs violations without raising."""

    def test_dispatch_guard_valid_agent(self, engine_instance):
        """Valid dispatch does not raise."""
        # Should not raise — advisory only
        engine_instance._pre_dispatch_check(
            "research",
            {"query": "test"},
            workflow_id="research_v1",
        )

    def test_dispatch_guard_invalid_agent(self, engine_instance):
        """Unknown agent does not raise — advisory mode never blocks execution."""
        # validate_dispatch returns early for unknown agents without logging;
        # _pre_dispatch_check must not raise in advisory mode.
        engine_instance._pre_dispatch_check("nonexistent_agent", {})

    def test_harness_registry_lazy_loaded(self, engine_instance):
        """_get_harness_registry lazy-loads on first access."""
        reg1 = engine_instance._get_harness_registry()
        reg2 = engine_instance._get_harness_registry()
        assert reg1 is reg2  # Same instance


# ============================================================================
# StrategicDraft Route Metadata
# ============================================================================

# Strategic module requires agentscope runtime; skip when not available.
try:
    from agentscope_blaiq.agents.strategic import StrategicDraft as _StrategicDraft
    from agentscope_blaiq.contracts.workflow import WorkflowMode as _WorkflowMode
    _STRATEGIC_AVAILABLE = True
except ImportError:
    _STRATEGIC_AVAILABLE = False


@pytest.mark.skipif(not _STRATEGIC_AVAILABLE, reason="agentscope runtime not installed")
class TestStrategicDraftRouteMetadata:
    """StrategicDraft emits Phase 3 route metadata fields."""

    def test_strategic_draft_has_workflow_template_id(self):
        """StrategicDraft has workflow_template_id field."""
        from agentscope_blaiq.agents.strategic import StrategicDraft
        from agentscope_blaiq.contracts.workflow import WorkflowMode

        draft = StrategicDraft(
            workflow_mode=WorkflowMode.sequential,
            summary="test",
            task_count=2,
            workflow_template_id="visual_artifact_v1",
        )
        assert draft.workflow_template_id == "visual_artifact_v1"

    def test_strategic_draft_has_node_assignments(self):
        """StrategicDraft has node_assignments field."""
        from agentscope_blaiq.agents.strategic import StrategicDraft
        from agentscope_blaiq.contracts.workflow import WorkflowMode

        draft = StrategicDraft(
            workflow_mode=WorkflowMode.sequential,
            summary="test",
            task_count=3,
            node_assignments={"strategist": "strategist", "research": "deep_research"},
        )
        assert draft.node_assignments["research"] == "deep_research"

    def test_strategic_draft_has_required_tools_per_node(self):
        """StrategicDraft has required_tools_per_node field."""
        from agentscope_blaiq.agents.strategic import StrategicDraft
        from agentscope_blaiq.contracts.workflow import WorkflowMode

        draft = StrategicDraft(
            workflow_mode=WorkflowMode.sequential,
            summary="test",
            task_count=2,
            required_tools_per_node={"research": ["hivemind_recall", "hivemind_web_search"]},
        )
        assert "hivemind_recall" in draft.required_tools_per_node["research"]

    def test_strategic_draft_has_fallback_path(self):
        """StrategicDraft has fallback_path field."""
        from agentscope_blaiq.agents.strategic import StrategicDraft
        from agentscope_blaiq.contracts.workflow import WorkflowMode

        draft = StrategicDraft(
            workflow_mode=WorkflowMode.sequential,
            summary="test",
            task_count=2,
            fallback_path="hitl",
        )
        assert draft.fallback_path == "hitl"

    def test_strategic_draft_has_missing_requirements(self):
        """StrategicDraft has missing_requirements field."""
        from agentscope_blaiq.agents.strategic import StrategicDraft
        from agentscope_blaiq.contracts.workflow import WorkflowMode

        draft = StrategicDraft(
            workflow_mode=WorkflowMode.sequential,
            summary="test",
            task_count=2,
            missing_requirements=["target_audience", "brand_context"],
        )
        assert "target_audience" in draft.missing_requirements

    def test_strategic_draft_backward_compatible(self):
        """StrategicDraft without Phase 3 fields still works."""
        from agentscope_blaiq.agents.strategic import StrategicDraft
        from agentscope_blaiq.contracts.workflow import WorkflowMode

        draft = StrategicDraft(
            workflow_mode=WorkflowMode.sequential,
            summary="legacy plan",
            task_count=1,
        )
        assert draft.workflow_template_id is None
        assert draft.node_assignments == {}
        assert draft.required_tools_per_node == {}
        assert draft.fallback_path is None
        assert draft.missing_requirements == []
