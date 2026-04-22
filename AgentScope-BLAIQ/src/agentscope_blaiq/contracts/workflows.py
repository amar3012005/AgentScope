"""
Phase 2: Canonical Workflow Templates

Message-driven orchestration templates bound to harness contracts.
Each template defines:
  - DAG structure using Node entities (input_from/output_to edges)
  - Tool bindings through required_tools
  - Approval gates and conditional branching
  - Fallback behavior for failures

No runtime changes. Contracts isolated. Ready for AgentScope orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .harness import Node, WorkflowTemplate


# ============================================================================
# Message Templates (Msg content contracts)
# ============================================================================

@dataclass
class UserRequest:
    """User's initial request to the system."""
    query: str
    artifact_family: Optional[str] = None
    target_audience: Optional[str] = None
    tone: Optional[str] = None
    brand_context: Optional[str] = None
    must_have_sections: list[str] | None = None


@dataclass
class StrategicPlan:
    """Strategist output: high-level plan and artifact spec."""
    user_request: str
    strategy_summary: str
    artifact_family: str
    artifact_spec: dict[str, Any]
    research_focus: str
    delivery_channel: Optional[str] = None


@dataclass
class EvidencePack:
    """Research output: findings, citations, evidence."""
    findings: list[dict[str, Any]]
    citations: list[dict[str, str]]
    source_summary: str
    confidence_score: float
    research_gaps: list[str] | None = None


@dataclass
class VisualSpec:
    """Content Director output: visual layout and component specs."""
    artifact_family: str
    layout_structure: dict[str, Any]
    sections: list[dict[str, Any]]
    styling_hints: dict[str, str]
    component_specs: list[dict[str, Any]]
    deliverable_format: str = "visual_html"


@dataclass
class VisualArtifact:
    """Vangogh output: rendered visual artifact."""
    artifact_family: str
    content: str  # HTML/SVG content
    styling: dict[str, str]
    preview_url: Optional[str] = None
    component_metadata: dict[str, Any] | None = None


@dataclass
class TextArtifact:
    """TextBuddy output: formatted text with branding."""
    artifact_family: str
    content: str
    tone: str
    brand_applied: bool = False
    formatting_metadata: dict[str, Any] | None = None


@dataclass
class GovernanceReview:
    """Governance output: approval decision and feedback."""
    artifact_id: str
    approved: bool
    review_notes: str
    required_revisions: list[str] | None = None
    approval_metadata: dict[str, Any] | None = None


# ============================================================================
# Workflow 1: visual_artifact_v1
# DAG: Strategist → Research → ContentDirector → Vangogh → Governance
# ============================================================================

VISUAL_ARTIFACT_V1 = WorkflowTemplate(
    workflow_id="visual_artifact_v1",
    purpose="Create visual artifacts (pitch decks, presentations, posters) through strategic planning, research, content direction, and visual rendering",
    version="1.0",
    description="Multi-stage visual artifact creation (pitch decks, presentations, posters)",
    entry_conditions={"artifact_type": "visual"},
    nodes=[
        Node(
            node_id="strategist",
            agent_id="strategist",
            input_from=["start"],
            output_to=["research"],
            required_tools=["hivemind_recall"],
            timeout_seconds=60,
        ),
        Node(
            node_id="research",
            agent_id="research",
            input_from=["strategist"],
            output_to=["content_director"],
            required_tools=["hivemind_recall", "hivemind_web_search"],
            timeout_seconds=90,
        ),
        Node(
            node_id="content_director",
            agent_id="content_director",
            input_from=["research"],
            output_to=["vangogh"],
            required_tools=[],
            timeout_seconds=60,
        ),
        Node(
            node_id="vangogh",
            agent_id="vangogh",
            input_from=["content_director"],
            output_to=["governance"],
            required_tools=["artifact_contract"],
            timeout_seconds=120,
        ),
        Node(
            node_id="governance",
            agent_id="governance",
            input_from=["vangogh"],
            output_to=[],
            required_tools=[],
            approval_gate="governance",
            timeout_seconds=30,
        ),
    ],
    allowed_agents=["strategist", "research", "content_director", "vangogh", "governance"],
    required_handoffs=[
        ("strategist", "research"),
        ("research", "content_director"),
        ("content_director", "vangogh"),
        ("vangogh", "governance"),
    ],
    approval_gates=["governance"],
    fallback_branches={
        "weak_evidence": "research",
        "timeout": "governance",
    },
)


# ============================================================================
# Workflow 2: text_artifact_v1
# DAG: Strategist → Research → TextBuddy → Governance
# ============================================================================

TEXT_ARTIFACT_V1 = WorkflowTemplate(
    workflow_id="text_artifact_v1",
    purpose="Create text artifacts (emails, proposals, reports, social posts) through strategic planning, research, brand voice application, and governance approval",
    version="1.0",
    description="Text artifact creation (emails, proposals, reports, social posts)",
    entry_conditions={"artifact_type": "text"},
    nodes=[
        Node(
            node_id="strategist",
            agent_id="strategist",
            input_from=["start"],
            output_to=["research"],
            required_tools=["hivemind_recall"],
            timeout_seconds=60,
        ),
        Node(
            node_id="research",
            agent_id="research",
            input_from=["strategist"],
            output_to=["text_buddy"],
            required_tools=["hivemind_recall", "hivemind_web_search"],
            timeout_seconds=90,
        ),
        Node(
            node_id="text_buddy",
            agent_id="text_buddy",
            input_from=["research"],
            output_to=["governance"],
            required_tools=["apply_brand_voice"],
            timeout_seconds=60,
        ),
        Node(
            node_id="governance",
            agent_id="governance",
            input_from=["text_buddy"],
            output_to=[],
            required_tools=[],
            approval_gate="governance",
            timeout_seconds=30,
        ),
    ],
    allowed_agents=["strategist", "research", "text_buddy", "governance"],
    required_handoffs=[
        ("strategist", "research"),
        ("research", "text_buddy"),
        ("text_buddy", "governance"),
    ],
    approval_gates=["governance"],
    fallback_branches={
        "weak_evidence": "research",
        "timeout": "governance",
    },
)


