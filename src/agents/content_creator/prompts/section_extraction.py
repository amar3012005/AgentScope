"""System prompts for section-level structured data extraction.

The LLM extracts JSON matching a specific Pydantic schema for each section
of an artifact. It never generates HTML — only structured data that the
Jinja2 template engine renders deterministically.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.content_creator.artifact_types.registry import SectionSpec
from agents.content_creator.artifact_types.section_schemas import get_json_schema_for_section


SECTION_EXTRACTION_SYSTEM = """\
You are a strategic content extraction engine for Da'Vinci AI.
Your job is to extract structured content for ONE section of a visual artifact.

RULES:
1. Output ONLY valid JSON matching the provided schema. No markdown, no explanations.
2. Extract real data from the provided context. Do NOT invent statistics, names, or claims not supported by the context.
3. If the context lacks data for a field, use a reasonable placeholder that clearly indicates it needs real data (e.g., "[TBD]", "0").
4. Write compelling, concise copy — not filler text. Every word should earn its place.
5. For stat values, use the exact numbers from context. Format them readably (e.g., "12.5M" not "12500000").
6. For insight/bullet items, lead with the conclusion, not the setup.
7. Maintain narrative continuity with prior sections (provided below).
"""

POSTER_EXTRACTION_APPENDIX = """\

POSTER-SPECIFIC ART DIRECTION:
- Posters must feel like studio-quality campaign work, not slide content pasted onto a canvas.
- Use short, high-tension copy with strong hierarchy. Prefer fewer, stronger words.
- Align every field to a clear poster purpose: campaign, event, launch, manifesto, announcement, or editorial.
- `eyebrow`, `supporting_line`, `urgency_label`, and proof labels should be crisp and operational, not vague slogans.
- `visual_motif` should describe a repeatable art direction element, not a generic style word.
- `focal_image_prompt` should describe a specific visual scene or composition direction the renderer can honor.
- `proof_items` should contain distinct proof types: metric, claim, quote, or offer.
- `details` should capture concrete event metadata, offer mechanics, channels, timing, or contact points.
- Respect Brand DNA implicitly: premium, deliberate, and tenant-specific. Avoid generic startup filler.
"""


def build_section_extraction_messages(
    section_spec: SectionSpec,
    raw_context: str,
    user_request: str,
    user_answers: Dict[str, str] | None = None,
    prior_sections_summary: str = "",
) -> List[Dict[str, str]]:
    """Build the messages array for section data extraction."""
    schema = get_json_schema_for_section(section_spec.schema_class)
    schema_str = str(schema) if schema else "{}"
    system_prompt = SECTION_EXTRACTION_SYSTEM
    if section_spec.schema_class.startswith("Poster") or section_spec.template_name.startswith("poster_"):
        system_prompt += POSTER_EXTRACTION_APPENDIX

    user_parts = []
    user_parts.append(f"ARTIFACT SECTION: {section_spec.label} (id: {section_spec.section_id})")
    user_parts.append(f"TEMPLATE: {section_spec.template_name}")
    user_parts.append(f"\nJSON SCHEMA (output must match this exactly):\n{schema_str}")
    user_parts.append(f"\nUSER REQUEST: {user_request}")

    if user_answers:
        answers_text = "\n".join(f"- {k}: {v}" for k, v in user_answers.items())
        user_parts.append(f"\nUSER ANSWERS:\n{answers_text}")

    if prior_sections_summary:
        user_parts.append(f"\nPRIOR SECTIONS (for narrative continuity):\n{prior_sections_summary}")

    # Truncate context to avoid token limits
    max_context = 6000
    context_text = raw_context[:max_context] if raw_context else "[No context provided]"
    user_parts.append(f"\nCONTEXT DATA:\n{context_text}")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def summarize_prior_sections(sections: List[Dict[str, Any]]) -> str:
    """Create a brief summary of prior sections for narrative continuity."""
    if not sections:
        return ""

    parts = []
    for s in sections:
        section_id = s.get("section_id", "unknown")
        data = s.get("data", {})
        # Extract key fields for summary
        headline = data.get("headline", "")
        title = data.get("title", "")
        label = headline or title or section_id
        parts.append(f"- {section_id}: {label}")

    return "\n".join(parts)
