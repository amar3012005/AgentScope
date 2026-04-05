"""Load agent skills based on artifact family and agent role."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).parent


def load_skill(artifact_family: str, role: str) -> str:
    """Load the skill file for a given artifact family and agent role.

    Args:
        artifact_family: e.g. "pitch_deck", "poster", "finance_analysis", "report"
        role: "content" for ContentDirector, "visual" for Vangogh

    Returns:
        The skill content as a string. Includes shared rules prepended.
    """
    parts: list[str] = []

    # Always load shared evidence rules
    evidence_rules = _SKILLS_DIR / "shared" / "evidence_rules.md"
    if evidence_rules.exists():
        parts.append(evidence_rules.read_text(encoding="utf-8"))

    # Load shared slide types reference
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
