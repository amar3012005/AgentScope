"""Output contract manifests with Claim Check pattern.

Large artefacts (chunk arrays, rendered HTML) are stored out-of-band in Redis
and referenced via ``artifact_uri``.  The manifest carries only lightweight
metadata so it can travel through LangGraph state and Temporal payloads without
exceeding size limits.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChunkReference(BaseModel):
    """A single retrieved evidence chunk with provenance metadata."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    text: str
    original_filename: str
    score: float
    retrieval_method: str


class EvidenceManifest(BaseModel):
    """Output contract for the GraphRAG retrieval agent.

    When the chunk list exceeds a configured threshold the chunks are
    persisted to Redis and ``artifact_uri`` is set instead of populating
    ``chunks`` inline.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    query: str
    answer: str = ""
    artifact_uri: Optional[str] = None
    chunks: Optional[List[ChunkReference]] = None
    summary: Dict[str, Any] = Field(default_factory=dict)
    graph: Optional[Dict[str, Any]] = None
    retrieval_stats: Dict[str, Any] = Field(default_factory=dict)
    message_ids: List[str] = Field(default_factory=list)
    memory_refs: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContentSchema(BaseModel):
    """Structured strategic metadata attached to a content draft."""

    model_config = ConfigDict(extra="forbid")

    strategic_pillars: List[str] = Field(default_factory=list)
    kpis: List[str] = Field(default_factory=list)
    target_audience: str = ""
    vision_statement: str = ""
    timeline: str = ""


class PitchDeckDraft(BaseModel):
    """Output contract for the content-generation agent.

    Full HTML is stored via claim check when it exceeds the inline size
    threshold.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    artifact_uri: Optional[str] = None
    html_artifact: Optional[str] = None
    schema_data: ContentSchema = Field(default_factory=ContentSchema)
    skills_used: List[str] = Field(default_factory=list)
    brand_dna_version: str = "2.0"
    message_ids: List[str] = Field(default_factory=list)
    memory_refs: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PolicyCheck(BaseModel):
    """Result of a single governance policy evaluation."""

    model_config = ConfigDict(extra="forbid")

    rule: str
    passed: bool
    detail: str = ""


class GovernanceReport(BaseModel):
    """Output contract for the governance / brand-safety agent."""

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    validation_passed: bool = True
    policy_checks: List[PolicyCheck] = Field(default_factory=list)
    violations: List[str] = Field(default_factory=list)
    approved_output: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FinalArtifact(BaseModel):
    """Canonical result returned by every completed workflow."""

    kind: str  # "evidence_only" | "content" | "error"
    mission_id: str = ""
    validation_passed: bool = False
    governance_report: Optional[Dict[str, Any]] = None
    artifact_uri: Optional[str] = None
    html_artifact: Optional[str] = None
    schema_data: Optional[Dict[str, Any]] = None
    skills_used: List[str] = Field(default_factory=list)
    brand_dna_version: str = ""
    answer: Optional[str] = None  # for evidence-only results
    error_message: Optional[str] = None
    message_ids: List[str] = Field(default_factory=list)
    memory_refs: List[str] = Field(default_factory=list)
    trace_context: Dict[str, str] = Field(default_factory=dict)


class SectionManifest(BaseModel):
    """One rendered section within a composed artifact."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    template_name: str
    data: Dict[str, Any] = Field(default_factory=dict)
    html_fragment: str = ""
    order: int = 0


class ArtifactManifest(BaseModel):
    """Complete manifest for a template-rendered artifact (Vangogh V2).

    Carries per-section structured data and rendered HTML fragments
    alongside the composed full document.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str  # ArtifactKind value
    mission_id: str = ""
    title: str = ""
    sections: List[SectionManifest] = Field(default_factory=list)
    full_html: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    message_ids: List[str] = Field(default_factory=list)
    memory_refs: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_legacy_content_schema(self) -> "ContentSchema":
        """Extract a backward-compatible ContentSchema from section data."""
        pillars: list[str] = []
        kpis: list[str] = []
        audience = ""
        vision = ""
        timeline = ""

        for section in self.sections:
            data = section.data
            if "insights" in data:
                for insight in data["insights"]:
                    if isinstance(insight, dict):
                        pillars.append(insight.get("title", ""))
            if "stats" in data:
                for stat in data["stats"]:
                    if isinstance(stat, dict):
                        kpis.append(f"{stat.get('label', '')}: {stat.get('value', '')}")
            if "personas" in data:
                for persona in data["personas"]:
                    if isinstance(persona, dict):
                        audience = persona.get("name", audience)
            if section.section_id in ("title_slide", "hero", "header", "cover"):
                vision = data.get("headline", vision)
            if "phases" in data:
                phases = data["phases"]
                if phases and isinstance(phases, list):
                    timeline = ", ".join(
                        p.get("phase", "") for p in phases if isinstance(p, dict)
                    )

        return ContentSchema(
            strategic_pillars=pillars,
            kpis=kpis,
            target_audience=audience,
            vision_statement=vision,
            timeline=timeline,
        )


def build_final_artifact(state: Dict[str, Any]) -> FinalArtifact:
    """Build a FinalArtifact from the terminal graph state."""
    gov = state.get("governance_report") or {}
    content = state.get("content_draft") or {}
    evidence = state.get("evidence_manifest") or {}
    error_msg = state.get("error_message")

    if error_msg or state.get("status") == "error":
        return FinalArtifact(
            kind="error",
            mission_id=content.get("mission_id") or evidence.get("mission_id", ""),
            validation_passed=False,
            governance_report=gov if gov else None,
            error_message=error_msg or "Unknown error",
        )

    if content:
        return FinalArtifact(
            kind="content",
            mission_id=content.get("mission_id", ""),
            validation_passed=gov.get("validation_passed", False),
            governance_report=gov if gov else None,
            artifact_uri=content.get("artifact_uri"),
            html_artifact=gov.get("approved_output") or content.get("html_artifact"),
            schema_data=content.get("schema_data"),
            skills_used=content.get("skills_used", []),
            brand_dna_version=content.get("brand_dna_version", ""),
        )

    return FinalArtifact(
        kind="evidence_only",
        mission_id=evidence.get("mission_id", ""),
        validation_passed=gov.get("validation_passed", False),
        governance_report=gov if gov else None,
        answer=evidence.get("answer"),
    )


__all__ = [
    "ArtifactManifest",
    "ChunkReference",
    "ContentSchema",
    "EvidenceManifest",
    "FinalArtifact",
    "GovernanceReport",
    "PitchDeckDraft",
    "PolicyCheck",
    "SectionManifest",
    "build_final_artifact",
]