# ============================================================================
# Workflow 3: direct_answer_v1
# DAG: Research → TextBuddy (no strategist, no governance)
# ============================================================================

DIRECT_ANSWER_V1 = WorkflowTemplate(
    workflow_id="direct_answer_v1",
    purpose="Answer questions directly through research and formatted response without strategic planning or approval gates",
    version="1.0",
    description="Quick question-answering with formatted response",
    entry_conditions={"artifact_type": "answer"},
    nodes=[
        Node(
            node_id="research",
            agent_id="research",
            input_from=["start"],
            output_to=["text_buddy"],
            required_tools=["hivemind_recall", "hivemind_web_search"],
            timeout_seconds=90,
        ),
        Node(
            node_id="text_buddy",
            agent_id="text_buddy",
            input_from=["research"],
            output_to=[],
            required_tools=["apply_brand_voice"],
            timeout_seconds=60,
        ),
    ],
    allowed_agents=["research", "text_buddy"],
    required_handoffs=[
        ("research", "text_buddy"),
    ],
    approval_gates=[],
    fallback_branches={},
)


# ============================================================================
# Workflow 4: research_v1
# DAG: Research → {DeepResearch + TextBuddy} → TextBuddy (fanout/merge)
# ============================================================================

RESEARCH_V1 = WorkflowTemplate(
    workflow_id="research_v1",
    purpose="Conduct deep market research with optional parallel deep research phase and formatted output",
    version="1.0",
    description="Deep market research with optional parallel deep dive",
    entry_conditions={"artifact_type": "research"},
    nodes=[
        Node(
            node_id="research",
            agent_id="research",
            input_from=["start"],
            output_to=["deep_research", "text_buddy"],  # Fanout: both paths
            required_tools=["hivemind_recall", "hivemind_web_search"],
            timeout_seconds=90,
            parallel_group="research_phase",
        ),
        Node(
            node_id="deep_research",
            agent_id="deep_research",
            input_from=["research"],
            output_to=["text_buddy"],  # Merge back to formatting
            required_tools=["hivemind_recall", "hivemind_web_search", "hivemind_web_crawl"],
            timeout_seconds=180,
            parallel_group="research_phase",
        ),
        Node(
            node_id="text_buddy",
            agent_id="text_buddy",
            input_from=["research", "deep_research"],  # Merge point
            output_to=[],
            required_tools=["apply_brand_voice"],
            timeout_seconds=60,
        ),
    ],
    allowed_agents=["research", "deep_research", "text_buddy"],
    required_handoffs=[
        ("research", "deep_research"),
        ("research", "text_buddy"),
        ("deep_research", "text_buddy"),
    ],
    approval_gates=[],
    fallback_branches={
        "deep_research_timeout": "text_buddy",  # Skip deep phase if timeout
    },
)


# ============================================================================
# Workflow 5: finance_v1
# DAG: FinanceResearch → DataScience → TextBuddy → Governance
# ============================================================================

FINANCE_V1 = WorkflowTemplate(
    workflow_id="finance_v1",
    purpose="Conduct financial analysis with data science modeling, formatted reporting, and governance approval",
    version="1.0",
    description="Financial analysis with modeling and approval",
    entry_conditions={"artifact_type": "finance"},
    nodes=[
        Node(
            node_id="finance_research",
            agent_id="finance_research",
            input_from=["start"],
            output_to=["data_science"],
            required_tools=["hivemind_recall", "hivemind_web_search"],
            timeout_seconds=120,
        ),
        Node(
            node_id="data_science",
            agent_id="data_science",
            input_from=["finance_research"],
            output_to=["text_buddy"],
            required_tools=[],
            timeout_seconds=180,
        ),
        Node(
            node_id="text_buddy",
            agent_id="text_buddy",
            input_from=["data_science"],
            output_to=["governance"],
            required_tools=["apply_brand_voice"],
            timeout_seconds=60,
        ),
        Node(
            node_id="governance",
            agent_id="governance",
            input_from=["text_buddy"],
            output_to=[],
            required_tools=[],
            approval_gate="governance",
            timeout_seconds=30,
        ),
    ],
    allowed_agents=["finance_research", "data_science", "text_buddy", "governance"],
    required_handoffs=[
        ("finance_research", "data_science"),
        ("data_science", "text_buddy"),
        ("text_buddy", "governance"),
    ],
    approval_gates=["governance"],
    fallback_branches={
        "modeling_error": "finance_research",
        "timeout": "governance",
    },
)


# ============================================================================
# Canonical Registry
# ============================================================================

WORKFLOW_TEMPLATES = {
    "visual_artifact_v1": VISUAL_ARTIFACT_V1,
    "text_artifact_v1": TEXT_ARTIFACT_V1,
    "direct_answer_v1": DIRECT_ANSWER_V1,
    "research_v1": RESEARCH_V1,
    "finance_v1": FINANCE_V1,
}


def get_workflow_template(workflow_id: str) -> Optional[WorkflowTemplate]:
    """Fetch canonical workflow template by ID."""
    return WORKFLOW_TEMPLATES.get(workflow_id)


def list_workflow_templates() -> list[str]:
    """List all canonical workflow IDs."""
    return sorted(WORKFLOW_TEMPLATES.keys())
