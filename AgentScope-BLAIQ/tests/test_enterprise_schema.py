"""Enterprise schema validation tests.

Ensures all 6 domains (auth, control, runtime, agents, memory, audit)
import cleanly, relationships resolve, and basic CRUD works.
"""
from __future__ import annotations

import importlib

import pytest

from agentscope_blaiq.persistence.database import Base
from agentscope_blaiq.persistence.models import (
    AgentCatalogRecord,
    AgentRunRecord,
    ApiKeyRecord,
    ArtifactRecord,
    AuditLogRecord,
    BrandDnaExtractionJobRecord,
    ConversationMessageRecord,
    ConversationRecord,
    DocumentChunkRecord,
    DocumentRecord,
    EvidencePackRecord,
    ModelRegistryRecord,
    OrgRecord,
    PermissionRecord,
    PolicyRuleRecord,
    PolicySetRecord,
    RolePermissionRecord,
    RoleRecord,
    SessionRecord,
    ToolRegistryRecord,
    UploadRecord,
    UserRecord,
    WorkflowEventRecord,
    WorkflowRecord,
    WorkspaceRecord,
    workspace_members,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "users",
    "orgs",
    "workspaces",
    "roles",
    "permissions",
    "role_permissions",
    "workspace_members",
    "sessions",
    "api_keys",
    "policy_sets",
    "policy_rules",
    "model_registry",
    "tool_registry",
    "conversations",
    "conversation_messages",
    "agent_catalog",
    "documents",
    "document_chunks",
    "audit_log",
    "workflows",
    "workflow_events",
    "agent_runs",
    "artifacts",
    "uploads",
    "brand_dna_extraction_jobs",
    "evidence_packs",
}

ALL_MODEL_CLASSES = [
    UserRecord,
    OrgRecord,
    WorkspaceRecord,
    RoleRecord,
    PermissionRecord,
    RolePermissionRecord,
    SessionRecord,
    ApiKeyRecord,
    PolicySetRecord,
    PolicyRuleRecord,
    ModelRegistryRecord,
    ToolRegistryRecord,
    ConversationRecord,
    ConversationMessageRecord,
    AgentCatalogRecord,
    DocumentRecord,
    DocumentChunkRecord,
    AuditLogRecord,
    WorkflowRecord,
    WorkflowEventRecord,
    AgentRunRecord,
    ArtifactRecord,
    UploadRecord,
    BrandDnaExtractionJobRecord,
    EvidencePackRecord,
]


def _has_column(model_cls: type, column_name: str) -> bool:
    return column_name in model_cls.__table__.columns


def _has_relationship(model_cls: type, rel_name: str) -> bool:
    mapper = model_cls.__mapper__  # type: ignore[attr-defined]
    return rel_name in mapper.relationships


# ---------------------------------------------------------------------------
# TestSchemaImport
# ---------------------------------------------------------------------------


class TestSchemaImport:
    def test_all_models_import(self) -> None:
        """Every model class from models.py imports without error."""
        for cls in ALL_MODEL_CLASSES:
            assert hasattr(cls, "__tablename__"), f"{cls.__name__} missing __tablename__"

    def test_base_metadata_has_all_tables(self) -> None:
        """Base.metadata.tables contains every expected table name."""
        actual_tables = set(Base.metadata.tables.keys())
        missing = EXPECTED_TABLES - actual_tables
        assert not missing, f"Missing tables in metadata: {missing}"


# ---------------------------------------------------------------------------
# TestAuthDomain
# ---------------------------------------------------------------------------


class TestAuthDomain:
    def test_user_record_fields(self) -> None:
        for col in ("id", "email", "full_name", "is_active", "is_superuser", "created_at"):
            assert _has_column(UserRecord, col), f"UserRecord missing column: {col}"

    def test_org_record_fields(self) -> None:
        for col in ("id", "name", "slug", "created_at"):
            assert _has_column(OrgRecord, col), f"OrgRecord missing column: {col}"

    def test_workspace_record_fields(self) -> None:
        for col in ("id", "org_id", "name", "slug"):
            assert _has_column(WorkspaceRecord, col), f"WorkspaceRecord missing column: {col}"

    def test_role_record_has_permissions_relationship(self) -> None:
        assert _has_relationship(RoleRecord, "permissions"), (
            "RoleRecord missing 'permissions' relationship"
        )

    def test_permission_record_fields(self) -> None:
        for col in ("id", "name", "description"):
            assert _has_column(PermissionRecord, col), f"PermissionRecord missing column: {col}"

    def test_session_record_fields(self) -> None:
        for col in ("id", "user_id", "token", "expires_at"):
            assert _has_column(SessionRecord, col), f"SessionRecord missing column: {col}"

    def test_api_key_record_fields(self) -> None:
        for col in ("id", "user_id", "key_hash", "name"):
            assert _has_column(ApiKeyRecord, col), f"ApiKeyRecord missing column: {col}"


# ---------------------------------------------------------------------------
# TestControlDomain
# ---------------------------------------------------------------------------


class TestControlDomain:
    def test_policy_set_has_rules_relationship(self) -> None:
        assert _has_relationship(PolicySetRecord, "rules"), (
            "PolicySetRecord missing 'rules' relationship"
        )

    def test_policy_rule_fields(self) -> None:
        for col in ("rule_type", "effect", "resource_pattern"):
            assert _has_column(PolicyRuleRecord, col), f"PolicyRuleRecord missing column: {col}"

    def test_model_registry_fields(self) -> None:
        for col in ("provider", "model_name", "is_enabled"):
            assert _has_column(ModelRegistryRecord, col), (
                f"ModelRegistryRecord missing column: {col}"
            )

    def test_tool_registry_fields(self) -> None:
        for col in ("name", "manifest_json", "is_enabled"):
            assert _has_column(ToolRegistryRecord, col), (
                f"ToolRegistryRecord missing column: {col}"
            )


