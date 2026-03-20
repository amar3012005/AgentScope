import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

import httpx
from openai import OpenAI
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ProtocolType = Literal["rest", "ws", "auto"]
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("blaiq-core")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
LITELLM_STRATEGIST_MODEL = os.getenv("LITELLM_STRATEGIST_MODEL") or os.getenv("LITELLM_PLANNER_MODEL") or "openai/gpt-4o-mini"
STRATEGIST_ENABLED = os.getenv("STRATEGIST_ENABLED", "true").lower() == "true"
_openai_client = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE_URL, max_retries=0)
    return _openai_client


def _normalize_model_name(model: str) -> str:
    if model.startswith("openai/"):
        return model.replace("openai/", "", 1)
    return model


def _load_json_env(name: str, default: Any) -> Any:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("invalid_json_env name=%s", name)
        return default


def _tenant_env_key(tenant_id: str, suffix: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in tenant_id.upper())
    return f"TENANT_{normalized}_{suffix}"


@dataclass
class AgentConfig:
    name: str
    protocol: ProtocolType = "auto"
    base_url: Optional[str] = None
    execute_path: str = "/execute"
    stream_path: str = "/query/graphrag/stream"
    history_path: str = "/history/{session_id}"
    supports_stream: bool = True
    capabilities: List[str] = field(default_factory=list)
    method: str = "POST"
    timeout_seconds: int = 60


@dataclass
class AgentConnection:
    websocket: Optional[WebSocket] = None
    connected: bool = False
    last_error: Optional[str] = None


class OrchestrationRequest(BaseModel):
    task: str = Field(..., description="Task instructions for downstream agent")
    target_agent: Optional[str] = Field(default=None, description="Agent name; defaults to BLAIQ_DEFAULT_AGENT")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Payload sent to downstream agent")
    protocol: ProtocolType = Field(default="auto", description="Force protocol or allow automatic selection")
    method: Literal["GET", "POST"] = Field(default="POST")
    timeout_seconds: Optional[int] = Field(default=None)


class AgentRegistrationRequest(BaseModel):
    name: str
    protocol: ProtocolType = "auto"
    base_url: Optional[str] = None
    execute_path: str = "/execute"
    stream_path: str = "/query/graphrag/stream"
    history_path: str = "/history/{session_id}"
    supports_stream: bool = True
    capabilities: List[str] = Field(default_factory=list)
    method: Literal["GET", "POST"] = "POST"
    timeout_seconds: int = 60


class GraphRagQueryRequest(BaseModel):
    query: str
    collection_name: Optional[str] = None
    include_graph: bool = False
    graph_depth: int = 1
    top_k: int = 12
    session_id: Optional[str] = None


class GraphRagStreamRequest(BaseModel):
    query: str
    tenant_id: Optional[str] = None
    collection_name: Optional[str] = None
    include_graph: bool = False
    graph_depth: int = 1
    session_id: Optional[str] = None
    room_number: Optional[str] = None
    chat_history: Optional[List[Dict[str, str]]] = None
    mode: Optional[str] = None
    use_reranker: Optional[bool] = None
    use_cache: Optional[bool] = None
    k: Optional[int] = None
    content_mode: Optional[str] = None
    top_k: Optional[int] = None
    answers: Optional[Dict[str, str]] = None

    model_config = {"extra": "allow"}


STRATEGIST_SYSTEM_PROMPT = """You are BLAIQ-CORE Strategist, responsible for routing enterprise user tasks to live sub-agents.

You must:
1) Choose ONLY from currently live agents.
2) Match requested work to agent capabilities.
3) Prefer one primary stream agent for final user response.
4) Optionally select helper agents that run first and provide context to the primary.
5) Never choose unavailable agents.

Return strict JSON with keys:
{
  "reasoning": "short rationale",
  "requested_capability": "graphrag|analysis|workflow|generic",
  "primary_agent": "agent-name-or-null",
  "selected_agents": ["ordered list of agent names"],
  "helper_agents": ["agents to run before primary"],
  "route_mode": "single|sequential|parallel|fallback",
  "instructions": {
     "agent-name": "short imperative task instruction for that agent"
  }
}
"""


