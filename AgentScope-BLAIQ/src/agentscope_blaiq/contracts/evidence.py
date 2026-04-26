from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .brief import ArtifactBrief, BriefSection
from .workflow import ArtifactFamily


class Citation(BaseModel):
    source_id: str
    label: str
    excerpt: str | None = None
    url: str | None = None


class SourceRecord(BaseModel):
    source_id: str
    source_type: str
    title: str
    location: str
    metadata: dict[str, str] = Field(default_factory=dict)


class EvidenceFinding(BaseModel):
    finding_id: str
    title: str
    summary: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class EvidenceContradiction(BaseModel):
    topic: str
    description: str
    source_ids: list[str] = Field(default_factory=list)
    severity: str = "medium"


class EvidenceFreshness(BaseModel):
    memory_is_fresh: bool = True
    web_verified: bool = False
    freshness_summary: str = ""
    checked_at: str | None = None


class EvidenceProvenance(BaseModel):
    memory_sources: int = 0
    web_sources: int = 0
    upload_sources: int = 0
    graph_traversals: int = 0
    primary_ground_truth: str = "memory"
    save_back_eligible: bool = False


class StructuredInsight(BaseModel):
    """A content-ready insight extracted from research findings.

    Attributes:
        insight: The core insight statement (1-2 sentences)
        insight_type: "key_claim" | "supporting_evidence" | "metric" | "comparison" | "risk" | "opportunity"
        audience_relevance: list of audiences this matters to ("investor" | "customer" | "technical" | "executive")
        confidence: 0-1 confidence score
        source_refs: list of source_ids that support this insight
        quotable: Whether this is a strong quote-worthy statement
        narrative_hook: How this connects to a broader story arc
    """
    insight: str
    insight_type: str
    audience_relevance: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    source_refs: list[str] = Field(default_factory=list)
    quotable: bool = False
    narrative_hook: str = ""


class ContentHook(BaseModel):
    """A hook or angle for content creation.

    Attributes:
        hook_type: "problem" | "solution" | "proof" | "urgency" | "contrast" | "social_proof"
        description: The hook statement
        supporting_evidence: source_ids that back this hook
        emotional_weight: "low" | "medium" | "high"
    """
    hook_type: str
    description: str
    supporting_evidence: list[str] = Field(default_factory=list)
    emotional_weight: str = "medium"


class RiskFlag(BaseModel):
    """A risk or sensitivity flag for downstream governance.

    Attributes:
        risk_type: "compliance" | "legal" | "reputational" | "accuracy" | "sensitivity"
        description: What the risk is
        severity: "low" | "medium" | "high" | "critical"
        affected_claims: source_refs of claims that carry this risk
        mitigation: Suggested mitigation approach
    """
    risk_type: str
    description: str
    severity: str
    affected_claims: list[str] = Field(default_factory=list)
    mitigation: str = ""


class ResearchCacheEntry(BaseModel):
    """Cache entry for research results.

    Attributes:
        query_hash: Hash of the normalized query
        cached_at: ISO timestamp of cache
        expires_at: ISO timestamp when cache expires
        query: Original query text
        evidence_pack_summary: Summary of cached evidence
        freshness_tags: list of data elements that may go stale
    """
    query_hash: str
    cached_at: str
    expires_at: str
    query: str
    evidence_pack_summary: str
    freshness_tags: list[str] = Field(default_factory=list)


