from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AgentStatus(str, Enum):
    ready = "ready"
    busy = "busy"
    degraded = "degraded"
    disabled = "disabled"


class AgentKind(str, Enum):
    builtin = "builtin"
    custom = "custom"
    remote = "remote"


class AgentTransport(str, Enum):
    local = "local"
    remote_a2a = "remote-a2a"


class RuntimeKind(str, Enum):
    react = "react"
    custom_base = "custom-base"
    a2a = "a2a"


class AgentCapability(BaseModel):
    name: str
    description: str
    supported_task_types: list[str] = Field(default_factory=list)
    supported_task_roles: list[str] = Field(default_factory=list)
    supported_artifact_families: list[str] = Field(default_factory=list)


class AgentSkill(BaseModel):
    name: str
    level: str = "core"


class AgentRuntimeFeatures(BaseModel):
    session_capable: bool = True
    planning_capable: bool = False
    structured_output_capable: bool = True
    interrupt_capable: bool = True
    tool_calling_capable: bool = True


class AgentExecutionMetadata(BaseModel):
    transport: AgentTransport = AgentTransport.local
    runtime_kind: RuntimeKind = RuntimeKind.react
    endpoint_ref: str | None = None
    agent_card_ref: str | None = None
    model: str | None = None


class AgentGovernanceMetadata(BaseModel):
    approval_required: bool = False
    approval_mode: str = "none"
    visibility: str = "tenant"
    tenant_scope: str = "tenant"
    safety_class: str = "standard"


class AgentSourceMetadata(BaseModel):
    source: str = "builtin"
    raw: dict[str, Any] = Field(default_factory=dict)


class LiveAgentProfile(BaseModel):
    profile_id: str = ""
    name: str
    role: str
    description: str = ""
    agent_kind: AgentKind = AgentKind.builtin
    transport: AgentTransport = AgentTransport.local
    runtime_kind: RuntimeKind = RuntimeKind.react
    tags: list[str] = Field(default_factory=list)
    artifact_affinities: list[str] = Field(default_factory=list)
    is_custom: bool = False
    status: AgentStatus = AgentStatus.ready
    model: str | None = None
    capabilities: list[AgentCapability] = Field(default_factory=list)
    skills: list[AgentSkill] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    current_load: float = 0.0
    current_stage: str | None = None
    last_seen: str | None = None
    planner_roles: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    runtime_features: AgentRuntimeFeatures = Field(default_factory=AgentRuntimeFeatures)
    execution: AgentExecutionMetadata = Field(default_factory=AgentExecutionMetadata)
    governance: AgentGovernanceMetadata = Field(default_factory=AgentGovernanceMetadata)
    source_metadata: AgentSourceMetadata = Field(default_factory=AgentSourceMetadata)
    profile_document: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_profile_defaults(self) -> LiveAgentProfile:
        if not self.profile_id:
            self.profile_id = self.name
        if self.is_custom:
            self.agent_kind = AgentKind.custom
        if self.agent_kind == AgentKind.remote:
            self.transport = AgentTransport.remote_a2a
            self.runtime_kind = RuntimeKind.a2a
        self.execution.transport = self.transport
        self.execution.runtime_kind = self.runtime_kind
        self.execution.model = self.model
        return self

    @property
    def capability_names(self) -> list[str]:
        return [cap.name for cap in self.capabilities]

    @property
    def skill_names(self) -> list[str]:
        return [skill.name for skill in self.skills]

    def routing_index(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "agent_kind": self.agent_kind.value,
            "transport": self.transport.value,
            "runtime_kind": self.runtime_kind.value,
            "role": self.role,
            "status": self.status.value,
            "current_load": self.current_load,
            "capability_names": self.capability_names,
            "skill_names": self.skill_names,
            "tool_ids": list(self.tools),
            "artifact_affinities": list(self.artifact_affinities),
        }


class AgentTaskAssignment(BaseModel):
    task_id: str
    agent_name: str
    role: str
    reason: str
    parallel_group: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    task_role: str | None = None
    executor_kind: str = "agent"
    task_graph_node_id: str | None = None
    requires_approval: bool = False
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
