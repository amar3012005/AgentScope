"""Load agent skills based on artifact family and agent role."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).parent
_SAFE_TENANT_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def load_skill(artifact_family: str, role: str) -> str:
    """Load the skill file for a given artifact family and agent role.

    Args:
        artifact_family: e.g. "pitch_deck", "poster", "finance_analysis", "report"
        role: "content" for ContentDirector, "visual" for Vangogh, "text_buddy" for TextBuddy

    Returns:
        The skill content as a string. Includes shared rules prepended.
    """
    parts: list[str] = []

    # Always load shared evidence rules
    evidence_rules = _SKILLS_DIR / "shared" / "evidence_rules.md"
    if evidence_rules.exists():
        parts.append(evidence_rules.read_text(encoding="utf-8"))

    # For text_buddy, load main skill first, then artifact-specific skill
    if role == "text_buddy":
        main_skill = _SKILLS_DIR / "text_buddy" / "main.md"
        if main_skill.exists():
            parts.append(main_skill.read_text(encoding="utf-8"))
        artifact_skill = _SKILLS_DIR / "text_buddy" / f"{artifact_family}.md"
        if artifact_skill.exists():
            parts.append(artifact_skill.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(parts)

    # Load shared slide types reference (visual pipeline only)
    slide_types = _SKILLS_DIR / "shared" / "slide_types.md"
    if slide_types.exists():
        parts.append(slide_types.read_text(encoding="utf-8"))

    # Load artifact-specific skill
    skill_path = _SKILLS_DIR / artifact_family / f"{role}.md"
    if skill_path.exists():
        parts.append(skill_path.read_text(encoding="utf-8"))
    else:
        # Fallback to pitch_deck as default
        fallback = _SKILLS_DIR / "pitch_deck" / f"{role}.md"
        if fallback.exists():
            parts.append(fallback.read_text(encoding="utf-8"))

    return "\n\n---\n\n".join(parts)


def load_brand_voice(tenant_id: str) -> str:
    """Load the brand voice markdown for a tenant.

    Args:
        tenant_id: Tenant identifier (e.g. "davinci_ai"). Falls back to "default".

    Returns:
        Brand voice guidelines as a markdown string.
    """
    from agentscope_blaiq.runtime.config import settings

    brand_voice_dir = Path(settings.brand_voice_dir).resolve()

    # Validate tenant_id to prevent path traversal
    safe_id = tenant_id if _SAFE_TENANT_ID.match(tenant_id) else "default"
    tenant_path = (brand_voice_dir / f"{safe_id}.md").resolve()
    if not str(tenant_path).startswith(str(brand_voice_dir)):
        tenant_path = brand_voice_dir / "default.md"

    if tenant_path.exists():
        return tenant_path.read_text(encoding="utf-8")
    default_path = brand_voice_dir / "default.md"
    if default_path.exists():
        return default_path.read_text(encoding="utf-8")
    return "Use a professional, clear, and concise writing style."


def load_brand_context(brand_dna: dict[str, Any] | None) -> str:
    """Format Brand DNA as a context string for agent prompts."""
    if not brand_dna:
        return "No Brand DNA configured. Use default styling."

    tokens: dict[str, str] = brand_dna.get("tokens", {})
    typo: dict[str, str] = brand_dna.get("typography", {})
    effects: list[str] = brand_dna.get("effects", [])

    lines: list[str] = [
        f"## Brand DNA: {brand_dna.get('theme', 'Custom')}",
        f"Description: {brand_dna.get('description', 'N/A')}",
        "",
        "### Color Tokens",
    ]
    for k, v in tokens.items():
        lines.append(f"- {k}: {v}")

    lines.append("")
    lines.append("### Typography")
    for k, v in typo.items():
        lines.append(f"- {k}: {v}")

    if effects:
        lines.append("")
        lines.append("### Design Effects")
        for e in effects:
            lines.append(f"- {e}")

    return "\n".join(lines)
