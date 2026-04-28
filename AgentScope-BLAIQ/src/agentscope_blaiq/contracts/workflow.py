from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .agent_catalog import AgentTaskAssignment, LiveAgentProfile


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowMode(str, Enum):
    sequential = "sequential"
    parallel = "parallel"
    hybrid = "hybrid"


class AnalysisMode(str, Enum):
    standard = "standard"
    deep_research = "deep_research"
    finance = "finance"
    creative = "creative"
    data_science = "data_science"


class ArtifactFamily(str, Enum):
    pitch_deck = "pitch_deck"
    keynote = "keynote"
    poster = "poster"
    brochure = "brochure"
    one_pager = "one_pager"
    landing_page = "landing_page"
    report = "report"
    finance_analysis = "finance_analysis"
    custom = "custom"
    email = "email"
    invoice = "invoice"
    letter = "letter"
    memo = "memo"
    proposal = "proposal"
    social_post = "social_post"
    summary = "summary"


# Canonical set of text-based artifact families handled by TextBuddy.
TEXT_ARTIFACT_FAMILIES: frozenset[str] = frozenset({
    "email", "invoice", "letter", "memo",
    "proposal", "report", "social_post", "summary", "direct",
})


class TaskRole(str, Enum):
    strategist = "strategist"
    research = "research"
    hitl = "hitl"
    oracle = "oracle"
    content_director = "content_director"
    vangogh = "vangogh"
    governance = "governance"
    synthesis = "synthesis"
    render = "render"
    custom = "custom"
    data_science = "data_science"
    text_buddy = "text_buddy"


class ExecutorKind(str, Enum):
    agent = "agent"
    human = "human"
    tool = "tool"
    system = "system"


class RequirementStage(str, Enum):
    before_research = "before_research"
    before_storyboard = "before_storyboard"
    before_render = "before_render"
    before_synthesis = "before_synthesis"
    evidence_informed = "evidence_informed"


class WorkflowStatus(str, Enum):
    queued = "queued"
    running = "running"
    blocked = "blocked"
    complete = "complete"
    error = "error"
    failed = "failed"
    cancelled = "cancelled"


class WorkflowExecutionResult(BaseModel):
    status: WorkflowStatus = WorkflowStatus.complete
    results: Dict[str, Any] = Field(default_factory=dict)
    blocked_by: Optional[RequirementStage] = None
    next_action: Optional[str] = None


class AgentType(str, Enum):
    strategist = "strategist"
    research = "research"
    content_director = "content_director"
    vangogh = "vangogh"
    governance = "governance"
    graph_knowledge = "graph_knowledge"
    text_buddy = "text_buddy"


class ArtifactSpec(BaseModel):
    family: ArtifactFamily = ArtifactFamily.custom
    title: str | None = None
    audience: str | None = None
    deliverable_format: str = "visual_html"
    required_sections: list[str] = Field(default_factory=list)
    tone: str = "executive"
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class RequirementItem(BaseModel):
    requirement_id: str
    text: str
    category: str = "general"
    source: str = "strategy"
    priority: int = 0
    must_have: bool = True
    owner_task_id: str | None = None
    status: str = "pending"
    blockers: list[str] = Field(default_factory=list)
    blocking_stage: RequirementStage = RequirementStage.before_render


class RequirementsChecklist(BaseModel):
    items: list[RequirementItem] = Field(default_factory=list)
    coverage_score: float = 0.0
    missing_required_ids: list[str] = Field(default_factory=list)


class WorkflowNode(BaseModel):
    node_id: str = Field(default_factory=lambda: str(uuid4()))
    task_role: TaskRole = TaskRole.custom
    executor_kind: ExecutorKind = ExecutorKind.agent
    purpose: str
    depends_on: list[str] = Field(default_factory=list)
    parallel_group: str | None = None
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    acceptance_criteria: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    assigned_to: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)


class WorkflowEdge(BaseModel):
    from_node: str
    to_node: str
    condition: str | None = None


class TaskGraph(BaseModel):
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    entry_nodes: list[str] = Field(default_factory=list)
    terminal_nodes: list[str] = Field(default_factory=list)
    fan_in_groups: list[str] = Field(default_factory=list)


