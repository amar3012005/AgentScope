from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_custom_modules():
    custom_dir = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agentscope_blaiq"
        / "agents"
        / "custom"
    )
    package_name = "_custom_manifest_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(custom_dir)]  # type: ignore[attr-defined]
    sys.modules[package_name] = package

    manifest_spec = importlib.util.spec_from_file_location(
        f"{package_name}.manifest",
        custom_dir / "manifest.py",
    )
    assert manifest_spec is not None and manifest_spec.loader is not None
    manifest_module = importlib.util.module_from_spec(manifest_spec)
    sys.modules[f"{package_name}.manifest"] = manifest_module
    manifest_spec.loader.exec_module(manifest_module)

    store_spec = importlib.util.spec_from_file_location(
        f"{package_name}.store",
        custom_dir / "store.py",
    )
    assert store_spec is not None and store_spec.loader is not None
    store_module = importlib.util.module_from_spec(store_spec)
    sys.modules[f"{package_name}.store"] = store_module
    store_spec.loader.exec_module(store_module)

    return manifest_module, store_module


_manifest_module, _store_module = _load_custom_modules()
DEFAULT_MANIFEST_SCHEMA_VERSION = _manifest_module.DEFAULT_MANIFEST_SCHEMA_VERSION
CustomAgentManifest = _manifest_module.CustomAgentManifest
InMemoryCustomAgentManifestStore = _store_module.InMemoryCustomAgentManifestStore
PersistentCustomAgentManifestStore = _store_module.PersistentCustomAgentManifestStore


def _manifest(agent_id: str = "store_agent") -> CustomAgentManifest:
    return CustomAgentManifest(
        manifest_schema_version=DEFAULT_MANIFEST_SCHEMA_VERSION,
        requires_runtime_version=">=1.0.0",
        requires_tool_ids=[],
        requires_workflow_ids=[],
        metadata={"agent_id": agent_id, "display_name": "Store Agent", "tags": []},
        spec={
            "role": "text_buddy",
            "prompt": "You are a custom manifest-backed agent for testing persistence flows.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        },
        contracts={},
        runtime={},
        tests={},
    )


def test_in_memory_store_round_trip() -> None:
    store = InMemoryCustomAgentManifestStore()
    manifest = _manifest()

    store.upsert(manifest)

    assert store.get("store_agent") is not None
    assert len(store.list()) == 1


def test_in_memory_delete_returns_false_for_unknown() -> None:
    store = InMemoryCustomAgentManifestStore()
    assert store.delete("missing_agent") is False


def test_in_memory_delete_removes_manifest() -> None:
    store = InMemoryCustomAgentManifestStore()
    manifest = _manifest()
    store.upsert(manifest)

    deleted = store.delete(manifest.metadata.agent_id)

    assert deleted is True
    assert store.get(manifest.metadata.agent_id) is None


def test_persistent_store_register_and_get() -> None:
    store = PersistentCustomAgentManifestStore()
    manifest = _manifest("persistent_agent")
    ok, errors = store.register(manifest, version="1.0.0")
    assert ok is True
    assert errors == []
    assert store.get("persistent_agent") is not None
