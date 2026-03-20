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

# Import skill loader
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts.prompt_loader import PromptLoader

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
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
        # Claude 4.6 Sonnet - best for complex UI/code generation
        return os.getenv("CONTENT_DESIGN_MODEL", "vertex_ai/claude-sonnet-4-6@default")
    elif task_type == "analysis":
        # Fast model for gap analysis and strategy
        return os.getenv("CONTENT_ANALYSIS_MODEL", "gpt-4o-mini")
    else:
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _get_gap_analysis_model() -> str:
    """Fast model for strategic gap analysis - gpt-4o-mini is perfect for this"""
    return os.getenv("GAP_ANALYSIS_MODEL", "gpt-4o-mini")

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
3. If gaps_found is FALSE, set questions to an empty array [] and provide a brief confirmation in analysis.

Output in STRICT JSON:
{{
  "gaps_found": true or false,
  "analysis": "Brief explanation - either what's missing OR confirmation that context is sufficient",
  "questions": ["Q1", "Q2", "Q3", "Q4"] or []
}}
"""


BRAND_DNA: Dict[str, Any] = {}
BRAND_DNA_PATH = Path(os.getenv("BRAND_DNA_PATH", "/app/brand_dna/davinci_ai.json"))

# Initialize skill loader
skill_loader: Optional[PromptLoader] = None

def load_brand_dna():
    global BRAND_DNA
    logger.info(f"Loading Brand DNA from: {BRAND_DNA_PATH}")
    if BRAND_DNA_PATH.exists():
        try:
            with open(BRAND_DNA_PATH, 'r') as f:
                BRAND_DNA = json.load(f)
            logger.info(f"Brand DNA loaded successfully from {BRAND_DNA_PATH}")
        except json.JSONDecodeError as e:
            logger.error(f"Brand DNA file is not valid JSON: {e}")
            BRAND_DNA = {"_error": f"Invalid JSON in Brand DNA file: {e}"}
        except Exception as e:
            logger.error(f"Failed to load Brand DNA: {e}")
            BRAND_DNA = {"_error": str(e)}
    else:
        logger.warning(f"Brand DNA file not found at {BRAND_DNA_PATH}. Using empty DNA. Set BRAND_DNA_PATH env var to configure.")
        BRAND_DNA = {"_warning": f"Brand DNA file not found at {BRAND_DNA_PATH}"}

def initialize_skill_loader():
    """Initialize the skill loader with proper paths and validation."""
    global skill_loader

    # Get the base directory (src)
    base_dir = Path(__file__).parent.parent.parent
    skills_dir = base_dir / "skills"
    prompt_dir = base_dir / "prompts" / "xml"

    logger.info(f"Initializing skill loader with skills_dir={skills_dir}, prompt_dir={prompt_dir}")

    # Validate directories exist
    if not skills_dir.exists():
        logger.warning(f"Skills directory not found at {skills_dir}. Creating...")
        try:
            skills_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create skills directory: {e}")

    if not prompt_dir.exists():
        logger.warning(f"Prompt directory not found at {prompt_dir}")

    try:
        skill_loader = PromptLoader(
            prompt_dir=str(prompt_dir),
            skills_dir=str(skills_dir)
        )
        available_skills = skill_loader.list_available_skills()
        logger.info(f"Skill loader initialized successfully. Available skills: {available_skills}")
    except Exception as e:
        logger.error(f"Failed to initialize skill loader: {e}")
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
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 404:
                logger.warning("GraphRAG returned 404 (no chunks found). Proceeding with empty context.")
                return {"data": {"results": []}, "note": "No chunks found"}
            res.raise_for_status()
            logger.info(f"GraphRAG context retrieved successfully.")
            return res.json()
        except Exception as e:
            logger.error(f"Failed to fetch GraphRAG context: {e}")
            return {"data": {"results": []}, "error": str(e)}

async def analyze_gaps(graphrag_data: Any, user_request: str) -> Dict[str, Any]:
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

    payload = {
        "model": _get_llm_model("analysis"),  # Fast model for gap analysis
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"USER REQUEST: {user_request}\n\nAnalyze this user request against the following project context and align with Brand DNA:\n\n{context_summary}"}
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
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            content = res.json()["choices"][0]["message"]["content"]
            result = json.loads(content)
            logger.info(f"Gap analysis result: {json.dumps(result)}")
            
            # If LLM returned empty or missing gaps_found, default to asking questions
            if not result or "gaps_found" not in result:
                logger.warning("Gap analysis returned incomplete data, defaulting to gaps_found=True")
                result = {
                    "gaps_found": True,
                    "analysis": "Insufficient context to generate a premium DaVinci AI asset.",
                    "questions": [
                        f"What is the primary goal and target audience for this {user_request.split()[0:6]}?",
                        "What specific data points, metrics, or outcomes should be highlighted?",
                        "What emotional tone should the visual convey — aggressive confidence, measured credibility, or innovative disruption?",
                        "Are there any specific brand elements, competitor references, or industry benchmarks to include?"
                    ]
                }

            # Ensure exactly 4 questions if gaps are found
            if result.get("gaps_found"):
                q = result.get("questions", [])
                if not isinstance(q, list) or len(q) == 0:
                    q = ["Could you clarify the primary value proposition?"]
                while len(q) < 4:
                    q.append("What specific target audience is most critical for this phase?")
                result["questions"] = q[:4]
            return result
        except Exception as e:
            logger.error(f"Gap analysis LLM call failed: {e}")
            return {"error": str(e)}

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

DESIGN_SYSTEM_PROMPT = """You are a premium UI/UX designer. Generate a SINGLE standalone HTML5 document.