class CoreOrchestrator:
    def __init__(self) -> None:
        self.default_agent = os.getenv("BLAIQ_DEFAULT_AGENT", "blaiq-graph-rag")
        self.agents: Dict[str, AgentConfig] = {}
        self.connections: Dict[str, AgentConnection] = {}
        self.pending_ws: Dict[str, asyncio.Future] = {}
        self.request_states: Dict[str, Dict[str, Any]] = {}
        self.session_request_index: Dict[str, List[str]] = {}
        self._lock = asyncio.Lock()
        self._load_agents_from_env()

    def resolve_tenant_config(self, tenant_id: Optional[str]) -> Dict[str, Any]:
        tenant_key = (tenant_id or "default").strip() or "default"
        tenant_map = _load_json_env("TENANT_CONFIG_MAP_JSON", {})
        cfg = dict(tenant_map.get(tenant_key, {}))

        if not cfg:
            cfg = {
                "tenant_id": tenant_key,
                "qdrant_url": os.getenv("QDRANT_URL", "http://qdrant-test:6333"),
                "qdrant_api_key": os.getenv("QDRANT_API_KEY", "apikey12345678"),
                "collection_name": tenant_key,
                "neo4j_uri": os.getenv("NEO4J_URI", "bolt://neo4j-test:7687"),
                "neo4j_user": os.getenv("NEO4J_USER", "neo4j"),
                "neo4j_password": os.getenv("NEO4J_PASSWORD", "password12345678"),
            }

        env_overrides = {
            "qdrant_url": os.getenv(_tenant_env_key(tenant_key, "QDRANT_URL")),
            "qdrant_api_key": os.getenv(_tenant_env_key(tenant_key, "QDRANT_API_KEY")),
            "collection_name": os.getenv(_tenant_env_key(tenant_key, "COLLECTION_NAME")),
            "neo4j_uri": os.getenv(_tenant_env_key(tenant_key, "NEO4J_URI")),
            "neo4j_user": os.getenv(_tenant_env_key(tenant_key, "NEO4J_USER")),
            "neo4j_password": os.getenv(_tenant_env_key(tenant_key, "NEO4J_PASSWORD")),
        }
        for key, value in env_overrides.items():
            if value:
                cfg[key] = value

        cfg.setdefault("tenant_id", tenant_key)
        cfg.setdefault("collection_name", tenant_key)
        return cfg

    def _load_agents_from_env(self) -> None:
        raw = os.getenv("BLAIQ_SUB_AGENTS", "[]")
        try:
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise ValueError("BLAIQ_SUB_AGENTS must be a JSON array")
        except Exception as exc:
            raise RuntimeError(f"Invalid BLAIQ_SUB_AGENTS: {exc}") from exc

        for item in payload:
            cfg = AgentConfig(
                name=item["name"],
                protocol=item.get("protocol", "auto"),
                base_url=item.get("base_url"),
                execute_path=item.get("execute_path", "/execute"),
                stream_path=item.get("stream_path", "/query/graphrag/stream"),
                history_path=item.get("history_path", "/history/{session_id}"),
                supports_stream=bool(item.get("supports_stream", True)),
                capabilities=item.get("capabilities", []),
                method=item.get("method", "POST").upper(),
                timeout_seconds=int(item.get("timeout_seconds", 60)),
            )
            self.agents[cfg.name] = cfg
            self.connections[cfg.name] = AgentConnection()

    async def register_agent(self, req: AgentRegistrationRequest) -> Dict[str, Any]:
        async with self._lock:
            cfg = AgentConfig(
                name=req.name,
                protocol=req.protocol,
                base_url=req.base_url,
                execute_path=req.execute_path,
                stream_path=req.stream_path,
                history_path=req.history_path,
                supports_stream=req.supports_stream,
                capabilities=req.capabilities,
                method=req.method,
                timeout_seconds=req.timeout_seconds,
            )
            self.agents[req.name] = cfg
            self.connections.setdefault(req.name, AgentConnection())
        logger.info("agent_registered name=%s protocol=%s base_url=%s", req.name, req.protocol, req.base_url)
        return {"ok": True, "agent": req.name}

    def _resolve_agent(self, requested: Optional[str]) -> AgentConfig:
        # Treat "auto" as None to use default agent
        name = requested if requested and requested != "auto" else self.default_agent
        agent = self.agents.get(name)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Unknown agent '{name}'")
        return agent

    def set_state(
        self,
        request_id: str,
        phase: str,
        agent_name: str,
        session_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        state = {
            "request_id": request_id,
            "phase": phase,
            "agent": agent_name,
            "session_id": session_id,
            "error": error,
            "timestamp": int(time.time() * 1000),
        }
        self.request_states[request_id] = state
        if session_id:
            ids = self.session_request_index.setdefault(session_id, [])
            if request_id not in ids:
                ids.append(request_id)
        msg = (
            "request_state request_id=%s session_id=%s phase=%s agent=%s error=%s"
            % (request_id, session_id, phase, agent_name, error)
        )
        if error:
            logger.error(msg)
        else:
            logger.info(msg)
        return state

    async def get_live_agents(self) -> List[Dict[str, Any]]:
        live_entries: List[Dict[str, Any]] = []
        for name, cfg in self.agents.items():
            conn = self.connections.get(name)
            ws_live = bool(conn and conn.connected and conn.websocket)
            rest_live = False
            rest_error = None
            if cfg.base_url:
                try:
                    async with httpx.AsyncClient(timeout=2.5) as client:
                        res = await client.get(f"{cfg.base_url.rstrip('/')}/")
                        rest_live = res.status_code < 500
                except Exception as exc:
                    rest_error = str(exc)

            is_live = ws_live or rest_live
            live_entries.append(
                {
                    "name": name,
                    "protocol": cfg.protocol,
                    "capabilities": cfg.capabilities,
                    "supports_stream": cfg.supports_stream,
                    "base_url": cfg.base_url,
                    "ws_live": ws_live,
                    "rest_live": rest_live,
                    "is_live": is_live,
                    "rest_error": rest_error,
                }
            )
        return live_entries

    def heuristic_strategy(self, query: str, live_agents: List[Dict[str, Any]]) -> Dict[str, Any]:
        available = [a for a in live_agents if a.get("is_live")]
        if not available:
            return {
                "reasoning": "No live agents available.",
                "requested_capability": "generic",
                "primary_agent": None,
                "selected_agents": [],
                "helper_agents": [],
                "route_mode": "fallback",
                "instructions": {},
            }

        graphrag = next((a for a in available if "graphrag" in (a.get("capabilities") or []) or a["name"] == "blaiq-graph-rag"), None)
        primary = graphrag or available[0]
        return {
            "reasoning": "Heuristic fallback selected best available primary agent.",
            "requested_capability": "graphrag",
            "primary_agent": primary["name"],
            "selected_agents": [primary["name"]],
            "helper_agents": [],
            "route_mode": "single",
            "instructions": {
                primary["name"]: "Handle user query and return grounded response."
            },
        }

    def choose_stream_fallback_agent(
        self,
        requested_name: Optional[str],
        live_agents: List[Dict[str, Any]],
    ) -> Optional[AgentConfig]:
        live_stream_agents = [
            agent for agent in live_agents
            if agent.get("is_live") and agent.get("supports_stream") and agent.get("protocol") != "ws"
        ]
        if not live_stream_agents:
            return None

        preferred_names = [
            requested_name,
            os.getenv("BLAIQ_GRAPHRAG_AGENT", "blaiq-graph-rag"),
            self.default_agent,
        ]
        seen: set[str] = set()

        for name in preferred_names:
            if not name or name in seen:
                continue
            seen.add(name)
            match = next((agent for agent in live_stream_agents if agent.get("name") == name), None)
            if match:
                return self._resolve_agent(match["name"])

        return self._resolve_agent(live_stream_agents[0]["name"])

    def strategist_decide(self, query: str, session_id: Optional[str], live_agents: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not STRATEGIST_ENABLED or not OPENAI_API_KEY:
            return self.heuristic_strategy(query, live_agents)

        model_name = _normalize_model_name(LITELLM_STRATEGIST_MODEL)
        live_compact = [
            {
                "name": a["name"],
                "capabilities": a.get("capabilities", []),
                "supports_stream": a.get("supports_stream", False),
                "protocol": a.get("protocol"),
                "live": a.get("is_live", False),
            }
            for a in live_agents
        ]

        user_prompt = json.dumps(
            {
                "session_id": session_id,
                "query": query,
                "live_agents": live_compact,
                "policy": {
                    "must_use_live_agents_only": True,
                    "prefer_stream_primary": True,
                    "helpers_run_before_primary": True,
                },
            },
            ensure_ascii=False,
        )

        try:
            client = _get_openai_client()
            params = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": STRATEGIST_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
                "timeout": 20,
                "response_format": {"type": "json_object"},
            }
            response = client.chat.completions.create(**params)
            content = response.choices[0].message.content or "{}"
            decision = json.loads(content)
        except Exception as exc:
            logger.warning("strategist_llm_failed reason=%s", str(exc))
            return self.heuristic_strategy(query, live_agents)

        allowed = {a["name"] for a in live_agents if a.get("is_live")}
        selected = [a for a in (decision.get("selected_agents") or []) if a in allowed]
        helpers = [a for a in (decision.get("helper_agents") or []) if a in allowed]
        primary = decision.get("primary_agent")
        if primary not in allowed:
            primary = selected[0] if selected else None
        if not selected and primary:
            selected = [primary]
        if not primary and selected:
            primary = selected[0]
        if not selected:
            return self.heuristic_strategy(query, live_agents)

        decision["selected_agents"] = selected
        decision["helper_agents"] = [a for a in helpers if a != primary]
        decision["primary_agent"] = primary
        decision["instructions"] = decision.get("instructions") or {}
        return decision

    async def _dispatch_rest(self, agent: AgentConfig, req: OrchestrationRequest) -> Dict[str, Any]:
        if not agent.base_url:
            raise HTTPException(status_code=400, detail=f"Agent '{agent.name}' missing base_url for REST")

        timeout = req.timeout_seconds or agent.timeout_seconds
        method = req.method or agent.method
        url = f"{agent.base_url.rstrip('/')}{agent.execute_path}"

        body: Dict[str, Any] = {"task": req.task, "query": req.task, **req.payload}
        params = body if method == "GET" else None

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(url, params=params)
            else:
                response = await client.post(url, json=body)

        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        return {
            "agent": agent.name,
            "protocol": "rest",
            "status": "ok",
            "result": data,  # Changed from "data" to "result" to match frontend expectations
        }

    async def _dispatch_ws(self, agent: AgentConfig, req: OrchestrationRequest) -> Dict[str, Any]:
        conn = self.connections.get(agent.name)
        if not conn or not conn.connected or not conn.websocket:
            raise HTTPException(status_code=503, detail=f"Agent '{agent.name}' is not connected via websocket")

        timeout = req.timeout_seconds or agent.timeout_seconds
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.pending_ws[request_id] = future

        try:
            message = {
                "type": "task",
                "request_id": request_id,
                "task": req.task,
                "payload": req.payload,
            }
            await conn.websocket.send_json(message)
            result = await asyncio.wait_for(future, timeout=timeout)
            return {
                "agent": agent.name,
                "protocol": "ws",
                "status": "ok",
                "result": result,  # Changed from "data" to "result"
            }
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=504, detail=f"Timeout waiting for websocket response from '{agent.name}'") from exc
        finally:
            self.pending_ws.pop(request_id, None)

    async def orchestrate(self, req: OrchestrationRequest) -> Dict[str, Any]:
        agent = self._resolve_agent(req.target_agent)

        protocol = req.protocol
        if protocol == "auto":
            conn = self.connections.get(agent.name)
            has_ws = bool(conn and conn.connected and conn.websocket)
            if agent.protocol == "ws" and has_ws:
                protocol = "ws"
            elif agent.protocol == "ws" and not has_ws and agent.base_url:
                protocol = "rest"
            elif agent.protocol == "rest":
                protocol = "rest"
            else:
                protocol = "ws" if has_ws else "rest"

        if protocol == "ws":
            result = await self._dispatch_ws(agent, req)
        else:
            result = await self._dispatch_rest(agent, req)

        # Check if GraphRAG returned results - route to Content Creator for content generation
        if agent.name == "blaiq-graph-rag" and isinstance(result, dict):
            result_data = result.get("result", {})
            chunks_retrieved = result_data.get("chunks_retrieved", 0)

            # Detect content-creation tasks (visual/marketing outputs)
            task_lower = req.task.lower()
            content_creation_keywords = [
                "pitch deck", "pitchdeck", "poster", "flyer", "brochure",
                "one-pager", "one pager", "landing page", "webpage",
                "presentation", "slide deck", "slides", "visual",
                "generate poster", "create poster", "generate pitch",
                "create pitch", "marketing", "campaign", "banner"
            ]
            is_content_creation = any(kw in task_lower for kw in content_creation_keywords)

            if chunks_retrieved == 0 or is_content_creation:
                if chunks_retrieved == 0:
                    logger.info("GraphRAG returned 0 chunks, routing to Content Creator for gap analysis")
                else:
                    logger.info(f"Content creation task detected: '{req.task}', routing to Content Creator for visual synthesis")
                # Route to Content Creator with the original task and GraphRAG context
                content_agent = self._resolve_agent("blaiq-content-agent")
                if content_agent:
                    content_req = OrchestrationRequest(
                        task=req.task,
                        target_agent="blaiq-content-agent",
                        payload={
                            **req.payload,
                            "graphrag_context": result_data,  # Pass GraphRAG context (empty or with chunks)
                            "orchestrator_instruction": req.task,
                            "answers": req.payload.get("answers"),  # Pass answers if provided
                        },
                        protocol="auto",
                        method="POST",
                        timeout_seconds=300,
                    )
                    return await self._dispatch_rest(content_agent, content_req)
                else:
                    logger.warning("Content Creator agent not found, returning GraphRAG result")

        return result


