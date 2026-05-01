from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class ArtifactSection(BaseModel):
    section_id: str
    section_index: int
    title: str
    summary: str
    html_fragment: str
    section_data: dict[str, str] = Field(default_factory=dict)


class PreviewMetadata(BaseModel):
    viewport: str = "desktop"
    format_hint: str = "visual_html"
    theme_notes: list[str] = Field(default_factory=list)


class MediaItem(BaseModel):
    """A single media asset in a VisualArtifact."""
    id: str
    type: Literal["image", "video"]
    src: str
    thumbnail_src: str | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None          # e.g. "16/9", "4/3", "1/1"
    mime_type: str = ""
    duration_ms: int | None = None           # video only
    alt: str = ""
    caption: str = ""
    status: Literal["pending", "ready", "failed"] = "ready"
    generation_state: Literal["pending", "ready", "failed"] = "ready"


class LayoutHints(BaseModel):
    layout: Literal["hero", "grid", "carousel", "inline", "stack"] = "grid"
    hero_item_id: str | None = None


class VisualArtifact(BaseModel):
    artifact_id: str
    artifact_type: str = "visual_html"
    title: str
    sections: list[ArtifactSection] = Field(default_factory=list)
    theme: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    governance_status: str = "pending"
    html: str = ""
    css: str = ""
    media: list[MediaItem] = Field(default_factory=list)
    layout_hints: LayoutHints = Field(default_factory=LayoutHints)
    preview_metadata: PreviewMetadata = Field(default_factory=PreviewMetadata)


class TextArtifact(BaseModel):
    """Final text output produced by the TextBuddy agent."""
    artifact_id: str
    artifact_type: str = "text"
    family: str
    title: str
    content: str
    template_used: str = "default"
    brand_voice_applied: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    governance_status: str = "pending"
    metadata: dict[str, str] = Field(default_factory=dict)
    completion_summary: str = ""
