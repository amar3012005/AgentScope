"""Section-by-section artifact generation pipeline for Vangogh V2.

Replaces the single-shot generate_design() with a loop that:
1. Extracts structured JSON per section via LLM (gpt-4o-mini)
2. Renders each section deterministically via Jinja2 templates
3. Emits progressive callbacks for SSE streaming
4. Composes the full artifact document at the end
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import ValidationError

from agents.content_creator.artifact_types.definitions import get_registry
from agents.content_creator.artifact_types.registry import (
    ArtifactKind,
    ArtifactTypeDefinition,
    SectionSpec,
)
from agents.content_creator.artifact_types.section_schemas import (
    SECTION_SCHEMA_MAP,
    get_json_schema_for_section,
    get_schema_for_section,
)
from agents.content_creator.prompts.section_extraction import (
    build_section_extraction_messages,
    summarize_prior_sections,
)
from agents.content_creator.template_engine import (
    VangoghTemplateEngine,
    build_chart_config,
)
from orchestrator.contracts.manifests import ArtifactManifest, SectionManifest

logger = logging.getLogger("blaiq-vangogh.section_generator")

EXTRACTION_MODEL: str = os.getenv("VANGOGH_EXTRACTION_MODEL", "nebius/Qwen/Qwen3-32B-fast")
TEMPLATES_DIR = Path(__file__).parent / "templates"


def _strip_code_fences(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    text = re.sub(r"^```(?:json|js|javascript)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_first_json_object(raw_text: str) -> str:
    text = _strip_code_fences(raw_text)
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return text[start:]


def _parse_structured_json(raw_text: str) -> Dict[str, Any]:
    candidate = _extract_first_json_object(raw_text)
    if not candidate:
        raise ValueError("empty JSON response")
    return json.loads(candidate)


def _resolve_extraction_client() -> AsyncOpenAI:
    """Build an async OpenAI client for section extraction."""
    model = EXTRACTION_MODEL
    if model.startswith("groq/"):
        api_key = os.getenv("GROQ_API_KEY", "")
        base_url = os.getenv("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")
    else:
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
    return AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=1)


def _normalize_model_name(model: str) -> str:
    """Strip provider prefix so the SDK receives a bare model id."""
    for prefix in ("openai/", "groq/"):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


async def extract_section_data(
    section_spec: SectionSpec,
    raw_context: str,
    user_request: str,
    user_answers: Dict[str, str] | None = None,
    prior_sections: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Extract structured JSON data for a single section via LLM.

    Uses gpt-4o-mini with response_format=json_object for fast,
    reliable structured extraction.
    """
    prior_summary = summarize_prior_sections(prior_sections or [])
    messages = build_section_extraction_messages(
        section_spec=section_spec,
        raw_context=raw_context,
        user_request=user_request,
        user_answers=user_answers,
        prior_sections_summary=prior_summary,
    )

    client = _resolve_extraction_client()
    model_name = _normalize_model_name(EXTRACTION_MODEL)

    ts = time.time()
    raw = ""
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content or "{}"
        data = _parse_structured_json(raw)

        # Validate against Pydantic schema if available
        schema_cls = get_schema_for_section(section_spec.schema_class)
        if schema_cls:
            try:
                validated = schema_cls.model_validate(data)
                data = validated.model_dump()
            except ValidationError as ve:
                logger.warning(
                    "section_schema_validation_warning section=%s errors=%s",
                    section_spec.section_id,
                    str(ve),
                )
                # Use raw data as fallback — templates are tolerant of missing fields

        logger.info(
            "section_extracted section=%s model=%s latency_ms=%d",
            section_spec.section_id,
            model_name,
            int((time.time() - ts) * 1000),
        )
        return data

    except Exception as exc:
        logger.warning(
            "section_extraction_retry section=%s error=%s",
            section_spec.section_id,
            str(exc),
        )
        try:
            retry_messages = list(messages)
            retry_messages[0] = {
                "role": "system",
                "content": (
                    f"{retry_messages[0]['content']}\n\n"
                    "Your previous response was invalid or incomplete.\n"
                    "Return ONLY the JSON object. No markdown, no code fences, no commentary."
                ),
            }
            retry_response = await client.chat.completions.create(
                model=model_name,
                messages=retry_messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2000,
            )
            raw = retry_response.choices[0].message.content or "{}"
            data = _parse_structured_json(raw)
            schema_cls = get_schema_for_section(section_spec.schema_class)
            if schema_cls:
                try:
                    validated = schema_cls.model_validate(data)
                    data = validated.model_dump()
                except ValidationError as ve:
                    logger.warning(
                        "section_schema_validation_warning section=%s errors=%s",
                        section_spec.section_id,
                        str(ve),
                    )
            logger.info(
                "section_extracted_retry section=%s model=%s latency_ms=%d",
                section_spec.section_id,
                model_name,
                int((time.time() - ts) * 1000),
            )
            return data
        except Exception as retry_exc:
            logger.error(
                "section_extraction_error section=%s error=%s retry_error=%s raw=%s",
                section_spec.section_id,
                str(exc),
                str(retry_exc),
                raw[:400],
            )
        # Return minimal fallback data so the pipeline doesn't stall
        logger.error(
            "section_extraction_error section=%s error=%s",
            section_spec.section_id,
            str(exc),
        )
        return _fallback_section_data(section_spec)


