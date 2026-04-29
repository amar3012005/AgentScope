from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agentscope_blaiq.agents.content_director.models import SlidesData

logger = logging.getLogger(__name__)

def is_pitch_deck_family(artifact_family: str) -> bool:
    return artifact_family in {"pitch_deck", "keynote"}

def default_pitch_deck_sections() -> list[str]:
    return [
        "Title",
        "Problem",
        "Solution",
        "Proof",
        "Differentiation",
        "Ask",
    ]

def section_title_to_request(title: str, user_query: str, hitl_answers: dict[str, str] | None) -> str:
    normalized = title.strip().lower()
    cta = (hitl_answers or {}).get("cta", "")
    if normalized in {"title", "hook", "opening"}:
        return f"Validate the strongest opening hook for: {user_query}. Check if the headline is specific enough for a Hanover Messe enterprise audience."
    if normalized in {"problem", "challenge", "pain"}:
        return "Collect quantified market pain, operational friction, and recent evidence that supports the problem slide."
    if normalized in {"solution", "product", "approach"}:
        return "Gather crisp proof of the product architecture, core workflow, and why the solution is materially different."
    if normalized in {"proof", "traction", "evidence"}:
        return "Find the strongest proof points: traction, customer evidence, architecture credibility, and any compliant claims."
    if normalized in {"differentiation", "why us", "competition"}:
        return "Collect current competitor positioning, category language, and a clear differentiation comparison for the deck."
    if normalized in {"ask", "cta", "next steps"}:
        return f"Validate the best closing ask and partnership call-to-action for the deck. Existing CTA hint: {cta or 'none'}."
    return f"Find the strongest evidence and framing for slide '{title}' in the context of: {user_query}"

def pitch_deck_research_groups(
    *,
    user_query: str,
    section_titles: list[str],
    hitl_answers: dict[str, str] | None,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    if not section_titles:
        section_titles = default_pitch_deck_sections()
    chunks = [
        section_titles[:2],
        section_titles[2:4],
        section_titles[4:],
    ]
    for idx, titles in enumerate(chunks, start=1):
        if not titles:
            continue
        requests = [section_title_to_request(title, user_query, hitl_answers) for title in titles]
        groups.append(
            {
                "group_id": f"deck-bundle-{idx}",
                "slide_titles": titles,
                "request": " / ".join(requests),
            }
        )
    return groups

def template_name_for_family(family: Any) -> str:
    family_value = family.value if hasattr(family, "value") else str(family)
    if family_value == "custom":
        return "default"
    # Assuming ArtifactFamily import or similar string check
    if family_value == "finance_analysis":
        return "finance-analysis-executive"
    return f"{family_value.replace('_', '-')}-executive"
