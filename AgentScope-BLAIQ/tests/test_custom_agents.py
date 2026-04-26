"""
Tests for custom agent onboarding: registration, validation, deregistration,
built-in shadowing prevention, tool restriction enforcement.
"""

from __future__ import annotations

import pytest

from agentscope_blaiq.contracts.custom_agents import (
    CustomAgentSpec,
    CustomAgentRegistration,
    validate_custom_agent_spec,
    spec_to_harness,
)
from agentscope_blaiq.contracts.user_agent_registry import UserAgentRegistry
from agentscope_blaiq.contracts.registry import HarnessRegistry, get_registry, reset_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(**overrides) -> CustomAgentSpec:
    defaults = dict(
        agent_id="my_custom_agent",
        display_name="My Custom Agent",
        prompt="You are a helpful assistant that summarizes documents in detail.",
        role="text_buddy",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )
    defaults.update(overrides)
    return CustomAgentSpec(**defaults)


@pytest.fixture()
def fresh_registry():
    reset_registry()
    hr = get_registry()
    return hr


@pytest.fixture()
def user_registry(fresh_registry):
    return UserAgentRegistry(fresh_registry)


# ---------------------------------------------------------------------------
# TestCustomAgentSpec — schema validation
# ---------------------------------------------------------------------------

class TestCustomAgentSpec:
    def test_valid_spec_constructs(self):
        spec = _make_spec()
        assert spec.agent_id == "my_custom_agent"

    def test_agent_id_regex_rejects_uppercase(self):
        with pytest.raises(Exception):
            _make_spec(agent_id="MyAgent")

    def test_agent_id_regex_rejects_spaces(self):
        with pytest.raises(Exception):
            _make_spec(agent_id="my agent")

    def test_agent_id_regex_allows_underscores_digits(self):
        spec = _make_spec(agent_id="my_agent_99")
        assert spec.agent_id == "my_agent_99"

    def test_prompt_min_length_enforced(self):
        with pytest.raises(Exception):
            _make_spec(prompt="Too short")

    def test_defaults_applied(self):
        spec = _make_spec()
        assert spec.model_hint == "sonnet"
        assert spec.max_iterations == 6
        assert spec.timeout_seconds == 120
        assert spec.allowed_tools == []
        assert spec.tags == []

    def test_input_schema_must_have_type_or_properties(self):
        with pytest.raises(Exception):
            _make_spec(input_schema={"description": "no type or properties"})

    def test_input_schema_with_properties_key_is_valid(self):
        spec = _make_spec(input_schema={"properties": {"q": {"type": "string"}}})
        assert spec.input_schema is not None


# ---------------------------------------------------------------------------
# TestValidateCustomAgentSpec — cross-registry validation
# ---------------------------------------------------------------------------

class TestValidateCustomAgentSpec:
    def test_valid_spec_passes(self, fresh_registry):
        spec = _make_spec()
        ok, errors = validate_custom_agent_spec(spec, fresh_registry)
        assert ok
        assert errors == []

    def test_unknown_tool_rejected(self, fresh_registry):
        spec = _make_spec(allowed_tools=["nonexistent_tool_xyz"])
        ok, errors = validate_custom_agent_spec(spec, fresh_registry)
        assert not ok
        assert any("nonexistent_tool_xyz" in e for e in errors)

    def test_unknown_workflow_rejected(self, fresh_registry):
        spec = _make_spec(allowed_workflows=["fake_workflow_v99"])
        ok, errors = validate_custom_agent_spec(spec, fresh_registry)
        assert not ok
        assert any("fake_workflow_v99" in e for e in errors)

    def test_builtin_agent_id_rejected(self, fresh_registry):
        # strategist is a built-in agent
        spec = _make_spec(agent_id="strategist")
        ok, errors = validate_custom_agent_spec(spec, fresh_registry)
        assert not ok
        assert any("built-in" in e.lower() or "strategist" in e for e in errors)

    def test_known_tool_allowed(self, fresh_registry):
        # Use a real built-in tool from the harness registry
        tool_id = list(fresh_registry.tools.keys())[0]
        spec = _make_spec(allowed_tools=[tool_id])
        ok, errors = validate_custom_agent_spec(spec, fresh_registry)
        assert ok, errors

    def test_known_workflow_allowed(self, fresh_registry):
        fresh_registry.load_builtin_workflows()
        workflow_id = list(fresh_registry.workflows.keys())[0]
        spec = _make_spec(allowed_workflows=[workflow_id])
        ok, errors = validate_custom_agent_spec(spec, fresh_registry)
        assert ok, errors


