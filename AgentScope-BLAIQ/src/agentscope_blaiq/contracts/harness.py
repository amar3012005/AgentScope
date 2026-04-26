"""
Agent and Tool harness definitions.

Contract layer for multi-agent system. Defines explicit harnesses for agents, tools, and workflows.
No execution logic here—only type definitions and constraints.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# ============================================================================
# Enums
# ============================================================================

class RetryStrategy(str, Enum):
    """Retry behavior on failure."""
    no_retry = "no_retry"
    exponential = "exponential"
    linear = "linear"
    once = "once"


class FailureMode(str, Enum):
    """Explicit failure modes for agents."""
    missing_input = "missing_input"
    invalid_schema = "invalid_schema"
    timeout = "timeout"
    tool_not_found = "tool_not_found"
    weak_evidence = "weak_evidence"
    low_confidence = "low_confidence"
    workflow_mismatch = "workflow_mismatch"
    governance_failed = "governance_failed"
    unknown = "unknown"


class RecoveryAction(str, Enum):
    """Action on failure."""
    ask_hitl = "ask_hitl"
    replan = "replan"
    rerun = "rerun"
    use_fallback = "use_fallback"
    abort = "abort"


# ============================================================================
# Retry Policy
# ============================================================================

class RetryPolicy(BaseModel):
    """Retry configuration for agents and tools."""
    strategy: RetryStrategy = RetryStrategy.exponential
    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    backoff_factor: float = 2.0
    retry_on_timeout: bool = True
    retry_on_rate_limit: bool = True


# ============================================================================
# Agent Harness
# ============================================================================

class AgentHarness(BaseModel):
    """Formal contract for an agent."""
    # Identity
    agent_id: str = Field(..., description="e.g., 'strategist'")
    role: str = Field(..., description="Human-readable role")
    description: str = Field(default="", description="What this agent does")

    # I/O
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for inputs"
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for outputs"
    )

    # Context
    required_context: list[str] = Field(
        default_factory=list,
        description="e.g., ['user_request', 'agent_catalog']"
    )
    optional_context: list[str] = Field(
        default_factory=list,
        description="e.g., ['evidence', 'memory']"
    )

    # Constraints
    allowed_workflows: list[str] = Field(
        default_factory=list,
        description="Workflows this agent can participate in"
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tools this agent is allowed to call"
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Other agents this depends on"
    )

    # Runtime
    timeout_seconds: int = Field(default=60, ge=1)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    max_retries: int = Field(default=3, ge=0)

    # Failure modes and recovery
    failure_modes: dict[FailureMode, RecoveryAction] = Field(
        default_factory=dict,
        description="How to handle each failure mode"
    )

    # Governance
    approval_gate: Optional[str] = Field(
        default=None,
        description="Optional approval agent (e.g., 'governance')"
    )
    requires_approval: bool = Field(default=False)

    # Artifact families this agent produces
    artifact_families: list[str] = Field(
        default_factory=list,
        description="e.g., ['pitch_deck', 'email']"
    )


# ============================================================================
# Tool Harness
# ============================================================================

class ToolHarness(BaseModel):
    """Formal contract for a tool."""
    # Identity
    tool_id: str = Field(..., description="e.g., 'email_generator'")
    owner_agent: str = Field(..., description="Primary owning agent")
    purpose: str = Field(..., description="What this tool does")
    description: str = Field(default="")

    # I/O
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for inputs"
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for outputs"
    )

    # Constraints
    allowed_agents: list[str] = Field(
        default_factory=list,
        description="Agents allowed to call this tool"
    )
    allowed_workflows: list[str] = Field(
        default_factory=list,
        description="Workflows this tool can be used in"
    )

    # Behavior
    side_effects: list[str] = Field(
        default_factory=list,
        description="e.g., ['updates_memory', 'writes_artifact']"
    )
    idempotent: bool = Field(
        default=False,
        description="Safe to retry without side effects"
    )

    # Runtime
    timeout_seconds: int = Field(default=30, ge=1)
    max_parallel_calls: int = Field(default=1, ge=1)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)

    # Validation
    validation_rules: dict[str, str] = Field(
        default_factory=dict,
        description="e.g., {'email_count': 'must_be_1'}"
    )

    # Governance
    requires_approval: bool = Field(default=False)
    approval_agent: Optional[str] = Field(default=None)


# ============================================================================
# Workflow Node
# ============================================================================

class Node(BaseModel):
    """Single node in a workflow DAG."""
    node_id: str = Field(..., description="Unique within workflow")
    agent_id: str = Field(default="", description="Agent to execute at this node (legacy — use required_role)")
    required_role: str = Field(default="", description="Role this node needs (e.g. 'text_buddy', 'research')")
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="Capabilities the assigned agent must have",
    )
    input_from: list[str] = Field(
        default_factory=list,
        description="Node IDs or 'start' that feed into this"
    )
    output_to: list[str] = Field(
        default_factory=list,
        description="Node IDs that consume this output"
    )
    required_tools: list[str] = Field(
        default_factory=list,
        description="Tools required at this node"
    )
    approval_gate: Optional[str] = Field(
        default=None,
        description="Optional approval agent"
    )
    timeout_seconds: int = Field(default=60, ge=1)
    parallel_group: Optional[str] = Field(
        default=None,
        description="For grouping parallel nodes"
    )
    conditional_branches: Optional[dict[str, str]] = Field(
        default=None,
        description="e.g., {'success': 'next_node', 'failed': 'hitl'}"
    )

    @model_validator(mode="after")
    def _fill_role_from_agent_id(self) -> Node:
        """Auto-fill required_role from agent_id when required_role is empty."""
        if not self.required_role and self.agent_id:
            self.required_role = self.agent_id
        return self

    def accepts_agent(self, agent_role: str, agent_capabilities: list[str] | None = None) -> bool:
        """Check if an agent with the given role and capabilities can fill this node.

        Role-based: matches if agent_role == self.required_role.
        Legacy: matches if agent_role == self.agent_id (backward compat).
        Capabilities: if required_capabilities is set, agent must have all of them.
        """
        role_match = (
            agent_role == self.required_role
            or agent_role == self.agent_id  # legacy compat
        )
        if not role_match:
            return False
        if self.required_capabilities and agent_capabilities is not None:
            return all(cap in agent_capabilities for cap in self.required_capabilities)
        return True


# ============================================================================
# Workflow Template
# ============================================================================

class WorkflowTemplate(BaseModel):
    """Predefined workflow for a task family."""
    # Identity
    workflow_id: str = Field(..., description="e.g., 'text_artifact_v1'")
    purpose: str = Field(..., description="What this workflow does")
    version: str = Field(default="v1")
    description: str = Field(default="")

    # Entry conditions
    entry_conditions: dict[str, str] = Field(
        default_factory=dict,
        description="e.g., {'task_family': 'text_generation'}"
    )

    # DAG
    nodes: list[Node] = Field(
        default_factory=list,
        description="Directed acyclic graph nodes"
    )

    # Constraints
    allowed_agents: list[str] = Field(
        default_factory=list,
        description="Agents allowed in this workflow (legacy — use allowed_roles)"
    )
    allowed_roles: list[str] = Field(
        default_factory=list,
        description="Roles allowed in this workflow",
    )
    required_handoffs: list[tuple[str, str]] = Field(
        default_factory=list,
        description="e.g., [('strategist', 'research'), ('research', 'content_director')]"
    )
    approval_gates: list[str] = Field(
        default_factory=list,
        description="e.g., ['governance']"
    )

    # Recovery
    fallback_branches: dict[str, str] = Field(
        default_factory=dict,
        description="e.g., {'weak_evidence': 'replan', 'timeout': 'abort'}"
    )

    # Metadata
    artifact_families: list[str] = Field(
        default_factory=list,
        description="Artifact families this workflow produces"
    )

    @model_validator(mode="after")
    def _fill_roles_from_agents(self) -> WorkflowTemplate:
        """Auto-fill allowed_roles from allowed_agents when allowed_roles is empty."""
        if not self.allowed_roles and self.allowed_agents:
            self.allowed_roles = list(set(self.allowed_agents))
        return self

    def accepts_role(self, role: str) -> bool:
        """Check if a role is allowed in this workflow.

        Checks allowed_roles first, falls back to allowed_agents for compat.
        """
        if self.allowed_roles:
            return role in self.allowed_roles
        return role in self.allowed_agents


# ============================================================================
# Built-in Examples
# ============================================================================

# Retry policies
RETRY_AGGRESSIVE = RetryPolicy(
    strategy=RetryStrategy.exponential,
    max_attempts=3,
    initial_delay_seconds=1.0,
)

RETRY_CONSERVATIVE = RetryPolicy(
    strategy=RetryStrategy.once,
    max_attempts=1,
)

# ============================================================================
# All canonical workflow IDs (referenced by harnesses)
# ============================================================================

ALL_VISUAL_WORKFLOWS = ["visual_artifact_v1"]
ALL_TEXT_WORKFLOWS = ["text_artifact_v1"]
ALL_RESEARCH_WORKFLOWS = ["research_v1", "direct_answer_v1"]
ALL_FINANCE_WORKFLOWS = ["finance_v1"]
ALL_DATA_SCIENCE_WORKFLOWS = ["data_science_v1"]
ALL_WORKFLOWS = (
    ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS + ALL_RESEARCH_WORKFLOWS
    + ALL_FINANCE_WORKFLOWS + ALL_DATA_SCIENCE_WORKFLOWS
)


WORKFLOW_TEMPLATE_ID_ALIASES: dict[str, str] = {
    "visual_artifact": "visual_artifact_v1",
    "text_artifact": "text_artifact_v1",
    "direct_answer": "direct_answer_v1",
    "research": "research_v1",
    "finance": "finance_v1",
    "data_science": "data_science_v1",
}


def canonicalize_workflow_template_id(workflow_id: Optional[str]) -> Optional[str]:
    """Return canonical workflow template ID for validation checks."""
    if workflow_id is None:
        return None
    normalized = workflow_id.strip().lower()
    if not normalized:
        return None
    return WORKFLOW_TEMPLATE_ID_ALIASES.get(normalized, normalized)

# ============================================================================
# Agent Harnesses — aligned with runtime/registry.py LiveAgentProfile names
# ============================================================================

STRATEGIST_HARNESS = AgentHarness(
    agent_id="strategist",
    role="Task classifier and workflow router",
    description="Analyze user request, select workflow template, assign agents, build task graph",
    input_schema={
        "type": "object",
        "properties": {
            "user_request": {"type": "string"},
            "agent_catalog": {"type": "array", "items": {"type": "object"}},
            "workflow_templates": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["user_request"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "string"},
            "query": {"type": "string"},
            "source_scope": {"type": "string"},
            "workflow_plan": {"type": "object"},
            "task_graph": {"type": "object"},
            "agent_assignments": {"type": "array"},
            "missing_requirements": {"type": "array"},
            "topology_reason": {"type": "string"},
        },
        "required": ["workflow_id", "query", "workflow_plan"],
    },
    allowed_workflows=ALL_WORKFLOWS,
    allowed_tools=[
        "list_live_agents", "match_agent_capabilities",
        "compose_execution_strategy", "classify_artifact_family",
        "derive_artifact_requirements", "compute_missing_requirements",
        "compose_task_graph",
    ],
    timeout_seconds=30,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.missing_input: RecoveryAction.ask_hitl,
        FailureMode.timeout: RecoveryAction.rerun,
    },
    artifact_families=[],
)

HITL_HARNESS = AgentHarness(
    agent_id="hitl",
    role="Human-in-the-loop clarification",
    description="Transform missing requirements into natural language questions for the user",
    input_schema={
        "type": "object",
        "properties": {
            "missing_requirements": {"type": "array", "items": {"type": "object"}},
            "evidence_summary": {"type": "string"},
            "workflow_family": {"type": "string"},
        },
        "required": ["missing_requirements"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "clarification_prompt": {"type": "string"},
            "question_list": {"type": "array"},
            "user_responses": {"type": "object"},
        },
        "required": ["clarification_prompt"],
    },
    allowed_workflows=ALL_WORKFLOWS,
    allowed_tools=["clarify_requirements"],
    timeout_seconds=3600,
    retry_policy=RETRY_CONSERVATIVE,
    failure_modes={
        FailureMode.timeout: RecoveryAction.abort,
    },
    artifact_families=[],
)

HUMAN_HARNESS = AgentHarness(
    agent_id="human",
    role="Human approval checkpoint",
    description="Represents a human-in-the-loop approval/review node in staged workflows",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "context": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "answers": {"type": "object"},
            "notes": {"type": "string"},
        },
    },
    allowed_workflows=ALL_WORKFLOWS,
    allowed_tools=[],
    timeout_seconds=3600,
    retry_policy=RETRY_CONSERVATIVE,
    failure_modes={
        FailureMode.timeout: RecoveryAction.abort,
    },
    artifact_families=[],
)

RESEARCH_HARNESS = AgentHarness(
    agent_id="research",
    role="Evidence gathering and synthesis",
    description="Recall memory, search web, collect evidence, normalize provenance",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "source_scope": {"type": "string"},
            "memory_chain_id": {"type": "string"},
            "tenant_id": {"type": "string"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "evidence_pack": {"type": "object"},
        },
        "required": ["evidence_pack"],
    },
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS + ALL_RESEARCH_WORKFLOWS,
    allowed_tools=[
        "hivemind_recall", "hivemind_query_with_ai", "hivemind_get_memory",
        "hivemind_traverse_graph", "hivemind_web_search", "hivemind_web_crawl",
        "hivemind_web_job_status", "hivemind_web_usage", "validate_document_path",
    ],
    timeout_seconds=120,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.weak_evidence: RecoveryAction.rerun,
        FailureMode.timeout: RecoveryAction.rerun,
    },
    artifact_families=[],
)

DEEP_RESEARCH_HARNESS = AgentHarness(
    agent_id="deep_research",
    role="Deep tree-search research",
    description="Decompose queries into sub-questions, research each via HIVE-MIND and web",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "source_scope": {"type": "string"},
            "max_depth": {"type": "integer"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "evidence_pack": {"type": "object"},
        },
        "required": ["evidence_pack"],
    },
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS + ALL_RESEARCH_WORKFLOWS,
    allowed_tools=[
        "hivemind_recall", "hivemind_query_with_ai", "hivemind_web_search",
    ],
    dependencies=["research"],
    timeout_seconds=180,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.weak_evidence: RecoveryAction.rerun,
        FailureMode.timeout: RecoveryAction.replan,
    },
    artifact_families=[],
)

FINANCE_RESEARCH_HARNESS = AgentHarness(
    agent_id="finance_research",
    role="Hypothesis-driven finance research",
    description="Finance research with hypothesis verification workflow",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "analysis_objective": {"type": "string"},
            "analysis_horizon": {"type": "string"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "evidence_pack": {"type": "object"},
        },
        "required": ["evidence_pack"],
    },
    allowed_workflows=ALL_FINANCE_WORKFLOWS + ALL_VISUAL_WORKFLOWS,
    allowed_tools=[
        "hivemind_recall", "hivemind_query_with_ai", "hivemind_web_search",
    ],
    dependencies=["research"],
    timeout_seconds=180,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.weak_evidence: RecoveryAction.rerun,
        FailureMode.timeout: RecoveryAction.replan,
    },
    artifact_families=["finance_analysis", "report"],
)

DATA_SCIENCE_HARNESS = AgentHarness(
    agent_id="data_science",
    role="Autonomous data analysis",
    description="Process uploads, execute sandboxed Python, generate statistical reports",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "upload_paths": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "report_html": {"type": "string"},
            "visualizations": {"type": "array"},
            "insights": {"type": "array"},
        },
        "required": ["report_html"],
    },
    allowed_workflows=ALL_DATA_SCIENCE_WORKFLOWS,
    allowed_tools=[
        "data_upload", "sandbox_execute", "statistical_test", "generate_visualization",
    ],
    timeout_seconds=300,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.timeout: RecoveryAction.replan,
    },
    artifact_families=["report", "finance_analysis"],
)

CONTENT_DIRECTOR_HARNESS = AgentHarness(
    agent_id="content_director",
    role="Content structure and narrative planning",
    description="Map evidence to sections, select template, generate render brief",
    input_schema={
        "type": "object",
        "properties": {
            "artifact_spec": {
                "type": "object",
                "properties": {
                    "family": {"type": "string"},
                    "title": {"type": "string"},
                    "audience": {"type": "string"},
                    "tone": {"type": "string"},
                    "required_sections": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["family"],
            },
            "requirements_checklist": {"type": "object"},
            "evidence_pack": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "sources": {"type": "array"},
                    "memory_findings": {"type": "array"},
                    "web_findings": {"type": "array"},
                    "doc_findings": {"type": "array"},
                },
                "required": ["sources"],
            },
        },
        "required": ["artifact_spec", "evidence_pack"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "artifact_brief": {
                "type": "object",
                "properties": {
                    "brief_id": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "artifact_family": {"type": "string"},
                    "title": {"type": "string"},
                    "core_narrative": {"type": "string"},
                    "target_audience": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section_id": {"type": "string"},
                                "title": {"type": "string"},
                                "objective": {"type": "string"},
                                "key_points": {"type": "array", "items": {"type": "string"}},
                                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                                "visual_hint": {"type": "string"},
                                "constraints": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["section_id", "title", "objective", "evidence_refs"],
                        },
                    },
                    "evidence_pack_id": {"type": "string"},
                },
                "required": [
                    "brief_id",
                    "thread_id",
                    "artifact_family",
                    "title",
                    "core_narrative",
                    "target_audience",
                    "sections",
                    "evidence_pack_id",
                ],
            },
            "content_brief": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "family": {"type": "string"},
                    "narrative": {"type": "string"},
                    "section_plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section_id": {"type": "string"},
                                "title": {"type": "string"},
                                "objective": {"type": "string"},
                                "audience": {"type": "string"},
                                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                                "visual_intent": {"type": "string"},
                                "acceptance_checks": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["section_id", "title", "objective", "evidence_refs", "visual_intent"],
                        },
                    },
                },
                "required": ["title", "family", "section_plan"],
            },
            "slides_data": {"type": "object"},
        },
        "required": ["artifact_brief"],
    },
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS,
    allowed_tools=[
        "content_distribution", "section_planning",
        "template_selection", "render_brief_generation",
    ],
    timeout_seconds=60,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.weak_evidence: RecoveryAction.replan,
    },
    artifact_families=[],
)

TEXT_BUDDY_HARNESS = AgentHarness(
    agent_id="text_buddy",
    role="Text artifact generation",
    description="Generate final text in brand voice using templates",
    input_schema={
        "type": "object",
        "properties": {
            "artifact_family": {"type": "string", "description": "One of TEXT_ARTIFACT_FAMILIES"},
            "user_query": {"type": "string"},
            "evidence_pack": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "sources": {"type": "array"},
                    "memory_findings": {"type": "array"},
                    "web_findings": {"type": "array"},
                    "doc_findings": {"type": "array"},
                    "citations": {"type": "array"},
                },
                "required": ["sources"],
            },
            "brand_voice": {"type": "string"},
            "hitl_answers": {"type": "object"},
        },
        "required": ["artifact_family", "user_query", "evidence_pack"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string"},
            "family": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "template_used": {"type": "string"},
            "brand_voice_applied": {"type": "boolean"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "governance_status": {"type": "string", "enum": ["pending", "approved", "rejected"]},
            "uncited_claims": {"type": "array", "items": {"type": "string"}, "description": "Claims without citation — must be explicitly listed"},
        },
        "required": ["artifact_id", "family", "title", "content", "evidence_refs", "governance_status"],
    },
    allowed_workflows=ALL_TEXT_WORKFLOWS,
    allowed_tools=["apply_brand_voice", "select_template", "format_output"],
    timeout_seconds=60,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.invalid_schema: RecoveryAction.rerun,
    },
    artifact_families=["email", "invoice", "letter", "memo", "proposal", "social_post", "summary"],
)

VANGOGH_HARNESS = AgentHarness(
    agent_id="vangogh",
    role="Visual artifact rendering",
    description="Render final visual artifact with brand DNA, layout, visual hierarchy",
    input_schema={
        "type": "object",
        "properties": {
            "artifact_brief": {
                "type": "object",
                "properties": {
                    "brief_id": {"type": "string"},
                    "title": {"type": "string"},
                    "artifact_family": {"type": "string"},
                    "sections": {"type": "array"},
                },
                "required": ["title", "sections"],
            },
            "content_brief": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "family": {"type": "string"},
                    "section_plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section_id": {"type": "string"},
                                "title": {"type": "string"},
                            },
                            "required": ["section_id", "title"],
                        },
                    },
                },
                "required": ["title", "section_plan"],
            },
            "artifact_family": {"type": "string"},
            "brand_dna": {"type": "object"},
            "evidence_pack": {
                "type": "object",
                "properties": {
                    "citations": {"type": "array"},
                },
            },
        },
        "anyOf": [
            {"required": ["artifact_brief", "artifact_family"]},
            {"required": ["content_brief", "artifact_family"]},
        ],
    },
    output_schema={
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string"},
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_id": {"type": "string"},
                        "section_index": {"type": "integer"},
                        "title": {"type": "string"},
                        "html_fragment": {"type": "string"},
                    },
                    "required": ["section_id", "section_index", "title", "html_fragment"],
                },
                "description": "Must map 1:1 to content_brief.section_plan sections",
            },
            "html": {"type": "string"},
            "css": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "preview_metadata": {"type": "object"},
        },
        "required": ["artifact_id", "title", "sections", "html", "evidence_refs"],
    },
    allowed_workflows=ALL_VISUAL_WORKFLOWS,
    allowed_tools=["artifact_contract"],
    timeout_seconds=90,
    retry_policy=RETRY_AGGRESSIVE,
    failure_modes={
        FailureMode.invalid_schema: RecoveryAction.rerun,
        FailureMode.governance_failed: RecoveryAction.rerun,
    },
    artifact_families=[
        "pitch_deck", "keynote", "poster", "brochure",
        "one_pager", "landing_page", "report", "finance_analysis",
    ],
)

GOVERNANCE_HARNESS = AgentHarness(
    agent_id="governance",
    role="Artifact validation and approval",
    description="Validate completeness, check evidence linkage, approve or reject",
    input_schema={
        "type": "object",
        "properties": {
            "artifact": {"type": "object"},
            "evidence_pack": {"type": "object"},
        },
        "required": ["artifact"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "approval_status": {"type": "string", "enum": ["approved", "rejected", "needs_revision"]},
            "issues": {"type": "array", "items": {"type": "object"}},
            "score": {"type": "number"},
        },
        "required": ["approval_status"],
    },
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS,
    allowed_tools=["validate_visual_artifact"],
    timeout_seconds=30,
    retry_policy=RETRY_CONSERVATIVE,
    failure_modes={
        FailureMode.governance_failed: RecoveryAction.replan,
    },
    artifact_families=[],
)


# ============================================================================
# Tool Harnesses — aligned with runtime/registry.py LiveAgentProfile.tools
# ============================================================================

# --- Strategist tools ---
LIST_LIVE_AGENTS_TOOL = ToolHarness(
    tool_id="list_live_agents",
    owner_agent="strategist",
    purpose="List available agents with status and capabilities",
    allowed_agents=["strategist"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

MATCH_AGENT_CAPABILITIES_TOOL = ToolHarness(
    tool_id="match_agent_capabilities",
    owner_agent="strategist",
    purpose="Match task requirements to agent capabilities",
    allowed_agents=["strategist"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

COMPOSE_EXECUTION_STRATEGY_TOOL = ToolHarness(
    tool_id="compose_execution_strategy",
    owner_agent="strategist",
    purpose="Compose execution strategy (sequential/parallel/hybrid)",
    allowed_agents=["strategist"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

CLASSIFY_ARTIFACT_FAMILY_TOOL = ToolHarness(
    tool_id="classify_artifact_family",
    owner_agent="strategist",
    purpose="Classify user request into artifact family",
    allowed_agents=["strategist"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

DERIVE_ARTIFACT_REQUIREMENTS_TOOL = ToolHarness(
    tool_id="derive_artifact_requirements",
    owner_agent="strategist",
    purpose="Derive requirements from artifact spec",
    allowed_agents=["strategist"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

COMPUTE_MISSING_REQUIREMENTS_TOOL = ToolHarness(
    tool_id="compute_missing_requirements",
    owner_agent="strategist",
    purpose="Compute missing requirements from checklist",
    allowed_agents=["strategist"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

COMPOSE_TASK_GRAPH_TOOL = ToolHarness(
    tool_id="compose_task_graph",
    owner_agent="strategist",
    purpose="Build ordered task graph from agent assignments",
    allowed_agents=["strategist"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

# --- HITL tools ---
CLARIFY_REQUIREMENTS_TOOL = ToolHarness(
    tool_id="clarify_requirements",
    owner_agent="hitl",
    purpose="Frame missing requirements as user questions",
    allowed_agents=["hitl"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

# --- Research tools ---
HIVEMIND_RECALL_TOOL = ToolHarness(
    tool_id="hivemind_recall",
    owner_agent="research",
    purpose="Recall information from HIVE-MIND memory",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "results": {"type": "array"},
        },
    },
    allowed_agents=["research", "deep_research", "finance_research"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

HIVEMIND_QUERY_WITH_AI_TOOL = ToolHarness(
    tool_id="hivemind_query_with_ai",
    owner_agent="research",
    purpose="AI-powered query over HIVE-MIND memory",
    allowed_agents=["research", "deep_research", "finance_research"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=15,
)

HIVEMIND_GET_MEMORY_TOOL = ToolHarness(
    tool_id="hivemind_get_memory",
    owner_agent="research",
    purpose="Get specific memory by ID from HIVE-MIND",
    allowed_agents=["research"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

HIVEMIND_TRAVERSE_GRAPH_TOOL = ToolHarness(
    tool_id="hivemind_traverse_graph",
    owner_agent="research",
    purpose="Traverse linked memories and historical decisions",
    allowed_agents=["research"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

HIVEMIND_WEB_SEARCH_TOOL = ToolHarness(
    tool_id="hivemind_web_search",
    owner_agent="research",
    purpose="Live web search for freshness verification",
    allowed_agents=["research", "deep_research", "finance_research"],
    allowed_workflows=ALL_WORKFLOWS,
    side_effects=["external_api_call"],
    idempotent=True,
    timeout_seconds=15,
)

HIVEMIND_WEB_CRAWL_TOOL = ToolHarness(
    tool_id="hivemind_web_crawl",
    owner_agent="research",
    purpose="Crawl and extract content from URLs",
    allowed_agents=["research"],
    allowed_workflows=ALL_WORKFLOWS,
    side_effects=["external_api_call"],
    idempotent=True,
    timeout_seconds=30,
)

HIVEMIND_WEB_JOB_STATUS_TOOL = ToolHarness(
    tool_id="hivemind_web_job_status",
    owner_agent="research",
    purpose="Check status of web crawl jobs",
    allowed_agents=["research"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

HIVEMIND_WEB_USAGE_TOOL = ToolHarness(
    tool_id="hivemind_web_usage",
    owner_agent="research",
    purpose="Check web search usage and quotas",
    allowed_agents=["research"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

VALIDATE_DOCUMENT_PATH_TOOL = ToolHarness(
    tool_id="validate_document_path",
    owner_agent="research",
    purpose="Validate uploaded document paths before processing",
    allowed_agents=["research"],
    allowed_workflows=ALL_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

# --- Data Science tools ---
DATA_UPLOAD_TOOL = ToolHarness(
    tool_id="data_upload",
    owner_agent="data_science",
    purpose="Process uploaded CSV, Excel, and JSON files",
    allowed_agents=["data_science"],
    allowed_workflows=ALL_DATA_SCIENCE_WORKFLOWS,
    side_effects=["writes_temp_files"],
    idempotent=False,
    timeout_seconds=30,
)

SANDBOX_EXECUTE_TOOL = ToolHarness(
    tool_id="sandbox_execute",
    owner_agent="data_science",
    purpose="Execute Python code in secure Docker sandbox",
    allowed_agents=["data_science"],
    allowed_workflows=ALL_DATA_SCIENCE_WORKFLOWS,
    side_effects=["executes_code", "writes_temp_files"],
    idempotent=False,
    timeout_seconds=60,
)

STATISTICAL_TEST_TOOL = ToolHarness(
    tool_id="statistical_test",
    owner_agent="data_science",
    purpose="Run statistical tests on data",
    allowed_agents=["data_science"],
    allowed_workflows=ALL_DATA_SCIENCE_WORKFLOWS,
    idempotent=True,
    timeout_seconds=30,
)

GENERATE_VISUALIZATION_TOOL = ToolHarness(
    tool_id="generate_visualization",
    owner_agent="data_science",
    purpose="Generate charts and plots",
    allowed_agents=["data_science"],
    allowed_workflows=ALL_DATA_SCIENCE_WORKFLOWS,
    side_effects=["writes_temp_files"],
    idempotent=True,
    timeout_seconds=30,
)

# --- Content Director tools ---
CONTENT_DISTRIBUTION_TOOL = ToolHarness(
    tool_id="content_distribution",
    owner_agent="content_director",
    purpose="Map requirements into section-by-section content plan",
    allowed_agents=["content_director"],
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

SECTION_PLANNING_TOOL = ToolHarness(
    tool_id="section_planning",
    owner_agent="content_director",
    purpose="Plan content sections and their ordering",
    allowed_agents=["content_director"],
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

TEMPLATE_SELECTION_TOOL = ToolHarness(
    tool_id="template_selection",
    owner_agent="content_director",
    purpose="Select appropriate template for artifact family",
    allowed_agents=["content_director"],
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

RENDER_BRIEF_GENERATION_TOOL = ToolHarness(
    tool_id="render_brief_generation",
    owner_agent="content_director",
    purpose="Generate render brief for visual designer",
    allowed_agents=["content_director"],
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

# --- TextBuddy tools ---
APPLY_BRAND_VOICE_TOOL = ToolHarness(
    tool_id="apply_brand_voice",
    owner_agent="text_buddy",
    purpose="Apply enterprise brand voice guidelines to text",
    allowed_agents=["text_buddy"],
    allowed_workflows=ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

SELECT_TEMPLATE_TOOL = ToolHarness(
    tool_id="select_template",
    owner_agent="text_buddy",
    purpose="Select text template for artifact family",
    allowed_agents=["text_buddy"],
    allowed_workflows=ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=5,
)

FORMAT_OUTPUT_TOOL = ToolHarness(
    tool_id="format_output",
    owner_agent="text_buddy",
    purpose="Format final text output with citations",
    allowed_agents=["text_buddy"],
    allowed_workflows=ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=10,
)

# --- VanGogh tools ---
ARTIFACT_CONTRACT_TOOL = ToolHarness(
    tool_id="artifact_contract",
    owner_agent="vangogh",
    purpose="Produce HTML/CSS artifact with layout and brand DNA",
    allowed_agents=["vangogh"],
    allowed_workflows=ALL_VISUAL_WORKFLOWS,
    side_effects=["writes_artifact"],
    idempotent=True,
    timeout_seconds=30,
)

# --- Governance tools ---
VALIDATE_VISUAL_ARTIFACT_TOOL = ToolHarness(
    tool_id="validate_visual_artifact",
    owner_agent="governance",
    purpose="Validate artifact completeness, citations, and readiness",
    allowed_agents=["governance"],
    allowed_workflows=ALL_VISUAL_WORKFLOWS + ALL_TEXT_WORKFLOWS,
    idempotent=True,
    timeout_seconds=15,
)


# ============================================================================
# Built-in registries
# ============================================================================

AGENT_HARNESSES: dict[str, AgentHarness] = {
    "strategist": STRATEGIST_HARNESS,
    "hitl": HITL_HARNESS,
    "human": HUMAN_HARNESS,
    "research": RESEARCH_HARNESS,
    "deep_research": DEEP_RESEARCH_HARNESS,
    "finance_research": FINANCE_RESEARCH_HARNESS,
    "data_science": DATA_SCIENCE_HARNESS,
    "content_director": CONTENT_DIRECTOR_HARNESS,
    "text_buddy": TEXT_BUDDY_HARNESS,
    "vangogh": VANGOGH_HARNESS,
    "governance": GOVERNANCE_HARNESS,
}

TOOL_HARNESSES: dict[str, ToolHarness] = {
    # Strategist
    "list_live_agents": LIST_LIVE_AGENTS_TOOL,
    "match_agent_capabilities": MATCH_AGENT_CAPABILITIES_TOOL,
    "compose_execution_strategy": COMPOSE_EXECUTION_STRATEGY_TOOL,
    "classify_artifact_family": CLASSIFY_ARTIFACT_FAMILY_TOOL,
    "derive_artifact_requirements": DERIVE_ARTIFACT_REQUIREMENTS_TOOL,
    "compute_missing_requirements": COMPUTE_MISSING_REQUIREMENTS_TOOL,
    "compose_task_graph": COMPOSE_TASK_GRAPH_TOOL,
    # HITL
    "clarify_requirements": CLARIFY_REQUIREMENTS_TOOL,
    # Research
    "hivemind_recall": HIVEMIND_RECALL_TOOL,
    "hivemind_query_with_ai": HIVEMIND_QUERY_WITH_AI_TOOL,
    "hivemind_get_memory": HIVEMIND_GET_MEMORY_TOOL,
    "hivemind_traverse_graph": HIVEMIND_TRAVERSE_GRAPH_TOOL,
    "hivemind_web_search": HIVEMIND_WEB_SEARCH_TOOL,
    "hivemind_web_crawl": HIVEMIND_WEB_CRAWL_TOOL,
    "hivemind_web_job_status": HIVEMIND_WEB_JOB_STATUS_TOOL,
    "hivemind_web_usage": HIVEMIND_WEB_USAGE_TOOL,
    "validate_document_path": VALIDATE_DOCUMENT_PATH_TOOL,
    # Data Science
    "data_upload": DATA_UPLOAD_TOOL,
    "sandbox_execute": SANDBOX_EXECUTE_TOOL,
    "statistical_test": STATISTICAL_TEST_TOOL,
    "generate_visualization": GENERATE_VISUALIZATION_TOOL,
    # Content Director
    "content_distribution": CONTENT_DISTRIBUTION_TOOL,
    "section_planning": SECTION_PLANNING_TOOL,
    "template_selection": TEMPLATE_SELECTION_TOOL,
    "render_brief_generation": RENDER_BRIEF_GENERATION_TOOL,
    # TextBuddy
    "apply_brand_voice": APPLY_BRAND_VOICE_TOOL,
    "select_template": SELECT_TEMPLATE_TOOL,
    "format_output": FORMAT_OUTPUT_TOOL,
    # VanGogh
    "artifact_contract": ARTIFACT_CONTRACT_TOOL,
    # Governance
    "validate_visual_artifact": VALIDATE_VISUAL_ARTIFACT_TOOL,
}
