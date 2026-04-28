from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field
from agentscope.tool import Toolkit

from agentscope_blaiq.agents.skills import load_skill, load_brand_context
from agentscope_blaiq.contracts.brief import ArtifactBrief, BriefSection
from agentscope_blaiq.contracts.evidence import EvidencePack
from agentscope_blaiq.contracts.messages import make_agent_input, make_agent_output
from agentscope_blaiq.contracts.workflow import ArtifactFamily, ArtifactSpec, RequirementsChecklist
from agentscope_blaiq.runtime.agent_base import BaseAgent

logger = logging.getLogger(__name__)


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


class SlidesData(BaseModel):
    """Complete slides.json output that maps directly to a React template."""
    title: str
    brand: str = "default"
    layout: str = "slides"
    slides: list[SlideData] = Field(default_factory=list)


class ContentDirectorAgent(BaseAgent):
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

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        self.register_tool(toolkit, tool_id="content_distribution", fn=self._tool_content_distribution, description="Decide how content should be distributed across sections.")
        self.register_tool(toolkit, tool_id="section_planning", fn=self._tool_section_planning, description="Produce a section-by-section plan from requirements and evidence.")
        self.register_tool(toolkit, tool_id="template_selection", fn=self._tool_template_selection, description="Select a template direction for the renderer.")
        self.register_tool(toolkit, tool_id="render_brief_generation", fn=self._tool_render_brief_generation, description="Generate the renderer handoff brief.")
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
    def _artifact_family_value(family: ArtifactFamily | str) -> str:
        return family.value if isinstance(family, ArtifactFamily) else str(family)

    @staticmethod
    def _artifact_family_from_value(value: str) -> ArtifactFamily:
        try:
            return ArtifactFamily(value)
        except ValueError:
            return ArtifactFamily.custom

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

    def _build_enriched_evidence_context(self, evidence_pack: EvidencePack | None) -> str:
        """Build enriched context from research agent's handoff.

        Includes:
        - Content brief (key message, pillars, audience angles)
        - Structured insights (quotable claims, metrics)
        - Content hooks (narrative angles)
        - Risk flags (for careful framing)
        """
        if not evidence_pack:
            return ""

        sections = []

        # Content brief from research agent
        if evidence_pack.content_brief:
            brief = evidence_pack.content_brief
            sections.append("=== RESEARCH HANDOFF BRIEF ===")
            sections.append(f"**Key Message**: {brief.key_message}")
            if brief.supporting_pillars:
                sections.append("**Supporting Pillars**:")
                for pillar in brief.supporting_pillars[:4]:
                    sections.append(f"  - {pillar}")
            if brief.audience_angles:
                sections.append("**Audience Angles**:")
                for audience, angle in brief.audience_angles.items():
                    sections.append(f"  - {audience}: {angle}")
            if brief.recommended_structure:
                sections.append(f"**Recommended Structure**: {' → '.join(brief.recommended_structure)}")
            if brief.tone_guidance:
                sections.append(f"**Tone Guidance**: {brief.tone_guidance}")
            if brief.must_include_claims:
                sections.append("**Must Include Claims**:")
                for claim in brief.must_include_claims[:4]:
                    sections.append(f"  - {claim}")
            if brief.avoid_claims:
                sections.append("**Claims to Qualify/Avoid**:")
                for claim in brief.avoid_claims[:4]:
                    sections.append(f"  - {claim}")
            sections.append("")

        # Structured insights
        if evidence_pack.structured_insights:
            sections.append("=== STRUCTURED INSIGHTS ===")
            quotable = [i for i in evidence_pack.structured_insights if i.quotable]
            metrics = [i for i in evidence_pack.structured_insights if i.insight_type == "metric"]

            if quotable:
                sections.append("**Quotable Claims**:")
                for insight in quotable[:5]:
                    sections.append(f"  - \"{insight.insight}\" [{', '.join(insight.source_refs)}]")
            if metrics:
                sections.append("**Key Metrics**:")
                for insight in metrics[:5]:
                    sections.append(f"  - {insight.insight} [{', '.join(insight.source_refs)}]")
            sections.append("")

        # Content hooks
        if evidence_pack.content_hooks:
            sections.append("=== NARRATIVE HOOKS ===")
            for hook in evidence_pack.content_hooks[:4]:
                sections.append(f"  - [{hook.hook_type}] {hook.description}")
            sections.append("")

        # Risk flags
        if evidence_pack.risk_flags:
            sections.append("=== RISK FLAGS ===")
            for flag in evidence_pack.risk_flags:
                sections.append(f"  - [{flag.severity.upper()}] {flag.risk_type}: {flag.description}")
                if flag.mitigation:
                    sections.append(f"    → Mitigation: {flag.mitigation}")
            sections.append("")

        return "\n".join(sections) if sections else ""

    def _build_artifact_brief_prompt(
        self,
        *,
        user_query: str,
        artifact_spec: ArtifactSpec,
        evidence_text: str,
        evidence_summary: str,
        hitl_text: str,
        section_titles: list[str],
    ) -> str:
        schema_hint = {
            "brief_id": "string",
            "thread_id": "string",
            "artifact_family": self._artifact_family_value(artifact_spec.family),
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
                }
            ],
            "brand_voice_id": "optional-string",
            "style_preference": artifact_spec.tone or "executive",
            "evidence_pack_id": "string",
            "required_disclaimers": [],
            "metadata": {"template_name": self._template_name_for_family(artifact_spec.family)},
        }
        return (
            "Create an ArtifactBrief JSON only. Keep it concise and evidence-anchored.\n"
            f"Request: {user_query}\n"
            f"Artifact Family: {self._artifact_family_value(artifact_spec.family)}\n"
            f"Audience: {artifact_spec.audience or 'general'}\n"
            f"Tone: {artifact_spec.tone or 'professional'}\n"
            f"Required Sections: {', '.join(section_titles)}\n\n"
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
            artifact_family=self._artifact_family_from_value(brief.family),
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
                    visual_intent=section.visual_hint or defaults["visual_intent"],
                    acceptance_checks=section.constraints,
                )
            )

        metadata = artifact_brief.metadata or {}
        return ContentBrief(
            title=artifact_brief.title,
            family=self._artifact_family_value(artifact_brief.artifact_family),
            template_name=str(metadata.get("template_name") or self._template_name_for_family(artifact_brief.artifact_family)),
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
        evidence_text = self._format_evidence_for_prompt(evidence_pack)
        hitl_text = "\n".join(f"- {k}: {v}" for k, v in (hitl_answers or {}).items()) or "None"
        section_titles = artifact_spec.required_sections or ["Hero", "Evidence", "CTA"]
        summary = evidence_summary
        if evidence_pack and evidence_pack.summary and len(evidence_pack.summary) > 30:
            summary = evidence_pack.summary

        prompt = self._build_artifact_brief_prompt(
            user_query=user_query,
            artifact_spec=artifact_spec,
            evidence_text=evidence_text,
            evidence_summary=summary,
            hitl_text=hitl_text,
            section_titles=section_titles,
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
        # await self.log(
        #     f"Planning content distribution for {artifact_spec.family.value}.",
        #     kind="thought",
        #     detail={"family": artifact_spec.family.value, "requirement_count": len(requirements.items)},
        # )

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

        # await self.log(
        #     f"Content brief ready: {len(brief.section_plan)} sections planned.",
        #     kind="decision",
        #     detail={"template_name": brief.template_name, "section_count": len(brief.section_plan)},
        # )
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
        # await self.log(
        #     f"Planning slides for artifact family '{artifact_family}'.",
        #     kind="thought",
        #     detail={"artifact_family": artifact_family, "tenant_id": tenant_id},
        # )

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

        # Build a context summary from evidence to anchor the LLM BEFORE the query
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

CRITICAL: The meaning of any acronyms, names, or terms in the request MUST be
interpreted based on the evidence above, NOT from your training data.
For example, if the evidence says "CSI" means "Cognitive Swarm Intelligence",
then the artifact MUST be about Cognitive Swarm Intelligence — not any other
meaning of the acronym.

=== AVAILABLE SLIDE TYPES ===
You have access to these premium slide types for creating high-quality data visualizations:

1. **metrics_dashboard** — For KPI cards with values, labels, trends, and comparisons
   - Use when: Displaying key metrics, performance indicators, or statistics
   - Fields: metrics=[{{value, label, trend, trendValue, comparison}}]
   - Example: Revenue dashboard with 4-6 metric cards showing values and trends

2. **analysis_chart** — For line, bar, or area charts with data points
   - Use when: Showing trends over time, comparisons, or distributions
   - Fields: chart_type="line"|"bar"|"area", chart_data=[{{label, value, value2, label2}}]
   - Example: Monthly performance trend with primary and secondary metrics

3. **data_table** — For structured tabular data with formatted columns
   - Use when: Presenting detailed comparisons, breakdowns, or multi-metric analysis
   - Fields: columns=[{{key, header, align, format}}], table_data=[{{columnKey: value}}]
   - Example: Funnel stage breakdown with spend, conversions, CPA, ROAS columns

4. **insight_cards** — For insight cards with verdicts and recommendations
   - Use when: Presenting analysis findings with clear verdicts (positive/negative/warning)
   - Fields: insights=[{{title, finding, verdict, verdictLabel, metrics, recommendation}}]
   - Example: CPA analysis with "Expected", "Over-invested", "Efficient" verdicts

5. **hero** — Opening slide with headline and subheadline
6. **data_grid** — Grid of stat cards (simpler than metrics_dashboard)
7. **bullets** — Bullet point lists
8. **evidence** — Evidence blocks with citations
9. **cta** — Call-to-action slide
10. **quote** — Testimonial or quote slide

=== SLIDE TYPE SELECTION GUIDANCE ===
- For **reports and analysis**: Use metrics_dashboard, analysis_chart, data_table, insight_cards
- For **pitch decks**: Use hero, data_grid, bullets, evidence, cta
- For **finance analysis**: Use data_table, insight_cards, analysis_chart, metrics_dashboard
- Always match the slide type to the content: numbers → metrics_dashboard, trends → analysis_chart, comparisons → data_table, findings → insight_cards

Return ONLY valid JSON matching the SlidesData schema:
{{
  "title": "...",
  "brand": "{tenant_id}",
    "layout": "{ 'poster' if artifact_family == 'poster' else 'slides' }",
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

        expected_layout = "poster" if artifact_family == "poster" else "slides"
        if slides.layout != expected_layout:
            slides.layout = expected_layout

        # await self.log(
        #     f"Slides plan ready: {len(slides.slides)} slides generated.",
        #     kind="decision",
        #     detail={"slide_count": len(slides.slides), "artifact_family": artifact_family},
        # )
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
            layout="slides",
            slides=slides,
        )
