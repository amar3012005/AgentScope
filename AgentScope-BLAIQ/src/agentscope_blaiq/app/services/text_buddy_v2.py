# -*- coding: utf-8 -*-
"""
TextBuddy V2 — Single ReAct agent that:
        1. Lists registered task skills (brand_tone excluded from list — it is always global).
  2. Reasons about user prompt to pick the best task skill.
  3. Reads that skill's SKILL.md.
        4. Writes the final artifact following chosen skill + global brand_tone.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
import json
import re

from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock
from agentscope.pipeline import stream_printing_messages
from agentscope.tool import ToolResponse, Toolkit

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
        def __init__(self, *_, app_name=None, app_description=None, a2a_config=None, **kwargs):  # noqa: ARG002  # a2a_config unused in fallback
            super().__init__(title=app_name, description=app_description, **kwargs)
        def query(self, *args, **kwargs):
            return lambda fn: fn

    # Create a module-level app instance for decorators to use
    _fallback_app = AgentApp(app_name="agentscope", app_description="AgentScope Runtime")
    app = _fallback_app

from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.agent_base import BaseAgent

logger = logging.getLogger("text-buddy-v2")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)
logger.propagate = False

# ─── Skill discovery ──────────────────────────────────────────────────────────

# Agent-specific task skills root — only text_buddy skills are visible here.
_TASK_SKILLS_ROOT: Path = Path(__file__).resolve().parents[2] / "skills" / "text_buddy"

# Global skills root (brand_tone lives here — injected into system prompt, not listed as a task)
_GLOBAL_SKILLS_ROOT: Path = Path(__file__).resolve().parents[2] / "skills"


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
    """Discover text_buddy-specific task skills recursively from skills/text_buddy/."""
    catalog: dict[str, dict] = {}
    if not _TASK_SKILLS_ROOT.exists():
        logger.warning("[TEXTBUDDY] Task skills directory missing: %s", _TASK_SKILLS_ROOT)
        return catalog
        
    # Recursive discovery using rglob for SKILL.md
    for skill_md in sorted(_TASK_SKILLS_ROOT.rglob("SKILL.md"), key=lambda p: p.parent.name.lower()):
        child = skill_md.parent
        fm = _parse_frontmatter(skill_md)
        catalog[child.name] = {
            "name": fm.get("name", child.name),
            "description": fm.get("description", ""),
            "dir": str(child),
            "path": str(skill_md),
        }
    return catalog


def _extract_labeled_section(content: str, labels: list[str]) -> str:
    if not content.strip():
        return ""
    escaped = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:#+\s*)?(?:\d+\.\s*)?(?:{escaped})\s*:?\s*\n(.*?)(?=\n\s*(?:#+\s*)?(?:\d+\.\s*)?(?:{escaped}|\w[^\n]*?:)\s*:?\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(content)
    return match.group(1).strip() if match else ""


def _cleanup_email_artifact(content: str) -> str:
    text = content.strip()
    if not text:
        return text

    if not re.search(r"(?:subject line|greeting|opening line|body paragraphs|call to action|sign-off|signoff)", text, re.IGNORECASE):
        return text

    title = ""
    title_match = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()

    subject = _extract_labeled_section(text, ["Subject Line", "Subject"])
    greeting = _extract_labeled_section(text, ["Greeting", "Salutation"])
    opening = _extract_labeled_section(text, ["Opening Line", "Opening"])
    body = _extract_labeled_section(text, ["Body Paragraphs", "Body", "Core Value", "Value Proposition"])
    cta = _extract_labeled_section(text, ["Call to Action", "CTA", "Next Step"])
    signoff = _extract_labeled_section(text, ["Sign-Off", "Signoff", "Closing"])

    composed: list[str] = []
    if title:
        composed.append(f"# {title}")
    if subject:
        composed.append(f"**Subject:** {subject.splitlines()[0].strip()}")
    if greeting:
        composed.append(greeting)
    if opening:
        composed.append(opening)
    if body:
        composed.append(body)
    if cta:
        composed.append(cta)
    if signoff:
        composed.append(signoff)

    cleaned = "\n\n".join(part.strip() for part in composed if part and part.strip())
    return cleaned or text


def _load_brand_tone_skill() -> str:
    brand_tone_path = _GLOBAL_SKILLS_ROOT / "brand_tone" / "SKILL.md"
    if not brand_tone_path.exists():
        raise RuntimeError("brand_tone global skill is required for TextBuddy output")
    content = brand_tone_path.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError("brand_tone global skill is empty")
    return content


def _select_skill_without_model(
    task_catalog: dict[str, dict],
    request_text: str,
    artifact_type: str,
) -> str:
    """Deterministic fallback when the selector LLM is unavailable.

    Preference order matches the prompt contract: explicit user format first,
    then the artifact_type hint, then a stable catalog fallback.
    """
    if not task_catalog:
        return ""

    normalized_request = (request_text or "").lower()
    normalized_hint = (artifact_type or "").lower()

    direct_aliases = {
        "email": ["email", "e-mail", "mail"],
        "professional_email": ["professional email"],
        "report": ["report"],
        "proposal": ["proposal"],
        "invoice": ["invoice"],
        "letter": ["letter"],
        "memo": ["memo", "memorandum"],
        "social_post": ["social post", "linkedin post", "instagram post", "x post", "tweet", "thread"],
        "case_study": ["case study"],
    }

    def score_candidate(candidate_key: str, candidate_meta: dict, source_text: str, source_weight: int) -> int:
        haystack = " ".join(
            [
                candidate_key.lower(),
                str(candidate_meta.get("name", "")).lower(),
                str(candidate_meta.get("description", "")).lower(),
            ]
        )
        score = 0
        for alias in direct_aliases.get(candidate_key, []):
            if alias in source_text:
                score += source_weight + len(alias)
        tokens = set(re.findall(r"[a-z0-9_]+", haystack))
        for token in tokens:
            if len(token) > 3 and token in source_text:
                score += max(source_weight - 2, 1)
        return score

    best_key = ""
    best_score = -1

    for key, meta in task_catalog.items():
        request_score = score_candidate(key, meta, normalized_request, 10)
        hint_score = score_candidate(key, meta, normalized_hint, 6)
        score = request_score + hint_score
        if score > best_score:
            best_score = score
            best_key = key

    if best_key and best_score > 0:
        return best_key

    preferred_defaults = ["email", "professional_email", "report", "proposal"]
    for candidate in preferred_defaults:
        if candidate in task_catalog:
            return candidate

    return next(iter(task_catalog), "")


# ─── pre_print hook factory (AgentScope native) ───────────────────────────────
# Tags every printed message with metadata so the AaaS layer routes it as live
# agent-thought telemetry (frontend AgentCard subscribes to this).
# Reference: AgentScope docs — Hooking Functions / pre_print

def _make_text_buddy_print_hook(phase_label: str):
    def _hook(self, kwargs):  # noqa: ANN001
        msg = kwargs.get("msg")
        if msg is None:
            return None
        meta = dict(msg.metadata or {})
        meta.setdefault("kind", "agent_thought")
        meta["phase"] = phase_label
        meta["agent_name"] = getattr(self, "name", "TextBuddy")
        msg.metadata = meta
        logger.info("[PREPRINT_HOOK] agent=%s tagged kind=agent_thought content_len=%d",
                    meta["agent_name"],
                    len(msg.get_text_content() or "") if hasattr(msg, "get_text_content") else 0)
        return None
    return _hook


def _extract_response_text(response: object) -> str:
    text_content: object = ""

    def _coerce_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for block in value:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    parts.append(str(block.get("text") or block.get("content") or ""))
                elif hasattr(block, "text"):
                    parts.append(str(getattr(block, "text") or ""))
                else:
                    parts.append(str(block))
            return " ".join(part for part in parts if part).strip()
        if isinstance(value, dict):
            return str(value.get("text") or value.get("content") or "")
        return str(value)

    try:
        if hasattr(response, "text") and getattr(response, "text"):
            text_content = _coerce_text(getattr(response, "text"))
        elif hasattr(response, "content") and getattr(response, "content"):
            content = getattr(response, "content")
            if isinstance(content, str):
                text_content = content
            else:
                text_content = _coerce_text(content)
    except (AttributeError, KeyError, TypeError):
        text_content = ""

    if text_content:
        return _coerce_text(text_content)

    if isinstance(response, dict):
        return _coerce_text(
            response.get("text")
            or response.get("choices", [{}])[0].get("message", {}).get("content", "")
            or response.get("content", "")
            or ""
        )

    return _coerce_text(response)


# ─── TextBuddy core ───────────────────────────────────────────────────────────

class TextBuddy(BaseAgent):
    def __init__(self, resolver: LiteLLMModelResolver):
        super().__init__(
            name="TextBuddy",
            role="text_buddy",
            sys_prompt="You are TextBuddy — BLAIQ's professional content writer.",
            resolver=resolver
        )

    async def generate_artifact(
        self,
        request_text: str,
        artifact_type: str,
        evidence_brief: str = "",
        hitl_feedback: str = "",
    ) -> AsyncGenerator[Msg, None]:

        task_catalog = _build_task_skill_catalog()
        logger.info("[TEXTBUDDY] Discovered %d task skills: %s", len(task_catalog), list(task_catalog.keys()))
        brand_tone_content = _load_brand_tone_skill()

        # ── Phase 1: Bounded skill selection (single model call, no ReAct loop) ──
        yield Msg(
            name="TextBuddySkillSelector",
            content="Selecting the best artifact structure...",
            role="assistant",
            metadata={"kind": "agent_thought", "phase": "text_buddy", "agent_name": "TextBuddySkillSelector"},
        )

        selector_model = self.resolver.build_agentscope_model("skill_selector")
        # Lightweight catalog: key + name + description only (no full markdown)
        skill_catalog_text = "\n".join(
            f"- key={key}; name={meta['name']}; description={meta['description']}"
            for key, meta in sorted(task_catalog.items())
        ) or "- key=report; name=report; description=General report output"

        selector_messages = [
            {
                "name": "system",
                "role": "system",
                "content": (
                    "You are the Skill Selector for BLAIQ TextBuddy. "
                    "The brand tone below is always active and must be respected when choosing a skill:\n\n"
                    f"{brand_tone_content}\n\n"
                    "Pick exactly one skill key based on the user's requested output format. "
                    "CRITICAL RULES (in priority order):\n"
                    "1. USER REQUEST FIRST: If the user explicitly mentions a format (email, report, proposal, letter, memo, social post, etc.), match that skill. This ALWAYS overrides any artifact_type hint.\n"
                    "2. ARTIFACT_TYPE HINT: Only use the artifact_type hint if the user request is ambiguous or doesn't mention a format.\n"
                    "3. NEVER override an explicit user format request with a hint.\n"
                    "Return JSON only with keys selected_skill and reason."
                ),
            },
            {
                "name": "user",
                "role": "user",
                "content": (
                    f"artifact_type hint: {artifact_type or '(none provided)'}\n"
                    f"user request: {request_text}\n\n"
                    f"available skills:\n{skill_catalog_text}\n\n"
                    "Choose one skill key. Return JSON only like "
                    "{\"selected_skill\":\"email\",\"reason\":\"user explicitly requested email format\"}."
                ),
            },
        ]

        selector_text = ""
        selected_skill_key = ""
        try:
            selector_response = await selector_model(selector_messages)
            selector_text = _extract_response_text(selector_response)
            if isinstance(selector_text, list):
                selector_text = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in selector_text
                )

            match = re.search(r'\{[^{}]*"selected_skill"[^{}]*\}', selector_text)
            if match:
                parsed = json.loads(match.group())
                selected_skill_key = parsed.get("selected_skill", "").strip()
                logger.info("[TEXTBUDDY SELECTOR] selected=%s reason=%s", selected_skill_key, parsed.get("reason", ""))
        except Exception as exc:
            logger.warning("[TEXTBUDDY SELECTOR] model unavailable, using local fallback: %s", exc)
            selected_skill_key = _select_skill_without_model(task_catalog, request_text, artifact_type)

        if not selected_skill_key or selected_skill_key not in task_catalog:
            selected_skill_key = _select_skill_without_model(task_catalog, request_text, artifact_type)
            logger.warning("[TEXTBUDDY SELECTOR] fallback to deterministic skill: %s", selected_skill_key)

        # ── Phase 2: Writer (direct generation, no ReAct loop) ──
        # Load only the essential sections of the selected skill (not full markdown bloat)
        selected_skill_content = ""
        if selected_skill_key and selected_skill_key in task_catalog:
            try:
                skill_path = Path(task_catalog[selected_skill_key]["path"])
                selected_skill_content = skill_path.read_text(encoding="utf-8")
                logger.info("[TEXTBUDDY WRITER] loaded skill: %s", selected_skill_key)
            except Exception:
                logger.warning("[TEXTBUDDY WRITER] Failed to load skill: %s", selected_skill_key)

        writer_sys_prompt = f"""You are TEXTBUDDY — BLAIQ's professional content writer.

