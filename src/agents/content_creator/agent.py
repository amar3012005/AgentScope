import asyncio
import json
import logging
import os
import re
import socket
from pathlib import Path
from contextlib import suppress
from typing import Any, Dict, List, Optional

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from utils.logging_utils import configure_service_logging, log_flow

# Import skill loader
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts.prompt_loader import PromptLoader

from agents.content_creator.artifact_types.definitions import get_registry
from agents.content_creator.blueprints.registry import get_blueprint_registry
from agents.content_creator.section_generator import generate_artifact_sections
from orchestrator.contracts.manifests import ArtifactManifest

configure_service_logging("blaiq-content-agent")
logger = logging.getLogger("blaiq-content-agent")

class ExecuteRequest(BaseModel):
    task: Optional[str] = None
    query: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


app = FastAPI(title="BLAIQ Content Creator Agent", version="1.0.0")

# Enable CORS
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WS_TASK: asyncio.Task | None = None

def _agent_name() -> str:
    return os.getenv("AGENT_NAME", "blaiq-content-agent")

def _core_ws_url() -> str:
    return os.getenv("AGENT_CORE_WS_URL", f"ws://blaiq-core:6000/ws/agents/{_agent_name()}")

def _core_http_url() -> str:
    return os.getenv("AGENT_CORE_HTTP_URL", "http://blaiq-core:6000")

def _get_llm_model(task_type: str = "design") -> str:
    """
    Model selection based on task type:
    - design: Claude 4.6 Sonnet for high-quality HTML/Tailwind generation
    - analysis: gpt-4o-mini for fast gap analysis and strategy
    """
    if task_type == "design":
        # Use Claude only for final artifact synthesis.
        return os.getenv("CONTENT_DESIGN_MODEL", "vertex_ai/claude-sonnet-4-6@default")
    elif task_type == "analysis":
        # Fast planning/extraction model.
        return os.getenv("CONTENT_ANALYSIS_MODEL", "nebius/Qwen/Qwen3-32B-fast")
    else:
        return os.getenv("OPENAI_MODEL", "nebius/Qwen/Qwen3-32B-fast")


def _get_gap_analysis_model() -> str:
    """Fast model for strategic gap analysis."""
    return os.getenv("GAP_ANALYSIS_MODEL", "nebius/Qwen/Qwen3-32B-fast")

def _get_openai_url() -> str:
    return os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")

def _get_openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")

# ----------------------------------------------------------------------------
# 1. STRATEGIC INTERVIEW PROMPTS (Gap Analysis)
# ----------------------------------------------------------------------------
MARKETING_CHECKLIST = [
    "Clear Value Proposition (Why does the user care?)",
    "Defined Target Audience (Who is this for?)",
    "Core Problem Addressed (What pain point does this solve?)",
    "Strategic Solution (How does this fix the problem?)",
    "Key Evidence/Metrics (Proof that it works)"
]

STRATEGIC_INTERVIEW_SYSTEM_PROMPT = """You are the BLAIQ Content Creator Agent, acting as the Strategic Creative Director.
Your job is to analyze the provided raw project context against a strict Marketing Checklist AND align it with our Brand DNA.

Market Checklist:
{checklist}

Brand DNA (Aesthetic and Voice Guidelines):
{brand_dna}

Your goal:
1. Compare Context against the Checklist.
2. Ensure the tone and strategic direction align with the Brand DNA.
3. Determine if current data is sufficient to create a 'DaVinci AI' quality asset, OR if critical gaps exist.

DECISION CRITERIA:
Set "gaps_found" to TRUE only if:
- The user request is vague or unclear (e.g., "create something" without specifics)
- Critical information like target audience, value proposition, or key metrics is completely missing
- The Brand DNA requirements cannot be met with available context

Set "gaps_found" to FALSE if:
- The user has provided a clear, specific request (e.g., "Create a LinkedIn post about our new AI feature targeting CTOs")
- Even if some details are missing, you can infer reasonable defaults from the context
- The request is actionable with the available information

CRITICAL formatting:
1. If gaps_found is TRUE, generate EXACTLY 4 strategic questions targeting the missing information.
2. Questions must be directly related to the USER REQUEST.
3. For BLAIQ Core NotebookLM source-pack requests, the 4 questions must cover:
   - current architecture/documents to include
   - evidence flow / proof sources
   - GraphRAG flow / retrieval behavior
   - content generator agent behavior and output
3. If gaps_found is FALSE, set questions to an empty array [] and provide a brief confirmation in analysis.

Output in STRICT JSON:
{{
  "gaps_found": true or false,
  "analysis": "Brief explanation - either what's missing OR confirmation that context is sufficient",
  "questions": ["Q1", "Q2", "Q3", "Q4"] or []
}}
"""

CONTEXTUAL_HITL_SYSTEM_PROMPT = """You are the BLAIQ Content Creator Agent, preparing a mandatory human-in-the-loop clarification step before visual synthesis.

You will receive:
- the user request
- the current evidence summary from GraphRAG

Your job:
1. Read the evidence and identify what is already known.
2. Ask exactly 4 high-value clarification questions that are still needed to turn the evidence into a strong final artifact.
3. Questions must be specific to the current evidence and request.
4. Avoid generic boilerplate unless the evidence truly leaves that area unresolved.

Requirements:
- Return STRICT JSON
- Questions must be concise, concrete, and artifact-oriented
- Prefer questions about emphasis, comparison framing, audience, narrative angle, evidence selection, and design direction
- If the evidence is about sales/revenue, ask about which metrics, segments, comparisons, or storyline to highlight

Output:
{
  "analysis": "1-2 sentence summary of what the evidence already covers and what still needs direction",
  "questions": ["Q1", "Q2", "Q3", "Q4"]
}
"""

CONTENT_DIRECTOR_SYSTEM_PROMPT = """You are the BLAIQ Content Director.
Plan multi-page artifact composition before rendering starts.

Return STRICT JSON:
{
  "overall_strategy": "short strategic summary",
  "pages": [
    {
      "page_number": 1,
      "section_id": "hero",
      "objective": "what this page must achieve",
      "evidence_focus": ["metric/comparison/proof to emphasize"],
      "layout_direction": "short layout direction",
      "copy_tone": "tone cue",
      "must_include": ["critical fields or facts"]
    }
  ]
}

Rules:
- One plan entry per section/page in order.
- Keep each field concise and actionable.
- Ground `evidence_focus` and `must_include` in available evidence and user answers.
- No markdown, no prose outside JSON.
"""


BRAND_DNA: Dict[str, Any] = {}
BRAND_DNA_PATH = Path(os.getenv("BRAND_DNA_PATH", "/app/brand_dna/davinci_ai.json"))

# Initialize skill loader
skill_loader: Optional[PromptLoader] = None

def load_brand_dna():
    global BRAND_DNA
    log_flow(logger, "brand_dna_load_start", path=str(BRAND_DNA_PATH))
    if BRAND_DNA_PATH.exists():
        try:
            with open(BRAND_DNA_PATH, 'r') as f:
                BRAND_DNA = json.load(f)
            log_flow(logger, "brand_dna_load_complete", path=str(BRAND_DNA_PATH), status="ok")
        except json.JSONDecodeError as e:
            log_flow(logger, "brand_dna_load_error", level="error", path=str(BRAND_DNA_PATH), error=str(e))
            BRAND_DNA = {"_error": f"Invalid JSON in Brand DNA file: {e}"}
        except Exception as e:
            log_flow(logger, "brand_dna_load_error", level="error", path=str(BRAND_DNA_PATH), error=str(e))
            BRAND_DNA = {"_error": str(e)}
    else:
        log_flow(logger, "brand_dna_missing", level="warning", path=str(BRAND_DNA_PATH))
        BRAND_DNA = {"_warning": f"Brand DNA file not found at {BRAND_DNA_PATH}"}

