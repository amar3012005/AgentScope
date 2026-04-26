"""
Tests for dispatch validation (Phase 1.5).

Validates that agent dispatches, tool calls, and handoffs are checked
against harness contracts before execution.
"""

import pytest

from agentscope_blaiq.contracts.dispatch import (
    DispatchResult,
    validate_dispatch,
    validate_handoff,
    validate_tool_call,
)
from agentscope_blaiq.contracts.harness import AGENT_HARNESSES, TOOL_HARNESSES
from agentscope_blaiq.contracts.registry import HarnessRegistry


@pytest.fixture
def registry() -> HarnessRegistry:
    """Fresh registry with all built-ins loaded."""
    reg = HarnessRegistry()
    reg.load_builtin_agents()
    reg.load_builtin_tools()
    return reg


# ============================================================================
# validate_dispatch
# ============================================================================

class TestValidateDispatch:
    """Test agent dispatch validation."""

    def test_valid_dispatch_strategist(self, registry: HarnessRegistry):
        """Valid strategist dispatch passes."""
        result = validate_dispatch(
            "strategist",
            {"user_request": "Build me a pitch deck"},
            registry,
        )
        assert result.ok
        assert len(result.errors) == 0

    def test_valid_dispatch_research(self, registry: HarnessRegistry):
        """Valid research dispatch passes."""
        result = validate_dispatch(
            "research",
            {"query": "Market analysis for SaaS"},
            registry,
        )
        assert result.ok

    def test_unknown_agent_fails(self, registry: HarnessRegistry):
        """Dispatch to unknown agent fails."""
        result = validate_dispatch("nonexistent", {}, registry)
        assert not result.ok
        assert any("No harness" in e for e in result.errors)

    def test_missing_required_input_fails(self, registry: HarnessRegistry):
        """Dispatch with missing required input field fails."""
        result = validate_dispatch(
            "strategist",
            {},  # Missing user_request
            registry,
        )
        assert not result.ok
        assert any("user_request" in e for e in result.errors)

    def test_workflow_compatibility_pass(self, registry: HarnessRegistry):
        """Agent allowed in workflow passes."""
        result = validate_dispatch(
            "research",
            {"query": "test"},
            registry,
            workflow_id="research_v1",
        )
        assert result.ok

    def test_workflow_template_alias_is_canonicalized(self, registry: HarnessRegistry):
        """Validation accepts non-versioned workflow aliases."""
        result = validate_dispatch(
            "research",
            {"query": "test"},
            registry,
            workflow_id="research",
        )
        assert result.ok

    def test_workflow_compatibility_fail(self, registry: HarnessRegistry):
        """Agent not allowed in workflow fails."""
        result = validate_dispatch(
            "text_buddy",
            {"evidence_pack": {}, "artifact_family": "email"},
            registry,
            workflow_id="visual_artifact_v1",
        )
        assert not result.ok
        assert any("not allowed in workflow" in e for e in result.errors)

    def test_tool_access_valid(self, registry: HarnessRegistry):
        """Agent with allowed tools passes."""
        result = validate_dispatch(
            "research",
            {"query": "test"},
            registry,
            tools_requested=["hivemind_recall", "hivemind_web_search"],
        )
        assert result.ok

    def test_tool_access_denied(self, registry: HarnessRegistry):
        """Agent using unauthorized tool fails."""
        result = validate_dispatch(
            "governance",
            {"artifact": {}},
            registry,
            tools_requested=["hivemind_recall"],
        )
        assert not result.ok
        assert any("not allowed to use tool" in e for e in result.errors)

    def test_required_context_warning(self, registry: HarnessRegistry):
        """Missing required context produces warning (not error) in non-strict mode."""
        # Set up a harness with required_context
        from agentscope_blaiq.contracts.harness import AgentHarness
        custom = AgentHarness(
            agent_id="custom_test",
            role="test",
            required_context=["tenant_id", "session_id"],
        )
        registry.add_agent(custom)

        result = validate_dispatch(
            "custom_test",
            {},  # Missing required context
            registry,
        )
        assert result.ok  # Non-strict: warnings only
        assert len(result.warnings) == 2

    def test_required_context_strict_fails(self, registry: HarnessRegistry):
        """Missing required context fails in strict mode."""
        from agentscope_blaiq.contracts.harness import AgentHarness
        custom = AgentHarness(
            agent_id="custom_strict",
            role="test",
            required_context=["tenant_id"],
        )
        registry.add_agent(custom)

        result = validate_dispatch(
            "custom_strict",
            {},
            registry,
            strict=True,
        )
        assert not result.ok

    def test_dispatch_result_bool(self, registry: HarnessRegistry):
        """DispatchResult is truthy when ok=True."""
        result = validate_dispatch("strategist", {"user_request": "test"}, registry)
        assert bool(result)

        result = validate_dispatch("nonexistent", {}, registry)
        assert not bool(result)


