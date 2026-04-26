"""Tests for role-based routing: resolver in strategist, dispatch validation, and can_route_to.

Covers M4 integration: AgentResolver wired into StrategicAgent._assign_role_agent,
dispatch validation with role-based fallback, and UserAgentRegistry.can_route_to
with role compatibility checks.
"""
from __future__ import annotations

import pytest

from agentscope_blaiq.contracts.agent_catalog import (
    AgentCapability,
    AgentSkill,
    AgentStatus,
    LiveAgentProfile,
)
from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
from agentscope_blaiq.contracts.dispatch import validate_dispatch, DispatchResult
from agentscope_blaiq.contracts.harness import AgentHarness, WorkflowTemplate
from agentscope_blaiq.contracts.registry import HarnessRegistry
from agentscope_blaiq.contracts.user_agent_registry import UserAgentRegistry


# ── Helpers ───────────────────────────────────────────────────────────


def _cap(
    name: str,
    *,
    task_roles: list[str] | None = None,
    artifact_families: list[str] | None = None,
) -> AgentCapability:
    return AgentCapability(
        name=name,
        description=f"{name} capability",
        supported_task_roles=task_roles or [],
        supported_artifact_families=artifact_families or [],
    )


def _make_profile(
    name: str,
    role: str,
    *,
    capabilities: list[AgentCapability] | None = None,
    tools: list[str] | None = None,
    is_custom: bool = False,
    tags: list[str] | None = None,
    artifact_affinities: list[str] | None = None,
) -> LiveAgentProfile:
    return LiveAgentProfile(
        name=name,
        role=role,
        status=AgentStatus.ready,
        capabilities=capabilities or [],
        tools=tools or [],
        is_custom=is_custom,
        tags=tags or [],
        artifact_affinities=artifact_affinities or [],
    )


def _make_harness(
    agent_id: str,
    role: str,
    *,
    allowed_workflows: list[str] | None = None,
) -> AgentHarness:
    return AgentHarness(
        agent_id=agent_id,
        role=role,
        allowed_workflows=allowed_workflows or [],
    )


def _make_workflow(
    workflow_id: str,
    allowed_agents: list[str],
) -> WorkflowTemplate:
    return WorkflowTemplate(
        workflow_id=workflow_id,
        purpose=f"Workflow for {workflow_id}",
        allowed_agents=allowed_agents,
    )


def _text_buddy_spec(
    agent_id: str = "custom_text_buddy",
    *,
    tags: list[str] | None = None,
    artifact_family: str | None = None,
    allowed_workflows: list[str] | None = None,
) -> CustomAgentSpec:
    return CustomAgentSpec(
        agent_id=agent_id,
        display_name="Custom Text Buddy",
        prompt="You are a custom text composition agent.",
        role="text_buddy",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        tags=tags or [],
        artifact_family=artifact_family,
        allowed_workflows=allowed_workflows or [],
        allowed_tools=[],
    )


def _vangogh_spec(
    agent_id: str = "custom_vangogh",
) -> CustomAgentSpec:
    return CustomAgentSpec(
        agent_id=agent_id,
        display_name="Custom Vangogh",
        prompt="You are a custom visual agent.",
        role="vangogh",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"artifact": {"type": "string"}}},
        allowed_tools=[],
    )


def _build_registry_with_workflow(
    workflow_id: str,
    allowed_agents: list[str],
    agents: list[AgentHarness] | None = None,
) -> HarnessRegistry:
    """Build a minimal HarnessRegistry with one workflow and optional agents."""
    registry = HarnessRegistry()
    wf = _make_workflow(workflow_id, allowed_agents)
    registry.workflows[workflow_id] = wf
    for agent in (agents or []):
        registry.agents[agent.agent_id] = agent
    return registry


# ── TestResolverInStrategist ─────────────────────────────────────────


