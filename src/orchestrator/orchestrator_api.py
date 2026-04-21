import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

import httpx
import redis.asyncio as aioredis
from openai import OpenAI
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from orchestrator.contracts.envelope import MCPEnvelope
from orchestrator.contracts.manifests import ContentSchema
from orchestrator.observability import setup_otel, get_trace_headers
from utils.auth import verify_api_key
from utils.logging_utils import configure_service_logging, log_flow


ProtocolType = Literal["rest", "ws", "auto"]
configure_service_logging("blaiq-core")
logger = logging.getLogger("blaiq-core")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
LITELLM_STRATEGIST_MODEL = os.getenv("LITELLM_STRATEGIST_MODEL") or os.getenv("LITELLM_PLANNER_MODEL") or "openai/gpt-4o-mini"
STRATEGIST_ENABLED = os.getenv("STRATEGIST_ENABLED", "true").lower() == "true"
BLAIQ_UI_MODE = os.getenv("BLAIQ_UI_MODE", "auto").strip().lower()
VALID_UI_MODES = {"react", "legacy", "auto"}
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


def _default_collection_name(tenant_key: str) -> str:
    global_collection = os.getenv("QDRANT_COLLECTION", "default")
    if tenant_key != "default" and global_collection and global_collection != "default":
        return global_collection
    return tenant_key


def _resolve_ui_mode() -> str:
    requested = BLAIQ_UI_MODE if BLAIQ_UI_MODE in VALID_UI_MODES else "auto"
    if requested != BLAIQ_UI_MODE:
        logger.warning("invalid_ui_mode requested=%s fallback=auto", BLAIQ_UI_MODE)

    react_available = dist_dir.exists()
    if requested == "legacy":
        return "legacy"
    if requested == "react":
        if react_available:
            return "react"
        logger.warning("react_ui_requested_but_missing dist_dir=%s fallback=legacy", dist_dir)
        return "legacy"
    return "react" if react_available else "legacy"


def _ui_path() -> str:
    return "/app/" if UI_MODE == "react" else "/static/core_client.html"


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Any):
        try:
            return await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as exc:
            if exc.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise


@dataclass
class AgentConfig:
    name: str
    protocol: ProtocolType = "auto"
    base_url: Optional[str] = None
    execute_path: str = "/execute"
    stream_path: str = "/query/graphrag/stream"
    history_path: str = "/history/{session_id}"
    health_path: str = "/healthz"
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
    health_path: str = "/healthz"
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
6) Do NOT include content-creation agents unless the user explicitly asks to generate/design/create visual or presentation-style output.
7) For textual retrieval, revenue analysis, historical data, enterprise knowledge, or graph-backed research requests, route ONLY to `blaiq-graph-rag` when it is live.
8) Do NOT use `echo-agent` for production retrieval or analysis routes. Treat it as unavailable unless the user explicitly asks for it.

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

_CONTENT_GENERATION_KEYWORDS = [
    "pitch deck",
    "pitchdeck",
    "poster",
    "flyer",
    "brochure",
    "one-pager",
    "one pager",
    "landing page",
    "webpage",
    "presentation",
    "slide deck",
    "slides",
    "visual",
    "generate poster",
    "create poster",
    "generate pitch",
    "create pitch",
    "banner",
    "infographic",
    "mockup",
    "design layout",
]


def _is_content_generation_query(query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    return any(keyword in q for keyword in _CONTENT_GENERATION_KEYWORDS)


def _requires_content_hitl_for_plan(
    query: str,
    execution_plan: List[str],
    primary_agent: Optional[str] = None,
    workflow_mode: str = "standard",
) -> bool:
    plan = [str(step).lower() for step in execution_plan if isinstance(step, str)]
    primary = str(primary_agent or "").lower()
    return (
        workflow_mode == "creative"
        or _is_content_generation_query(query)
        or "content" in plan
        or "vangogh" in primary
        or "content" in primary
    )


class CoreOrchestrator:
    def __init__(self) -> None:
        self.default_agent = os.getenv("BLAIQ_DEFAULT_AGENT", "blaiq-graph-rag")
        self.agents: Dict[str, AgentConfig] = {}
        self.connections: Dict[str, AgentConnection] = {}
        self.pending_ws: Dict[str, asyncio.Future] = {}
        self.request_states: Dict[str, Dict[str, Any]] = {}
        self.session_request_index: Dict[str, List[str]] = {}
        # Per-session ring buffer of state transitions for realtime status tracking.
        self.session_timelines: Dict[str, deque[Dict[str, Any]]] = {}
        self.live_agent_cache: Dict[str, Dict[str, Any]] = {}
        self.live_agent_cache_ttl_seconds = int(os.getenv("BLAIQ_LIVE_AGENT_CACHE_TTL_SECONDS", "30"))
        self.live_probe_timeout_seconds = float(os.getenv("BLAIQ_LIVE_AGENT_PROBE_TIMEOUT_SECONDS", "1.5"))
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
                "collection_name": _default_collection_name(tenant_key),
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
        cfg.setdefault("collection_name", _default_collection_name(tenant_key))
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
                health_path=item.get("health_path", "/healthz"),
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
                health_path=req.health_path,
                supports_stream=req.supports_stream,
                capabilities=req.capabilities,
                method=req.method,
                timeout_seconds=req.timeout_seconds,
            )
            self.agents[req.name] = cfg
            self.connections.setdefault(req.name, AgentConnection())
        log_flow(
            logger,
            "agent_registered",
            name=req.name,
            protocol=req.protocol,
            base_url=req.base_url,
            agent_count=len(self.agents),
        )
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
        now_ms = int(time.time() * 1000)
        previous = self.request_states.get(request_id) or {}
        started_at_ms = previous.get("started_at_ms", now_ms)
        elapsed_ms = now_ms - started_at_ms
        state = {
            "request_id": request_id,
            "phase": phase,
            "agent": agent_name,
            "session_id": session_id,
            "error": error,
            "timestamp": now_ms,
            "started_at_ms": started_at_ms,
            "elapsed_ms": elapsed_ms,
        }
        self.request_states[request_id] = state
        if session_id:
            ids = self.session_request_index.setdefault(session_id, [])
            if request_id not in ids:
                ids.append(request_id)
            session_states = [self.request_states[rid] for rid in ids if rid in self.request_states]
            state["session_request_count"] = len(ids)
            state["session_agent_count"] = len({entry.get("agent") for entry in session_states if entry.get("agent")})
            state["session_phases"] = [entry.get("phase") for entry in session_states[-5:]]
            timeline = self.session_timelines.setdefault(session_id, deque(maxlen=200))
            timeline.append(
                {
                    "request_id": request_id,
                    "phase": phase,
                    "agent": agent_name,
                    "error": error,
                    "timestamp": now_ms,
                    "elapsed_ms": elapsed_ms,
                }
            )
        state_changed = (
            previous.get("phase") != phase
            or previous.get("agent") != agent_name
            or previous.get("error") != error
        )
        if state_changed or error:
            log_flow(
                logger,
                "request_state",
                level="error" if error else "info",
                request_id=request_id,
                session_id=session_id,
                phase=phase,
                agent=agent_name,
                error=error,
                elapsed_ms=elapsed_ms,
                session_request_count=state.get("session_request_count"),
                session_agent_count=state.get("session_agent_count"),
                session_phases=state.get("session_phases"),
            )
        return state

    async def get_live_agents(self) -> List[Dict[str, Any]]:
        live_entries: List[Dict[str, Any]] = []
        now = time.time()
        for name, cfg in self.agents.items():
            conn = self.connections.get(name)
            ws_live = bool(conn and conn.connected and conn.websocket)
            rest_live = False
            rest_error = None
            cache_entry = self.live_agent_cache.get(name) or {}
            cached_live = bool(cache_entry.get("is_live"))
            cached_at = float(cache_entry.get("checked_at", 0.0) or 0.0)
            cache_age = now - cached_at if cached_at else float("inf")
            if cfg.base_url:
                probe_paths = [cfg.health_path or "/healthz", "/", cfg.execute_path or "/execute"]
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(self.live_probe_timeout_seconds)) as client:
                        for probe_path in probe_paths:
                            for attempt in range(3):
                                try:
                                    res = await client.get(f"{cfg.base_url.rstrip('/')}{probe_path}")
                                    if res.status_code < 500:
                                        rest_live = True
                                        rest_error = None
                                        break
                                    rest_error = f"HTTP {res.status_code} @ {probe_path}"
                                except Exception as exc:
                                    rest_error = str(exc)
                                if rest_live:
                                    break
                                await asyncio.sleep(0.15 * (attempt + 1))
                            if rest_live:
                                break
                    if not rest_live and cached_live and cache_age <= max(self.live_agent_cache_ttl_seconds, 30):
                        rest_live = True
                        rest_error = cache_entry.get("rest_error") or rest_error
                except Exception as exc:
                    rest_error = str(exc)
                    if cached_live and cache_age <= max(self.live_agent_cache_ttl_seconds, 30):
                        rest_live = True

            is_live = ws_live or rest_live
            self.live_agent_cache[name] = {
                "is_live": is_live,
                "checked_at": now,
                "rest_error": rest_error,
            }
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
        decision = {
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
        return _prioritize_content_route_for_creation_query(query, decision, available)

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

        live_by_name = {str(agent.get("name")): agent for agent in live_agents if agent.get("is_live")}
        selected = [name for name in selected if name in live_by_name and not _is_echo_agent(live_by_name[name])]
        helpers = [name for name in helpers if name in live_by_name and not _is_echo_agent(live_by_name[name])]
        if primary in live_by_name and _is_echo_agent(live_by_name[primary]):
            primary = None
        if not selected and primary:
            selected = [primary]

        # Guardrail: content agent is only for explicit content-generation/design intent.
        if not _is_content_generation_query(query):
            non_content_selected = [
                name for name in selected
                if name in live_by_name and not _is_content_agent(live_by_name[name])
            ]
            non_content_helpers = [
                name for name in helpers
                if name in live_by_name and not _is_content_agent(live_by_name[name])
            ]
            # Only drop content agents when we still have at least one non-content route.
            if non_content_selected:
                selected = non_content_selected
                helpers = non_content_helpers
                if primary not in selected:
                    primary = selected[0]
                decision["requested_capability"] = "analysis"
                decision["reasoning"] = (
                    str(decision.get("reasoning") or "").strip()
                    + " Guardrail: content agent excluded because request is analysis/retrieval, not content generation."
                ).strip()

            graphrag_name = next(
                (name for name, agent in live_by_name.items() if _is_graphrag_agent(agent)),
                None,
            )
            if graphrag_name:
                selected = [graphrag_name]
                helpers = []
                primary = graphrag_name
                decision["requested_capability"] = "graphrag"
                decision["route_mode"] = "single"
                decision["reasoning"] = (
                    str(decision.get("reasoning") or "").strip()
                    + " Enforced: textual retrieval and analysis routes run only on blaiq-graph-rag; echo-agent removed."
                ).strip()

        decision["selected_agents"] = selected
        decision["helper_agents"] = [a for a in helpers if a != primary]
        decision["primary_agent"] = primary
        decision["instructions"] = decision.get("instructions") or {}
        return _prioritize_content_route_for_creation_query(query, decision, live_agents)

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

            # Detect explicit content-creation tasks (visual/presentation outputs only).
            is_content_creation = _is_content_generation_query(req.task)

            if is_content_creation:
                logger.info(
                    "Content creation task detected: '%s', routing to Content Creator for visual synthesis",
                    req.task,
                )
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


@app.on_event("startup")
async def _startup() -> None:
    setup_otel("blaiq-core")

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
# Serve Vite build (dist/) if available, fallback to static/ root for legacy HTML
dist_dir = static_dir / "dist"
UI_MODE = _resolve_ui_mode()
if UI_MODE == "react":
    app.mount("/app", SPAStaticFiles(directory=str(dist_dir), html=True), name="app")
    logger.info("mounted_vite_dist directory=%s", dist_dir)
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
        "ui_mode": UI_MODE,
        "ui": _ui_path(),
        "legacy_ui": "/static/core_client.html",
    }


