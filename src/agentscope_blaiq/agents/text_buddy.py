from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from agentscope.tool import Toolkit

from agentscope_blaiq.agents.skills import load_skill, load_brand_voice
from agentscope_blaiq.contracts.artifact import TextArtifact
from agentscope_blaiq.contracts.evidence import EvidencePack
from agentscope_blaiq.contracts.workflow import TEXT_ARTIFACT_FAMILIES
from agentscope_blaiq.runtime.agent_base import BaseAgent

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
TEXT_FAMILIES = TEXT_ARTIFACT_FAMILIES


class TextBuddyAgent(BaseAgent):
    """Brand-voice text writer for BLAIQ.

    Produces final text-based outputs (emails, invoices, letters, memos,
    proposals, social posts, summaries) by combining research evidence,
    HITL-refined requirements, and enterprise brand voice guidelines.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="TextBuddyAgent",
            role="text_buddy",
            sys_prompt=(
                "You are TextBuddy, BLAIQ's brand-voice text writer. "
                "You receive research evidence, user requirements, and brand voice guidelines, "
                "then produce polished, ready-to-use text content. "
                "Always follow the brand voice guidelines exactly. "
                "Cite evidence using [source:ID] format. "
                "Write in active voice with concise, professional prose. "
                "Structure your output according to the artifact template provided."
            ),
            **kwargs,
        )

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        toolkit.register_tool_function(
            self._tool_apply_brand_voice,
            func_name="apply_brand_voice",
            func_description="Apply brand voice guidelines to draft text, ensuring tone and style compliance.",
        )
        toolkit.register_tool_function(
            self._tool_select_template,
            func_name="select_template",
            func_description="Select the appropriate text template for the artifact family.",
        )
        toolkit.register_tool_function(
            self._tool_format_output,
            func_name="format_output",
            func_description="Format the final text output with proper structure and metadata.",
        )
        return toolkit

    def _tool_apply_brand_voice(self, draft_text: str | None = None, brand_voice: str | None = None) -> Any:
        return self.tool_response({
            "instruction": "Rewrite the draft to match brand voice guidelines.",
            "draft": draft_text or "",
            "brand_voice": brand_voice or "Professional default.",
        })

    def _tool_select_template(self, artifact_family: str | None = None) -> Any:
        templates = {
            "email": "subject | greeting | body | cta | sign_off",
            "invoice": "header | invoice_meta | bill_to | line_items | totals | payment_terms | footer",
            "letter": "sender_info | date | recipient_info | salutation | body | closing | signature",
            "memo": "to_from_date_subject | executive_summary | body | action_items",
            "proposal": "executive_summary | problem | solution | scope | timeline | pricing | terms",
            "social_post": "hook | body | hashtags | cta",
            "summary": "key_finding | evidence | analysis | recommendation",
        }
        family = artifact_family or "summary"
        return self.tool_response({
            "artifact_family": family,
            "template_structure": templates.get(family, templates["summary"]),
        })

    def _tool_format_output(self, content: str | None = None, family: str | None = None) -> Any:
        return self.tool_response({
            "formatted": True,
            "family": family or "summary",
            "content": content or "",
        })

    def _format_evidence_for_prompt(self, evidence: EvidencePack) -> str:
        """Format evidence findings into a concise prompt section."""
        lines: list[str] = []
        for finding in evidence.memory_findings[:12]:
            source_tag = f"[source:{finding.source_ids[0]}]" if finding.source_ids else ""
            lines.append(f"- {finding.title}: {finding.summary} {source_tag}")
        for finding in evidence.web_findings[:8]:
            source_tag = f"[source:{finding.source_ids[0]}]" if finding.source_ids else ""
            lines.append(f"- {finding.title}: {finding.summary} {source_tag}")
        for finding in evidence.doc_findings[:6]:
            source_tag = f"[source:{finding.source_ids[0]}]" if finding.source_ids else ""
            lines.append(f"- {finding.title}: {finding.summary} {source_tag}")
        if evidence.summary:
            lines.insert(0, f"Evidence Summary: {evidence.summary}")
        return "\n".join(lines) or "No evidence findings available."

    async def compose(
        self,
        *,
        user_query: str,
        artifact_family: str,
        evidence_pack: EvidencePack,
        hitl_answers: dict[str, str] | None = None,
        brand_voice: str | None = None,
        tenant_id: str = "default",
        prior_context: str = "",
    ) -> TextArtifact:
        """Compose a text artifact in brand voice.

        Args:
            user_query: The original user request.
            artifact_family: One of TEXT_FAMILIES (email, invoice, etc.).
            evidence_pack: Research evidence gathered by the research agent.
            hitl_answers: Answers from the HITL clarification stage.
            brand_voice: Brand voice markdown. Loaded from tenant if not provided.
            tenant_id: Tenant ID for brand voice fallback.

        Returns:
            A completed TextArtifact ready for governance review.
        """
        if brand_voice is None:
            brand_voice = load_brand_voice(tenant_id)

        family_key = artifact_family if artifact_family in TEXT_FAMILIES else "summary"
        skill_prompt = load_skill(family_key, "text_buddy")
        evidence_text = self._format_evidence_for_prompt(evidence_pack)

        hitl_section = ""
        if hitl_answers:
            hitl_lines = [f"- {key}: {value}" for key, value in hitl_answers.items()]
            hitl_section = f"\n\n## User Clarifications\n" + "\n".join(hitl_lines)

        source_refs = [
            s.source_id for s in evidence_pack.sources if s.source_id
        ][:20]

        prompt = (
            f"## Skill Instructions\n{skill_prompt}\n\n"
            f"## Brand Voice Guidelines\n{brand_voice}\n\n"
            f"## Evidence\n{evidence_text}"
            f"{hitl_section}\n\n"
            f"{prior_context}"
            f"## Task\n"
            f"Artifact type: {family_key}\n"
            f"User request: {user_query}\n\n"
            f"Write the complete {family_key} following the template structure "
            f"from your skill instructions. Apply the brand voice guidelines exactly. "
            f"Cite evidence using [source:ID] format where applicable. "
            f"Output ONLY the final text content — no commentary or explanation."
        )

        await self.log(
            f"Composing {family_key} in brand voice for tenant {tenant_id}",
            kind="status",
            detail={"artifact_family": family_key, "evidence_count": len(evidence_pack.sources)},
        )

        # Use acompletion() directly (like VanGogh/ContentDirector) to ensure
        # correct model routing through the LiteLLM proxy with full model name.
        response = await self.resolver.acompletion(
            "text_buddy",
            [
                {"role": "system", "content": self.sys_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        content = self.resolver.extract_text(response)

        await self.log(
            f"Finished composing {family_key} ({len(content)} chars)",
            kind="status",
            detail={"artifact_family": family_key, "content_length": len(content)},
        )

        return TextArtifact(
            artifact_id=str(uuid4()),
            family=family_key,
            title=f"{family_key.replace('_', ' ').title()}: {user_query[:80]}",
            content=content,
            template_used=family_key,
            brand_voice_applied=bool(brand_voice),
            evidence_refs=source_refs,
            governance_status="pending",
        )