class SubmitWorkflowRequest(BaseModel):
    schema_version: str = "v1"
    user_query: str
    workflow_mode: WorkflowMode = WorkflowMode.hybrid
    analysis_mode: AnalysisMode = AnalysisMode.standard
    tenant_id: str = "default"
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    thread_id: str = Field(default_factory=lambda: str(uuid4()))
    artifact_type: str = "visual_html"
    source_scope: str = "web_and_docs"
    artifact_family_hint: ArtifactFamily | None = None
    target_audience: str | None = None
    delivery_channel: str | None = None
    brand_context: str | None = None
    analysis_subject: str | None = None
    analysis_objective: str | None = None
    analysis_horizon: str | None = None
    analysis_benchmark: str | None = None
    must_have_sections: list[str] = Field(default_factory=list)
    explicit_requirements: list[str] = Field(default_factory=list)
    hivemind_project: str | None = None
    hivemind_tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = Field(default=None)
    memory_chain_id: str | None = None
    re_run_from_planning: bool = False


class ClarificationQuestion(BaseModel):
    """Single typed clarification question surfaced to the user during HITL.

    Extends the agent-layer ``ClarificationQuestion`` with validation metadata
    so the frontend can render and validate answers without a round-trip.
    """

    requirement_id: str
    question: str
    why_it_matters: str | None = None
    answer_hint: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    input_type: str = "option"  # "option" | "text" | "multi_select"
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class ClarificationBundle(BaseModel):
    """Typed pause payload emitted by the engine when a workflow is blocked.

    Replaces the ad-hoc ``blocked_question`` string so the frontend can render
    structured options and the resume path can validate answers precisely.
    """

    bundle_id: str = Field(default_factory=lambda: str(uuid4()))
    headline: str
    intro: str
    blocking_stage: str = ""
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    expected_answer_schema: dict[str, str] = Field(default_factory=dict)
    pending_node: str | None = None
    resume_from_node: str | None = None
    plan_snapshot: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ClarificationAnswerSet(BaseModel):
    """Typed answer payload posted by the frontend to resume a blocked workflow."""

    bundle_id: str
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="requirement_id -> answer value",
    )
    validation_errors: dict[str, str] = Field(default_factory=dict)
    completed: bool = False


class ResumeWorkflowRequest(BaseModel):
    thread_id: str
    tenant_id: str | None = None
    resume_reason: str | None = None
    # Legacy flat answers dict — kept for backwards compat.
    answers: dict[str, str] = Field(default_factory=dict)
    # Typed resume path (Phase 4+): prefer these over bare ``answers``.
    clarification_bundle_id: str | None = None
    answer_set: ClarificationAnswerSet | None = None
    resume_strategy: str = "continue"  # "continue" | "replan" | "restart_from_planning"


class AgentRunPayload(WorkflowNode):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: AgentType = AgentType.research
    task_input: dict = Field(default_factory=dict)


class WorkflowPlan(BaseModel):
    workflow_mode: WorkflowMode
    analysis_mode: AnalysisMode = AnalysisMode.standard
    summary: str
    direct_answer: bool = False
    conversational: bool = False
    notes: list[str] = Field(default_factory=list)
    artifact_family: ArtifactFamily = ArtifactFamily.custom
    artifact_spec: ArtifactSpec | None = None
    requirements_checklist: RequirementsChecklist = Field(default_factory=RequirementsChecklist)
    task_graph: TaskGraph = Field(default_factory=TaskGraph)
    tasks: list[AgentRunPayload] = Field(default_factory=list)
    hitl_nodes: list[WorkflowNode] = Field(default_factory=list)
    content_director_nodes: list[WorkflowNode] = Field(default_factory=list)
    available_agents: list[LiveAgentProfile] = Field(default_factory=list)
    agent_assignments: list[AgentTaskAssignment] = Field(default_factory=list)
    topology_reason: str = ""
    workflow_template_id: str | None = None
    node_assignments: dict[str, str] = Field(default_factory=dict)
    required_tools_per_node: dict[str, list[str]] = Field(default_factory=dict)
    fallback_path: str | None = None
    missing_requirements: list[str] = Field(default_factory=list)
    fan_in_required: bool = False
    fan_in_agent: AgentType = AgentType.strategist
    planner_snapshot_json: str | None = None  # Phase 1: exported PlanNotebook snapshot
    created_at: datetime = Field(default_factory=utc_now)
