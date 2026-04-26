"""
Regression gate tests — lock exact failures from production logs.

Each test class corresponds to a failure class observed in production.
Tests are pure contract-layer checks (no agentscope runtime dependency).
"""

from __future__ import annotations

import pytest

from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
from agentscope_blaiq.contracts.dispatch import validate_dispatch, validate_handoff
from agentscope_blaiq.contracts.harness import (
    AGENT_HARNESSES,
    ALL_WORKFLOWS,
    DEEP_RESEARCH_HARNESS,
    RESEARCH_HARNESS,
    STRATEGIST_HARNESS,
    canonicalize_workflow_template_id,
)
from agentscope_blaiq.contracts.registry import HarnessRegistry, get_registry, reset_registry
from agentscope_blaiq.contracts.user_agent_registry import UserAgentRegistry
from agentscope_blaiq.contracts.workflow import WorkflowMode


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_registry()
    yield  # type: ignore[misc]


@pytest.fixture
def registry() -> HarnessRegistry:
    hr = get_registry()
    hr.load_builtin_workflows()
    return hr


# ============================================================================
# Helpers
# ============================================================================

CANONICAL_IDS = [
    "visual_artifact_v1",
    "text_artifact_v1",
    "direct_answer_v1",
    "research_v1",
    "finance_v1",
]


def _make_custom_spec(**overrides: object) -> CustomAgentSpec:
    defaults: dict[str, object] = dict(
        agent_id="test_custom_agent",
        display_name="Test Custom Agent",
        prompt="You are a helpful assistant that summarizes documents in detail.",
        role="text_buddy",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )
    defaults.update(overrides)
    return CustomAgentSpec(**defaults)


# ============================================================================
# Class 1: Workflow ID mismatch
#
# Production bug: engine passed workflow_id="sequential" (a WorkflowMode enum
# value) instead of a canonical template ID like "text_artifact_v1".
# Every dispatch check failed with "agent not allowed in workflow 'sequential'".
# ============================================================================


