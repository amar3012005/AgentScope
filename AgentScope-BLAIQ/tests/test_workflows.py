"""
Tests for Phase 2: Canonical Workflow Templates

Validates that all canonical workflows are:
  - Properly defined and loadable
  - DAG-valid (no cycles, valid edges)
  - Agent/tool existence in registry
  - Isolation to correct agents/tools
"""

import pytest

from agentscope_blaiq.contracts import (
    DIRECT_ANSWER_V1,
    FINANCE_V1,
    RESEARCH_V1,
    TEXT_ARTIFACT_V1,
    VISUAL_ARTIFACT_V1,
    WORKFLOW_TEMPLATES,
    EvidencePack,
    GovernanceReview,
    StrategicPlan,
    TextArtifact,
    UserRequest,
    VisualArtifact,
    VisualSpec,
    get_workflow_template,
    list_workflow_templates,
)
from agentscope_blaiq.contracts.registry import HarnessRegistry
from agentscope_blaiq.contracts.validation import validate_workflow_template


@pytest.fixture
def registry() -> HarnessRegistry:
    """Fresh registry with all built-ins loaded."""
    reg = HarnessRegistry()
    reg.load_builtin_agents()
    reg.load_builtin_tools()
    return reg


# ============================================================================
# Template Loading
# ============================================================================

class TestWorkflowLoading:
    """Test that all 5 canonical templates load correctly."""

    def test_all_templates_defined(self):
        """All 5 templates in WORKFLOW_TEMPLATES."""
        assert len(WORKFLOW_TEMPLATES) == 5
        assert "visual_artifact_v1" in WORKFLOW_TEMPLATES
        assert "text_artifact_v1" in WORKFLOW_TEMPLATES
        assert "direct_answer_v1" in WORKFLOW_TEMPLATES
        assert "research_v1" in WORKFLOW_TEMPLATES
        assert "finance_v1" in WORKFLOW_TEMPLATES

    def test_get_workflow_template(self):
        """get_workflow_template() retrieves by ID."""
        t = get_workflow_template("visual_artifact_v1")
        assert t is not None
        assert t.workflow_id == "visual_artifact_v1"

    def test_get_nonexistent_template(self):
        """get_workflow_template() returns None for unknown ID."""
        t = get_workflow_template("nonexistent")
        assert t is None

    def test_list_workflow_templates(self):
        """list_workflow_templates() returns sorted list."""
        ids = list_workflow_templates()
        assert len(ids) == 5
        assert ids == sorted(ids)
        assert "visual_artifact_v1" in ids

    def test_visual_artifact_v1_structure(self):
        """visual_artifact_v1 has staged nodes with HITL + recall."""
        t = VISUAL_ARTIFACT_V1
        assert t.workflow_id == "visual_artifact_v1"
        assert len(t.nodes) == 7
        node_ids = [n.node_id for n in t.nodes]
        assert node_ids == [
            "strategist",
            "research",
            "hitl_verification",
            "research_final_recall",
            "content_director",
            "vangogh",
            "governance",
        ]

    def test_text_artifact_v1_structure(self):
        """text_artifact_v1 has staged nodes with HITL + recall."""
        t = TEXT_ARTIFACT_V1
        assert t.workflow_id == "text_artifact_v1"
        assert len(t.nodes) == 7
        node_ids = [n.node_id for n in t.nodes]
        assert node_ids == [
            "strategist",
            "research",
            "hitl_verification",
            "research_final_recall",
            "content_director",
            "text_buddy",
            "governance",
        ]

    def test_direct_answer_v1_structure(self):
        """direct_answer_v1 is minimal 2-node workflow."""
        t = DIRECT_ANSWER_V1
        assert t.workflow_id == "direct_answer_v1"
        assert len(t.nodes) == 2
        assert t.nodes[0].agent_id == "research"
        assert t.nodes[1].agent_id == "text_buddy"

    def test_research_v1_structure(self):
        """research_v1 has 3 nodes with fanout/merge."""
        t = RESEARCH_V1
        assert t.workflow_id == "research_v1"
        assert len(t.nodes) == 3
        node_ids = [n.node_id for n in t.nodes]
        assert "research" in node_ids
        assert "deep_research" in node_ids
        assert "text_buddy" in node_ids

    def test_finance_v1_structure(self):
        """finance_v1 has 4 nodes with finance_research."""
        t = FINANCE_V1
        assert t.workflow_id == "finance_v1"
        assert len(t.nodes) == 4
        agent_ids = [n.agent_id for n in t.nodes]
        assert "finance_research" in agent_ids
        assert "data_science" in agent_ids