orchestrator = CoreOrchestrator()
app = FastAPI(title="BLAIQ-CORE", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    body = await request.body()
    logger.error(f"Validation failed for {request.url}: {errors} | Body: {body.decode()}")
    return JSONResponse(
        status_code=422,
        content={"detail": errors, "body": body.decode()},
    )
static_dir = Path(__file__).resolve().parents[2] / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info("mounted_static directory=%s", static_dir)
else:
    logger.warning("static_directory_not_found path=%s", static_dir)


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": "BLAIQ-CORE",
        "status": "healthy",
        "default_agent": orchestrator.default_agent,
        "registered_agents": len(orchestrator.agents),
        "ui": "/static/core_client.html",
    }


@app.get("/agents")
async def list_agents() -> Dict[str, Any]:
    entries = []
    for name, cfg in orchestrator.agents.items():
        conn = orchestrator.connections.get(name)
        entries.append(
            {
                "name": name,
                "protocol": cfg.protocol,
                "base_url": cfg.base_url,
                "execute_path": cfg.execute_path,
                "stream_path": cfg.stream_path,
                "history_path": cfg.history_path,
                "supports_stream": cfg.supports_stream,
                "capabilities": cfg.capabilities,
                "connected_ws": bool(conn and conn.connected),
                "timeout_seconds": cfg.timeout_seconds,
            }
        )
    return {"agents": entries}