class TestWorkflowIdMismatch:
    """Lock regression: raw WorkflowMode values must never be valid workflow IDs."""

    def test_sequential_is_not_a_valid_workflow_id(self) -> None:
        """'sequential' is a WorkflowMode, not a workflow template ID.
        No agent should list it in allowed_workflows."""
        for agent_id, harness in AGENT_HARNESSES.items():
            assert "sequential" not in harness.allowed_workflows, (
                f"Agent '{agent_id}' has 'sequential' in allowed_workflows — "
                "this is a WorkflowMode, not a canonical workflow template ID"
            )

    def test_no_workflow_mode_values_in_allowed_workflows(self) -> None:
        """None of the WorkflowMode enum values should appear as workflow IDs."""
        mode_values = {m.value for m in WorkflowMode}
        for agent_id, harness in AGENT_HARNESSES.items():
            overlap = mode_values & set(harness.allowed_workflows)
            assert not overlap, (
                f"Agent '{agent_id}' has WorkflowMode values {overlap} in "
                "allowed_workflows — these are execution modes, not template IDs"
            )

    def test_canonical_workflow_ids_exist_in_registry(self, registry: HarnessRegistry) -> None:
        """All 5 canonical IDs must be registered as workflow templates."""
        registered = set(registry.list_workflow_ids())
        for wf_id in CANONICAL_IDS:
            assert wf_id in registered, (
                f"Canonical workflow '{wf_id}' not found in registry. "
                f"Registered: {sorted(registered)}"
            )

    def test_canonicalize_maps_aliases(self) -> None:
        """canonicalize_workflow_template_id must resolve common aliases."""
        assert canonicalize_workflow_template_id("text_artifact") == "text_artifact_v1"
        assert canonicalize_workflow_template_id("visual_artifact") == "visual_artifact_v1"
        assert canonicalize_workflow_template_id("research") == "research_v1"
        assert canonicalize_workflow_template_id("finance") == "finance_v1"
        assert canonicalize_workflow_template_id("direct_answer") == "direct_answer_v1"

    def test_canonicalize_returns_none_for_empty(self) -> None:
        """Edge cases: None and empty strings should return None."""
        assert canonicalize_workflow_template_id(None) is None
        assert canonicalize_workflow_template_id("") is None
        assert canonicalize_workflow_template_id("   ") is None

    def test_canonicalize_passes_through_canonical_ids(self) -> None:
        """Already-canonical IDs should pass through unchanged."""
        for wf_id in CANONICAL_IDS:
            assert canonicalize_workflow_template_id(wf_id) == wf_id

    def test_dispatch_fails_for_raw_mode_value(self, registry: HarnessRegistry) -> None:
        """validate_dispatch with workflow_id='sequential' must fail.
        This was the exact production failure."""
        result = validate_dispatch(
            "text_buddy",
            {"artifact_family": "email", "user_query": "Write an email", "evidence_pack": {"sources": []}},
            registry,
            workflow_id="sequential",
        )
        assert not result.ok, (
            "Dispatch should FAIL when workflow_id is a raw WorkflowMode value"
        )
        assert any("sequential" in err for err in result.errors)

    def test_dispatch_passes_for_canonical_id(self, registry: HarnessRegistry) -> None:
        """validate_dispatch with workflow_id='text_artifact_v1' for text_buddy must pass."""
        result = validate_dispatch(
            "text_buddy",
            {"artifact_family": "email", "user_query": "Write an email", "evidence_pack": {"sources": []}},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert result.ok, (
            f"Dispatch should PASS for canonical workflow ID. Errors: {result.errors}"
        )


# ============================================================================
# Class 2: Missing query key in handoff
#
# Production bug: engine passed `user_query` instead of `query` in dispatch
# payloads to the research agent, but the research harness requires `query`.
# ============================================================================


class TestMissingQueryKey:
    """Lock regression: research agent requires 'query', not 'user_query'."""

    def test_research_harness_requires_query_key(self) -> None:
        """Research agent input_schema must have 'query' as required."""
        schema = RESEARCH_HARNESS.input_schema
        assert "required" in schema, "Research input_schema must have 'required' field"
        assert "query" in schema["required"], (
            f"'query' must be required in research input_schema. "
            f"Got required: {schema.get('required')}"
        )

    def test_dispatch_with_query_key_passes(self, registry: HarnessRegistry) -> None:
        """validate_dispatch for research agent with {'query': 'test'} should pass."""
        result = validate_dispatch(
            "research",
            {"query": "What is the market size?"},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert result.ok, (
            f"Dispatch with 'query' key should pass. Errors: {result.errors}"
        )

    def test_dispatch_with_user_query_key_fails(self, registry: HarnessRegistry) -> None:
        """validate_dispatch for research with {'user_query': 'test'} (missing 'query') must fail."""
        result = validate_dispatch(
            "research",
            {"user_query": "What is the market size?"},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert not result.ok, (
            "Dispatch with 'user_query' instead of 'query' should FAIL — "
            "'query' is a required field in the research input_schema"
        )

    def test_strategist_output_requires_query(self) -> None:
        """Strategist output_schema must have 'query' as required so handoffs carry it."""
        schema = STRATEGIST_HARNESS.output_schema
        assert "required" in schema, "Strategist output_schema must have 'required' field"
        assert "query" in schema["required"], (
            f"'query' must be required in strategist output_schema. "
            f"Got required: {schema.get('required')}"
        )

    def test_handoff_strategist_to_research_requires_query(self, registry: HarnessRegistry) -> None:
        """Handoff from strategist to research must fail when 'query' is missing."""
        # Strategist output without 'query' — should produce warnings on the target side
        result = validate_handoff(
            "strategist",
            "research",
            {"workflow_id": "text_artifact_v1", "workflow_plan": {}},
            registry,
            workflow_id="text_artifact_v1",
        )
        # The handoff should produce errors or warnings about missing 'query'
        has_query_issue = (
            any("query" in w.lower() for w in result.warnings)
            or any("query" in e.lower() for e in result.errors)
        )
        assert has_query_issue, (
            "Handoff from strategist to research without 'query' should flag an issue. "
            f"Errors: {result.errors}, Warnings: {result.warnings}"
        )


# ============================================================================
# Class 3: quick_recall parameter safety
#
# Production bug: ResearchAgent.gather() does not accept quick_recall — only
# DeepResearchAgent does. Engine must not pass it blindly.
# ============================================================================


class TestQuickRecallSafety:
    """Lock regression: research harness contract must not include quick_recall."""

    def test_research_harness_input_schema_no_quick_recall(self) -> None:
        """Research agent input_schema must not list quick_recall as a property.
        It is not part of the harness contract — only DeepResearchAgent uses it."""
        properties = RESEARCH_HARNESS.input_schema.get("properties", {})
        assert "quick_recall" not in properties, (
            "Research harness input_schema should NOT include 'quick_recall'. "
            "Only DeepResearchAgent supports this parameter."
        )

    def test_deep_research_harness_exists(self) -> None:
        """Deep research agent must exist in the harness registry."""
        assert "deep_research" in AGENT_HARNESSES, (
            "deep_research agent not found in AGENT_HARNESSES"
        )
        assert DEEP_RESEARCH_HARNESS.agent_id == "deep_research"

    def test_deep_research_requires_query_not_quick_recall(self) -> None:
        """Deep research input_schema must require 'query', not quick_recall."""
        schema = DEEP_RESEARCH_HARNESS.input_schema
        required = schema.get("required", [])
        assert "query" in required, (
            f"Deep research must require 'query'. Got required: {required}"
        )
        # quick_recall is a runtime parameter, not a harness-contract field
        assert "quick_recall" not in required, (
            "quick_recall must not be a *required* input for deep_research"
        )


# ============================================================================
# Class 4: Custom agent routing validation
#
# Production bug: custom agents were blocked by validate_workflow_for_agent
# because it checks agent_id membership in template node lists. Custom agents
# substitute for built-in agents at specific nodes and need separate routing.
# ============================================================================


class TestCustomAgentRouting:
    """Lock regression: custom agents must route via UserAgentRegistry, not node-list checks."""

    def test_custom_agent_can_route_when_workflow_allowed(self, registry: HarnessRegistry) -> None:
        """Custom agent with allowed_workflows=['text_artifact_v1'] should pass can_route_to."""
        user_reg = UserAgentRegistry(registry)
        spec = _make_custom_spec(allowed_workflows=["text_artifact_v1"])
        reg_result = user_reg.register(spec)
        assert reg_result.harness_valid, (
            f"Registration should succeed. Errors: {reg_result.validation_errors}"
        )

        ok, errors = user_reg.can_route_to("test_custom_agent", "text_artifact_v1")
        assert ok, (
            f"Custom agent should be routable to text_artifact_v1. Errors: {errors}"
        )

    def test_custom_agent_blocked_when_workflow_not_allowed(self, registry: HarnessRegistry) -> None:
        """Custom agent with allowed_workflows=['finance_v1'] must be blocked from text_artifact_v1."""
        user_reg = UserAgentRegistry(registry)
        spec = _make_custom_spec(allowed_workflows=["finance_v1"])
        reg_result = user_reg.register(spec)
        assert reg_result.harness_valid, (
            f"Registration should succeed. Errors: {reg_result.validation_errors}"
        )

        ok, errors = user_reg.can_route_to("test_custom_agent", "text_artifact_v1")
        assert not ok, (
            "Custom agent with allowed_workflows=['finance_v1'] should NOT route to text_artifact_v1"
        )
        assert any("text_artifact_v1" in err for err in errors)

    def test_custom_agent_with_empty_workflows_routes_anywhere(self, registry: HarnessRegistry) -> None:
        """Custom agent with allowed_workflows=[] should accept any workflow."""
        user_reg = UserAgentRegistry(registry)
        spec = _make_custom_spec(allowed_workflows=[])
        reg_result = user_reg.register(spec)
        assert reg_result.harness_valid, (
            f"Registration should succeed. Errors: {reg_result.validation_errors}"
        )

        for wf_id in CANONICAL_IDS:
            ok, errors = user_reg.can_route_to("test_custom_agent", wf_id)
            assert ok, (
                f"Custom agent with empty allowed_workflows should route to '{wf_id}'. "
                f"Errors: {errors}"
            )

    def test_validate_draft_routing_passes_for_valid_custom_agent(self, registry: HarnessRegistry) -> None:
        """Draft with node_assignments mapping to a valid custom agent should pass."""
        user_reg = UserAgentRegistry(registry)
        spec = _make_custom_spec(allowed_workflows=["text_artifact_v1"])
        reg_result = user_reg.register(spec)
        assert reg_result.harness_valid, (
            f"Registration should succeed. Errors: {reg_result.validation_errors}"
        )

        ok, errors = user_reg.validate_draft_routing(
            draft_node_assignments={"text_buddy": "test_custom_agent"},
            workflow_id="text_artifact_v1",
        )
        assert ok, (
            f"Draft routing should pass for valid custom agent. Errors: {errors}"
        )

    def test_validate_draft_routing_fails_for_wrong_workflow(self, registry: HarnessRegistry) -> None:
        """Draft routing must fail if custom agent does not allow the target workflow."""
        user_reg = UserAgentRegistry(registry)
        spec = _make_custom_spec(allowed_workflows=["finance_v1"])
        reg_result = user_reg.register(spec)
        assert reg_result.harness_valid, (
            f"Registration should succeed. Errors: {reg_result.validation_errors}"
        )

        ok, errors = user_reg.validate_draft_routing(
            draft_node_assignments={"text_buddy": "test_custom_agent"},
            workflow_id="text_artifact_v1",
        )
        assert not ok, (
            "Draft routing should FAIL when custom agent does not allow the workflow"
        )

    def test_custom_agent_does_not_shadow_builtin(self, registry: HarnessRegistry) -> None:
        """Registering a custom agent with a built-in ID must fail."""
        user_reg = UserAgentRegistry(registry)
        spec = _make_custom_spec(agent_id="strategist")
        reg_result = user_reg.register(spec)
        assert not reg_result.harness_valid, (
            "Custom agent with built-in agent_id 'strategist' must fail registration"
        )
        assert any("conflicts" in err or "built-in" in err for err in reg_result.validation_errors)