def _fallback_section_data(section_spec: SectionSpec) -> Dict[str, Any]:
    """Produce minimal valid data for a section when extraction fails."""
    fallbacks: Dict[str, Dict[str, Any]] = {
        "HeroSectionData": {"headline": "[Content extraction pending]", "subheadline": "", "background_effect": "spotlight"},
        "StatSectionData": {"title": "", "stats": []},
        "ChartSectionData": {"chart_type": "bar", "title": "", "labels": [], "datasets": []},
        "InsightSectionData": {"title": "", "insights": []},
        "TimelineSectionData": {"title": "", "phases": []},
        "PersonaSectionData": {"title": "", "personas": []},
        "FlowchartSectionData": {"mermaid_definition": "graph LR; A[Start] --> B[End]", "title": ""},
        "ContentBlockData": {"headline": "[Content extraction pending]", "body": "", "bullets": []},
        "TeamSectionData": {"title": "Team", "members": []},
        "CtaSectionData": {"headline": "[Call to Action]", "body": "", "stats": []},
    }
    return fallbacks.get(section_spec.schema_class, {"headline": "[Pending]"})


def _prepare_section_data_for_template(
    section_spec: SectionSpec,
    data: Dict[str, Any],
    brand_dna: Dict[str, Any],
) -> Dict[str, Any]:
    """Post-process extracted data before template rendering.

    For chart sections, builds the Chart.js config from the raw data.
    """
    if section_spec.schema_class == "ChartSectionData" and data.get("labels"):
        datasets = data.get("datasets", [])
        if isinstance(datasets, list):
            ds_dicts = []
            for ds in datasets:
                if isinstance(ds, dict):
                    ds_dicts.append(ds)
            chart_config = build_chart_config(
                chart_type=data.get("chart_type", "bar"),
                title=data.get("title", ""),
                labels=data.get("labels", []),
                datasets=ds_dicts,
                brand_dna=brand_dna,
            )
            data["chart_config"] = chart_config

    return data


# Type alias for the section-ready callback
SectionReadyCallback = Callable[
    [int, str, str, str, Dict[str, Any]],  # index, section_id, label, html_fragment, section_data
    Awaitable[None],
]