STYLE TOKENS:
- Background: #0a0a0a | Surface: #0d0d0d | Border: #1a1a1a
- Primary: #FF4500 (orange) | Accent: #3b82f6 (blue) | Emerald: #10b981
- Headings: 'Bebas Neue', sans-serif | Body: 'Space Grotesk', sans-serif
- Glassmorphism: backdrop-blur-md bg-white/5 border border-white/10
- Stats: text-4xl font-mono font-bold text-orange-500

TEMPLATE:
```
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://unpkg.com/@tailwindcss/browser@4"></script>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>body {{ font-family: 'Space Grotesk', sans-serif; }} h1,h2,h3 {{ font-family: 'Bebas Neue', sans-serif; }}</style>
</head>
<body class="bg-[#0a0a0a] text-white min-h-screen">
  <!-- YOUR CONTENT HERE -->
</body>
</html>
```

RULES:
1. Use Tailwind CSS classes (NOT className).
2. Use Bento Grid (grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6) for layout.
3. Apply glassmorphism to cards: backdrop-blur-md bg-white/5 border border-white/10 rounded-xl p-6.
4. Stats in text-4xl font-mono font-bold text-orange-500.
5. Use subtle hover effects: hover:border-orange-500/50 transition-all duration-300.
6. Output ONLY the raw HTML. No markdown, no explanation, no code fences."""


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
    skill_names: Optional[List[str]] = None
) -> str:
    """Generate premium HTML from structured data using a compact prompt."""
    
    # Build a concise data summary (cap at 3000 chars to keep prompt lean)
    data_summary = json.dumps(structured_data, indent=2)
    if len(data_summary) > 3000:
        data_summary = data_summary[:3000] + "\n..."
    
    logger.info(f"Design prompt: system={len(DESIGN_SYSTEM_PROMPT)} chars, data={len(data_summary)} chars")
    
    payload = {
        "model": _get_llm_model("design"),  # Claude 4.6 for high-quality HTML/Tailwind
        "messages": [
            {"role": "system", "content": DESIGN_SYSTEM_PROMPT},
            {"role": "user", "content": f"Create a premium dark-mode visual for: {user_request}\n\nDATA:\n{data_summary}"}
        ],
        "temperature": 0.4
    }

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
            
            logger.info(f"Generated HTML: {len(html_content)} chars")
            return html_content
        except Exception as e:
            logger.error(f"Design generation failed: {e}")
            return f"<div class='p-10 bg-black text-white border border-red-500'>Synthesis Fault: {str(e)}</div>"



async def process_task(task_instruction: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"Processing task: {task_instruction} | Payload keys: {list(payload.keys())}")

    session_id = payload.get("session_id")
    # If this is a follow-up with answers
    user_answers = payload.get("answers")
    # Allow explicit skill override via payload
    explicit_skills = payload.get("skills", None)
    logger.info(f"User answers present: {bool(user_answers)}")
    logger.info(f"Explicit skills provided: {explicit_skills}")

    # 1. Pull context
    # Multi-agent support: Check if orchestrator already provided helper outputs (GraphRAG)
    helper_outputs = payload.get("strategy_helper_outputs", {})
    graphrag_data = helper_outputs.get("blaiq-graph-rag")

    if graphrag_data:
        logger.info("Using GraphRAG context provided by Orchestrator helpers.")
        # Extract results from GraphRAG response
        context_text = extract_graphrag_results(graphrag_data)
        logger.info(f"Extracted GraphRAG context: {len(context_text)} chars")
    else:
        logger.info("No helper context found, pulling GraphRAG context manually...")
        graphrag_data = await fetch_graphrag_context(task_instruction, session_id, payload)
        context_text = extract_graphrag_results(graphrag_data)

    # Use the extracted text as raw context
    raw_context = context_text

    # 2. If no answers yet, check for gaps
    if not user_answers:
        logger.info("No answers provided, performing gap analysis...")
        analysis = await analyze_gaps(graphrag_data, task_instruction)
        if "error" in analysis:
            return {"status": "error", "message": "Failed gap analysis", "details": analysis}

        if analysis.get("gaps_found"):
            return {
                "status": "blocked_on_user",
                "message": "Strategic Intelligence Audit: I have identified critical gaps that prevent us from achieving a DaVinci AI premium alignment. Please guide the creative direction by answering these questions.",
                "analysis": analysis.get("analysis"),
                "questions": analysis.get("questions")
            }

    logger.info("Proceeding to schema extraction and design generation...")
    # 3. Extract Schema
    structured_data = await extract_schema(raw_context, user_answers)
    if "error" in structured_data:
         return {"status": "error", "message": "Failed schema extraction", "details": structured_data}

    # 4. Generate the design using Visual Synthesis with skill injection
    html = await generate_design(
        structured_data=structured_data,
        user_request=task_instruction,
        skill_names=explicit_skills
    )

    return {
        "status": "success",
        "message": "DaVinci Visual Synthesis complete.",
        "html_artifact": html
    }

@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": _agent_name(),
        "status": "healthy",
        "mode": "rest+ws-worker",
        "host": socket.gethostname(),
    }

@app.post("/execute")
async def execute(req: ExecuteRequest) -> Dict[str, Any]:
    task = req.task or req.query or req.payload.get("orchestrator_instruction", "No task provided")
    full_payload = {**req.payload, **req.model_dump(exclude={"task", "query", "payload"})}
    logger.info(
        "execute tenant_id=%s room_number=%s collection_name=%s qdrant_url=%s neo4j_uri=%s",
        full_payload.get("tenant_id"),
        full_payload.get("room_number"),
        full_payload.get("collection_name"),
        full_payload.get("qdrant_url"),
        full_payload.get("neo4j_uri"),
    )
    result = await process_task(task, full_payload)
    return {
        "agent": _agent_name(),
        "received_task": task,
        "payload": full_payload,
        "result": result,
    }

@app.post("/stream")
async def stream(req: ExecuteRequest):
    task = req.task or req.query or req.payload.get("orchestrator_instruction", "No task provided")
    full_payload = {**req.payload, **req.model_dump(exclude={"task", "query", "payload"})}
    logger.info(
        "stream tenant_id=%s room_number=%s collection_name=%s qdrant_url=%s neo4j_uri=%s",
        full_payload.get("tenant_id"),
        full_payload.get("room_number"),
        full_payload.get("collection_name"),
        full_payload.get("qdrant_url"),
        full_payload.get("neo4j_uri"),
    )
    
    async def sse_gen():
        """Generate SSE events with consistent format for frontend consumption."""
        # Initial status update
        yield f"data: {json.dumps({'type': 'status', 'message': '🎯 Starting Strategic Intelligence Audit...'})}\n\n"

        # Planning phase
        yield f"data: {json.dumps({'type': 'planning', 'message': 'Auditing context against Brand DNA...'})}\n\n"
        await asyncio.sleep(0.3)

        try:
            result = await process_task(task, full_payload)

            # Forward the result with proper type annotation
            if result.get("status") == "blocked_on_user":
                # User needs to answer questions
                yield f"data: {json.dumps({'type': 'blocked', 'message': result.get('message'), 'analysis': result.get('analysis'), 'questions': result.get('questions')})}\n\n"
            elif result.get("status") == "error":
                # Error occurred
                yield f"data: {json.dumps({'type': 'error', 'message': result.get('message'), 'details': result.get('details')})}\n\n"
            elif result.get("status") == "success":
                # Success with HTML
                yield f"data: {json.dumps({'type': 'success', 'message': result.get('message'), 'html_artifact': result.get('html_artifact')})}\n\n"
            else:
                # Unknown status
                yield f"data: {json.dumps({'type': 'unknown', 'result': result})}\n\n"

        except Exception as e:
            logger.error(f"Error in stream processing: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': f'Processing error: {str(e)}'})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_gen(), media_type="text/event-stream")


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
