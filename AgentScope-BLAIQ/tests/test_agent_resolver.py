"""Tests for the typed, scored agent resolver.

Covers: AgentCandidate qualification, role matching, custom preference,
artifact affinity, capability checks, scoring order, and the module-level
convenience function.
"""
from __future__ import annotations

import pytest

from agentscope_blaiq.contracts.agent_catalog import (
    AgentCapability,
    AgentStatus,
    LiveAgentProfile,
)
from agentscope_blaiq.contracts.resolver import (
    AgentCandidate,
    AgentResolver,
    ResolverResult,
    resolve_agent,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_profile(
    name: str,
    role: str,
    *,
    capabilities: list[AgentCapability] | None = None,
    tools: list[str] | None = None,
    status: AgentStatus = AgentStatus.ready,
    is_custom: bool = False,
    tags: list[str] | None = None,
    artifact_affinities: list[str] | None = None,
) -> LiveAgentProfile:
    """Build a LiveAgentProfile with optional new typed fields.

    The ``is_custom``, ``tags``, and ``artifact_affinities`` fields are
    being added to LiveAgentProfile by another milestone.  We attach them
    dynamically so the tests remain valid both before and after that
    migration lands.
    """
    profile = LiveAgentProfile(
        name=name,
        role=role,
        status=status,
        capabilities=capabilities or [],
        tools=tools or [],
    )
    # Attach typed fields that M2 is adding to LiveAgentProfile
    object.__setattr__(profile, "is_custom", is_custom)
    object.__setattr__(profile, "tags", tags or [])
    object.__setattr__(profile, "artifact_affinities", artifact_affinities or [])
    return profile


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


# ── TestAgentCandidate ────────────────────────────────────────────────


class TestAgentCandidate:
    def test_qualified_when_no_disqualify(self) -> None:
        candidate = AgentCandidate(
            agent_name="agent-a",
            role="research",
            score=0.5,
            is_custom=False,
            match_reasons=["role match: research"],
            disqualify_reasons=[],
        )
        assert candidate.qualified is True

    def test_not_qualified_when_disqualified(self) -> None:
        candidate = AgentCandidate(
            agent_name="agent-b",
            role="vangogh",
            score=0.3,
            is_custom=False,
            match_reasons=[],
            disqualify_reasons=["role mismatch: agent has 'vangogh', need 'research'"],
        )
        assert candidate.qualified is False

    def test_not_qualified_when_score_zero(self) -> None:
        candidate = AgentCandidate(
            agent_name="agent-c",
            role="research",
            score=0.0,
            is_custom=False,
            match_reasons=[],
            disqualify_reasons=[],
        )
        assert candidate.qualified is False


# ── TestAgentResolverRoleMatch ────────────────────────────────────────


class TestAgentResolverRoleMatch:
    def setup_method(self) -> None:
        self.resolver = AgentResolver()

    def test_selects_agent_with_matching_role(self) -> None:
        agents = [
            _make_profile("research-1", "research", capabilities=[_cap("web_research")]),
            _make_profile("vangogh-1", "vangogh", capabilities=[_cap("artifact_layout")]),
        ]
        result = self.resolver.resolve(agents, required_role="research")
        assert result.selected == "research-1"
        assert result.fallback_used is False

    def test_rejects_agent_with_wrong_role(self) -> None:
        agents = [
            _make_profile("vangogh-1", "vangogh", capabilities=[_cap("artifact_layout")]),
        ]
        result = self.resolver.resolve(
            agents, required_role="research", default_agent="fallback"
        )
        assert result.selected == "fallback"
        assert result.fallback_used is True
        # The vangogh agent should be disqualified
        assert len(result.candidates) == 1
        assert result.candidates[0].qualified is False

    def test_fallback_when_no_role_match(self) -> None:
        result = self.resolver.resolve(
            [], required_role="governance", default_agent="default-gov"
        )
        assert result.selected == "default-gov"
        assert result.fallback_used is True
        assert result.candidates == []

    def test_capability_role_match_accepted(self) -> None:
        """An agent whose capability declares a supported_task_role should still qualify."""
        agents = [
            _make_profile(
                "flex-agent",
                "multi",
                capabilities=[_cap("web_research", task_roles=["research"])],
            ),
        ]
        result = self.resolver.resolve(agents, required_role="research")
        assert result.selected == "flex-agent"
        assert result.fallback_used is False


# ── TestAgentResolverCustomPreference ─────────────────────────────────


class TestAgentResolverCustomPreference:
    def setup_method(self) -> None:
        self.resolver = AgentResolver()

    def test_custom_preferred_over_builtin_same_role(self) -> None:
        agents = [
            _make_profile(
                "builtin-cd",
                "content_director",
                capabilities=[_cap("content_distribution")],
                is_custom=False,
            ),
            _make_profile(
                "custom-cd",
                "content_director",
                capabilities=[_cap("content_distribution")],
                is_custom=True,
            ),
        ]
        result = self.resolver.resolve(agents, required_role="content_director")
        assert result.selected == "custom-cd"

    def test_builtin_used_when_no_custom(self) -> None:
        agents = [
            _make_profile(
                "builtin-cd",
                "content_director",
                capabilities=[_cap("content_distribution")],
                is_custom=False,
            ),
        ]
        result = self.resolver.resolve(agents, required_role="content_director")
        assert result.selected == "builtin-cd"
        assert result.fallback_used is False


# ── TestAgentResolverArtifactAffinity ─────────────────────────────────


class TestAgentResolverArtifactAffinity:
    def setup_method(self) -> None:
        self.resolver = AgentResolver()

    def test_agent_with_artifact_affinity_scores_higher(self) -> None:
        generic = _make_profile(
            "generic-tb",
            "text_buddy",
            capabilities=[_cap("text_composition")],
        )
        specialist = _make_profile(
            "email-tb",
            "text_buddy",
            capabilities=[_cap("text_composition")],
            artifact_affinities=["email"],
        )
        result = self.resolver.resolve(
            [generic, specialist],
            required_role="text_buddy",
            artifact_family="email",
        )
        assert result.selected == "email-tb"
        specialist_cand = next(
            c for c in result.candidates if c.agent_name == "email-tb"
        )
        generic_cand = next(
            c for c in result.candidates if c.agent_name == "generic-tb"
        )
        assert specialist_cand.score > generic_cand.score

    def test_agent_with_tag_affinity_scores_higher(self) -> None:
        generic = _make_profile(
            "generic-tb",
            "text_buddy",
            capabilities=[_cap("text_composition")],
        )
        tagged = _make_profile(
            "social-tb",
            "text_buddy",
            capabilities=[_cap("text_composition")],
            tags=["social_post", "linkedin"],
        )
        result = self.resolver.resolve(
            [generic, tagged],
            required_role="text_buddy",
            artifact_family="social_post",
        )
        assert result.selected == "social-tb"

    def test_capability_artifact_family_scores_higher(self) -> None:
        generic = _make_profile(
            "generic-tb",
            "text_buddy",
            capabilities=[_cap("text_composition")],
        )
        cap_specialist = _make_profile(
            "proposal-tb",
            "text_buddy",
            capabilities=[
                _cap("text_composition", artifact_families=["proposal"])
            ],
        )
        result = self.resolver.resolve(
            [generic, cap_specialist],
            required_role="text_buddy",
            artifact_family="proposal",
        )
        assert result.selected == "proposal-tb"

    def test_no_affinity_still_selects_by_role(self) -> None:
        agents = [
            _make_profile(
                "basic-tb",
                "text_buddy",
                capabilities=[_cap("text_composition")],
            ),
        ]
        result = self.resolver.resolve(
            agents,
            required_role="text_buddy",
            artifact_family="invoice",
        )
        assert result.selected == "basic-tb"
        assert result.fallback_used is False


# ── TestAgentResolverCapabilities ─────────────────────────────────────


class TestAgentResolverCapabilities:
    def setup_method(self) -> None:
        self.resolver = AgentResolver()

    def test_missing_capability_disqualifies(self) -> None:
        agents = [
            _make_profile(
                "agent-no-cap",
                "content_director",
                capabilities=[_cap("content_distribution")],
            ),
        ]
        result = self.resolver.resolve(
            agents,
            required_role="content_director",
            required_capabilities=["content_distribution", "section_planning"],
            default_agent="fallback-cd",
        )
        assert result.selected == "fallback-cd"
        assert result.fallback_used is True
        assert result.candidates[0].qualified is False

    def test_all_capabilities_present_qualifies(self) -> None:
        agents = [
            _make_profile(
                "full-cd",
                "content_director",
                capabilities=[
                    _cap("content_distribution"),
                    _cap("section_planning"),
                ],
            ),
        ]
        result = self.resolver.resolve(
            agents,
            required_role="content_director",
            required_capabilities=["content_distribution", "section_planning"],
        )
        assert result.selected == "full-cd"
        assert result.fallback_used is False
        cand = result.candidates[0]
        assert cand.qualified is True
        assert cand.score >= 0.5  # role (0.3) + caps (0.2)


# ── TestAgentResolverScoring ──────────────────────────────────────────


class TestAgentResolverScoring:
    def setup_method(self) -> None:
        self.resolver = AgentResolver()

    def test_scoring_order_role_caps_affinity_custom(self) -> None:
        """Verify the additive scoring: role > caps > affinity > custom."""
        agent = _make_profile(
            "super-agent",
            "text_buddy",
            capabilities=[_cap("text_composition")],
            artifact_affinities=["email"],
            is_custom=True,
        )
        result = self.resolver.resolve(
            [agent],
            required_role="text_buddy",
            required_capabilities=["text_composition"],
            artifact_family="email",
        )
        cand = result.candidates[0]
        assert cand.qualified is True
        # role(0.3) + caps(0.2) + affinity(0.2) + custom(0.05) = 0.75
        assert cand.score == pytest.approx(0.75, abs=0.01)

    def test_multiple_custom_agents_best_affinity_wins(self) -> None:
        generic_custom = _make_profile(
            "custom-generic",
            "text_buddy",
            capabilities=[_cap("text_composition")],
            is_custom=True,
        )
        affinity_custom = _make_profile(
            "custom-email",
            "text_buddy",
            capabilities=[_cap("text_composition")],
            artifact_affinities=["email"],
            is_custom=True,
        )
        result = self.resolver.resolve(
            [generic_custom, affinity_custom],
            required_role="text_buddy",
            artifact_family="email",
        )
        # Both are custom, but affinity_custom has artifact_affinities bonus
        assert result.selected == "custom-email"

    def test_tool_bonus_applied(self) -> None:
        with_tools = _make_profile(
            "agent-tools",
            "research",
            capabilities=[_cap("web_research")],
            tools=["tavily", "browser"],
        )
        without_tools = _make_profile(
            "agent-no-tools",
            "research",
            capabilities=[_cap("web_research")],
            tools=[],
        )
        result = self.resolver.resolve(
            [with_tools, without_tools],
            required_role="research",
            required_tools=["tavily"],
        )
        t_cand = next(c for c in result.candidates if c.agent_name == "agent-tools")
        nt_cand = next(c for c in result.candidates if c.agent_name == "agent-no-tools")
        assert t_cand.score > nt_cand.score


# ── TestResolveAgentFunction ──────────────────────────────────────────


class TestResolveAgentFunction:
    def test_module_level_function_works(self) -> None:
        agents = [
            _make_profile(
                "gov-1",
                "governance",
                capabilities=[_cap("artifact_validation")],
            ),
        ]
        result = resolve_agent(
            agents,
            required_role="governance",
            default_agent="default-gov",
        )
        assert isinstance(result, ResolverResult)
        assert result.selected == "gov-1"
        assert result.fallback_used is False

    def test_module_level_with_empty_candidates(self) -> None:
        result = resolve_agent(
            [],
            required_role="research",
            default_agent="fallback-research",
        )
        assert result.selected == "fallback-research"
        assert result.fallback_used is True
