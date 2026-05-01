# -*- coding: utf-8 -*-
"""
ContentDirector V2 — Visual orchestration pipeline.

Phase 0 — Skill Selector:
    Direct model call selects one task skill (e.g. visual_pitch_deck)
    from skills/content_director/* based on request intent.

Phase 1 — Abstract Generator:
    Direct authoring model combines the selected skill template,
    brand tone, and evidence pack into a structured markdown abstract
    with section_id, title, content_plan, and recall_query.

Section Recall Loop:
    For each section, fires hivemind_recall(section.recall_query) directly.
    Enriches each section with targeted evidence snippets.

Phase 2 — Detailed Storyboard:
    Direct authoring model combines the phase 1 abstract, brand DNA,
    selected skill template, and enriched evidence into the final
    markdown render contract consumed by VanGogh and the frontend.

Poster Feature Path:
    Poster-like artifacts skip the generic Phase 2 section expansion.
    Instead, a dedicated poster brief agent combines the selected template
    skill, brand tone, brand DNA, evidence pack, and phase 1 abstract into a
    single-canvas final phase 2 contract with an exact image-generation block.
"""
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from agentscope.message import Msg, TextBlock
from agentscope.tool import ToolResponse
from pydantic import BaseModel, Field

try:
    from agentscope_runtime.engine.app import AgentApp
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
    from agentscope_runtime.engine.deployers.adapter.a2a import AgentCardWithRuntimeConfig
except ImportError:
    from fastapi import FastAPI
    from pydantic import BaseModel
    class AgentRequest(BaseModel):
        input: list
        session_id: str
        user_id: str
    class AgentCardWithRuntimeConfig(BaseModel):
        host: str = "0.0.0.0"
    class AgentApp(FastAPI):
        def __init__(self, *_, app_name=None, app_description=None, a2a_config=None, **kwargs):
            super().__init__(title=app_name, description=app_description, **kwargs)
        def query(self, *args, **kwargs):
            return lambda fn: fn

    # Create a module-level app instance for decorators to use
    _fallback_app = AgentApp(app_name="agentscope", app_description="AgentScope Runtime")
    app = _fallback_app

from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.agent_base import BaseAgent
from agentscope_blaiq.tools.enterprise_fleet import BlaiqEnterpriseFleet, active_session_id

logger = logging.getLogger("content-director-v2")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)
logger.propagate = False

# ─── Skill discovery ──────────────────────────────────────────────────────────

_TASK_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills" / "content_director"
_GLOBAL_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"
_CONTENT_DIRECTOR_AUTHORING_MODEL = "groq/openai/gpt-oss-120b"


class Phase1Section(BaseModel):
    section_id: str
    title: str
    content_plan: str = ""
    recall_query: str = ""


class Phase2Section(BaseModel):
    section_id: str
    title: str
    synthesis: str = ""
    brand_tone_signals: str = ""
    visual_spec: str = ""
    image_prompt_notes: str = ""


class VisualRenderPlan(BaseModel):
    contract: str = "visual_render_plan_v1"
    artifact_type: str
    selected_skill: str
    title: str
    render_mode: str
    storyboard_markdown: str
    content_abstract_markdown: str = ""
    sections: list[Phase2Section] = Field(default_factory=list)
    image_prompt: str | None = None
    poster_feature_markdown: str | None = None
    prompt_strategy: str | None = None


def _parse_frontmatter(skill_md: Path) -> dict[str, str]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip().lower()] = v.strip().strip('"').strip("'")
    return fm


def _build_task_skill_catalog() -> dict[str, dict]:
    """Discover content_director-specific task skills recursively from skills/content_director/."""
    catalog: dict[str, dict] = {}
    if not _TASK_SKILLS_ROOT.exists():
        logger.warning("[CONTENTDIR] Task skills dir missing: %s", _TASK_SKILLS_ROOT)
        return catalog
        
    # Recursive discovery using rglob for SKILL.md
    for skill_md in sorted(_TASK_SKILLS_ROOT.rglob("SKILL.md"), key=lambda p: p.parent.name.lower()):
        child = skill_md.parent
        fm = _parse_frontmatter(skill_md)
        skill_key = child.name.strip()
        skill_name = (fm.get("name") or skill_key).strip()
        if len(skill_key) < 2 or len(skill_name) < 2:
            logger.warning("[CONTENTDIR] Skipping malformed task skill: dir=%s name=%s", child, skill_name or skill_key)
            continue
        catalog[child.name] = {
            "name": skill_name,
            "description": fm.get("description", ""),
            "dir": str(child),
            "path": str(skill_md),
        }
    return catalog


def _select_skill_without_model(
    task_catalog: dict[str, dict],
    request_text: str,
    artifact_type: str,
) -> str:
    """Deterministic fallback when the selector response is unusable.

    Prefer explicit request intent first, then artifact_type hint, then the
    highest-scoring registered skill based on its own name/description.
    """
    if not task_catalog:
        return ""

    normalized_request = (request_text or "").lower()
    normalized_hint = (artifact_type or "").lower()

    alias_map = {
        "visual_poster": ["poster", "flyer", "one pager poster", "campaign poster"],
        "visual_pitch_deck": ["pitch deck", "deck", "slides", "presentation", "keynote"],
        "viral_video_script": ["video", "trailer", "reel", "short", "viral video", "video script"],
        "cinematic_product_shots": ["product shots", "cinematic", "hero shot", "product shoot", "shot list"],
    }

    def score_candidate(candidate_key: str, candidate_meta: dict, source_text: str, source_weight: int) -> int:
        haystack = " ".join([
            candidate_key.lower(),
            str(candidate_meta.get("name", "")).lower(),
            str(candidate_meta.get("description", "")).lower(),
        ])
        score = 0
        for alias in alias_map.get(candidate_key, []):
            if alias in source_text:
                score += source_weight + len(alias)
        for token in set(re.findall(r"[a-z0-9_]+", haystack)):
            if len(token) > 3 and token in source_text:
                score += max(source_weight - 2, 1)
        return score

    best_key = ""
    best_score = -1
    for key, meta in task_catalog.items():
        score = score_candidate(key, meta, normalized_request, 10) + score_candidate(key, meta, normalized_hint, 6)
        if score > best_score:
            best_score = score
            best_key = key

    if best_key and best_score > 0:
        return best_key

    if best_key:
        return best_key

    ordered_catalog = sorted(
        task_catalog.items(),
        key=lambda item: (
            len(str(item[1].get("description", "")).strip()),
            item[0].lower(),
        ),
        reverse=True,
    )
    return ordered_catalog[0][0] if ordered_catalog else ""


