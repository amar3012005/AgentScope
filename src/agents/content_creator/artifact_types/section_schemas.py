"""Pydantic schemas for section-level structured data.

Each model defines the exact JSON shape the LLM must extract for a
specific section type. The template engine uses these to render
deterministic HTML via Jinja2 templates.
"""
from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


# -- Atomic items -------------------------------------------------------------


class StatItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str  # String to support "12.5M", "$1.2B", "99.9%"
    unit: str = ""
    trend: str = ""  # "up", "down", "flat", or percentage like "+47%"


class InsightItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    tag: str = ""
    icon: str = ""  # Optional emoji or icon name


class TimelinePhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: str
    status: Literal["complete", "active", "upcoming"] = "upcoming"
    description: str = ""
    progress_pct: int = 0  # 0-100


class PersonaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str = ""
    pain_points: List[str] = Field(default_factory=list)
    quote: str = ""
    avatar_initials: str = ""  # e.g. "JD" for John Doe


class TeamMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    bio: str = ""
    expertise: List[str] = Field(default_factory=list)
    avatar_initials: str = ""


class ChartDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    data: List[float | int]
    color: str = ""  # Optional override; template uses brand palette if empty


class PosterProofItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    detail: str = ""
    label: str = ""
    emphasis: Literal["metric", "quote", "claim", "offer"] = "claim"


class PosterDetailItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    note: str = ""
    icon: str = ""


# -- Section data models -------------------------------------------------------


class HeroSectionData(BaseModel):
    """Data for hero/title sections."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    subheadline: str = ""
    cta_text: str = ""
    background_effect: Literal["spotlight", "gradient", "plain"] = "spotlight"


class StatSectionData(BaseModel):
    """Data for stat/KPI display sections."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    stats: List[StatItem] = Field(default_factory=list)


class ChartSectionData(BaseModel):
    """Data for chart sections (Chart.js)."""

    model_config = ConfigDict(extra="forbid")

    chart_type: Literal["bar", "line", "pie", "doughnut", "radar", "polarArea"] = "bar"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    datasets: List[ChartDataset] = Field(default_factory=list)
    caption: str = ""


class InsightSectionData(BaseModel):
    """Data for insight/feature card sections."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    insights: List[InsightItem] = Field(default_factory=list)


class TimelineSectionData(BaseModel):
    """Data for timeline/roadmap sections."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    phases: List[TimelinePhase] = Field(default_factory=list)


class PersonaSectionData(BaseModel):
    """Data for persona/audience sections."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    personas: List[PersonaItem] = Field(default_factory=list)


class FlowchartSectionData(BaseModel):
    """Data for Mermaid flowchart sections."""

    model_config = ConfigDict(extra="forbid")

    mermaid_definition: str
    title: str = ""
    caption: str = ""


class ContentBlockData(BaseModel):
    """Data for general content block sections (text + bullets)."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    body: str = ""  # Markdown-safe text
    bullets: List[str] = Field(default_factory=list)
    tech_stack: List[str] = Field(default_factory=list)  # Optional tech badges


class TeamSectionData(BaseModel):
    """Data for team/people sections."""

    model_config = ConfigDict(extra="forbid")

    title: str = "Team"
    members: List[TeamMember] = Field(default_factory=list)


class CtaSectionData(BaseModel):
    """Data for call-to-action / closing sections."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    body: str = ""
    button_text: str = ""
    button_url: str = ""
    stats: List[StatItem] = Field(default_factory=list)  # Optional supporting stats


class PosterHeroData(BaseModel):
    """Primary studio poster hero block."""

    model_config = ConfigDict(extra="forbid")

    poster_type: Literal["campaign", "event", "launch", "manifesto", "announcement", "editorial"] = "campaign"
    eyebrow: str = ""
    headline: str
    subheadline: str = ""
    supporting_line: str = ""
    visual_motif: str = ""
    focal_image_prompt: str = ""
    alignment: Literal["left", "center"] = "left"
    intensity: Literal["quiet", "balanced", "bold"] = "balanced"


class PosterProofSectionData(BaseModel):
    """High-emphasis proof zone for posters."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    lead_metric: str = ""
    lead_label: str = ""
    proof_items: List[PosterProofItem] = Field(default_factory=list)


class PosterDetailsData(BaseModel):
    """Operational details, offer specifics, or event metadata."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    details: List[PosterDetailItem] = Field(default_factory=list)
    footnote: str = ""


class PosterCtaData(BaseModel):
    """Poster closing section with CTA and optional urgency."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    body: str = ""
    button_text: str = ""
    button_url: str = ""
    urgency_label: str = ""
    contact_line: str = ""
    stats: List[StatItem] = Field(default_factory=list)


# -- Schema lookup -------------------------------------------------------------

SECTION_SCHEMA_MAP: Dict[str, type[BaseModel]] = {
    "HeroSectionData": HeroSectionData,
    "StatSectionData": StatSectionData,
    "ChartSectionData": ChartSectionData,
    "InsightSectionData": InsightSectionData,
    "PosterCtaData": PosterCtaData,
    "PosterDetailsData": PosterDetailsData,
    "PosterHeroData": PosterHeroData,
    "PosterProofSectionData": PosterProofSectionData,
    "TimelineSectionData": TimelineSectionData,
    "PersonaSectionData": PersonaSectionData,
    "FlowchartSectionData": FlowchartSectionData,
    "ContentBlockData": ContentBlockData,
    "TeamSectionData": TeamSectionData,
    "CtaSectionData": CtaSectionData,
}


def get_schema_for_section(schema_class_name: str) -> type[BaseModel] | None:
    """Look up a section schema class by name."""
    return SECTION_SCHEMA_MAP.get(schema_class_name)


def get_json_schema_for_section(schema_class_name: str) -> dict | None:
    """Get the JSON schema dict for a section schema class."""
    cls = SECTION_SCHEMA_MAP.get(schema_class_name)
    if cls is None:
        return None
    return cls.model_json_schema()


__all__ = [
    "ChartDataset",
    "ChartSectionData",
    "ContentBlockData",
    "CtaSectionData",
    "FlowchartSectionData",
    "HeroSectionData",
    "InsightItem",
    "InsightSectionData",
    "PersonaItem",
    "PersonaSectionData",
    "PosterCtaData",
    "PosterDetailItem",
    "PosterDetailsData",
    "PosterHeroData",
    "PosterProofItem",
    "PosterProofSectionData",
    "SECTION_SCHEMA_MAP",
    "StatItem",
    "StatSectionData",
    "TeamMember",
    "TeamSectionData",
    "TimelinePhase",
    "TimelineSectionData",
    "get_json_schema_for_section",
    "get_schema_for_section",
]