class ContentBriefHandoff(BaseModel):
    """Structured handoff from research to content director.

    Attributes:
        key_message: The one-sentence core message content should convey
        supporting_pillars: 2-4 key supporting points
        audience_angles: How to frame for different audiences
        recommended_structure: Suggested section/ordering
        tone_guidance: Tone recommendations based on evidence
        must_include_claims: Claims that must appear in content
        avoid_claims: Claims to avoid or qualify
        visual_opportunities: Data points that would work well visually
    """
    key_message: str
    supporting_pillars: list[str] = Field(default_factory=list)
    audience_angles: dict[str, str] = Field(default_factory=dict)  # audience -> framing
    recommended_structure: list[str] = Field(default_factory=list)
    tone_guidance: str = ""
    must_include_claims: list[str] = Field(default_factory=list)
    avoid_claims: list[str] = Field(default_factory=list)
    visual_opportunities: list[dict] = Field(default_factory=list)  # [{value, label, visual_type}]

    def to_artifact_brief(
        self,
        *,
        thread_id: str,
        brief_id: str,
        artifact_family: ArtifactFamily | str = ArtifactFamily.custom,
        title: str = "Generated Artifact",
        evidence_pack_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactBrief:
        return content_brief_to_artifact_brief(
            self,
            thread_id=thread_id,
            brief_id=brief_id,
            artifact_family=artifact_family,
            title=title,
            evidence_pack_id=evidence_pack_id,
            metadata=metadata,
        )


def content_brief_to_artifact_brief(
    content_brief: ContentBriefHandoff,
    *,
    thread_id: str,
    brief_id: str,
    artifact_family: ArtifactFamily | str = ArtifactFamily.custom,
    title: str = "Generated Artifact",
    evidence_pack_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> ArtifactBrief:
    """Compatibility bridge from legacy ContentBriefHandoff to canonical ArtifactBrief."""

    if isinstance(artifact_family, ArtifactFamily):
        family = artifact_family
    else:
        try:
            family = ArtifactFamily(str(artifact_family))
        except ValueError:
            family = ArtifactFamily.custom
    ordered_sections = content_brief.recommended_structure or [
        "problem",
        "solution",
        "proof",
        "cta",
    ]
    sections: list[BriefSection] = []
    for index, section_name in enumerate(ordered_sections):
        pillar = (
            content_brief.supporting_pillars[index]
            if index < len(content_brief.supporting_pillars)
            else content_brief.key_message
        )
        visual_hint = None
        if index < len(content_brief.visual_opportunities):
            visual_hint = content_brief.visual_opportunities[index].get("visual_type")
        sections.append(
            BriefSection(
                section_id=f"section_{index + 1}",
                title=section_name.replace("_", " ").title(),
                objective=pillar or content_brief.key_message,
                key_points=[pillar] if pillar else [],
                visual_hint=visual_hint,
                constraints=content_brief.avoid_claims[:3],
            )
        )

    return ArtifactBrief(
        brief_id=brief_id,
        thread_id=thread_id,
        artifact_family=family,
        title=title,
        core_narrative=content_brief.key_message,
        target_audience=", ".join(content_brief.audience_angles.keys()) or "general",
        sections=sections,
        style_preference="executive",
        evidence_pack_id=evidence_pack_id,
        required_disclaimers=content_brief.avoid_claims,
        metadata=metadata or {"compat_source": "ContentBriefHandoff"},
    )


# =============================================================================
# Data Science Agent Extensions
# =============================================================================


class CodeExecutionResult(BaseModel):
    """Result from sandboxed code execution.

    Attributes:
        execution_id: Unique execution identifier
        code: Python code that was executed
        exit_code: Process exit code (0 = success)
        stdout: Standard output captured
        stderr: Standard error captured
        execution_time_ms: Execution duration
        memory_usage_bytes: Peak memory consumption
        artifacts: List of generated file paths
        error_type: Exception type if failed (e.g., "SyntaxError")
    """
    execution_id: str
    code: str
    exit_code: int
    stdout: str
    stderr: str
    execution_time_ms: int
    memory_usage_bytes: int = 0
    artifacts: list[str] = Field(default_factory=list)
    error_type: str | None = None


class Visualization(BaseModel):
    """Generated visualization metadata.

    Attributes:
        viz_id: Unique visualization identifier
        viz_type: "bar" | "line" | "scatter" | "histogram" | "box" | "heatmap" | "correlation_matrix"
        title: Chart title
        description: Human-readable description
        file_path: Path to saved visualization (PNG/HTML)
        file_type: "png" | "html" | "svg"
        data_summary: Brief description of underlying data
        plotly_json: Plotly JSON for interactive rendering (if HTML)
        thumbnail_path: Path to thumbnail image
    """
    viz_id: str
    viz_type: str
    title: str
    description: str
    file_path: str
    file_type: str
    data_summary: str
    plotly_json: dict | None = None
    thumbnail_path: str | None = None


class StatisticalResult(BaseModel):
    """Statistical analysis result.

    Attributes:
        stat_type: "descriptive" | "inferential" | "regression" | "correlation"
        test_name: Name of statistical test (e.g., "Pearson correlation")
        result_dict: Dictionary of results (e.g., {"r": 0.85, "p": 0.001})
        interpretation: Human-readable interpretation
        assumptions_checked: List of assumptions and their status
        effect_size: Effect size metric if applicable
        confidence_interval: [lower, upper] if applicable
    """
    stat_type: str
    test_name: str
    result_dict: dict[str, float]
    interpretation: str
    assumptions_checked: list[dict[str, str]] = Field(default_factory=list)
    effect_size: float | None = None
    confidence_interval: list[float] | None = None


class DataSchema(BaseModel):
    """Schema information for uploaded dataset.

    Attributes:
        column_name: Name of the column
        data_type: "numeric" | "categorical" | "datetime" | "text"
        nullable: Whether column contains nulls
        unique_count: Number of unique values
        sample_values: Example values for understanding
        statistics: Numeric stats (min, max, mean, std) if numeric
    """
    column_name: str
    data_type: str
    nullable: bool
    unique_count: int
    sample_values: list[str]
    statistics: dict[str, float] | None = None


class AnalysisResult(BaseModel):
    """Complete analysis result from DS Agent.

    Attributes:
        dataset_info: DataSchema list describing input data
        code_execution: CodeExecutionResult from sandbox
        statistical_results: List of StatisticalResult
        visualizations: List of Visualization
        key_findings: Summary of key insights discovered
        limitations: Known limitations or caveats
        recommendations: Suggested next steps
    """
    dataset_info: list[DataSchema] = Field(default_factory=list)
    code_execution: CodeExecutionResult | None = None
    statistical_results: list[StatisticalResult] = Field(default_factory=list)
    visualizations: list[Visualization] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class EvidencePack(BaseModel):
    summary: str
    sources: list[SourceRecord] = Field(default_factory=list)
    memory_findings: list[EvidenceFinding] = Field(default_factory=list)
    web_findings: list[EvidenceFinding] = Field(default_factory=list)
    doc_findings: list[EvidenceFinding] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    citations: list[Citation] = Field(default_factory=list)
    contradictions: list[EvidenceContradiction] = Field(default_factory=list)
    freshness: EvidenceFreshness = Field(default_factory=EvidenceFreshness)
    provenance: EvidenceProvenance = Field(default_factory=EvidenceProvenance)
    recommended_followups: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # New enriched fields for downstream agents
    structured_insights: list[StructuredInsight] = Field(default_factory=list)
    content_hooks: list[ContentHook] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    artifact_brief: ArtifactBrief | None = None
    # Deprecated compatibility path: producers may still set this legacy handoff.
    content_brief: ContentBriefHandoff | None = None
    cache_entry: ResearchCacheEntry | None = None
    # Data Science Agent specific fields
    analysis_result: AnalysisResult | None = None
    data_uploads: list[str] = Field(default_factory=list)  # upload IDs

    @model_validator(mode="after")
    def _upgrade_legacy_content_brief(self) -> EvidencePack:
        """Ensure ArtifactBrief is the canonical boundary while keeping legacy support."""
        if self.artifact_brief is not None:
            return self
        if self.content_brief is None:
            return self
        thread_id = str(self.metadata.get("thread_id", "legacy-thread"))
        brief_id = str(self.metadata.get("brief_id", "legacy-brief"))
        artifact_family_hint = str(self.metadata.get("artifact_family", "custom"))
        title_hint = str(self.metadata.get("title", "Generated Artifact"))
        evidence_pack_id = str(self.metadata.get("evidence_pack_id", ""))
        try:
            family = ArtifactFamily(artifact_family_hint)
        except ValueError:
            family = ArtifactFamily.custom
        self.artifact_brief = self.content_brief.to_artifact_brief(
            thread_id=thread_id,
            brief_id=brief_id,
            artifact_family=family,
            title=title_hint,
            evidence_pack_id=evidence_pack_id,
            metadata={"compat_source": "ContentBriefHandoff", **self.metadata},
        )
        return self