class TestResolverInStrategist:
    """Verify _assign_role_agent logic delegates to the scored resolver.

    We test the resolver directly (same logic as _assign_role_agent) to avoid
    importing StrategicAgent which pulls in ``agentscope`` — a heavy external
    dependency not always available in unit-test environments.
    """

    def test_builtin_text_buddy_assigned_by_default(self) -> None:
        """When no custom agents exist, the built-in text_buddy gets assigned."""
        from agentscope_blaiq.contracts.resolver import resolve_agent

        catalog = [
            _make_profile(
                "text_buddy",
                "brand-voice text composition",
                capabilities=[
                    _cap("text_composition", task_roles=["text_buddy"]),
                    _cap("brand_voice_writing", task_roles=["text_buddy"]),
                ],
            ),
            _make_profile(
                "vangogh",
                "visual artifact generation",
                capabilities=[_cap("artifact_layout")],
            ),
        ]
        # Mirrors _assign_role_agent(catalog, "text_composition", "text_buddy")
        result = resolve_agent(
            catalog,
            required_role="text_buddy",
            required_capabilities=["text_composition"],
            default_agent="text_buddy",
        )
        # text_buddy is the default and should match via capability role
        assert result.selected == "text_buddy"

    def test_custom_agent_preferred_over_builtin(self) -> None:
        """A custom agent with matching role and tags beats the built-in."""
        from agentscope_blaiq.contracts.resolver import resolve_agent

        builtin = _make_profile(
            "text_buddy",
            "text_buddy",
            capabilities=[
                _cap("text_composition", task_roles=["text_buddy"],
                     artifact_families=["social_post"]),
            ],
            is_custom=False,
        )
        custom = _make_profile(
            "my_social_writer",
            "text_buddy",
            capabilities=[
                _cap("text_composition", task_roles=["text_buddy"],
                     artifact_families=["social_post"]),
            ],
            is_custom=True,
            tags=["linkedin", "social"],
            artifact_affinities=["social_post"],
        )
        catalog = [builtin, custom]
        # Mirrors _assign_role_agent(catalog, "text_composition", "text_buddy", artifact_family="social_post")
        result = resolve_agent(
            catalog,
            required_role="text_buddy",
            required_capabilities=["text_composition"],
            artifact_family="social_post",
            default_agent="text_buddy",
        )
        assert result.selected == "my_social_writer"


# ── TestDispatchValidationRoleBased ──────────────────────────────────


class TestDispatchValidationRoleBased:
    """Verify dispatch validation accepts agents by role when not in allowed_agents list."""

    def test_custom_agent_passes_dispatch_by_role(self) -> None:
        """A custom agent whose role matches an allowed_role passes dispatch."""
        agent_harness = _make_harness(
            "custom_text_buddy",
            role="text_buddy",
            allowed_workflows=["text_artifact_v1"],
        )
        # Workflow allows "text_buddy" (the built-in) but not "custom_text_buddy"
        registry = _build_registry_with_workflow(
            "text_artifact_v1",
            allowed_agents=["research", "text_buddy", "governance"],
            agents=[agent_harness],
        )

        result = validate_dispatch(
            "custom_text_buddy",
            {},
            registry,
            workflow_id="text_artifact_v1",
        )
        # Should pass because the role "text_buddy" is in allowed_roles
        assert result.ok is True, f"Expected ok=True, got errors: {result.errors}"

    def test_dispatch_fails_for_incompatible_role(self) -> None:
        """An agent with a role not in the workflow's allowed_roles fails."""
        agent_harness = _make_harness(
            "custom_vangogh",
            role="vangogh",
            allowed_workflows=["text_artifact_v1"],
        )
        # text_artifact_v1 only allows text_buddy-related roles
        registry = _build_registry_with_workflow(
            "text_artifact_v1",
            allowed_agents=["research", "text_buddy", "governance"],
            agents=[agent_harness],
        )

        result = validate_dispatch(
            "custom_vangogh",
            {},
            registry,
            workflow_id="text_artifact_v1",
        )
        # Should fail because "vangogh" role is not in allowed_roles
        assert result.ok is False
        assert any("does not allow agent" in err for err in result.errors)


# ── TestCanRouteToRoleBased ──────────────────────────────────────────


class TestCanRouteToRoleBased:
    """Verify UserAgentRegistry.can_route_to checks role compatibility."""

    def _make_user_registry(
        self,
        workflow_id: str,
        allowed_agents: list[str],
    ) -> UserAgentRegistry:
        registry = _build_registry_with_workflow(
            workflow_id, allowed_agents,
        )
        return UserAgentRegistry(registry)

    def test_custom_agent_routes_when_role_compatible(self) -> None:
        """A custom text_buddy agent routes to text_artifact_v1."""
        user_reg = self._make_user_registry(
            "text_artifact_v1",
            allowed_agents=["research", "text_buddy", "governance"],
        )
        spec = _text_buddy_spec(
            agent_id="custom_tb",
            tags=["linkedin"],
            artifact_family="social_post",
            allowed_workflows=["text_artifact_v1"],
        )
        user_reg.register(spec)

        ok, errors = user_reg.can_route_to("custom_tb", "text_artifact_v1")
        assert ok is True, f"Expected ok=True, got errors: {errors}"

    def test_custom_agent_blocked_when_role_incompatible(self) -> None:
        """A custom vangogh agent is blocked from text_artifact_v1."""
        user_reg = self._make_user_registry(
            "text_artifact_v1",
            allowed_agents=["research", "text_buddy", "governance"],
        )
        # Must declare allowed_workflows so the role gate fires
        spec = _vangogh_spec(agent_id="custom_vg")
        spec = spec.model_copy(update={"allowed_workflows": ["text_artifact_v1"]})
        user_reg.register(spec)

        ok, errors = user_reg.can_route_to("custom_vg", "text_artifact_v1")
        assert ok is False
        assert any("role" in err.lower() for err in errors)
