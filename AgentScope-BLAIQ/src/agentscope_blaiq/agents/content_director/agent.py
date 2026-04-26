from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, TYPE_CHECKING

from agentscope.tool import Toolkit

from agentscope_blaiq.agents.skills import load_skill, load_brand_context
from agentscope_blaiq.contracts.brief import ArtifactBrief, BriefSection
from agentscope_blaiq.contracts.messages import make_agent_input, make_agent_output
from agentscope_blaiq.contracts.workflow import ArtifactFamily, ArtifactSpec, RequirementsChecklist
from agentscope_blaiq.contracts.agent_catalog import AgentCapability, AgentSkill
from agentscope_blaiq.runtime.agent_base import BaseAgent

from agentscope_blaiq.agents.content_director.models import (
    ContentSectionPlan,
    ContentBrief,
    SlideData,
    SlidesData,
    _section_defaults
)
from agentscope_blaiq.agents.content_director.evidence import (
    is_usable_finding,
    format_evidence_for_prompt,
    build_enriched_evidence_context
)
from agentscope_blaiq.agents.content_director.planning import (
    is_pitch_deck_family,
    default_pitch_deck_sections,
    section_title_to_request,
    pitch_deck_research_groups,
    template_name_for_family
)
from agentscope_blaiq.agents.content_director.handoff import build_artifact_brief_prompt
from agentscope_blaiq.agents.content_director.fallbacks import fallback_slides

if TYPE_CHECKING:
    from agentscope_blaiq.contracts.evidence import EvidencePack

logger = logging.getLogger(__name__)

