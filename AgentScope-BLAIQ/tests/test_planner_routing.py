"""
Tests for Phase 7 planner routing: can_route_to, validate_draft_routing,
StrategicDraft.validate_routing, and cross-phase integration.
"""

from __future__ import annotations

import pytest

from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
from agentscope_blaiq.contracts.registry import HarnessRegistry, get_registry, reset_registry
from agentscope_blaiq.contracts.user_agent_registry import UserAgentRegistry

try:
    from agentscope_blaiq.agents.strategic import StrategicDraft
    _STRATEGIC_AVAILABLE = True
except ImportError:
    _STRATEGIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(**overrides: object) -> CustomAgentSpec:
    defaults: dict[str, object] = dict(
        agent_id="my_custom_agent",
        display_name="My Custom Agent",
        prompt="You are a helpful assistant that summarizes documents in detail.",
        role="text_buddy",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )
    defaults.update(overrides)
    return CustomAgentSpec(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_registry() -> HarnessRegistry:
    reset_registry()
    hr = get_registry()
    hr.load_builtin_workflows()
    return hr


@pytest.fixture()
def user_registry(fresh_registry: HarnessRegistry) -> UserAgentRegistry:
    return UserAgentRegistry(fresh_registry)


# ---------------------------------------------------------------------------
# TestCanRouteTo
# ---------------------------------------------------------------------------


class TestCanRouteTo:
    """Tests for UserAgentRegistry.can_route_to()."""

    def test_custom_agent_matching_workflow_passes(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A custom agent whose allowed_workflows includes the target workflow passes."""
        workflow_id = fresh_registry.list_workflow_ids()[0]
        spec = _make_spec(
            agent_id="route_ok_agent",
            allowed_workflows=[workflow_id],
        )
        user_registry.register(spec)

        ok, errors = user_registry.can_route_to("route_ok_agent", workflow_id)
        # The harness-level check may add errors if the workflow's allowed_agents
        # does not include the custom agent, but the *spec-level* workflow gate
        # should pass.  We verify the spec-level gate does not reject.
        workflow_gate_errors = [
            e for e in errors if "does not allow workflow" in e
        ]
        assert workflow_gate_errors == []

    def test_custom_agent_non_matching_workflow_rejected(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A custom agent whose allowed_workflows does NOT include the target is rejected."""
        workflow_ids = fresh_registry.list_workflow_ids()
        assert len(workflow_ids) >= 2, "Need at least two workflows for this test"
        allowed_wf = workflow_ids[0]
        target_wf = workflow_ids[1]

        spec = _make_spec(
            agent_id="restricted_agent",
            allowed_workflows=[allowed_wf],
        )
        user_registry.register(spec)

        ok, errors = user_registry.can_route_to("restricted_agent", target_wf)
        assert not ok
        assert any("does not allow workflow" in e for e in errors)

    def test_custom_agent_empty_allowed_workflows_accepts_any(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Empty allowed_workflows means the agent accepts any workflow (spec-level gate)."""
        workflow_id = fresh_registry.list_workflow_ids()[0]
        spec = _make_spec(
            agent_id="any_workflow_agent",
            allowed_workflows=[],
        )
        user_registry.register(spec)

        ok, errors = user_registry.can_route_to("any_workflow_agent", workflow_id)
        # The spec-level workflow gate should NOT produce an error.
        workflow_gate_errors = [
            e for e in errors if "does not allow workflow" in e
        ]
        assert workflow_gate_errors == []

    def test_unknown_agent_id_rejected(
        self, user_registry: UserAgentRegistry
    ) -> None:
        """An agent_id not in the user registry is immediately rejected."""
        ok, errors = user_registry.can_route_to("nonexistent_agent_xyz", "visual_artifact_v1")
        assert not ok
        assert any("not found" in e for e in errors)

    def test_builtin_agent_not_in_specs_rejected_gracefully(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Built-in agents are not in _specs, so can_route_to rejects them (they are
        validated through the harness registry elsewhere)."""
        builtin_id = list(fresh_registry.agents.keys())[0]
        ok, errors = user_registry.can_route_to(builtin_id, "visual_artifact_v1")
        assert not ok
        assert any("not found" in e for e in errors)


# ---------------------------------------------------------------------------
# TestValidateDraftRouting
# ---------------------------------------------------------------------------


class TestValidateDraftRouting:
    """Tests for UserAgentRegistry.validate_draft_routing()."""

    def test_draft_all_builtin_agents_passes(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A draft containing only built-in agent IDs is silently skipped (passes)."""
        builtin_ids = list(fresh_registry.agents.keys())[:2]
        assignments = {f"node_{i}": aid for i, aid in enumerate(builtin_ids)}
        workflow_id = fresh_registry.list_workflow_ids()[0]

        ok, errors = user_registry.validate_draft_routing(assignments, workflow_id)
        assert ok
        assert errors == []

    def test_draft_valid_custom_agent_passes(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A draft with a valid custom agent (output_schema non-empty) passes."""
        workflow_id = fresh_registry.list_workflow_ids()[0]
        spec = _make_spec(
            agent_id="valid_draft_agent",
            allowed_workflows=[],  # any workflow accepted
        )
        user_registry.register(spec)

        assignments = {"node_custom": "valid_draft_agent"}
        ok, errors = user_registry.validate_draft_routing(assignments, workflow_id)
        # The spec-level workflow gate passes (empty allowed_workflows).
        # The harness-level check may flag the agent not being in workflow.allowed_agents,
        # but the output_schema check should not fail since it's non-empty.
        output_schema_errors = [e for e in errors if "output_schema" in e]
        assert output_schema_errors == []

    def test_draft_invalid_custom_agent_fails(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A draft with a custom agent that has a non-matching workflow fails."""
        workflow_ids = fresh_registry.list_workflow_ids()
        assert len(workflow_ids) >= 2
        target_wf = workflow_ids[1]

        spec = _make_spec(
            agent_id="bad_route_agent",
            allowed_workflows=[workflow_ids[0]],  # only allows the first workflow
        )
        user_registry.register(spec)

        assignments = {"node_bad": "bad_route_agent"}
        ok, errors = user_registry.validate_draft_routing(assignments, target_wf)
        assert not ok
        assert any("does not allow workflow" in e for e in errors)

    def test_draft_mixing_builtin_and_custom_validates_only_custom(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Built-in agents are skipped; only custom agents are validated."""
        workflow_id = fresh_registry.list_workflow_ids()[0]
        builtin_id = list(fresh_registry.agents.keys())[0]

        spec = _make_spec(
            agent_id="mixed_custom",
            allowed_workflows=[],
        )
        user_registry.register(spec)

        assignments = {
            "node_builtin": builtin_id,
            "node_custom": "mixed_custom",
        }
        ok, errors = user_registry.validate_draft_routing(assignments, workflow_id)
        # No errors should mention the built-in agent.
        builtin_errors = [e for e in errors if builtin_id in e]
        assert builtin_errors == []

    def test_empty_draft_passes(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """An empty node_assignments mapping trivially passes."""
        workflow_id = fresh_registry.list_workflow_ids()[0]
        ok, errors = user_registry.validate_draft_routing({}, workflow_id)
        assert ok
        assert errors == []

    def test_custom_agent_empty_output_schema_fails(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A custom agent with an empty output_schema is flagged by validate_draft_routing."""
        workflow_id = fresh_registry.list_workflow_ids()[0]
        # Build a spec with a structurally valid but semantically empty output_schema.
        spec = _make_spec(
            agent_id="empty_output_agent",
            allowed_workflows=[],
            output_schema={"type": "object"},  # valid schema but no properties
        )
        reg = user_registry.register(spec)
        assert reg.harness_valid, reg.validation_errors

        # Manually clear the output_schema on the stored spec to simulate
        # an agent that declares no outputs.
        user_registry._specs["empty_output_agent"].output_schema.clear()  # noqa: SLF001

        assignments = {"node_empty": "empty_output_agent"}
        ok, errors = user_registry.validate_draft_routing(assignments, workflow_id)
        assert not ok
        assert any("output_schema" in e for e in errors)


# ---------------------------------------------------------------------------
# TestStrategicDraftValidation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _STRATEGIC_AVAILABLE, reason="agentscope not installed")
class TestStrategicDraftValidation:
    """Tests for StrategicDraft.validate_routing() classmethod."""

    def _make_draft(self, **overrides: object) -> StrategicDraft:
        from agentscope_blaiq.contracts.workflow import (  # noqa: PLC0415
            AnalysisMode,
            ArtifactFamily,
            TaskGraph,
            WorkflowMode,
        )

        defaults: dict[str, object] = dict(
            workflow_mode=WorkflowMode.hybrid,
            analysis_mode=AnalysisMode.standard,
            summary="Test draft summary.",
            task_count=0,
            artifact_family=ArtifactFamily.custom,
            task_graph=TaskGraph(),
            workflow_template_id="visual_artifact_v1",
            node_assignments={},
        )
        defaults.update(overrides)
        return StrategicDraft(**defaults)

    def test_empty_assignments_passes(
        self, user_registry: UserAgentRegistry
    ) -> None:
        draft = self._make_draft(node_assignments={})
        ok, errors = StrategicDraft.validate_routing(draft, user_registry)
        assert ok
        assert errors == []

    def test_builtin_agent_in_harness_passes(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Built-in agents present in the harness registry pass validation."""
        builtin_id = list(fresh_registry.agents.keys())[0]
        draft = self._make_draft(node_assignments={"node_0": builtin_id})
        ok, errors = StrategicDraft.validate_routing(draft, user_registry)
        assert ok, errors

    def test_builtin_agent_not_in_harness_fails(
        self, user_registry: UserAgentRegistry
    ) -> None:
        """A supposed built-in agent that doesn't exist in the harness registry fails."""
        draft = self._make_draft(node_assignments={"node_missing": "totally_fake_builtin"})
        ok, errors = StrategicDraft.validate_routing(draft, user_registry)
        assert not ok
        assert any("not found" in e for e in errors)

    def test_valid_custom_agent_passes(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A registered custom agent with compatible routing passes."""
        spec = _make_spec(
            agent_id="strategic_custom",
            allowed_workflows=[],
        )
        user_registry.register(spec)

        draft = self._make_draft(
            workflow_template_id="visual_artifact_v1",
            node_assignments={"node_c": "strategic_custom"},
        )
        ok, errors = StrategicDraft.validate_routing(draft, user_registry)
        # Spec-level workflow gate passes (empty allowed_workflows).
        # Output schema check passes (non-empty output_schema).
        output_errors = [e for e in errors if "output_schema" in e]
        workflow_gate_errors = [e for e in errors if "does not allow workflow" in e]
        assert output_errors == []
        assert workflow_gate_errors == []

    def test_invalid_custom_agent_fails(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """A custom agent that does not allow the draft's workflow fails."""
        spec = _make_spec(
            agent_id="wrong_wf_agent",
            allowed_workflows=["research_v1"],
        )
        user_registry.register(spec)

        draft = self._make_draft(
            workflow_template_id="text_artifact_v1",
            node_assignments={"node_wf": "wrong_wf_agent"},
        )
        ok, errors = StrategicDraft.validate_routing(draft, user_registry)
        assert not ok
        assert any("does not allow workflow" in e for e in errors)

    def test_mixed_builtin_and_custom(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Mixed draft: built-in passes, custom passes."""
        builtin_id = list(fresh_registry.agents.keys())[0]
        spec = _make_spec(
            agent_id="mixed_ok_agent",
            allowed_workflows=[],
        )
        user_registry.register(spec)

        draft = self._make_draft(
            node_assignments={
                "node_bi": builtin_id,
                "node_cu": "mixed_ok_agent",
            },
        )
        ok, errors = StrategicDraft.validate_routing(draft, user_registry)
        # No builtin errors, no output_schema errors.
        builtin_errors = [e for e in errors if builtin_id in e]
        output_errors = [e for e in errors if "output_schema" in e]
        assert builtin_errors == []
        assert output_errors == []


# ---------------------------------------------------------------------------
# TestCrossPhaseRouting
# ---------------------------------------------------------------------------


class TestCrossPhaseRouting:
    """Cross-phase integration: register -> draft assignment -> validate routing."""

    def test_register_then_validate_passes(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Register a custom agent, build a draft assignment, validate routing: passes."""
        workflow_id = fresh_registry.list_workflow_ids()[0]
        spec = _make_spec(
            agent_id="cross_phase_ok",
            allowed_workflows=[],
        )
        reg = user_registry.register(spec)
        assert reg.harness_valid, reg.validation_errors

        # Validate via validate_draft_routing.
        assignments = {"research_custom": "cross_phase_ok"}
        ok, errors = user_registry.validate_draft_routing(assignments, workflow_id)
        output_errors = [e for e in errors if "output_schema" in e]
        workflow_gate_errors = [e for e in errors if "does not allow workflow" in e]
        assert output_errors == []
        assert workflow_gate_errors == []

    def test_register_then_validate_fails_wrong_workflow(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Register a custom agent with restricted workflows, try wrong workflow: fails."""
        workflow_ids = fresh_registry.list_workflow_ids()
        assert len(workflow_ids) >= 2
        spec = _make_spec(
            agent_id="cross_phase_restricted",
            allowed_workflows=[workflow_ids[0]],
        )
        reg = user_registry.register(spec)
        assert reg.harness_valid, reg.validation_errors

        wrong_wf = workflow_ids[1]
        assignments = {"node_x": "cross_phase_restricted"}
        ok, errors = user_registry.validate_draft_routing(assignments, wrong_wf)
        assert not ok
        assert any("does not allow workflow" in e for e in errors)

    def test_deregister_then_validate_unknown(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """After deregistering a custom agent, validate_draft_routing skips it
        (it becomes neither custom nor built-in, so it's silently ignored by
        validate_draft_routing which only checks agents in _specs)."""
        spec = _make_spec(agent_id="ephemeral_agent", allowed_workflows=[])
        user_registry.register(spec)
        user_registry.deregister("ephemeral_agent")

        workflow_id = fresh_registry.list_workflow_ids()[0]
        assignments = {"node_gone": "ephemeral_agent"}
        ok, errors = user_registry.validate_draft_routing(assignments, workflow_id)
        # The agent is no longer in _specs, so it is skipped like a built-in.
        assert ok
        assert errors == []

    @pytest.mark.skipif(not _STRATEGIC_AVAILABLE, reason="agentscope not installed")
    def test_cross_phase_with_strategic_draft(
        self, user_registry: UserAgentRegistry, fresh_registry: HarnessRegistry
    ) -> None:
        """Full cross-phase: register agent -> build StrategicDraft -> validate_routing."""
        from agentscope_blaiq.contracts.workflow import (  # noqa: PLC0415
            AnalysisMode,
            ArtifactFamily,
            TaskGraph,
            WorkflowMode,
        )

        spec = _make_spec(
            agent_id="cross_strategic",
            allowed_workflows=[],
        )
        reg = user_registry.register(spec)
        assert reg.harness_valid, reg.validation_errors

        builtin_id = list(fresh_registry.agents.keys())[0]
        draft = StrategicDraft(
            workflow_mode=WorkflowMode.hybrid,
            analysis_mode=AnalysisMode.standard,
            summary="Cross-phase integration test.",
            task_count=2,
            artifact_family=ArtifactFamily.custom,
            task_graph=TaskGraph(),
            workflow_template_id="visual_artifact_v1",
            node_assignments={
                "node_builtin": builtin_id,
                "node_custom": "cross_strategic",
            },
        )
        ok, errors = StrategicDraft.validate_routing(draft, user_registry)
        # Built-in agent is in harness -> passes.
        # Custom agent has empty allowed_workflows and non-empty output_schema -> passes.
        builtin_errors = [e for e in errors if builtin_id in e]
        output_errors = [e for e in errors if "output_schema" in e]
        workflow_gate_errors = [e for e in errors if "does not allow workflow" in e]
        assert builtin_errors == []
        assert output_errors == []
        assert workflow_gate_errors == []
