from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agentscope_blaiq.agents.content_director import ContentDirectorAgent
from agentscope_blaiq.contracts.evidence import EvidenceFinding, EvidencePack
from agentscope_blaiq.contracts.workflow import ArtifactFamily, ArtifactSpec, RequirementItem, RequirementsChecklist


def _make_evidence_pack(findings: list[EvidenceFinding] | None = None) -> EvidencePack:
    return EvidencePack(
        summary="Test evidence",
        memory_findings=findings or [],
        confidence=0.7,
    )


def _make_agent() -> ContentDirectorAgent:
    """Create a ContentDirectorAgent with a mock resolver that always fails (triggers fallback)."""
    agent = ContentDirectorAgent.__new__(ContentDirectorAgent)
    agent.name = "ContentDirectorAgent"
    agent.role = "content_director"
    agent.sys_prompt = "test"
    agent._log_sink = AsyncMock()
    # Mock resolver so acompletion() raises → forces _fallback_brief
    mock_resolver = MagicMock()
    mock_resolver.acompletion = AsyncMock(side_effect=RuntimeError("no LLM"))
    mock_resolver.settings = MagicMock()
    mock_resolver.settings.content_director_max_output_tokens = 4000
    agent.resolver = mock_resolver
    return agent


@pytest.mark.asyncio
async def test_content_director_fallback_brief_is_section_aware():
    agent = _make_agent()
    findings = [
        EvidenceFinding(finding_id="f1", title="Company Overview", summary="B&B is a premium hospitality brand.", confidence=0.8),
        EvidenceFinding(finding_id="f2", title="Market Position", summary="B&B holds 15% market share in luxury segment.", confidence=0.7),
    ]
    brief = await agent.plan_content(
        user_query="Create a pitch deck for B&B",
        evidence_summary="Evidence pack says the company needs an executive deck.",
        artifact_spec=ArtifactSpec(
            family=ArtifactFamily.pitch_deck,
            title="B&B Pitch Deck",
            audience="enterprise buyers",
            required_sections=["Hero", "Problem", "Solution", "Proof", "CTA"],
        ),
        requirements=RequirementsChecklist(
            items=[
                RequirementItem(requirement_id="section:hero", text="Provide the Hero."),
                RequirementItem(requirement_id="section:proof", text="Provide the Proof."),
            ]
        ),
        hitl_answers={"cta": "Book a demo"},
        evidence_pack=_make_evidence_pack(findings),
    )

    assert brief.audience == "enterprise buyers"
    assert brief.cta == "Book a demo"
    assert len(brief.section_plan) == 5
    # Fallback should use actual evidence findings, not the raw summary string
    assert "B&B" in brief.section_plan[0].core_message or "hospitality" in brief.section_plan[0].core_message
    assert brief.section_plan[0].objective


@pytest.mark.asyncio
async def test_content_director_finance_report_brief_uses_report_sections():
    agent = _make_agent()
    findings = [
        EvidenceFinding(finding_id="f1", title="Tesla Revenue", summary="Tesla reported Q4 revenue of $25.2B.", confidence=0.9),
    ]
    brief = await agent.plan_content(
        user_query="Analyze Tesla's Q4 2024 financial performance",
        evidence_summary="Tesla evidence pack with filings and market context.",
        artifact_spec=ArtifactSpec(
            family=ArtifactFamily.finance_analysis,
            title="Tesla Q4 2024 Finance Analysis",
            audience="investors",
            required_sections=["Thesis", "Hypotheses", "Evidence", "Risks", "Recommendation"],
        ),
        requirements=RequirementsChecklist(
            items=[
                RequirementItem(requirement_id="section:thesis", text="Provide the Thesis."),
                RequirementItem(requirement_id="section:evidence", text="Provide the Evidence."),
            ]
        ),
        hitl_answers={"analysis_objective": "Assess whether the trend is improving"},
        evidence_pack=_make_evidence_pack(findings),
    )

    assert brief.template_name == "finance-analysis-executive"
    assert brief.family == "finance_analysis"
    assert [section.title for section in brief.section_plan] == ["Thesis", "Hypotheses", "Evidence", "Risks", "Recommendation"]
    assert brief.section_plan[0].objective


@pytest.mark.asyncio
async def test_content_director_poster_slides_set_poster_layout_on_fallback():
    agent = _make_agent()
    findings = [
        EvidenceFinding(
            finding_id="f1",
            title="Launch date",
            summary="The launch event is on May 12 in Berlin with a live product demo.",
            confidence=0.9,
        ),
    ]

    slides = await agent.plan_slides(
        user_query="Create a poster for the Berlin launch event",
        artifact_family="poster",
        evidence_pack=_make_evidence_pack(findings),
        hitl_answers={"cta": "Register today"},
        brand_dna={"tokens": {"background": "#000000"}},
        tenant_id="tenant-1",
    )

    assert slides.layout == "poster"
    assert slides.brand == "tenant-1"
    assert [slide.type for slide in slides.slides] == ["hero", "bullets", "evidence", "cta"]
