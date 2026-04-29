from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscope_blaiq.contracts.evidence import EvidencePack, EvidenceFinding

logger = logging.getLogger(__name__)

def is_usable_finding(f: "EvidenceFinding") -> bool:
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

def format_evidence_for_prompt(evidence_pack: "EvidencePack" | None, max_findings: int = 15) -> str:
    if evidence_pack is None:
        return "No evidence pack provided."
    # Memory findings are the primary knowledge base (HIVE-MIND).
    # Doc findings can be useful but often contain test files or unparsed PDFs.
    # Web findings are generic and go last.
    memory = [f for f in evidence_pack.memory_findings if is_usable_finding(f)]
    docs = [f for f in evidence_pack.doc_findings if is_usable_finding(f)]
    web = [f for f in evidence_pack.web_findings if is_usable_finding(f)]
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

def build_enriched_evidence_context(evidence_pack: "EvidencePack" | None) -> str:
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
