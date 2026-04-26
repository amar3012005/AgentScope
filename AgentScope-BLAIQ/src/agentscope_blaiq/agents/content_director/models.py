from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

def _section_defaults(section_title: str) -> dict[str, str]:
    title = section_title.strip() or "Section"
    lower = title.lower()
    if lower in {"hero", "opening"}:
        return {"purpose": "Establish the core narrative and immediate context.", "visual_intent": "hero-centered"}
    if lower in {"evidence", "proof"}:
        return {"purpose": "Present concrete proof points anchored in evidence.", "visual_intent": "evidence-grid"}
    if lower in {"cta", "call to action", "next steps"}:
        return {"purpose": "Drive a single explicit next action.", "visual_intent": "single-cta"}
    return {"purpose": f"Advance the narrative through {title}.", "visual_intent": "section-grid"}


class ContentSectionPlan(BaseModel):
    section_id: str
    title: str
    purpose: str
    source_refs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    objective: str = ""
    audience: str | None = None
    core_message: str = ""
    # Rich content fields — these drive actual slide copy
    headline: str = ""           # Main slide heading (10 words max)
    subheadline: str = ""        # Supporting statement (1 sentence)
    body: str = ""               # 2-3 paragraphs of narrative content
    bullets: list[str] = Field(default_factory=list)   # 3-5 key points (full sentences)
    stats: list[dict] = Field(default_factory=list)    # [{"value": "¥50T", "label": "Market Size"}]
    evidence_refs: list[str] = Field(default_factory=list)
    visual_intent: str = ""
    cta: str = ""
    risks: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)


class ContentBrief(BaseModel):
    title: str
    family: str
    template_name: str = "default"
    narrative: str
    audience: str | None = None
    core_message: str = ""
    visual_direction: str = ""
    cta: str = ""
    risks: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    section_plan: list[ContentSectionPlan] = Field(default_factory=list)
    distribution_notes: list[str] = Field(default_factory=list)
    handoff_notes: list[str] = Field(default_factory=list)


class SlideData(BaseModel):
    """Single slide in a slides.json structure, maps to a React slide component."""
    type: str  # "hero", "data_grid", "bullets", "evidence", "cta", "quote", "metrics_dashboard", "analysis_chart", "data_table", "insight_cards"
    # Hero fields
    tag: str | None = None
    headline: str | None = None
    subheadline: str | None = None
    body: str | None = None
    # Bullets fields
    title: str | None = None
    subtitle: str | None = None
    bullets: list[str] = Field(default_factory=list)
    # DataGrid fields
    items: list[dict] = Field(default_factory=list)  # [{value, label, source}] or [{finding, source, confidence}]
    # CTA fields
    cta_text: str | None = None
    cta_url: str | None = None
    # Quote fields
    quote: str | None = None
    attribution: str | None = None
    role: str | None = None
    # MetricsDashboard fields
    metrics: list[dict] = Field(default_factory=list)  # [{value, label, trend, trendValue, comparison}]
    # AnalysisChart fields
    chart_type: str | None = None  # "line", "bar", "area"
    chart_data: list[dict] = Field(default_factory=list)  # [{label, value, value2, label2}]
    chart_title: str | None = None
    y_label: str | None = None
    # DataTable fields
    columns: list[dict] = Field(default_factory=list)  # [{key, header, align, format, highlight}]
    table_data: list[dict] = Field(default_factory=list)  # [{columnKey: value}]
    highlight_column: str | None = None
    # InsightCards fields
    insights: list[dict] = Field(default_factory=list)  # [{title, finding, verdict, verdictLabel, metrics, recommendation}]
    research_requests: list[str] = Field(default_factory=list)
    speaker_notes: str = ""


class SlidesData(BaseModel):
    """Complete slides.json output that maps directly to a React template."""
    title: str
    brand: str = "default"
    layout: str = "slides"
    slides: list[SlideData] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

