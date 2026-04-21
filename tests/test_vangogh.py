from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscope_blaiq.agents.vangogh import VangoghAgent
from agentscope_blaiq.contracts.evidence import Citation, EvidenceFinding, EvidencePack, EvidenceProvenance, SourceRecord


class NoLLMVangogh(VangoghAgent):
    async def complete_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("LLM unavailable for test")


@pytest.mark.asyncio
async def test_vangogh_renders_all_planned_sections():
    agent = NoLLMVangogh()
    evidence = EvidencePack(
        summary="Strong evidence pack.",
        sources=[
            SourceRecord(source_id="source-1", source_type="memory", title="Memory 1", location="memory://1"),
            SourceRecord(source_id="source-2", source_type="upload", title="Upload 1", location="/tmp/upload.txt"),
        ],
        memory_findings=[
            EvidenceFinding(finding_id="memory-1", title="Memory 1", summary="Project memory", source_ids=["source-1"], confidence=0.9),
        ],
        citations=[
            Citation(source_id="source-1", label="Memory 1", excerpt="Project memory"),
            Citation(source_id="source-2", label="Upload 1", excerpt="Upload evidence"),
        ],
        provenance=EvidenceProvenance(memory_sources=1, upload_sources=1, primary_ground_truth="memory", save_back_eligible=True),
    )

    artifact = await agent.generate(
        "Create a pitch deck",
        evidence,
        content_brief={
            "title": "Create a pitch deck",
            "family": "pitch_deck",
            "template_name": "pitch_deck-executive",
            "narrative": "Executive narrative",
            "visual_direction": "Bold executive layout",
            "section_plan": [
                {
                    "section_id": "hero",
                    "title": "Hero",
                    "purpose": "Opening",
                    "objective": "Set the angle",
                    "core_message": "Main message",
                    "evidence_refs": ["source-1"],
                    "visual_intent": "Strong hero frame",
                    "cta": "Keep reading",
                },
                {
                    "section_id": "problem",
                    "title": "Problem",
                    "purpose": "Context",
                    "objective": "Frame the problem",
                    "core_message": "Problem statement",
                    "evidence_refs": ["source-2"],
                    "visual_intent": "Contrast panel",
                },
                {
                    "section_id": "solution",
                    "title": "Solution",
                    "purpose": "Resolution",
                    "objective": "Show the solution",
                    "core_message": "Solution statement",
                    "evidence_refs": ["source-1", "source-2"],
                    "visual_intent": "Benefit grid",
                },
            ],
        },
    )

    assert [section.title for section in artifact.sections] == ["Hero", "Problem", "Solution"]
    # Summary is now headline or core_message (not the old concatenated string)
    assert "Main message" in artifact.sections[0].summary
    assert "Problem statement" in artifact.html or "Problem" in artifact.html
    assert "Solution statement" in artifact.html or "Solution" in artifact.html
    assert artifact.evidence_refs == ["source-1", "source-2"]


@pytest.mark.asyncio
async def test_vangogh_renders_finance_analysis_sections():
    agent = NoLLMVangogh()
    evidence = EvidencePack(
        summary="Finance evidence pack.",
        sources=[
            SourceRecord(source_id="source-1", source_type="memory", title="Memory 1", location="memory://1"),
        ],
        citations=[
            Citation(source_id="source-1", label="Memory 1", excerpt="Finance memory"),
        ],
        provenance=EvidenceProvenance(memory_sources=1, primary_ground_truth="memory", save_back_eligible=True),
    )

    artifact = await agent.generate(
        "Analyze Tesla's Q4 2024 financial performance",
        evidence,
        content_brief={
            "title": "Tesla Q4 2024 Finance Analysis",
            "family": "finance_analysis",
            "template_name": "finance-analysis-executive",
            "narrative": "Report narrative",
            "visual_direction": "Analytical report layout",
            "section_plan": [
                {
                    "section_id": "thesis",
                    "title": "Thesis",
                    "purpose": "State the investment thesis",
                    "objective": "Summarize the conclusion",
                    "core_message": "Tesla has improving operating leverage.",
                    "evidence_refs": ["source-1"],
                    "visual_intent": "Bold thesis callout",
                    "cta": "Review the evidence",
                },
                {
                    "section_id": "recommendation",
                    "title": "Recommendation",
                    "purpose": "State the recommendation",
                    "objective": "Close with a decision",
                    "core_message": "Hold pending further evidence.",
                    "evidence_refs": ["source-1"],
                    "visual_intent": "Decision box",
                },
            ],
        },
    )

    assert [section.title for section in artifact.sections] == ["Thesis", "Recommendation"]
    assert "Tesla has improving operating leverage." in artifact.html
    assert "Hold pending further evidence." in artifact.html


def test_vangogh_writes_poster_layout_for_bundle_workspace(tmp_path: Path):
    agent = NoLLMVangogh()
    workspace = tmp_path / "workspace"
    src_dir = workspace / "src"
    src_dir.mkdir(parents=True)

    agent._write_slides_data(
        workspace,
        {
            "title": "Poster",
            "brand": "tenant-1",
            "slides": [
                {"type": "hero", "headline": "Launch"},
                {"type": "data_grid", "title": "At a Glance", "items": []},
                {"type": "cta", "headline": "Join Us"},
            ],
        },
        artifact_family="poster",
    )

    payload = json.loads((src_dir / "slides.json").read_text(encoding="utf-8"))
    assert payload["layout"] == "poster"
    assert payload["slides"][0]["type"] == "hero"