@app.get("/agents/live")
async def list_live_agents() -> Dict[str, Any]:
    entries = await orchestrator.get_live_agents()
    return {"agents": entries}


@app.post("/agents/register")
async def register_agent(req: AgentRegistrationRequest) -> Dict[str, Any]:
    return await orchestrator.register_agent(req)


@app.post("/orchestrate")
async def orchestrate_task(req: OrchestrationRequest) -> Dict[str, Any]:
    return await orchestrator.orchestrate(req)


@app.post("/query/graphrag")
async def query_graphrag(req: GraphRagQueryRequest) -> Dict[str, Any]:
    request = OrchestrationRequest(
        task="graphrag_query",
        target_agent=os.getenv("BLAIQ_GRAPHRAG_AGENT", "blaiq-graph-rag"),
        payload=req.model_dump(exclude_none=True),
        protocol="auto",
        method="POST",
        timeout_seconds=int(os.getenv("BLAIQ_GRAPHRAG_TIMEOUT_SECONDS", "180")),
    )
    return await orchestrator.orchestrate(request)


def _sse(data: Any) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


@app.post("/query/graphrag/stream")
async def query_graphrag_stream(req: GraphRagStreamRequest, http_request: Request) -> StreamingResponse:
    logger.info(f"Received stream request: {req.model_dump()}")
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    request_id = str(uuid.uuid4())
    start_ms = int(time.time() * 1000)
    tenant_id = req.tenant_id or http_request.headers.get("x-tenant-id") or "default"
    tenant_cfg = orchestrator.resolve_tenant_config(tenant_id)

    live_agents = await orchestrator.get_live_agents()
    decision = orchestrator.strategist_decide(query, req.session_id, live_agents)
    selected_agents = decision.get("selected_agents", [])
    primary_agent_name = decision.get("primary_agent")

    if not selected_agents:
        selected_agents = []
    if not primary_agent_name and selected_agents:
        primary_agent_name = selected_agents[0]

    logger.info(
        "stream_request_start request_id=%s session_id=%s query_len=%s selected_agents=%s primary=%s",
        request_id,
        req.session_id,
        len(query),
        selected_agents,
        primary_agent_name,
    )

    base_payload = req.model_dump(exclude_none=True)
    base_payload["tenant_id"] = tenant_cfg["tenant_id"]
    base_payload["collection_name"] = tenant_cfg["collection_name"]
    base_payload["qdrant_url"] = tenant_cfg.get("qdrant_url")
    base_payload["qdrant_api_key"] = tenant_cfg.get("qdrant_api_key")
    base_payload["neo4j_uri"] = tenant_cfg.get("neo4j_uri")
    base_payload["neo4j_user"] = tenant_cfg.get("neo4j_user")
    base_payload["neo4j_password"] = tenant_cfg.get("neo4j_password")
    base_payload["orchestrator_request_id"] = request_id
    base_payload["requested_capability"] = decision.get("requested_capability", "generic")

    forward_headers: Dict[str, str] = {}
    for h in ("x-api-key", "x-tenant-id"):
        if h in http_request.headers:
            forward_headers[h] = http_request.headers[h]
    forward_headers["x-tenant-id"] = tenant_cfg["tenant_id"]

    async def stream_generator():
        session_id = req.session_id
        current_primary_agent_name = primary_agent_name
        try:
            strategy_agent_name = current_primary_agent_name or "none"
            queued = orchestrator.set_state(request_id, "queued", strategy_agent_name, session_id=session_id)
            yield _sse({"agent_state": queued})
            yield _sse(
                {
                    "strategist": {
                        "request_id": request_id,
                        "reasoning": decision.get("reasoning"),
                        "route_mode": decision.get("route_mode"),
                        "requested_capability": decision.get("requested_capability"),
                        "tenant_id": tenant_cfg["tenant_id"],
                        "tenant_config": {
                            "collection_name": tenant_cfg.get("collection_name"),
                            "qdrant_url": tenant_cfg.get("qdrant_url"),
                            "neo4j_uri": tenant_cfg.get("neo4j_uri"),
                        },
                        "selected_agents": selected_agents,
                        "helper_agents": decision.get("helper_agents", []),
                        "primary_agent": current_primary_agent_name,
                        "live_agents": [
                            {
                                "name": a["name"],
                                "is_live": a["is_live"],
                                "supports_stream": a["supports_stream"],
                                "capabilities": a["capabilities"],
                            }
                            for a in live_agents
                        ],
                    }
                }
            )

            if not current_primary_agent_name:
                failed = orchestrator.set_state(
                    request_id,
                    "dispatch_failed",
                    "none",
                    session_id=session_id,
                    error="Strategist could not choose a live primary agent.",
                )
                yield _sse({"agent_state": failed})
                yield _sse({"log": "❌ STRATEGIST could not find a live primary agent."})
                yield _sse_done()
                return

            primary_agent = orchestrator._resolve_agent(current_primary_agent_name)
            if primary_agent.protocol == "ws" or not primary_agent.supports_stream:
                fallback_agent = orchestrator.choose_stream_fallback_agent(primary_agent.name, live_agents)
                if fallback_agent and fallback_agent.name != primary_agent.name:
                    yield _sse(
                        {
                            "log": (
                                f"⚠️ STRATEGIST selected '{primary_agent.name}', "
                                f"but it cannot stream. Falling back to '{fallback_agent.name}'."
                            )
                        }
                    )
                    primary_agent = fallback_agent
                    current_primary_agent_name = fallback_agent.name

            helper_outputs: Dict[str, Any] = {}
            for helper_name in decision.get("helper_agents", []):
                if helper_name == current_primary_agent_name:
                    continue
                helper_agent = orchestrator._resolve_agent(helper_name)
                helper_dispatch = orchestrator.set_state(request_id, "dispatching", helper_name, session_id=session_id)
                yield _sse({"agent_state": helper_dispatch})
                yield _sse({"log": f"🧩 STRATEGIST helper selected: {helper_name}"})

                helper_instruction = (decision.get("instructions") or {}).get(
                    helper_name,
                    "Process helper subtask and return concise structured JSON.",
                )
                helper_payload = {
                    **base_payload,
                    "orchestrator_instruction": helper_instruction,
                    "strategy_primary_agent": current_primary_agent_name,
                }

                try:
                    if helper_agent.base_url:
                        helper_url = f"{helper_agent.base_url.rstrip('/')}{helper_agent.execute_path}"
                        
                        # Build helper payload - use 'query' for GraphRAG, 'task' for others
                        helper_json = {"task": "helper_subtask", **helper_payload}
                        
                        # Special handling for GraphRAG helper - it expects 'query' not 'task'
                        if helper_name == "blaiq-graph-rag":
                            # Convert orchestrator_instruction or query to GraphRAG query field
                            query_text = helper_payload.get("orchestrator_instruction", "")
                            if not query_text:
                                query_text = helper_payload.get("query", "Gather comprehensive project intelligence")
                            helper_json = {
                                "query": query_text,
                                "session_id": helper_payload.get("session_id"),
                                "tenant_id": helper_payload.get("tenant_id"),
                                "room_number": helper_payload.get("room_number"),
                                "chat_history": helper_payload.get("chat_history"),
                                "collection_name": helper_payload.get("collection_name"),
                                "qdrant_url": helper_payload.get("qdrant_url"),
                                "qdrant_api_key": helper_payload.get("qdrant_api_key"),
                                "neo4j_uri": helper_payload.get("neo4j_uri"),
                                "neo4j_user": helper_payload.get("neo4j_user"),
                                "neo4j_password": helper_payload.get("neo4j_password"),
                                "include_graph": True,
                                "k": 15,
                                "use_reranker": False,
                                "use_cache": False,
                            }
                        
                        async with httpx.AsyncClient(timeout=helper_agent.timeout_seconds) as client:
                            helper_res = await client.post(helper_url, json=helper_json, headers=forward_headers)
                        if helper_res.status_code < 400:
                            helper_outputs[helper_name] = helper_res.json()
                            helper_done = orchestrator.set_state(request_id, "completed", helper_name, session_id=session_id)
                            yield _sse({"agent_state": helper_done})
                            yield _sse({"log": f"✅ Helper {helper_name} completed."})
                        else:
                            helper_fail = orchestrator.set_state(
                                request_id,
                                "agent_error",
                                helper_name,
                                session_id=session_id,
                                error=f"HTTP {helper_res.status_code}",
                            )
                            yield _sse({"agent_state": helper_fail})
                            yield _sse({"log": f"⚠️ Helper {helper_name} failed ({helper_res.status_code}). Continuing."})
                            # For GraphRAG 404 (no chunks found), treat as empty result, not failure
                            if helper_name == "blaiq-graph-rag" and helper_res.status_code == 404:
                                helper_outputs[helper_name] = {"data": {"results": []}, "note": "No chunks found"}
                                logger.info(f"GraphRAG 404 treated as empty result - content agent will proceed without context")
                    else:
                        helper_fail = orchestrator.set_state(
                            request_id,
                            "dispatch_failed",
                            helper_name,
                            session_id=session_id,
                            error="missing base_url",
                        )
                        yield _sse({"agent_state": helper_fail})
                        yield _sse({"log": f"⚠️ Helper {helper_name} skipped: missing base_url."})
                except Exception as exc:
                    helper_fail = orchestrator.set_state(
                        request_id,
                        "agent_error",
                        helper_name,
                        session_id=session_id,
                        error=str(exc),
                    )
                    yield _sse({"agent_state": helper_fail})
                    yield _sse({"log": f"⚠️ Helper {helper_name} error: {str(exc)}. Continuing."})

            dispatching = orchestrator.set_state(request_id, "dispatching", primary_agent.name, session_id=session_id)
            yield _sse({"agent_state": dispatching})
            yield _sse({"log": f"🤖 CORE selected primary agent: {primary_agent.name}"})
            if helper_outputs:
                yield _sse({"log": f"🧠 Helper context ready from: {', '.join(helper_outputs.keys())}"})

            if primary_agent.protocol == "ws":
                failed = orchestrator.set_state(
                    request_id,
                    "failed",
                    primary_agent.name,
                    session_id=session_id,
                    error="Streaming over WS agents is not supported yet.",
                )
                yield _sse({"agent_state": failed})
                yield _sse({"log": "❌ CORE stream dispatch failed: agent does not support REST stream passthrough."})
                yield _sse_done()
                return

            if not primary_agent.supports_stream:
                failed = orchestrator.set_state(
                    request_id,
                    "failed",
                    primary_agent.name,
                    session_id=session_id,
                    error="Agent streaming is disabled.",
                )
                yield _sse({"agent_state": failed})
                yield _sse({"log": f"❌ Agent '{primary_agent.name}' does not support streaming."})
                yield _sse_done()
                return

            if not primary_agent.base_url:
                failed = orchestrator.set_state(
                    request_id,
                    "dispatch_failed",
                    primary_agent.name,
                    session_id=session_id,
                    error="Agent base_url missing",
                )
                yield _sse({"agent_state": failed})
                yield _sse({"log": f"❌ Agent '{primary_agent.name}' missing base_url."})
                yield _sse_done()
                return

            stream_url = f"{primary_agent.base_url.rstrip('/')}{primary_agent.stream_path}"
            streaming = orchestrator.set_state(request_id, "streaming", primary_agent.name, session_id=session_id)
            yield _sse({"agent_state": streaming})

            stream_payload = {
                **base_payload,
                "orchestrator_instruction": (decision.get("instructions") or {}).get(
                    primary_agent.name,
                    "Process as delegated BLAIQ-CORE task; return SSE log/planning/delta/metrics contract.",
                ),
                "strategy_primary_agent": primary_agent.name,
                "strategy_selected_agents": selected_agents,
                "strategy_helper_outputs": helper_outputs,
            }

            timeout = int(os.getenv("BLAIQ_GRAPHRAG_TIMEOUT_SECONDS", str(primary_agent.timeout_seconds)))
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=timeout, read=timeout)) as client:
                async with client.stream("POST", stream_url, json=stream_payload, headers=forward_headers) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="ignore")
                        failed = orchestrator.set_state(
                            request_id,
                            "agent_error",
                            primary_agent.name,
                            session_id=session_id,
                            error=f"HTTP {response.status_code}",
                        )
                        yield _sse({"agent_state": failed})
                        yield _sse({"log": f"❌ Agent error: {response.status_code} {detail[:250]}"})
                        yield _sse_done()
                        return

                    passthrough_events = 0
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            parsed = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        passthrough_events += 1
                        yield _sse(parsed)

            completed = orchestrator.set_state(request_id, "completed", primary_agent.name, session_id=session_id)
            completed["latency_ms"] = int(time.time() * 1000) - start_ms
            logger.info(
                "stream_request_complete request_id=%s agent=%s session_id=%s latency_ms=%s passthrough_events=%s",
                request_id,
                primary_agent.name,
                session_id,
                completed["latency_ms"],
                passthrough_events,
            )
            yield _sse({"agent_state": completed})
            yield _sse_done()
        except httpx.TimeoutException:
            failed = orchestrator.set_state(
                request_id,
                "timeout",
                current_primary_agent_name or "none",
                session_id=req.session_id,
                error="Timeout while waiting for downstream agent stream",
            )
            yield _sse({"agent_state": failed})
            yield _sse({"log": "❌ CORE timeout waiting for agent stream."})
            yield _sse_done()
            logger.error(
                "stream_request_timeout request_id=%s agent=%s session_id=%s",
                request_id,
                current_primary_agent_name,
                req.session_id,
            )
        except Exception as exc:
            failed = orchestrator.set_state(
                request_id,
                "dispatch_failed",
                current_primary_agent_name or "none",
                session_id=req.session_id,
                error=str(exc),
            )
            yield _sse({"agent_state": failed})
            yield _sse({"log": f"❌ CORE dispatch failed: {str(exc)}"})
            yield _sse_done()
            logger.exception(
                "stream_request_error request_id=%s agent=%s session_id=%s",
                request_id,
                current_primary_agent_name,
                req.session_id,
            )

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.get("/history/{session_id}")
async def get_history(session_id: str, http_request: Request) -> Dict[str, Any]:
    target_agent_name = os.getenv("BLAIQ_GRAPHRAG_AGENT", "blaiq-graph-rag")
    agent = orchestrator._resolve_agent(target_agent_name)
    logger.info("history_proxy_request session_id=%s agent=%s", session_id, agent.name)

    if not agent.base_url:
        return {"session_id": session_id, "tenant": None, "history": []}

    supports_history = ("history" in agent.capabilities) or bool(agent.history_path)
    if not supports_history:
        return {"session_id": session_id, "tenant": None, "history": []}

    encoded_session = quote(session_id, safe="")
    path = (agent.history_path or "/history/{session_id}").replace("{session_id}", encoded_session)
    url = f"{agent.base_url.rstrip('/')}{path}"
    forward_headers: Dict[str, str] = {}
    for h in ("x-api-key", "x-tenant-id"):
        if h in http_request.headers:
            forward_headers[h] = http_request.headers[h]

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=forward_headers)
        if response.status_code >= 400:
            logger.warning("history_proxy_non_200 session_id=%s status=%s", session_id, response.status_code)
            return {"session_id": session_id, "tenant": None, "history": []}
        logger.info("history_proxy_success session_id=%s", session_id)
        return response.json()
    except Exception:
        logger.exception("history_proxy_error session_id=%s", session_id)
        return {"session_id": session_id, "tenant": None, "history": []}