async def generate_artifact_sections(
    artifact_type: ArtifactTypeDefinition,
    raw_context: str,
    user_request: str,
    user_answers: Dict[str, str] | None = None,
    brand_dna: Dict[str, Any] | None = None,
    on_section_ready: SectionReadyCallback | None = None,
) -> ArtifactManifest:
    """Generate all sections for an artifact type.

    For each section:
    1. Extract structured data via LLM
    2. Post-process (e.g., build chart configs)
    3. Render HTML fragment via Jinja2 template
    4. Emit on_section_ready callback for SSE streaming
    5. Append to manifest

    Returns the complete ArtifactManifest with all sections and composed HTML.
    """
    engine = VangoghTemplateEngine(TEMPLATES_DIR, brand_dna or {})
    sections_manifest: List[SectionManifest] = []
    sections_data_for_continuity: List[Dict[str, Any]] = []

    mission_id = str(uuid4())
    ts_start = time.time()

    logger.info(
        "artifact_generation_start kind=%s sections=%d mission_id=%s",
        artifact_type.kind.value,
        len(artifact_type.sections),
        mission_id,
    )

    for idx, section_spec in enumerate(artifact_type.sections):
        section_ts = time.time()

        # 1. Extract structured data via LLM
        section_data = await extract_section_data(
            section_spec=section_spec,
            raw_context=raw_context,
            user_request=user_request,
            user_answers=user_answers,
            prior_sections=sections_data_for_continuity,
        )

        # 2. Post-process (chart configs, etc.)
        section_data = _prepare_section_data_for_template(
            section_spec, section_data, brand_dna or {}
        )

        # 3. Render HTML fragment
        try:
            html_fragment = engine.render_section(
                section_spec.template_name, section_data
            )
        except Exception as render_exc:
            logger.error(
                "section_render_error section=%s error=%s",
                section_spec.section_id,
                str(render_exc),
            )
            html_fragment = (
                f'<div class="p-8 text-stone-400">'
                f'Section "{section_spec.label}" render error: {render_exc}'
                f'</div>'
            )

        # 4. Build manifest entry
        manifest_entry = SectionManifest(
            section_id=section_spec.section_id,
            template_name=section_spec.template_name,
            data=section_data,
            html_fragment=html_fragment,
            order=idx,
        )
        sections_manifest.append(manifest_entry)
        sections_data_for_continuity.append({
            "section_id": section_spec.section_id,
            "data": section_data,
        })

        logger.info(
            "section_complete section=%s index=%d/%d latency_ms=%d html_len=%d",
            section_spec.section_id,
            idx + 1,
            len(artifact_type.sections),
            int((time.time() - section_ts) * 1000),
            len(html_fragment),
        )

        # 5. Emit callback for progressive SSE streaming
        if on_section_ready:
            await on_section_ready(
                idx,
                section_spec.section_id,
                section_spec.label,
                html_fragment,
                section_data,
            )

    # 6. Compose full document
    sections_for_composition = [
        {"section_id": s.section_id, "html_fragment": s.html_fragment}
        for s in sections_manifest
    ]
    full_html_body = engine.render_artifact(
        artifact_type.kind.value,
        sections_for_composition,
        {"title": user_request[:120]},
    )

    # Wrap in base document shell
    base_shell = engine.render_base_shell({"title": user_request[:80]})
    full_html = base_shell.replace(
        '<div id="vangogh-root">\n    \n  </div>',
        f'<div id="vangogh-root">\n{full_html_body}\n  </div>',
    )
    # Fallback if the exact replacement string doesn't match
    if "vangogh-root" in full_html and full_html_body not in full_html:
        full_html = base_shell.replace("</div>\n  <script>", f"{full_html_body}\n  </div>\n  <script>", 1)

    total_ms = int((time.time() - ts_start) * 1000)
    logger.info(
        "artifact_generation_complete kind=%s sections=%d total_ms=%d html_len=%d mission_id=%s",
        artifact_type.kind.value,
        len(sections_manifest),
        total_ms,
        len(full_html),
        mission_id,
    )

    return ArtifactManifest(
        kind=artifact_type.kind.value,
        mission_id=mission_id,
        title=user_request[:120],
        sections=sections_manifest,
        full_html=full_html,
        metadata={
            "total_sections": len(sections_manifest),
            "generation_ms": total_ms,
            "extraction_model": EXTRACTION_MODEL,
        },
    )
