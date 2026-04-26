from __future__ import annotations
import re
import logging
from typing import TYPE_CHECKING
from agentscope_blaiq.agents.content_director.models import SlidesData, SlideData

if TYPE_CHECKING:
    from agentscope_blaiq.contracts.evidence import EvidencePack

logger = logging.getLogger(__name__)

def fallback_slides(
    *,
    user_query: str,
    evidence_pack: "EvidencePack" | None = None,
    hitl_answers: dict[str, str] | None = None,
    tenant_id: str = "default",
    required_sections: list[str] | None = None,
    artifact_family: str = "pitch_deck",
    is_usable_finding_fn: callable,
    default_pitch_deck_sections_fn: callable,
    is_pitch_deck_family_fn: callable,
    section_title_to_request_fn: callable,
    pitch_deck_research_groups_fn: callable,
) -> SlidesData:
    """Build a deterministic SlidesData from evidence when the LLM fails."""
    all_findings = []
    if evidence_pack:
        memory = [f for f in evidence_pack.memory_findings if is_usable_finding_fn(f)]
        docs = [f for f in evidence_pack.doc_findings if is_usable_finding_fn(f)]
        web = [f for f in evidence_pack.web_findings if is_usable_finding_fn(f)]
        memory.sort(key=lambda f: f.confidence, reverse=True)
        docs.sort(key=lambda f: f.confidence, reverse=True)
        web.sort(key=lambda f: f.confidence, reverse=True)
        all_findings = memory + docs + web

    top_5 = all_findings[:5]
    hitl = {k.lower(): v for k, v in (hitl_answers or {}).items()}
    section_names = [s for s in (required_sections or []) if s]
    if not section_names:
        section_names = default_pitch_deck_sections_fn() if is_pitch_deck_family_fn(artifact_family) else ["Hero", "Problem", "Solution", "Proof", "CTA"]
    requested_count = None
    match = re.search(r"\b(\d+)\s*[- ]?(?:slide|slides|section|sections)\b", user_query.lower())
    if match:
        try:
            requested_count = int(match.group(1))
        except Exception:
            requested_count = None
    if requested_count and requested_count > len(section_names):
        for idx in range(len(section_names) + 1, requested_count + 1):
            section_names.append(f"Section {idx}")

    def _section_answer(title: str) -> str:
        key = title.strip().lower().replace(" ", "_")
        direct = hitl.get(f"section:{key}") or hitl.get(key)
        if direct:
            return direct
        if key == "cta":
            return hitl.get("section:cta") or hitl.get("cta", "")
        return ""

    slides: list[SlideData] = []
    for idx, section_title in enumerate(section_names):
        section_key = section_title.strip().lower()
        answer_text = _section_answer(section_title)
        finding = top_5[min(idx, len(top_5) - 1)] if top_5 else None
        default_body = finding.summary if finding else user_query
        body = answer_text or default_body
        speaker_notes = ""
        research_requests = [section_title_to_request_fn(section_title, user_query, hitl_answers)]

        if section_key in {"hero", "opening"}:
            speaker_notes = "Lead with the core promise and avoid over-explaining."
            slides.append(SlideData(type="hero", headline=section_title, subheadline=user_query, body=body, research_requests=research_requests, speaker_notes=speaker_notes))
        elif section_key in {"proof", "evidence"}:
            items = []
            if top_5:
                items = [{"finding": f.summary, "source": f.title, "confidence": str(f.confidence)} for f in top_5]
            elif body:
                items = [{"finding": body, "source": "HITL", "confidence": "n/a"}]
            speaker_notes = "Use concrete proof and keep sources visible."
            slides.append(SlideData(type="evidence", title=section_title, items=items, research_requests=research_requests, speaker_notes=speaker_notes))
        elif section_key in {"cta", "next_steps", "next steps"}:
            speaker_notes = "End with a specific meeting ask or partnership action."
            slides.append(SlideData(type="cta", headline=section_title, body=body or "Define the next action.", research_requests=research_requests, speaker_notes=speaker_notes))
        else:
            bullets = []
            if answer_text:
                bullets.append(answer_text)
            if finding:
                bullets.append(finding.summary)
            if not bullets:
                bullets.append(default_body)
            speaker_notes = "Make each bullet one idea and keep the slide scan-friendly."
            slides.append(SlideData(type="bullets", title=section_title, bullets=bullets[:5], research_requests=research_requests, speaker_notes=speaker_notes))

    metadata = {
        "slide_count_target": 6 if len(section_names) >= 5 else len(section_names),
        "followup_research_requests": pitch_deck_research_groups_fn(
            user_query=user_query,
            section_titles=section_names,
            hitl_answers=hitl_answers,
        ) if len(section_names) >= 5 else [],
    }

    return SlidesData(
        title=user_query,
        brand=tenant_id,
        layout="slides",
        slides=slides,
        metadata=metadata,
    )