# ============================================================================
# validate_tool_call
# ============================================================================

class TestValidateToolCall:
    """Test tool call validation."""

    def test_valid_tool_call(self, registry: HarnessRegistry):
        """Valid tool call passes."""
        result = validate_tool_call(
            "research",
            "hivemind_recall",
            {"query": "test"},
            registry,
        )
        assert result.ok

    def test_agent_not_allowed_tool(self, registry: HarnessRegistry):
        """Agent using tool not in its allowed_tools fails."""
        result = validate_tool_call(
            "governance",
            "hivemind_recall",
            {"query": "test"},
            registry,
        )
        assert not result.ok
        assert any("not allowed to use" in e for e in result.errors)

    def test_tool_not_allowing_agent(self, registry: HarnessRegistry):
        """Tool not listing agent in allowed_agents fails."""
        result = validate_tool_call(
            "strategist",
            "hivemind_web_search",
            {},
            registry,
        )
        assert not result.ok
        assert any("does not allow" in e for e in result.errors)

    def test_unknown_tool_fails(self, registry: HarnessRegistry):
        """Tool call to unknown tool fails."""
        result = validate_tool_call(
            "research",
            "nonexistent_tool",
            {},
            registry,
        )
        assert not result.ok
        assert any("No harness" in e for e in result.errors)

    def test_tool_workflow_compatibility(self, registry: HarnessRegistry):
        """Tool not allowed in current workflow fails."""
        result = validate_tool_call(
            "text_buddy",
            "apply_brand_voice",
            {},
            registry,
            workflow_id="visual_artifact_v1",
        )
        assert not result.ok
        assert any("not allowed in workflow" in e for e in result.errors)

    def test_tool_workflow_template_alias_is_canonicalized(self, registry: HarnessRegistry):
        """Tool validation accepts canonical workflow aliases."""
        result = validate_tool_call(
            "research",
            "hivemind_recall",
            {"query": "test"},
            registry,
            workflow_id="research",
        )
        assert result.ok

    def test_tool_input_schema_validation(self, registry: HarnessRegistry):
        """Tool with input schema validates data."""
        result = validate_tool_call(
            "research",
            "hivemind_recall",
            {"query": 123},  # Should be string
            registry,
        )
        assert not result.ok
        assert any("input" in e.lower() for e in result.errors)

    def test_deep_research_shares_research_tools(self, registry: HarnessRegistry):
        """Deep research agent can use shared research tools."""
        result = validate_tool_call(
            "deep_research",
            "hivemind_recall",
            {"query": "test"},
            registry,
        )
        assert result.ok

    def test_finance_research_shares_research_tools(self, registry: HarnessRegistry):
        """Finance research agent can use shared research tools."""
        result = validate_tool_call(
            "finance_research",
            "hivemind_web_search",
            {},
            registry,
        )
        assert result.ok


# ============================================================================
# validate_handoff
# ============================================================================