def initialize_skill_loader():
    """Initialize the skill loader with proper paths and validation."""
    global skill_loader

    # Get the base directory (src)
    base_dir = Path(__file__).parent.parent.parent
    skills_dir = base_dir / "skills"
    prompt_dir = base_dir / "prompts" / "xml"

    log_flow(logger, "skill_loader_init_start", skills_dir=str(skills_dir), prompt_dir=str(prompt_dir))

    # Validate directories exist
    if not skills_dir.exists():
        log_flow(logger, "skill_dir_missing", level="warning", path=str(skills_dir))
        try:
            skills_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_flow(logger, "skill_dir_create_error", level="error", path=str(skills_dir), error=str(e))

    if not prompt_dir.exists():
        log_flow(logger, "prompt_dir_missing", level="warning", path=str(prompt_dir))

    try:
        skill_loader = PromptLoader(
            prompt_dir=str(prompt_dir),
            skills_dir=str(skills_dir)
        )
        available_skills = skill_loader.list_available_skills()
        log_flow(logger, "skill_loader_init_complete", available_skills=available_skills)
    except Exception as e:
        log_flow(logger, "skill_loader_init_error", level="error", error=str(e))
        skill_loader = None

load_brand_dna()
initialize_skill_loader()

async def fetch_graphrag_context(
    query: str,
    session_id: Optional[str] = None,
    tenant_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pull project context directly from the GraphRAG service."""
    # Call GraphRAG service directly (not through orchestrator)
    graphrag_url = os.getenv("GRAPHRAG_DIRECT_URL", "http://blaiq-graph-rag:6001")
    url = f"{graphrag_url}/query/graphrag"
    tenant_context = tenant_context or {}
    payload = {
        "query": query,
        "include_graph": True,
        "k": 15,
        "use_reranker": False,
        "use_cache": False,
        "session_id": session_id,
        "tenant_id": tenant_context.get("tenant_id"),
        "room_number": tenant_context.get("room_number"),
        "chat_history": tenant_context.get("chat_history"),
        "collection_name": tenant_context.get("collection_name"),
        "qdrant_url": tenant_context.get("qdrant_url"),
        "qdrant_api_key": tenant_context.get("qdrant_api_key"),
        "neo4j_uri": tenant_context.get("neo4j_uri"),
        "neo4j_user": tenant_context.get("neo4j_user"),
        "neo4j_password": tenant_context.get("neo4j_password"),
    }
    headers = {}
    if tenant_context.get("tenant_id"):
        headers["X-Tenant-Id"] = str(tenant_context["tenant_id"])
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            log_flow(logger, "graphrag_context_fetch_start", query_len=len(query), session_id=session_id)
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 404:
                log_flow(logger, "graphrag_context_fetch_empty", level="warning", status_code=404)
                return {"data": {"results": []}, "note": "No chunks found"}
            res.raise_for_status()
            log_flow(logger, "graphrag_context_fetch_complete", status_code=res.status_code)
            return res.json()
        except Exception as e:
            log_flow(logger, "graphrag_context_fetch_error", level="error", error=str(e))
            return {"data": {"results": []}, "error": str(e)}

async def analyze_gaps(graphrag_data: Any, user_request: str, force_questions: bool = False) -> Dict[str, Any]:
    """Perform Chain-of-Thought gap detection via LLM."""
    if not _get_openai_key():
        return {"error": "Missing OPENAI_API_KEY for gap analysis"}

    checklist_str = "\n".join([f"- {item}" for item in MARKETING_CHECKLIST])
    brand_dna_str = json.dumps(BRAND_DNA, indent=2)
    sys_prompt = STRATEGIC_INTERVIEW_SYSTEM_PROMPT.format(checklist=checklist_str, brand_dna=brand_dna_str)
    
    # Extract text content from graphrag_data for cleaner prompt
    context_summary = "No relevant context found."
    if isinstance(graphrag_data, dict) and "data" in graphrag_data:
        # Assuming blaiq-graph-rag response structure
        results = graphrag_data["data"].get("results", [])
        if results:
            context_summary = "\n".join([r.get("content", "") for r in results[:5]])
    elif isinstance(graphrag_data, dict) and graphrag_data.get("evidence_context"):
        context_summary = str(graphrag_data.get("evidence_context", "")).strip() or context_summary

    payload = {
        "model": _get_llm_model("analysis"),  # Fast model for gap analysis
        "messages": [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": (
                    f"USER REQUEST: {user_request}\n"
                    f"FORCE_QUESTIONS: {'true' if force_questions else 'false'}\n\n"
                    "Analyze this user request against the following project context and align with Brand DNA.\n"
                    "If FORCE_QUESTIONS is true, you must return exactly 4 tailored strategic questions even if the context is fairly complete.\n\n"
                    f"{context_summary}"
                ),
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }

    url = f"{_get_openai_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_get_openai_key()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            log_flow(logger, "gap_analysis_start", model=_get_llm_model("analysis"), request_len=len(user_request))
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            content = res.json()["choices"][0]["message"]["content"]
            result = json.loads(content)
            log_flow(logger, "gap_analysis_complete", result=result.get("gaps_found"), question_count=len(result.get("questions", [])))
            
            # If LLM returned empty or missing gaps_found, default to asking questions
            if not result or "gaps_found" not in result:
                log_flow(logger, "gap_analysis_fallback", level="warning")
                result = {
                    "gaps_found": True,
                    "analysis": "Insufficient context to generate a premium DaVinci AI asset.",
                    "questions": [
                        "Which current architecture documents should be included in the NotebookLM source pack?",
                        "What evidence flow or proof sources should the pack explain and preserve?",
                        "How should the GraphRAG flow be described for the core workflow and retrieval path?",
                        "What should the content generator agent do, and what output format should it produce?"
                    ]
                }

            # Ensure exactly 4 questions if gaps are found or the workflow explicitly requires HITL.
            if result.get("gaps_found") or force_questions:
                notebooklm_anchor = any(
                    keyword in user_request.lower()
                    for keyword in ("notebook", "notebooklm", "blaiq core", "source pack", "read me")
                )
                q = result.get("questions", [])
                if not isinstance(q, list) or len(q) == 0:
                    q = [
                        "Which current architecture documents should be included in the NotebookLM source pack?",
                        "What evidence flow or proof sources should the pack explain and preserve?",
                        "How should the GraphRAG flow be described for the core workflow and retrieval path?",
                        "What should the content generator agent do, and what output format should it produce?",
                    ] if notebooklm_anchor else ["Could you clarify the primary value proposition?"]
                elif notebooklm_anchor:
                    q = [
                        "Which current architecture documents should be included in the NotebookLM source pack?",
                        "What evidence flow or proof sources should the pack explain and preserve?",
                        "How should the GraphRAG flow be described for the core workflow and retrieval path?",
                        "What should the content generator agent do, and what output format should it produce?",
                    ]
                while len(q) < 4:
                    q.append("What specific target audience is most critical for this phase?")
                result["gaps_found"] = True
                result["questions"] = q[:4]
            return result
        except Exception as e:
            log_flow(logger, "gap_analysis_error", level="error", error=str(e))
            return {"error": str(e)}


async def generate_contextual_hitl_questions(raw_context: str, user_request: str) -> Dict[str, Any]:
    """Generate evidence-aware HITL questions for mandatory creation workflows."""
    if not _get_openai_key():
        return {"error": "Missing OPENAI_API_KEY for contextual HITL generation"}

    context_excerpt = raw_context[:12000] if raw_context else "No relevant context found."
    payload = {
        "model": _get_llm_model("analysis"),
        "messages": [
            {"role": "system", "content": CONTEXTUAL_HITL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"USER REQUEST: {user_request}\n\n"
                    "CURRENT EVIDENCE:\n"
                    f"{context_excerpt}"
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }

    url = f"{_get_openai_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_get_openai_key()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            log_flow(logger, "contextual_hitl_start", model=_get_llm_model("analysis"), request_len=len(user_request))
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            content = res.json()["choices"][0]["message"]["content"]
            result = json.loads(content)
            questions = result.get("questions", [])
            if not isinstance(questions, list):
                questions = []
            questions = [str(question).strip() for question in questions if str(question).strip()]
            while len(questions) < 4:
                fallback_questions = [
                    "Which sales segments or customer groups should the deck emphasize most?",
                    "Which metrics matter most for this deck: revenue growth, margin, pipeline, retention, or another KPI?",
                    "Should the story focus on year-over-year growth, quarterly momentum, or the most recent period?",
                    "What presentation tone should lead the deck: board-ready, investor-facing, or sales-strategy oriented?",
                ]
                questions.append(fallback_questions[len(questions)])
            result["questions"] = questions[:4]
            result["analysis"] = str(result.get("analysis", "")).strip()
            log_flow(logger, "contextual_hitl_complete", question_count=len(result["questions"]))
            return result
        except Exception as exc:
            log_flow(logger, "contextual_hitl_error", level="error", error=str(exc))
            return {"error": str(exc)}

DATA_SCHEMA_EXTRACTION_PROMPT = """You are the BLAIQ Schema Agent.
Your task is to transform raw project context (GraphRAG findings) and user answers into a strict, structured JSON schema for visual rendering.
Categorize the information into key strategic pillars, intelligence metrics, and project phases.

Output in STRICT JSON with exactly this structure:
{{
  "strategic_pillars": [{{ "title": "...", "description": "..." }}],
  "kpis": [{{ "label": "...", "value": "...", "unit": "..." }}],
  "timeline": [{{ "phase": "...", "status": "..." }}],
  "target_audience": {{ "persona": "...", "pain_points": ["..."] }},
  "vision_statement": "Short compelling vision hook",
  "technical_infrastructure": ["..."]
}}
"""

# ============================================================================
# COMPACT DESIGN SYNTHESIS PROMPT (lean like Claude/Gemini native)
# ============================================================================

DESIGN_SYSTEM_PROMPT = """You are Vangogh, a premium editorial presentation designer.
Generate a SINGLE standalone HTML5 document with luxury monochrome art direction.

DESIGN GOAL:
- The output should feel like a high-end perfume campaign crossed with an investor-grade strategy deck.
- Prioritize restraint, hierarchy, spacing, and premium material feel over noisy dashboards.
- The result must look intentional on first paint: deep black canvas, ivory typography, graphite surfaces, hairline borders, soft spotlight gradients.

HTML TEMPLATE:
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://unpkg.com/@tailwindcss/browser@4"></script>
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Manrope:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Manrope', sans-serif; }
    h1, h2, h3, h4 { font-family: 'Cormorant Garamond', serif; }
    html { scroll-behavior: smooth; }
  </style>
</head>
<body class="min-h-screen bg-[#050505] text-[#F5F5F1]">
  <!-- Build the full artifact here -->
</body>
</html>

NON-NEGOTIABLE RULES:
1. Output only raw HTML. No markdown, no prose, no code fences.
2. Use Tailwind classes, never className.
3. Build a complete polished experience, not a fragment.
4. Use strong visual hierarchy:
   - one commanding hero statement
   - sectional rhythm with generous whitespace
   - premium cards or editorial panels
   - 1-3 key metrics only per section unless data demands more
5. Use subtle motion or reveal styling only when it improves elegance.
6. Avoid bright accent colors unless explicitly in the brand DNA palette.
7. Keep the layout believable for executive review and premium brand presentation.
8. Make every section feel finished: no placeholders, no TODO language, no obvious AI filler.

QUALITY BAR:
- Prefer asymmetry over generic symmetry when it improves composition.
- Use restrained gradients, soft vignettes, spotlight or bloom effects.
- Use editorial typography with large serif headlines and clean sans body copy.
- If data is sparse, lean into narrative framing, not fake metrics.
- Make KPI cards feel luxurious and minimal, not SaaS boilerplate."""


def _html_chunks(html: str, chunk_size: int = 900) -> list[str]:
    if not html:
        return []
    return [html[i:i + chunk_size] for i in range(0, len(html), chunk_size)]


def _build_design_system_prompt(
    skill_names: list[str] | None,
    prompt_loader: PromptLoader | None,
    brand_dna: dict,
    force_brand_constraints: bool = False,
) -> str:
    """Build the design system prompt with dynamic skill and brand DNA injection."""
    base = DESIGN_SYSTEM_PROMPT
    parts = [base]

    # Inject skills if provided
    if skill_names and prompt_loader:
        try:
            skill_xml = prompt_loader.load_skill_stack(skill_names)
            parts.append(f"\n\n<active_skills>\n{skill_xml}\n</active_skills>")
        except Exception as e:
            logger.warning("skill_injection_failed skills=%s err=%s", skill_names, e)

    # Inject brand DNA constraints dynamically
    if brand_dna or force_brand_constraints:
        if not brand_dna:
            brand_dna = {}
        tokens = brand_dna.get("tokens", {})
        typography = brand_dna.get("typography", {})
        parts.append(
            "\n\n<brand_dna_constraints>"
            f"\nPrimary color: {tokens.get('primary', '#FF4500')}"
            f"\nBackground: {tokens.get('background', '#0a0a0a')}"
            f"\nSurface: {tokens.get('surface', '#0d0d0d')}"
            f"\nAccent blue: {tokens.get('accent_blue', '#3b82f6')}"
            f"\nAccent emerald: {tokens.get('accent_emerald', '#10b981')}"
            f"\nHeading font: {typography.get('headings', 'Bebas Neue, sans-serif')}"
            f"\nBody font: {typography.get('body', 'Space Grotesk, monospace')}"
            f"\nFull palette: {json.dumps(tokens)}"
            "\nYou MUST use ONLY these colors. Any hex outside this palette is a violation."
            "\n</brand_dna_constraints>"
        )

    return "\n".join(parts)


async def extract_schema(raw_context: str, answers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Schema Agent: Preprocess raw context into categorized JSON."""
    full_text = raw_context
    if answers:
        full_text += f"\n\nUser Answers: {json.dumps(answers)}"

    # Cap context to avoid oversized prompts
    if len(full_text) > 6000:
        full_text = full_text[:6000] + "\n..."

    payload = {
        "model": _get_llm_model("analysis"),  # Fast model for schema extraction
        "messages": [
            {"role": "system", "content": DATA_SCHEMA_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Extract the strategic schema from this data:\n\n{full_text}"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }

    url = f"{_get_openai_url()}/chat/completions"
    headers = {"Authorization": f"Bearer {_get_openai_key()}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            return json.loads(res.json()["choices"][0]["message"]["content"])
        except Exception as e:
            logger.error(f"Schema extraction failed: {e}")
            return {"error": "extraction_failed", "details": str(e)}


def extract_graphrag_results(graphrag_data: Dict[str, Any]) -> str:
    """Extract text results from GraphRAG response. Handles multiple formats."""
    if not graphrag_data:
        return "No GraphRAG context available."
    
    if isinstance(graphrag_data, dict) and "data" in graphrag_data:
        results = graphrag_data["data"].get("results", [])
        if results:
            return "\n\n".join([r.get("content", "") for r in results])
    
    if isinstance(graphrag_data, dict) and "results" in graphrag_data:
        results = graphrag_data["results"]
        if isinstance(results, list):
            return "\n\n".join([r.get("content", "") if isinstance(r, dict) else str(r) for r in results])
    
    if isinstance(graphrag_data, dict) and "chunks" in graphrag_data:
        chunks = graphrag_data["chunks"]
        if isinstance(chunks, list):
            return "\n\n".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in chunks])
    
    return json.dumps(graphrag_data, indent=2)


async def generate_design(
    structured_data: Dict[str, Any],
    user_request: str,
    skill_names: Optional[List[str]] = None,
    max_tokens: Optional[int] = None,
    force_brand_constraints: bool = False,
) -> str:
    """Generate premium HTML from structured data using a compact prompt."""

    # Build a concise data summary (cap at 3000 chars to keep prompt lean)
    data_summary = json.dumps(structured_data, indent=2)
    if len(data_summary) > 3000:
        data_summary = data_summary[:3000] + "\n..."

    # Build the system prompt with dynamic skill and brand DNA injection
    system_prompt = _build_design_system_prompt(
        skill_names,
        skill_loader,
        BRAND_DNA,
        force_brand_constraints=force_brand_constraints,
    )

    log_flow(logger, "design_generation_start", system_chars=len(system_prompt), data_chars=len(data_summary),
             skill_names=skill_names, max_tokens=max_tokens)

    payload = {
        "model": _get_llm_model("design"),  # Claude 4.6 for high-quality HTML/Tailwind
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Create a premium dark-mode visual for: {user_request}\n\nDATA:\n{data_summary}"}
        ],
        "temperature": 0.4
    }

    # Apply max_tokens constraint if provided (e.g. from MCP envelope)
    if max_tokens:
        payload["max_tokens"] = max_tokens
        log_flow(logger, "design_max_tokens_applied", max_tokens=max_tokens)

    url = f"{_get_openai_url()}/chat/completions"
    headers = {"Authorization": f"Bearer {_get_openai_key()}", "Content-Type": "application/json"}
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            html_content = res.json()["choices"][0]["message"]["content"]
            
            # Strip markdown code blocks
            html_content = re.sub(r'^```html\s*', '', html_content, flags=re.IGNORECASE | re.MULTILINE)
            html_content = re.sub(r'^```\s*', '', html_content, flags=re.MULTILINE)
            html_content = re.sub(r'\s*```$', '', html_content, flags=re.MULTILINE)
            html_content = html_content.strip()
            
            if html_content.lower().startswith('html'):
                html_content = re.sub(r'^html\s*', '', html_content, flags=re.IGNORECASE)
            
            log_flow(logger, "design_generation_complete", html_chars=len(html_content))
            return html_content
        except Exception as e:
            log_flow(logger, "design_generation_error", level="error", error=str(e))
            return f"<div class='p-10 bg-black text-white border border-red-500'>Synthesis Fault: {str(e)}</div>"



async def process_task(task_instruction: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    log_flow(
        logger,
        "task_start",
        task=task_instruction,
        payload_keys=sorted(payload.keys()),
        session_id=payload.get("session_id"),
        orchestrator_request_id=payload.get("orchestrator_request_id"),
        mission_id=payload.get("mcp_mission_id"),
        thread_id=payload.get("mcp_thread_id"),
        has_answers=bool(payload.get("answers")),
    )

    session_id = payload.get("session_id")
    # If this is a follow-up with answers
    user_answers = payload.get("answers")
    require_hitl = bool(payload.get("_require_hitl"))
    # Allow explicit skill override via payload
    explicit_skills = payload.get("skills", None)

    # T1-A: Auto-detect skills from user request when none explicitly provided
    if not explicit_skills and skill_loader:
        try:
            detected_skills = skill_loader.detect_intent_and_load_skills(task_instruction)
            if detected_skills:
                explicit_skills = detected_skills
                logger.info("auto_detected_skills skills=%s for request=%s", detected_skills, task_instruction[:80])
        except Exception as e:
            logger.warning("skill_detection_failed err=%s", e)

    log_flow(logger, "task_inputs", has_answers=bool(user_answers), explicit_skills=explicit_skills)

    # 1. Pull context
    # Multi-agent support: Check if orchestrator already provided helper outputs (GraphRAG)
    helper_outputs = payload.get("strategy_helper_outputs", {})
    graphrag_data = helper_outputs.get("blaiq-graph-rag")
    evidence_context = payload.get("evidence_context")

    if graphrag_data:
        log_flow(logger, "context_source", source="helper", agent="blaiq-graph-rag")
        # Extract results from GraphRAG response
        context_text = extract_graphrag_results(graphrag_data)
        log_flow(logger, "context_ready", source="helper", chars=len(context_text))
    elif isinstance(evidence_context, str) and evidence_context.strip():
        log_flow(logger, "context_source", source="orchestrator_evidence")
        context_text = evidence_context.strip()
        graphrag_data = {"evidence_context": context_text}
        log_flow(logger, "context_ready", source="orchestrator_evidence", chars=len(context_text))
    else:
        log_flow(logger, "context_source", source="direct_graph_rag")
        graphrag_data = await fetch_graphrag_context(task_instruction, session_id, payload)
        context_text = extract_graphrag_results(graphrag_data)

    # Use the extracted text as raw context
    raw_context = context_text

    # 2. If no answers yet, check for gaps
    # T1-C: Skip gap analysis when MCP envelope forces content generation and context exists
    if require_hitl and not user_answers:
        log_flow(logger, "gap_analysis_gate", status="mandatory_hitl")
        analysis = await generate_contextual_hitl_questions(raw_context, task_instruction)
        if "error" in analysis:
            log_flow(logger, "gap_analysis_gate", level="warning", status="mandatory_hitl_fallback")
            analysis = await analyze_gaps(graphrag_data, task_instruction, force_questions=True)
        if "error" in analysis:
            log_flow(logger, "gap_analysis_gate", level="error", status="error")
            return {"status": "error", "message": "Failed gap analysis", "details": analysis}
        questions = analysis.get("questions", [])
        return {
            "status": "blocked_on_user",
            "message": "Strategic Intelligence Audit: before final synthesis, I need a few targeted clarifications based on the current evidence. Please answer these questions to continue.",
            "analysis": analysis.get("analysis"),
            "questions": questions,
            "post_hitl_search_prompt_template": _build_post_hitl_search_prompt_template(
                task_instruction,
                raw_context,
                questions,
            ),
        }
    if payload.get("_force_content") and raw_context and raw_context != "No GraphRAG context available.":
        log_flow(logger, "gap_analysis_skipped", reason="mcp_force_content", context_chars=len(raw_context))
    elif not user_answers:
        log_flow(logger, "gap_analysis_gate", status="start")
        analysis = await analyze_gaps(graphrag_data, task_instruction, force_questions=require_hitl)
        if "error" in analysis:
            log_flow(logger, "gap_analysis_gate", level="error", status="error")
            return {"status": "error", "message": "Failed gap analysis", "details": analysis}

        if analysis.get("gaps_found") or require_hitl:
            blocked_message = (
                "Strategic Intelligence Audit: I have identified critical gaps that prevent us from achieving a DaVinci AI premium alignment. Please guide the creative direction by answering these questions."
                if analysis.get("gaps_found") and not require_hitl
                else "Strategic Intelligence Audit: before final synthesis, I need a few targeted clarifications based on the current evidence. Please answer these questions to continue."
            )
            return {
                "status": "blocked_on_user",
                "message": blocked_message,
                "analysis": analysis.get("analysis"),
                "questions": analysis.get("questions"),
                "post_hitl_search_prompt_template": _build_post_hitl_search_prompt_template(
                    task_instruction,
                    raw_context,
                    analysis.get("questions", []),
                ),
            }

    log_flow(logger, "design_pipeline_start", stage="schema_extraction")
    # 3. Extract Schema (or use override)
    schema_override = payload.get("schema_override")
    if schema_override:
        if not isinstance(schema_override, dict):
            log_flow(logger, "schema_override_error", level="error", reason="invalid_schema_override")
            return {"status": "error", "message": "Invalid schema override", "details": schema_override}
        structured_data = schema_override
        log_flow(logger, "schema_override_applied", keys=sorted(schema_override.keys()))
    else:
        structured_data = await extract_schema(raw_context, user_answers)
        if "error" in structured_data:
            log_flow(logger, "design_pipeline_error", level="error", stage="schema_extraction")
            return {"status": "error", "message": "Failed schema extraction", "details": structured_data}

    # 4. Generate the design using Visual Synthesis with skill injection
    log_flow(logger, "design_pipeline_start", stage="html_generation")
    html = await generate_design(
        structured_data=structured_data,
        user_request=task_instruction,
        skill_names=explicit_skills,
        max_tokens=payload.get("_max_tokens"),
        force_brand_constraints=payload.get("_force_brand_constraints", False),
    )

    return {
        "status": "success",
        "message": "DaVinci Visual Synthesis complete.",
        "html_artifact": html,
        "schema_data": structured_data,
        "skills_used": explicit_skills or [],
        "brand_dna_version": str(BRAND_DNA.get("version", "unknown")),
    }

async def process_task_v2(
    user_request: str,
    payload: dict,
    brand_dna: dict,
    session_id: str = "",
    mcp_env: dict | None = None,
) -> dict:
    """V2 pipeline: section-by-section extraction + template rendering.

    Uses the artifact type registry to determine sections, extracts
    structured data per section via LLM, and renders deterministic
    HTML via Jinja2 templates.
    """
    # Reuse existing context retrieval
    evidence_context = payload.get("evidence_context", "")
    user_answers = payload.get("answers")
    require_hitl = bool(payload.get("_require_hitl"))

    if not evidence_context:
        # Try to fetch from GraphRAG (same as V1)
        try:
            graphrag_results = await fetch_graphrag_context(user_request, session_id, payload)
            evidence_context = extract_graphrag_results(graphrag_results)
        except Exception as exc:
            logger.warning("v2_graphrag_fallback_error err=%s", exc)
            evidence_context = ""

    if require_hitl and not user_answers:
        log_flow(logger, "v2_gap_analysis_gate", status="mandatory_hitl")
        analysis = await generate_contextual_hitl_questions(evidence_context, user_request)
        if "error" in analysis:
            log_flow(logger, "v2_gap_analysis_gate", level="warning", status="mandatory_hitl_fallback")
            analysis = await analyze_gaps({"evidence_context": evidence_context}, user_request, force_questions=True)
        questions = analysis.get("questions", [])
        return {
            "status": "blocked_on_user",
            "message": "Strategic Intelligence Audit: before final synthesis, I need a few targeted clarifications based on the current evidence. Please answer these questions to continue.",
            "analysis": analysis.get("analysis", ""),
            "questions": questions,
            "post_hitl_search_prompt_template": _build_post_hitl_search_prompt_template(
                user_request,
                evidence_context,
                questions,
            ),
        }

    # Gap analysis (same as V1) — skip if answers provided or force flag set
    if not user_answers and not payload.get("_force_content"):
        try:
            analysis = await analyze_gaps({"evidence_context": evidence_context}, user_request)
            if analysis.get("gaps_found"):
                questions = analysis.get("questions", [])
                return {
                    "status": "blocked_on_user",
                    "message": "Strategic Intelligence Audit: critical gaps identified in the project context.",
                    "analysis": analysis.get("analysis", ""),
                    "questions": questions,
                    "post_hitl_search_prompt_template": _build_post_hitl_search_prompt_template(
                        user_request,
                        evidence_context,
                        questions,
                    ),
                }
        except Exception as exc:
            logger.warning("v2_gap_analysis_error err=%s", exc)

    # Detect artifact type
    registry = get_registry()
    artifact_kind = registry.detect_kind(user_request, payload.get("skills"))
    artifact_type = registry.get(artifact_kind)

    log_flow(
        logger,
        "v2_artifact_type_resolved",
        kind=artifact_kind.value,
        sections=len(artifact_type.sections),
        session_id=session_id,
    )

    # Generate all sections
    manifest = await generate_artifact_sections(
        artifact_type=artifact_type,
        raw_context=evidence_context,
        user_request=user_request,
        user_answers=user_answers,
        brand_dna=brand_dna,
    )

    # Build response matching V1 contract
    legacy_schema = manifest.to_legacy_content_schema()

    return {
        "status": "success",
        "message": "DaVinci Visual Synthesis complete (V2 template engine).",
        "html_artifact": manifest.full_html,
        "schema_data": legacy_schema.model_dump(),
        "skills_used": artifact_type.default_skills,
        "brand_dna_version": "2.0",
        # V2-specific fields
        "artifact_manifest": manifest.model_dump(mode="json"),
    }


def _normalized_stream_event_type(event_type: str) -> str:
    if event_type == "blocked":
        return "hitl_required"
    if event_type in {"html_generation_started", "rendering_started"}:
        return "rendering_started"
    if event_type == "success":
        return "artifact_ready"
    if event_type == "status":
        return "pipeline_started"
    return event_type


def _evidence_summary_payload(evidence_context: str, user_answers: Optional[dict] = None) -> dict:
    compact = " ".join((evidence_context or "").split())
    payload = {
        "summary": compact[:500],
        "evidence_chars": len(evidence_context or ""),
        "has_answers": bool(user_answers),
    }
    if user_answers:
        payload["answers_count"] = len(user_answers)
    return payload


def _build_post_hitl_search_prompt_template(
    user_request: str,
    evidence_context: str,
    questions: Optional[list[str]] = None,
) -> str:
    """Build a deterministic retrieval prompt used for post-HITL evidence refresh."""
    compact_evidence = " ".join((evidence_context or "").split())[:1200]
    question_lines = []
    for idx, question in enumerate(questions or [], start=1):
        q = str(question or "").strip()
        if q:
            question_lines.append(f"- q{idx}: {q}")
    if not question_lines:
        question_lines = [
            "- q1: Clarify primary audience and decision context.",
            "- q2: Clarify the key metric or proof to prioritize.",
            "- q3: Clarify preferred comparison or baseline.",
            "- q4: Clarify final narrative emphasis and CTA intent.",
        ]
    return (
        "Refresh evidence for artifact synthesis.\n"
        f"Original request: {user_request.strip()}\n"
        "Use the HITL answers below to retrieve the most decision-critical facts.\n"
        "Prioritize numeric evidence, segment-level comparisons, trend deltas, and source-grounded claims.\n"
        "Resolve these clarification targets:\n"
        f"{chr(10).join(question_lines)}\n"
        "Current evidence snapshot:\n"
        f"{compact_evidence}"
    )


async def build_content_director_plan(
    user_request: str,
    evidence_context: str,
    section_ids: list[str],
    user_answers: Optional[dict] = None,
) -> Dict[str, Any]:
    """Generate per-page rendering plan before section synthesis."""
    if not _get_openai_key():
        return {"overall_strategy": "", "pages": []}
    payload = {
        "model": _get_llm_model("analysis"),
        "messages": [
            {"role": "system", "content": CONTENT_DIRECTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"USER REQUEST:\n{user_request}\n\n"
                    f"SECTION ORDER:\n{json.dumps(section_ids)}\n\n"
                    f"USER ANSWERS:\n{json.dumps(user_answers or {}, ensure_ascii=True)}\n\n"
                    f"EVIDENCE:\n{(evidence_context or '')[:8000]}"
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    url = f"{_get_openai_url()}/chat/completions"
    headers = {"Authorization": f"Bearer {_get_openai_key()}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            raw = res.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw) if raw else {}
            pages = parsed.get("pages") if isinstance(parsed, dict) else []
            if not isinstance(pages, list):
                pages = []
            return {
                "overall_strategy": str(parsed.get("overall_strategy", "")) if isinstance(parsed, dict) else "",
                "pages": pages,
            }
    except Exception as exc:
        log_flow(logger, "content_director_plan_error", level="warning", error=str(exc))
        fallback_pages = []
        for idx, section_id in enumerate(section_ids, start=1):
            fallback_pages.append(
                {
                    "page_number": idx,
                    "section_id": section_id,
                    "objective": "Advance narrative with evidence-backed clarity.",
                    "evidence_focus": [],
                    "layout_direction": "Use clear hierarchy and restrained visuals.",
                    "copy_tone": "confident, concise, executive",
                    "must_include": [],
                }
            )
        return {"overall_strategy": "Fallback plan", "pages": fallback_pages}


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": _agent_name(),
        "status": "healthy",
        "mode": "rest+ws-worker",
        "host": socket.gethostname(),
    }

@app.post("/execute")
async def execute(req: ExecuteRequest, http_request: Request) -> Dict[str, Any]:
    task = req.task or req.query or req.payload.get("orchestrator_instruction", "No task provided")
    full_payload = {**req.payload, **req.model_dump(exclude={"task", "query", "payload"})}
    # Opportunistically parse MCP envelope for correlation ids.
    raw_env = http_request.headers.get("x-mcp-envelope")
    if raw_env:
        try:
            env = json.loads(raw_env)
            full_payload.setdefault("mcp_mission_id", env.get("mission_id"))
            full_payload.setdefault("mcp_thread_id", env.get("thread_id"))
            full_payload.setdefault("mcp_run_id", env.get("run_id"))
            full_payload.setdefault("mcp_intent", env.get("intent"))

            # T1-C: Wire envelope constraints into processing
            envelope_constraints = env.get("constraints", {})
            envelope_intent = env.get("intent", "")
            envelope_policy_refs = env.get("policy_refs", [])

            # If intent is explicitly "generate_content", skip gap-check keyword heuristic
            if envelope_intent == "generate_content":
                full_payload["_force_content"] = True
                log_flow(logger, "mcp_envelope_force_content", intent=envelope_intent)

            # Pass max_tokens constraint to LLM calls
            if envelope_constraints.get("max_tokens"):
                full_payload["_max_tokens"] = envelope_constraints["max_tokens"]
                log_flow(logger, "mcp_envelope_max_tokens", max_tokens=envelope_constraints["max_tokens"])

            if envelope_policy_refs:
                full_payload.setdefault("mcp_policy_refs", envelope_policy_refs)
                if any("brand_dna/davinci_ai.json" in ref for ref in envelope_policy_refs):
                    load_brand_dna()
                    full_payload["_force_brand_constraints"] = True

        except Exception as exc:
            log_flow(logger, "mcp_envelope_parse_error", level="warning", error=str(exc))
    log_flow(
        logger,
        "execute_start",
        tenant_id=full_payload.get("tenant_id"),
        room_number=full_payload.get("room_number"),
        collection_name=full_payload.get("collection_name"),
        session_id=full_payload.get("session_id"),
        orchestrator_request_id=full_payload.get("orchestrator_request_id"),
        mission_id=full_payload.get("mcp_mission_id"),
        thread_id=full_payload.get("mcp_thread_id"),
    )
    # V2 template engine pipeline
    if full_payload.get("_use_template_engine"):
        session_id = full_payload.get("session_id", "")
        mcp_env = None
        if raw_env:
            try:
                mcp_env = json.loads(raw_env)
            except Exception:
                pass
        result = await process_task_v2(
            user_request=task,
            payload=full_payload,
            brand_dna=BRAND_DNA,
            session_id=session_id,
            mcp_env=mcp_env,
        )
        return result

    result = await process_task(task, full_payload)
    return {
        "agent": _agent_name(),
        "received_task": task,
        "payload": full_payload,
        "result": result,
    }

@app.post("/stream")
async def stream(req: ExecuteRequest, http_request: Request):
    task = req.task or req.query or req.payload.get("orchestrator_instruction", "No task provided")
    full_payload = {**req.payload, **req.model_dump(exclude={"task", "query", "payload"})}
    raw_env = http_request.headers.get("x-mcp-envelope")
    if raw_env:
        try:
            env = json.loads(raw_env)
            full_payload.setdefault("mcp_mission_id", env.get("mission_id"))
            full_payload.setdefault("mcp_thread_id", env.get("thread_id"))
            full_payload.setdefault("mcp_run_id", env.get("run_id"))
            full_payload.setdefault("mcp_intent", env.get("intent"))

            # T1-C: Wire envelope constraints into processing
            envelope_constraints = env.get("constraints", {})
            envelope_intent = env.get("intent", "")
            envelope_policy_refs = env.get("policy_refs", [])

            if envelope_intent == "generate_content":
                full_payload["_force_content"] = True
                log_flow(logger, "mcp_envelope_force_content", intent=envelope_intent)

            if envelope_constraints.get("max_tokens"):
                full_payload["_max_tokens"] = envelope_constraints["max_tokens"]
                log_flow(logger, "mcp_envelope_max_tokens", max_tokens=envelope_constraints["max_tokens"])

            if envelope_policy_refs:
                full_payload.setdefault("mcp_policy_refs", envelope_policy_refs)
                if any("brand_dna/davinci_ai.json" in ref for ref in envelope_policy_refs):
                    load_brand_dna()
                    full_payload["_force_brand_constraints"] = True

        except Exception as exc:
            log_flow(logger, "mcp_envelope_parse_error", level="warning", error=str(exc))
    log_flow(
        logger,
        "stream_start",
        tenant_id=full_payload.get("tenant_id"),
        room_number=full_payload.get("room_number"),
        collection_name=full_payload.get("collection_name"),
        session_id=full_payload.get("session_id"),
        orchestrator_request_id=full_payload.get("orchestrator_request_id"),
        mission_id=full_payload.get("mcp_mission_id"),
        thread_id=full_payload.get("mcp_thread_id"),
    )
    
    async def sse_gen():
        """Generate SSE events with consistent format for frontend consumption."""
        event_sequence = 0

        def _emit(event_type: str, **payload: Any) -> str:
            nonlocal event_sequence
            event_sequence += 1
            payload.setdefault("sequence", event_sequence)
            payload.setdefault("normalized_type", _normalized_stream_event_type(event_type))
            return f"data: {json.dumps({'type': event_type, **payload})}\n\n"

        # V2 template engine pipeline
        if full_payload.get("_use_template_engine"):
            async for event in sse_gen_v2(
                user_request=task,
                payload=full_payload,
                brand_dna=BRAND_DNA,
                session_id=full_payload.get("session_id", ""),
            ):
                yield event
            return

        # Initial status update
        yield _emit("status", message="Starting Strategic Intelligence Audit")

        # Planning phase
        yield _emit("planning", message="Auditing context against Brand DNA")
        await asyncio.sleep(0.3)

        try:
            result = await process_task(task, full_payload)

            # Forward the result with proper type annotation
            if result.get("status") == "blocked_on_user":
                # User needs to answer questions
                yield _emit(
                    "blocked",
                    message=result.get("message"),
                    analysis=result.get("analysis"),
                    questions=result.get("questions"),
                    post_hitl_search_prompt_template=result.get("post_hitl_search_prompt_template", ""),
                    status="blocked_on_user",
                    agent_node="content_node",
                )
            elif result.get("status") == "error":
                # Error occurred
                yield _emit("error", message=result.get("message"), details=result.get("details"))
            elif result.get("status") == "success":
                # Success with HTML
                html_artifact = result.get("html_artifact", "")
                schema_data = result.get("schema_data")
                yield _emit("schema_ready", message="Schema extracted", schema_data=schema_data)
                yield _emit(
                    "html_generation_started",
                    message="Vangogh is composing the artifact",
                    rendering_phase="rendering_started",
                )
                for index, chunk in enumerate(_html_chunks(html_artifact), start=1):
                    yield _emit("html_chunk", index=index, chunk=chunk)
                    await asyncio.sleep(0.03)
                yield _emit(
                    "success",
                    message=result.get("message"),
                    html_artifact=html_artifact,
                    schema_data=schema_data,
                    skills_used=result.get("skills_used", []),
                )
            else:
                # Unknown status
                yield _emit("unknown", result=result)

        except Exception as e:
            logger.exception("event=stream_processing_error err=%s", str(e))
            yield _emit("error", message=f"Processing error: {str(e)}")

        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_gen(), media_type="text/event-stream")


async def sse_gen_v2(
    user_request: str,
    payload: dict,
    brand_dna: dict,
    session_id: str = "",
):
    """V2 SSE generator with section-level progressive events."""
    import json as _json

    event_sequence = 0
    page_review_enabled = str(os.getenv("CONTENT_PAGE_REVIEW_GATE", "true")).lower() in {"1", "true", "yes", "on"}

    def _sse(data: dict) -> str:
        return f"data: {_json.dumps(data)}\n\n"

    def _emit(event_type: str, **payload_data: Any) -> str:
        nonlocal event_sequence
        event_sequence += 1
        payload_data.setdefault("sequence", event_sequence)
        payload_data.setdefault("normalized_type", _normalized_stream_event_type(event_type))
        return _sse({"type": event_type, **payload_data})

    yield _emit("status", message="Starting Vangogh V2 pipeline")

    # Reuse context retrieval
    evidence_context = payload.get("evidence_context", "")
    user_answers = payload.get("answers")
    require_hitl = bool(payload.get("_require_hitl"))

    if not evidence_context:
        try:
            graphrag_results = await fetch_graphrag_context(user_request, session_id, payload)
            evidence_context = extract_graphrag_results(graphrag_results)
        except Exception as exc:
            yield _emit("error", message=f"Context retrieval failed: {exc}")
            yield "data: [DONE]\n\n"
            return

    evidence_type = "evidence_refreshed" if user_answers else "evidence_summary"
    yield _emit(
        evidence_type,
        message="Evidence refreshed" if user_answers else "Evidence summarized",
        summary=_evidence_summary_payload(evidence_context, user_answers),
    )

    if require_hitl and not user_answers:
        yield _emit("planning", message="Auditing context against Brand DNA")
        analysis = await generate_contextual_hitl_questions(evidence_context, user_request)
        if "error" in analysis:
            analysis = await analyze_gaps({"evidence_context": evidence_context}, user_request, force_questions=True)
        yield _emit(
            "blocked",
            message=analysis.get("analysis", "Clarifications required"),
            analysis=analysis.get("analysis", ""),
            questions=analysis.get("questions", []),
            post_hitl_search_prompt_template=_build_post_hitl_search_prompt_template(
                user_request,
                evidence_context,
                analysis.get("questions", []),
            ),
            status="blocked_on_user",
            agent_node="content_node",
        )
        yield "data: [DONE]\n\n"
        return

    # Gap analysis
    if not user_answers and not payload.get("_force_content"):
        yield _emit("planning", message="Auditing context against Brand DNA")
        try:
            analysis = await analyze_gaps({"evidence_context": evidence_context}, user_request)
            if analysis.get("gaps_found"):
                yield _emit(
                    "blocked",
                    message=analysis.get("analysis", "Gaps found"),
                    analysis=analysis.get("analysis", ""),
                    questions=analysis.get("questions", []),
                    post_hitl_search_prompt_template=_build_post_hitl_search_prompt_template(
                        user_request,
                        evidence_context,
                        analysis.get("questions", []),
                    ),
                    status="blocked_on_user",
                    agent_node="content_node",
                )
                yield "data: [DONE]\n\n"
                return
        except Exception as exc:
            logger.warning("v2_stream_gap_error err=%s", exc)

    # Detect artifact type
    registry = get_registry()
    artifact_kind = registry.detect_kind(user_request, payload.get("skills"))
    artifact_type = registry.get(artifact_kind)
    preferred_blueprint_id = payload.get("_blueprint_id")
    blueprint_registry = get_blueprint_registry()
    blueprint = blueprint_registry.resolve(artifact_kind, preferred_blueprint_id)

    # Initialize the template engine early so we can send the base shell for
    # progressive rendering in CORE/frontends.
    from agents.content_creator.template_engine import VangoghTemplateEngine, TEMPLATES_DIR
    engine = VangoghTemplateEngine(TEMPLATES_DIR, brand_dna, blueprint=blueprint)
    try:
        base_shell = engine.render_base_shell({
            "title": user_request[:80],
            "blueprint_id": blueprint.get("id", ""),
        })
    except Exception:
        base_shell = ""

    section_ids = [s.section_id for s in artifact_type.sections]
    content_director_plan = await build_content_director_plan(
        user_request=user_request,
        evidence_context=evidence_context,
        section_ids=section_ids,
        user_answers=user_answers,
    )
    yield _emit(
        "artifact_type_resolved",
        kind=artifact_kind.value,
        total_sections=len(artifact_type.sections),
        section_ids=section_ids,
        blueprint_id=blueprint.get("id", ""),
    )
    yield _emit(
        "content_director_plan",
        message="Content Director finalized page-by-page plan",
        plan=content_director_plan,
        blueprint=blueprint,
    )
    yield _emit(
        "html_generation_started",
        message="Vangogh is rendering the artifact",
        artifact_kind=artifact_kind.value,
        total_sections=len(artifact_type.sections),
        section_ids=section_ids,
        rendering_phase="rendering_started",
        base_shell=base_shell,
        root_id="vangogh-root",
    )

    # Section-by-section generation with callbacks
    collected_fragments: list[str] = []

    async def on_section_ready(
        index: int,
        section_id: str,
        label: str,
        html_fragment: str,
        section_data: dict,
    ) -> None:
        collected_fragments.append(html_fragment)

    # We can't yield from inside the callback, so we use a different approach:
    # generate all sections, yielding events between each
    from agents.content_creator.template_engine import build_chart_config
    from agents.content_creator.section_generator import extract_section_data, _prepare_section_data_for_template, _fallback_section_data
    from orchestrator.contracts.manifests import ArtifactManifest, SectionManifest

    sections_manifest: list[dict] = []
    sections_for_continuity: list[dict] = []

    for idx, section_spec in enumerate(artifact_type.sections):
        page_plan = {}
        for candidate in content_director_plan.get("pages", []):
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("section_id", "")).strip() == section_spec.section_id:
                page_plan = candidate
                break

        yield _emit(
            "section_started",
            section_index=idx,
            section_id=section_spec.section_id,
            section_label=section_spec.label,
            page_plan=page_plan,
            section_progress={"current": idx + 1, "total": len(artifact_type.sections)},
        )

        # Extract
        enriched_request = user_request
        if page_plan:
            enriched_request = (
                f"{user_request}\n\n"
                f"CONTENT DIRECTOR PAGE BRIEF:\n{json.dumps(page_plan, ensure_ascii=True)}"
            )
        section_data = await extract_section_data(
            section_spec=section_spec,
            raw_context=evidence_context,
            user_request=enriched_request,
            user_answers=user_answers,
            prior_sections=sections_for_continuity,
        )

        # Post-process
        section_data = _prepare_section_data_for_template(
            section_spec, section_data, brand_dna
        )

        # Render
        try:
            html_fragment = engine.render_section(section_spec.template_name, section_data)
        except Exception as render_exc:
            html_fragment = f'<div class="p-8 text-stone-400">Render error: {render_exc}</div>'

        sections_manifest.append({
            "section_id": section_spec.section_id,
            "template_name": section_spec.template_name,
            "data": section_data,
            "html_fragment": html_fragment,
            "order": idx,
        })
        sections_for_continuity.append({
            "section_id": section_spec.section_id,
            "data": section_data,
        })

        yield _emit(
            "section_ready",
            section_index=idx,
            section_id=section_spec.section_id,
            section_label=section_spec.label,
            html_fragment=html_fragment,
            section_data=section_data,
            page_plan=page_plan,
            section_progress={"current": idx + 1, "total": len(artifact_type.sections)},
        )

        # Gate multi-page artifacts after first page so users can continue or cancel.
        if (
            page_review_enabled
            and len(artifact_type.sections) > 1
            and idx == 0
            and not bool(payload.get("_page_review_approved"))
        ):
            yield _emit(
                "blocked",
                message="Page 1 is ready for review. Reply 'continue' to render remaining pages, or 'cancel' to stop.",
                analysis="First page preview generated. Confirm continuation before full artifact rendering.",
                questions=["Continue rendering pages 2+ or cancel this artifact?"],
                status="blocked_on_user",
                agent_node="content_page_review",
                hitl_mode="page_review",
                post_hitl_search_prompt_template="",
            )
            yield "data: [DONE]\n\n"
            return

    # Compose full document
    sections_for_comp = [
        {"section_id": s["section_id"], "html_fragment": s["html_fragment"]}
        for s in sections_manifest
    ]
    full_body = engine.render_artifact(
        artifact_kind.value,
        sections_for_comp,
        {"title": user_request[:80], "blueprint": blueprint},
    )
    base_shell = engine.render_base_shell({
        "title": user_request[:80],
        "blueprint_id": blueprint.get("id", ""),
    })
    full_html = base_shell.replace(
        '<div id="vangogh-root">\n    \n  </div>',
        f'<div id="vangogh-root">\n{full_body}\n  </div>',
    )
    if full_body not in full_html:
        full_html = base_shell.replace("</div>\n  <script>", f"{full_body}\n  </div>\n  <script>", 1)

    yield _emit(
        "artifact_composed",
        total_sections=len(sections_manifest),
        kind=artifact_kind.value,
    )

    # Slide metadata for decks/keynotes
    if artifact_type.supports_navigation:
        slide_titles = [s.get("data", {}).get("headline", s.get("data", {}).get("title", s["section_id"])) for s in sections_manifest]
        yield _emit(
            "slide_metadata",
            total_slides=len(sections_manifest),
            slide_titles=slide_titles,
        )

    # Legacy schema
    manifest = ArtifactManifest(
        kind=artifact_kind.value,
        title=user_request[:120],
        sections=[SectionManifest(**s) for s in sections_manifest],
        full_html=full_html,
    )
    legacy_schema = manifest.to_legacy_content_schema()

    yield _emit(
        "success",
        message="DaVinci Visual Synthesis complete (V2).",
        html_artifact=full_html,
        schema_data=legacy_schema.model_dump(),
        skills_used=artifact_type.default_skills,
        brand_dna_version="2.0",
    )
    yield "data: [DONE]\n\n"


async def ws_worker() -> None:
    reconnect_delay = 2
    while True:
        url = _core_ws_url()
        logger.info(f"Attempting WS connection to {url}")
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                logger.info(f"Connected to Orchestrator WS at {url}")
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if msg.get("type") != "task":
                        continue

                    request_id = msg.get("request_id")
                    task = msg.get("task")
                    payload = msg.get("payload") or {}
                    
                    # Execute logic
                    exec_result = await process_task(task, payload)

                    response = {
                        "type": "result",
                        "request_id": request_id,
                        "status": "ok",
                        "data": {
                            "agent": _agent_name(),
                            "received_task": task,
                            "payload": payload,
                            "result": exec_result,
                        },
                    }
                    await ws.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WS connection closed, reconnecting...")
            await asyncio.sleep(reconnect_delay)
        except Exception as e:
            logger.error(f"WS worker error: {e}")
            await asyncio.sleep(reconnect_delay)

@app.on_event("startup")
async def startup_event() -> None:
    global WS_TASK
    if os.getenv("AGENT_ENABLE_WS", "true").lower() == "true":
        WS_TASK = asyncio.create_task(ws_worker())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global WS_TASK
    if WS_TASK:
        WS_TASK.cancel()
        with suppress(asyncio.CancelledError):
            await WS_TASK