# ============================================================================
# DAG Validation
# ============================================================================

class TestWorkflowDAG:
    """Test DAG validity via workflow validation."""

    def test_visual_artifact_v1_dag_valid(self):
        """visual_artifact_v1 DAG passes validation."""
        ok, errors = validate_workflow_template(VISUAL_ARTIFACT_V1)
        assert ok, errors

    def test_text_artifact_v1_dag_valid(self):
        """text_artifact_v1 DAG passes validation."""
        ok, errors = validate_workflow_template(TEXT_ARTIFACT_V1)
        assert ok, errors

    def test_direct_answer_v1_dag_valid(self):
        """direct_answer_v1 DAG passes validation."""
        ok, errors = validate_workflow_template(DIRECT_ANSWER_V1)
        assert ok, errors

    def test_research_v1_dag_valid(self):
        """research_v1 DAG passes validation."""
        ok, errors = validate_workflow_template(RESEARCH_V1)
        assert ok, errors

    def test_finance_v1_dag_valid(self):
        """finance_v1 DAG passes validation."""
        ok, errors = validate_workflow_template(FINANCE_V1)
        assert ok, errors

    def test_all_templates_dag_valid(self):
        """All 5 templates pass DAG validation."""
        for template in WORKFLOW_TEMPLATES.values():
            ok, errors = validate_workflow_template(template)
            assert ok, f"{template.workflow_id}: {errors}"

    def test_visual_artifact_edges_sequential(self):
        """visual_artifact forms staged DAG."""
        t = VISUAL_ARTIFACT_V1
        strategist = next(n for n in t.nodes if n.node_id == "strategist")
        research = next(n for n in t.nodes if n.node_id == "research")
        hitl = next(n for n in t.nodes if n.node_id == "hitl_verification")
        final_recall = next(n for n in t.nodes if n.node_id == "research_final_recall")
        content_director = next(n for n in t.nodes if n.node_id == "content_director")
        vangogh = next(n for n in t.nodes if n.node_id == "vangogh")
        governance = next(n for n in t.nodes if n.node_id == "governance")

        assert strategist.input_from == ["start"]
        assert "research" in strategist.output_to
        assert "strategist" in research.input_from
        assert "hitl_verification" in research.output_to
        assert "research" in hitl.input_from
        assert "research_final_recall" in hitl.output_to
        assert "hitl_verification" in final_recall.input_from
        assert "content_director" in final_recall.output_to
        assert "research_final_recall" in content_director.input_from
        assert "vangogh" in content_director.output_to
        assert "content_director" in vangogh.input_from
        assert "governance" in vangogh.output_to
        assert "vangogh" in governance.input_from
        assert governance.output_to == []


# ============================================================================
# Agent/Tool Existence
# ============================================================================

class TestWorkflowAgentToolExistence:
    """Test that all referenced agents and tools exist."""

    def test_all_agents_in_templates_exist(self, registry: HarnessRegistry):
        """All agent IDs in templates exist in registry."""
        for template in WORKFLOW_TEMPLATES.values():
            for node in template.nodes:
                agent = registry.get_agent(node.agent_id)
                assert agent is not None, f"Agent '{node.agent_id}' not in {template.workflow_id}"

    def test_all_tools_in_templates_exist(self, registry: HarnessRegistry):
        """All tool IDs in templates exist in registry."""
        for template in WORKFLOW_TEMPLATES.values():
            for node in template.nodes:
                for tool_id in node.required_tools:
                    tool = registry.get_tool(tool_id)
                    assert tool is not None, f"Tool '{tool_id}' not in {template.workflow_id}"

    def test_visual_artifact_tools(self, registry: HarnessRegistry):
        """visual_artifact_v1 uses only valid tools."""
        t = VISUAL_ARTIFACT_V1
        all_tools = set()
        for node in t.nodes:
            all_tools.update(node.required_tools)
        # Should only contain: hivemind_recall, hivemind_web_search, artifact_contract
        assert "hivemind_recall" in all_tools
        assert "artifact_contract" in all_tools

    def test_research_v1_deep_research_agent(self, registry: HarnessRegistry):
        """research_v1 has deep_research with web_crawl."""
        t = RESEARCH_V1
        deep_research_node = next((n for n in t.nodes if n.agent_id == "deep_research"), None)
        assert deep_research_node is not None
        assert "hivemind_web_crawl" in deep_research_node.required_tools


