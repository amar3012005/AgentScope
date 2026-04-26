from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from agentscope_blaiq.contracts.workflow import ArtifactSpec
    from agentscope_blaiq.agents.content_director.planning import template_name_for_family

def build_artifact_brief_prompt(
    *,
    user_query: str,
    artifact_spec: "ArtifactSpec",
    evidence_text: str,
    evidence_summary: str,
    hitl_text: str,
    section_titles: list[str],
    artifact_family_value_fn: callable,
    template_name_fn: callable,
) -> str:
    schema_hint = {
        "brief_id": "string",
        "thread_id": "string",
        "artifact_family": artifact_family_value_fn(artifact_spec.family),
        "title": "string",
        "core_narrative": "string",
        "target_audience": artifact_spec.audience or "general",
        "sections": [
            {
                "section_id": "section-1",
                "title": "string",
                "objective": "string",
                "key_points": ["string"],
                "evidence_refs": ["finding_id"],
                "visual_hint": "string",
                "constraints": ["string"],
                "research_requests": ["string"],
                "speaker_notes": "string",
            }
        ],
        "brand_voice_id": "optional-string",
        "style_preference": artifact_spec.tone or "executive",
        "evidence_pack_id": "string",
        "required_disclaimers": [],
        "metadata": {"template_name": template_name_fn(artifact_spec.family)},
    }
    return (
        "Create an ArtifactBrief JSON only. Keep it concise and evidence-anchored.\n"
        f"Request: {user_query}\n"
        f"Artifact Family: {artifact_family_value_fn(artifact_spec.family)}\n"
        f"Audience: {artifact_spec.audience or 'general'}\n"
        f"Tone: {artifact_spec.tone or 'professional'}\n"
        f"Required Sections: {', '.join(section_titles)}\n\n"
        "If this is a pitch deck or keynote, produce a compact 5-6 section deck blueprint with slide-specific objectives, evidence_refs, and short research_requests for any unresolved claims.\n\n"
        "Evidence:\n"
        f"{evidence_text}\n\n"
        "Evidence Summary:\n"
        f"{evidence_summary or 'None'}\n\n"
        "HITL Answers:\n"
        f"{hitl_text}\n\n"
        "Requirements:\n"
        "- sections must include objective, key_points, and evidence_refs\n"
        "- keep claims supported by evidence_refs\n"
        "- include visual_hint per section\n\n"
        "Return JSON matching this shape:\n"
        f"{schema_hint}"
    )
