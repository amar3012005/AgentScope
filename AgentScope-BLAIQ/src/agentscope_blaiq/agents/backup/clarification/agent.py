from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agentscope_blaiq.contracts.evidence import EvidencePack
from agentscope_blaiq.contracts.workflow import ArtifactFamily, RequirementsChecklist, WorkflowNode
from agentscope_blaiq.runtime.agent_base import BaseAgent


class ClarificationQuestion(BaseModel):
    requirement_id: str
    question: str
    why_it_matters: str | None = None
    answer_hint: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    # Phase 3: Typed validation metadata for frontend rendering.
    input_type: str = "option"  # "option" | "text" | "multi_select"
    validation_rules: dict = Field(default_factory=dict)
    required: bool = True


class ClarificationPrompt(BaseModel):
    headline: str
    intro: str
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    blocked_question: str
    expected_answer_schema: dict[str, str] = Field(default_factory=dict)
    family: ArtifactFamily = ArtifactFamily.custom


class ClarificationDraft(BaseModel):
    headline: str
    intro: str
    questions: list[ClarificationQuestion] = Field(default_factory=list)


class ClarificationAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="HITL Agent",
            role="hitl",
            sys_prompt=(
                "You are the HITL clarification agent for BLAIQ. Your job is to turn missing requirements into short, "
                "human-friendly clarification questions. Never ask fill-in-the-blank prompts. Write like a product "
                "specialist helping the user make the output stronger. Keep questions grounded in the request, concise, "
                "and action-oriented. Prefer grouped questions that feel natural to answer."
            ),
            **kwargs,
        )

    @staticmethod
    def _generic_options_for_family(family: ArtifactFamily, requirement_id: str, request_text: str) -> list[str]:
        section = requirement_id.split(":", 1)[1].replace("_", " ") if ":" in requirement_id else requirement_id
        lower_section = section.lower()
        family_label = family.value.replace("_", " ")
        if requirement_id.startswith("field:target_audience"):
            return ["Leadership team", "External customers", "Investors / partners"]
        if requirement_id.startswith("field:delivery_channel"):
            return ["Live presentation", "PDF deck", "Web page / digital"]
        if requirement_id.startswith("field:must_have_sections"):
            return ["Hero + narrative", "Problem / solution / proof", "I’ll specify the exact sections"]
        if requirement_id.startswith("field:brand_context"):
            return ["Use current brand system", "Follow a lighter executive style", "I’ll share brand guidance"]
        section_options = {
            "hero": [
                f"A strong opening for the {family_label}",
                "A bold headline and value proposition",
                "A concise executive summary lead-in",
            ],
            "problem": [
                "The business pain / market gap",
                "The customer challenge",
                "The risk of doing nothing",
            ],
            "solution": [
                "The proposed solution",
                "The differentiating approach",
                "The operating model or product direction",
            ],
            "proof": [
                "Evidence from research",
                "Customer traction / metrics",
                "Credible market validation",
            ],
            "cta": [
                "Request a meeting / follow-up",
                "Approve next steps",
                "Move to implementation",
            ],
            "opening": [
                "A sharp opening statement",
                "A story-led introduction",
                "A metric-led introduction",
            ],
            "narrative": [
                "Problem → solution → proof",
                "Current state → future state",
                "Challenge → opportunity → action",
            ],
            "closing": [
                "A decisive call to action",
                "A memorable closing statement",
                "A summary with next steps",
            ],
            "headline": [
                "A bold short headline",
                "A clear executive headline",
                "A benefit-led headline",
            ],
            "benefits": [
                "Efficiency and speed",
                "Revenue and growth",
                "Trust and credibility",
            ],
            "evidence": [
                "Customer proof points",
                "Market data and insights",
                "Internal source-backed evidence",
            ],
            "offer": [
                "Product value proposition",
                "A service or package offer",
                "A conversion-focused offer",
            ],
            "details": [
                "Operational specifics",
                "Product specifics",
                "Audience-specific details",
            ],
            "summary": [
                "Executive summary",
                "Key takeaways",
                "One-paragraph overview",
            ],
            "recommendations": [
                "Recommended next steps",
                "Priority actions",
                "Decision-oriented guidance",
            ],
            "visual hook": [
                "Minimal and elegant",
                "Bold and energetic",
                "Analytical and clean",
            ],
        }
        fallback = [
            f"A concise answer for the {family_label}",
            f"A stronger version of {section}",
            f"I’ll type my own answer",
        ]
        return section_options.get(lower_section, fallback)

    @staticmethod
    def _is_usable_finding(f) -> bool:
        text = f.summary or ""
        if not text or len(text.strip()) < 20:
            return False
        if text.startswith("%PDF") or "\x00" in text:
            return False
        lower = text.lower()
        if "smoke test" in lower or "this file exists to verify" in lower:
            return False
        return True

    @staticmethod
    def _top_evidence_summaries(evidence: EvidencePack | None, max_items: int = 5) -> list[str]:
        """Return top usable finding summaries — memory first, then docs, then web."""
        if evidence is None:
            return []
        usable = ClarificationAgent._is_usable_finding
        memory = [f for f in evidence.memory_findings if usable(f)]
        docs = [f for f in evidence.doc_findings if usable(f)]
        memory.sort(key=lambda f: f.confidence, reverse=True)
        all_f = memory + docs
        return [f"{f.title}: {f.summary[:150]}" for f in all_f[:max_items]]

    @staticmethod
    def _evidence_context(evidence: EvidencePack | None) -> dict[str, object]:
        if evidence is None:
            return {
                "text": "",
                "supporting_sources": 0,
                "has_supporting_sources": False,
                "upload_only": False,
                "weak": True,
                "top_summaries": [],
            }
        usable = ClarificationAgent._is_usable_finding
        snippets = [evidence.summary, *evidence.open_questions, *evidence.recommended_followups]
        for finding in [*evidence.memory_findings, *evidence.web_findings, *evidence.doc_findings]:
            if usable(finding):
                snippets.extend([finding.title, finding.summary])
        text = " ".join(str(part or "") for part in snippets).lower()
        supporting_sources = len(evidence.memory_findings) + len(evidence.web_findings)
        upload_only = supporting_sources == 0 and len(evidence.doc_findings) > 0
        weak = supporting_sources == 0 and evidence.confidence < 0.65
        return {
            "text": text,
            "supporting_sources": supporting_sources,
            "has_supporting_sources": supporting_sources > 0,
            "upload_only": upload_only,
            "weak": weak,
            "top_summaries": ClarificationAgent._top_evidence_summaries(evidence),
        }

    @staticmethod
    def _requirement_covered_by_context(
        requirement_id: str,
        request_text: str,
        evidence: EvidencePack | None,
        *,
        target_audience: str | None = None,
        delivery_channel: str | None = None,
        brand_context: str | None = None,
    ) -> bool:
        request_lower = str(request_text or "").lower()
        context = ClarificationAgent._evidence_context(evidence)
        evidence_text = str(context["text"])
        if requirement_id == "field:target_audience":
            if str(target_audience or "").strip():
                return True
            audience_markers = ("investor", "buyer", "customer", "leadership", "executive", "partner", "board", "procurement")
            return any(marker in request_lower or marker in evidence_text for marker in audience_markers)
        if requirement_id == "field:delivery_channel":
            if str(delivery_channel or "").strip():
                return True
            return any(marker in request_lower for marker in ("pdf", "web", "landing page", "poster", "brochure", "presentation", "deck"))
        if requirement_id == "field:brand_context":
            if str(brand_context or "").strip():
                return True
            return any(marker in request_lower or marker in evidence_text for marker in ("brand", "visual identity", "style guide"))
        if requirement_id == "field:must_have_sections":
            section_markers = ("hero", "problem", "solution", "proof", "cta", "agenda", "summary", "recommendation")
            return sum(1 for marker in section_markers if marker in request_lower) >= 2
        if not requirement_id.startswith("section:"):
            return False

        section_name = requirement_id.split(":", 1)[1].replace("_", " ")
        section_keywords = {
            "hero": ("headline", "hook", "opening", "positioning", "value proposition"),
            "problem": ("problem", "pain", "challenge", "gap", "risk"),
            "solution": ("solution", "approach", "platform", "product", "offer", "direction"),
            "proof": ("proof", "traction", "evidence", "metric", "validation", "reference", "customer"),
            "cta": ("cta", "next step", "follow-up", "call to action", "meeting", "decision"),
        }
        keywords = section_keywords.get(section_name, (section_name,))
        keyword_hits = sum(1 for keyword in keywords if keyword in request_lower or keyword in evidence_text)
        return bool(context["has_supporting_sources"]) and keyword_hits >= 2 and not bool(context["weak"])

    @staticmethod
    def _question_priority(requirement_id: str, evidence: EvidencePack | None) -> tuple[int, int]:
        context = ClarificationAgent._evidence_context(evidence)
        if requirement_id == "field:target_audience":
            return (0, 0)
        if requirement_id == "field:must_have_sections":
            return (0, 1)
        if requirement_id.startswith("section:proof") and bool(context["upload_only"]):
            return (0, 2)
        if requirement_id.startswith("section:hero"):
            return (1, 0)
        if requirement_id.startswith("section:problem"):
            return (1, 1)
        if requirement_id.startswith("section:solution"):
            return (1, 2)
        if requirement_id.startswith("section:proof"):
            return (1, 3)
        if requirement_id.startswith("section:cta"):
            return (1, 4)
        return (2, 0)

    @staticmethod
    def _question_from_requirement(
        requirement_id: str,
        requirement_text: str,
        family: ArtifactFamily,
        request_text: str,
        evidence: EvidencePack | None = None,
    ) -> ClarificationQuestion:
        cleaned = requirement_text.rstrip(".")
        context = ClarificationAgent._evidence_context(evidence)
        top_summaries = context.get("top_summaries", [])
        # Build a short evidence hint the question can reference
        evidence_hint = ""
        if top_summaries:
            evidence_hint = top_summaries[0].split(":", 1)[-1].strip()[:100]

        if requirement_id.startswith("section:"):
            section_name = requirement_id.split(":", 1)[1].replace("_", " ")
            family_label = family.value.replace("_", " ")

            # Personalized questions that reference the evidence and request
            if section_name == "hero":
                if evidence_hint:
                    question = f"Based on the research (e.g. \"{evidence_hint}...\"), what angle should we lead with for the {family_label}?"
                elif bool(context["weak"]):
                    question = f"The evidence is still thin. What should be the main hook for the opening of this {family_label}?"
                else:
                    question = f"What should be the main hook for the opening of this {family_label}?"
            elif section_name == "problem":
                if evidence_hint:
                    question = f"The research mentions \"{evidence_hint}...\" — is this the core problem, or should we frame it differently?"
                else:
                    question = "What problem should the audience immediately recognize?"
            elif section_name == "solution":
                if evidence_hint:
                    question = f"Given the findings, what solution or approach should we emphasize?"
                else:
                    question = "What solution or direction should we emphasize?"
            elif section_name == "proof":
                if bool(context["upload_only"]):
                    question = "The current evidence is mostly internal uploads. Which proof point should we elevate?"
                elif top_summaries and len(top_summaries) >= 2:
                    question = f"We found {len(top_summaries)}+ evidence points. Which ones matter most for the proof section?"
                else:
                    question = "What proof point or evidence should we highlight?"
            elif section_name == "cta":
                question = f"What action should the audience take after seeing this {family_label}?"
            else:
                base_questions = {
                    "opening": "How should we open to capture attention?",
                    "narrative": "What story arc should the middle follow?",
                    "closing": "How should we close the piece?",
                    "headline": "What is the headline message we should lead with?",
                    "benefits": "Which benefits matter most for this audience?",
                    "evidence": "What evidence should we foreground?",
                    "offer": "What offer or value should be emphasized?",
                    "details": "What details are necessary to make this complete?",
                    "summary": "What summary should the audience remember?",
                    "recommendations": "What recommendations should this artifact leave the user with?",
                    "visual hook": "What visual or motif should anchor the design?",
                }
                question = base_questions.get(section_name, f"What should we emphasize for the {section_name} section?")

            # Build evidence-aware answer options
            answer_options = []
            if top_summaries:
                for s in top_summaries[:3]:
                    title_part = s.split(":")[0].strip()[:60]
                    answer_options.append(f"Focus on: {title_part}")
                answer_options.append("I'll provide my own direction")
            else:
                answer_options = ClarificationAgent._generic_options_for_family(family, requirement_id, request_text)

            return ClarificationQuestion(
                requirement_id=requirement_id,
                question=question,
                why_it_matters=f"It helps us shape the {section_name} section using the {context['supporting_sources']} sources we found.",
                answer_hint=cleaned,
                answer_options=answer_options,
            )
        if requirement_id.startswith("field:target_audience"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="Who is this really for, and what do they already care about?",
                why_it_matters="The audience changes the tone, proof points, and structure.",
                answer_hint=cleaned,
                answer_options=ClarificationAgent._generic_options_for_family(family, requirement_id, request_text),
            )
        if requirement_id.startswith("field:must_have_sections"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="Are there any sections, slides, or blocks that must be included no matter what?",
                why_it_matters="We need to protect the must-have structure before rendering.",
                answer_hint=cleaned,
                answer_options=ClarificationAgent._generic_options_for_family(family, requirement_id, request_text),
            )
        if requirement_id.startswith("field:delivery_channel"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="Where will this artifact be used: live presentation, PDF, web page, print, or something else?",
                why_it_matters="The delivery channel affects layout, pacing, and export constraints.",
                answer_hint=cleaned,
                answer_options=ClarificationAgent._generic_options_for_family(family, requirement_id, request_text),
            )
        if requirement_id.startswith("field:brand_context"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="Are there brand or style rules we need to respect?",
                why_it_matters="Brand context keeps the output aligned with the organization.",
                answer_hint=cleaned,
                answer_options=ClarificationAgent._generic_options_for_family(family, requirement_id, request_text),
            )
        # ── Text artifact families (email, memo, proposal, letter, etc.) ──────────
        text_families = {
            ArtifactFamily.email, ArtifactFamily.memo, ArtifactFamily.proposal,
            ArtifactFamily.letter, ArtifactFamily.report, ArtifactFamily.social_post,
        }
        if family in text_families:
            family_label = family.value.replace("_", " ")
            if requirement_id in ("field:target_audience", "field:recipient"):
                return ClarificationQuestion(
                    requirement_id=requirement_id,
                    question=f"Who is this {family_label} going to, and what matters most to them?",
                    why_it_matters="The recipient shapes the tone, level of detail, and call to action.",
                    answer_hint=cleaned,
                    answer_options=["Decision-maker / executive", "Subject matter expert / technical lead", "External client / partner", "Internal team member"],
                )
            if requirement_id in ("field:tone", "field:brand_context"):
                return ClarificationQuestion(
                    requirement_id=requirement_id,
                    question=f"What tone should this {family_label} take?",
                    why_it_matters="Tone determines word choice, structure, and how the message lands.",
                    answer_hint=cleaned,
                    answer_options=["Formal and professional", "Friendly and collaborative", "Direct and concise", "Persuasive / sales-oriented"],
                )
            if requirement_id in ("field:cta", "field:objective"):
                return ClarificationQuestion(
                    requirement_id=requirement_id,
                    question=f"What should the reader do after reading this {family_label}?",
                    why_it_matters="The call to action shapes how we close and what we emphasise.",
                    answer_hint=cleaned,
                    answer_options=["Book a meeting or call", "Review and approve", "Reply with information", "Make a purchase / decision"],
                )
            if requirement_id in ("field:key_points", "field:must_have_sections"):
                return ClarificationQuestion(
                    requirement_id=requirement_id,
                    question=f"Are there specific points this {family_label} must cover?",
                    why_it_matters="Missing key points is the most common reason for revisions.",
                    answer_hint=cleaned,
                    answer_options=["Cover the key research findings", "Focus on the specific topic from my request", "I'll specify the exact points"],
                )

        if family == ArtifactFamily.finance_analysis and requirement_id.startswith("field:analysis_subject"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="Which company, asset, or market should this analysis focus on?",
                why_it_matters="The subject determines the evidence we collect and the thesis we test.",
                answer_hint=cleaned,
                answer_options=[
                    "A single company",
                    "A sector or market",
                    "A specific investment theme",
                ],
            )
        if family == ArtifactFamily.finance_analysis and requirement_id.startswith("field:analysis_objective"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="What decision should this analysis help the audience make?",
                why_it_matters="The objective determines whether we emphasize thesis, valuation, risk, or recommendation.",
                answer_hint=cleaned,
                answer_options=[
                    "Investment thesis",
                    "Risk review",
                    "Valuation / recommendation",
                ],
            )
        if family == ArtifactFamily.finance_analysis and requirement_id.startswith("field:analysis_horizon"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="What time horizon should we use for the analysis?",
                why_it_matters="The horizon changes how we interpret trends, catalysts, and risks.",
                answer_hint=cleaned,
                answer_options=[
                    "Next quarter",
                    "Next 12 months",
                    "Multi-year outlook",
                ],
            )
        if family == ArtifactFamily.finance_analysis and requirement_id.startswith("field:analysis_benchmark"):
            return ClarificationQuestion(
                requirement_id=requirement_id,
                question="What benchmark should we compare against?",
                why_it_matters="The benchmark anchors the analysis and keeps the conclusion measurable.",
                answer_hint=cleaned,
                answer_options=[
                    "Sector peer",
                    "Index / market benchmark",
                    "Prior company period",
                ],
            )
        return ClarificationQuestion(
            requirement_id=requirement_id,
            question=f"What should we know about {cleaned.lower()}?",
            why_it_matters=f"It affects how we frame the {family.value.replace('_', ' ')}.",
            answer_hint=cleaned,
            answer_options=ClarificationAgent._generic_options_for_family(family, requirement_id, request_text),
        )

    async def generate_prompt(
        self,
        *,
        user_query: str,
        artifact_family: ArtifactFamily,
        requirements: RequirementsChecklist,
        missing_requirement_ids: list[str],
        evidence: EvidencePack | None = None,
        evidence_summary: str | None = None,
        target_audience: str | None = None,
        delivery_channel: str | None = None,
        brand_context: str | None = None,
    ) -> ClarificationPrompt:
        await self.log_user(
            "Reviewing requirements against your query...",
            detail={"artifact_family": artifact_family.value, "missing_requirement_count": len(missing_requirement_ids)},
        )
        await self.log(
            "Drafting a human-friendly clarification prompt for the missing requirements.",
            kind="thought",
            detail={"artifact_family": artifact_family.value, "missing_requirement_count": len(missing_requirement_ids)},
        )

        unresolved_ids = [
            requirement_id
            for requirement_id in missing_requirement_ids
            if not self._requirement_covered_by_context(
                requirement_id,
                user_query,
                evidence,
                target_audience=target_audience,
                delivery_channel=delivery_channel,
                brand_context=brand_context,
            )
        ]
        prioritized_ids = sorted(
            unresolved_ids,
            key=lambda requirement_id: self._question_priority(requirement_id, evidence),
        )
        await self.log_user(
            "Comparing missing details with available evidence...",
            detail={"unresolved_requirement_count": len(prioritized_ids)},
        )
        questions = [
            self._question_from_requirement(item.requirement_id, item.text, artifact_family, user_query, evidence)
            for item in requirements.items
            if item.requirement_id in prioritized_ids and item.must_have
        ]

        if not questions:
            questions = [
                ClarificationQuestion(
                    requirement_id="clarification:default",
                    question="What are the most important details I should lock in before I generate the final artifact?",
                    why_it_matters="That lets me shape the final output to your real intent.",
                    answer_hint="Provide the key details, constraints, and priorities.",
                )
            ]

        question_payload = [
            {
                "requirement_id": question.requirement_id,
                "question": question.question,
                "why_it_matters": question.why_it_matters,
                "answer_hint": question.answer_hint,
                "answer_options": question.answer_options,
            }
            for question in questions
        ]
        # Filter evidence for the LLM prompt — only usable findings, memory first
        usable_memory = [f for f in (evidence.memory_findings if evidence else []) if self._is_usable_finding(f)]
        usable_docs = [f for f in (evidence.doc_findings if evidence else []) if self._is_usable_finding(f)]
        usable_web = [f for f in (evidence.web_findings if evidence else []) if self._is_usable_finding(f)]
        usable_memory.sort(key=lambda f: f.confidence, reverse=True)
        top_findings_for_llm = [
            {"title": f.title, "summary": f.summary[:200]}
            for f in (usable_memory + usable_docs + usable_web)[:8]
        ]
        evidence_context = {
            "summary": evidence.summary if evidence is not None else evidence_summary,
            "top_findings": top_findings_for_llm,
            "open_questions": list((evidence.open_questions if evidence is not None else [])[:5]),
            "contradictions": [item.model_dump() for item in (evidence.contradictions if evidence is not None else [])][:3],
            "confidence": evidence.confidence if evidence is not None else None,
            "source_count": len(usable_memory) + len(usable_docs) + len(usable_web),
        }

        headline = {
            ArtifactFamily.pitch_deck: "Let me lock the story before I draft the deck",
            ArtifactFamily.keynote: "I need a few speaking and pacing details",
            ArtifactFamily.poster: "I need a few design choices before I lay this out",
            ArtifactFamily.brochure: "I need a few structure details before I build the brochure",
            ArtifactFamily.one_pager: "I need a few framing choices before I condense this",
            ArtifactFamily.landing_page: "I need a few conversion details before I structure the page",
            ArtifactFamily.report: "I need a few context details before I write the report",
            ArtifactFamily.finance_analysis: "I need a few finance details before I build the analysis",
            ArtifactFamily.email: "I need a few details to write the most effective email",
            ArtifactFamily.memo: "A few details will make this memo land better",
            ArtifactFamily.proposal: "I need a few details before I write the proposal",
            ArtifactFamily.letter: "A few details will make this letter more precise",
            ArtifactFamily.social_post: "I need a few details to shape this post",
            ArtifactFamily.custom: "I need a few clarifications before I continue",
        }.get(artifact_family, "I need a few clarifications before I continue")

        top_summaries = self._top_evidence_summaries(evidence, max_items=3)
        intro_parts = [
            f"I can keep this moving, but I need a few details to make the {artifact_family.value.replace('_', ' ')} feel complete and relevant.",
        ]
        if top_summaries:
            intro_parts.append(f"Evidence so far: {'; '.join(top_summaries[:2])}.")
        elif evidence_summary:
            intro_parts.append(f"Evidence so far: {evidence_summary}.")
        if target_audience:
            intro_parts.append(f"Current audience direction: {target_audience}.")
        if delivery_channel:
            intro_parts.append(f"Planned delivery channel: {delivery_channel}.")
        if brand_context:
            intro_parts.append(f"Brand context: {brand_context}.")
        if evidence is not None and evidence.open_questions:
            intro_parts.append(f"The research still leaves these gaps open: {'; '.join(evidence.open_questions[:2])}.")

        draft: ClarificationDraft | None = None
        try:
            await self.log_user("Preparing clarification questions...")
            await self.log(
                "Synthesizing clarification questions from the request, checklist, and research evidence.",
                kind="thought",
                detail={"question_count": len(question_payload), "uses_model": True},
            )

            # Build a rich evidence summary for the LLM
            findings_text = "\n".join(
                f"- [{f['title']}]: {f['summary']}"
                for f in top_findings_for_llm[:8]
            ) or "No specific findings available."

            is_text_family = artifact_family.value in ("email", "memo", "proposal", "letter", "report", "social_post", "summary", "direct")
            text_family_guidance = """
For text artifacts (email, memo, proposal, letter):
- Ask about the RECIPIENT (who, role, what they care about)
- Ask about the KEY MESSAGE or CTA (what action should follow)
- Ask about TONE (formal vs casual, urgent vs informational)
- Reference specific names, products, or topics from the research findings in your options
- Do NOT ask about visual sections (hero, problem, solution) — that is for decks only
""" if is_text_family else ""

            llm_prompt = f"""You are the HITL clarification agent for BLAIQ. The user asked:
"{user_query}"

The research agent found {evidence_context['source_count']} sources. Top findings:
{findings_text}

Artifact type: {artifact_family.value.replace('_', ' ')}
{text_family_guidance}
Generate 2-3 clarification questions that are SPECIFIC to this request and evidence.

RULES:
1. Reference SPECIFIC names, products, or details from the findings in questions and options.
2. answer_options must be CONCRETE CHOICES derived from what was found — not generic phrases.
3. NEVER use options like "Use best judgement", "Keep it concise", "Standard", "Something else", "Skip this".
4. Each option = a decision the user can make with one click.
5. Headline must name what was found (e.g. "I found details about SolvisMax and SolvisLea — help me focus").
6. STRICTLY 3-4 answer_options per question. Make them distinct and specific.

BAD options: ["Use best judgement", "Keep it concise", "Standard format"]
GOOD options (email about SolvisLea): ["Ask for product brochure and specs", "Request a product demo", "Enquire about pricing and availability", "Ask about installation requirements"]

Return ONLY valid JSON:
{{
  "headline": "specific headline referencing what was found",
  "intro": "1-2 sentence intro mentioning key findings and what still needs clarifying",
  "questions": [
    {{
      "requirement_id": "field:target_audience",
      "question": "specific question using evidence details",
      "why_it_matters": "why this shapes the output",
      "answer_hint": "the kind of answer expected",
      "answer_options": ["specific option 1", "specific option 2", "specific option 3", "specific option 4"]
    }}
  ]
}}"""

            response = await self.resolver.acompletion(
                "hitl",
                [
                    {"role": "system", "content": "You generate precise, evidence-informed clarification questions. Return only JSON."},
                    {"role": "user", "content": llm_prompt},
                ],
                max_tokens=1500,
                temperature=0.3,
            )
            raw = self.resolver.extract_text(response)
            payload = self.resolver.safe_json_loads(raw)
            draft = ClarificationDraft.model_validate(payload)
            if not draft.questions:
                draft = None
        except Exception:
            draft = None

        # When LLM generates topic-specific questions, use them DIRECTLY
        # (don't merge back into generic templates — the LLM output is better)
        if draft is not None and draft.questions:
            final_questions = [
                question
                if isinstance(question, ClarificationQuestion)
                else ClarificationQuestion.model_validate(question)
                for question in draft.questions
            ]
        else:
            final_questions = questions
        # Ensure every question has at least 3 concrete options — prefer LLM-generated ones
        for question in final_questions:
            if not question.answer_options or len(question.answer_options) < 2:
                question.answer_options = ClarificationAgent._generic_options_for_family(
                    artifact_family, question.requirement_id, user_query
                )
                if not question.answer_options:
                    question.answer_options = [
                        "Focus on key evidence from research",
                        "I'll provide specific direction",
                        "Use best judgement based on context",
                    ]
        expected_answer_schema = {question.requirement_id: question.question for question in final_questions}
        blocked_question = " ".join([question.question for question in final_questions]).strip()
        prompt = ClarificationPrompt(
            headline=draft.headline if draft is not None else headline,
            intro=draft.intro if draft is not None else " ".join(intro_parts),
            questions=final_questions,
            blocked_question=blocked_question,
            expected_answer_schema=expected_answer_schema,
            family=artifact_family,
        )

        await self.log(
            f"Prepared {len(final_questions)} clarification question(s) for the user.",
            kind="decision",
            detail={"headline": prompt.headline, "question_count": len(final_questions), "uses_model": draft is not None},
        )
        return prompt