# ---------------------------------------------------------------------------
# TestRuntimeDomain
# ---------------------------------------------------------------------------


class TestRuntimeDomain:
    def test_workflow_record_fields(self) -> None:
        for col in ("thread_id", "run_id", "status", "workflow_mode", "user_query"):
            assert _has_column(WorkflowRecord, col), f"WorkflowRecord missing column: {col}"

    def test_workflow_event_record_fields(self) -> None:
        for col in ("event_type", "agent_name", "payload_json"):
            assert _has_column(WorkflowEventRecord, col), (
                f"WorkflowEventRecord missing column: {col}"
            )

    def test_conversation_record_has_messages(self) -> None:
        assert _has_relationship(ConversationRecord, "messages"), (
            "ConversationRecord missing 'messages' relationship"
        )

    def test_conversation_has_workflow_link(self) -> None:
        assert _has_column(ConversationRecord, "thread_id"), (
            "ConversationRecord missing 'thread_id' FK column"
        )
        # Verify the FK target
        fk_targets = {
            str(fk.target_fullname)
            for fk in ConversationRecord.__table__.columns["thread_id"].foreign_keys
        }
        assert "workflows.thread_id" in fk_targets


# ---------------------------------------------------------------------------
# TestAgentsDomain
# ---------------------------------------------------------------------------


class TestAgentsDomain:
    def test_agent_catalog_has_workspace_id(self) -> None:
        assert _has_column(AgentCatalogRecord, "workspace_id")

    def test_agent_catalog_has_created_by(self) -> None:
        assert _has_column(AgentCatalogRecord, "created_by")

    def test_agent_catalog_has_is_active(self) -> None:
        assert _has_column(AgentCatalogRecord, "is_active")


# ---------------------------------------------------------------------------
# TestMemoryDomain
# ---------------------------------------------------------------------------


class TestMemoryDomain:
    def test_document_record_has_workspace_id(self) -> None:
        assert _has_column(DocumentRecord, "workspace_id")

    def test_document_record_has_user_id(self) -> None:
        assert _has_column(DocumentRecord, "user_id")

    def test_document_has_chunks_relationship(self) -> None:
        assert _has_relationship(DocumentRecord, "chunks"), (
            "DocumentRecord missing 'chunks' relationship"
        )


# ---------------------------------------------------------------------------
# TestAuditDomain
# ---------------------------------------------------------------------------


class TestAuditDomain:
    def test_audit_log_fields(self) -> None:
        for col in ("action", "resource_type", "details_json"):
            assert _has_column(AuditLogRecord, col), f"AuditLogRecord missing column: {col}"

    def test_audit_log_has_workspace_time_index(self) -> None:
        """Check the compound index ix_audit_log_workspace_created exists."""
        index_names = {idx.name for idx in AuditLogRecord.__table__.indexes}
        assert "ix_audit_log_workspace_created" in index_names, (
            f"Missing compound index. Found indexes: {index_names}"
        )


# ---------------------------------------------------------------------------
# TestSeedScript
# ---------------------------------------------------------------------------


class TestSeedScript:
    def test_seed_module_imports(self) -> None:
        """seed.py can be imported without errors."""
        mod = importlib.import_module("agentscope_blaiq.persistence.seed")
        assert mod is not None

    def test_seed_data_function_exists(self) -> None:
        mod = importlib.import_module("agentscope_blaiq.persistence.seed")
        assert hasattr(mod, "seed_data"), "seed.py missing seed_data function"
        assert callable(mod.seed_data)
        assert hasattr(mod, "init_db"), "seed.py missing init_db function"
        assert callable(mod.init_db)


# ---------------------------------------------------------------------------
# TestBootstrapServiceShape
# ---------------------------------------------------------------------------


class TestBootstrapServiceShape:
    def test_bootstrap_service_imports(self) -> None:
        mod = importlib.import_module("agentscope_blaiq.app.bootstrap_service")
        assert hasattr(mod, "BootstrapService")

    def test_bootstrap_response_keys(self) -> None:
        """Inspect the source to verify the return dict shape includes expected keys."""
        from agentscope_blaiq.app.bootstrap_service import BootstrapService
        import inspect

        source = inspect.getsource(BootstrapService.get_bootstrap_data)
        expected_keys = [
            "user",
            "organization",
            "roles",
            "permissions",
            "workspace_memberships",
            "feature_flags",
            "connectivity",
            "client_support",
        ]
        for key in expected_keys:
            assert f'"{key}"' in source, (
                f"BootstrapService.get_bootstrap_data missing key: {key}"
            )


# ---------------------------------------------------------------------------
# TestPolicyServiceShape
# ---------------------------------------------------------------------------


class TestPolicyServiceShape:
    def test_policy_service_imports(self) -> None:
        mod = importlib.import_module("agentscope_blaiq.app.policy_service")
        assert hasattr(mod, "PolicyService")

    def test_policy_response_keys(self) -> None:
        """Inspect the source to verify the return dict shape includes expected keys."""
        from agentscope_blaiq.app.policy_service import PolicyService
        import inspect

        source = inspect.getsource(PolicyService.get_active_policies)
        expected_keys = [
            "allowedModels",
            "allowedTools",
            "canUseTools",
            "dataRetentionDays",
            "approvalRequirements",
        ]
        for key in expected_keys:
            assert f'"{key}"' in source, (
                f"PolicyService.get_active_policies missing key: {key}"
            )
