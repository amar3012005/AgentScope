from __future__ import annotations

from agentscope_blaiq.agents.text_buddy.models import ComposePromptParts
from agentscope_blaiq.contracts.evidence import EvidencePack

SYSTEM_PROMPT = (
    "You are TextBuddy, BLAIQ's brand-voice text writer. "
    "You receive research evidence, user requirements, and brand voice guidelines, "
    "then produce polished, ready-to-use text content. "
    "Always follow the brand voice guidelines exactly. "
    "Cite evidence using [source:ID] format. "
    "Write in active voice with concise, professional prose. "
    "Structure your output according to the artifact template provided."
)


def format_evidence_for_prompt(evidence: EvidencePack) -> str:
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


def build_hitl_section(hitl_answers: dict[str, str] | None) -> str:
    if not hitl_answers:
        return ""
    hitl_lines = [f"- {key}: {value}" for key, value in hitl_answers.items()]
    return f"\n\n## User Clarifications\n" + "\n".join(hitl_lines)


def build_compose_prompt(parts: ComposePromptParts) -> str:
    if parts.family_key == "summary":
        return (
            f"## Skill Instructions\n{parts.skill_prompt}\n\n"
            f"## Brand Voice Guidelines\n{parts.brand_voice}\n\n"
            f"## Evidence\n{parts.evidence_text}"
            f"{parts.hitl_section}\n\n"
            f"{parts.prior_context}"
            f"## Task\n"
            f"Artifact type: {parts.family_key}\n"
            f"User request: {parts.user_query}\n\n"
            "Write a structured final answer with the following exact sections:\n"
            "## Analysis\n"
            "- Summarize the evidence and any key constraints.\n"
            "- Mention source coverage, confidence, and open questions if relevant.\n\n"
            "## ANSWER\n"
            "- Provide the direct answer in clear, professional prose.\n"
            "- Keep the content grounded in the evidence.\n"
            "- Use [source:ID] citations inline where factual claims are made.\n\n"
            "## Confidence\n"
            "- Include a one-line confidence statement or score.\n\n"
            "## Sources\n"
            "- List the most relevant source identifiers and short labels.\n\n"
            "Rules:\n"
            "- Do not add any extra sections beyond the ones above.\n"
            "- Do not add commentary outside the structured sections.\n"
            "- Output ONLY the final text content.\n"
        )

    return (
        f"## Skill Instructions\n{parts.skill_prompt}\n\n"
        f"## Brand Voice Guidelines\n{parts.brand_voice}\n\n"
        f"## Evidence\n{parts.evidence_text}"
        f"{parts.hitl_section}\n\n"
        f"{parts.prior_context}"
        f"## Task\n"
        f"Artifact type: {parts.family_key}\n"
        f"User request: {parts.user_query}\n\n"
        f"Write the complete {parts.family_key} following the template structure "
        f"from your skill instructions. Apply the brand voice guidelines exactly. "
        f"Cite evidence using [source:ID] format where applicable. "
        f"Output ONLY the final text content — no commentary or explanation."
    )
