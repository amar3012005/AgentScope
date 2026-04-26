from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_manifest_module():
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agentscope_blaiq"
        / "agents"
        / "custom"
        / "manifest.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_custom_manifest_module",
        manifest_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_custom_manifest_module"] = module
    spec.loader.exec_module(module)
    return module


_manifest_module = _load_manifest_module()
DEFAULT_MANIFEST_SCHEMA_VERSION = _manifest_module.DEFAULT_MANIFEST_SCHEMA_VERSION
CustomAgentManifest = _manifest_module.CustomAgentManifest
validate_custom_agent_manifest = _manifest_module.validate_custom_agent_manifest


def _manifest_payload(**overrides):
    payload = {
        "manifest_schema_version": DEFAULT_MANIFEST_SCHEMA_VERSION,
        "requires_runtime_version": ">=1.0.0",
        "requires_tool_ids": ["apply_brand_voice"],
        "requires_workflow_ids": ["text_artifact_v1"],
        "metadata": {
            "agent_id": "manifest_agent",
            "display_name": "Manifest Agent",
            "description": "Custom manifest test agent",
            "tags": ["custom", "manifest"],
        },
        "spec": {
            "role": "text_buddy",
            "prompt": "You are a custom manifest-driven agent for enterprise writing tasks.",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"result": {"type": "string"}}},
            "model_hint": "sonnet",
            "max_iterations": 6,
            "timeout_seconds": 120,
        },
        "contracts": {
            "agent_harness_ref": "contracts/custom_agents.py::CustomAgentSpec",
            "tool_contract_refs": ["contracts/harness.py::ToolHarness"],
            "workflow_contract_refs": ["contracts/workflow.py::WorkflowMode"],
        },
        "runtime": {
            "execution_mode": "async",
            "env": {"RUNTIME_REGION": "eu-central-1"},
            "feature_flags": {"enable_checks": True},
        },
        "tests": {
            "unit_test_ids": ["tests/test_custom_agent_manifest.py::test_valid_manifest"],
            "smoke_test_ids": [],
            "contract_test_ids": ["tests/test_custom_agents.py::TestValidateCustomAgentSpec::test_valid_spec_passes"],
        },
    }
    payload.update(overrides)
    return payload


def test_valid_manifest_constructs() -> None:
    manifest = CustomAgentManifest(**_manifest_payload())
    assert manifest.metadata.agent_id == "manifest_agent"
    assert manifest.manifest_schema_version == DEFAULT_MANIFEST_SCHEMA_VERSION


def test_manifest_schema_version_requires_prefix() -> None:
    with pytest.raises(Exception):
        CustomAgentManifest(**_manifest_payload(manifest_schema_version="v1"))


def test_requires_runtime_version_non_empty() -> None:
    with pytest.raises(Exception):
        CustomAgentManifest(**_manifest_payload(requires_runtime_version=""))


def test_compatibility_lists_must_not_contain_duplicates() -> None:
    with pytest.raises(Exception):
        CustomAgentManifest(
            **_manifest_payload(requires_tool_ids=["apply_brand_voice", "apply_brand_voice"])
        )


def test_validate_manifest_unknown_requirements_reported() -> None:
    manifest = CustomAgentManifest(**_manifest_payload())
    ok, errors = validate_custom_agent_manifest(
        manifest,
        known_tool_ids={"other_tool"},
        known_workflow_ids={"other_workflow"},
    )
    assert not ok
    assert any("unknown tool" in err for err in errors)
    assert any("unknown workflow" in err for err in errors)


def test_validate_manifest_known_requirements_pass() -> None:
    manifest = CustomAgentManifest(**_manifest_payload())
    ok, errors = validate_custom_agent_manifest(
        manifest,
        known_tool_ids={"apply_brand_voice"},
        known_workflow_ids={"text_artifact_v1"},
    )
    assert ok
    assert errors == []
