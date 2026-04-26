"""Tests for role-based workflow node semantics (Milestone 2)."""

from __future__ import annotations

from agentscope_blaiq.contracts.agent_catalog import LiveAgentProfile
from agentscope_blaiq.contracts.harness import Node, WorkflowTemplate
from agentscope_blaiq.contracts.workflows import WORKFLOW_TEMPLATES


# ============================================================================
# TestNodeRoleSemantics
# ============================================================================


class TestNodeRoleSemantics:
    """Verify Node role auto-fill and accepts_agent logic."""

    def test_legacy_node_fills_role_from_agent_id(self) -> None:
        node = Node(node_id="n1", agent_id="text_buddy")
        assert node.required_role == "text_buddy"

    def test_explicit_role_preserved(self) -> None:
        node = Node(node_id="n1", agent_id="text_buddy", required_role="writer")
        assert node.required_role == "writer"

    def test_accepts_agent_by_role(self) -> None:
        node = Node(node_id="n1", required_role="text_buddy")
        assert node.accepts_agent("text_buddy") is True

    def test_rejects_agent_wrong_role(self) -> None:
        node = Node(node_id="n1", required_role="text_buddy")
        assert node.accepts_agent("vangogh") is False

    def test_accepts_agent_by_legacy_agent_id(self) -> None:
        node = Node(node_id="n1", agent_id="text_buddy")
        assert node.accepts_agent("text_buddy") is True

    def test_capabilities_required(self) -> None:
        node = Node(
            node_id="n1",
            required_role="text_buddy",
            required_capabilities=["text_composition"],
        )
        assert node.accepts_agent("text_buddy", agent_capabilities=["research"]) is False

    def test_capabilities_matched(self) -> None:
        node = Node(
            node_id="n1",
            required_role="text_buddy",
            required_capabilities=["text_composition"],
        )
        assert node.accepts_agent("text_buddy", agent_capabilities=["text_composition", "brand_voice"]) is True


# ============================================================================
# TestWorkflowTemplateRoles
# ============================================================================


class TestWorkflowTemplateRoles:
    """Verify WorkflowTemplate role auto-fill and accepts_role logic."""

    def test_allowed_roles_filled_from_agents(self) -> None:
        template = WorkflowTemplate(
            workflow_id="test_wf",
            purpose="test",
            allowed_agents=["text_buddy", "research"],
        )
        assert set(template.allowed_roles) == {"text_buddy", "research"}

    def test_explicit_allowed_roles_preserved(self) -> None:
        template = WorkflowTemplate(
            workflow_id="test_wf",
            purpose="test",
            allowed_agents=["text_buddy"],
            allowed_roles=["writer"],
        )
        assert template.allowed_roles == ["writer"]

    def test_accepts_role_by_allowed_roles(self) -> None:
        template = WorkflowTemplate(
            workflow_id="test_wf",
            purpose="test",
            allowed_agents=["text_buddy", "research"],
        )
        assert template.accepts_role("text_buddy") is True

    def test_rejects_role_not_allowed(self) -> None:
        template = WorkflowTemplate(
            workflow_id="test_wf",
            purpose="test",
            allowed_agents=["text_buddy", "research"],
        )
        assert template.accepts_role("vangogh") is False

    def test_all_builtin_templates_have_roles(self) -> None:
        assert len(WORKFLOW_TEMPLATES) >= 5, "Expected at least 5 builtin templates"
        for wf_id, template in WORKFLOW_TEMPLATES.items():
            assert len(template.allowed_roles) > 0, (
                f"Template {wf_id} has empty allowed_roles"
            )


# ============================================================================
# TestLiveAgentProfileTypedMetadata
# ============================================================================


class TestLiveAgentProfileTypedMetadata:
    """Verify new typed metadata fields on LiveAgentProfile."""

    def test_tags_field_exists(self) -> None:
        profile = LiveAgentProfile(name="test", role="tester")
        assert hasattr(profile, "tags")
        assert profile.tags == []

    def test_artifact_affinities_field_exists(self) -> None:
        profile = LiveAgentProfile(name="test", role="tester")
        assert hasattr(profile, "artifact_affinities")
        assert profile.artifact_affinities == []

    def test_is_custom_default_false(self) -> None:
        profile = LiveAgentProfile(name="test", role="tester")
        assert profile.is_custom is False
