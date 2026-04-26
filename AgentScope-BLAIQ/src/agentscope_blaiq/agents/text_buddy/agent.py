from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentscope.tool import Toolkit
from agentscope.message import Msg

from agentscope_blaiq.agents.skills import load_brand_voice
from agentscope_blaiq.agents.text_buddy.models import ComposePromptParts, TextCompositionResult
from agentscope_blaiq.agents.text_buddy.prompts import (
    SYSTEM_PROMPT,
    build_compose_prompt,
    build_hitl_section,
    format_evidence_for_prompt,
)
from agentscope_blaiq.agents.text_buddy.tools import (
    apply_brand_voice,
    format_output,
    select_template,
)
from agentscope_blaiq.contracts.artifact import TextArtifact
from agentscope_blaiq.contracts.evidence import EvidencePack
from agentscope_blaiq.contracts.messages import make_agent_input, make_agent_output
from agentscope_blaiq.contracts.workflow import TEXT_ARTIFACT_FAMILIES
from agentscope_blaiq.contracts.agent_catalog import AgentCapability, AgentSkill
from agentscope_blaiq.runtime.agent_base import BaseAgent

# Keep legacy logger name stable for downstream log filtering.
logger = logging.getLogger("agentscope_blaiq.agents.text_buddy")

# Re-export for backward compatibility
TEXT_FAMILIES = TEXT_ARTIFACT_FAMILIES
TEXT_BUDDY_TOOL_IDS = ("select_template", "apply_brand_voice", "format_output")


def _normalize_section_key(raw_key: str) -> str:
    key = (raw_key or "").strip().lower()
    if key.startswith("section:"):
        key = key.split(":", 1)[1]
    return key.replace(" ", "_")


def _loaded_skill_files(family_key: str) -> list[str]:
    files = [
        "shared/evidence_rules.md",
        "text_buddy/main.md",
    ]
    family_file = f"text_buddy/{family_key}.md"
    files.append(family_file)
    return files


_TEXT_FAMILIES = ["email", "invoice", "letter", "memo", "proposal", "report", "social_post", "summary"]


