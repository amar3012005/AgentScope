# -*- coding: utf-8 -*-
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from agentscope.message import Msg
from agentscope.message import TextBlock
from agentscope.tool import Toolkit, ToolResponse

# AgentScope Runtime (AaaS)
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
        def __init__(
            self,
            *args,
            app_name: str | None = None,
            app_description: str | None = None,
            a2a_config=None,
            **kwargs,
        ):
            del args, a2a_config
            super().__init__(title=app_name, description=app_description, **kwargs)

        def query(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator


def _create_decorator_app() -> AgentApp:
    try:
        return AgentApp(app_name="agentscope", app_description="AgentScope Runtime")
    except TypeError:
        return AgentApp(title="agentscope", description="AgentScope Runtime")


_fallback_app = _create_decorator_app()
app = _fallback_app
import json
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.tools.openrouter_media import OpenRouterMediaService, image_tool_response, video_tool_response

from agentscope_blaiq.runtime.agent_base import BaseAgent


def _extract_json_object(text: str) -> dict | None:
    clean = str(text or "").strip()
    if not clean:
        return None
    clean = re.sub(r"^```(?:json)?\s*\n?", "", clean)
    clean = re.sub(r"\n?```\s*$", "", clean).strip()
    try:
        parsed = json.loads(clean)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    start = clean.find("{")
    if start == -1:
        return None
    depth = 0
    for idx, ch in enumerate(clean[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(clean[start:idx + 1])
                    return parsed if isinstance(parsed, dict) else None
                except Exception:
                    return None
    return None


def _strip_code_fences(text: str) -> str:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", clean)
        clean = re.sub(r"\n?```\s*$", "", clean).strip()
    return clean


def _normalize_media_items(payload: dict | None) -> dict[str, list[dict]]:
    generated_media = payload if isinstance(payload, dict) else {}
    images: list[dict] = []
    videos: list[dict] = []

    for index, image in enumerate(generated_media.get("images") or [], start=1):
        if not isinstance(image, dict):
            continue
        src = str(image.get("image_url") or image.get("saved_path") or "").strip()
        if not src:
            continue
        images.append(
            {
                "id": f"image-{index}",
                "type": "image",
                "src": src,
                "thumbnail_src": str(image.get("image_url") or src),
                "mime_type": "image/png",
                "alt": "Generated visual artifact",
                "caption": str(image.get("prompt") or "Generated image").strip() or "Generated image",
                "status": "ready",
                "generation_state": "ready",
            }
        )

    for index, video in enumerate(generated_media.get("videos") or [], start=1):
        if not isinstance(video, dict):
            continue
        unsigned_urls = video.get("unsigned_urls") or []
        src = str(unsigned_urls[0] if unsigned_urls else video.get("src") or "").strip()
        if not src:
            continue
        videos.append(
            {
                "id": f"video-{index}",
                "type": "video",
                "src": src,
                "mime_type": "video/mp4",
                "alt": "Generated video artifact",
                "caption": str(video.get("prompt") or "Generated video").strip() or "Generated video",
                "status": "ready",
                "generation_state": "ready",
            }
        )

    return {"images": images, "videos": videos}


def _merge_media_items(normalized_media: dict[str, list[dict]]) -> list[dict]:
    return list(normalized_media.get("images") or []) + list(normalized_media.get("videos") or [])


def _build_preview_html(data: dict) -> str:
    html = _strip_code_fences(str(data.get("html") or ""))
    if html:
        return html

    css = _strip_code_fences(str(data.get("css") or ""))
    prompts = data.get("image_prompts") if isinstance(data.get("image_prompts"), list) else []
    rationale = str(data.get("design_rationale") or "").strip()
    legacy_code = _strip_code_fences(str(data.get("ui_code") or ""))

    prompt_cards = []
    for prompt in prompts:
        if not isinstance(prompt, dict):
            continue
        prompt_id = str(prompt.get("id") or "section").strip()
        prompt_text = str(prompt.get("prompt") or "").strip()
        if not prompt_text:
            continue
        prompt_cards.append(
            "<article class='vg-card'>"
            f"<div class='vg-eyebrow'>{prompt_id}</div>"
            f"<p>{prompt_text}</p>"
            "</article>"
        )

    rationale_html = f"<section class='vg-rationale'><h2>Design Rationale</h2><p>{rationale}</p></section>" if rationale else ""
    code_html = (
        "<section class='vg-rationale'><h2>Implementation Notes</h2>"
        f"<pre>{legacy_code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</pre>"
        "</section>"
        if legacy_code else ""
    )

    default_css = """
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, system-ui, sans-serif;
      background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
      color: #0f172a;
    }
    .vg-shell {
      max-width: 1200px;
      margin: 0 auto;
      padding: 40px 24px 64px;
    }
    .vg-hero {
      padding: 32px;
      border-radius: 28px;
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(15,23,42,0.08);
      box-shadow: 0 18px 48px rgba(15,23,42,0.08);
      backdrop-filter: blur(10px);
    }
    .vg-hero h1 {
      margin: 0 0 12px;
      font-size: clamp(32px, 5vw, 56px);
      line-height: 1;
      letter-spacing: -0.04em;
    }
    .vg-hero p {
      margin: 0;
      max-width: 820px;
      font-size: 18px;
      line-height: 1.7;
      color: #334155;
    }
    .vg-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 20px;
      margin-top: 28px;
    }
    .vg-card, .vg-rationale {
      padding: 24px;
      border-radius: 24px;
      background: rgba(255,255,255,0.9);
      border: 1px solid rgba(15,23,42,0.08);
      box-shadow: 0 12px 32px rgba(15,23,42,0.06);
    }
    .vg-eyebrow {
      margin-bottom: 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: #475569;
    }
    .vg-card p, .vg-rationale p {
      margin: 0;
      white-space: pre-wrap;
      line-height: 1.7;
      color: #334155;
    }
    .vg-rationale { margin-top: 24px; }
    .vg-rationale h2 {
      margin: 0 0 12px;
      font-size: 20px;
      letter-spacing: -0.02em;
    }
    .vg-rationale pre {
      overflow: auto;
      padding: 16px;
      border-radius: 16px;
      background: #0f172a;
      color: #e2e8f0;
      font-size: 13px;
      line-height: 1.6;
    }
    @media (max-width: 640px) {
      .vg-shell { padding: 20px 14px 40px; }
      .vg-hero, .vg-card, .vg-rationale { padding: 20px; border-radius: 20px; }
    }
    """
    style_block = f"<style>{default_css}\n{css}</style>"
    grid_html = "<section class='vg-grid'>" + "".join(prompt_cards) + "</section>" if prompt_cards else ""
    subtitle = rationale or "Visual package generated by VanGogh."
    return (
        style_block
        + "<main class='vg-shell'>"
        + "<section class='vg-hero'><div class='vg-eyebrow'>VanGogh Preview</div>"
        + "<h1>Visual Artifact Ready</h1>"
        + f"<p>{subtitle}</p></section>"
        + grid_html
        + rationale_html
        + code_html
        + "</main>"
    )


def _build_render_plan_preview_html(render_plan: dict | None, fallback_text: str = "") -> str:
    if not isinstance(render_plan, dict):
        return _build_preview_html({"design_rationale": _strip_code_fences(fallback_text)})

    title = str(render_plan.get("title") or "Visual Artifact Ready").strip() or "Visual Artifact Ready"
    sections = render_plan.get("sections") or []
    cards: list[str] = []
    for section in sections[:8]:
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title") or section.get("section_id") or "Section").strip()
        synthesis = str(section.get("synthesis") or "").strip()
        visual_spec = str(section.get("visual_spec") or "").strip()
        prompt_notes = str(section.get("image_prompt_notes") or "").strip()
        excerpt = synthesis or visual_spec or prompt_notes
        if len(excerpt) > 520:
            excerpt = excerpt[:520].rstrip() + "..."
        if not excerpt:
            continue
        cards.append(
            "<article class='vg-card'>"
            f"<div class='vg-eyebrow'>{section_title}</div>"
            f"<p>{excerpt}</p>"
            "</article>"
        )

    narrative = str(render_plan.get("storyboard_markdown") or fallback_text or "").strip()
    subtitle = "Structured render plan preview generated from ContentDirector output."
    if narrative:
        subtitle = narrative.splitlines()[0].lstrip("# ").strip() or subtitle

    default_css = """
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, system-ui, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(251, 146, 60, 0.12), transparent 36%),
        linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
      color: #0f172a;
    }
    .vg-shell { max-width: 1220px; margin: 0 auto; padding: 40px 24px 64px; }
    .vg-hero {
      padding: 32px;
      border-radius: 28px;
      background: rgba(255,255,255,0.88);
      border: 1px solid rgba(15,23,42,0.08);
      box-shadow: 0 18px 48px rgba(15,23,42,0.08);
      backdrop-filter: blur(10px);
    }
    .vg-hero h1 {
      margin: 0 0 10px;
      font-size: clamp(30px, 5vw, 54px);
      line-height: 1;
      letter-spacing: -0.04em;
    }
    .vg-hero p {
      margin: 0;
      max-width: 860px;
      font-size: 18px;
      line-height: 1.7;
      color: #334155;
    }
    .vg-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 20px;
      margin-top: 28px;
    }
    .vg-card {
      padding: 24px;
      border-radius: 24px;
      background: rgba(255,255,255,0.92);
      border: 1px solid rgba(15,23,42,0.08);
      box-shadow: 0 12px 32px rgba(15,23,42,0.06);
    }
    .vg-eyebrow {
      margin-bottom: 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: #475569;
    }
    .vg-card p {
      margin: 0;
      white-space: pre-wrap;
      line-height: 1.75;
      color: #334155;
    }
    @media (max-width: 640px) {
      .vg-shell { padding: 20px 14px 40px; }
      .vg-hero, .vg-card { padding: 20px; border-radius: 20px; }
    }
    """
    return (
        f"<style>{default_css}</style>"
        + "<main class='vg-shell'>"
        + "<section class='vg-hero'>"
        + "<div class='vg-eyebrow'>VanGogh Render Plan Preview</div>"
        + f"<h1>{title}</h1>"
        + f"<p>{subtitle}</p>"
        + "</section>"
        + ("<section class='vg-grid'>" + "".join(cards) + "</section>" if cards else "")
        + "</main>"
    )


def _extract_render_plan(visual_spec: str) -> dict | None:
    parsed = _extract_json_object(visual_spec)
    if isinstance(parsed, dict) and parsed.get("contract") == "visual_render_plan_v1":
        return parsed
    return None


def _resolve_direct_media_mode(render_plan: dict | None, metadata: dict | None = None) -> str | None:
    metadata = metadata or {}
    if not isinstance(render_plan, dict):
        artifact_type = str(metadata.get("artifact_type") or "").strip().lower()
        if artifact_type in {"video", "motion", "trailer", "reel", "video_trailer", "video_campaign"}:
            return "generate_video"
        return "generate_image"

    artifact_type = str(render_plan.get("artifact_type") or metadata.get("artifact_type") or "").strip().lower()
    render_mode = str(render_plan.get("render_mode") or "").strip().lower()
    prompt_strategy = str(render_plan.get("prompt_strategy") or "").strip().lower()

    if render_mode == "generate_video":
        return "generate_video"
    if render_mode == "generate_image":
        return "generate_image"
    if artifact_type in {"video", "motion", "trailer", "reel"}:
        return "generate_video"
    if prompt_strategy.startswith("poster_feature"):
        return "generate_image"
    return "generate_image"


def _pick_direct_media_prompt(render_plan: dict | None, visual_spec: str, mode: str) -> str:
    if not isinstance(render_plan, dict):
        return str(visual_spec or "").strip()

    storyboard_markdown = str(render_plan.get("storyboard_markdown") or "").strip()

    def _extract_phase2_prompt(markdown: str) -> str:
        if not markdown:
            return ""
        exact_prompt = re.search(
            r"\*\*Exact VanGogh Image Prompt\*\*\s*\n+(.*?)(?=\n\*\*Negative Prompt\*\*|\Z)",
            markdown,
            re.DOTALL,
        )
        if exact_prompt:
            return exact_prompt.group(1).strip()
        image_notes = re.search(
            r"###\s+Image Prompt Notes\s*\n(.*?)(?=\n###\s+|\n##\s+|\Z)",
            markdown,
            re.DOTALL,
        )
        if image_notes:
            return image_notes.group(1).strip()
        return ""

    phase2_prompt = _extract_phase2_prompt(storyboard_markdown)
    if phase2_prompt:
        return phase2_prompt

    prompt_fields = ["video_prompt", "motion_prompt", "image_prompt", "storyboard_markdown"]
    if mode == "generate_image":
        prompt_fields = ["image_prompt", "storyboard_markdown", "video_prompt", "motion_prompt"]
    for field in prompt_fields:
        value = str(render_plan.get(field) or "").strip()
        if value:
            return value
    return str(visual_spec or "").strip()


def _build_layout_hints(mode: str, media_items: list[dict]) -> dict[str, Any]:
    if mode == "generate_video":
        first_video = next((item for item in media_items if item.get("type") == "video"), None)
        return {"layout": "inline", "hero_item_id": (first_video or {}).get("id")}
    hero_id = media_items[0]["id"] if media_items else None
    return {"layout": "hero", "hero_item_id": hero_id}


def _build_visual_render_result(
    *,
    artifact_type: str | None,
    title: str,
    render_mode: str,
    html: str,
    css: str,
    media: list[dict],
    layout_hints: dict[str, Any],
    storyboard_markdown: str,
    source_render_plan: dict | None,
    generated_media: dict[str, Any] | None = None,
    preview_metadata: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": "visual_render_result_v1",
        "artifact_type": artifact_type,
        "title": title,
        "render_mode": render_mode,
        "html": html,
        "css": css,
        "media": media,
        "layout_hints": layout_hints,
        "storyboard_markdown": storyboard_markdown,
        "source_render_plan": source_render_plan,
        "preview_metadata": preview_metadata or {
            "viewport": "desktop",
            "format_hint": "visual_media" if render_mode in {"generate_image", "generate_video"} else "visual_html",
            "theme_notes": [],
        },
    }
    if generated_media is not None:
        payload["generated_media"] = generated_media
    if diagnostics:
        payload["diagnostics"] = diagnostics
    return payload


def _toolkit_visual_payload(
    *,
    generated_payload: dict[str, Any] | None,
    direct_media_mode: str,
    artifact_type: str | None,
    title: str,
    storyboard_markdown: str,
    render_plan: dict | None,
    prompt: str,
) -> dict[str, Any]:
    generated_payload = generated_payload if isinstance(generated_payload, dict) else {}
    normalized_media = _normalize_media_items(
        {
            "images": generated_payload.get("images", []),
            "videos": generated_payload.get("videos", [generated_payload] if direct_media_mode == "generate_video" else []),
        }
    )
    media_items = _merge_media_items(normalized_media)
    return _build_visual_render_result(
        artifact_type=artifact_type,
        title=title,
        render_mode=direct_media_mode,
        html="",
        css="",
        media=media_items,
        layout_hints=_build_layout_hints(direct_media_mode, media_items),
        storyboard_markdown=storyboard_markdown,
        source_render_plan=render_plan,
        generated_media=generated_payload,
        diagnostics={"tool_path": direct_media_mode, "prompt_used": prompt},
    )


def _truncate_for_log(value: object, limit: int = 240) -> str:
    text = str(value or "").strip().replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _build_compact_visual_spec(render_plan: dict | None, fallback_spec: str) -> str:
    if not isinstance(render_plan, dict):
        return str(fallback_spec or "").strip()

    sections = render_plan.get("sections") or []
    compact_sections: list[str] = []
    for section in sections[:8]:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or section.get("section_id") or "Section").strip()
        synthesis = str(section.get("synthesis") or "").strip()
        tone = str(section.get("brand_tone_signals") or "").strip()
        visual = str(section.get("visual_spec") or "").strip()
        image_notes = str(section.get("image_prompt_notes") or "").strip()

        if len(synthesis) > 700:
            synthesis = synthesis[:700].rstrip() + "..."
        if len(tone) > 300:
            tone = tone[:300].rstrip() + "..."
        if len(visual) > 700:
            visual = visual[:700].rstrip() + "..."
        if len(image_notes) > 350:
            image_notes = image_notes[:350].rstrip() + "..."

        lines = [f"## {title}"]
        if synthesis:
            lines.append(f"Synthesis: {synthesis}")
        if tone:
            lines.append(f"Brand Tone Signals: {tone}")
        if visual:
            lines.append(f"Visual Spec: {visual}")
        if image_notes:
            lines.append(f"Image Prompt Notes: {image_notes}")
        compact_sections.append("\n".join(lines))

    compact_parts = [
        f"Artifact type: {str(render_plan.get('artifact_type') or '').strip()}",
        f"Selected skill: {str(render_plan.get('selected_skill') or '').strip()}",
        f"Render mode: {str(render_plan.get('render_mode') or '').strip()}",
        f"Title: {str(render_plan.get('title') or '').strip()}",
    ]
    if compact_sections:
        compact_parts.append("\n\n".join(compact_sections))

    compact_spec = "\n\n".join(part for part in compact_parts if part and part.strip()).strip()
    return compact_spec or str(fallback_spec or "").strip()


def _extract_response_text(response: object) -> str:
    if response is None:
        return ""
    if isinstance(response, dict):
        value = response.get("text") or response.get("content") or ""
    elif hasattr(response, "get_text_content"):
        try:
            value = response.get_text_content() or getattr(response, "content", "")
        except Exception:
            value = getattr(response, "content", "")
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
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()

class VanGogh(BaseAgent):
    """
    The Visual Execution Node.
    Translates Storyboard pages into Image Prompts and React Code.
    """
    def __init__(self, resolver: LiteLLMModelResolver | None = None):
        runtime_resolver = resolver or LiteLLMModelResolver.from_settings(settings)
        super().__init__(
            name="VanGogh",
            role="vangogh",
            sys_prompt="",
            resolver=runtime_resolver,
        )
        self.model = self.resolver.build_agentscope_model("vangogh")
        self.media_service = OpenRouterMediaService()

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        toolkit.register_tool_function(self.generate_image)
        toolkit.register_tool_function(self.generate_video)
        return toolkit

    async def _run_image_generation(
        self,
        *,
        prompt: str,
        reference_image: str | None = None,
        model: str | None = None,
    ) -> dict[str, object]:
        logger.info(
            "[VANGOGH TOOL] generate_image model=%s prompt_len=%d ref=%s preview=%s",
            model or settings.openrouter_image_model,
            len(prompt or ""),
            bool(reference_image),
            _truncate_for_log(prompt),
        )
        return await self.media_service.generate_image(
            prompt=prompt,
            reference_image=reference_image,
            model=model,
        )

    async def _run_video_generation(
        self,
        *,
        prompt: str,
        model: str | None = None,
    ) -> dict[str, object]:
        logger.info(
            "[VANGOGH TOOL] generate_video model=%s prompt_len=%d preview=%s",
            model or settings.openrouter_video_model,
            len(prompt or ""),
            _truncate_for_log(prompt),
        )
        return await self.media_service.generate_video(prompt=prompt, model=model)

    async def generate_image(
        self,
        prompt: str,
        reference_image: str | None = None,
        model: str | None = None,
    ) -> ToolResponse:
        try:
            result = await self._run_image_generation(prompt=prompt, reference_image=reference_image, model=model)
            return image_tool_response(result)
        except Exception as exc:
            return ToolResponse(content=[TextBlock(type="text", text=f"Error: {exc}")])

    async def generate_video(
        self,
        prompt: str,
        model: str | None = None,
    ) -> ToolResponse:
        try:
            result = await self._run_video_generation(prompt=prompt, model=model)
            return video_tool_response(result)
        except Exception as exc:
            return ToolResponse(content=[TextBlock(type="text", text=f"Error: {exc}")])

    async def render(
        self,
        msgs,
        request: AgentRequest = None,
        **kwargs,
    ):
        """
        Renders design specs into assets and code.
        """
        resolver = LiteLLMModelResolver.from_settings(settings)
        self.model = resolver.build_agentscope_model("vangogh")

        latest_msg = msgs[-1]
        if isinstance(latest_msg, dict):
            latest_msg = Msg(**latest_msg)
            
        metadata = latest_msg.metadata or {}
        visual_spec = latest_msg.content
        brand_dna = metadata.get("brand_dna", "")

        logger.info(f"Rendering design for session {request.session_id}")

        # VanGogh rendering is a one-shot LLM call, but we wrap it for telemetry
        await self._universal_acting_hook(agent_name="VanGogh", phase="rendering")

        async for item in self.render_artifact_internal(
            visual_spec=visual_spec,
            brand_dna=brand_dna,
            metadata=metadata,
        ):
            yield item, True

    async def render_artifact_internal(
        self,
        visual_spec: str,
        brand_dna: str,
        metadata: dict | None = None,
    ) -> AsyncGenerator[Msg, None]:
        render_plan = _extract_render_plan(visual_spec)
        metadata = metadata or {}
        direct_media_mode = _resolve_direct_media_mode(render_plan, metadata)
        logger.info(
            "[VANGOGH RENDER] direct_mode=%s artifact_type=%s render_mode=%s title=%s selected_skill=%s",
            direct_media_mode,
            metadata.get("artifact_type") or (render_plan.get("artifact_type") if isinstance(render_plan, dict) else None),
            (render_plan.get("render_mode") if isinstance(render_plan, dict) else None),
            _truncate_for_log((render_plan.get("title") if isinstance(render_plan, dict) else "")),
            (render_plan.get("selected_skill") if isinstance(render_plan, dict) else None),
        )

        if direct_media_mode:
            prompt = _pick_direct_media_prompt(render_plan, visual_spec, direct_media_mode)
            logger.info(
                "[VANGOGH RENDER] executing tool path=%s prompt_len=%d prompt_preview=%s",
                direct_media_mode,
                len(prompt or ""),
                _truncate_for_log(prompt, 320),
            )
            if direct_media_mode == "generate_video":
                generated_payload = await self._run_video_generation(prompt=prompt)
            else:
                reference_image = None
                if isinstance(render_plan, dict):
                    reference_image = str(render_plan.get("reference_image") or "").strip() or None
                generated_payload = await self._run_image_generation(prompt=prompt, reference_image=reference_image)
            logger.info(
                "[VANGOGH RENDER] tool result path=%s images=%d videos=%d payload_keys=%s",
                direct_media_mode,
                len((generated_payload or {}).get("images") or []),
                len((generated_payload or {}).get("videos") or []),
                sorted((generated_payload or {}).keys()) if isinstance(generated_payload, dict) else [],
            )

            artifact_type = metadata.get("artifact_type") or (render_plan.get("artifact_type") if isinstance(render_plan, dict) else None)
            title = str((render_plan or {}).get("title") or "Visual Artifact").strip() or "Visual Artifact"
            storyboard_markdown = str((render_plan or {}).get("storyboard_markdown") or "")
            payload = _toolkit_visual_payload(
                generated_payload=generated_payload if isinstance(generated_payload, dict) else None,
                direct_media_mode=direct_media_mode,
                artifact_type=artifact_type,
                title=title,
                storyboard_markdown=storyboard_markdown,
                render_plan=render_plan,
                prompt=prompt,
            )
            logger.info(
                "[VANGOGH RENDER] normalized payload media=%d layout=%s hero=%s",
                len(payload.get("media") or []),
                ((payload.get("layout_hints") or {}).get("layout")),
                ((payload.get("layout_hints") or {}).get("hero_item_id")),
            )

            yield Msg(
                name="VanGogh",
                content=json.dumps(
                    payload,
                    ensure_ascii=False,
                ),
                role="assistant",
                metadata={
                    "kind": "design_spec",
                    "artifact_type": artifact_type,
                },
            )
            return

        system_prompt = f"""
You are the BLAIQ Visual Designer (Van Gogh). Your mission is to transform a detailed Visual Specification into a high-fidelity, interactive digital experience.

### BRAND DNA (MANDATORY DESIGN SYSTEM):
{brand_dna}

### EXECUTION PRIORITY:
- If the upstream render plan says `render_mode=generate_image`, do not debate, reinterpret, or redesign it.
- Call `generate_image` first and treat yourself as a direct executor.
- Only use the HTML generation path when the render plan explicitly requires `html`.

### YOUR TASKS:
1. **MULTI-SLIDE UI/UX**: If the spec defines multiple slides/sections, you MUST write a React component that includes navigation (tabs, arrows, or scroll-spy) to experience every slide.
2. **IMAGE PROMPTS**: Generate a high-fidelity prompt for EVERY major section or slide. Ensure visual consistency across all prompts.
3. **GLASSMORPHISM**: Use Tailwind CSS to implement the 'Glassmorphism' style (backdrop-blur, semi-transparent borders, vibrant gradients) as defined in the Brand DNA.
4. **COMPONENT ARCHITECTURE**: The primary deliverable must be previewable HTML that can render directly in an iframe. Optional CSS can be returned separately.
5. **MEDIA TOOLS**: Use `generate_image` when the brief calls for actual still-image generation. Use `generate_video` when the brief calls for motion, a trailer, or video output. `generate_image` supports both prompt-only and prompt+reference-image generation.

### OUTPUT FORMAT:
You MUST output a valid JSON object:
{{
  "image_prompts": [
    {{"id": "slide_1", "prompt": "..."}},
    {{"id": "slide_2", "prompt": "..."}}
  ],
    "html": "<main>...</main>",
    "css": ".artifact { ... }",
    "design_rationale": "Explanation of how the UX flows and how the Brand DNA was applied.",
    "generated_media": {{
        "images": [],
        "videos": []
    }}
}}

Rules:
- Return JSON only.
- `html` must be directly renderable HTML. Do NOT return JSX, TSX, React components, or markdown fences.
- `css` is optional, but if included it must be plain CSS without fences.
- If tool calls are not needed, keep `generated_media.images` and `generated_media.videos` as empty arrays.
- If the specification asks for a video trailer or motion concept, call `generate_video` and include its returned metadata under `generated_media.videos`.
"""
        agent = self._create_runtime_agent(
            name="VanGoghRuntime",
            sys_prompt=system_prompt,
            role="vangogh",
            toolkit=self.build_toolkit(),
            max_iters=8,
        )
        compact_visual_spec = _build_compact_visual_spec(render_plan, visual_spec)
        response = await agent.reply(Msg("user", f"VISUAL SPECIFICATION:\n{compact_visual_spec}", "user"))
        content = _extract_response_text(response)
            
        # Parse the JSON response
        try:
            data = _extract_json_object(content)
            if data is None:
                raise ValueError("No valid JSON object found in model output")
            logger.info("VanGogh successfully parsed design JSON")
            preview_html = _build_preview_html(data)
            normalized_media = _normalize_media_items(data.get("generated_media") if isinstance(data, dict) else {})
            media_items = _merge_media_items(normalized_media)
            artifact_type = metadata.get("artifact_type") or (render_plan.get("artifact_type") if render_plan else None)
            yield Msg(
                name="VanGogh",
                content=json.dumps(
                    _build_visual_render_result(
                        artifact_type=artifact_type,
                        title=str(data.get("title") or "Visual Artifact Ready").strip() or "Visual Artifact Ready",
                        render_mode="html",
                        html=preview_html,
                        css=_strip_code_fences(str(data.get("css") or "")),
                        media=media_items,
                        layout_hints={"layout": "grid", "hero_item_id": None},
                        storyboard_markdown=str(render_plan.get("storyboard_markdown") or "") if render_plan else "",
                        source_render_plan=render_plan,
                        generated_media=data.get("generated_media") if isinstance(data, dict) else None,
                        diagnostics={"tool_path": "llm_html"},
                    ),
                    ensure_ascii=False,
                ),
                role="assistant",
                metadata={
                    "kind": "design_spec",
                    "artifact_type": artifact_type,
                }
            )
            return # Ensure we never yield twice
        except Exception as e:
            logger.error("VanGogh JSON parse failed: %s content_preview=%s", e, _truncate_for_log(content, 320))
            # Fallback to a readable render-plan preview instead of raw model text.
            yield Msg(
                name="VanGogh",
                content=json.dumps(
                    _build_visual_render_result(
                        artifact_type=metadata.get("artifact_type") or (render_plan.get("artifact_type") if render_plan else None),
                        title="Visual Artifact Ready",
                        render_mode="html",
                        html=_build_render_plan_preview_html(render_plan, _strip_code_fences(content)),
                        css="",
                        media=[],
                        layout_hints={"layout": "grid", "hero_item_id": None},
                        storyboard_markdown=str(render_plan.get("storyboard_markdown") or "") if render_plan else "",
                        source_render_plan=render_plan,
                        diagnostics={"tool_path": "llm_html_fallback", "error": str(e)},
                    ),
                    ensure_ascii=False,
                ),
                role="assistant",
                metadata={"kind": "design_spec", "artifact_type": metadata.get("artifact_type")}
            )
            return

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("van-gogh-v2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Van Gogh Design Node online.")
    yield
    logger.info("Van Gogh Design Node offline.")

# Initialize the real production app
app = AgentApp(
    app_name="VanGoghV2",
    app_description="Visual Execution & Design Node",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)


@app.query(framework="agentscope")
async def render(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    resolver = LiteLLMModelResolver.from_settings(settings)
    van_gogh = VanGogh(resolver=resolver)

    latest_msg = msgs[-1]
    if isinstance(latest_msg, dict):
        latest_msg = Msg(**latest_msg)

    metadata = latest_msg.metadata or {}
    visual_spec = latest_msg.content
    brand_dna = metadata.get("brand_dna", "")

    logger.info(f"Rendering design for session {request.session_id}")

    await van_gogh._universal_acting_hook(agent_name="VanGogh", phase="rendering")

    async for item in van_gogh.render_artifact_internal(
        visual_spec=visual_spec,
        brand_dna=brand_dna,
        metadata=metadata,
    ):
        yield item, True

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8096)