_VISUAL_FAMILIES = ["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "finance_analysis"]


from agentscope_blaiq.agents.content_director.tools.planning import content_distribution, section_planning
from agentscope_blaiq.agents.content_director.tools.templates import template_selection
from agentscope_blaiq.agents.content_director.tools.briefing import render_brief_generation

class ContentDirectorAgent(BaseAgent):
    # Self-declared profile — add a capability here to propagate to the planner catalog.
    CAPABILITIES: list[AgentCapability] = [
        AgentCapability(
            name="content_distribution",
            description="Map requirements into a section-by-section content plan.",
            supported_task_types=["planning", "content"],
            supported_task_roles=["content_director"],
            supported_artifact_families=_VISUAL_FAMILIES,
        ),
        AgentCapability(
            name="section_planning",
            description="Plan content sections and their ordering.",
            supported_task_types=["planning", "content"],
            supported_task_roles=["content_director"],
            supported_artifact_families=_VISUAL_FAMILIES,
        ),
    ]

    SKILLS: list[AgentSkill] = [
        AgentSkill(name="template_selection", level="core"),
        AgentSkill(name="render_brief_generation", level="core"),
    ]

    TOOLS: list[str] = ["content_distribution", "section_planning", "template_selection", "render_brief_generation"]
    PLANNER_ROLES: list[str] = ["content_director"]

    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="ContentDirectorAgent",
            role="content_director",
            sys_prompt=(
                "You are a senior creative director. Your sole responsibility is to transform research "
                "findings into a structured ArtifactBrief. You do NOT perform research or render final HTML.\n\n"
                "Focus on:\n"
                "1. Narrative Flow: Ensure sections build a coherent story (Problem -> Solution -> Proof).\n"
                "2. Sectional Objectives: Define exactly what each section should achieve.\n"
                "3. Key Points: Extract the most impactful 3-5 points from evidence for each section.\n"
                "4. Visual Hints: Recommend layout patterns (e.g., 'hero-centered', 'metric-grid').\n\n"
                "Your output must be a valid ArtifactBrief JSON which guides the downstream renderers."
            ),
            **kwargs,
        )

    async def reply(self, msg: Msg | str, *, extra_context: dict[str, Any] | None = None) -> Msg:
        """Execute the ContentDirector planning cycle via ReAct worker."""
        agent = self._create_runtime_agent()
        user_text = msg.content if isinstance(msg, Msg) else str(msg)
        
        # Build a context-rich prompt for the ReAct agent
        context = extra_context or {}
        requirements = context.get("requirements", "No specific requirements provided.")
        family = context.get("artifact_family", "custom")
        evidence_summary = context.get("evidence_summary", "No evidence summary available.")
        hitl_answers = context.get("hitl_answers", {})
        
        instruction = (
            f"Plan a {family} artifact for the request: '{user_text}'.\n\n"
            f"Requirements:\n{requirements}\n\n"
            f"Evidence Summary:\n{evidence_summary}\n\n"
            f"User Guidelines (HITL):\n{hitl_answers}\n\n"
            "Steps:\n"
            "1. Use 'content_distribution' to map the narrative flow.\n"
            "2. Use 'section_planning' to define objectives for each section.\n"
            "3. Use 'template_selection' to choose the right rendering template.\n"
            "4. Finally, use 'render_brief_generation' to produce the final ArtifactBrief JSON."
        )

        runtime_msg = self.make_msg(
            instruction,
            role="user",
            phase="content_director",
        )
        return await agent.reply(runtime_msg)

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        self.register_tool(toolkit, tool_id="content_distribution", fn=content_distribution, description="Decide how content should be distributed across sections.")
        self.register_tool(toolkit, tool_id="section_planning", fn=section_planning, description="Produce a section-by-section plan from requirements and evidence.")
        self.register_tool(toolkit, tool_id="template_selection", fn=template_selection, description="Select a template direction for the renderer.")
        self.register_tool(toolkit, tool_id="render_brief_generation", fn=render_brief_generation, description="Generate the renderer handoff brief.")
        return toolkit

    def _normalize_slide_bundle(
        self,
        *,
        slides: SlidesData,
        artifact_family: str,
        user_query: str,
        hitl_answers: dict[str, str] | None,
        required_sections: list[str] | None,
    ) -> SlidesData:
        if not is_pitch_deck_family(artifact_family):
            if not slides.metadata:
                slides.metadata = {}
            return slides

        minimum_sections = 5
        maximum_sections = 6
        section_titles = required_sections or default_pitch_deck_sections()

        if len(slides.slides) < minimum_sections:
            logger.warning(
                "Pitch deck slides underfilled (%d < %d); falling back to deterministic 6-slide structure.",
                len(slides.slides),
                minimum_sections,
            )
            slides = self._fallback_slides(
                user_query=user_query,
                evidence_pack=None,
                hitl_answers=hitl_answers,
                tenant_id=slides.brand,
                required_sections=section_titles,
                artifact_family=artifact_family,
            )
        elif len(slides.slides) > maximum_sections:
            slides.slides = slides.slides[:maximum_sections]

        for index, slide in enumerate(slides.slides):
            if not slide.research_requests:
                slide.research_requests = [section_title_to_request(section_titles[min(index, len(section_titles) - 1)], user_query, hitl_answers)]
            if not slide.speaker_notes:
                slide.speaker_notes = slide.headline or slide.title or section_titles[min(index, len(section_titles) - 1)]

        slide_groups = pitch_deck_research_groups(
            user_query=user_query,
            section_titles=section_titles[:maximum_sections],
            hitl_answers=hitl_answers,
        )
        slides.metadata = {
            **(slides.metadata or {}),
            "slide_count_target": maximum_sections,
            "followup_research_requests": slide_groups,
        }
        return slides

    def _content_brief_to_artifact_brief(
        self,
        *,
        brief: ContentBrief,
        artifact_spec: ArtifactSpec,
        evidence_pack: EvidencePack | None = None,
    ) -> ArtifactBrief:
        sections: list[BriefSection] = []
        for section in brief.section_plan:
            key_points = section.bullets or ([section.core_message] if section.core_message else [])
            sections.append(
                BriefSection(
                    section_id=section.section_id,
                    title=section.title,
                    objective=section.objective or section.purpose or f"Cover {section.title}",
                    key_points=[point for point in key_points if point],
                    evidence_refs=section.evidence_refs,
                    visual_hint=section.visual_intent or None,
                    constraints=section.acceptance_checks,
                    research_requests=section.notes[:3],
                    speaker_notes=section.core_message or section.purpose,
                )
            )

        evidence_pack_id = "ep-unknown"
        if evidence_pack and evidence_pack.metadata:
            evidence_pack_id = str(
                evidence_pack.metadata.get("evidence_pack_id")
                or evidence_pack.metadata.get("pack_id")
                or evidence_pack_id
            )

        return ArtifactBrief(
            brief_id=f"brief-{uuid4().hex[:12]}",
            thread_id="workflow-thread",
            artifact_family=ArtifactFamily(brief.family) if brief.family in ArtifactFamily.__members__ else ArtifactFamily.custom,
            title=brief.title,
            core_narrative=brief.narrative or brief.core_message or brief.title,
            target_audience=brief.audience or artifact_spec.audience or "general",
            sections=sections,
            style_preference=artifact_spec.tone or "executive",
            evidence_pack_id=evidence_pack_id,
            required_disclaimers=[risk for risk in brief.risks if risk],
            metadata={
                "template_name": brief.template_name,
                "visual_direction": brief.visual_direction,
                "cta": brief.cta,
                "acceptance_checks": brief.acceptance_checks,
                "distribution_notes": brief.distribution_notes,
                "handoff_notes": brief.handoff_notes,
            },
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _artifact_brief_to_content_brief(
        self,
        *,
        artifact_brief: ArtifactBrief,
        artifact_spec: ArtifactSpec,
        hitl_answers: dict[str, str] | None,
    ) -> ContentBrief:
        section_plan: list[ContentSectionPlan] = []
        for section in artifact_brief.sections:
            defaults = _section_defaults(section.title)
            section_plan.append(
                ContentSectionPlan(
                    section_id=section.section_id,
                    title=section.title,
                    purpose=defaults["purpose"],
                    objective=section.objective,
                    audience=artifact_brief.target_audience,
                    core_message=" ".join(section.key_points[:2]),
                    bullets=section.key_points,
                    evidence_refs=section.evidence_refs,
                    visual_intent=section.visual_intent or defaults["visual_intent"],
                    acceptance_checks=section.constraints,
                )
            )

        metadata = artifact_brief.metadata or {}
        return ContentBrief(
            title=artifact_brief.title,
            family=artifact_brief.artifact_family.value if isinstance(artifact_brief.artifact_family, ArtifactFamily) else str(artifact_brief.artifact_family),
            template_name=str(metadata.get("template_name") or template_name_for_family(artifact_brief.artifact_family)),
            narrative=artifact_brief.core_narrative,
            audience=artifact_brief.target_audience,
            core_message=artifact_brief.core_narrative,
            visual_direction=str(metadata.get("visual_direction") or f"{artifact_spec.tone} {artifact_spec.family.value} layout"),
            cta=str(metadata.get("cta") or (hitl_answers or {}).get("cta", "")),
            risks=[d for d in artifact_brief.required_disclaimers if d],
            acceptance_checks=list(metadata.get("acceptance_checks", [])),
            section_plan=section_plan,
            distribution_notes=list(metadata.get("distribution_notes", [])),
            handoff_notes=list(metadata.get("handoff_notes", [])),
        )

    def _fallback_artifact_brief(
        self,
        *,
        user_query: str,
        evidence_summary: str,
        artifact_spec: ArtifactSpec,
        requirements: RequirementsChecklist,
        hitl_answers: dict[str, str] | None,
        evidence_pack: EvidencePack | None = None,
    ) -> ArtifactBrief:
        legacy = self._fallback_brief(
            user_query=user_query,
            evidence_summary=evidence_summary,
            artifact_spec=artifact_spec,
            requirements=requirements,
            hitl_answers=hitl_answers,
            evidence_pack=evidence_pack,
        )
        return self._content_brief_to_artifact_brief(
            brief=legacy,
            artifact_spec=artifact_spec,
            evidence_pack=evidence_pack,
        )

    async def plan_artifact_brief(
        self,
        *,
        user_query: str,
        evidence_summary: str,
        artifact_spec: ArtifactSpec,
        requirements: RequirementsChecklist,
        hitl_answers: dict[str, str] | None = None,
        evidence_pack: EvidencePack | None = None,
    ) -> ArtifactBrief:
        evidence_text = format_evidence_for_prompt(evidence_pack)
        hitl_text = "\n".join(f"- {k}: {v}" for k, v in (hitl_answers or {}).items()) or "None"
        section_titles = artifact_spec.required_sections or ["Hero", "Evidence", "CTA"]
        summary = evidence_summary
        if evidence_pack and evidence_pack.summary and len(evidence_pack.summary) > 30:
            summary = evidence_pack.summary

        prompt = build_artifact_brief_prompt(
            user_query=user_query,
            artifact_spec=artifact_spec,
            evidence_text=evidence_text,
            evidence_summary=summary,
            hitl_text=hitl_text,
            section_titles=section_titles,
            artifact_family_value_fn=lambda f: f.value if isinstance(f, ArtifactFamily) else str(f),
            template_name_fn=template_name_for_family,
        )

        try:
            response = await self.resolver.acompletion(
                "content_director",
                [
                    {"role": "system", "content": self.sys_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.resolver.settings.content_director_max_output_tokens,
                temperature=0.2,
            )
            raw = self.resolver.extract_text(response)
            artifact_brief = ArtifactBrief.model_validate(self.resolver.safe_json_loads(raw))
        except Exception:
            artifact_brief = self._fallback_artifact_brief(
                user_query=user_query,
                evidence_summary=summary,
                artifact_spec=artifact_spec,
                requirements=requirements,
                hitl_answers=hitl_answers,
                evidence_pack=evidence_pack,
            )

        if not artifact_brief.sections:
            artifact_brief = self._fallback_artifact_brief(
                user_query=user_query,
                evidence_summary=summary,
                artifact_spec=artifact_spec,
                requirements=requirements,
                hitl_answers=hitl_answers,
                evidence_pack=evidence_pack,
            )

        return artifact_brief

    def _fallback_brief(
        self,
        *,
        user_query: str,
        evidence_summary: str,
        artifact_spec: ArtifactSpec,
        requirements: RequirementsChecklist,
        hitl_answers: dict[str, str] | None,
        evidence_pack: EvidencePack | None = None,
    ) -> ContentBrief:
        section_names = artifact_spec.required_sections or ["Hero", "Evidence"]
        # Memory findings (HIVE-MIND) are the primary ground truth.
        # Filter out garbage: smoke tests, raw PDF bytes, empty content.
        all_findings = []
        if evidence_pack:
            memory = [f for f in evidence_pack.memory_findings if is_usable_finding(f)]
            docs = [f for f in evidence_pack.doc_findings if is_usable_finding(f)]
            web = [f for f in evidence_pack.web_findings if is_usable_finding(f)]
            memory.sort(key=lambda f: f.confidence, reverse=True)
            docs.sort(key=lambda f: f.confidence, reverse=True)
            web.sort(key=lambda f: f.confidence, reverse=True)
            all_findings = memory + docs + web

        hitl_str = ""
        if hitl_answers:
            hitl_str = " | ".join(f"{k}: {v}" for k, v in hitl_answers.items())

        section_plan = []
        for index, section_title in enumerate(section_names):
            defaults = _section_defaults(section_title)
            # pick the most relevant finding for this section
            relevant = all_findings[min(index, len(all_findings) - 1)] if all_findings else None
            # Core message: HITL answers + finding content — HITL is the user's direct input
            core_parts = []
            if hitl_str:
                core_parts.append(hitl_str)
            if relevant:
                core_parts.append(relevant.summary)
            core_msg = " | ".join(core_parts) if core_parts else user_query

            section_plan.append(
                ContentSectionPlan(
                    section_id=f"section-{index + 1}",
                    title=section_title,
                    purpose=defaults["purpose"],
                    source_refs=[],
                    notes=[],
                    objective=defaults["purpose"],
                    audience=artifact_spec.audience,
                    core_message=core_msg,
                    evidence_refs=[relevant.finding_id for relevant in ([relevant] if relevant else [])],
                    visual_intent=defaults["visual_intent"],
                    cta=(hitl_answers or {}).get("cta", "") if section_title.lower() == "cta" else "",
                    risks=[],
                    acceptance_checks=[f"{section_title} is supported by evidence and aligned to the plan."],
                )
            )

        narrative = (
            all_findings[0].summary if all_findings
            else (hitl_str or user_query)
        )

        return ContentBrief(
            title=artifact_spec.title or user_query,
            family=artifact_spec.family.value,
            template_name=template_name_for_family(artifact_spec.family),
            narrative=narrative,
            audience=artifact_spec.audience,
            core_message=narrative,
            visual_direction=f"{artifact_spec.tone} {artifact_spec.family.value} layout",
            cta=(hitl_answers or {}).get("cta", ""),
            risks=["Do not add unsupported claims.", "Keep the artifact aligned to the evidence and user answers."],
            acceptance_checks=[
                "The artifact has a clear opening, evidence, and close.",
                "Each section contains specific content from the evidence.",
            ],
            section_plan=section_plan,
            distribution_notes=["Use the strongest evidence first.", "Each section must have real copy."],
            handoff_notes=[
                "Final render should reflect the accepted HITL answers.",
                f"Answered fields: {', '.join(sorted(hitl_answers or {})) or 'none'}",
            ],
        )

    async def plan_content(
        self,
        *,
        user_query: str,
        evidence_summary: str,
        artifact_spec: ArtifactSpec,
        requirements: RequirementsChecklist,
        hitl_answers: dict[str, str] | None = None,
        evidence_pack: EvidencePack | None = None,
    ) -> ContentBrief:
        input_msg = make_agent_input(
            workflow_id=None,
            node_id="content_director",
            agent_id="content_director",
            payload={"family": artifact_spec.family.value, "user_query": user_query},
            schema_ref="ContentDirectorInput",
        )
        logger.debug("content_director input_msg=%s", input_msg.msg_id)

        artifact_brief = await self.plan_artifact_brief(
            user_query=user_query,
            evidence_summary=evidence_summary,
            artifact_spec=artifact_spec,
            requirements=requirements,
            hitl_answers=hitl_answers,
            evidence_pack=evidence_pack,
        )
        brief = self._artifact_brief_to_content_brief(
            artifact_brief=artifact_brief,
            artifact_spec=artifact_spec,
            hitl_answers=hitl_answers,
        )

        # Validate: each section must have objective, evidence_refs, and visual_intent
        missing_fields: list[str] = []
        for section in brief.section_plan:
            if not section.objective:
                missing_fields.append(f"section '{section.title}' missing objective")
            if not section.evidence_refs:
                missing_fields.append(f"section '{section.title}' missing evidence_refs")
            if not section.visual_intent:
                missing_fields.append(f"section '{section.title}' missing visual_intent")
        if missing_fields:
            logger.warning(
                "content_director acceptance_check: %d issues in %s",
                len(missing_fields), brief.title,
            )
            for issue in missing_fields[:5]:
                logger.warning("  - %s", issue)

        output_msg = make_agent_output(
            input_msg=input_msg,
            payload={"title": brief.title, "section_count": len(brief.section_plan), "brief_id": artifact_brief.brief_id},
            schema_ref="ArtifactBrief",
        )
        logger.debug("content_director output_msg=%s parent=%s", output_msg.msg_id, output_msg.parent_msg_id)
        return brief

    # ------------------------------------------------------------------
    # plan_slides — structured slides.json output using the skills system
    # ------------------------------------------------------------------

    async def plan_slides(
        self,
        *,
        user_query: str,
        artifact_family: str,  # "pitch_deck", "poster", etc.
        evidence_pack: EvidencePack | None = None,
        hitl_answers: dict[str, str] | None = None,
        brand_dna: dict | None = None,
        tenant_id: str = "default",
        required_sections: list[str] | None = None,
    ) -> SlidesData:
        """Generate a structured SlidesData object using artifact-specific skills."""
        pitch_deck_mode = is_pitch_deck_family(artifact_family)
        effective_required_sections = required_sections or (
            default_pitch_deck_sections() if pitch_deck_mode else None
        )

        # 1. Load skill and brand context
        skill_text = load_skill(artifact_family, "content")
        brand_context = load_brand_context(brand_dna)

        # 2. Format evidence findings
        evidence_text = format_evidence_for_prompt(evidence_pack, max_findings=15)

        # 3. Format HITL answers
        hitl_text = (
            "\n".join(f"- {k}: {v}" for k, v in hitl_answers.items())
            if hitl_answers else "None"
        )

        # 4. Build messages with skill in SYSTEM, evidence+query in USER
        system_message = f"{skill_text}\n\n{brand_context}"

        evidence_summary = ""
        if evidence_pack and evidence_pack.summary and len(evidence_pack.summary) > 30:
            evidence_summary = evidence_pack.summary

        user_message = f"""IMPORTANT — READ THE EVIDENCE FIRST BEFORE INTERPRETING THE REQUEST.

=== EVIDENCE FROM ENTERPRISE MEMORY (this defines what the request is about) ===
{evidence_text}

=== EVIDENCE SYNTHESIS ===
{evidence_summary or "See individual findings above."}

=== USER ANSWERS ===
{hitl_text}

=== NOW GENERATE slides.json FOR THIS REQUEST ===
REQUEST: {user_query}
ARTIFACT TYPE: {artifact_family}
TARGET SLIDE COUNT: {'5-6' if pitch_deck_mode else 'as needed'}
REQUIRED SLIDE OUTLINE: {', '.join(effective_required_sections or []) or 'derive from evidence'}

CRITICAL: The meaning of any acronyms, names, or terms in the request MUST be
interpreted based on the evidence above, NOT from your training data.

=== AVAILABLE SLIDE TYPES ===
1. metrics_dashboard, 2. analysis_chart, 3. data_table, 4. insight_cards, 5. hero, 6. data_grid, 7. bullets, 8. evidence, 9. cta, 10. quote

Return ONLY valid JSON matching the SlidesData schema."""

        try:
            response = await self.resolver.acompletion(
                "content_director",
                [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=self.resolver.settings.content_director_max_output_tokens,
                temperature=0.2,
            )
            raw = self.resolver.extract_text(response)
            payload = self.resolver.safe_json_loads(raw)
            slides = SlidesData.model_validate(payload)
        except Exception:
            logger.warning("LLM slides generation failed for '%s'; using deterministic fallback.", artifact_family, exc_info=True)
            slides = self._fallback_slides(
                user_query=user_query,
                evidence_pack=evidence_pack,
                hitl_answers=hitl_answers,
                tenant_id=tenant_id,
                required_sections=effective_required_sections,
                artifact_family=artifact_family,
            )

        if not slides.slides or (effective_required_sections and len(slides.slides) < len(effective_required_sections)):
            slides = self._fallback_slides(
                user_query=user_query,
                evidence_pack=evidence_pack,
                hitl_answers=hitl_answers,
                tenant_id=tenant_id,
                required_sections=effective_required_sections,
                artifact_family=artifact_family,
            )

        expected_layout = "poster" if artifact_family == "poster" else "slides"
        if slides.layout != expected_layout:
            slides.layout = expected_layout

        slides = self._normalize_slide_bundle(
            slides=slides,
            artifact_family=artifact_family,
            user_query=user_query,
            hitl_answers=hitl_answers,
            required_sections=effective_required_sections,
        )
        return slides

    def _fallback_slides(
        self,
        *,
        user_query: str,
        evidence_pack: EvidencePack | None = None,
        hitl_answers: dict[str, str] | None = None,
        tenant_id: str = "default",
        required_sections: list[str] | None = None,
        artifact_family: str = "pitch_deck",
    ) -> SlidesData:
        return fallback_slides(
            user_query=user_query,
            evidence_pack=evidence_pack,
            hitl_answers=hitl_answers,
            tenant_id=tenant_id,
            required_sections=required_sections,
            artifact_family=artifact_family,
            is_usable_finding_fn=is_usable_finding,
            default_pitch_deck_sections_fn=default_pitch_deck_sections,
            is_pitch_deck_family_fn=is_pitch_deck_family,
            section_title_to_request_fn=section_title_to_request,
            pitch_deck_research_groups_fn=pitch_deck_research_groups,
        )