# ============================================================================
# Workflow Isolation
# ============================================================================

class TestWorkflowIsolation:
    """Test workflow agent/tool isolation."""

    def test_visual_and_text_agents_differ(self):
        """visual_artifact and text_artifact have different agents."""
        visual_agents = set(n.agent_id for n in VISUAL_ARTIFACT_V1.nodes)
        text_agents = set(n.agent_id for n in TEXT_ARTIFACT_V1.nodes)

        assert "content_director" in visual_agents
        assert "vangogh" in visual_agents
        assert "text_buddy" in text_agents
        assert "content_director" in text_agents
        assert "vangogh" not in text_agents

    def test_direct_answer_minimal_agents(self):
        """direct_answer_v1 uses only research and text_buddy."""
        agents = set(n.agent_id for n in DIRECT_ANSWER_V1.nodes)
        assert len(agents) == 2
        assert agents == {"research", "text_buddy"}

    def test_finance_exclusive_agents(self):
        """finance_v1 uses finance_research and data_science."""
        agents = set(n.agent_id for n in FINANCE_V1.nodes)
        assert "finance_research" in agents
        assert "data_science" in agents

    def test_governance_multiuse(self):
        """governance appears in visual, text, finance (shared agent)."""
        visual_has_gov = any(n.agent_id == "governance" for n in VISUAL_ARTIFACT_V1.nodes)
        text_has_gov = any(n.agent_id == "governance" for n in TEXT_ARTIFACT_V1.nodes)
        finance_has_gov = any(n.agent_id == "governance" for n in FINANCE_V1.nodes)

        assert visual_has_gov
        assert text_has_gov
        assert finance_has_gov


# ============================================================================
# Approval Gates
# ============================================================================

class TestApprovalGates:
    """Test approval gate configuration."""

    def test_visual_artifact_has_governance_gate(self):
        """visual_artifact_v1 has governance approval_gate."""
        assert "governance" in VISUAL_ARTIFACT_V1.approval_gates
        gov_node = next(n for n in VISUAL_ARTIFACT_V1.nodes if n.agent_id == "governance")
        assert gov_node.approval_gate == "governance"

    def test_text_artifact_has_governance_gate(self):
        """text_artifact_v1 has governance approval_gate."""
        assert "governance" in TEXT_ARTIFACT_V1.approval_gates
        gov_node = next(n for n in TEXT_ARTIFACT_V1.nodes if n.agent_id == "governance")
        assert gov_node.approval_gate == "governance"

    def test_direct_answer_no_gates(self):
        """direct_answer_v1 has no approval gates."""
        assert len(DIRECT_ANSWER_V1.approval_gates) == 0
        for node in DIRECT_ANSWER_V1.nodes:
            assert node.approval_gate is None

    def test_finance_has_governance_gate(self):
        """finance_v1 has governance approval_gate."""
        assert "governance" in FINANCE_V1.approval_gates
        gov_node = next(n for n in FINANCE_V1.nodes if n.agent_id == "governance")
        assert gov_node.approval_gate == "governance"


# ============================================================================
# Message Contracts
# ============================================================================

class TestMessageContracts:
    """Test Phase 2 message contract classes."""

    def test_user_request(self):
        """UserRequest dataclass."""
        req = UserRequest(query="test", artifact_family="pitch_deck")
        assert req.query == "test"
        assert req.artifact_family == "pitch_deck"

    def test_strategic_plan(self):
        """StrategicPlan dataclass."""
        plan = StrategicPlan(
            user_request="test",
            strategy_summary="summary",
            artifact_family="pitch_deck",
            artifact_spec={"sections": []},
            research_focus="market"
        )
        assert plan.artifact_family == "pitch_deck"

    def test_evidence_pack(self):
        """EvidencePack dataclass."""
        evidence = EvidencePack(
            findings=[{"title": "Finding 1"}],
            citations=[{"source": "web"}],
            source_summary="summary",
            confidence_score=0.85
        )
        assert evidence.confidence_score == 0.85

    def test_visual_spec(self):
        """VisualSpec dataclass."""
        spec = VisualSpec(
            artifact_family="pitch_deck",
            layout_structure={"sections": []},
            sections=[],
            styling_hints={},
            component_specs=[]
        )
        assert spec.artifact_family == "pitch_deck"

    def test_visual_artifact(self):
        """VisualArtifact dataclass."""
        artifact = VisualArtifact(
            artifact_family="pitch_deck",
            content="<html></html>",
            styling={}
        )
        assert artifact.content == "<html></html>"

    def test_text_artifact(self):
        """TextArtifact dataclass."""
        artifact = TextArtifact(
            artifact_family="email",
            content="Hello...",
            tone="professional"
        )
        assert artifact.tone == "professional"

    def test_governance_review(self):
        """GovernanceReview dataclass."""
        review = GovernanceReview(
            artifact_id="artifact_1",
            approved=True,
            review_notes="Approved"
        )
        assert review.approved is True