def _extract_json(text: str) -> dict | None:
    clean = text.strip()
    # Strip code fences (opening and closing)
    clean = re.sub(r"^```[a-z]*\s*\n?", "", clean)
    clean = re.sub(r"\n?```\s*$", "", clean).strip()
    # Direct parse
    try:
        return json.loads(clean)
    except Exception:
        pass
    # Find the outermost JSON object via brace depth scan
    start = clean.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(clean[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(clean[start : i + 1])
                    except Exception:
                        break
    return None


def _extract_phase1_abstract(text: str, default_skill: str) -> dict | None:
    """Parse Phase 1 README markdown into structured sections.

    Expected format is markdown-first, but JSON remains supported as a
    compatibility fallback while prompts transition.
    """
    parsed_json = _extract_json(text)
    if parsed_json and "sections" in parsed_json:
        return parsed_json

    clean = text.strip()
    clean = re.sub(r"^```[a-z]*\s*\n?", "", clean)
    clean = re.sub(r"\n?```\s*$", "", clean).strip()
    if not clean:
        return None

    skill = default_skill
    skill_match = re.search(r"^Skill:\s*(.+)$", clean, re.MULTILINE)
    if skill_match:
        skill = skill_match.group(1).strip()

    section_blocks = re.split(r"^##\s+", clean, flags=re.MULTILINE)
    sections: list[dict] = []

    for block in section_blocks[1:]:
        lines = [line.rstrip() for line in block.splitlines()]
        if not lines:
            continue

        header = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        section_id = ""
        title = header

        if "|" in header:
            left, right = header.split("|", 1)
            section_id = left.strip()
            title = right.strip()

        content_plan_match = re.search(
            r"(?:###\s+Content Plan|Content Plan:)\s*\n?(.*?)(?=\n(?:###\s+Recall Query|Recall Query:)|$)",
            body,
            re.DOTALL,
        )
        recall_query_match = re.search(
            r"(?:###\s+Recall Query|Recall Query:)\s*\n?(.*)$",
            body,
            re.DOTALL,
        )

        content_plan = content_plan_match.group(1).strip() if content_plan_match else ""
        recall_query = recall_query_match.group(1).strip() if recall_query_match else ""

        if not section_id:
            section_id = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")

        if title:
            sections.append(
                {
                    "section_id": section_id,
                    "title": title,
                    "content_plan": content_plan,
                    "recall_query": recall_query,
                },
            )

    if not sections:
        return None

    return {"skill": skill or default_skill, "sections": sections}


def _coerce_phase1_sections(sections: list[dict]) -> list[Phase1Section]:
    normalized: list[Phase1Section] = []
    for index, section in enumerate(sections, start=1):
        section_id = str(section.get("section_id") or f"section_{index}").strip()
        title = str(section.get("title") or section_id).strip()
        normalized.append(
            Phase1Section(
                section_id=section_id,
                title=title,
                content_plan=str(section.get("content_plan") or "").strip(),
                recall_query=str(section.get("recall_query") or "").strip(),
            )
        )
    return normalized


def _coerce_phase2_sections(sections: list[dict]) -> list[Phase2Section]:
    normalized: list[Phase2Section] = []
    for index, section in enumerate(sections, start=1):
        section_id = str(section.get("section_id") or f"section_{index}").strip()
        title = str(section.get("title") or section_id).strip()
        normalized.append(
            Phase2Section(
                section_id=section_id,
                title=title,
                synthesis=str(section.get("synthesis") or "").strip(),
                brand_tone_signals=str(section.get("brand_tone_signals") or "").strip(),
                visual_spec=str(section.get("visual_spec") or "").strip(),
                image_prompt_notes=str(section.get("image_prompt_notes") or "").strip(),
            )
        )
    return normalized


def _select_render_mode(artifact_type: str, selected_skill_key: str) -> str:
    normalized_type = (artifact_type or "").strip().lower()
    normalized_skill = (selected_skill_key or "").strip().lower()
    if normalized_type in {"video", "motion", "trailer", "reel", "video_trailer", "video_campaign"}:
        return "generate_video"
    if any(token in normalized_skill for token in ("video", "motion", "trailer", "reel", "film")):
        return "generate_video"
    return "generate_image"


def _is_poster_feature_path(artifact_type: str, selected_skill_key: str) -> bool:
    normalized_type = (artifact_type or "").strip().lower()
    normalized_skill = (selected_skill_key or "").strip().lower()
    return normalized_type == "poster" or "poster" in normalized_skill


def _normalize_visual_artifact_type(artifact_type: str, request_text: str, selected_skill_key: str) -> str:
    normalized_type = (artifact_type or "").strip().lower()
    normalized_request = (request_text or "").strip().lower()
    normalized_skill = (selected_skill_key or "").strip().lower()

    if normalized_type in {"poster", "brochure", "banner", "one_pager", "social_visual", "ad_creative"}:
        return normalized_type
    if "poster" in normalized_request or "poster" in normalized_skill:
        return "poster"
    if "brochure" in normalized_request:
        return "brochure"
    if "banner" in normalized_request:
        return "banner"
    if "one-pager" in normalized_request or "one pager" in normalized_request or "one_pager" in normalized_request:
        return "one_pager"
    return normalized_type or "general"


def _read_skill_markdown_text(task_catalog: dict[str, dict], selected_skill_key: str) -> str:
    skill_meta = task_catalog.get(selected_skill_key) or {}
    skill_path = skill_meta.get("path")
    if not skill_path:
        return ""
    try:
        return Path(str(skill_path)).read_text(encoding="utf-8").strip()
    except Exception as exc:
        logger.warning("[CONTENTDIR POSTER] Failed to read skill markdown for %s: %s", selected_skill_key, exc)
        return ""


def _read_global_skill_markdown(skill_key: str) -> str:
    skill_path = _GLOBAL_SKILLS_ROOT / skill_key / "SKILL.md"
    try:
        return skill_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _build_content_director_authoring_model(
    resolver: LiteLLMModelResolver,
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
):
    resolved = resolver.resolve_model_name(
        _CONTENT_DIRECTOR_AUTHORING_MODEL,
        role="content_director",
        temperature=temperature,
        max_output_tokens=max_output_tokens or settings.content_director_max_output_tokens,
    )
    return resolver.build_agentscope_model_from_resolved(resolved)


def _strip_skill_frontmatter(text: str) -> str:
    raw = str(text or "")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return raw.strip()


def _parse_skill_blueprint_sections(skill_markdown: str) -> list[dict[str, str]]:
    clean = _strip_skill_frontmatter(skill_markdown)
    if not clean:
        return []

    lines = clean.splitlines()
    sections: list[dict[str, str]] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        title = current_title.strip()
        if not title:
            current_lines = []
            return
        section_id = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or f"section_{len(sections) + 1}"
        body = "\n".join(line.rstrip() for line in current_lines).strip()
        sections.append({"section_id": section_id, "title": title, "blueprint": body})
        current_title = ""
        current_lines = []

    for line in lines:
        zone_match = re.match(r"^###\s+Zone\s+\d+:\s*(.+?)(?:\s+\(.*)?\s*$", line.strip())
        if zone_match:
            flush()
            current_title = zone_match.group(1).strip()
            continue
        if current_title:
            if re.match(r"^###\s+", line.strip()) or re.match(r"^##\s+(?!ARTIFACT TYPE|PHASE 1 ABSTRACT|PHASE 2 SYNTHESIS)", line.strip()):
                flush()
                continue
            current_lines.append(line)

    flush()

    if sections:
        return sections

    generic_sections: list[dict[str, str]] = []
    chunks = re.split(r"^##\s+", clean, flags=re.MULTILINE)
    for chunk in chunks[1:]:
        rows = [row.rstrip() for row in chunk.splitlines()]
        if not rows:
            continue
        title = rows[0].strip()
        if not title or title.lower() in {"canvas specification", "typography rules (phase 2 mandatory)", "color palette (phase 2 mandatory)", "micro-interactions (phase 2 suggestions for digital version)"}:
            continue
        section_id = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or f"section_{len(generic_sections) + 1}"
        generic_sections.append(
            {"section_id": section_id, "title": title, "blueprint": "\n".join(rows[1:]).strip()}
        )
    return generic_sections


def _build_fallback_phase1_sections(
    *,
    request_text: str,
    artifact_type: str,
    selected_skill_key: str,
    skill_markdown: str,
) -> list[Phase1Section]:
    blueprint_sections = _parse_skill_blueprint_sections(skill_markdown)
    if not blueprint_sections:
        return []

    normalized_request = request_text.strip() or f"{artifact_type or 'visual'} artifact"
    fallback_sections: list[Phase1Section] = []
    for index, section in enumerate(blueprint_sections, start=1):
        title = str(section.get("title") or f"Section {index}").strip()
        blueprint = str(section.get("blueprint") or "").strip()
        section_id = str(section.get("section_id") or f"section_{index}").strip()
        blueprint_lines = [
            line.strip()
            for line in blueprint.splitlines()
            if line.strip().startswith("-")
        ][:5]
        template_constraints = "\n".join(blueprint_lines)
        content_plan_parts = [
            f"**Purpose**",
            f"Translate the request into the **{title}** portion of the `{selected_skill_key or artifact_type or 'visual'}` artifact.",
            "",
            f"**Content Focus**",
            f"- Keep this section tightly aligned with the user request: **{normalized_request}**.",
            f"- Use organization-specific messaging and evidence-backed claims only.",
            f"- Preserve brand tone and keep copy concise, structured, and artifact-ready.",
        ]
        if template_constraints:
            content_plan_parts.extend(
                [
                    "",
                    f"**Template Constraints**",
                    template_constraints,
                ]
            )
        recall_query = (
            f"{normalized_request} {title} section facts, proof points, constraints, product specifics, brand messaging"
        ).strip()
        fallback_sections.append(
            Phase1Section(
                section_id=section_id,
                title=title,
                content_plan="\n".join(content_plan_parts).strip(),
                recall_query=recall_query,
            )
        )
    return fallback_sections


def _is_invalid_phase1_reply(text: str) -> bool:
    clean = str(text or "").strip().lower()
    if not clean:
        return True
    if "could you share" in clean or "i need to know" in clean or "i'm ready to draft" in clean:
        return True
    if "## " not in clean and "### content plan" not in clean:
        return True
    return False


def _extract_response_text(response: object) -> str:
    if response is None:
        return ""
    if isinstance(response, dict):
        value = response.get("text") or response.get("content") or ""
    else:
        value = getattr(response, "text", None) or getattr(response, "content", "")
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _extract_markdown_block(text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text.strip(), re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _merge_stream_text(previous: str, piece: str) -> str:
    prev = str(previous or "")
    current = str(piece or "")
    if not current:
        return prev
    if not prev:
        return current
    if current == prev:
        return prev
    if current.startswith(prev):
        return current
    if prev.endswith(current):
        return prev
    overlap_max = min(len(prev), len(current))
    for overlap in range(overlap_max, 0, -1):
        if prev.endswith(current[:overlap]):
            return prev + current[overlap:]
    return prev + current


def _parse_poster_feature_brief(text: str) -> dict[str, str]:
    clean = text.strip()
    clean = re.sub(r"^```[a-z]*\s*\n?", "", clean)
    clean = re.sub(r"\n?```\s*$", "", clean).strip()
    return {
        "creative_brief": clean,
        "concept": _extract_markdown_block(clean, "Poster Objective") or _extract_markdown_block(clean, "Poster Concept"),
        "evidence_pack": _extract_markdown_block(clean, "Research Evidence Distillate") or _extract_markdown_block(clean, "Evidence Pack"),
        "brand_tone": _extract_markdown_block(clean, "Brand Tone Directives"),
        "brand_dna": _extract_markdown_block(clean, "Brand DNA Directives") or _extract_markdown_block(clean, "Brand DNA Translation"),
        "template_system": _extract_markdown_block(clean, "Template Enforcement") or _extract_markdown_block(clean, "Template System"),
        "image_prompt": _extract_markdown_block(clean, "Final Image Generation Instructions") or _extract_markdown_block(clean, "Image Generation Prompt"),
        "negative_prompt": _extract_markdown_block(clean, "Negative Prompt"),
    }


def _build_poster_sections_from_brief(brief: dict[str, str]) -> list[dict[str, str]]:
    exact_prompt = brief.get("image_prompt", "").strip()
    negative_prompt = brief.get("negative_prompt", "").strip()
    prompt_notes_parts: list[str] = []
    if exact_prompt:
        prompt_notes_parts.extend(
            [
                "**Exact VanGogh Image Prompt**",
                "",
                exact_prompt,
            ]
        )
    if negative_prompt:
        prompt_notes_parts.extend(
            [
                "",
                "**Negative Prompt**",
                "",
                negative_prompt,
            ]
        )
    return [
        {
            "section_id": "poster_canvas",
            "title": "Poster Canvas",
            "synthesis": "\n\n".join(
                part for part in [brief.get("concept", "").strip(), brief.get("evidence_pack", "").strip()] if part
            ).strip(),
            "brand_tone_signals": brief.get("brand_tone", "").strip(),
            "visual_spec": "\n\n".join(
                part for part in [brief.get("brand_dna", "").strip(), brief.get("template_system", "").strip()] if part
            ).strip(),
            "image_prompt_notes": "\n".join(prompt_notes_parts).strip(),
        },
    ]


def _build_phase1_contract_markdown(
    skill_key: str,
    artifact_type: str,
    request_text: str,
    secs: list[Phase1Section],
) -> str:
    skill_label = skill_key.replace("_", " ").title() if skill_key else "General"
    request_cell = request_text.strip().replace("|", "\\|") or "n/a"
    lines = [
        f"# Content Abstract — {skill_label}",
        "",
        "> [!NOTE] Stable phase 1 contract for downstream enrichment and rendering.",
        "",
        "## Planning Context",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Selected Skill | {skill_key or 'unknown'} |",
        f"| Artifact Type | {artifact_type or 'general'} |",
        f"| Request | {request_cell} |",
        f"| Section Count | {len(secs)} |",
        "",
    ]
    for index, section in enumerate(secs, start=1):
        section_id = section.section_id
        title = section.title
        content_plan = section.content_plan
        recall_query = section.recall_query
        lines.extend(
            [
                f"## {section_id} | {title}",
                "",
                f"**Sequence:** {index}",
                "",
                "### Content Plan",
                "",
                content_plan or "_No content plan provided._",
                "",
                "### Recall Query",
                "",
                recall_query or "_No recall query required._",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _extract_markdown_section(text: str, heading: str) -> str:
    match = re.search(
        rf"###\s+{re.escape(heading)}\s*\n(.*?)(?=\n###\s+|\Z)",
        text.strip(),
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _build_phase2_contract_markdown(
    skill_key: str,
    artifact_type: str,
    request_text: str,
    secs: list[Phase2Section],
) -> str:
    skill_label = skill_key.replace("_", " ").title() if skill_key else "General"
    request_cell = request_text.strip().replace("|", "\\|") or "n/a"
    lines = [
        f"# Visual Render Plan — {skill_label}",
        "",
        "> [!NOTE] Stable phase 2 storyboard contract for VanGogh and frontend preview.",
        "",
        "## Render Context",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Selected Skill | {skill_key or 'unknown'} |",
        f"| Artifact Type | {artifact_type or 'general'} |",
        f"| Request | {request_cell} |",
        f"| Section Count | {len(secs)} |",
        "",
    ]
    for index, section in enumerate(secs, start=1):
        section_id = section.section_id
        title = section.title
        synthesis = section.synthesis
        tone = section.brand_tone_signals
        visual_spec = section.visual_spec
        image_notes = section.image_prompt_notes
        lines.extend(
            [
                f"## {section_id} | {title}",
                "",
                f"**Sequence:** {index}",
                "",
                "### Synthesis",
                "",
                synthesis or "_No synthesis provided._",
                "",
                "### Brand Tone Signals",
                "",
                tone or "_No brand tone signals provided._",
                "",
                "### Visual Spec",
                "",
                visual_spec or "_No visual spec provided._",
                "",
                "### Image Prompt Notes",
                "",
                image_notes or "_No image prompt notes provided._",
                "",
            ]
        )
    return "\n".join(lines).strip()


async def _generate_poster_feature_brief(
    owner: "ContentDirector",
    *,
    request_text: str,
    artifact_type: str,
    selected_skill_key: str,
    task_catalog: dict[str, dict],
    phase1_markdown: str,
    evidence_brief: str,
    optimized_research_evidence: str,
    optimized_recall_query: str,
) -> dict[str, str]:
    skill_markdown = _read_skill_markdown_text(task_catalog, selected_skill_key)
    brand_tone_markdown = _read_global_skill_markdown("brand_tone")
    brand_dna_markdown = _read_global_skill_markdown("brand_dna")
    poster_model = _build_content_director_authoring_model(owner.resolver, temperature=0.2)
    poster_sys_prompt = f"""You are ContentDirector Poster Feature - a dedicated poster orchestration system.

This is a feature-specific pipeline for single-canvas visual posters.
You are not writing a generic storyboard and you are not expanding multi-section phase 2 cards.
Your job is to create the definitive instruction packet for an image generation tool.

ACTIVE INPUTS
- The selected poster template skill defines the poster canvas, zones, typography, spacing, and composition rules.
- The brand_tone skill defines voice, emotional stance, phrase discipline, and how the organization should sound.
- The brand_dna skill defines colors, typography, composition values, and aesthetic translation rules.
- The evidence pack is the factual source of truth.
- The phase 1 abstract is the approved message hierarchy and content plan.

CORE OBJECTIVE
Produce a concise but complete poster-specific instruction packet for image generation.
This is a single-canvas artifact. The result must be clean, specific, high-signal, and ready for VanGogh to pass directly into image generation without rewriting.

MANDATORY RULES
- This is for artifact_type={artifact_type}. Treat it as a single poster canvas, not a slide deck and not a scrollable page.
- Keep the outcome poster-oriented and concise. Include all critical constraints, but do not flood the result with raw research dumps, repeated facts, or decorative filler.
- Use the phase 1 abstract as the message hierarchy and narrative spine.
- Use the optimized research evidence as the factual source of truth. Distill it. Do not paste it verbatim.
- Use only evidence-backed claims, entities, and product specifics. Do not invent facts.
- Translate brand DNA into concrete visual instructions: composition, palette, lighting, texture, materials, typography feel, hierarchy, CTA treatment, and exclusions.
- Translate brand tone into copy discipline and emotional direction.
- Preserve and operationalize the selected template skill, not just mention it.
- Write the final image prompt as the exact instruction payload VanGogh should pass to image generation.
- The final image prompt must be context-rich, internally consistent, concise enough to stay usable, and strict about brand DNA, brand tone, and template hierarchy.

OUTPUT FORMAT
Return ONLY markdown with exactly these top-level sections in this order:

## Poster Objective
<single-canvas concept, audience, objective, and poster thesis>

## Research Evidence Distillate
<bulleted distilled facts, differentiators, product claims, and constraints that matter for the poster. No raw logs. No JSON.>

## Brand Tone Directives
<bulleted tone and copywriting directives inherited from phase 1>

## Brand DNA Directives
<bulleted visual language directives derived from brand_dna: palette, mood, materials, lighting, typography feel, spacing, composition, logo treatment, and any poster-specific focal elements>

## Template Enforcement
<bulleted instructions from the selected poster template skill translated into concrete canvas zones, hierarchy, sizing discipline, safe areas, and key visible elements>

## Final Image Generation Instructions
<one exact prompt block for VanGogh/image generation. It must include hero subject, layout hierarchy, palette, materials, lighting, product depiction, typography feel, CTA placement, realism/stylization, exclusions, and the main evidence-backed copy/message priorities.>

## Negative Prompt
<comma-separated exclusions and anti-patterns>

QUALITY BAR FOR IMAGE GENERATION PROMPT
- Include subject, scene, composition, camera/framing, poster layout hierarchy, lighting, texture/material treatment, color system, typography feel, CTA treatment, realism/stylization level, and brand constraints.
- Include only the most important evidence-backed message points so the image prompt is organization-specific without becoming bloated.
- Explicitly state that the result is a polished premium poster suitable for launch or campaign use.
- Do not output JSON, XML, code fences, or commentary.
"""

    user_msg = (
        f"USER REQUEST:\n{request_text.strip()}\n\n"
        f"BRAND TONE SKILL:\n{brand_tone_markdown or '(missing brand_tone skill)'}\n\n"
        f"BRAND DNA SKILL:\n{brand_dna_markdown or '(missing brand_dna skill)'}\n\n"
        f"SELECTED TEMPLATE SKILL: {selected_skill_key}\n\n"
        f"SELECTED TEMPLATE MARKDOWN:\n{skill_markdown or '(missing skill markdown)'}\n\n"
        f"PHASE 1 ABSTRACT (approved content plan):\n{phase1_markdown.strip()}\n\n"
        f"BASE EVIDENCE PACK:\n{evidence_brief.strip() or '(no evidence provided)'}\n\n"
        f"OPTIMIZED POSTER RECALL QUERY:\n{optimized_recall_query.strip() or '(no optimized recall query generated)'}\n\n"
        f"OPTIMIZED POSTER RESEARCH EVIDENCE:\n{optimized_research_evidence.strip() or '(no optimized poster evidence returned)'}"
    )

    reply = await poster_model(
        [
            {"role": "system", "content": poster_sys_prompt},
            {"role": "user", "content": user_msg},
        ]
    )
    parsed = _parse_poster_feature_brief(_extract_response_text(reply))
    if not parsed.get("image_prompt"):
        fallback_prompt = "\n\n".join(
            part
            for part in [
                parsed.get("concept", "").strip(),
                parsed.get("evidence_pack", "").strip(),
                parsed.get("brand_tone", "").strip(),
                parsed.get("brand_dna", "").strip(),
                parsed.get("template_system", "").strip(),
            ]
            if part
        ).strip()
        parsed["image_prompt"] = fallback_prompt
    return parsed


async def _generate_poster_recall_query(
    owner: "ContentDirector",
    *,
    request_text: str,
    artifact_type: str,
    selected_skill_key: str,
    phase1_markdown: str,
    phase1_sections: list[Phase1Section],
) -> str:
    query_candidates = [section.recall_query.strip() for section in phase1_sections if section.recall_query.strip()]
    fallback = " | ".join(query_candidates[:4]).strip() or (
        f"{request_text.strip()} poster launch facts, product differentiators, brand palette, typography rules, target audience, CTA constraints"
    )
    recall_model = _build_content_director_authoring_model(owner.resolver, temperature=0.1)
    recall_sys_prompt = f"""You write one high-signal HIVE-MIND recall query for poster enrichment.

Rules:
- Output exactly one plain-text query line.
- Optimize for artifact_type={artifact_type} and selected_skill={selected_skill_key}.
- Focus on the facts needed to generate a branded poster: product details, proof points, target audience, launch framing, palette, typography, CTA constraints, compliance constraints, and visual brand signals.
- Merge overlapping section recall queries into one compact, retrieval-friendly query.
- Bias toward organization-specific facts that materially improve the final poster brief and image prompt.
- No JSON, bullets, markdown, labels, or explanation.
"""
    reply = await recall_model(
        [
            {"role": "system", "content": recall_sys_prompt},
            {
                "role": "user",
                "content": "\n\n".join(
                    part
                    for part in [
                        f"REQUEST:\n{request_text.strip()}",
                        f"PHASE 1 ABSTRACT:\n{phase1_markdown.strip()}",
                        "SECTION RECALL QUERIES:\n" + "\n".join(f"- {item}" for item in query_candidates) if query_candidates else "",
                        f"FALLBACK QUERY:\n{fallback}",
                    ]
                    if part
                ),
            },
        ]
    )
    response_text = _extract_response_text(reply)
    query = response_text.splitlines()[0].strip() if response_text else ""
    return query or fallback


# ─── pre_print hook factory ──────────────────────────────────────────────────

def _make_content_director_print_hook(phase_label: str):
    def _hook(self, kwargs):  # noqa: ANN001
        msg = kwargs.get("msg")
        if msg is None:
            return None
        meta = dict(msg.metadata or {})
        meta.setdefault("kind", "content_abstract")
        meta["phase"] = phase_label
        meta["agent_name"] = getattr(self, "name", "ContentDirector")
        msg.metadata = meta
        logger.info("[PREPRINT_HOOK] agent=%s tagged kind=content_abstract", meta["agent_name"])
        return None
    return _hook


# ─── Main pipeline ────────────────────────────────────────────────────────────

class ContentDirector(BaseAgent):
    def __init__(self, resolver: LiteLLMModelResolver):
        super().__init__(
            name="ContentDirector",
            role="content_director",
            sys_prompt="You are ContentDirector — BLAIQ's visual orchestration pipeline.",
            resolver=resolver
        )
        self.fleet = BlaiqEnterpriseFleet()

    async def orchestrate(
        self,
        request_text: str,
        artifact_type: str,
        evidence_brief: str,
        session_id: str,
    ) -> AsyncGenerator[Msg, None]:

        task_catalog = _build_task_skill_catalog()
        logger.info("[CONTENTDIR] Discovered %d task skills: %s", len(task_catalog), list(task_catalog.keys()))

        # ── Shared skill tools ────────────────────────────────────────────────
        def list_available_skills() -> ToolResponse:
            """List all registered content_director task skills."""
            if not task_catalog:
                return ToolResponse(content=[TextBlock(type="text", text="No task skills registered.")])
            rows = [f"- {m['name']} (key: {k}): {m['description']}" for k, m in sorted(task_catalog.items())]
            logger.info("[CONTENTDIR TOOL] list_available_skills → %d skills", len(task_catalog))
            return ToolResponse(content=[TextBlock(type="text", text="\n".join(rows))])

        def read_skill_markdown(skill_name: str) -> ToolResponse:
            """Read the full SKILL.md for a content_director skill by key or name."""
            raw = (skill_name or "").strip().lower()
            key = next((k for k in task_catalog if k.lower() == raw), None)
            if not key:
                key = next((k for k, m in task_catalog.items() if m["name"].lower() == raw), None)
            if not key:
                return ToolResponse(content=[TextBlock(type="text", text=f"Unknown skill: '{skill_name}'. Call list_available_skills.")])
            try:
                content = Path(task_catalog[key]["path"]).read_text(encoding="utf-8")
                logger.info("[CONTENTDIR TOOL] read_skill_markdown: key=%s size=%d", key, len(content))
                return ToolResponse(content=[TextBlock(type="text", text=content)])
            except Exception as exc:
                return ToolResponse(content=[TextBlock(type="text", text=f"Failed: {exc}")])

        # ── Phase 0: Skill Selector ───────────────────────────────────────────
        selector_model = self.resolver.build_agentscope_model("skill_selector")
        skill_catalog_text = "\n".join(
            f"- key={key}; name={meta['name']}; description={meta['description']}"
            for key, meta in sorted(task_catalog.items())
        ) or "- key=visual_poster; name=visual_poster; description=General visual poster output"
        selector_response = await selector_model(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the Skill Selector for BLAIQ ContentDirector. "
                        "Pick exactly one visual skill based on the user's request and the artifact_type hint. "
                        "Prefer the user's explicit intent. Return JSON only with keys selected_skill and reason."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"artifact_type hint: {artifact_type or '(none provided)'}\n"
                        f"user request: {request_text}\n\n"
                        f"available skills:\n{skill_catalog_text}\n\n"
                        "Return JSON only like "
                        "{\"selected_skill\":\"visual_poster\",\"reason\":\"user explicitly requested a poster\"}."
                    ),
                },
            ]
        )
        selector_text = _extract_response_text(selector_response)

        selected_skill_key = ""
        try:
            m = re.search(r'\{[^{}]*"selected_skill"[^{}]*\}', selector_text)
            if m:
                parsed = json.loads(m.group())
                selected_skill_key = parsed.get("selected_skill", "").strip()
                logger.info("[CONTENTDIR SELECTOR] selected=%s reason=%s", selected_skill_key, parsed.get("reason", ""))
        except Exception:
            pass

        if not selected_skill_key or selected_skill_key not in task_catalog:
            selected_skill_key = _select_skill_without_model(task_catalog, request_text, artifact_type)
            logger.warning("[CONTENTDIR SELECTOR] fallback skill: %s", selected_skill_key)

        # ── Phase 1: Abstract Generator ───────────────────────────────────────
        # Bounded direct generation call. This is an authoring task, not a ReAct tool loop.
        brand_tone_markdown = _read_global_skill_markdown("brand_tone")
        skill_markdown = _read_skill_markdown_text(task_catalog, selected_skill_key)
        logger.info("[CONTENTDIR PHASE1] registered skills: %s + brand_tone", selected_skill_key)
        phase1_model = _build_content_director_authoring_model(self.resolver, temperature=0.2)
        phase1_sys_prompt = "\n".join(
            [
                "You are ContentDirector Phase 1 - Abstract Planner.",
                "",
                "ACTIVE SKILLS",
                "- Brand tone skill:",
                brand_tone_markdown or "(missing brand tone skill)",
                "",
                f"- Selected structure skill ({selected_skill_key}):",
                skill_markdown or "(missing selected skill markdown)",
                "",
                "## YOUR JOB",
                "Map the research evidence to the skill's section structure and produce a content abstract in the correct organizational tone.",
                "Treat the selected skill template as a hard section contract.",
                "Treat the brand tone skill as the writing discipline and the research evidence as factual ground truth.",
                "",
                "## PHASE 1 SCOPE",
                "- This phase defines what the organization should say in each section.",
                "- The content plan must already reflect brand tone, language choice, audience stance, and organizational framing.",
                "- Do NOT write generic placeholder marketing copy. Make it specific to the organization and request.",
                "- If the request or evidence implies one language, keep the whole abstract in that language. Do not mix languages across sections.",
                "- Do not add visual design tokens, palette choices, layout styling, or brand DNA implementation notes in Phase 1.",
                "- Make every section useful for downstream rendering: message hierarchy, proof points, CTA intent, product emphasis, and constraints should already be clear.",
                "",
                "## OUTPUT - return ONLY README-style markdown, nothing else:",
                "# Content Abstract",
                f"Skill: {selected_skill_key}",
                "",
                "## <section_id> | <section title from skill blueprint>",
                "### Content Plan",
                "<context-rich markdown describing what this section must communicate, why it matters, the factual spine, the copy hierarchy, and the organization-specific message priorities. Use bullets, short paragraphs, and tables if useful.>",
                "",
                "### Recall Query",
                "<targeted HIVE-MIND query to enrich this section further with the exact facts needed for rendering and copy precision>",
                "",
                "## RULES",
                "- One section object per section/slide defined in the skill blueprint - no extras, no omissions.",
                "- content_plan: map only facts present in the evidence. No invention.",
                "- content_plan: must reflect brand tone and organization-specific framing, not generic copywriting language.",
                "- content_plan: produce context-rich markdown, not terse notes. Preserve concrete product names, differentiators, constraints, and narrative hierarchy.",
                "- content_plan: explicitly carry forward section-level CTA intent, audience relevance, product benefits, proof points, and compliance constraints where applicable.",
                '- recall_query: specific, section-focused (e.g. "Solvis LEA heat pump COP efficiency specs").',
                "- No visual details in Phase 1 - content mapping only.",
                "- Keep language consistent across the entire abstract.",
                "- Use the exact markdown structure above for every section.",
            ]
        )

        phase1_user_msg = request_text
        if evidence_brief:
            phase1_user_msg = (
                f"## RESEARCH EVIDENCE (ground truth):\n{evidence_brief}\n\n"
                f"## MISSION:\n{request_text}"
            )

        logger.info("[CONTENTDIR PHASE1] Generating abstract. evidence_len=%d", len(evidence_brief))
        phase1_response = await phase1_model(
            [
                {"role": "system", "content": phase1_sys_prompt},
                {"role": "user", "content": phase1_user_msg},
            ]
        )
        phase1_text = _extract_response_text(phase1_response).strip()

        abstract = _extract_phase1_abstract(phase1_text, selected_skill_key)
        if _is_invalid_phase1_reply(phase1_text) or not abstract or "sections" not in abstract:
            logger.warning("[CONTENTDIR PHASE1] Invalid abstract reply, using skill fallback - raw: %s", phase1_text[:300])
            fallback_sections = _build_fallback_phase1_sections(
                request_text=request_text,
                artifact_type=artifact_type,
                selected_skill_key=selected_skill_key,
                skill_markdown=skill_markdown,
            )
            abstract = {
                "skill": selected_skill_key,
                "sections": [section.model_dump() for section in fallback_sections],
            }

        sections = _coerce_phase1_sections(abstract.get("sections", []))
        logger.info("[CONTENTDIR PHASE1] Abstract complete. sections=%d", len(sections))

        # ── Yield Phase 1 abstract as markdown (renders in TextArtifactPreview) ──
        phase1_markdown = _build_phase1_contract_markdown(
            selected_skill_key,
            artifact_type,
            request_text,
            sections,
        )

        yield Msg(
            name="ContentDirector",
            content=phase1_markdown,
            role="assistant",
            metadata={
                "kind": "content_abstract",
                "artifact_type": artifact_type,
                "selected_skill": selected_skill_key,
            },
        )

        normalized_artifact_type = _normalize_visual_artifact_type(artifact_type, request_text, selected_skill_key)
        poster_feature_path = _is_poster_feature_path(normalized_artifact_type, selected_skill_key)

        recall_enabled = (
            selected_skill_key == "visual_pitch_deck"
            or normalized_artifact_type in {"pitch_deck", "keynote", "presentation"}
        )

        if poster_feature_path:
            optimized_recall_query = await _generate_poster_recall_query(
                self,
                request_text=request_text,
                artifact_type=normalized_artifact_type,
                selected_skill_key=selected_skill_key,
                phase1_markdown=phase1_markdown,
                phase1_sections=sections,
            )
            poster_research_evidence = ""
            if optimized_recall_query:
                try:
                    recall_result = await self.fleet.hivemind_recall(
                        query=optimized_recall_query,
                        session_id=session_id,
                    )
                    poster_research_evidence = "".join(
                        block.text for block in (recall_result.content or []) if hasattr(block, "text")
                    ).strip()
                    logger.info(
                        "[CONTENTDIR POSTER] optimized recall query len=%d evidence_len=%d",
                        len(optimized_recall_query),
                        len(poster_research_evidence),
                    )
                except Exception as exc:
                    logger.warning("[CONTENTDIR POSTER] optimized recall failed: %s", exc)
            poster_brief = await _generate_poster_feature_brief(
                self,
                request_text=request_text,
                artifact_type=normalized_artifact_type,
                selected_skill_key=selected_skill_key,
                task_catalog=task_catalog,
                phase1_markdown=phase1_markdown,
                evidence_brief=evidence_brief,
                optimized_research_evidence=poster_research_evidence,
                optimized_recall_query=optimized_recall_query,
            )
            poster_sections = _coerce_phase2_sections(_build_poster_sections_from_brief(poster_brief))
            poster_markdown = _build_phase2_contract_markdown(
                selected_skill_key,
                normalized_artifact_type,
                request_text,
                poster_sections,
            )

            render_plan = VisualRenderPlan(
                artifact_type=normalized_artifact_type,
                selected_skill=selected_skill_key,
                title=request_text.strip() or f"{normalized_artifact_type or 'visual'} artifact",
                render_mode="generate_image",
                storyboard_markdown=poster_markdown,
                content_abstract_markdown=phase1_markdown,
                sections=poster_sections,
                image_prompt=None,
                poster_feature_markdown=poster_brief.get("creative_brief", "").strip() or None,
                prompt_strategy="poster_feature_v1",
            )

            yield Msg(
                name="ContentDirector",
                content=render_plan.model_dump_json(),
                role="assistant",
                metadata={
                    "kind": "storyboard_detailed",
                    "artifact_type": normalized_artifact_type,
                    "selected_skill": selected_skill_key,
                    "render_mode": "generate_image",
                    "prompt_strategy": "poster_feature_v1",
                },
            )
            return

        # ── Section recall helper (direct fleet call, no agent overhead) ────────
        token = active_session_id.set(session_id)

        async def _recall(section: Phase1Section) -> str:
            query = section.recall_query
            if not query:
                return ""
            try:
                result = await self.fleet.hivemind_recall(query=query, session_id=session_id)
                text = "".join(block.text for block in (result.content or []) if hasattr(block, "text"))
                logger.info("[CONTENTDIR RECALL] section=%s evidence_len=%d",
                            section.section_id, len(text))
                return text
            except Exception as exc:
                logger.warning("[CONTENTDIR RECALL] section=%s failed: %s", section.section_id, exc)
                return ""

        # ── Phase 2: Detailed Storyboard — section-by-section ────────────────
        phase2_sys_prompt = """You are ContentDirector Phase 2 - Section Detail Generator.

Your active brand_dna skill above defines visual design tokens, typography, and layout rules.
Your active selected skill blueprint defines the section contract and layout intent.

## YOUR JOB
    Generate one detailed storyboard section for VanGogh.

    ## SOURCE OF TRUTH
    - The Phase 1 abstract is the content source of truth.
    - Preserve the message hierarchy, section intent, and language established in Phase 1.
    - Use brand_dna to decide how the content should be visually expressed, not to rewrite the organization into a different voice.
    - Make the result organization-specific and internally consistent with the Phase 1 abstract.
    - The final result must read like a content-rich README for a downstream visual generator.
    - The tone must still feel like the organization described in Phase 1, while the visual instructions must explicitly operationalize brand_dna.
    - The selected skill template is mandatory. Respect its section purpose, hierarchy, visible components, and any canvas or layout constraints.
    - Use enriched recall evidence to make the section more precise, more factual, and more organization-context-rich.

    ## MARKDOWN RENDERING REQUIREMENTS
    Your output will be rendered as markdown in a React preview. Optimize for readability and strong visual hierarchy.

    - Use clean markdown only. No HTML, no code fences, no JSON.
    - Keep paragraphs short. Prefer 1-3 sentence blocks.
    - Use bullet lists for grouped directives, assets, component lists, and layout instructions.
    - Use markdown tables for structured specs when multiple properties need comparison or alignment.
    - Use **bold** for key tokens, numbers, colors, typography names, and critical constraints.
    - Use blockquotes for single-line creative direction or emphasis callouts when helpful.
    - Do not write meta commentary such as "Here is the section".
    - Make the content look editorial and presentation-ready, not like raw notes.

## OUTPUT - return ONLY this markdown block (no other text):

## <section_id> | <title>

### Synthesis
<context-rich markdown with headline, subheadline, body copy, data points, and evidence-backed narrative structure. Use bullets or tables when they improve clarity.>

### Brand Tone Signals
<short markdown bullets describing the tone, audience stance, and key phrasing signals inherited from Phase 1>

### Visual Spec
<context-rich markdown for VanGogh using brand_dna tokens and template constraints: layout type, background color, typography tokens, component list, spacing, dimensions, composition cues, UI elements, and section-specific hierarchy>

### Image Prompt Notes
<high-density markdown prompt ingredients VanGogh should preserve if it calls generate_image, including subject, hierarchy, brand cues, UI/canvas details, and exclusions>

## RULES
- brand_dna tokens MUST be used (hex colors, font names, spacing scale).
- Synthesis uses the Phase 1 abstract plus evidence as ground truth - no invention.
- Do not change the language chosen in Phase 1.
- Brand Tone Signals must be derived from Phase 1 wording, not invented from scratch.
- Image Prompt Notes should be concise but visually specific: subject, composition, mood, color, typography feel, CTA treatment, realism level, UI treatment, and exclusions where useful.
    - In Visual Spec, prefer compact markdown lists or tables instead of dense prose.
    - If the section benefits from a hero, comparison, or step layout, state that explicitly.
- Carry forward concrete evidence-backed names, features, dimensions, and section copy priorities whenever they materially improve render quality.
- Output ONLY the markdown block above. No JSON, no preamble, no explanation.
"""

        def _parse_phase2_markdown(text: str, fallback_section: Phase1Section) -> Phase2Section:
            """Parse Phase 2 markdown output into a section dict."""
            clean = text.strip()
            section_id = fallback_section.section_id
            title = fallback_section.title

            # Extract section_id and title from "## section_id | title"
            header_m = re.search(r"^##\s+([^|\n]+)\|([^\n]+)", clean, re.MULTILINE)
            if header_m:
                section_id = header_m.group(1).strip() or section_id
                title = header_m.group(2).strip() or title

            synthesis = _extract_markdown_section(clean, "Synthesis") or clean
            brand_tone_signals = _extract_markdown_section(clean, "Brand Tone Signals")
            visual_spec = _extract_markdown_section(clean, "Visual Spec")
            image_prompt_notes = _extract_markdown_section(clean, "Image Prompt Notes")

            return Phase2Section(
                section_id=section_id,
                title=title,
                synthesis=synthesis,
                brand_tone_signals=brand_tone_signals,
                visual_spec=visual_spec,
                image_prompt_notes=image_prompt_notes,
            )

        async def _generate_section_detail(section: Phase1Section, enriched_evidence: str) -> Phase2Section:
            brand_dna_markdown = _read_global_skill_markdown("brand_dna")
            phase2_model = _build_content_director_authoring_model(self.resolver, temperature=0.2)
            user_msg = (
                f"PHASE 1 ABSTRACT (source of truth):\n"
                f"section_id: {section.section_id}\n"
                f"title: {section.title}\n"
                f"content_plan: {section.content_plan}\n"
                f"recall_query: {section.recall_query}\n\n"
                f"SELECTED SKILL TEMPLATE ({selected_skill_key}):\n"
                f"{skill_markdown or '(missing selected skill markdown)'}\n\n"
                f"SECTION TO DETAIL:\n"
                f"section_id: {section.section_id}\n"
                f"title: {section.title}\n"
                f"content_plan: {section.content_plan}\n\n"
                f"ENRICHED EVIDENCE FOR THIS SECTION:\n"
                f"{enriched_evidence or 'None - use original evidence brief only.'}"
            )
            reply = await phase2_model(
                [
                    {
                        "role": "system",
                        "content": phase2_sys_prompt + f"\n\nACTIVE BRAND DNA SKILL:\n{brand_dna_markdown or '(missing brand_dna skill)'}",
                    },
                    {"role": "user", "content": user_msg},
                ]
            )
            text = _extract_response_text(reply).strip()
            parsed = _parse_phase2_markdown(text, section)
            if parsed.synthesis:
                logger.info("[CONTENTDIR PHASE2] section=%s ✓", section.section_id)
            else:
                logger.warning("[CONTENTDIR PHASE2] section=%s empty synthesis", section.section_id)
            return parsed

        # Pitch decks benefit from per-section evidence enrichment.
        # Posters and similar single-surface visuals should skip recall and move
        # directly from phase 1 abstract to phase 2 expansion.
        logger.info(
            "[CONTENTDIR PHASE2] Starting generation. sections=%d recall_enabled=%s artifact_type=%s skill=%s",
            len(sections),
            recall_enabled,
            artifact_type,
            selected_skill_key,
        )
        detailed_sections: list[Phase2Section] = []
        recall_results: list[str] = [""] * len(sections)

        try:
            if recall_enabled and sections:
                recall_results[0] = await _recall(sections[0])

            for i, section in enumerate(sections):
                tasks: list = [_generate_section_detail(section, recall_results[i])]
                if recall_enabled and i + 1 < len(sections):
                    tasks.append(_recall(sections[i + 1]))
                results = await asyncio.gather(*tasks)
                detailed_sections.append(results[0])
                if recall_enabled and i + 1 < len(sections):
                    recall_results[i + 1] = results[1]
                    logger.info("[CONTENTDIR PIPELINE] generated=%s recalled=%s",
                                section.section_id, sections[i + 1].section_id)
                elif not recall_enabled:
                    logger.info("[CONTENTDIR PIPELINE] generated=%s (recall skipped)", section.section_id)
                else:
                    logger.info("[CONTENTDIR PIPELINE] generated=%s (last)", section.section_id)
        finally:
            active_session_id.reset(token)

        logger.info("[CONTENTDIR PHASE2] All sections complete. count=%d", len(detailed_sections))

        output_content = _build_phase2_contract_markdown(
            selected_skill_key,
            artifact_type,
            request_text,
            detailed_sections,
        )
        render_mode = _select_render_mode(artifact_type, selected_skill_key)
        render_plan = VisualRenderPlan(
            artifact_type=artifact_type,
            selected_skill=selected_skill_key,
            title=request_text.strip() or f"{artifact_type or 'visual'} artifact",
            render_mode=render_mode,
            storyboard_markdown=output_content,
            content_abstract_markdown=phase1_markdown,
            sections=detailed_sections,
            image_prompt=None,
        )

        yield Msg(
            name="ContentDirector",
            content=render_plan.model_dump_json(),
            role="assistant",
            metadata={
                "kind": "storyboard_detailed",
                "artifact_type": artifact_type,
                "selected_skill": selected_skill_key,
                "render_mode": render_mode,
            },
        )


# ─── AaaS app ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    logger.info("ContentDirector V2 (Skill-Selector | Phase1-Abstract | Recall-Loop | Phase2-Detail) online.")
    yield
    logger.info("ContentDirector V2 offline.")


# Initialize the real production app
app = AgentApp(
    app_name="ContentDirectorV2",
    app_description="Three-phase visual orchestration: skill selection → abstract → section recall → detailed storyboard",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0"),
)


@app.query(framework="agentscope")
async def orchestrate(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    resolver = LiteLLMModelResolver.from_settings(settings)
    director = ContentDirector(resolver=resolver)

    # Scan all msgs — AaaS may drop message-level metadata
    artifact_type = ""
    evidence_brief = ""
    request_text = ""
    first_text = ""

    for raw in msgs:
        m = Msg(**raw) if isinstance(raw, dict) else raw
        text = m.get_text_content() or ""
        if text and not first_text:
            first_text = text
        if text and getattr(m, "role", "") == "user" and not request_text:
            request_text = text
        meta = m.metadata or {}
        if meta.get("artifact_type"):
            artifact_type = meta["artifact_type"]
        if meta.get("evidence_brief"):
            evidence_brief = meta["evidence_brief"]

    if not request_text:
        request_text = first_text

    if not artifact_type:
        artifact_type = "general"

    logger.info("[CONTENTDIR REQUEST] type=%s session=%s evidence_len=%d",
                artifact_type, request.session_id, len(evidence_brief))

    async for item in director.orchestrate(
        request_text=request_text,
        artifact_type=artifact_type,
        evidence_brief=evidence_brief,
        session_id=request.session_id,
    ):
        kind = (item.metadata or {}).get("kind", "")
        is_last = kind == "storyboard_detailed"
        logger.info("[CONTENTDIR OUTPUT] kind=%s is_last=%s length=%d",
                    kind, is_last, len(item.content) if item.content else 0)
        yield item, is_last


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8095)
