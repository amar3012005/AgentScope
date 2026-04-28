"""Declarative manifest schema for user-defined custom agents."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

_AGENT_ID_RE = re.compile(r"^[a-z0-9_]+$")
_MANIFEST_SCHEMA_PREFIX = "custom-agent-manifest/"

DEFAULT_MANIFEST_SCHEMA_VERSION = "custom-agent-manifest/v1"


def _validate_schema_object(name: str, value: dict[str, Any]) -> dict[str, Any]:
    if "type" not in value and "properties" not in value:
        raise ValueError(
            f"{name} must be a valid JSON Schema object with a 'type' or 'properties' key"
        )
    return value


def _validate_str_list(name: str, values: list[str]) -> list[str]:
    if any(not item.strip() for item in values):
        raise ValueError(f"{name} cannot contain empty values")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    return values


class CustomAgentManifestMetadata(BaseModel):
    agent_id: str
    display_name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, value: str) -> str:
        if not _AGENT_ID_RE.match(value):
            raise ValueError(
                "agent_id must be lowercase alphanumeric characters and underscores only"
            )
        return value

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must be non-empty")
        return value

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, values: list[str]) -> list[str]:
        return _validate_str_list("tags", values)


class CustomAgentManifestSpec(BaseModel):
    role: str
    prompt: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    artifact_family: str | None = None
    model_hint: str = "sonnet"
    max_iterations: int = 6
    timeout_seconds: int = 120

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("role must be non-empty")
        return value

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, value: str) -> str:
        if len(value.strip()) < 20:
            raise ValueError("prompt must be at least 20 characters")
        return value

    @field_validator("input_schema")
    @classmethod
    def _validate_input_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_schema_object("input_schema", value)

    @field_validator("output_schema")
    @classmethod
    def _validate_output_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_schema_object("output_schema", value)

    @field_validator("max_iterations")
    @classmethod
    def _validate_max_iterations(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_iterations must be >= 1")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("timeout_seconds must be > 0")
        return value


class CustomAgentManifestContracts(BaseModel):
    agent_harness_ref: str | None = None
    tool_contract_refs: list[str] = Field(default_factory=list)
    workflow_contract_refs: list[str] = Field(default_factory=list)

    @field_validator("tool_contract_refs")
    @classmethod
    def _validate_tool_contract_refs(cls, values: list[str]) -> list[str]:
        return _validate_str_list("tool_contract_refs", values)

    @field_validator("workflow_contract_refs")
    @classmethod
    def _validate_workflow_contract_refs(cls, values: list[str]) -> list[str]:
        return _validate_str_list("workflow_contract_refs", values)


class CustomAgentManifestRuntime(BaseModel):
    execution_mode: str = "async"
    env: dict[str, str] = Field(default_factory=dict)
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class CustomAgentManifestTests(BaseModel):
    unit_test_ids: list[str] = Field(default_factory=list)
    smoke_test_ids: list[str] = Field(default_factory=list)
    contract_test_ids: list[str] = Field(default_factory=list)

    @field_validator("unit_test_ids")
    @classmethod
    def _validate_unit_test_ids(cls, values: list[str]) -> list[str]:
        return _validate_str_list("unit_test_ids", values)

    @field_validator("smoke_test_ids")
    @classmethod
    def _validate_smoke_test_ids(cls, values: list[str]) -> list[str]:
        return _validate_str_list("smoke_test_ids", values)

    @field_validator("contract_test_ids")
    @classmethod
    def _validate_contract_test_ids(cls, values: list[str]) -> list[str]:
        return _validate_str_list("contract_test_ids", values)


class CustomAgentManifest(BaseModel):
    manifest_schema_version: str = DEFAULT_MANIFEST_SCHEMA_VERSION
    requires_runtime_version: str
    requires_tool_ids: list[str] = Field(default_factory=list)
    requires_workflow_ids: list[str] = Field(default_factory=list)
    metadata: CustomAgentManifestMetadata
    spec: CustomAgentManifestSpec
    contracts: CustomAgentManifestContracts
    runtime: CustomAgentManifestRuntime
    tests: CustomAgentManifestTests

    @field_validator("manifest_schema_version")
    @classmethod
    def _validate_manifest_schema_version(cls, value: str) -> str:
        if not value.startswith(_MANIFEST_SCHEMA_PREFIX):
            raise ValueError(
                f"manifest_schema_version must start with '{_MANIFEST_SCHEMA_PREFIX}'"
            )
        return value

    @field_validator("requires_runtime_version")
    @classmethod
    def _validate_runtime_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("requires_runtime_version must be non-empty")
        return value

    @field_validator("requires_tool_ids")
    @classmethod
    def _validate_requires_tool_ids(cls, values: list[str]) -> list[str]:
        return _validate_str_list("requires_tool_ids", values)

    @field_validator("requires_workflow_ids")
    @classmethod
    def _validate_requires_workflow_ids(cls, values: list[str]) -> list[str]:
        return _validate_str_list("requires_workflow_ids", values)


def validate_custom_agent_manifest(
    manifest: CustomAgentManifest,
    known_tool_ids: set[str] | None = None,
    known_workflow_ids: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """
    Validate compatibility references against optional known runtime sets.
    """
    errors: list[str] = []

    if known_tool_ids is not None:
        for tool_id in manifest.requires_tool_ids:
            if tool_id not in known_tool_ids:
                errors.append(f"requires_tool_ids references unknown tool '{tool_id}'")

    if known_workflow_ids is not None:
        for workflow_id in manifest.requires_workflow_ids:
            if workflow_id not in known_workflow_ids:
                errors.append(
                    f"requires_workflow_ids references unknown workflow '{workflow_id}'"
                )

    return len(errors) == 0, errors