# ============================================================================
# Handoff Validation
# ============================================================================

class TestRequiredHandoffs:
    """Test that required_handoffs are consistent."""

    def test_visual_artifact_handoffs(self):
        """visual_artifact has all staged handoffs."""
        t = VISUAL_ARTIFACT_V1
        expected = {
            ("strategist", "research"),
            ("research", "hitl_verification"),
            ("hitl_verification", "research_final_recall"),
            ("research_final_recall", "content_director"),
            ("content_director", "vangogh"),
            ("vangogh", "governance"),
        }
        actual = set(t.required_handoffs)
        assert actual == expected

    def test_text_artifact_handoffs(self):
        """text_artifact has all staged handoffs."""
        t = TEXT_ARTIFACT_V1
        expected = {
            ("strategist", "research"),
            ("research", "hitl_verification"),
            ("hitl_verification", "research_final_recall"),
            ("research_final_recall", "content_director"),
            ("content_director", "text_buddy"),
            ("text_buddy", "governance"),
        }
        actual = set(t.required_handoffs)
        assert actual == expected

    def test_research_v1_handoffs(self):
        """research_v1 has fanout/merge handoffs."""
        t = RESEARCH_V1
        expected = {
            ("research", "deep_research"),
            ("research", "text_buddy"),
            ("deep_research", "text_buddy"),
        }
        actual = set(t.required_handoffs)
        assert actual == expected


# ============================================================================
# Fallback Branches
# ============================================================================

class TestFallbackBranches:
    """Test fallback behavior configuration."""

    def test_visual_artifact_fallbacks(self):
        """visual_artifact has staged fallbacks."""
        t = VISUAL_ARTIFACT_V1
        assert "insufficient_findings" in t.fallback_branches
        assert "human_rejected" in t.fallback_branches

    def test_text_artifact_fallbacks(self):
        """text_artifact has weak_evidence and timeout fallbacks."""
        t = TEXT_ARTIFACT_V1
        assert "weak_evidence" in t.fallback_branches
        assert "timeout" in t.fallback_branches

    def test_direct_answer_no_fallbacks(self):
        """direct_answer has no fallback branches."""
        t = DIRECT_ANSWER_V1
        assert len(t.fallback_branches) == 0

    def test_research_v1_deep_research_fallback(self):
        """research_v1 can skip deep_research on timeout."""
        t = RESEARCH_V1
        assert "deep_research_timeout" in t.fallback_branches
        assert t.fallback_branches["deep_research_timeout"] == "text_buddy"


# ============================================================================
# Integration
# ============================================================================

class TestIntegration:
    """Full workflow integration tests."""

    def test_all_templates_load_and_validate(self):
        """All templates pass complete validation suite."""
        for template in WORKFLOW_TEMPLATES.values():
            # Load
            assert template is not None
            # Structure
            assert len(template.nodes) > 0
            assert len(template.allowed_agents) > 0
            # Validate
            ok, errors = validate_workflow_template(template)
            assert ok, f"{template.workflow_id} validation failed: {errors}"

    def test_shared_agents_consistent_across_workflows(self):
        """Agents used in multiple workflows have consistent tool access."""
        # research appears in: visual, text, direct_answer, research, finance
        workflows_with_research = [
            VISUAL_ARTIFACT_V1, TEXT_ARTIFACT_V1, DIRECT_ANSWER_V1, RESEARCH_V1, FINANCE_V1
        ]
        
        research_configs = []
        for wf in workflows_with_research:
            research_node = next((n for n in wf.nodes if n.agent_id == "research"), None)
            if research_node:
                research_configs.append(research_node)
        
        # All research nodes should have hivemind_recall access
        assert all("hivemind_recall" in n.required_tools for n in research_configs)
