from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import BaseModel, Field
from .workflow import ArtifactFamily


class BriefSection(BaseModel):
    """A detailed instruction for an artifact section."""

    section_id: str
    title: str
    objective: str
    key_points: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)  # IDs from EvidencePack
    visual_hint: Optional[str] = None  # e.g. "hero-chart", "benefit-grid"
    constraints: List[str] = Field(default_factory=list)
    research_requests: List[str] = Field(default_factory=list)
    speaker_notes: str = ""


class ArtifactBrief(BaseModel):
    """The canonical handoff from Content Director to Renderers (VanGogh/TextBuddy).

    This replaces the older ContentBriefHandoff and provides a thin, deterministic
    instruction set that decouples 'what to say' (Brief) from 'how to show it' (Renderer).
    """

    brief_id: str
    thread_id: str
    artifact_family: ArtifactFamily
    title: str
    core_narrative: str
    target_audience: str
    sections: List[BriefSection] = Field(default_factory=list)
    
    # Global Style & Brand Alignment
    brand_voice_id: Optional[str] = None
    style_preference: Optional[str] = "executive" # "creative", "technical", "minimal"
    
    # Governance & Context
    evidence_pack_id: str # Reference to the complete evidence finding set
    required_disclaimers: List[str] = Field(default_factory=list)
    
    # Metadata for the Renderer
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
