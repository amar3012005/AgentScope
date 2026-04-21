"""LangGraph shared state definition for BLAIQ workflow graphs.

The ``BlaiqGraphState`` TypedDict is the single source of truth that flows
through every node in a LangGraph execution.  Large artefacts (evidence
chunks, rendered HTML) are stored out-of-band via the Claim Check pattern
and referenced here as serialised manifest dicts.

The ``logs`` field uses LangGraph's ``Annotated[list, add]`` reducer so
that every node can append log entries without overwriting prior output.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Optional, TypedDict


class BlaiqGraphState(TypedDict):
    """Shared state flowing through the BLAIQ LangGraph execution graph.

    Fields are grouped by lifecycle phase.  Only lightweight data travels
    in state; bulky payloads live behind ``artifact_uri`` pointers in the
    manifest dicts.
    """

    # ── Identity ────────────────────────────────────────────────────────
    thread_id: str
    session_id: str
    tenant_id: str
    collection_name: str
    run_id: str  # Temporal workflow run ID

    # ── Input ───────────────────────────────────────────────────────────
    user_query: str
    workflow_mode: str  # standard | deep_research | creative
    use_template_engine: bool  # enable Vangogh v2 template pipeline
    room_number: str
    chat_history: list[dict[str, str]]
    strategy_execution_plan: list[str]  # strategist-selected plan override
    strategy_selected_agents: list[str]
    strategy_primary_agent: str
    strategy_route_mode: str
    strategy_reasoning: str

    # ── Tracing & lineage ────────────────────────────────────────────────
    message_id: str  # canonical message ID for the current turn
    trace_context: dict[str, str]  # W3C traceparent/tracestate propagation
    memory_refs: list[str]  # references to persisted memory/artifact records

    # ── Planner output ──────────────────────────────────────────────────
    execution_plan: list[str]  # e.g. ["graphrag", "content", "governance"]
    extracted_entities: list[str]
    keywords: list[str]
    workflow_plan: Optional[dict]  # CORE-driven workflow plan payload
    workflow_complete: bool

    # ── Evidence (GraphRAG output) — lightweight via claim check ───────
    evidence_manifest: Optional[dict]  # serialised EvidenceManifest

    # ── Content output — lightweight via claim check ───────────────────
    content_draft: Optional[dict]  # serialised PitchDeckDraft
    content_director_plan: Optional[dict]  # page-by-page rendering plan

    # ── HITL ────────────────────────────────────────────────────────────
    hitl_required: bool
    hitl_questions: list[str]
    hitl_answers: dict[str, str]
    hitl_node: str  # which agent requested HITL
    hitl_mode: str  # clarification | page_review
    post_hitl_search_prompt_template: str  # content-authored retrieval prompt template
    content_requires_hitl: bool  # force HITL in content-creation workflows
    post_hitl_refresh_needed: bool  # force GraphRAG refresh before next content pass

    # ── Governance ──────────────────────────────────────────────────────
    governance_report: Optional[dict]  # serialised GovernanceReport

    # ── Status ──────────────────────────────────────────────────────────
    current_node: str
    status: str  # planning | retrieving | generating | blocked | complete | error
    error_message: str
    logs: Annotated[list[str], add]  # append-only via reducer


__all__ = [
    "BlaiqGraphState",
]
