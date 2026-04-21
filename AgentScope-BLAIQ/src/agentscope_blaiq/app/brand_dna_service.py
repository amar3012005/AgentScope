from __future__ import annotations

import base64
import io
import json
import logging
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r"builtin type (SwigPyPacked|SwigPyObject|swigvarlink) has no __module__ attribute",
        category=DeprecationWarning,
    )
    import fitz
import litellm

from agentscope_blaiq.persistence.repositories import BrandDnaRepository, UploadRepository
from agentscope_blaiq.runtime.config import settings

logger = logging.getLogger(__name__)

HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")

DEFAULT_COMPILED_RUNTIME: dict[str, Any] = {
    "theme": "Extracted Brand",
    "version": "2.0",
    "description": "Auto-generated layered Brand DNA.",
    "tokens": {
        "primary": "inherit",
        "background": "inherit",
        "surface": "inherit",
        "border": "inherit",
        "accent_blue": "inherit",
        "accent_emerald": "inherit",
        "accent_purple": "inherit",
        "muted": "inherit",
        "ink": "inherit",
    },
    "typography": {
        "headings": "Inter, Arial, sans-serif",
        "body": "Inter, Arial, sans-serif",
        "title_massive": "text-6xl font-bold tracking-tight",
        "body_default": "text-base leading-relaxed",
    },
    "effects": [],
}

# Use the full LiteLLM-compatible path for the proxy
# Prefix with openai/ to force standard API routing through the proxy
MODEL_VISUAL = "openai/nebius/Qwen/Qwen2.5-VL-72B-Instruct"
MAX_VISUAL_UPLOADS = 6
MAX_VISUAL_IMAGE_BYTES = 6 * 1024 * 1024
MAX_VISUAL_PDF_PAGES = 2


