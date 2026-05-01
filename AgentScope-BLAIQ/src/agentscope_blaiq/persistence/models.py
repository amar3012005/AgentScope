from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, Boolean, Integer, Table, Column, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


JsonType = JSON().with_variant(Text(), "sqlite")

# M-M table for Workspace Memberships
workspace_members = Table(
    "workspace_members",
    Base.metadata,
    Column("workspace_id", String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String(64), ForeignKey("roles.id")),
    Column("joined_at", DateTime(timezone=True), default=utc_now),
)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sessions: Mapped[list["SessionRecord"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[list["ApiKeyRecord"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    workspaces: Mapped[list["WorkspaceRecord"]] = relationship(
        secondary=workspace_members, back_populates="members"
    )


class OrgRecord(Base):
    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), index=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    workspaces: Mapped[list["WorkspaceRecord"]] = relationship(back_populates="org", cascade="all, delete-orphan")


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    org: Mapped[OrgRecord] = relationship(back_populates="workspaces")
    members: Mapped[list[UserRecord]] = relationship(
        secondary=workspace_members, back_populates="workspaces"
    )
    policy_sets: Mapped[list["PolicySetRecord"]] = relationship(back_populates="workspace")


class RoleRecord(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)

    permissions: Mapped[list["PermissionRecord"]] = relationship(
        secondary="role_permissions", back_populates="roles"
    )


class PermissionRecord(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)

    roles: Mapped[list[RoleRecord]] = relationship(
        secondary="role_permissions", back_populates="permissions"
    )


class RolePermissionRecord(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[UserRecord] = relationship(back_populates="sessions")


class ApiKeyRecord(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    scopes_json: Mapped[str] = mapped_column(Text(), default="[]")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[UserRecord] = relationship(back_populates="api_keys")


# Control Plane Models
class PolicySetRecord(Base):
    __tablename__ = "policy_sets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    workspace: Mapped[WorkspaceRecord | None] = relationship(back_populates="policy_sets")
    rules: Mapped[list["PolicyRuleRecord"]] = relationship(back_populates="policy_set", cascade="all, delete-orphan")


class PolicyRuleRecord(Base):
    __tablename__ = "policy_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    policy_set_id: Mapped[str] = mapped_column(ForeignKey("policy_sets.id", ondelete="CASCADE"), index=True)
    rule_type: Mapped[str] = mapped_column(String(64))  # model_allow, tool_allow, data_retention
    effect: Mapped[str] = mapped_column(String(32), default="allow")  # allow, deny
    resource_pattern: Mapped[str] = mapped_column(String(255))  # gpt-4*, bing_search

    policy_set: Mapped[PolicySetRecord] = relationship(back_populates="rules")


class ModelRegistryRecord(Base):
    __tablename__ = "model_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    config_json: Mapped[str] = mapped_column(Text(), default="{}")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ToolRegistryRecord(Base):
    __tablename__ = "tool_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    manifest_json: Mapped[str] = mapped_column(Text())
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# Runtime / Conversation Models
class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    thread_id: Mapped[str | None] = mapped_column(ForeignKey("workflows.thread_id"), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    messages: Mapped[list["ConversationMessageRecord"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    workflow: Mapped[WorkflowRecord | None] = relationship(foreign_keys=[thread_id])

    __table_args__ = (
        Index("ix_conversations_workspace_user", "workspace_id", "user_id"),
    )


class ConversationMessageRecord(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    sender_type: Mapped[str] = mapped_column(String(32))  # user, agent, system
    sender_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text())
    metadata_json: Mapped[str] = mapped_column(Text(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    conversation: Mapped[ConversationRecord] = relationship(back_populates="messages")


# Agent Catalog Models
class AgentCatalogRecord(Base):
    __tablename__ = "agent_catalog"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(32))
    manifest_json: Mapped[str] = mapped_column(Text())
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    workspace: Mapped[WorkspaceRecord | None] = relationship(foreign_keys=[workspace_id])
    creator: Mapped[UserRecord | None] = relationship(foreign_keys=[created_by])

    __table_args__ = (
        Index("ix_agent_catalog_workspace_name", "workspace_id", "name"),
        UniqueConstraint("workspace_id", "name", "version", name="uq_agent_workspace_name_version"),
    )


# Memory / Document Models
class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    chunks: Mapped[list["DocumentChunkRecord"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    creator: Mapped[UserRecord | None] = relationship(foreign_keys=[user_id])


class DocumentChunkRecord(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text())
    embedding_json: Mapped[str | None] = mapped_column(Text(), nullable=True)

    document: Mapped[DocumentRecord] = relationship(back_populates="chunks")


# Audit Models
class AuditLogRecord(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details_json: Mapped[str] = mapped_column(Text(), default="{}")
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_audit_log_workspace_created", "workspace_id", "created_at"),
    )


class WorkflowRecord(Base):
    __tablename__ = "workflows"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    workflow_mode: Mapped[str] = mapped_column(String(32), default="hybrid")
    user_query: Mapped[str] = mapped_column(Text())
    current_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    workflow_plan_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    workflow_state_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    final_artifact_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    events: Mapped[list["WorkflowEventRecord"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class WorkflowEventRecord(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("workflows.thread_id"))
    sequence: Mapped[int] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(64))
    agent_name: Mapped[str] = mapped_column(String(64), default="system")
    payload_json: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_workflow_events_thread_sequence", "thread_id", "sequence"),
    )


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    agent_type: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    input_json: Mapped[str] = mapped_column(Text(), default="{}")
    output_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    html_path: Mapped[str] = mapped_column(String(255))
    css_path: Mapped[str] = mapped_column(String(255))
    artifact_json: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UploadRecord(Base):
    __tablename__ = "uploads"

    upload_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BrandDnaExtractionJobRecord(Base):
    __tablename__ = "brand_dna_extraction_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    upload_ids: Mapped[str] = mapped_column(Text())  # JSON list of strings
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued, running, succeeded, failed
    progress: Mapped[int] = mapped_column(default=0)
    intermediate_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class EvidencePackRecord(Base):
    __tablename__ = "evidence_packs"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    evidence_json: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


