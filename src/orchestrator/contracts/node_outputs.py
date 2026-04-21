"""Typed output contracts for every LangGraph node.

Each node constructs a typed result model, which validates the output shape
at the boundary, then calls ``.to_state_update()`` to produce the plain dict
that LangGraph expects.  This gives us compile-time documentation and
runtime validation without changing the LangGraph reducer contract.

Usage in a node::

    result = PlannerResult(
        execution_plan=["graphrag", "governance"],
        extracted_entities=["ACME"],
        keywords=["revenue"],
        content_requires_hitl=False,
        status="planning",
        current_node="planner",
        logs=["planner: plan=..."],
    )
    return result.to_state_update()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class NodeResult(BaseModel):
    """Base contract shared by every LangGraph node return value."""

    model_config = ConfigDict(extra="forbid")

    status: str
    current_node: str
    schema_version: str = ""
    logs: List[str] = Field(default_factory=list)
    error_message: str = ""
    message_id: str = ""

    def to_state_update(self) -> Dict[str, Any]:
        """Serialize to the dict shape LangGraph reducers expect.

        Drops ``error_message`` when empty so it doesn't overwrite a
        prior error with a blank string.  Drops ``message_id`` when empty.
        """
        data = self.model_dump(mode="json")
        if not data.get("error_message"):
            data.pop("error_message", None)
        if not data.get("message_id"):
            data.pop("message_id", None)
        return data


# ── Planner ──────────────────────────────────────────────────────────────


class PlannerResult(NodeResult):
    """Output contract for ``planner_node``."""

    execution_plan: List[str]
    extracted_entities: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    content_requires_hitl: bool = False
    workflow_plan: Dict[str, Any] = Field(default_factory=dict)


# ── GraphRAG ─────────────────────────────────────────────────────────────


class RetrievalResult(NodeResult):
    """Output contract for ``graphrag_node``."""

    evidence_manifest: Optional[Dict[str, Any]] = None
    post_hitl_refresh_needed: bool = False


# ── Content ──────────────────────────────────────────────────────────────


class ContentResult(NodeResult):
    """Output contract for ``content_node``.

    When ``hitl_required`` is ``True`` the node is requesting a HITL
    interrupt; ``content_draft`` will be ``None`` in that case.
    """

    content_draft: Optional[Dict[str, Any]] = None
    artifact_manifest: Optional[Dict[str, Any]] = None
    streamed_events: List[Dict[str, Any]] = Field(default_factory=list)
    hitl_required: bool = False
    hitl_questions: List[str] = Field(default_factory=list)
    hitl_node: str = ""
    hitl_mode: str = ""
    post_hitl_search_prompt_template: str = ""
    recovery_hint: str = ""
    workflow_plan: Dict[str, Any] = Field(default_factory=dict)


# ── Governance ───────────────────────────────────────────────────────────


class GovernanceResult(NodeResult):
    """Output contract for ``governance_node``."""

    governance_report: Optional[Dict[str, Any]] = None


# ── HITL ─────────────────────────────────────────────────────────────────


class HITLResult(NodeResult):
    """Output contract for ``hitl_node``."""

    hitl_answers: Dict[str, str] = Field(default_factory=dict)
    hitl_required: bool = False
    post_hitl_refresh_needed: bool = False
    hitl_mode: str = ""


__all__ = [
    "ContentResult",
    "GovernanceResult",
    "HITLResult",
    "NodeResult",
    "PlannerResult",
    "RetrievalResult",
]