def _strip_markdown_json(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrandDnaExtractionService:
    def __init__(self, tenant_id: str, repo: BrandDnaRepository, upload_repo: UploadRepository) -> None:
        self.tenant_id = tenant_id
        self.repo = repo
        self.upload_repo = upload_repo

    def _encode_image(self, image_path: str) -> str:
        path_obj = Path(image_path)
        if path_obj.stat().st_size > 20 * 1024 * 1024:
            raise ValueError(f"File {path_obj.name} exceeds 20MB limit")
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def _encode_pdf_pages(self, pdf_path: str, *, max_pages: int = 4, zoom: float = 1.5) -> list[str]:
        encoded_pages: list[str] = []
        path_obj = Path(pdf_path)
        if path_obj.stat().st_size > 50 * 1024 * 1024:
            raise ValueError(f"PDF {path_obj.name} exceeds 50MB limit")

        with fitz.open(pdf_path) as document:
            page_count = min(len(document), max_pages)
            matrix = fitz.Matrix(zoom, zoom)
            for page_index in range(page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                png_bytes = pixmap.tobytes("png")
                encoded_pages.append(base64.b64encode(png_bytes).decode("utf-8"))

        return encoded_pages

    def _source_descriptor(self, upload: Any) -> dict[str, Any]:
        return {
            "upload_id": upload.upload_id,
            "filename": upload.filename,
            "content_type": upload.content_type,
            "storage_path": upload.storage_path,
            "kind": "pdf" if (upload.content_type or "").endswith("pdf") else "image",
        }

    def _extract_hex_colors(self, value: Any) -> list[str]:
        matches: list[str] = []
        if isinstance(value, str):
            matches.extend(HEX_COLOR_RE.findall(value))
        elif isinstance(value, dict):
            for nested in value.values():
                matches.extend(self._extract_hex_colors(nested))
        elif isinstance(value, list):
            for nested in value:
                matches.extend(self._extract_hex_colors(nested))

        deduped: list[str] = []
        for match in matches:
            normalized = match.upper()
            if normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _pick_color(self, colors: list[str], index: int, fallback: str) -> str:
        return colors[index] if index < len(colors) else fallback

    def _build_fast_preview_payload(
        self,
        *,
        sources: list[dict[str, Any]],
        extracted: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        artifact_summary = extracted.get("artifact_summary", {}) if isinstance(extracted, dict) else {}
        brand_core = extracted.get("brand_core", {}) if isinstance(extracted, dict) else {}
        visual_system = extracted.get("visual_system", {}) if isinstance(extracted, dict) else {}
        palette = visual_system.get("palette", {}) if isinstance(visual_system, dict) else {}
        typography = visual_system.get("typography", {}) if isinstance(visual_system, dict) else {}
        composition = visual_system.get("composition", {}) if isinstance(visual_system, dict) else {}
        shape_language = visual_system.get("shape_language", {}) if isinstance(visual_system, dict) else {}

        extracted_colors = self._extract_hex_colors([
            palette.get("primary", []),
            palette.get("secondary", []),
            palette.get("neutrals", []),
            palette.get("accent", []),
        ])

        compiled_runtime = self._normalize_compiled_runtime({
            "theme": (brand_core.get("brand_keywords") or [artifact_summary.get("likely_purpose") or "Extracted Brand"])[0],
            "version": "2.0-preview",
            "description": artifact_summary.get("evidence_summary")
            or brand_core.get("evidence_summary")
            or "Fast preview generated from first-pass visual extraction.",
            "tokens": {
                "primary": self._pick_color(extracted_colors, 0, "#F5F5F1"),
                "background": self._pick_color(extracted_colors, 2, "#0F1115"),
                "surface": self._pick_color(extracted_colors, 3, "#151922"),
                "border": self._pick_color(extracted_colors, 4, "#262C37"),
                "accent_blue": self._pick_color(extracted_colors, 1, "#1C69D4"),
                "accent_emerald": self._pick_color(extracted_colors, 5, "#2E8B57"),
                "accent_purple": self._pick_color(extracted_colors, 6, "#0653B6"),
                "muted": self._pick_color(extracted_colors, 7, "#757575"),
                "ink": self._pick_color(extracted_colors, 8, "#262626"),
            },
            "typography": {
                "headings": ", ".join((typography.get("fallback_descriptors") or typography.get("font_candidates") or ["Helvetica, Arial, sans-serif"])[:2]),
                "body": ", ".join((typography.get("fallback_descriptors") or ["Helvetica, Arial, sans-serif"])[:2]),
                "title_massive": "text-6xl font-bold tracking-tight",
                "body_default": "text-base leading-relaxed",
            },
            "effects": (shape_language.get("motifs") or [])[:4],
        })

        normalized_preview = {
            "keywords": brand_core.get("brand_keywords", []),
            "tone_axes": brand_core.get("tone_axes", {}),
            "core_traits": brand_core.get("core_identity_traits", []),
            "contextual_traits": brand_core.get("contextual_or_campaign_traits", []),
            "confidence": brand_core.get("confidence", artifact_summary.get("confidence", 0.0)),
            "visual_system": {
                "palette": {
                    "tokens": compiled_runtime["tokens"],
                    "rules": palette.get("usage_rules", []),
                },
                "typography": {
                    "display_family": {},
                    "body_family": {},
                    "role_rules": typography.get("hierarchy_rules", []),
                    "fallback_css": {
                        "display": compiled_runtime["typography"]["headings"],
                        "body": compiled_runtime["typography"]["body"],
                    },
                },
                "composition": {
                    "grid_style": composition.get("grid_style", ""),
                    "alignment_bias": composition.get("alignment_bias", ""),
                    "density": composition.get("density", ""),
                    "negative_space_strategy": composition.get("negative_space_strategy", ""),
                    "focal_element_strategy": composition.get("focal_element_strategy", ""),
                    "motifs": shape_language.get("motifs", []),
                },
            },
            "recipes": extracted.get("design_recipes", {}),
            "guardrails": extracted.get("guardrails", {}),
        }

        designer_handoff = {
            "hard_constraints": {
                "palette_tokens": compiled_runtime["tokens"],
                "composition_rules": [
                    rule
                    for rule in [
                        composition.get("grid_style"),
                        composition.get("alignment_bias"),
                        composition.get("negative_space_strategy"),
                    ]
                    if rule
                ],
                "typography_rules": typography.get("hierarchy_rules", []),
            },
            "soft_constraints": {
                "preferred_motifs": shape_language.get("motifs", []),
                "preferred_moods": brand_core.get("brand_keywords", []),
                "preferred_spacing": [composition.get("density")] if composition.get("density") else [],
            },
            "optional_signatures": extracted.get("artifact_patterns", []),
            "avoid": extracted.get("guardrails", {}).get("avoid", []),
            "fallback_logic": {},
            "recipes": {
                "hero": extracted.get("design_recipes", {}).get("hero", []),
                "social": extracted.get("design_recipes", {}).get("social", []),
                "landing_page": extracted.get("design_recipes", {}).get("landing_page", []),
            },
        }

        document = self._build_final_document(
            sources=sources,
            extracted=extracted,
            normalized=normalized_preview,
            designer_handoff=designer_handoff,
            compiled_runtime=compiled_runtime,
            warnings=warnings,
        )
        document["meta"]["extraction_mode"] = "visual-preview"
        return document

    def _build_visual_system_prompt(self) -> str:
        return """You are BrandDNA-Vision, a specialist visual identity analysis model for Blaiq.

Analyze uploaded brand artifacts and return a layered visual brand representation useful for a downstream visual designer agent.

Rules:
- Prefer observable evidence over speculation.
- Do not hallucinate exact font names. If uncertain, return descriptive font descriptors.
- Distinguish core identity traits from artifact-specific traits.
- Extract composition and motif logic, not just palette and fonts.
- Prioritize dominant style signals: layout archetype, component shape language, density, rhythm, contrast model.
- For UI/dashboard artifacts, explicitly capture grid behavior, card modules, data-viz treatment, and typography scale.
- Return strict JSON only. No markdown.

Return valid JSON with this exact structure:
{
  "artifact_summary": {
    "artifact_type": "",
    "likely_purpose": "",
    "analysis_scope": "",
    "page_roles": [],
    "confidence": 0.0,
    "evidence_summary": ""
  },
  "brand_core": {
    "tone_axes": {
      "formal_informal": 0.0,
      "minimal_expressive": 0.0,
      "premium_accessible": 0.0,
      "corporate_editorial": 0.0,
      "technical_human": 0.0,
      "playful_serious": 0.0
    },
    "brand_keywords": [],
    "core_identity_traits": [],
    "contextual_or_campaign_traits": [],
    "uncertain_traits": [],
    "confidence": 0.0,
    "evidence_summary": ""
  },
  "visual_system": {
    "palette": {
      "primary": [],
      "secondary": [],
      "neutrals": [],
      "accent": [],
      "usage_rules": [],
      "confidence": 0.0,
      "evidence_summary": ""
    },
    "typography": {
      "font_candidates": [],
      "hierarchy_rules": [],
      "style_rules": [],
      "fallback_descriptors": [],
      "confidence": 0.0,
      "evidence_summary": ""
    },
    "composition": {
      "layout_archetype": "",
      "grid_style": "",
      "alignment_bias": "",
      "density": "",
      "negative_space_strategy": "",
      "focal_element_strategy": "",
      "scale_behavior": "",
      "confidence": 0.0,
      "evidence_summary": ""
    },
    "shape_language": {
      "geometry": [],
      "corner_style": "",
      "stroke_style": "",
      "motifs": [],
      "confidence": 0.0,
      "evidence_summary": ""
    }
  },
  "artifact_patterns": [],
  "design_recipes": {
    "hero": [],
    "social": [],
    "presentation_cover": [],
    "landing_page": [],
    "marketing_banner": [],
    "confidence": 0.0,
    "evidence_summary": ""
  },
  "guardrails": {
    "must_preserve": [],
    "should_prefer": [],
    "use_sparingly": [],
    "avoid": [],
    "forbidden_patterns": [],
    "confidence": 0.0,
    "evidence_summary": ""
  },
  "provenance": {
    "source_pages_or_regions": [],
    "notes": []
  }
}"""

    def _build_normalization_prompt(self, raw_brand_dna: dict[str, Any]) -> str:
        return f"""You are BrandDNA-Composer for Blaiq.

Your task is to normalize a raw layered brand DNA analysis into:
1. a normalized brand document,
2. a compact designer handoff,
3. a compiled runtime brand DNA for rendering.

Rules:
- Preserve high-confidence evidence.
- Convert uncertain exact font names into descriptive fallbacks.
- Prefer reusable composition logic over vague adjectives.
- Keep hard constraints separate from soft constraints.
- Return strict JSON only.

INPUT RAW BRAND DNA:
{json.dumps(raw_brand_dna, indent=2)}

Return valid JSON with this exact structure:
{{
  "normalized_brand_dna": {{
    "keywords": [],
    "tone_axes": {{}},
    "core_traits": [],
    "contextual_traits": [],
    "confidence": 0.0,
    "visual_system": {{
      "palette": {{
        "tokens": {{
          "primary": "#HEX (Main primary color OR transparent if not seen)",
          "background": "#HEX (Primary canvas/background color)",
          "surface": "#HEX",
          "border": "#HEX",
          "accent_blue": "#HEX",
          "accent_emerald": "#HEX",
          "accent_purple": "#HEX",
          "muted": "#HEX",
          "ink": "#HEX (Primary content/text color)"
        }},
        "rules": []
      }},
      "typography": {{
        "display_family": {{}},
        "body_family": {{}},
        "role_rules": [],
        "fallback_css": {{
          "display": "",
          "body": ""
        }}
      }},
      "composition": {{
        "grid_style": "",
        "alignment_bias": "",
        "density": "",
        "negative_space_strategy": "",
        "focal_element_strategy": "",
        "motifs": []
      }}
    }},
    "recipes": {{
      "hero": [],
      "social": [],
      "landing_page": [],
      "presentation_cover": [],
      "marketing_banner": []
    }},
    "guardrails": {{
      "must_preserve": [],
      "should_prefer": [],
      "use_sparingly": [],
      "avoid": [],
      "forbidden_patterns": []
    }}
  }},
  "designer_handoff": {{
    "hard_constraints": {{
      "palette_tokens": {{}},
      "composition_rules": [],
      "typography_rules": []
    }},
    "soft_constraints": {{
      "preferred_motifs": [],
      "preferred_moods": [],
      "preferred_spacing": []
    }},
    "optional_signatures": [],
    "avoid": [],
    "fallback_logic": {{}},
    "recipes": {{
      "hero": [],
      "social": [],
      "landing_page": []
    }}
  }},
  "compiled_runtime": {{
    "theme": "string",
    "version": "2.0",
    "description": "string",
    "tokens": {{
      "primary": "#HEX",
      "background": "#HEX",
      "surface": "#HEX",
      "border": "#HEX",
      "accent_blue": "#HEX",
      "accent_emerald": "#HEX",
      "accent_purple": "#HEX",
      "muted": "#HEX",
      "ink": "#HEX"
    }},
    "typography": {{
      "headings": "CSS font stack",
      "body": "CSS font stack",
      "title_massive": "tailwind classes",
      "body_default": "tailwind classes"
    }},
    "effects": []
  }}
}}"""

    def _normalize_compiled_runtime(self, compiled_runtime: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(json.dumps(DEFAULT_COMPILED_RUNTIME))
        # First, copy high-level fields except nests
        for k, v in compiled_runtime.items():
            if k not in {"tokens", "typography", "effects"}:
                normalized[k] = v
        
        # Merge tokens selectively - only if the LLM provided a hex color
        if "tokens" in compiled_runtime and isinstance(compiled_runtime["tokens"], dict):
            for k, v in compiled_runtime["tokens"].items():
                if v and isinstance(v, str) and (v.startswith("#") or v == "transparent" or v == "none"):
                    normalized["tokens"][k] = v
        
        # Merge typography selectively
        if "typography" in compiled_runtime and isinstance(compiled_runtime["typography"], dict):
            for k, v in compiled_runtime["typography"].items():
                if v and isinstance(v, str) and v != "string" and "CSS font stack" not in v:
                    normalized["typography"][k] = v
        
        # Handle effects list
        if "effects" in compiled_runtime and isinstance(compiled_runtime["effects"], (list, tuple)):
            normalized["effects"] = list(compiled_runtime["effects"])
            
        return normalized

    def _build_final_document(
        self,
        *,
        sources: list[dict[str, Any]],
        extracted: dict[str, Any],
        normalized: dict[str, Any],
        designer_handoff: dict[str, Any],
        compiled_runtime: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        compiled = self._normalize_compiled_runtime(compiled_runtime)
        design_readme = self._build_design_readme(
          extracted=extracted,
          normalized=normalized,
          designer_handoff=designer_handoff,
          compiled=compiled,
          warnings=warnings,
        )
        return {
            "schema_version": "brand-dna/v2",
            "meta": {
                "tenant_id": self.tenant_id,
                "source_count": len(sources),
                "generated_at": _utc_now_iso(),
                "extraction_mode": "auto",
            },
            "sources": sources,
            "evidence": {
                "raw_brand_dna": extracted,
                "warnings": warnings,
            },
            "design_readme": design_readme,
            "layers": {
                "extracted": extracted,
                "normalized": normalized,
                "designer_handoff": designer_handoff,
                "compiled": compiled,
            },
            "compiled": compiled,
            "theme": compiled["theme"],
            "version": compiled["version"],
            "description": compiled["description"],
            "tokens": compiled["tokens"],
            "typography": compiled["typography"],
            "effects": compiled["effects"],
        }

    def _build_design_readme(
        self,
        *,
        extracted: dict[str, Any],
        normalized: dict[str, Any],
        designer_handoff: dict[str, Any],
        compiled: dict[str, Any],
        warnings: list[str],
    ) -> str:
        def _list_or(items: list[str] | None, fallback: list[str]) -> list[str]:
            if items:
                cleaned = [str(i).strip() for i in items if str(i).strip()]
                if cleaned:
                    return cleaned
            return fallback

        def _value_or(value: Any, fallback: str) -> str:
            if value is None:
                return fallback
            text = str(value).strip()
            return text if text else fallback

        visual_system = normalized.get("visual_system", {}) if isinstance(normalized, dict) else {}
        composition = visual_system.get("composition", {}) if isinstance(visual_system, dict) else {}
        keywords = normalized.get("keywords", [])
        core_traits = normalized.get("core_traits", [])
        contextual_traits = normalized.get("contextual_traits", [])
        palette_rules = visual_system.get("palette", {}).get("rules", []) if isinstance(visual_system.get("palette", {}), dict) else []
        role_rules = visual_system.get("typography", {}).get("role_rules", []) if isinstance(visual_system.get("typography", {}), dict) else []
        motifs = composition.get("motifs", [])
        recipes = normalized.get("recipes", {})
        guardrails = normalized.get("guardrails", {})
        tokens = compiled.get("tokens", {})
        typo = compiled.get("typography", {})
        tone_axes = normalized.get("tone_axes", {})

        should_prefer = _list_or(guardrails.get("should_prefer", []), [
            "Prefer high-contrast typography and clear visual hierarchy.",
            "Prefer modular blocks with consistent spacing rhythm.",
        ])
        avoid = _list_or((designer_handoff.get("avoid", []) or guardrails.get("avoid", [])), [
            "Avoid decorative effects not supported by source artifacts.",
            "Avoid inconsistent component styles within the same view.",
        ])
        hero_recipe = _list_or(recipes.get("hero", []), [
            "Lead with one dominant value statement and supporting evidence.",
            "Keep CTA hierarchy explicit: one primary action, one secondary action.",
        ])
        landing_recipe = _list_or(recipes.get("landing_page", []), [
            "Break content into modular sections with clear section titles.",
            "Place proof/data modules above long explanatory copy.",
        ])
        social_recipe = _list_or(recipes.get("social", []), [
            "Use one key message, one supporting metric, and one concise CTA.",
            "Maintain high legibility and simplified composition on small canvases.",
        ])
        component_suggestions = _list_or(extracted.get("artifact_patterns", []), [
            "KPI cards with consistent metric typography and subtle separators.",
            "Navigation rail with predictable spacing and compact labels.",
            "Action buttons with clear primary/secondary contrast.",
            "Form controls with strong focus visibility and helper text hierarchy.",
        ])

        grid_hint = _value_or(composition.get("grid_style"), "modular grid")
        alignment_hint = _value_or(composition.get("alignment_bias"), "left-weighted alignment")
        density_hint = _value_or(composition.get("density"), "balanced density")
        negative_space_hint = _value_or(composition.get("negative_space_strategy"), "controlled negative space")
        focal_hint = _value_or(composition.get("focal_element_strategy"), "single focal anchor")

        palette_rows = [
            ("Primary", tokens.get("primary", "N/A"), "Main visual anchor"),
            ("Background", tokens.get("background", "N/A"), "Primary canvas"),
            ("Surface", tokens.get("surface", "N/A"), "Cards/panels"),
            ("Border", tokens.get("border", "N/A"), "Dividers/outlines"),
            ("Accent Blue", tokens.get("accent_blue", "N/A"), "Primary interaction accent"),
            ("Accent Emerald", tokens.get("accent_emerald", "N/A"), "Success/support accent"),
            ("Accent Purple", tokens.get("accent_purple", "N/A"), "Secondary accent"),
            ("Muted", tokens.get("muted", "N/A"), "Secondary text/meta"),
            ("Ink", tokens.get("ink", "N/A"), "Primary text"),
        ]

        sections = [
            f"# Design System Inspired by {compiled.get('theme', 'Custom Brand')}",
            "",
            compiled.get("description", "Auto-generated design system reference for visual generation."),
            "",
            "## 1. Visual Theme & Atmosphere",
            f"- Keywords: {', '.join(_list_or(keywords, ['structured', 'modern', 'high-clarity']))}",
            f"- Core identity traits: {'; '.join(_list_or(core_traits, ['clear hierarchy', 'consistent rhythm']))}",
            f"- Contextual traits: {'; '.join(_list_or(contextual_traits, ['modular interface language']))}",
            f"- Composition style: {grid_hint}, {alignment_hint}, {density_hint}",
            f"- Focal strategy: {focal_hint}",
            f"- Negative space strategy: {negative_space_hint}",
            "",
            "Tone axes:",
            f"- formal_informal: `{tone_axes.get('formal_informal', 'N/A')}`",
            f"- minimal_expressive: `{tone_axes.get('minimal_expressive', 'N/A')}`",
            f"- premium_accessible: `{tone_axes.get('premium_accessible', 'N/A')}`",
            f"- corporate_editorial: `{tone_axes.get('corporate_editorial', 'N/A')}`",
            f"- technical_human: `{tone_axes.get('technical_human', 'N/A')}`",
            f"- playful_serious: `{tone_axes.get('playful_serious', 'N/A')}`",
            "",
            "## 2. Color Palette & Roles",
            "| Role | Token | Purpose |",
            "|---|---|---|",
        ]
        sections.extend([f"| {role} | `{value}` | {purpose} |" for role, value, purpose in palette_rows])
        if palette_rules:
            sections.extend(["", "Palette usage rules:"])
            sections.extend(f"- {rule}" for rule in palette_rules)

        sections.extend([
            "",
            "## 3. Typography Rules",
            f"- Heading family: `{typo.get('headings', 'N/A')}`",
            f"- Body family: `{typo.get('body', 'N/A')}`",
            f"- Display style hint: `{typo.get('title_massive', 'N/A')}`",
            f"- Body style hint: `{typo.get('body_default', 'N/A')}`",
            "",
            "Recommended scale:",
            "| Role | Size | Weight | Line Height | Notes |",
            "|---|---|---|---|---|",
            "| Display | 56-64px | 600-700 | 1.0-1.1 | Hero statement |",
            "| H1 | 42-48px | 500-600 | 1.1-1.2 | Major section title |",
            "| H2 | 28-36px | 500-600 | 1.2-1.3 | Subsection title |",
            "| H3 | 20-24px | 500 | 1.3-1.4 | Module heading |",
            "| Body | 14-16px | 400 | 1.5-1.6 | Standard content |",
            "| Caption | 11-12px | 400-500 | 1.3-1.4 | Metadata/helper text |",
        ])
        if role_rules:
            sections.extend(["", "Typography usage rules:"])
            sections.extend(f"- {rule}" for rule in role_rules)

        sections.extend([
            "",
            "## 4. Component Stylings",
            "Predefined component fields:",
        ])
        sections.extend(f"- {item}" for item in component_suggestions)
        sections.extend([
            "",
            "## 5. Layout Principles",
            f"- Grid style: {grid_hint}",
            f"- Alignment bias: {alignment_hint}",
            f"- Density: {density_hint}",
            f"- Negative space strategy: {negative_space_hint}",
            f"- Motifs: {', '.join(_list_or(motifs, ['modular cards', 'clear section segmentation']))}",
            "- Baseline spacing suggestion: 8px modular scale with consistent vertical rhythm.",
            "",
            "## 6. Depth & Elevation",
            "- Prefer layered surfaces and subtle border contrast before heavy shadows.",
            "- Use stronger elevation only for overlays, dialogs, and floating menus.",
            "",
            "## 7. Do's and Don'ts",
            "Do:",
        ])
        sections.extend(f"- {item}" for item in should_prefer)
        sections.extend(["", "Don't:"])
        sections.extend(f"- {item}" for item in avoid)

        sections.extend([
            "",
            "## 8. Responsive Behavior",
            "- Mobile: collapse multi-column modules into one column while preserving hierarchy.",
            "- Tablet: two-column module grouping with consistent spacing.",
            "- Desktop: full modular composition with clear focal regions and data hierarchy.",
            "",
            "## 9. Agent Prompt Guide",
            "### Hero Recipe",
        ])
        sections.extend(f"- {item}" for item in hero_recipe)
        sections.extend(["", "### Landing Page Recipe"])
        sections.extend(f"- {item}" for item in landing_recipe)
        sections.extend(["", "### Social Recipe"])
        sections.extend(f"- {item}" for item in social_recipe)
        sections.extend([
            "",
            "## VLM Extraction Instructions",
            "- Prefer observable evidence over speculation.",
            "- Do not hallucinate exact font families when confidence is low.",
            "- Separate core brand rules from campaign-specific expression.",
            "- Extract composition, motif systems, hierarchy, and spacing logic, not just colors.",
            "- Return structured JSON for machine use and preserve confidence-aware fallbacks.",
        ])

        if warnings:
            sections.extend(["", "## Extraction Notes"])
            sections.extend(f"- {warning}" for warning in warnings)
        provenance = extracted.get("provenance", {}) if extracted else {}
        if provenance:
            sections.extend(["", "## Provenance"])
            sections.extend(f"- {item}" for item in provenance.get("source_pages_or_regions", []))
        return "\n".join(sections).strip() + "\n"

    async def run_extraction(self, job_id: str, upload_ids: list[str]) -> None:
        try:
            await self.repo.update_job(job_id, status="running", progress=10)

            uploads = []
            allowed_mimetypes = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
            for uid in upload_ids:
                upload = await self.upload_repo.get_by_upload_id(uid)
                if upload and upload.tenant_id == self.tenant_id:
                    if upload.content_type in allowed_mimetypes:
                        uploads.append(upload)
                    else:
                        logger.warning("Skipping file %s with unsupported type %s", upload.filename, upload.content_type)

            if not uploads:
                await self.repo.update_job(job_id, status="failed", error_message="No valid images or PDFs found for extraction")
                return

            if len(uploads) > MAX_VISUAL_UPLOADS:
                warnings = [
                    f"Received {len(uploads)} assets. Only the first {MAX_VISUAL_UPLOADS} were used for extraction speed and consistency."
                ]
                uploads = uploads[:MAX_VISUAL_UPLOADS]
            else:
                warnings = []

            await self.repo.update_job(job_id, progress=20)
            sources = [self._source_descriptor(upload) for upload in uploads]

            visual_messages = [{"role": "system", "content": self._build_visual_system_prompt()}]
            visual_content: list[dict[str, Any]] = [{
                "type": "text",
                "text": (
                    "Analyze these brand assets and extract layered Brand DNA.\n"
                    f"Asset summaries: {json.dumps([{k: v for k, v in source.items() if k != 'storage_path'} for source in sources], indent=2)}\n"
                    f"Warnings: {json.dumps(warnings)}"
                ),
            }]

            for upload in uploads:
                if upload.content_type and upload.content_type.startswith("image/"):
                    if Path(upload.storage_path).stat().st_size > MAX_VISUAL_IMAGE_BYTES:
                        warnings.append(
                            f"Image '{upload.filename}' exceeded {MAX_VISUAL_IMAGE_BYTES // (1024 * 1024)}MB and was skipped to keep extraction responsive."
                        )
                        continue
                    visual_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{upload.content_type};base64,{self._encode_image(upload.storage_path)}"},
                    })
                elif upload.content_type == "application/pdf":
                    try:
                        encoded_pages = self._encode_pdf_pages(upload.storage_path, max_pages=MAX_VISUAL_PDF_PAGES)
                        for encoded_page in encoded_pages:
                            visual_content.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded_page}"},
                            })
                        if len(encoded_pages) == MAX_VISUAL_PDF_PAGES:
                            warnings.append(
                                f"PDF '{upload.filename}' was truncated to the first {MAX_VISUAL_PDF_PAGES} pages for visual extraction."
                            )
                    except Exception as exc:
                        logger.warning("Failed to rasterize PDF %s for Brand DNA extraction: %s", upload.filename, exc)
                        warnings.append(
                            f"PDF '{upload.filename}' could not be rasterized for visual extraction and was analyzed from metadata only."
                        )

            visual_messages.append({"role": "user", "content": visual_content})

            api_key = settings.openai_api_key
            api_base = settings.openai_api_base_url
            if not api_key:
                raise ValueError("OPENAI_API_KEY is not set. Add it to your .env to use brand DNA extraction.")

            visual_response = await litellm.acompletion(
                model=MODEL_VISUAL,
                messages=visual_messages,
                max_tokens=1400,
                api_key=api_key,
                api_base=api_base,
            )

            raw_content = visual_response.choices[0].message.content or ""
            try:
                raw_brand_dna = json.loads(_strip_markdown_json(raw_content))
            except json.JSONDecodeError as e:
                logger.error("JSON parse failed on layer 1: %s", e)
                raise ValueError(f"Visual model returned malformed JSON: {str(e)}")

            preview_document = self._build_fast_preview_payload(
                sources=sources,
                extracted=raw_brand_dna,
                warnings=warnings,
            )

            await self.repo.update_job(
                job_id,
                intermediate_json=json.dumps(raw_brand_dna),
                result_json=json.dumps(preview_document),
                progress=55,
            )

            normalized_payload = preview_document.get("layers", {}).get("normalized", {})
            designer_handoff = preview_document.get("layers", {}).get("designer_handoff", {})
            compiled_runtime = preview_document.get("layers", {}).get("compiled", {})
            final_document = self._build_final_document(
                sources=sources,
                extracted=raw_brand_dna,
                normalized=normalized_payload,
                designer_handoff=designer_handoff,
                compiled_runtime=compiled_runtime,
                warnings=warnings,
            )

            await self.repo.update_job(job_id, status="succeeded", progress=100, result_json=json.dumps(final_document))

            dna_dir = Path(settings.artifact_dir) / "brand_dna"
            dna_dir.mkdir(parents=True, exist_ok=True)
            dna_path = dna_dir / f"{self.tenant_id}.json"
            dna_path.write_text(json.dumps(final_document, indent=2))

            design_md_path = dna_dir / f"{self.tenant_id}.DESIGN.md"
            design_md_path.write_text(final_document.get("design_readme", ""), encoding="utf-8")
            logger.info("Saved brand artifacts to %s", dna_dir)

            source_truth_dir = Path("/Users/amar/blaiq/AgentScope-BLAIQ/src/brand_dna")
            source_truth_dir.mkdir(parents=True, exist_ok=True)
            (source_truth_dir / f"{self.tenant_id}.json").write_text(json.dumps(final_document, indent=2), encoding="utf-8")
            (source_truth_dir / f"{self.tenant_id}.DESIGN.md").write_text(final_document.get("design_readme", ""), encoding="utf-8")
            logger.info("Updated file-based source of truth in %s", source_truth_dir)

        except Exception as exc:
            logger.exception("Extraction failed")
            await self.repo.update_job(job_id, status="failed", error_message=str(exc))