@app.get("/sessions/{session_id}/agents")
async def get_session_agent_states(session_id: str) -> Dict[str, Any]:
    request_ids = orchestrator.session_request_index.get(session_id, [])
    states = [orchestrator.request_states[rid] for rid in request_ids if rid in orchestrator.request_states]
    return {"session_id": session_id, "states": states}


@app.websocket("/ws/agents/{agent_name}")
async def agent_websocket(websocket: WebSocket, agent_name: str) -> None:
    await websocket.accept()
    logger.info("agent_ws_connected agent=%s", agent_name)

    if agent_name not in orchestrator.agents:
        orchestrator.agents[agent_name] = AgentConfig(name=agent_name, protocol="ws")

    conn = orchestrator.connections.setdefault(agent_name, AgentConnection())
    conn.websocket = websocket
    conn.connected = True
    conn.last_error = None

    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "result":
                continue

            req_id = message.get("request_id")
            if not req_id:
                continue

            pending = orchestrator.pending_ws.get(req_id)
            if pending and not pending.done():
                pending.set_result(
                    {
                        "request_id": req_id,
                        "status": message.get("status", "ok"),
                        "data": message.get("data"),
                        "error": message.get("error"),
                    }
                )
    except WebSocketDisconnect:
        conn.connected = False
        logger.info("agent_ws_disconnected agent=%s", agent_name)
    except Exception as exc:
        conn.connected = False
        conn.last_error = str(exc)
        logger.exception("agent_ws_error agent=%s", agent_name)
    finally:
        conn.websocket = None


