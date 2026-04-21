"""Vangogh V2 Jinja2 template engine.

Renders section-level HTML fragments and composes full artifact documents
from Brand DNA tokens and component templates. The LLM never generates
HTML --- it produces structured JSON that this engine renders deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Brand DNA color palette for Chart.js
_DEFAULT_CHART_COLORS = [
    "#F5F5F1",  # primary (off-white)
    "#CFCFCB",  # accent_blue
    "#8F8F8A",  # accent_emerald
    "#6E6E6A",  # accent_purple
    "#A1A19B",  # muted
]


class VangoghTemplateEngine:
    """Jinja2-based template engine for Vangogh V2 artifacts."""

    def __init__(
        self,
        templates_dir: str | Path | None = None,
        brand_dna: Dict[str, Any] | None = None,
        blueprint: Dict[str, Any] | None = None,
    ) -> None:
        self._templates_dir = Path(templates_dir) if templates_dir else TEMPLATES_DIR
        self._brand_dna = brand_dna or {}
        self._blueprint = blueprint or {}
        self._env = Environment(
            loader=FileSystemLoader(str(self._templates_dir)),
            autoescape=select_autoescape(["html", "j2"]),
        )
        self._register_globals()
        self._register_filters()

    def _register_globals(self) -> None:
        """Inject Brand DNA tokens into all templates as globals."""
        tokens = self._brand_dna.get("tokens", {})
        typography = self._brand_dna.get("typography", {})
        glassmorphism = self._brand_dna.get("glassmorphism", {})
        animations = self._brand_dna.get("animations", {})
        component_mappings = self._brand_dna.get("component_mappings", {})
        layout_patterns = self._brand_dna.get("layout_patterns", {})

        self._env.globals.update({
            "tokens": tokens,
            "typography": typography,
            "glassmorphism": glassmorphism,
            "animations": animations,
            "component_mappings": component_mappings,
            "layout_patterns": layout_patterns,
            "brand_dna": self._brand_dna,
            "blueprint": self._blueprint,
        })

    def _register_filters(self) -> None:
        """Register custom Jinja2 filters."""
        self._env.filters["tojson_safe"] = _tojson_safe

    def render_section(self, template_name: str, data: Dict[str, Any]) -> str:
        """Render a single section template to an HTML fragment."""
        template = self._env.get_template(f"sections/{template_name}")
        return template.render(**data)

    def render_component(self, component_name: str, data: Dict[str, Any]) -> str:
        """Render a single reusable component template."""
        template = self._env.get_template(f"components/{component_name}")
        return template.render(**data)

    def render_artifact(
        self,
        kind: str,
        sections: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> str:
        """Compose a full artifact document from rendered section fragments."""
        template = self._env.get_template(f"artifacts/{kind}.html.j2")
        return template.render(sections=sections, metadata=metadata)

    def render_base_shell(self, metadata: Dict[str, Any] | None = None) -> str:
        """Render the base document shell with empty body for progressive rendering."""
        template = self._env.get_template("base.html.j2")
        return template.render(body="", **(metadata or {}))

    @property
    def brand_dna(self) -> Dict[str, Any]:
        return self._brand_dna

    def set_blueprint(self, blueprint: Dict[str, Any]) -> None:
        self._blueprint = blueprint or {}
        self._env.globals["blueprint"] = self._blueprint


def build_chart_config(
    chart_type: str,
    title: str,
    labels: List[str],
    datasets: List[Dict[str, Any]],
    brand_dna: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a Chart.js configuration object using Brand DNA colors."""
    tokens = (brand_dna or {}).get("tokens", {})
    palette = [
        tokens.get("primary", _DEFAULT_CHART_COLORS[0]),
        tokens.get("accent_blue", _DEFAULT_CHART_COLORS[1]),
        tokens.get("accent_emerald", _DEFAULT_CHART_COLORS[2]),
        tokens.get("accent_purple", _DEFAULT_CHART_COLORS[3]),
        tokens.get("muted", _DEFAULT_CHART_COLORS[4]),
    ]
    muted = tokens.get("muted", "#A1A19B")

    chart_datasets = []
    for i, ds in enumerate(datasets):
        color = ds.get("color") or palette[i % len(palette)]
        chart_datasets.append({
            "label": ds.get("label", ""),
            "data": ds.get("data", []),
            "backgroundColor": color,
            "borderColor": color,
            "borderWidth": 1,
        })

    config: Dict[str, Any] = {
        "type": chart_type,
        "data": {
            "labels": labels,
            "datasets": chart_datasets,
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": True,
            "plugins": {
                "legend": {
                    "labels": {"color": muted, "font": {"family": "Manrope"}},
                },
                "title": {
                    "display": bool(title),
                    "text": title,
                    "color": tokens.get("ink", "#E8E7E2"),
                    "font": {"family": "Cormorant Garamond", "size": 18, "weight": "600"},
                },
            },
            "scales": {},
        },
    }

    # Add axes for non-radial chart types
    if chart_type in ("bar", "line"):
        config["options"]["scales"] = {
            "x": {
                "ticks": {"color": muted},
                "grid": {"color": "rgba(255,255,255,0.05)"},
            },
            "y": {
                "ticks": {"color": muted},
                "grid": {"color": "rgba(255,255,255,0.05)"},
                "beginAtZero": True,
            },
        }

    return config


def _tojson_safe(value: Any) -> str:
    """JSON-encode a value, escaping for safe HTML attribute embedding."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