# ---------------------------------------------------------------------------
# TestSpecToHarness — conversion
# ---------------------------------------------------------------------------

class TestSpecToHarness:
    def test_harness_has_correct_agent_id(self):
        spec = _make_spec()
        harness = spec_to_harness(spec)
        assert harness.agent_id == spec.agent_id

    def test_harness_description_contains_display_name(self):
        spec = _make_spec()
        harness = spec_to_harness(spec)
        assert spec.display_name in harness.description

    def test_harness_allowed_tools_populated(self):
        spec = _make_spec(allowed_tools=["some_tool"])
        harness = spec_to_harness(spec)
        assert "some_tool" in harness.allowed_tools

    def test_harness_allowed_workflows_populated(self):
        spec = _make_spec(allowed_workflows=["research_v1"])
        harness = spec_to_harness(spec)
        assert "research_v1" in harness.allowed_workflows

    def test_harness_description_contains_model_hint(self):
        spec = _make_spec()
        harness = spec_to_harness(spec)
        # model_hint embedded in description string by spec_to_harness
        assert "model_hint=" in harness.description


# ---------------------------------------------------------------------------
# TestUserAgentRegistry — register / deregister / list
# ---------------------------------------------------------------------------

class TestUserAgentRegistry:
    def test_register_valid_spec_succeeds(self, user_registry):
        spec = _make_spec()
        reg = user_registry.register(spec)
        assert isinstance(reg, CustomAgentRegistration)
        assert reg.harness_valid
        assert reg.agent_id == spec.agent_id
        assert reg.validation_errors == []

    def test_registered_agent_retrievable(self, user_registry):
        spec = _make_spec()
        user_registry.register(spec)
        retrieved = user_registry.get(spec.agent_id)
        assert retrieved is not None
        assert retrieved.agent_id == spec.agent_id

    def test_register_invalid_spec_returns_invalid_registration(self, user_registry):
        spec = _make_spec(allowed_tools=["completely_fake_tool_abc"])
        reg = user_registry.register(spec)
        assert not reg.harness_valid
        assert reg.validation_errors

    def test_register_invalid_spec_does_not_persist(self, user_registry):
        spec = _make_spec(agent_id="invalid_agent_zzz", allowed_tools=["completely_fake_tool_abc"])
        user_registry.register(spec)
        assert user_registry.get("invalid_agent_zzz") is None

    def test_deregister_known_agent(self, user_registry):
        spec = _make_spec()
        user_registry.register(spec)
        removed = user_registry.deregister(spec.agent_id)
        assert removed is True
        assert user_registry.get(spec.agent_id) is None

    def test_deregister_unknown_agent_returns_false(self, user_registry):
        removed = user_registry.deregister("nonexistent_xyz")
        assert removed is False

    def test_deregister_builtin_agent_returns_false(self, user_registry, fresh_registry):
        builtin_id = list(fresh_registry.agents.keys())[0]
        removed = user_registry.deregister(builtin_id)
        assert removed is False

    def test_list_ids_includes_registered(self, user_registry):
        spec = _make_spec()
        user_registry.register(spec)
        ids = user_registry.list_ids()
        assert spec.agent_id in ids

    def test_list_all_returns_specs(self, user_registry):
        spec = _make_spec()
        user_registry.register(spec)
        all_specs = user_registry.list_all()
        agent_ids = [s.agent_id for s in all_specs]
        assert spec.agent_id in agent_ids

    def test_multiple_agents_registered(self, user_registry):
        specs = [
            _make_spec(agent_id="agent_alpha"),
            _make_spec(agent_id="agent_beta"),
            _make_spec(agent_id="agent_gamma"),
        ]
        for s in specs:
            reg = user_registry.register(s)
            assert reg.harness_valid
        ids = user_registry.list_ids()
        for s in specs:
            assert s.agent_id in ids

    def test_builtin_shadowing_prevented(self, user_registry, fresh_registry):
        builtin_id = list(fresh_registry.agents.keys())[0]
        spec = _make_spec(agent_id=builtin_id)
        reg = user_registry.register(spec)
        assert not reg.harness_valid
        assert any(builtin_id in e or "built-in" in e.lower() for e in reg.validation_errors)

    def test_tool_restriction_in_harness(self, user_registry, fresh_registry):
        tool_id = list(fresh_registry.tools.keys())[0]
        spec = _make_spec(allowed_tools=[tool_id])
        reg = user_registry.register(spec)
        assert reg.harness_valid
        harness = fresh_registry.agents.get(spec.agent_id)
        assert harness is not None
        assert tool_id in harness.allowed_tools
