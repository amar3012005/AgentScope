from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


BUILTIN_PACKAGES = {
    "content_director": "ContentDirectorAgent",
    "research": "ResearchAgent",
    "strategic": "StrategicAgent",
    "vangogh": "VangoghAgent",
    "governance": "GovernanceAgent",
}


def test_builtin_agent_packages_have_standard_layout() -> None:
    agents_root = Path(__file__).resolve().parents[1] / "src" / "agentscope_blaiq" / "agents"

    for package_name in BUILTIN_PACKAGES:
        package_dir = agents_root / package_name
        assert package_dir.is_dir(), package_name
        assert (package_dir / "__init__.py").is_file()
        assert (package_dir / "agent.py").is_file()
        assert (package_dir / "models.py").is_file()
        assert (package_dir / "runtime.py").is_file()
        assert (package_dir / "tools" / "__init__.py").is_file()
        assert (package_dir / "prompts" / "__init__.py").is_file()


def test_registry_source_uses_role_based_factories() -> None:
    registry_source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agentscope_blaiq"
        / "runtime"
        / "registry.py"
    ).read_text(encoding="utf-8")

    assert "_builtin_agent_factories" in registry_source
    assert "def _builtin_agent_for_role" in registry_source
    assert '"strategist": lambda: self.strategist' in registry_source
    assert '"content_director": lambda: self.content_director' in registry_source
    assert '"research": lambda: self.research' in registry_source
    assert '"vangogh": lambda: self.vangogh' in registry_source
    assert '"governance": lambda: self.governance' in registry_source


def test_core_package_agents_are_not_legacy_wrappers() -> None:
    agents_root = Path(__file__).resolve().parents[1] / "src" / "agentscope_blaiq" / "agents"

    for package_name in BUILTIN_PACKAGES:
        agent_source = (agents_root / package_name / "agent.py").read_text(encoding="utf-8")
        assert "load_legacy_agent_module" not in agent_source
        assert "agentscope_blaiq.agents._compat" not in agent_source


def test_builtin_agent_packages_export_expected_classes() -> None:
    if importlib.util.find_spec("agentscope") is None:
        pytest.skip("agentscope is not installed in this environment")

    for package_name, class_name in BUILTIN_PACKAGES.items():
        package = importlib.import_module(f"agentscope_blaiq.agents.{package_name}")
        assert hasattr(package, class_name)


def test_registry_resolves_custom_agent_by_role() -> None:
    if importlib.util.find_spec("agentscope") is None:
        pytest.skip("agentscope is not installed in this environment")

    from agentscope_blaiq.runtime.registry import AgentRegistry

    registry = object.__new__(AgentRegistry)
    sentinel = object()
    registry._builtin_agents = {}
    registry._builtin_agent_factories = {"research": lambda: sentinel}
    registry._remote_profiles = {}
    registry.user_agent_registry = SimpleNamespace(
        get=lambda _agent_name: SimpleNamespace(
            role="research",
            display_name="Custom Research",
            prompt="You are a custom research agent.",
            agent_id="custom_research",
        )
    )

    agent = AgentRegistry.get_agent(registry, "custom_research")

    assert agent is sentinel
    assert getattr(agent, "name") == "Custom Research"
    assert getattr(agent, "role") == "research"
    assert getattr(agent, "sys_prompt") == "You are a custom research agent."