@app.get("/api/v4/agents")
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
    entries.append(
        {
            "name": "core",
            "protocol": "internal",
            "capabilities": ["routing", "orchestration", "hitl", "state"],
            "supports_stream": True,
            "base_url": None,
            "ws_live": True,
            "rest_live": True,
            "is_live": True,
            "rest_error": None,
        }
    )
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

    log_flow(
        logger,
        "stream_request_start",
        request_id=request_id,
        session_id=req.session_id,
        tenant_id=tenant_cfg.get("tenant_id"),
        query_len=len(query),
        selected_agents=selected_agents,
        primary=primary_agent_name,
        route_mode=decision.get("route_mode"),
        requested_capability=decision.get("requested_capability"),
        has_history=bool(req.chat_history),
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
            log_flow(
                logger,
                "stream_request_complete",
                request_id=request_id,
                session_id=session_id,
                tenant_id=tenant_cfg.get("tenant_id"),
                agent=primary_agent.name,
                latency_ms=completed["latency_ms"],
                passthrough_events=passthrough_events,
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
            log_flow(
                logger,
                "stream_request_timeout",
                level="error",
                request_id=request_id,
                agent=current_primary_agent_name,
                session_id=req.session_id,
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
                "event=stream_request_error request_id=%s agent=%s session_id=%s err=%s",
                request_id,
                current_primary_agent_name,
                req.session_id,
                str(exc),
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


@app.get("/sessions/{session_id}/timeline")
async def get_session_timeline(session_id: str) -> Dict[str, Any]:
    timeline = list(orchestrator.session_timelines.get(session_id) or [])
    return {"session_id": session_id, "timeline": timeline}


@app.websocket("/ws/agents/{agent_name}")
async def agent_websocket(websocket: WebSocket, agent_name: str) -> None:
    await websocket.accept()
    log_flow(logger, "agent_ws_connected", agent=agent_name)

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
        log_flow(logger, "agent_ws_disconnected", agent=agent_name)
    except Exception as exc:
        conn.connected = False
        conn.last_error = str(exc)
        log_flow(logger, "agent_ws_error", level="error", agent=agent_name, error=str(exc))
    finally:
        conn.websocket = None


# ============================================================================
# FILE UPLOAD ENDPOINT
# ============================================================================

@app.post("/api/v4/upload")
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


# ============================================================
# V4 ORCHESTRATOR API — LangGraph + Temporal
# ============================================================

from datetime import datetime, timezone
from orchestrator.contracts.manifests import FinalArtifact, build_final_artifact

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = "blaiq-core-queue"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
BLAIQ_CONTENT_URL: str = os.getenv("BLAIQ_CONTENT_URL", "http://blaiq-content-agent:6003")
CONTENT_TIMEOUT: int = int(os.getenv("BLAIQ_CONTENT_TIMEOUT_SECONDS", "300"))
CLAIM_CHECK_THRESHOLD: int = 50_000  # bytes
CHAT_EXPORT_DIR = Path(os.getenv("CHAT_EXPORT_DIR", "/app/data/chat_exports"))
PREVIEW_PUBSUB_PREFIX: str = os.getenv("BLAIQ_PREVIEW_PUBSUB_PREFIX", "blaiq:preview:")


async def _preview_pubsub_listener(
    thread_id: str,
    out_q: "asyncio.Queue[tuple[str, Dict[str, Any]]]",
    stop: asyncio.Event,
) -> None:
    """Listen for progressive preview events published by content_node and forward them."""
    channel = f"{PREVIEW_PUBSUB_PREFIX}{thread_id}"
    try:
        async with aioredis.from_url(REDIS_URL) as redis_client:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)
            try:
                while not stop.is_set():
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if not msg:
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", "ignore")
                    if not isinstance(data, str):
                        continue
                    try:
                        event = json.loads(data)
                    except Exception:
                        continue
                    if not isinstance(event, dict):
                        continue

                    etype = str(event.get("normalized_type") or event.get("type") or "")
                    if not etype:
                        continue

                    payload = {k: v for k, v in event.items() if k != "type"}
                    # Ensure CORE remains the source of truth for ordering/timestamps.
                    payload.pop("sequence", None)
                    payload.pop("event_ts", None)
                    payload.setdefault("content_agent_type", event.get("type"))
                    await out_q.put((etype, payload))
            finally:
                try:
                    await pubsub.unsubscribe(channel)
                except Exception:
                    pass
    except Exception:
        # Preview is best-effort; failure here should not break orchestrator streaming.
        return

# Canonical mapping from LangGraph node names to SSE event types.
_NODE_EVENT_MAP: Dict[str, str] = {
    "planner": "planning",
    "graphrag_node": "evidence_ready",
    "graphrag": "evidence_ready",
    "content_node": "content_ready",
    "content": "content_ready",
    "governance_node": "governance",
    "governance": "governance",
}


def _normalized_stream_type(event_type: str, payload: Dict[str, Any]) -> str:
    """Translate legacy stream names into the new chat-first event vocabulary."""
    if event_type in {"content_ready", "regen_started"}:
        return "rendering_started"
    if event_type == "evidence_ready":
        if payload.get("post_hitl_refresh_needed") or payload.get("refresh_after_hitl"):
            return "evidence_refreshed"
        return "evidence_summary"
    if event_type in {"complete", "regen_complete"}:
        return "artifact_ready"
    return event_type


def _summarize_evidence_manifest(manifest: Any) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}

    summary = manifest.get("summary")
    summary_text = ""
    if isinstance(summary, dict):
        summary_text = str(
            summary.get("text")
            or summary.get("summary")
            or summary.get("answer")
            or summary.get("message")
            or ""
        )
    elif isinstance(summary, str):
        summary_text = summary

    chunks = manifest.get("chunks") or []
    if not isinstance(chunks, list):
        chunks = []

    return {
        "summary": summary_text[:500],
        "chunk_count": len(chunks),
        "has_graph": bool(manifest.get("graph")),
        "artifact_uri": manifest.get("artifact_uri"),
    }


def _artifact_payload_from_final_artifact(final_artifact: Any) -> Dict[str, Any]:
    if not isinstance(final_artifact, dict):
        return {}
    content = final_artifact.get("html_artifact") or final_artifact.get("approved_output") or ""
    schema_data = final_artifact.get("schema_data") or {}
    return {
        "artifact_kind": final_artifact.get("kind"),
        "validation_passed": final_artifact.get("validation_passed"),
        "html_chars": len(content) if isinstance(content, str) else 0,
        "schema_keys": sorted(schema_data.keys()) if isinstance(schema_data, dict) else [],
    }


def _content_preview_payload(content_draft: Any) -> Dict[str, Any]:
    if not isinstance(content_draft, dict):
        return {}
    html_artifact = content_draft.get("html_artifact") or ""
    schema_data = content_draft.get("schema_data") or {}
    return {
        "artifact_kind": content_draft.get("kind") or content_draft.get("artifact_kind") or "content",
        "html_chars": len(html_artifact) if isinstance(html_artifact, str) else 0,
        "schema_keys": sorted(schema_data.keys()) if isinstance(schema_data, dict) else [],
    }


def _streamed_preview_events(streamed_events: Any) -> List[Dict[str, Any]]:
    if not isinstance(streamed_events, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in streamed_events:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def _is_graphrag_agent(agent: Dict[str, Any]) -> bool:
    capabilities = {str(c).lower() for c in (agent.get("capabilities") or [])}
    name = str(agent.get("name", "")).lower()
    return "graphrag" in capabilities or "graph-rag" in name or "graphrag" in name


def _is_content_agent(agent: Dict[str, Any]) -> bool:
    capabilities = {str(c).lower() for c in (agent.get("capabilities") or [])}
    name = str(agent.get("name", "")).lower()
    return (
        "content_creation" in capabilities
        or "content" in capabilities
        or "content-agent" in name
        or "content" in name
    )


def _is_echo_agent(agent: Dict[str, Any]) -> bool:
    return str(agent.get("name", "")).strip().lower() == "echo-agent"


def _build_execution_plan_from_strategy(
    decision: Dict[str, Any],
    live_agents: List[Dict[str, Any]],
    workflow_mode: str,
) -> List[str]:
    live_by_name = {str(agent.get("name")): agent for agent in live_agents if agent.get("is_live")}
    selected_names = [str(name) for name in (decision.get("selected_agents") or []) if str(name) in live_by_name]
    primary_name = str(decision.get("primary_agent") or "")
    if primary_name and primary_name not in selected_names and primary_name in live_by_name:
        selected_names.append(primary_name)

    steps: List[str] = []
    has_graphrag = any(_is_graphrag_agent(live_by_name[name]) for name in selected_names)
    has_content = any(_is_content_agent(live_by_name[name]) for name in selected_names)

    requested_capability = str(decision.get("requested_capability") or "").lower()
    if requested_capability == "graphrag" and not has_graphrag:
        has_graphrag = any(_is_graphrag_agent(agent) for agent in live_agents if agent.get("is_live"))
    if requested_capability in {"workflow", "analysis", "generic"} and not has_graphrag:
        has_graphrag = True

    if requested_capability == "workflow" and not has_content:
        has_content = any(_is_content_agent(agent) for agent in live_agents if agent.get("is_live"))

    if workflow_mode == "creative":
        has_content = has_content or any(_is_content_agent(agent) for agent in live_agents if agent.get("is_live"))

    if has_graphrag:
        steps.append("graphrag")
    if has_content:
        steps.append("content")
    if "governance" not in steps:
        steps.append("governance")
    return steps


def _prioritize_content_route_for_creation_query(
    query: str,
    decision: Dict[str, Any],
    live_agents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _is_content_generation_query(query):
        return decision

    live_content = [a for a in live_agents if a.get("is_live") and _is_content_agent(a)]
    if not live_content:
        return decision

    content_name = str(live_content[0].get("name"))
    selected = [content_name]

    # Keep GraphRAG as helper when available so evidence is prepared first.
    graphrag = next((a for a in live_agents if a.get("is_live") and _is_graphrag_agent(a)), None)
    helpers: List[str] = []
    if graphrag:
        helpers.append(str(graphrag.get("name")))
        selected = helpers + selected

    decision["requested_capability"] = "workflow"
    decision["primary_agent"] = content_name
    decision["selected_agents"] = selected
    decision["helper_agents"] = helpers
    decision["route_mode"] = "sequential"
    decision["reasoning"] = (
        str(decision.get("reasoning") or "").strip()
        + " Enforced: creation intent routes primary to content agent with GraphRAG evidence helper."
    ).strip()
    return decision


def _build_workflow_plan_payload(
    *,
    strategy_decision: Dict[str, Any],
    execution_plan: List[str],
    live_agents: List[Dict[str, Any]],
    current_stage_id: str,
    current_status: str,
    workflow_complete: bool = False,
    hitl_mode: str = "",
    hitl_node: str = "",
    content_director_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    live_by_name = {
        str(agent.get("name")): agent
        for agent in live_agents
        if agent.get("name") and agent.get("is_live")
    }
    agents = [str(agent) for agent in (strategy_decision.get("selected_agents") or []) if str(agent)]
    primary = str(strategy_decision.get("primary_agent") or "")
    if primary and primary not in agents:
        agents.append(primary)

    has_content = any(
        _is_content_agent(live_by_name.get(name, {"name": name, "capabilities": []}))
        for name in agents
    )
    has_graph = any(
        _is_graphrag_agent(live_by_name.get(name, {"name": name, "capabilities": []}))
        for name in agents
    )

    stages: List[Dict[str, Any]] = [
        {"id": "routing", "label": "Routing", "agent": "Strategist", "state": "pending", "order": 1},
    ]
    if has_graph or "graphrag" in execution_plan:
        stages.append({"id": "evidence", "label": "Evidence", "agent": "GraphRAG", "state": "pending", "order": 2})
    if has_content or "content" in execution_plan:
        stages.extend(
            [
                {"id": "content_director", "label": "Content Director", "agent": "Core + Content", "state": "pending", "order": 3},
                {"id": "hitl", "label": "Human Review", "agent": "User + Core", "state": "pending", "order": 4},
                {"id": "rendering", "label": "Rendering", "agent": "Vangogh", "state": "pending", "order": 5},
            ]
        )
    stages.extend(
        [
            {"id": "governance", "label": "Governance", "agent": "Governance", "state": "pending", "order": 90},
            {"id": "delivery", "label": "Delivery", "agent": "Core", "state": "pending", "order": 100},
        ]
    )

    active_order = {
        "routing": 1,
        "evidence": 2,
        "content_director": 3,
        "hitl": 4,
        "rendering": 5,
        "governance": 90,
        "delivery": 100,
    }
    if current_stage_id not in active_order:
        if workflow_complete:
            current_stage_id = "delivery"
        elif current_status in {"blocked_on_user", "blocked"}:
            current_stage_id = "hitl" if any(stage["id"] == "hitl" for stage in stages) else "routing"
        else:
            current_stage_id = "routing"

    current_rank = active_order.get(current_stage_id, 1)
    for stage in stages:
        stage_rank = active_order.get(stage["id"], stage["order"])
        if workflow_complete:
            stage["state"] = "done"
        elif stage_rank < current_rank:
            stage["state"] = "done"
        elif stage["id"] == current_stage_id:
            stage["state"] = "blocked" if current_status in {"blocked_on_user", "blocked"} and stage["id"] == "hitl" else "active"
        else:
            stage["state"] = "pending"

    completed = sum(1 for stage in stages if stage["state"] == "done")
    progress_pct = 100 if workflow_complete else round((completed / max(1, len(stages))) * 100)

    return {
        "schema_version": "workflow_plan.v1",
        "route_mode": str(strategy_decision.get("route_mode") or ""),
        "primary_agent": str(strategy_decision.get("primary_agent") or ""),
        "helper_agents": [str(agent) for agent in (strategy_decision.get("helper_agents") or []) if str(agent)],
        "selected_agents": [str(agent) for agent in (strategy_decision.get("selected_agents") or []) if str(agent)],
        "current_stage_id": current_stage_id,
        "current_status": current_status,
        "workflow_complete": workflow_complete,
        "hitl_mode": hitl_mode,
        "hitl_node": hitl_node,
        "stages": stages,
        "progress_pct": progress_pct,
        "content_director_plan": content_director_plan or {},
    }


class WorkflowStatus(BaseModel):
    """Standardized workflow status returned by /status/{thread_id}."""
    thread_id: str
    execution_mode: str  # "temporal" | "direct"
    status: str
    current_node: str = ""
    hitl_required: bool = False
    hitl_questions: List[str] = Field(default_factory=list)
    error_message: str = ""
    final_artifact: Optional[Dict[str, Any]] = None
    updated_at: str = ""  # ISO timestamp


async def _resolve_html_artifact(artifact_uri: str) -> Optional[str]:
    if not artifact_uri or not artifact_uri.startswith("redis://"):
        return None
    redis_key = artifact_uri.replace("redis://", "", 1)
    try:
        async with aioredis.from_url(REDIS_URL) as redis_client:
            raw = await redis_client.get(redis_key)
        if raw:
            return raw.decode()
    except Exception as exc:
        logger.warning("artifact_resolve_error key=%s err=%s", redis_key, exc)
    return None


async def _store_html_artifact(mission_id: str, html: str) -> Optional[str]:
    if not html:
        return None
    redis_key = f"artifact:content:{mission_id}"
    try:
        async with aioredis.from_url(REDIS_URL) as redis_client:
            await redis_client.set(redis_key, html.encode(), ex=3600)
        return f"redis://{redis_key}"
    except Exception as exc:
        logger.warning("artifact_store_error key=%s err=%s", redis_key, exc)
    return None

_temporal_client = None
_temporal_lock = asyncio.Lock()


async def _get_temporal_client():
    global _temporal_client
    if _temporal_client is not None:
        return _temporal_client
    async with _temporal_lock:
        # Double-check after acquiring lock
        if _temporal_client is not None:
            return _temporal_client
        try:
            from temporalio.client import Client as TemporalClient
            _temporal_client = await TemporalClient.connect(
                TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE
            )
            logger.info("temporal_connected host=%s namespace=%s", TEMPORAL_HOST, TEMPORAL_NAMESPACE)
        except Exception as exc:
            logger.warning("temporal_unavailable error=%s — falling back to direct LangGraph", exc)
            return None
    return _temporal_client


class SubmitRequest(BaseModel):
    """V4 workflow submission request."""
    tenant_id: str = Field(..., description="Tenant identifier for multi-tenancy isolation")
    user_query: str = Field(..., min_length=1, description="Natural language task or question")
    workflow_mode: str = Field(default="standard", description="standard | deep_research | creative")
    collection_name: Optional[str] = Field(default=None, description="Qdrant collection; defaults to tenant_id")
    session_id: Optional[str] = Field(default=None, description="Session ID for history tracking")
    room_number: Optional[str] = Field(default=None, description="Browser room or tab identifier")
    chat_history: Optional[List[Dict[str, str]]] = Field(default=None, description="Recent browser conversation turns")
    use_template_engine: Optional[bool] = Field(
        default=None,
        description="Enable Vangogh v2 template engine for content-generation workflows",
    )


class ResumeRequest(BaseModel):
    """V4 HITL resume request."""
    thread_id: str = Field(..., description="Thread ID from the submit response")
    agent_node: str = Field(default="content_node", description="Node that requested HITL")
    answers: Dict[str, str] = Field(..., description="User answers to HITL questions")
    tenant_id: Optional[str] = Field(
        default=None,
        description="Optional tenant identifier for compatibility with tenant-scoped clients",
    )
    session_id: Optional[str] = Field(default=None, description="Frontend session identifier")
    room_number: Optional[str] = Field(default=None, description="Browser room or tab identifier")
    chat_history: Optional[List[Dict[str, str]]] = Field(default=None, description="Recent browser conversation turns")


class RegenerateRequest(BaseModel):
    """V4 schema regeneration request."""
    thread_id: str = Field(..., description="Thread ID from the submit response")
    patched_schema: ContentSchema = Field(..., description="User-edited schema values")
    workflow_mode: str = Field(default="standard", description="standard | deep_research | creative")


class ChatSnapshotRequest(BaseModel):
    """Persist a frontend chat/workflow snapshot to local storage."""
    tenant_id: str = Field(default="default", description="Tenant identifier")
    thread_id: Optional[str] = Field(default=None, description="Workflow thread identifier")
    session_id: str = Field(..., description="Frontend session identifier")
    run_id: Optional[str] = Field(default=None, description="Workflow run identifier")
    workflow_mode: Optional[str] = Field(default=None, description="Workflow mode")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Chat transcript entries")
    timeline: List[Dict[str, Any]] = Field(default_factory=list, description="Execution timeline entries")
    artifact: Optional[Dict[str, Any]] = Field(default=None, description="Artifact preview state")
    governance: Optional[Dict[str, Any]] = Field(default=None, description="Governance state")
    schema_state: Optional[Dict[str, Any]] = Field(
        default=None,
        alias="schema",
        description="Schema editor state",
    )
    status: Optional[Dict[str, Any]] = Field(default=None, description="Latest status payload")

    model_config = {"populate_by_name": True}


@app.post("/api/v4/orchestrator/submit")
async def v4_submit(req: SubmitRequest, _: str = Depends(verify_api_key)):
    """Submit a workflow to the LangGraph + Temporal orchestrator. Returns SSE stream."""
    thread_id = str(uuid.uuid4())
    session_id = req.session_id or str(uuid.uuid4())
    collection_name = req.collection_name or req.tenant_id
    log_flow(
        logger,
        "wf_submit_received",
        thread_id=thread_id,
        session_id=session_id,
        tenant_id=req.tenant_id,
        workflow_mode=req.workflow_mode,
        collection_name=collection_name,
        query_chars=len(req.user_query),
    )

    async def _stream_events():
        # Try Temporal first, fall back to direct LangGraph
        temporal = await _get_temporal_client()
        execution_mode = "temporal" if temporal else "direct"
        live_agents = await orchestrator.get_live_agents()
        strategist_decision = orchestrator.strategist_decide(req.user_query, session_id, live_agents)
        strategy_execution_plan = _build_execution_plan_from_strategy(
            strategist_decision,
            live_agents,
            req.workflow_mode,
        )

        live_summary = [
            {
                "name": agent.get("name"),
                "is_live": bool(agent.get("is_live")),
                "capabilities": agent.get("capabilities", []),
            }
            for agent in live_agents
        ]
        log_flow(
            logger,
            "wf_routing_decision",
            thread_id=thread_id,
            session_id=session_id,
            execution_mode=execution_mode,
            primary_agent=strategist_decision.get("primary_agent"),
            selected_agents=strategist_decision.get("selected_agents", []),
            helper_agents=strategist_decision.get("helper_agents", []),
            route_mode=strategist_decision.get("route_mode", ""),
            requested_capability=strategist_decision.get("requested_capability", ""),
            strategy_execution_plan=strategy_execution_plan,
        )
        log_flow(
            logger,
            "wf_dispatch_start",
            thread_id=thread_id,
            session_id=session_id,
            execution_mode=execution_mode,
        )

        event_sequence = 0

        def _event(event_type: str, **payload: Any) -> str:
            nonlocal event_sequence
            event_sequence += 1
            payload.setdefault("execution_mode", execution_mode)
            payload.setdefault("event_ts", datetime.now(timezone.utc).isoformat())
            payload.setdefault("sequence", event_sequence)
            payload.setdefault("normalized_type", _normalized_stream_type(event_type, payload))
            return f"data: {json.dumps({'type': event_type, **payload})}\n\n"

        orchestrator.set_state(thread_id, "queued", "orchestrator", session_id=session_id)
        # Emit submitted event
        yield _event("submitted", thread_id=thread_id, session_id=session_id)
        yield _event(
            "routing_decision",
            thread_id=thread_id,
            session_id=session_id,
            strategy=strategist_decision,
            strategy_execution_plan=strategy_execution_plan,
            workflow_plan=_build_workflow_plan_payload(
                strategy_decision=strategist_decision,
                execution_plan=strategy_execution_plan,
                live_agents=live_agents,
                current_stage_id="routing",
                current_status="running",
            ),
            live_agents=live_summary,
            primary_agent=strategist_decision.get("primary_agent"),
            selected_agents=strategist_decision.get("selected_agents", []),
            helper_agents=strategist_decision.get("helper_agents", []),
            route_mode=strategist_decision.get("route_mode", ""),
            requested_capability=strategist_decision.get("requested_capability", ""),
            reasoning=strategist_decision.get("reasoning", ""),
            execution_plan=strategy_execution_plan,
        )

        if temporal:
            try:
                from orchestrator.temporal_worker import (
                    BlaiqOrchestrationWorkflow,
                    WorkflowInput,
                )

                wf_input = WorkflowInput(
                    thread_id=thread_id,
                    session_id=session_id,
                    tenant_id=req.tenant_id,
                    collection_name=collection_name,
                    user_query=req.user_query,
                    room_number=req.room_number or "",
                    chat_history=req.chat_history or [],
                    workflow_mode=req.workflow_mode,
                    use_template_engine=(
                        req.use_template_engine
                        if req.use_template_engine is not None
                        else _is_content_generation_query(req.user_query)
                    ),
                    strategy_execution_plan=strategy_execution_plan,
                    strategy_selected_agents=strategist_decision.get("selected_agents", []),
                    strategy_primary_agent=strategist_decision.get("primary_agent", ""),
                    strategy_route_mode=strategist_decision.get("route_mode", ""),
                    strategy_reasoning=strategist_decision.get("reasoning", ""),
                    content_requires_hitl=_requires_content_hitl_for_plan(
                        req.user_query,
                        strategy_execution_plan,
                        strategist_decision.get("primary_agent", ""),
                        req.workflow_mode,
                    ),
                )

                handle = await temporal.start_workflow(
                    BlaiqOrchestrationWorkflow.run,
                    wf_input,
                    id=f"blaiq-{thread_id}",
                    task_queue=TEMPORAL_TASK_QUEUE,
                )

                orchestrator.set_state(
                    thread_id,
                    "dispatching",
                    "temporal-workflow",
                    session_id=session_id,
                )
                yield _event("workflow_started", run_id=handle.result_run_id, thread_id=thread_id)
                log_flow(
                    logger,
                    "wf_temporal_started",
                    thread_id=thread_id,
                    session_id=session_id,
                    run_id=handle.result_run_id,
                )

                # Poll workflow status until complete or blocked
                preview_q: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue()
                stop_preview = asyncio.Event()
                preview_task: Optional[asyncio.Task] = None
                if wf_input.use_template_engine:
                    preview_task = asyncio.create_task(
                        _preview_pubsub_listener(thread_id, preview_q, stop_preview)
                    )
                prev_node = ""
                for _ in range(600):  # max 10 min polling
                    try:
                        # Drain any progressive preview events published by the content node.
                        try:
                            while True:
                                etype, payload = preview_q.get_nowait()
                                yield _event(etype, **payload)
                        except asyncio.QueueEmpty:
                            pass

                        status = await handle.query(BlaiqOrchestrationWorkflow.get_status)

                        current_node = ""
                        result = status.get("result")
                        if isinstance(result, dict):
                            current_node = result.get("current_node", "")

                        orchestrator.set_state(
                            thread_id,
                            status.get("status", "running"),
                            current_node or status.get("hitl_node", "temporal-workflow"),
                            session_id=session_id,
                        )

                        # Emit node-transition events (not just raw status)
                        if current_node and current_node != prev_node:
                            event_type = _NODE_EVENT_MAP.get(current_node, "progress")
                            event_payload: Dict[str, Any] = {
                                "node": current_node,
                                "status": status.get("status", "running"),
                            }
                            result_payload = result if isinstance(result, dict) else {}
                            if current_node in ("graphrag", "graphrag_node"):
                                event_payload["evidence_summary"] = _summarize_evidence_manifest(
                                    result_payload.get("evidence_manifest")
                                )
                                event_payload["post_hitl_refresh_needed"] = bool(
                                    result_payload.get("post_hitl_refresh_needed")
                                )
                            if current_node in ("content", "content_node"):
                                event_payload["artifact_preview"] = _content_preview_payload(
                                    result_payload.get("content_draft")
                                )
                                streamed_events = _streamed_preview_events(
                                    result_payload.get("streamed_events")
                                )
                                for streamed_event in streamed_events:
                                    streamed_type = str(
                                        streamed_event.get("normalized_type")
                                        or streamed_event.get("type")
                                        or "progress"
                                    )
                                    streamed_payload = {
                                        k: v
                                        for k, v in streamed_event.items()
                                        if k not in {"type", "normalized_type", "sequence"}
                                    }
                                    yield _event(streamed_type, **streamed_payload)
                                if result_payload.get("content_draft"):
                                    event_type = "content_ready"
                            yield _event(event_type, **event_payload)
                            log_flow(
                                logger,
                                "wf_node_transition",
                                thread_id=thread_id,
                                session_id=session_id,
                                execution_mode="temporal",
                                node=current_node,
                                status=status.get("status", "running"),
                            )
                            prev_node = current_node
                        else:
                            yield _event("progress", status=status.get("status", "running"))

                        if status.get("status") in ("complete", "error"):
                            final_state = result if isinstance(result, dict) else {}
                            orchestrator.set_state(
                                thread_id,
                                status.get("status", "complete"),
                                current_node or status.get("hitl_node", "temporal-workflow"),
                                session_id=session_id,
                            )
                            final = build_final_artifact(final_state)
                            final_payload = final.model_dump(mode="json")
                            yield _event(
                                "complete",
                                final_artifact=final_payload,
                                artifact_ready=_artifact_payload_from_final_artifact(final_payload),
                            )
                            log_flow(
                                logger,
                                "wf_complete",
                                thread_id=thread_id,
                                session_id=session_id,
                                execution_mode="temporal",
                                final_kind=final.kind,
                                validation_passed=final.validation_passed,
                            )
                            break
                        elif status.get("status") == "blocked_on_user":
                            result = status.get("result", {})
                            orchestrator.set_state(
                                thread_id,
                                "blocked_on_user",
                                status.get("hitl_node", "content_node"),
                                session_id=session_id,
                            )
                            yield _event(
                                "hitl_required",
                                thread_id=thread_id,
                                questions=result.get("hitl_questions", []),
                                node=result.get("hitl_node", "content_node"),
                                agent_node=result.get("hitl_node", "content_node"),
                            )
                            log_flow(
                                logger,
                                "wf_hitl_blocked",
                                thread_id=thread_id,
                                session_id=session_id,
                                execution_mode="temporal",
                                node=result.get("hitl_node", "content_node"),
                                questions=len(result.get("hitl_questions", [])),
                            )
                            break
                    except Exception as poll_exc:
                        logger.warning("temporal_poll_error thread_id=%s err=%s", thread_id, poll_exc)
                        # Break on non-retryable errors (workflow not found, etc.)
                        err_str = str(poll_exc).lower()
                        if "not found" in err_str or "terminated" in err_str:
                            yield _event("error", message=str(poll_exc))
                            log_flow(
                                logger,
                                "wf_error",
                                level="error",
                                thread_id=thread_id,
                                session_id=session_id,
                                execution_mode="temporal",
                                error=str(poll_exc),
                            )
                            break

                    await asyncio.sleep(1)
                stop_preview.set()
                if preview_task:
                    preview_task.cancel()
                    try:
                        await preview_task
                    except Exception:
                        pass

            except Exception as exc:
                logger.error("temporal_workflow_error thread_id=%s error=%s", thread_id, exc)
                orchestrator.set_state(
                    thread_id,
                    "error",
                    "temporal-workflow",
                    session_id=session_id,
                    error=str(exc),
                )
                yield _event("error", message=str(exc))
                log_flow(
                    logger,
                    "wf_error",
                    level="error",
                    thread_id=thread_id,
                    session_id=session_id,
                    execution_mode="temporal",
                    error=str(exc),
                )

        else:
            # Direct LangGraph execution (no Temporal)
            try:
                from orchestrator.graph import build_graph

                graph = await build_graph(REDIS_URL)
                config = {"configurable": {"thread_id": thread_id}}
                orchestrator.set_state(thread_id, "dispatching", "direct-langgraph", session_id=session_id)
                use_template_engine = (
                    req.use_template_engine
                    if req.use_template_engine is not None
                    else _is_content_generation_query(req.user_query)
                )
                initial_state = {
                    "thread_id": thread_id,
                    "session_id": session_id,
                    "tenant_id": req.tenant_id,
                    "collection_name": collection_name,
                    "user_query": req.user_query,
                    "room_number": req.room_number or "",
                    "chat_history": req.chat_history or [],
                    "workflow_mode": req.workflow_mode,
                    "use_template_engine": use_template_engine,
                    "strategy_execution_plan": strategy_execution_plan,
                    "strategy_selected_agents": strategist_decision.get("selected_agents", []),
                    "strategy_primary_agent": strategist_decision.get("primary_agent", ""),
                    "strategy_route_mode": strategist_decision.get("route_mode", ""),
                    "strategy_reasoning": strategist_decision.get("reasoning", ""),
                    "run_id": "",
                    "execution_plan": [],
                    "extracted_entities": [],
                    "keywords": [],
                    "evidence_manifest": None,
                    "content_draft": None,
                    "hitl_required": False,
                    "hitl_questions": [],
                    "hitl_answers": {},
                    "hitl_node": "",
                    "post_hitl_search_prompt_template": "",
                    "content_requires_hitl": _requires_content_hitl_for_plan(
                        req.user_query,
                        strategy_execution_plan,
                        strategist_decision.get("primary_agent", ""),
                        req.workflow_mode,
                    ),
                    "post_hitl_refresh_needed": False,
                    "governance_report": None,
                    "current_node": "",
                    "status": "starting",
                    "error_message": "",
                    "logs": [],
                }

                # Merge LangGraph node updates and progressive content preview events.
                out_q: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue()
                stop_preview = asyncio.Event()
                preview_task: Optional[asyncio.Task] = None
                if use_template_engine:
                    preview_task = asyncio.create_task(
                        _preview_pubsub_listener(thread_id, out_q, stop_preview)
                    )

                async def _run_graph() -> None:
                    try:
                        async for event in graph.astream(initial_state, config=config, stream_mode="updates"):
                            for node_name, node_output in event.items():
                                orchestrator.set_state(
                                    thread_id,
                                    node_output.get("status", "running"),
                                    node_name,
                                    session_id=session_id,
                                )
                                event_type = _NODE_EVENT_MAP.get(node_name, "progress")
                                if node_name in ("content", "content_node") and node_output.get("hitl_required"):
                                    event_type = "hitl_required"

                                event_payload: Dict[str, Any] = {
                                    "node": node_name,
                                    "thread_id": thread_id,
                                    "session_id": session_id,
                                    **{k: v for k, v in node_output.items() if k != "logs"},
                                }
                                if node_name in ("graphrag", "graphrag_node"):
                                    event_payload["evidence_summary"] = _summarize_evidence_manifest(
                                        node_output.get("evidence_manifest")
                                    )
                                    event_payload["post_hitl_refresh_needed"] = bool(
                                        node_output.get("post_hitl_refresh_needed")
                                    )
                                if node_name in ("content", "content_node"):
                                    event_payload["rendering_phase"] = "rendering_started"
                                    event_payload["artifact_preview"] = _content_preview_payload(
                                        node_output.get("content_draft")
                                    )
                                    if node_output.get("content_draft"):
                                        event_type = "content_ready"
                                if event_type == "hitl_required":
                                    event_payload["agent_node"] = node_output.get("hitl_node", node_name)

                                await out_q.put((event_type, event_payload))
                                log_flow(
                                    logger,
                                    "wf_node_transition",
                                    thread_id=thread_id,
                                    session_id=session_id,
                                    execution_mode="direct",
                                    node=node_name,
                                    status=node_output.get("status", "running"),
                                    event_type=event_type,
                                )

                        snapshot = await graph.aget_state(config)
                        if snapshot.next:
                            state_vals = snapshot.values
                            orchestrator.set_state(
                                thread_id,
                                "blocked_on_user",
                                state_vals.get("hitl_node", "content_node"),
                                session_id=session_id,
                            )
                            await out_q.put(
                                (
                                    "hitl_required",
                                    {
                                        "thread_id": thread_id,
                                        "session_id": session_id,
                                        "questions": state_vals.get("hitl_questions", []),
                                        "node": state_vals.get("hitl_node", ""),
                                        "agent_node": state_vals.get("hitl_node", ""),
                                    },
                                )
                            )
                        else:
                            final_state = snapshot.values if snapshot else {}
                            orchestrator.set_state(
                                thread_id,
                                "complete",
                                final_state.get("hitl_node", "direct-langgraph"),
                                session_id=session_id,
                            )
                            final = build_final_artifact(final_state)
                            final_payload = final.model_dump(mode="json")
                            await out_q.put(
                                (
                                    "complete",
                                    {
                                        "thread_id": thread_id,
                                        "session_id": session_id,
                                        "final_artifact": final_payload,
                                        "artifact_ready": _artifact_payload_from_final_artifact(final_payload),
                                    },
                                )
                            )
                    except Exception as exc:
                        await out_q.put(
                            (
                                "error",
                                {
                                    "thread_id": thread_id,
                                    "session_id": session_id,
                                    "message": str(exc),
                                },
                            )
                        )
                        raise
                    finally:
                        stop_preview.set()

                graph_task = asyncio.create_task(_run_graph())
                try:
                    while True:
                        if graph_task.done() and out_q.empty():
                            break
                        try:
                            etype, payload = await asyncio.wait_for(out_q.get(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        yield _event(etype, **payload)
                finally:
                    stop_preview.set()
                    if preview_task:
                        preview_task.cancel()
                        try:
                            await preview_task
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                    try:
                        await graph_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        # Graph errors are surfaced via queued `error`/exception events.
                        pass

            except Exception as exc:
                logger.error("langgraph_direct_error thread_id=%s error=%s", thread_id, exc)
                orchestrator.set_state(
                    thread_id,
                    "error",
                    "direct-langgraph",
                    session_id=session_id,
                    error=str(exc),
                )
                yield _event("error", message=str(exc))
                log_flow(
                    logger,
                    "wf_error",
                    level="error",
                    thread_id=thread_id,
                    session_id=session_id,
                    execution_mode="direct",
                    error=str(exc),
                )

        yield "data: [DONE]\n\n"

    async def _safe_stream_events():
        try:
            async for chunk in _stream_events():
                yield chunk
        except asyncio.CancelledError:
            # Client disconnected while stream was active.
            return

    return StreamingResponse(_safe_stream_events(), media_type="text/event-stream")


@app.post("/api/v4/orchestrator/resume")
async def v4_resume(req: ResumeRequest, _: str = Depends(verify_api_key)) -> StreamingResponse:
    """Resume a paused workflow with HITL answers. Returns SSE stream."""
    log_flow(
        logger,
        "wf_resume_received",
        thread_id=req.thread_id,
        agent_node=req.agent_node,
        answers_keys=sorted(req.answers.keys()),
        tenant_id=req.tenant_id or "",
    )

    # ── E. Request validation ────────────────────────────────────────
    if not req.answers:
        raise HTTPException(status_code=422, detail="At least one answer is required")

    temporal = await _get_temporal_client()

    # Check thread existence and status before streaming
    if temporal:
        try:
            from orchestrator.temporal_worker import BlaiqOrchestrationWorkflow as _WF

            handle = temporal.get_workflow_handle(f"blaiq-{req.thread_id}")
            pre_status = await handle.query(_WF.get_status)
        except Exception:
            raise HTTPException(status_code=404, detail="Thread not found")

        current_status = pre_status.get("status", "")
        if current_status not in ("blocked_on_user", "blocked"):
            raise HTTPException(
                status_code=409,
                detail=f"Thread is not blocked. Current status: {current_status}",
            )
    else:
        try:
            from orchestrator.graph import build_graph as _bg

            _graph = await _bg(REDIS_URL)
            _cfg = {"configurable": {"thread_id": req.thread_id}}
            if req.tenant_id:
                _cfg["configurable"]["tenant_id"] = req.tenant_id
            _snap = await _graph.aget_state(_cfg)
            if not _snap or not _snap.values:
                raise HTTPException(status_code=404, detail="Thread not found")
            current_status = _snap.values.get("status", "")
            if current_status not in ("blocked_on_user", "blocked"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Thread is not blocked. Current status: {current_status}",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="Thread not found")

    # ── SSE streaming ────────────────────────────────────────────────
    async def _resume_stream() -> Any:
        execution_mode = "temporal" if temporal else "direct"
        event_sequence = 0

        def _event(event_type: str, **payload: Any) -> str:
            nonlocal event_sequence
            event_sequence += 1
            payload.setdefault("execution_mode", execution_mode)
            payload.setdefault("event_ts", datetime.now(timezone.utc).isoformat())
            payload.setdefault("sequence", event_sequence)
            payload.setdefault("normalized_type", _normalized_stream_type(event_type, payload))
            return f"data: {json.dumps({'type': event_type, **payload})}\n\n"

        yield _event("resuming", thread_id=req.thread_id)
        log_flow(
            logger,
            "wf_resume_start",
            thread_id=req.thread_id,
            execution_mode=execution_mode,
        )

        if temporal:
            try:
                from orchestrator.temporal_worker import BlaiqOrchestrationWorkflow

                handle = temporal.get_workflow_handle(f"blaiq-{req.thread_id}")
                await handle.signal(BlaiqOrchestrationWorkflow.submit_hitl_answers, req.answers)
                yield _event("signal_sent", thread_id=req.thread_id)
                log_flow(
                    logger,
                    "wf_resume_signal_sent",
                    thread_id=req.thread_id,
                    execution_mode="temporal",
                )

                # Poll for completion (same pattern as /submit)
                preview_q: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue()
                stop_preview = asyncio.Event()
                preview_task: Optional[asyncio.Task] = asyncio.create_task(
                    _preview_pubsub_listener(req.thread_id, preview_q, stop_preview)
                )
                prev_node = ""
                for _ in range(600):
                    try:
                        # Drain any progressive preview events published by the content node.
                        try:
                            while True:
                                etype, payload = preview_q.get_nowait()
                                yield _event(etype, **payload)
                        except asyncio.QueueEmpty:
                            pass

                        status = await handle.query(BlaiqOrchestrationWorkflow.get_status)
                        current_node = ""
                        result = status.get("result")
                        if isinstance(result, dict):
                            current_node = result.get("current_node", "")

                        if current_node and current_node != prev_node:
                            event_type = _NODE_EVENT_MAP.get(current_node, "progress")
                            event_payload: Dict[str, Any] = {
                                "node": current_node,
                                "status": status.get("status", "running"),
                            }
                            if isinstance(result, dict):
                                if current_node in ("graphrag", "graphrag_node"):
                                    event_payload["evidence_summary"] = _summarize_evidence_manifest(
                                        result.get("evidence_manifest")
                                    )
                                    event_payload["post_hitl_refresh_needed"] = bool(
                                        result.get("post_hitl_refresh_needed")
                                    )
                                if current_node in ("content", "content_node"):
                                    event_payload["artifact_preview"] = _content_preview_payload(
                                        result.get("content_draft")
                                    )
                                    streamed_events = _streamed_preview_events(
                                        result.get("streamed_events")
                                    )
                                    for streamed_event in streamed_events:
                                        streamed_type = str(
                                            streamed_event.get("normalized_type")
                                            or streamed_event.get("type")
                                            or "progress"
                                        )
                                        streamed_payload = {
                                            k: v
                                            for k, v in streamed_event.items()
                                            if k not in {"type", "normalized_type", "sequence"}
                                        }
                                        yield _event(streamed_type, **streamed_payload)
                                    if result.get("content_draft"):
                                        event_type = "content_ready"
                            yield _event(event_type, **event_payload)
                            log_flow(
                                logger,
                                "wf_node_transition",
                                thread_id=req.thread_id,
                                execution_mode="temporal",
                                node=current_node,
                                status=status.get("status", "running"),
                            )
                            prev_node = current_node

                        if status.get("status") in ("complete", "error"):
                            final_state = result if isinstance(result, dict) else {}
                            final = build_final_artifact(final_state)
                            final_payload = final.model_dump(mode="json")
                            yield _event(
                                "complete",
                                final_artifact=final_payload,
                                artifact_ready=_artifact_payload_from_final_artifact(final_payload),
                            )
                            log_flow(
                                logger,
                                "wf_complete",
                                thread_id=req.thread_id,
                                execution_mode="temporal",
                                final_kind=final.kind,
                                validation_passed=final.validation_passed,
                            )
                            break
                        elif status.get("status") == "blocked_on_user":
                            result = status.get("result", {})
                            yield _event(
                                "hitl_required",
                                thread_id=req.thread_id,
                                questions=result.get("hitl_questions", []),
                                node=result.get("hitl_node", ""),
                                agent_node=result.get("hitl_node", ""),
                            )
                            log_flow(
                                logger,
                                "wf_hitl_blocked",
                                thread_id=req.thread_id,
                                execution_mode="temporal",
                                node=result.get("hitl_node", ""),
                                questions=len(result.get("hitl_questions", [])),
                            )
                            break
                    except Exception as poll_exc:
                        logger.warning("temporal_resume_poll_error err=%s", poll_exc)
                        err_str = str(poll_exc).lower()
                        if "not found" in err_str or "terminated" in err_str:
                            yield _event("error", message=str(poll_exc))
                            log_flow(
                                logger,
                                "wf_error",
                                level="error",
                                thread_id=req.thread_id,
                                execution_mode="temporal",
                                error=str(poll_exc),
                            )
                            break

                    await asyncio.sleep(1)
                stop_preview.set()
                if preview_task:
                    preview_task.cancel()
                    try:
                        await preview_task
                    except Exception:
                        pass

            except Exception as exc:
                logger.error("temporal_resume_error thread_id=%s error=%s", req.thread_id, exc)
                yield _event("error", message=str(exc))
                log_flow(
                    logger,
                    "wf_error",
                    level="error",
                    thread_id=req.thread_id,
                    execution_mode="temporal",
                    error=str(exc),
                )

        else:
            # Direct LangGraph resume
            try:
                from orchestrator.graph import build_graph
                from langgraph.types import Command

                graph = await build_graph(REDIS_URL)
                config = {"configurable": {"thread_id": req.thread_id}}
                if req.tenant_id:
                    config["configurable"]["tenant_id"] = req.tenant_id

                out_q: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue()
                stop_preview = asyncio.Event()
                preview_task: Optional[asyncio.Task] = asyncio.create_task(
                    _preview_pubsub_listener(req.thread_id, out_q, stop_preview)
                )

                async def _run_graph() -> None:
                    try:
                        async for event in graph.astream(
                            Command(resume=req.answers),
                            config=config,
                            stream_mode="updates",
                        ):
                            for node_name, node_output in event.items():
                                event_type = _NODE_EVENT_MAP.get(node_name, "progress")
                                if node_name in ("content", "content_node") and node_output.get("hitl_required"):
                                    event_type = "hitl_required"
                                event_payload: Dict[str, Any] = {
                                    "node": node_name,
                                    "thread_id": req.thread_id,
                                    **{k: v for k, v in node_output.items() if k != "logs"},
                                }
                                if node_name in ("graphrag", "graphrag_node"):
                                    event_payload["evidence_summary"] = _summarize_evidence_manifest(
                                        node_output.get("evidence_manifest")
                                    )
                                    event_payload["post_hitl_refresh_needed"] = bool(
                                        node_output.get("post_hitl_refresh_needed")
                                    )
                                if node_name in ("content", "content_node"):
                                    event_payload["rendering_phase"] = "rendering_started"
                                    event_payload["artifact_preview"] = _content_preview_payload(
                                        node_output.get("content_draft")
                                    )
                                    if node_output.get("content_draft"):
                                        event_type = "content_ready"
                                if event_type == "hitl_required":
                                    event_payload["agent_node"] = node_output.get("hitl_node", node_name)

                                await out_q.put((event_type, event_payload))
                                log_flow(
                                    logger,
                                    "wf_node_transition",
                                    thread_id=req.thread_id,
                                    execution_mode="direct",
                                    node=node_name,
                                    status=node_output.get("status", "running"),
                                    event_type=event_type,
                                )

                        snapshot = await graph.aget_state(config)
                        if snapshot.next:
                            state_vals = snapshot.values
                            await out_q.put(
                                (
                                    "hitl_required",
                                    {
                                        "thread_id": req.thread_id,
                                        "questions": state_vals.get("hitl_questions", []),
                                        "node": state_vals.get("hitl_node", ""),
                                        "agent_node": state_vals.get("hitl_node", ""),
                                    },
                                )
                            )
                        else:
                            final_state = snapshot.values if snapshot else {}
                            final = build_final_artifact(final_state)
                            final_payload = final.model_dump(mode="json")
                            await out_q.put(
                                (
                                    "complete",
                                    {
                                        "thread_id": req.thread_id,
                                        "final_artifact": final_payload,
                                        "artifact_ready": _artifact_payload_from_final_artifact(final_payload),
                                    },
                                )
                            )
                    except Exception as exc:
                        await out_q.put(("error", {"thread_id": req.thread_id, "message": str(exc)}))
                        raise
                    finally:
                        stop_preview.set()

                graph_task = asyncio.create_task(_run_graph())
                try:
                    while True:
                        if graph_task.done() and out_q.empty():
                            break
                        try:
                            etype, payload = await asyncio.wait_for(out_q.get(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        yield _event(etype, **payload)
                finally:
                    stop_preview.set()
                    if preview_task:
                        preview_task.cancel()
                        try:
                            await preview_task
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                    try:
                        await graph_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

            except Exception as exc:
                logger.error("langgraph_resume_error thread_id=%s error=%s", req.thread_id, exc)
                yield _event("error", message=str(exc))
                log_flow(
                    logger,
                    "wf_error",
                    level="error",
                    thread_id=req.thread_id,
                    execution_mode="direct",
                    error=str(exc),
                )

        yield "data: [DONE]\n\n"

    async def _safe_resume_stream():
        try:
            async for chunk in _resume_stream():
                yield chunk
        except asyncio.CancelledError:
            # Client disconnected while stream was active.
            return

    return StreamingResponse(_safe_resume_stream(), media_type="text/event-stream")


@app.post("/api/v4/orchestrator/regenerate")
async def v4_regenerate(req: RegenerateRequest, _: str = Depends(verify_api_key)) -> StreamingResponse:
    """Regenerate content from a patched schema without re-running GraphRAG."""
    log_flow(
        logger,
        "wf_regenerate_received",
        thread_id=req.thread_id,
        workflow_mode=req.workflow_mode,
    )
    try:
        from orchestrator.graph import build_graph

        graph = await build_graph(REDIS_URL)
        config = {"configurable": {"thread_id": req.thread_id}}
        snapshot = await graph.aget_state(config)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}")

    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="Thread not found")

    vals = snapshot.values
    content_draft = vals.get("content_draft") or {}
    if not content_draft:
        raise HTTPException(status_code=409, detail="No content draft found for regeneration")

    base_schema = content_draft.get("schema_data") or {}
    patched_schema = req.patched_schema.model_dump(mode="json")
    merged_schema = {**base_schema, **patched_schema}

    tenant_id = vals.get("tenant_id", "default")
    collection_name = vals.get("collection_name", tenant_id)
    session_id = vals.get("session_id", str(uuid.uuid4()))
    user_query = vals.get("user_query", "Regenerate content")
    skills_used = content_draft.get("skills_used", [])
    mission_id = content_draft.get("mission_id") or str(uuid.uuid4())

    async def _regen_stream() -> Any:
        event_sequence = 0

        def _event(event_type: str, **payload: Any) -> str:
            nonlocal event_sequence
            event_sequence += 1
            payload.setdefault("sequence", event_sequence)
            payload.setdefault("event_ts", datetime.now(timezone.utc).isoformat())
            payload.setdefault("normalized_type", _normalized_stream_type(event_type, payload))
            return f"data: {json.dumps({'type': event_type, **payload})}\n\n"

        orchestrator.set_state(req.thread_id, "regenerating", "content_node", session_id=session_id)
        yield _event("regen_started", thread_id=req.thread_id)
        log_flow(
            logger,
            "wf_regenerate_start",
            thread_id=req.thread_id,
            session_id=session_id,
            tenant_id=tenant_id,
            collection_name=collection_name,
        )

        envelope = MCPEnvelope.create(
            thread_id=req.thread_id,
            intent="generate_content",
            tenant_id=tenant_id,
            collection_name=collection_name,
            payload={"query": user_query, "schema_override": merged_schema},
        )

        request_body: Dict[str, Any] = {
            "task": user_query,
            "session_id": session_id,
            "payload": {
                "answers": {"_regen": "true"},
                "schema_override": merged_schema,
                "skills": skills_used,
            },
        }

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-API-Key": os.getenv("API_KEY", ""),
            "x-mcp-envelope": envelope.to_header_value(),
            "x-idempotency-key": envelope.idempotency_key,
        }
        headers.update(get_trace_headers())

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(CONTENT_TIMEOUT)) as client:
                resp = await client.post(
                    f"{BLAIQ_CONTENT_URL}/execute",
                    json=request_body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            result_payload = data.get("result") if isinstance(data.get("result"), dict) else data
            status = result_payload.get("status", "success") if isinstance(result_payload, dict) else "success"

            if status == "blocked_on_user":
                yield _event(
                    "hitl_required",
                    thread_id=req.thread_id,
                    questions=result_payload.get("questions", []),
                    node="content_node",
                    agent_node="content_node",
                )
                return

            html_artifact = (
                result_payload.get("html_artifact")
                or result_payload.get("html")
                or result_payload.get("artifact", "")
            )
            artifact_uri = None
            if html_artifact and len(html_artifact.encode()) > CLAIM_CHECK_THRESHOLD:
                artifact_uri = await _store_html_artifact(mission_id, html_artifact)

            orchestrator.set_state(req.thread_id, "complete", "content_node", session_id=session_id)
            yield _event(
                "regen_complete",
                thread_id=req.thread_id,
                html_artifact=html_artifact,
                artifact_uri=artifact_uri,
                schema_data=merged_schema,
                skills_used=skills_used,
                mission_id=mission_id,
                artifact_ready={
                    "artifact_kind": "content",
                    "validation_passed": True,
                    "html_chars": len(html_artifact) if isinstance(html_artifact, str) else 0,
                    "schema_keys": sorted(merged_schema.keys()) if isinstance(merged_schema, dict) else [],
                },
            )
            log_flow(
                logger,
                "wf_regenerate_complete",
                thread_id=req.thread_id,
                session_id=session_id,
                html_chars=len(html_artifact) if isinstance(html_artifact, str) else 0,
                claim_check=bool(artifact_uri),
            )

        except Exception as exc:
            logger.error("regen_error thread_id=%s error=%s", req.thread_id, exc)
            orchestrator.set_state(req.thread_id, "error", "content_node", session_id=session_id, error=str(exc))
            yield _event("error", message=str(exc))
            log_flow(
                logger,
                "wf_regenerate_error",
                level="error",
                thread_id=req.thread_id,
                session_id=session_id,
                error=str(exc),
            )

        yield "data: [DONE]\n\n"

    async def _safe_regen_stream():
        try:
            async for chunk in _regen_stream():
                yield chunk
        except asyncio.CancelledError:
            return

    return StreamingResponse(_safe_regen_stream(), media_type="text/event-stream")


@app.get("/api/v4/orchestrator/status/{thread_id}")
async def v4_status(thread_id: str, _: str = Depends(verify_api_key)) -> Dict[str, Any]:
    """Get workflow status (Temporal or LangGraph checkpoint).

    Returns a ``WorkflowStatus``-shaped dict regardless of execution mode.
    """
    temporal = await _get_temporal_client()
    now_iso = datetime.now(timezone.utc).isoformat()

    if temporal:
        try:
            from orchestrator.temporal_worker import BlaiqOrchestrationWorkflow

            handle = temporal.get_workflow_handle(f"blaiq-{thread_id}")
            status = await handle.query(BlaiqOrchestrationWorkflow.get_status)

            result = status.get("result") or {}
            wf_status = status.get("status", "unknown")
            current_node = result.get("current_node", "") if isinstance(result, dict) else ""
            hitl_required = result.get("hitl_required", False) if isinstance(result, dict) else False
            hitl_questions = result.get("hitl_questions", []) if isinstance(result, dict) else []
            error_message = result.get("error_message", "") if isinstance(result, dict) else ""

            final_artifact: Optional[Dict[str, Any]] = None
            if wf_status in ("complete", "error") and isinstance(result, dict):
                final_artifact = build_final_artifact(result).model_dump(mode="json")

            return WorkflowStatus(
                thread_id=thread_id,
                execution_mode="temporal",
                status=wf_status,
                current_node=current_node,
                hitl_required=hitl_required,
                hitl_questions=hitl_questions,
                error_message=error_message,
                final_artifact=final_artifact,
                updated_at=now_iso,
            ).model_dump(mode="json")

        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Workflow not found: {exc}")
    else:
        try:
            from orchestrator.graph import build_graph

            graph = await build_graph(REDIS_URL)
            config = {"configurable": {"thread_id": thread_id}}
            snapshot = await graph.aget_state(config)
            if not snapshot or not snapshot.values:
                raise HTTPException(status_code=404, detail="Thread not found")

            vals = snapshot.values
            wf_status = vals.get("status", "unknown")
            hitl_required = bool(snapshot.next) or vals.get("hitl_required", False)
            hitl_questions: List[str] = vals.get("hitl_questions", [])
            error_message = vals.get("error_message", "")

            final_artifact = None
            if wf_status in ("complete", "error"):
                final_artifact = build_final_artifact(vals).model_dump(mode="json")

            return WorkflowStatus(
                thread_id=thread_id,
                execution_mode="direct",
                status=wf_status,
                current_node=vals.get("current_node", ""),
                hitl_required=hitl_required,
                hitl_questions=hitl_questions,
                error_message=error_message,
                final_artifact=final_artifact,
                updated_at=now_iso,
            ).model_dump(mode="json")

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v4/orchestrator/workflows")
async def v4_list_workflows(_: str = Depends(verify_api_key)):
    """List recent workflows (Temporal only)."""
    temporal = await _get_temporal_client()
    if not temporal:
        return {"workflows": [], "note": "Temporal unavailable — direct LangGraph mode"}

    try:
        workflows = []
        async for wf in temporal.list_workflows(query="WorkflowType = 'BlaiqOrchestrationWorkflow'"):
            workflows.append({
                "workflow_id": wf.id,
                "run_id": wf.run_id,
                "status": str(wf.status),
                "start_time": str(wf.start_time) if wf.start_time else None,
            })
            if len(workflows) >= 50:
                break
        return {"workflows": workflows}
    except Exception as exc:
        logger.error("temporal_list_error error=%s", exc)
        return {"workflows": [], "error": str(exc)}


@app.post("/api/v4/orchestrator/chats/save")
async def v4_save_chat_snapshot(req: ChatSnapshotRequest, _: str = Depends(verify_api_key)) -> Dict[str, Any]:
    """Save a chat/workflow snapshot to a local JSON file."""

    def _safe_part(raw: Optional[str], fallback: str) -> str:
        value = (raw or fallback).strip() or fallback
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)[:80]

    tenant = _safe_part(req.tenant_id, "default")
    thread_part = _safe_part(req.thread_id, "threadless")
    session_part = _safe_part(req.session_id, "session")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    folder = CHAT_EXPORT_DIR / tenant
    folder.mkdir(parents=True, exist_ok=True)
    file_name = f"{stamp}_{thread_part}_{session_part}.json"
    file_path = folder / file_name

    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": req.tenant_id,
        "thread_id": req.thread_id,
        "session_id": req.session_id,
        "run_id": req.run_id,
        "workflow_mode": req.workflow_mode,
        "messages": req.messages,
        "timeline": req.timeline,
        "artifact": req.artifact,
        "governance": req.governance,
        "schema": req.schema_state,
        "status": req.status,
    }

    try:
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("chat_snapshot_save_error path=%s err=%s", file_path, exc)
        raise HTTPException(status_code=500, detail=f"Failed to save chat snapshot: {exc}")

    logger.info(
        "chat_snapshot_saved tenant=%s thread=%s session=%s file=%s",
        req.tenant_id,
        req.thread_id or "",
        req.session_id,
        file_path,
    )
    return {
        "status": "saved",
        "file_path": str(file_path),
        "file_name": file_name,
    }
