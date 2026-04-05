from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field
from agentscope.tool import Toolkit

from agentscope_blaiq.agents.skills import load_skill, load_brand_context
from agentscope_blaiq.contracts.evidence import EvidencePack
from agentscope_blaiq.contracts.workflow import ArtifactFamily, ArtifactSpec, RequirementsChecklist
from agentscope_blaiq.runtime.agent_base import BaseAgent

logger = logging.getLogger(__name__)


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
    type: str  # "hero", "data_grid", "bullets", "evidence", "cta", "quote"
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


class SlidesData(BaseModel):
    """Complete slides.json output that maps directly to a React template."""
    title: str
    brand: str = "default"
    slides: list[SlideData] = Field(default_factory=list)


_SECTION_DEFAULTS: dict[str, dict] = {
    "hero": {
        "purpose": "Hook the audience — bold headline and 1-sentence value statement.",
        "visual_intent": "Full-bleed background, oversized headline, minimal copy.",
    },
    "problem": {
        "purpose": "Make the audience feel the pain point acutely.",
        "visual_intent": "Data callout or stat that quantifies the problem.",
    },
    "solution": {
        "purpose": "Show how the product/idea solves the stated problem.",
        "visual_intent": "Before/after or 3-step flow diagram.",
    },
    "proof": {
        "purpose": "Evidence that the solution works — metrics, testimonials, case studies.",
        "visual_intent": "Number cards or quote blocks with source attribution.",
    },
    "traction": {
        "purpose": "Show growth momentum and key milestones.",
        "visual_intent": "Timeline or growth chart with callout numbers.",
    },
    "market": {
        "purpose": "Size the opportunity — TAM/SAM/SOM or market context.",
        "visual_intent": "Concentric circles or bar chart showing market layers.",
    },
    "team": {
        "purpose": "Build trust in the people executing the vision.",
        "visual_intent": "Headshots with name, role, 1-line credential.",
    },
    "ask": {
        "purpose": "State clearly what you are asking for and why.",
        "visual_intent": "Clean single-focus slide with the ask front and centre.",
    },
    "cta": {
        "purpose": "Drive the next action — book a call, invest, sign up.",
        "visual_intent": "Bold CTA button or contact info, minimal distractions.",
    },
    "thesis": {
        "purpose": "State the central investment or analytical thesis.",
        "visual_intent": "1-sentence thesis in oversized type with supporting context.",
    },
    "hypotheses": {
        "purpose": "List testable sub-hypotheses that support or challenge the thesis.",
        "visual_intent": "Numbered hypothesis cards with verification status.",
    },
    "evidence": {
        "purpose": "Present source-backed evidence for each hypothesis.",
        "visual_intent": "Evidence table or cards with source citations.",
    },
    "risks": {
        "purpose": "Acknowledge key risks and mitigants honestly.",
        "visual_intent": "Risk matrix or bullet list with mitigation notes.",
    },
    "recommendation": {
        "purpose": "State the analytical conclusion and recommended action.",
        "visual_intent": "Clear verdict with confidence level and next steps.",
    },
}


def _section_defaults(title: str) -> dict:
    return _SECTION_DEFAULTS.get(title.lower(), {
        "purpose": f"Cover {title.lower()} for the audience.",
        "visual_intent": f"Clear {title.lower()} section with supporting evidence.",
    })


class ContentDirectorAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="ContentDirectorAgent",
            role="content_director",
            sys_prompt=(
                "You are a world-class content director for high-stakes presentations and research reports. "
                "Your job is to transform evidence and user requirements into precise, slide-by-slide content plans. "
                "Every section plan must contain SPECIFIC copy guidance drawn from the actual evidence — no generic placeholders. "
                "core_message must be 2-4 sentences of real content the renderer can use directly. "
                "Return valid JSON matching the ContentBrief schema."
            ),
            **kwargs,
        )

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        toolkit.register_tool_function(
            self._tool_content_distribution,
            func_name="content_distribution",
            func_description="Decide how content should be distributed across sections.",
        )
        toolkit.register_tool_function(
            self._tool_section_planning,
            func_name="section_planning",
            func_description="Produce a section-by-section plan from requirements and evidence.",
        )
        toolkit.register_tool_function(
            self._tool_template_selection,
            func_name="template_selection",
            func_description="Select a template direction for the renderer.",
        )
        toolkit.register_tool_function(
            self._tool_render_brief_generation,
            func_name="render_brief_generation",
            func_description="Generate the renderer handoff brief.",
        )
        return toolkit

    def _tool_content_distribution(self, artifact_spec: dict | None = None, requirements: dict | None = None):
        return self.tool_response(
            {
                "artifact_spec": artifact_spec or {},
                "requirements": requirements or {},
                "distribution": "Match sections to the required narrative and evidence hierarchy.",
            }
        )

    def _tool_section_planning(self, section_plan: list[dict] | None = None):
        return self.tool_response({"section_plan": section_plan or []})

    def _tool_template_selection(self, artifact_spec: dict | None = None):
        family = (artifact_spec or {}).get("family", "custom")
        template_name = self._template_name_for_family(family)
        return self.tool_response({"template_name": template_name})

    @staticmethod
    def _template_name_for_family(family: ArtifactFamily | str) -> str:
        family_value = family.value if isinstance(family, ArtifactFamily) else str(family)
        if family_value == "custom":
            return "default"
        if family_value == ArtifactFamily.finance_analysis.value:
            return "finance-analysis-executive"
        return f"{family_value.replace('_', '-')}-executive"

    def _tool_render_brief_generation(self, brief: dict | None = None):
        return self.tool_response({"brief": brief or {}})

    @staticmethod
    def _is_usable_finding(f: "EvidenceFinding") -> bool:
        """Filter out garbage findings: raw PDF bytes, smoke tests, empty content."""
        text = f.summary or ""
        if not text or len(text.strip()) < 20:
            return False
        if text.startswith("%PDF") or "\x00" in text or "\\x0" in text:
            return False
        lower = text.lower()
        if "smoke test" in lower or "smoke-test" in lower:
            return False
        if "this file exists to verify" in lower:
            return False
        return True

    @staticmethod
    def _format_evidence_for_prompt(evidence_pack: EvidencePack | None, max_findings: int = 15) -> str:
        if evidence_pack is None:
            return "No evidence pack provided."
        # Memory findings are the primary knowledge base (HIVE-MIND).
        # Doc findings can be useful but often contain test files or unparsed PDFs.
        # Web findings are generic and go last.
        usable = ContentDirectorAgent._is_usable_finding
        memory = [f for f in evidence_pack.memory_findings if usable(f)]
        docs = [f for f in evidence_pack.doc_findings if usable(f)]
        web = [f for f in evidence_pack.web_findings if usable(f)]
        memory.sort(key=lambda f: f.confidence, reverse=True)
        docs.sort(key=lambda f: f.confidence, reverse=True)
        web.sort(key=lambda f: f.confidence, reverse=True)
        # Memory first (most reliable), then docs, then web
        all_findings = memory + docs + web
        if not all_findings:
            return "No structured findings available."
        sorted_findings = all_findings[:max_findings]
        lines = []
        for i, f in enumerate(sorted_findings, 1):
            lines.append(f"{i}. [{f.title}]: {f.summary}")
        return "\n".join(lines)

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
            usable = self._is_usable_finding
            memory = [f for f in evidence_pack.memory_findings if usable(f)]
            docs = [f for f in evidence_pack.doc_findings if usable(f)]
            web = [f for f in evidence_pack.web_findings if usable(f)]
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
            template_name=self._template_name_for_family(artifact_spec.family),
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
        await self.log(
            f"Planning content distribution for {artifact_spec.family.value}.",
            kind="thought",
            detail={"family": artifact_spec.family.value, "requirement_count": len(requirements.items)},
        )

        evidence_text = self._format_evidence_for_prompt(evidence_pack)
        hitl_text = (
            "\n".join(f"- {k}: {v}" for k, v in hitl_answers.items())
            if hitl_answers else "None"
        )
        sections_list = ", ".join(artifact_spec.required_sections or ["Hero", "Evidence"])

        prompt = f"""You are the content director writing the complete copy for a {artifact_spec.family.value}.

USER REQUEST: {user_query}
AUDIENCE: {artifact_spec.audience or "general"}
TONE: {artifact_spec.tone or "professional"}
REQUIRED SECTIONS: {sections_list}

USER ANSWERS (from clarification):
{hitl_text}

TOP EVIDENCE FINDINGS (extract specific facts, numbers, names, quotes from these):
{evidence_text}

---
TASK: Generate a ContentBrief JSON with FULL COPY for every section.
Each section must have REAL, SPECIFIC content — not placeholders or generic descriptions.
You are the writer. The renderer will use your copy verbatim.

CONTENT RULES:
- headline: punchy, specific (e.g. "Tokyo's ¥50T Tourism Market Awakens" not "Hero Section")
- subheadline: one strong sentence expanding the headline
- body: 2-3 paragraphs of narrative. Use actual facts from evidence. Min 80 words per section.
- bullets: 3-5 specific, complete sentences (not fragments). Each bullet should be a standalone insight.
- stats: extract real numbers from evidence. If no numbers exist, omit the field.
- core_message: 3-4 sentence synthesis of the section's key message
- visual_intent: specific layout instruction (e.g. "3-card grid with stat callouts" not "clean layout")

Return ONLY valid JSON:
{{
  "title": string,
  "family": "{artifact_spec.family.value}",
  "template_name": "{self._template_name_for_family(artifact_spec.family)}",
  "narrative": "3-4 sentence story arc covering the whole artifact",
  "audience": string or null,
  "core_message": "overall key message",
  "visual_direction": "specific design direction with colours and layout style",
  "cta": "specific call to action text",
  "risks": [],
  "acceptance_checks": [],
  "section_plan": [
    {{
      "section_id": "section-1",
      "title": "Hero",
      "purpose": "Hook audience with the central proposition",
      "objective": "Make the audience immediately understand what this is about",
      "headline": "SPECIFIC punchy headline using facts from evidence",
      "subheadline": "One supporting sentence with a key insight",
      "body": "2-3 paragraphs of real narrative content (min 80 words) using evidence findings",
      "bullets": ["Complete insight sentence 1", "Complete insight sentence 2", "Complete insight sentence 3"],
      "stats": [{{"value": "XXX", "label": "metric name"}}],
      "core_message": "3-4 sentence synthesis of this section",
      "visual_intent": "specific layout instruction for the renderer",
      "cta": "",
      "evidence_refs": [],
      "risks": [],
      "acceptance_checks": [],
      "source_refs": [],
      "notes": [],
      "audience": null
    }}
  ],
  "distribution_notes": [],
  "handoff_notes": []
}}"""

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
            payload = self.resolver.safe_json_loads(raw)
            brief = ContentBrief.model_validate(payload)
        except Exception:
            brief = self._fallback_brief(
                user_query=user_query,
                evidence_summary=evidence_summary,
                artifact_spec=artifact_spec,
                requirements=requirements,
                hitl_answers=hitl_answers,
                evidence_pack=evidence_pack,
            )

        if not brief.section_plan:
            brief = self._fallback_brief(
                user_query=user_query,
                evidence_summary=evidence_summary,
                artifact_spec=artifact_spec,
                requirements=requirements,
                hitl_answers=hitl_answers,
                evidence_pack=evidence_pack,
            )

        if not brief.audience:
            brief.audience = artifact_spec.audience
        if not brief.core_message:
            brief.core_message = brief.narrative or user_query
        if not brief.visual_direction:
            brief.visual_direction = f"{artifact_spec.tone} {artifact_spec.family.value} layout"
        if not brief.cta and hitl_answers:
            brief.cta = hitl_answers.get("cta", "")

        await self.log(
            f"Content brief ready: {len(brief.section_plan)} sections planned.",
            kind="decision",
            detail={"template_name": brief.template_name, "section_count": len(brief.section_plan)},
        )
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
    ) -> SlidesData:
        """Generate a structured SlidesData object using artifact-specific skills.

        This is the new primary method for the rewritten pipeline.
        The skill system provides per-artifact-type instructions that guide
        the LLM to produce slides.json structures mapping to React components.
        """
        await self.log(
            f"Planning slides for artifact family '{artifact_family}'.",
            kind="thought",
            detail={"artifact_family": artifact_family, "tenant_id": tenant_id},
        )

        # 1. Load skill and brand context
        skill_text = load_skill(artifact_family, "content")
        brand_context = load_brand_context(brand_dna)

        # 2. Format evidence findings (reuse existing filtering logic)
        evidence_text = self._format_evidence_for_prompt(evidence_pack, max_findings=15)

        # 3. Format HITL answers
        hitl_text = (
            "\n".join(f"- {k}: {v}" for k, v in hitl_answers.items())
            if hitl_answers else "None"
        )

        # 4. Build messages with skill in SYSTEM, evidence+query in USER
        system_message = f"{skill_text}\n\n{brand_context}"

        user_message = f"""Generate slides.json for this request:
REQUEST: {user_query}
ARTIFACT TYPE: {artifact_family}

USER ANSWERS:
{hitl_text}

EVIDENCE FINDINGS (use ONLY these for content):
{evidence_text}

Return ONLY valid JSON matching the SlidesData schema:
{{
  "title": "...",
  "brand": "{tenant_id}",
  "slides": [
    {{"type": "hero", "tag": "...", "headline": "...", ...}},
    ...
  ]
}}"""

        # 5. Call LLM
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
            logger.warning(
                "LLM slides generation failed for '%s'; using deterministic fallback.",
                artifact_family,
                exc_info=True,
            )
            slides = self._fallback_slides(
                user_query=user_query,
                evidence_pack=evidence_pack,
                hitl_answers=hitl_answers,
                tenant_id=tenant_id,
            )

        # Guard: if LLM returned empty slides, fall back
        if not slides.slides:
            slides = self._fallback_slides(
                user_query=user_query,
                evidence_pack=evidence_pack,
                hitl_answers=hitl_answers,
                tenant_id=tenant_id,
            )

        await self.log(
            f"Slides plan ready: {len(slides.slides)} slides generated.",
            kind="decision",
            detail={"slide_count": len(slides.slides), "artifact_family": artifact_family},
        )
        return slides

    def _fallback_slides(
        self,
        *,
        user_query: str,
        evidence_pack: EvidencePack | None = None,
        hitl_answers: dict[str, str] | None = None,
        tenant_id: str = "default",
    ) -> SlidesData:
        """Build a deterministic SlidesData from evidence when the LLM fails."""
        usable = self._is_usable_finding
        all_findings = []
        if evidence_pack:
            memory = [f for f in evidence_pack.memory_findings if usable(f)]
            docs = [f for f in evidence_pack.doc_findings if usable(f)]
            web = [f for f in evidence_pack.web_findings if usable(f)]
            memory.sort(key=lambda f: f.confidence, reverse=True)
            docs.sort(key=lambda f: f.confidence, reverse=True)
            web.sort(key=lambda f: f.confidence, reverse=True)
            all_findings = memory + docs + web

        top_5 = all_findings[:5]

        slides: list[SlideData] = []

        # Slide 1: hero
        first_body = top_5[0].summary if top_5 else user_query
        slides.append(SlideData(
            type="hero",
            headline=user_query,
            body=first_body,
        ))

        # Slide 2: bullets — key findings
        if top_5:
            slides.append(SlideData(
                type="bullets",
                title="Key Findings",
                bullets=[f.summary for f in top_5],
            ))

        # Slide 3: evidence — source-attributed findings
        if top_5:
            slides.append(SlideData(
                type="evidence",
                title="Proof Points",
                items=[
                    {
                        "finding": f.summary,
                        "source": f.title,
                        "confidence": str(f.confidence),
                    }
                    for f in top_5
                ],
            ))

        # Slide 4: cta
        cta_body = (
            hitl_answers.get("cta", "") if hitl_answers else ""
        ) or user_query
        slides.append(SlideData(
            type="cta",
            headline="Next Steps",
            body=cta_body,
        ))

        return SlidesData(
            title=user_query,
            brand=tenant_id,
            slides=slides,
        )
