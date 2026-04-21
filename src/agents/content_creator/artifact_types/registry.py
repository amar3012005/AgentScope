"""Artifact type registry for Vangogh V2 template engine."""
from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class ArtifactKind(str, Enum):
    PITCH_DECK = "pitch_deck"
    POSTER = "poster"
    KEYNOTE = "keynote"
    REPORT = "report"
    ONE_PAGER = "one_pager"
    DASHBOARD = "dashboard"


class SectionSpec(BaseModel):
    """Defines one section/slide within an artifact type."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    label: str
    template_name: str  # Jinja2 template filename (e.g. "hero_section.html.j2")
    schema_class: str = ""  # Name of the Pydantic model class for section data
    required: bool = True
    max_items: int = 1
    default_layout: str = "full"  # full | bento | sidebar | hero | stat-showcase


class ArtifactTypeDefinition(BaseModel):
    """Complete definition of an artifact type."""

    model_config = ConfigDict(extra="forbid")

    kind: ArtifactKind
    label: str
    description: str
    sections: List[SectionSpec]
    default_skills: List[str] = Field(default_factory=list)
    supports_navigation: bool = False
    supports_pagination: bool = False
    max_sections: int = 20


_CONTENT_KEYWORDS: dict[ArtifactKind, list[str]] = {
    ArtifactKind.PITCH_DECK: [
        "pitch deck",
        "pitch-deck",
        "pitchdeck",
        "investor deck",
        "investor presentation",
        "funding deck",
        "series a deck",
    ],
    ArtifactKind.POSTER: [
        "poster",
        "flyer",
        "banner",
        "infographic",
    ],
    ArtifactKind.KEYNOTE: [
        "keynote",
        "presentation",
        "slide deck",
        "slides",
        "talk",
        "conference",
    ],
    ArtifactKind.REPORT: [
        "report",
        "analysis",
        "whitepaper",
        "white paper",
        "research report",
        "quarterly report",
    ],
    ArtifactKind.ONE_PAGER: [
        "one-pager",
        "one pager",
        "onepager",
        "summary page",
        "executive summary",
        "brief",
    ],
    ArtifactKind.DASHBOARD: [
        "dashboard",
        "metrics dashboard",
        "kpi dashboard",
        "analytics dashboard",
        "data dashboard",
    ],
}


class ArtifactTypeRegistry:
    """Registry of artifact type definitions."""

    def __init__(self) -> None:
        self._types: dict[ArtifactKind, ArtifactTypeDefinition] = {}

    def register(self, defn: ArtifactTypeDefinition) -> None:
        self._types[defn.kind] = defn

    def get(self, kind: ArtifactKind) -> ArtifactTypeDefinition:
        if kind not in self._types:
            raise KeyError(f"Artifact type '{kind}' not registered")
        return self._types[kind]

    def detect_kind(
        self, user_query: str, skills: list[str] | None = None
    ) -> ArtifactKind:
        """Detect artifact kind from user query via keyword matching."""
        query_lower = user_query.lower()
        for kind, keywords in _CONTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                return kind
        # Fallback based on skills
        if skills:
            if "pitch_deck" in skills:
                return ArtifactKind.PITCH_DECK
            if "data_viz" in skills:
                return ArtifactKind.DASHBOARD
        return ArtifactKind.PITCH_DECK  # Default fallback

    def list_kinds(self) -> list[ArtifactKind]:
        return list(self._types.keys())