class TextBuddyAgent(BaseAgent):
    """Brand-voice text writer for BLAIQ.

    Produces final text-based outputs (emails, invoices, letters, memos,
    proposals, social posts, summaries) by combining research evidence,
    HITL-refined requirements, and enterprise brand voice guidelines.
    """

    # Self-declared profile — registry.py reads these directly.
    # Add a capability here and it propagates to the planner catalog automatically.
    CAPABILITIES: list[AgentCapability] = [
        AgentCapability(
            name="text_composition",
            description="Compose final text outputs in brand voice.",
            supported_task_types=["writing", "composition"],
            supported_task_roles=["text_buddy"],
            supported_artifact_families=_TEXT_FAMILIES,
        ),
        AgentCapability(
            name="brand_voice_writing",
            description="Apply enterprise-specific brand voice guidelines to all text output.",
            supported_task_types=["writing", "brand"],
            supported_task_roles=["text_buddy"],
            supported_artifact_families=_TEXT_FAMILIES,
        ),
        AgentCapability(
            name="template_formatting",
            description="Format text according to artifact-specific templates (email structure, invoice layout, etc.).",
            supported_task_types=["writing", "formatting"],
            supported_task_roles=["text_buddy"],
            supported_artifact_families=_TEXT_FAMILIES,
        ),
    ]

    SKILLS: list[AgentSkill] = [
        AgentSkill(name="brand_voice_application", level="core"),
        AgentSkill(name="text_template_adherence", level="core"),
        AgentSkill(name="evidence_citation", level="core"),
    ]

    TOOLS: list[str] = ["apply_brand_voice", "select_template", "format_output"]
    PLANNER_ROLES: list[str] = ["text_buddy"]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="TextBuddyAgent",
            role="text_buddy",
            sys_prompt=SYSTEM_PROMPT,
            **kwargs,
        )

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        # Real ReActAgent tools
        self.register_tool(toolkit, tool_id="apply_brand_voice", fn=apply_brand_voice, description="Apply brand voice guidelines to draft text, ensuring tone and style compliance.")
        self.register_tool(toolkit, tool_id="select_template", fn=select_template, description="Select the appropriate text template for the artifact family.")
        self.register_tool(toolkit, tool_id="format_output", fn=format_output, description="Format the final text output with proper structure and metadata.")

        # Skills via register_agent_skill (replaces manual load_skill)
        skills_base = Path(__file__).parent / "skills"
        if skills_base.exists():
            for skill_dir in skills_base.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    toolkit.register_agent_skill(str(skill_dir))

        return toolkit

    def _citation_validation_hook(self, _agent: Any, _kwargs: Any, output: Msg) -> Msg:
        """Post-reply hook for citation validation."""
        text = output.get_text_content() if hasattr(output, "get_text_content") else str(output)
        citation_pattern = re.compile(r"\[source:[^\]]+\]")
        sentences = [s.strip() for s in re.split(r"[.!?]\s+", text) if len(s.strip()) > 30]
        uncited = [s for s in sentences if not citation_pattern.search(s)]
        if uncited:
            logger.info("text_buddy citation_check: %d uncited claims", len(uncited))
        return output

    def _format_evidence_for_prompt(self, evidence: EvidencePack) -> str:
        return format_evidence_for_prompt(evidence)

    def _deterministic_fallback_content(
        self,
        *,
        user_query: str,
        family_key: str,
        evidence_pack: EvidencePack,
        hitl_answers: dict[str, str] | None,
    ) -> str:
        """Generate robust text output when model inference is unavailable.

        This prevents workflow failure in low-connectivity / missing-key modes.
        """
        answers = {_normalize_section_key(k): v for k, v in (hitl_answers or {}).items()}
        evidence_lines: list[str] = []
        for source in (evidence_pack.sources or [])[:5]:
            source_id = source.source_id or "uncited"
            title = source.title or "source"
            evidence_lines.append(f"- {title} [source:{source_id}]")
        if not evidence_lines:
            evidence_lines.append("- No validated external sources were available [source:uncited]")

        subject = answers.get("subject") or f"Update: {user_query[:70]}".strip()
        greeting = answers.get("greeting") or "Hi there,"
        body = answers.get("body") or user_query
        cta = answers.get("cta") or "Reply to this email and we will help you get started."
        sign_off = answers.get("sign-off") or answers.get("sign_off") or "Best,\nThe Team"

        if family_key == "email":
            return (
                f"Subject: {subject}\n\n"
                f"{greeting}\n\n"
                f"{body}\n\n"
                f"Why this matters:\n"
                f"{chr(10).join(evidence_lines)}\n\n"
                f"Next step: {cta}\n\n"
                f"{sign_off}"
            )

        bullets = []
        for key in ("summary", "body", "cta"):
            if answers.get(key):
                bullets.append(f"- {answers[key]}")
        if not bullets:
            bullets = [f"- {user_query}", "- Generated in deterministic fallback mode due model unavailability."]
        return (
            f"{family_key.replace('_', ' ').title()}\n\n"
            f"{chr(10).join(bullets)}\n\n"
            f"Evidence:\n{chr(10).join(evidence_lines)}"
        )

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
        input_msg = make_agent_input(
            workflow_id=None,
            node_id="text_buddy",
            agent_id="text_buddy",
            payload={"artifact_family": artifact_family, "user_query": user_query},
            schema_ref="TextBuddyInput",
        )
        logger.debug("text_buddy input_msg=%s", input_msg.msg_id)

        source_refs = [
            str(source.source_id)
            for source in (evidence_pack.sources or [])
            if getattr(source, "source_id", None)
        ]

        if brand_voice is None:
            brand_voice = load_brand_voice(tenant_id)

        family_key = artifact_family if artifact_family in TEXT_FAMILIES else "summary"
        toolkit = self.build_toolkit()
        skill_prompt = toolkit.get_agent_skill_prompt()
        evidence_text = self._format_evidence_for_prompt(evidence_pack)
        hitl_section = build_hitl_section(hitl_answers)

        await self.log(
            f"Composing {family_key} in brand voice for tenant {tenant_id}",
            kind="status",
            detail={"artifact_family": family_key, "evidence_count": len(evidence_pack.sources)},
        )

        prompt = build_compose_prompt(
            ComposePromptParts(
                skill_prompt=skill_prompt,
                brand_voice=brand_voice,
                evidence_text=evidence_text,
                hitl_section=hitl_section,
                prior_context=prior_context,
                family_key=family_key,
                user_query=user_query,
            )
        )

        try:
            # Create runtime agent with current notebook (if any)
            runtime_agent = self._create_runtime_agent()
            runtime_agent.register_instance_hook("post_reply", "citation_validator", self._citation_validation_hook)
            
            response = await runtime_agent.reply(
                self.make_msg(
                    self._build_user_prompt(
                        prompt,
                        {
                            "artifact_family": family_key,
                            "brand_voice": brand_voice[:100],
                            "tenant_id": tenant_id,
                        },
                    ),
                    role="user",
                    phase="request",
                ),
                structured_model=TextCompositionResult,
            )
            if response.metadata:
                result = TextCompositionResult.model_validate(response.metadata)
            else:
                payload = self.resolver.safe_json_loads(self._extract_msg_text(response))
                result = TextCompositionResult.model_validate(payload)
            content = result.content
        except Exception as exc:
            logger.warning("text_buddy ReAct compose failed; using deterministic fallback", exc_info=True)
            await self.log(
                f"Model compose failed ({type(exc).__name__}); using deterministic fallback.",
                kind="warning",
                detail={"artifact_family": family_key},
            )
            content = self._deterministic_fallback_content(
                user_query=user_query,
                family_key=family_key,
                evidence_pack=evidence_pack,
                hitl_answers=hitl_answers,
            )

        await self.log(
            f"Finished composing {family_key} ({len(content)} chars)",
            kind="status",
            detail={"artifact_family": family_key, "content_length": len(content)},
        )

        # Citation integrity check: every claim should be cited or explicitly marked uncited
        citation_pattern = re.compile(r"\[source:[^\]]+\]")
        cited_count = len(citation_pattern.findall(content))
        # Split content into sentences/claims for basic citation coverage check
        sentences = [s.strip() for s in re.split(r"[.!?]\s+", content) if len(s.strip()) > 30]
        uncited_claims = [s for s in sentences if not citation_pattern.search(s)]
        if uncited_claims:
            logger.info(
                "text_buddy citation_check: %d/%d claims uncited for %s",
                len(uncited_claims),
                len(sentences),
                family_key,
            )

        artifact = TextArtifact(
            artifact_id=str(uuid4()),
            family=family_key,
            title=f"{family_key.replace('_', ' ').title()}: {user_query[:80]}",
            content=content,
            template_used=family_key,
            brand_voice_applied=bool(brand_voice),
            evidence_refs=source_refs,
            governance_status="pending",
        )

        output_msg = make_agent_output(
            input_msg=input_msg,
            payload={"artifact_id": artifact.artifact_id, "family": artifact.family},
            schema_ref="TextArtifact",
        )
        logger.debug("text_buddy output_msg=%s parent=%s", output_msg.msg_id, output_msg.parent_msg_id)

        return artifact
