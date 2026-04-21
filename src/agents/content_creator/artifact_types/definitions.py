"""Concrete artifact type definitions for Vangogh V2."""
from __future__ import annotations

from agents.content_creator.artifact_types.registry import (
    ArtifactKind,
    ArtifactTypeDefinition,
    ArtifactTypeRegistry,
    SectionSpec,
)


def register_all(registry: ArtifactTypeRegistry) -> None:
    """Register all built-in artifact types."""

    registry.register(
        ArtifactTypeDefinition(
            kind=ArtifactKind.PITCH_DECK,
            label="Pitch Deck",
            description="Investor-grade slide deck following proven narrative frameworks",
            supports_navigation=True,
            default_skills=["visual_director", "pitch_deck", "copywriter"],
            sections=[
                SectionSpec(
                    section_id="title_slide",
                    label="Title Slide",
                    template_name="hero_section.html.j2",
                    schema_class="HeroSectionData",
                    default_layout="hero",
                ),
                SectionSpec(
                    section_id="problem",
                    label="Problem",
                    template_name="insight_section.html.j2",
                    schema_class="InsightSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="solution",
                    label="Solution",
                    template_name="content_block_section.html.j2",
                    schema_class="ContentBlockData",
                    default_layout="full",
                ),
                SectionSpec(
                    section_id="market",
                    label="Market Opportunity",
                    template_name="stat_section.html.j2",
                    schema_class="StatSectionData",
                    default_layout="stat-showcase",
                ),
                SectionSpec(
                    section_id="product",
                    label="Product",
                    template_name="timeline_section.html.j2",
                    schema_class="TimelineSectionData",
                    default_layout="full",
                ),
                SectionSpec(
                    section_id="traction",
                    label="Traction & Metrics",
                    template_name="chart_section.html.j2",
                    schema_class="ChartSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="team",
                    label="Team",
                    template_name="team_section.html.j2",
                    schema_class="TeamSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="ask",
                    label="The Ask",
                    template_name="cta_section.html.j2",
                    schema_class="CtaSectionData",
                    default_layout="hero",
                ),
            ],
        )
    )

    registry.register(
        ArtifactTypeDefinition(
            kind=ArtifactKind.POSTER,
            label="Poster",
            description="Studio-grade single-canvas poster for campaigns, events, launches, and editorial announcements",
            supports_navigation=False,
            default_skills=["visual_director", "brand_strategist", "copywriter"],
            sections=[
                SectionSpec(
                    section_id="hero",
                    label="Hero",
                    template_name="poster_hero_section.html.j2",
                    schema_class="PosterHeroData",
                    default_layout="hero",
                ),
                SectionSpec(
                    section_id="proof",
                    label="Proof & Emphasis",
                    template_name="poster_proof_section.html.j2",
                    schema_class="PosterProofSectionData",
                    default_layout="poster-proof",
                ),
                SectionSpec(
                    section_id="details",
                    label="Details",
                    template_name="poster_details_section.html.j2",
                    schema_class="PosterDetailsData",
                    default_layout="poster-details",
                ),
                SectionSpec(
                    section_id="cta",
                    label="Call to Action",
                    template_name="poster_cta_section.html.j2",
                    schema_class="PosterCtaData",
                    default_layout="poster-cta",
                ),
            ],
        )
    )

    registry.register(
        ArtifactTypeDefinition(
            kind=ArtifactKind.KEYNOTE,
            label="Keynote Presentation",
            description="Conference-style presentation with transitions and speaker notes",
            supports_navigation=True,
            default_skills=["visual_director", "copywriter", "ux_architect"],
            sections=[
                SectionSpec(
                    section_id="title_slide",
                    label="Title Slide",
                    template_name="hero_section.html.j2",
                    schema_class="HeroSectionData",
                    default_layout="hero",
                ),
                SectionSpec(
                    section_id="agenda",
                    label="Agenda",
                    template_name="content_block_section.html.j2",
                    schema_class="ContentBlockData",
                    default_layout="full",
                ),
                SectionSpec(
                    section_id="key_insights",
                    label="Key Insights",
                    template_name="insight_section.html.j2",
                    schema_class="InsightSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="data",
                    label="Data & Evidence",
                    template_name="chart_section.html.j2",
                    schema_class="ChartSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="timeline",
                    label="Timeline",
                    template_name="timeline_section.html.j2",
                    schema_class="TimelineSectionData",
                    default_layout="full",
                ),
                SectionSpec(
                    section_id="closing",
                    label="Closing",
                    template_name="cta_section.html.j2",
                    schema_class="CtaSectionData",
                    default_layout="hero",
                ),
            ],
        )
    )

    registry.register(
        ArtifactTypeDefinition(
            kind=ArtifactKind.REPORT,
            label="Report",
            description="Scrolling document with table of contents, sections, and findings",
            supports_pagination=True,
            default_skills=["copywriter", "data_viz", "ux_architect"],
            sections=[
                SectionSpec(
                    section_id="cover",
                    label="Cover Page",
                    template_name="hero_section.html.j2",
                    schema_class="HeroSectionData",
                    default_layout="hero",
                ),
                SectionSpec(
                    section_id="executive_summary",
                    label="Executive Summary",
                    template_name="content_block_section.html.j2",
                    schema_class="ContentBlockData",
                    default_layout="full",
                ),
                SectionSpec(
                    section_id="key_metrics",
                    label="Key Metrics",
                    template_name="stat_section.html.j2",
                    schema_class="StatSectionData",
                    default_layout="stat-showcase",
                ),
                SectionSpec(
                    section_id="findings",
                    label="Findings",
                    template_name="insight_section.html.j2",
                    schema_class="InsightSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="recommendations",
                    label="Recommendations",
                    template_name="content_block_section.html.j2",
                    schema_class="ContentBlockData",
                    default_layout="full",
                ),
            ],
        )
    )

    registry.register(
        ArtifactTypeDefinition(
            kind=ArtifactKind.ONE_PAGER,
            label="One-Pager",
            description="Single-page print-optimized executive summary",
            supports_navigation=False,
            default_skills=["copywriter", "visual_director"],
            sections=[
                SectionSpec(
                    section_id="header",
                    label="Header",
                    template_name="hero_section.html.j2",
                    schema_class="HeroSectionData",
                    default_layout="hero",
                ),
                SectionSpec(
                    section_id="value_prop",
                    label="Value Proposition",
                    template_name="content_block_section.html.j2",
                    schema_class="ContentBlockData",
                    default_layout="full",
                ),
                SectionSpec(
                    section_id="features",
                    label="Key Features",
                    template_name="insight_section.html.j2",
                    schema_class="InsightSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="social_proof",
                    label="Social Proof",
                    template_name="stat_section.html.j2",
                    schema_class="StatSectionData",
                    default_layout="stat-showcase",
                ),
                SectionSpec(
                    section_id="cta",
                    label="Call to Action",
                    template_name="cta_section.html.j2",
                    schema_class="CtaSectionData",
                    default_layout="full",
                ),
            ],
        )
    )

    registry.register(
        ArtifactTypeDefinition(
            kind=ArtifactKind.DASHBOARD,
            label="Dashboard",
            description="Data-heavy grid layout with KPIs, charts, and detailed metrics",
            supports_navigation=False,
            default_skills=["visual_director", "data_viz", "ux_architect"],
            sections=[
                SectionSpec(
                    section_id="header",
                    label="Dashboard Header",
                    template_name="hero_section.html.j2",
                    schema_class="HeroSectionData",
                    default_layout="hero",
                ),
                SectionSpec(
                    section_id="kpi_row",
                    label="KPI Overview",
                    template_name="stat_section.html.j2",
                    schema_class="StatSectionData",
                    default_layout="stat-showcase",
                ),
                SectionSpec(
                    section_id="charts",
                    label="Charts & Trends",
                    template_name="chart_section.html.j2",
                    schema_class="ChartSectionData",
                    default_layout="bento",
                ),
                SectionSpec(
                    section_id="details",
                    label="Detailed Breakdown",
                    template_name="insight_section.html.j2",
                    schema_class="InsightSectionData",
                    default_layout="bento",
                ),
            ],
        )
    )


_registry: ArtifactTypeRegistry | None = None


def get_registry() -> ArtifactTypeRegistry:
    """Get or create the singleton artifact type registry."""
    global _registry
    if _registry is None:
        _registry = ArtifactTypeRegistry()
        register_all(_registry)
    return _registry