## MANDATORY RULES

### 1. Brand Tone (dynamically loaded — NON-NEGOTIABLE)
The following brand guidelines define the tenant's voice. You MUST follow them strictly and apply them in the final copy, not just the reasoning:

{brand_tone_content}

### 2. Task Skill Structure — STRICT COMPLIANCE REQUIRED
You MUST follow the chosen skill blueprint ({selected_skill_key}) section by section, in the exact order specified.
Treat the skill blueprint as an INTERNAL checklist for what the final artifact must contain.
Do NOT render the blueprint labels literally unless the artifact type naturally requires them.

Examples:
- For emails: output the finished email only, ready to copy-paste and send. Do NOT print headings like "Subject Line", "Greeting", or "Body Paragraphs".
- For social posts: output the post itself, not a labeled scaffold.
- For letters and memos: output the finished document, not a training outline.
- For reports and proposals: use human editorial headings only where they help the reader, not template labels.

Do NOT improvise the required content, skip sections, or reorder them:

{selected_skill_content}

### 3. Markdown Formatting — FRONTEND RENDERING REQUIREMENTS
Your output will be rendered as markdown in a React frontend. Follow these rules strictly:

- Use H1 (#) only when the artifact truly needs a visible title.
- Do NOT add markdown headings to emails, letters, short memos, or social posts unless the user explicitly asked for a titled document.
- For email artifacts, the visible result should read like a final email, not a template.
- For report/proposal-style artifacts, use concise editorial headings rather than blueprint labels.
- Use **bold** for key figures, names, deadlines, and conclusions.
- Use *italic* sparingly — only for emphasis or foreign terms.
- Use tables (markdown pipe tables) for ALL structured data: pricing, timelines, comparisons, deliverables.
- Use numbered lists for ordered sequences (steps, findings, recommendations).
- Use bullet points for unordered lists (features, options, action items).
- Use `inline code` for technical terms, IDs, or code references.
- Use blockquotes (>) for callouts: [!NOTE], [!TIP], [!WARNING].
- Use horizontal rules (---) to separate major sections when appropriate.
- NEVER use HTML tags — pure markdown only.
- NEVER use code blocks for non-code content.

### 4. Output Hygiene — ZERO TOLERANCE
- Return ONLY the final artifact. NO preamble, NO explanation, NO meta-commentary.
- Do NOT write "Here is your email:" or "Below is the report:" — start directly with the content.
- Do NOT add "Let me know if you need changes" or similar sign-offs.
- If research evidence is provided, use it as your factual foundation.
- If no evidence is provided, generate professional content based on the request and skill blueprint.
- Even when evidence is missing, the writing must still reflect the loaded brand tone. Do not fall back to generic copy.
- NEVER fabricate statistics, names, dates, or company details not present in evidence or HITL.
- If critical data is missing, use a placeholder like [TBD] or [To be confirmed] rather than inventing figures.

### 5. Multi-Artifact Requests
- If the user requests a combined document (e.g., "proposal with invoice"), generate BOTH sections in one output.
- Use a horizontal rule (---) to separate distinct artifact types within the same output.
- Each section must follow its respective skill blueprint completely.
- The proposal section follows the proposal skill structure.
- The invoice section follows the invoice skill structure (with line items table, totals, payment terms).
- Do NOT merge financial data into narrative prose — always use tables for pricing/invoicing.
"""

        # Evidence + HITL injected directly into the user message (not system prompt)
        # Build a structured user message that grounds the generation
        user_parts = []

        if evidence_brief:
            user_parts.append(
                "## RESEARCH EVIDENCE (ground truth — use verbatim facts only, cite as [source:ID]):\n"
                + evidence_brief
            )

        user_parts.append(f"## MISSION:\n{request_text}")

        if hitl_feedback:
            user_parts.append(
                "## FEEDBACK TO APPLY (revise your output to address every point):\n"
                + hitl_feedback
            )

        writer_user_msg = "\n\n".join(user_parts)

        logger.info("[TEXTBUDDY WRITER] Starting generation. skill=%s evidence_len=%d", selected_skill_key, len(evidence_brief))

        # Direct model call for generation (no ReAct loop)
        writer_model = self.resolver.build_agentscope_model(self.role)
        writer_messages = [
            {"role": "system", "content": writer_sys_prompt},
            {"role": "user", "content": writer_user_msg},
        ]
        
        # Single direct call for generation
        writer_response = await writer_model(writer_messages)
        
        writer_text = _extract_response_text(writer_response)
        
        # Yield the complete thought for frontend activity card
        yield Msg(
            name="TextBuddyWriter",
            content=writer_text,
            role="assistant",
            metadata={"kind": "agent_thought", "phase": "text_buddy", "agent_name": "TextBuddyWriter"},
        )

        content = str(writer_text or "").strip()
        if selected_skill_key in {"email", "professional_email"}:
            content = _cleanup_email_artifact(content)
        logger.info("[TEXTBUDDY WRITER] Done. length=%d", len(content))

        yield Msg(
            name="TextBuddy",
            content=content,
            role="assistant",
            metadata={"kind": "text_artifact", "artifact_type": artifact_type},
        )


# ─── AaaS app ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    logger.info("TextBuddy V2 (Single-ReAct | Skill-Reasoning) online.")
    yield
    logger.info("TextBuddy V2 offline.")

# Initialize the real production app instance
app = AgentApp(
    app_name="TextBuddyV2",
    app_description="Single ReAct agent: skill reasoning → brand-aligned artifact generation",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0"),
)


@app.query(framework="agentscope")
async def process(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    resolver = LiteLLMModelResolver.from_settings(settings)
    buddy = TextBuddy(resolver=resolver)

    # AaaS may drop message-level metadata — scan ALL msgs, last non-empty value wins
    artifact_type = ""
    evidence_brief = ""
    hitl_feedback = ""
    request_text = ""

    for raw in msgs:
        m = Msg(**raw) if isinstance(raw, dict) else raw
        text = m.get_text_content() or ""
        if text:
            request_text = text
        meta = m.metadata or {}
        if meta.get("artifact_type"):
            artifact_type = meta["artifact_type"]
        if meta.get("evidence_brief"):
            evidence_brief = meta["evidence_brief"]
        if meta.get("hitl_feedback"):
            hitl_feedback = meta["hitl_feedback"]

    if not artifact_type:
        artifact_type = "general"

    logger.info("[TEXTBUDDY REQUEST] type=%s session=%s", artifact_type, request.session_id)

    async for item in buddy.generate_artifact(
        request_text=request_text,
        artifact_type=artifact_type,
        evidence_brief=evidence_brief,
        hitl_feedback=hitl_feedback,
    ):
        # Only the final artifact (kind=text_artifact) marks the stream as last.
        # Intermediate prints (kind=agent_thought from pre_print hook) stream live.
        meta = item.metadata or {}
        is_last = meta.get("kind") == "text_artifact"
        logger.info(
            "[TEXTBUDDY YIELD] kind=%s is_last=%s len=%d",
            meta.get("kind"), is_last, len(item.content) if item.content else 0,
        )
        yield item, is_last


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