# ============================================================================
# FILE UPLOAD ENDPOINT
# ============================================================================

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    tenant_id: str = Form("default"),
    metadata: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """
    Upload a document file (PDF, DOCX, TXT, MD) for processing.

    The file will be:
    1. Chunked using intelligent document processing
    2. Embedded and stored in Qdrant (vector search)
    3. Entities extracted and stored in Neo4j (graph)

    Args:
        file: The uploaded file
        tenant_id: Tenant identifier for multi-tenant isolation
        metadata: Optional JSON string with additional metadata

    Returns:
        Processing results including chunk count and document ID
    """
    request_id = str(uuid.uuid4())
    start_time = time.time()

    logger.info(f"upload_start request_id={request_id} tenant_id={tenant_id} filename={file.filename}")

    # Validate file type
    allowed_extensions = ('.pdf', '.docx', '.txt', '.md')
    if not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {allowed_extensions}"
        )

    # Resolve tenant configuration
    tenant_cfg = orchestrator.resolve_tenant_config(tenant_id)
    logger.info(f"upload_tenant_config request_id={request_id} collection={tenant_cfg.get('collection_name')}")

    # Read file content
    try:
        file_content = await file.read()
        file_size = len(file_content)
        logger.info(f"upload_file_read request_id={request_id} size_bytes={file_size}")
    except Exception as e:
        logger.error(f"upload_file_read_error request_id={request_id} error={e}")
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    # Build payload for GraphRAG agent
    payload = {
        "request_id": request_id,
        "tenant_id": tenant_cfg["tenant_id"],
        "collection_name": tenant_cfg["collection_name"],
        "qdrant_url": tenant_cfg.get("qdrant_url"),
        "qdrant_api_key": tenant_cfg.get("qdrant_api_key"),
        "neo4j_uri": tenant_cfg.get("neo4j_uri"),
        "neo4j_user": tenant_cfg.get("neo4j_user"),
        "neo4j_password": tenant_cfg.get("neo4j_password"),
        "filename": file.filename,
        "file_content": file_content.decode('latin-1'),  # Encode binary as string for JSON
        "file_size": file_size,
        "metadata": json.loads(metadata) if metadata else {},
    }

    # Forward to GraphRAG agent for processing
    try:
        graphrag_agent = orchestrator._resolve_agent("blaiq-graph-rag")
        if not graphrag_agent:
            raise HTTPException(status_code=503, detail="GraphRAG agent not available")

        # Call GraphRAG upload endpoint directly
        upload_url = f"{graphrag_agent.base_url.rstrip('/')}/upload"
        logger.info(f"upload_forwarding request_id={request_id} url={upload_url}")

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(upload_url, json=payload)
            response.raise_for_status()
            result = response.json()

        elapsed = time.time() - start_time
        logger.info(f"upload_complete request_id={request_id} elapsed_seconds={elapsed:.2f}")

        return {
            "status": "success",
            "request_id": request_id,
            "tenant_id": tenant_cfg["tenant_id"],
            "filename": file.filename,
            "file_size": file_size,
            "processing_result": result,
            "elapsed_seconds": round(elapsed, 2),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"upload_processing_error request_id={request_id} error={e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