class TestValidateHandoff:
    """Test handoff validation between agents."""

    def test_valid_handoff_research_to_content(self, registry: HarnessRegistry):
        """Research -> Content Director handoff with valid data passes."""
        result = validate_handoff(
            "research",
            "content_director",
            {"evidence_pack": {"findings": []}, "artifact_family": "pitch_deck"},
            registry,
        )
        assert result.ok

    def test_handoff_missing_output_schema_field(self, registry: HarnessRegistry):
        """Handoff with missing required output field fails."""
        result = validate_handoff(
            "research",
            "content_director",
            {},  # Missing evidence_pack
            registry,
        )
        assert not result.ok
        assert any("output" in e.lower() or "evidence_pack" in e.lower() for e in result.errors)

    def test_handoff_unknown_source_fails(self, registry: HarnessRegistry):
        """Handoff from unknown agent fails."""
        result = validate_handoff("nonexistent", "research", {}, registry)
        assert not result.ok

    def test_handoff_unknown_target_fails(self, registry: HarnessRegistry):
        """Handoff to unknown agent fails."""
        result = validate_handoff("research", "nonexistent", {}, registry)
        assert not result.ok

    def test_handoff_workflow_mismatch(self, registry: HarnessRegistry):
        """Handoff between agents not in same workflow fails."""
        result = validate_handoff(
            "text_buddy",
            "vangogh",
            {"artifact": {}},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert not result.ok
        assert any("vangogh" in e and "not allowed" in e for e in result.errors)

    def test_handoff_same_workflow_passes(self, registry: HarnessRegistry):
        """Handoff between agents in same workflow passes."""
        result = validate_handoff(
            "research",
            "content_director",
            {"evidence_pack": {"findings": []}},
            registry,
            workflow_id="visual_artifact_v1",
        )
        assert result.ok

    def test_handoff_strategist_to_research_variant_passes(self, registry: HarnessRegistry):
        """Strategist -> deep_research is treated as canonical strategist -> research handoff."""
        registry.load_builtin_workflows()
        result = validate_handoff(
            "strategist",
            "deep_research",
            {
                "workflow_id": "visual_artifact_v1",
                "query": "Build a pitch deck",
                "source_scope": "web_and_docs",
                "workflow_plan": {},
                "task_graph": {},
                "missing_requirements": [],
            },
            registry,
            workflow_id="visual_artifact",
        )
        assert result.ok

    def test_handoff_edge_not_in_template_is_blocked(self, registry: HarnessRegistry):
        """Template-defined handoff edges are enforced when workflow templates are loaded."""
        registry.load_builtin_workflows()
        result = validate_handoff(
            "strategist",
            "vangogh",
            {
                "workflow_id": "visual_artifact_v1",
                "query": "Build a pitch deck",
                "source_scope": "web_and_docs",
                "workflow_plan": {},
                "task_graph": {},
                "missing_requirements": [],
            },
            registry,
            workflow_id="visual_artifact",
        )
        assert not result.ok
        assert any("not allowed in workflow" in e for e in result.errors)


# ============================================================================
# Integration: Full dispatch chain
# ============================================================================

class TestFullDispatchChain:
    """Test realistic multi-step dispatch chains."""

    def test_text_artifact_chain(self, registry: HarnessRegistry):
        """Full text artifact chain validates cleanly."""
        # 1. Dispatch strategist
        r1 = validate_dispatch(
            "strategist",
            {"user_request": "Write me a professional email"},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert r1.ok

        # 2. Dispatch research
        r2 = validate_dispatch(
            "research",
            {"query": "Professional email templates"},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert r2.ok

        # 3. Tool call: hivemind_recall
        r3 = validate_tool_call(
            "research",
            "hivemind_recall",
            {"query": "email templates"},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert r3.ok

        # 4. Handoff: research -> text_buddy
        r4 = validate_handoff(
            "research",
            "text_buddy",
            {"evidence_pack": {"findings": []}, "artifact_family": "email"},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert r4.ok

        # 5. Tool call: apply_brand_voice
        r5 = validate_tool_call(
            "text_buddy",
            "apply_brand_voice",
            {},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert r5.ok

        # 6. Dispatch governance
        r6 = validate_dispatch(
            "governance",
            {"artifact": {"content": "email text"}},
            registry,
            workflow_id="text_artifact_v1",
        )
        assert r6.ok

    def test_visual_artifact_chain(self, registry: HarnessRegistry):
        """Full visual artifact chain validates cleanly."""
        # strategist -> research -> content_director -> vangogh -> governance
        assert validate_dispatch("strategist", {"user_request": "Pitch deck"}, registry, workflow_id="visual_artifact_v1")
        assert validate_dispatch("research", {"query": "market data"}, registry, workflow_id="visual_artifact_v1")
        assert validate_handoff("research", "content_director", {"evidence_pack": {}, "artifact_family": "pitch_deck"}, registry, workflow_id="visual_artifact_v1")
        assert validate_tool_call("vangogh", "artifact_contract", {}, registry, workflow_id="visual_artifact_v1")
        assert validate_dispatch("governance", {"artifact": {}}, registry, workflow_id="visual_artifact_v1")

    def test_cross_workflow_blocked(self, registry: HarnessRegistry):
        """Text agent in visual workflow blocked."""
        result = validate_dispatch(
            "text_buddy",
            {"evidence_pack": {}, "artifact_family": "email"},
            registry,
            workflow_id="visual_artifact_v1",
        )
        assert not result.ok
