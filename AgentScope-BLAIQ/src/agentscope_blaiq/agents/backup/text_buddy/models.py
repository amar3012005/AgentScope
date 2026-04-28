from __future__ import annotations

from dataclasses import dataclass
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class ComposePromptParts:
    """Normalized sections used to construct the compose prompt."""

    skill_prompt: str
    brand_voice: str
    evidence_text: str
    hitl_section: str
    prior_context: str
    family_key: str
    user_query: str


class TextCompositionResult(BaseModel):
    """Structured output from TextBuddyAgent."""

    content: str = Field(description="The final composed text content.")
    citations: list[str] = Field(default_factory=list, description="IDs of cited sources.")
    template_used: str = Field(description="The name of the template structure followed.")
    tone_applied: str = Field(description="The primary tone or brand voice variant applied.")
