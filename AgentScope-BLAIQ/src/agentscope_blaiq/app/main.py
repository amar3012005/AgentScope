from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import os
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
import bcrypt

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentscope_blaiq.contracts.hitl import HITLResumeRequest
from agentscope_blaiq.contracts.workflow import ResumeWorkflowRequest, SubmitWorkflowRequest, WorkflowStatus
from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec, validate_custom_agent_spec
from agentscope_blaiq.contracts.user_agent_registry import UserAgentRegistry
from agentscope_blaiq.persistence.database import get_db, init_engine, close_engine
from agentscope_blaiq.persistence.migrations import bootstrap_database
from agentscope_blaiq.persistence.redis_state import RedisStateStore
from agentscope_blaiq.persistence.repositories import (
    ArtifactRepository, UploadRepository, WorkflowRepository, UserRepository,
    ConversationRepository
)
from agentscope_blaiq.app.bootstrap_service import BootstrapService
from agentscope_blaiq.app.policy_service import PolicyService
from agentscope_blaiq.app.admin_routes import router as admin_router
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPError
from agentscope_blaiq.runtime.registry import AgentRegistry
from agentscope_blaiq.tools.docs import validate_uploaded_document
from agentscope_blaiq.streaming.sse import encode_sse
from agentscope_blaiq.workflows.swarm_workflow_engine import SwarmWorkflowEngine
from agentscope_blaiq.runtime.hivemind_client import _stored_credentials as hivemind_stored_creds
from agentscope_blaiq.contracts.tool_telemetry import (
    _EXECUTED_TOOL_EVENT_TYPES,
    build_tool_drift,
    normalize_executed_tool_event,
    normalize_plan_nodes,
)
from .model_resolver import current_litellm_config
from .runtime_checks import check_runtime_ready, check_storage_paths


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Ensure Directories
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    settings.agent_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    # 2. Initialize Resources
    init_engine()
    app.state.redis = await RedisStateStore.create()
    
    # 3. Migrate
    await bootstrap_database()

    runtime_report = await check_runtime_ready()
    logging.getLogger("agentscope_blaiq").info(
        "runtime_ready=%s env_sources=%s groq_api_key_present=%s models=%s issues=%s",
        runtime_report.ok,
        runtime_report.details.get("models", {}).get("env_sources"),
        runtime_report.details.get("models", {}).get("groq_api_key_present"),
        {name: info.get("route") for name, info in runtime_report.details.get("models", {}).get("models", {}).items()},
        runtime_report.issues,
    )
    
    yield
    
    # 4. Cleanup
    await app.state.redis.close()
    await close_engine()


app = FastAPI(title="AgentScope-BLAIQ", version="0.1.0", lifespan=lifespan)
app.include_router(admin_router)

# Silence low-level LLM / AgentScope console dumps in backend runtime.
os.environ.setdefault("AGENTSCOPE_DISABLE_CONSOLE_OUTPUT", "true")
os.environ.setdefault("LITELLM_LOG", "WARNING")

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
logging.Formatter.converter = __import__("time").gmtime  # force UTC across all handlers

# Keep production logs focused on workflow phase transitions and warnings.
for noisy_logger in (
    "LiteLLM",
    "litellm",
    "_toolkit",
    "httpx",
    "httpcore",
    "openai",
    "agentscope",
    "agentscope_blaiq.runtime",
):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logging.getLogger("agentscope_blaiq").setLevel(logging.INFO)
logging.getLogger("agentscope_blaiq.workflows.swarm_engine").setLevel(logging.INFO)
logging.getLogger("blaiq.swarm_engine").setLevel(logging.INFO)
logging.getLogger("agentscope_blaiq.swarm_workflow_engine").setLevel(logging.INFO)

# CORS — allow the frontend dev server
_allowed_origins = [
    origin
    for origin in (settings.allowed_origins if hasattr(settings, "allowed_origins") else "").split(",")
    if origin.strip()
] or ["http://localhost:3001", "http://127.0.0.1:3001", "http://localhost:3002", "http://127.0.0.1:3002"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

registry = AgentRegistry()
engine_runner = SwarmWorkflowEngine(registry)


def _get_user_agent_registry() -> UserAgentRegistry:
    return registry.user_agent_registry

# In-memory OAuth token store (use Redis/encrypted DB in production)
_hivemind_oauth_tokens: dict[str, str] = {}

# In-memory HiveMind enterprise credentials store
_hivemind_credentials: dict[str, str] = {}

# In-memory compatibility stores for optional frontend persistence helpers.
_frontend_tenants: dict[str, dict[str, str]] = {}
_frontend_chat_sessions: dict[str, dict[str, str]] = {}
_frontend_browser_cache: dict[tuple[str, str], dict[str, object]] = {}


class HivemindCredentialsRequest(BaseModel):
    api_key: str
    org_id: str
    user_id: str
    base_url: str | None = None


class HivemindTestRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    mode: str = "insight"


class TenantUpsertRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    display_name: str | None = None


class BrowserCacheRequest(BaseModel):
    cache: dict[str, object] = Field(default_factory=dict)




def _parse_hivemind_user_id(rpc_url: str | None) -> str | None:
    if not rpc_url:
        return None
    try:
        path = urlparse(rpc_url).path.strip("/")
        parts = path.split("/")
        if "servers" in parts:
            idx = parts.index("servers")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    except Exception:
        return None
    return None


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/v1/auth/login")
async def login(req: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from agentscope_blaiq.persistence.models import UserRecord, SessionRecord

    # 1. Look up UserRecord by email
    result = await db.execute(select(UserRecord).where(UserRecord.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # 2. Verify password
    if not bcrypt.checkpw(req.password.encode(), user.hashed_password.encode()):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # 3. Create SessionRecord
    token = uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    session_rec = SessionRecord(
        user_id=user.id,
        token=token,
        expires_at=expires_at
    )
    db.add(session_rec)
    await db.commit()

    # 4. Set cookie
    response.set_cookie(
        "hm_session", 
        token, 
        httponly=True, 
        samesite="lax", 
        max_age=86400, # 24 hours
        secure=False
    )

    return {"ok": True, "user_id": user.id}


@app.get("/api/v1/runs")
async def list_runs(
    workspace_id: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    from agentscope_blaiq.persistence.models import WorkflowRecord
    stmt = select(WorkflowRecord)
    if workspace_id:
        stmt = stmt.where(WorkflowRecord.workspace_id == workspace_id)
    if status:
        stmt = stmt.where(WorkflowRecord.status == status)
    if user_id:
        stmt = stmt.where(WorkflowRecord.user_id == user_id)
    
    stmt = stmt.order_by(WorkflowRecord.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    runs = result.scalars().all()
    
    return [
        {
            "thread_id": r.thread_id,
            "status": r.status,
            "user_query": r.user_query,
            "workflow_mode": r.workflow_mode,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat()
        } for r in runs
    ]


@app.get("/api/v1/runs/{thread_id}/replay")
async def get_run_replay(thread_id: str, db: AsyncSession = Depends(get_db)):
    from agentscope_blaiq.persistence.models import (
        WorkflowRecord, WorkflowEventRecord, AgentRunRecord, ArtifactRecord
    )
    
    # 1. Load WorkflowRecord
    workflow = await db.get(WorkflowRecord, thread_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    # 2. Load Events
    events_res = await db.execute(
        select(WorkflowEventRecord)
        .where(WorkflowEventRecord.thread_id == thread_id)
        .order_by(WorkflowEventRecord.sequence.asc())
    )
    events = events_res.scalars().all()
    
    # 3. Load Agent Runs
    runs_res = await db.execute(
        select(AgentRunRecord).where(AgentRunRecord.thread_id == thread_id)
    )
    agent_runs = runs_res.scalars().all()
    
    # 4. Load Artifact
    artifact_res = await db.execute(
        select(ArtifactRecord).where(ArtifactRecord.thread_id == thread_id).limit(1)
    )
    artifact = artifact_res.scalar_one_or_none()
    
    return {
        "workflow": {
            "thread_id": workflow.thread_id,
            "status": workflow.status,
            "workflow_mode": workflow.workflow_mode,
            "user_query": workflow.user_query,
            "created_at": workflow.created_at.isoformat()
        },
        "events": [
            {
                "sequence": e.sequence,
                "event_type": e.event_type,
                "agent_name": e.agent_name,
                "payload": json.loads(e.payload_json),
                "created_at": e.created_at.isoformat()
            } for e in events
        ],
        "agent_runs": [
            {
                "run_id": r.run_id,
                "agent_name": r.agent_name,
                "agent_type": r.agent_type,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "input": json.loads(r.input_json),
                "output": json.loads(r.output_json) if r.output_json else None
            } for r in agent_runs
        ],
        "artifact": {
            "artifact_id": artifact.artifact_id,
            "title": artifact.title,
            "artifact_type": artifact.artifact_type
        } if artifact else None
    }


@app.get("/api/v1/runs/{thread_id}/tool-calls")
async def get_run_tool_calls(thread_id: str, db: AsyncSession = Depends(get_db)):
    from agentscope_blaiq.persistence.models import WorkflowEventRecord
    
    stmt = select(WorkflowEventRecord).where(
        WorkflowEventRecord.thread_id == thread_id,
        WorkflowEventRecord.event_type.in_(sorted(_EXECUTED_TOOL_EVENT_TYPES))
    ).order_by(WorkflowEventRecord.sequence.asc())
    
    result = await db.execute(stmt)
    events = [event for event in result.scalars().all() if event.event_type in _EXECUTED_TOOL_EVENT_TYPES]
    tool_events = [normalize_executed_tool_event(e) for e in events]
    return {
        "thread_id": thread_id,
        "run_id": tool_events[-1]["run_id"] if tool_events else None,
        "source": "executed_only",
        "count": len(tool_events),
        "events": tool_events,
    }


@app.get("/api/v1/runs/{thread_id}/tool-plan")
async def get_run_tool_plan(thread_id: str, db: AsyncSession = Depends(get_db)):
    from agentscope_blaiq.persistence.models import WorkflowRecord, WorkflowEventRecord

    workflow = await db.get(WorkflowRecord, thread_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    plan: dict[str, Any] = {}
    if workflow.workflow_plan_json:
        try:
            parsed_plan = json.loads(workflow.workflow_plan_json)
            if isinstance(parsed_plan, dict):
                plan = parsed_plan
        except Exception:
            plan = {}

    plan_nodes = normalize_plan_nodes(plan)
    executed_res = await db.execute(
        select(WorkflowEventRecord)
        .where(
            WorkflowEventRecord.thread_id == thread_id,
            WorkflowEventRecord.event_type.in_(sorted(_EXECUTED_TOOL_EVENT_TYPES)),
        )
        .order_by(WorkflowEventRecord.sequence.asc())
    )
    executed_events = [
        normalize_executed_tool_event(event)
        for event in executed_res.scalars().all()
        if event.event_type in _EXECUTED_TOOL_EVENT_TYPES
    ]
    drift = build_tool_drift(plan_nodes, executed_events)
    summary = {
        "planned_node_count": len(plan_nodes),
        "planned_tool_count": drift["summary"]["planned_tool_count"],
        "executed_tool_count": drift["summary"]["executed_tool_count"],
        "matched_tool_count": drift["summary"]["matched_count"],
        "plan_incomplete": drift["summary"]["plan_incomplete"],
    }
    return {
        "thread_id": thread_id,
        "run_id": workflow.run_id,
        "workflow_id": plan.get("workflow_template_id"),
        "workflow_mode": plan.get("workflow_mode"),
        "artifact_family": plan.get("artifact_family"),
        "source": "workflow_plan",
        "summary": summary,
        "nodes": plan_nodes,
        "drift": drift,
    }


@app.post("/api/v1/auth/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from agentscope_blaiq.persistence.models import SessionRecord
    
    token = request.cookies.get("hm_session")
    if token:
        from sqlalchemy import delete
        await db.execute(delete(SessionRecord).where(SessionRecord.token == token))
        await db.commit()
    
    response.delete_cookie("hm_session")
    return {"ok": True}


@app.post("/api/v1/auth/refresh")
async def refresh_session(request: Request, db: AsyncSession = Depends(get_db)):
    from agentscope_blaiq.persistence.models import SessionRecord
    
    token = request.cookies.get("hm_session")
    if not token:
        raise HTTPException(status_code=401, detail="No session found")
        
    result = await db.execute(
        select(SessionRecord).where(
            SessionRecord.token == token,
            SessionRecord.expires_at > datetime.now(timezone.utc)
        )
    )
    session_rec = result.scalar_one_or_none()
    
    if not session_rec:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
        
    # Extend session
    session_rec.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.commit()
    
    return {"ok": True}


# ============================================================================
# CONVERSATION API ENDPOINTS
# ============================================================================

class CreateConversationRequest(BaseModel):
    workspace_id: str
    user_id: str
    thread_id: str
    title: str | None = None


class SaveMessageRequest(BaseModel):
    conversation_id: str
    sender_type: str  # 'user', 'agent', 'system'
    content: str
    metadata: dict | None = None


class UpdateConversationTitleRequest(BaseModel):
    title: str


@app.get("/api/v1/conversations")
async def list_conversations(
    workspace_id: str = Query(..., description="Workspace ID"),
    user_id: str = Query(..., description="User ID"),
    limit: int = Query(50, ge=1, le=100, description="Max conversations to return"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all conversations for a user in a workspace."""
    repo = ConversationRepository(db)
    conversations = await repo.list_conversations(workspace_id, user_id, limit)
    
    return [
        {
            "id": c.id,
            "workspace_id": c.workspace_id,
            "user_id": c.user_id,
            "thread_id": c.thread_id,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "message_count": len(c.messages),
        }
        for c in conversations
    ]


@app.post("/api/v1/conversations")
async def create_conversation(
    request: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new conversation."""
    repo = ConversationRepository(db)
    conversation = await repo.create_or_get_conversation(
        workspace_id=request.workspace_id,
        user_id=request.user_id,
        thread_id=request.thread_id,
        title=request.title,
    )
    
    return {
        "id": conversation.id,
        "workspace_id": conversation.workspace_id,
        "user_id": conversation.user_id,
        "thread_id": conversation.thread_id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
    }


@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a conversation with all its messages."""
    repo = ConversationRepository(db)
    conversation = await repo.get_conversation_by_id(conversation_id)
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = await repo.get_messages(conversation_id)
    
    return {
        "id": conversation.id,
        "workspace_id": conversation.workspace_id,
        "user_id": conversation.user_id,
        "thread_id": conversation.thread_id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "messages": [
            {
                "id": m.id,
                "conversation_id": m.conversation_id,
                "sender_type": m.sender_type,
                "sender_id": m.sender_id,
                "content": m.content,
                "metadata": json.loads(m.metadata_json) if m.metadata_json else {},
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@app.post("/api/v1/conversations/{conversation_id}/messages")
async def save_message(
    conversation_id: str,
    request: SaveMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save a message to a conversation."""
    repo = ConversationRepository(db)
    message = await repo.save_message(
        conversation_id=conversation_id,
        sender_type=request.sender_type,
        content=request.content,
        metadata=request.metadata or {},
    )
    
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_type": message.sender_type,
        "content": message.content,
        "metadata": json.loads(message.metadata_json) if message.metadata_json else {},
        "created_at": message.created_at.isoformat(),
    }


@app.patch("/api/v1/conversations/{conversation_id}")
async def update_conversation_title(
    conversation_id: str,
    request: UpdateConversationTitleRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update conversation title."""
    repo = ConversationRepository(db)
    await repo.update_conversation_title(conversation_id, request.title)
    
    return {"ok": True, "title": request.title}


# ============================================================================
# ROOT & HEALTH ENDPOINTS
# ============================================================================

@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "AgentScope-BLAIQ", "status": "ok"}


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    storage = check_storage_paths(settings.upload_dir, settings.artifact_dir, settings.log_dir)
    return {"status": "ok" if storage.ok else "degraded", "service": "AgentScope-BLAIQ", "storage": storage.details, "issues": storage.issues}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    report = await check_runtime_ready()
    payload = {"status": "ready" if report.ok else "not_ready", "ready": report.ok, "details": report.details, "issues": report.issues}
    if not report.ok:
        return JSONResponse(status_code=503, content=payload)
    return JSONResponse(status_code=200, content=payload)


@app.get("/api/v1/bootstrap")
async def bootstrap(request: Request, db: AsyncSession = Depends(get_db)):
    """Returns bootstrap data for the current user."""
    from agentscope_blaiq.persistence.models import ApiKeyRecord, SessionRecord, UserRecord
    try:
        user_id: str | None = None

        # Method 1: Session cookie
        session_token = request.cookies.get("hm_session") or request.cookies.get("hm_user_id")
        if session_token:
            result = await db.execute(
                select(SessionRecord).where(
                    SessionRecord.token == session_token,
                    SessionRecord.expires_at > datetime.now(timezone.utc),
                )
            )
            session_rec = result.scalar_one_or_none()
            if session_rec:
                user_id = session_rec.user_id

        # Method 2: Bearer token (API key)
        if not user_id:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                key_hash = hashlib.sha256(token.encode()).hexdigest()
                result = await db.execute(
                    select(ApiKeyRecord).where(ApiKeyRecord.key_hash == key_hash)
                )
                api_key_rec = result.scalar_one_or_none()
                if api_key_rec:
                    user_id = api_key_rec.user_id

        # Method 3: Dev fallback — first admin user (only in development)
        if not user_id and settings.app_env == "development":
            result = await db.execute(
                select(UserRecord).where(UserRecord.is_superuser == True).limit(1)
            )
            dev_user = result.scalar_one_or_none()
            if dev_user:
                user_id = dev_user.id

        if not user_id:
            raise HTTPException(status_code=401, detail="Session expired or invalid")

        service = BootstrapService(db)
        data = await service.get_bootstrap_data(user_id)
        if "error" in data:
            raise HTTPException(status_code=404, detail=data["error"])
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Bootstrap failed")
        raise HTTPException(status_code=500, detail="Bootstrap failed") from exc


@app.get("/api/v1/policies")
async def get_policies(workspace_id: str | None = None, db: AsyncSession = Depends(get_db)):
    """Returns active policies for the specified workspace."""
    service = PolicyService(db)
    data = await service.get_active_policies(workspace_id)
    return data


@app.put("/api/v1/tenants")
async def upsert_tenant(payload: TenantUpsertRequest):
    tenant_id = payload.tenant_id.strip()
    display_name = (payload.display_name or tenant_id).strip() or tenant_id
    record = {"tenant_id": tenant_id, "display_name": display_name}
    _frontend_tenants[tenant_id] = record
    return {"ok": True, "tenant": record}


@app.put("/api/v1/chat-sessions")
async def upsert_chat_session(payload: dict):
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    tenant_id = str(payload.get("tenant_id") or "default").strip() or "default"
    title = str(payload.get("title") or f"Chat {session_id[:8]}").strip() or f"Chat {session_id[:8]}"
    record = {"tenant_id": tenant_id, "session_id": session_id, "title": title}
    _frontend_chat_sessions[session_id] = record
    return {"ok": True, "session": record}


@app.put("/api/v1/browser-cache/{tenant_id}/{session_id}")
async def save_browser_cache(tenant_id: str, session_id: str, payload: BrowserCacheRequest):
    _frontend_browser_cache[(tenant_id, session_id)] = payload.cache
    return {"ok": True, "tenant_id": tenant_id, "session_id": session_id}


@app.get("/api/v1/browser-cache/{tenant_id}/{session_id}")
async def get_browser_cache(tenant_id: str, session_id: str, db: AsyncSession = Depends(get_db)):
    cache = _frontend_browser_cache.get((tenant_id, session_id))
    if cache is not None:
        return {"ok": True, "tenant_id": tenant_id, "session_id": session_id, "cache": cache}

    # DB fallback: rebuild frontend session cache from workflow history by session_id.
    workflows = await WorkflowRepository(db).list_workflows_by_session(session_id, tenant_id=tenant_id, limit=25)
    if not workflows:
        return {"ok": True, "tenant_id": tenant_id, "session_id": session_id, "cache": None}

    tasks: list[dict[str, Any]] = []
    for workflow in workflows:
        state_payload: dict[str, Any] = {}
        if workflow.workflow_state_json:
            try:
                raw_state = json.loads(workflow.workflow_state_json)
                if isinstance(raw_state, dict):
                    state_payload = raw_state
            except Exception:
                state_payload = {}

        artifact_payload: dict[str, Any] | None = None
        if workflow.final_artifact_json:
            try:
                raw = json.loads(workflow.final_artifact_json)
                if isinstance(raw, dict):
                    artifact_payload = {
                        "id": raw.get("artifact_id") or f"artifact-{workflow.thread_id}",
                        "title": raw.get("title") or "Final artifact",
                        "theme": raw.get("theme"),
                        "sections": raw.get("sections") or [],
                        "html": raw.get("html") or "",
                        "css": raw.get("css") or "",
                        "markdown": raw.get("markdown") or "",
                        "phase": raw.get("phase") or "artifact",
                        "governance_status": raw.get("governance_status"),
                    }
            except Exception:
                artifact_payload = None

        final_answer = str(
            state_payload.get("final_answer_display")
            or state_payload.get("final_answer")
            or ""
        ).strip()
        if not final_answer and artifact_payload:
            final_answer = str(artifact_payload.get("markdown") or "").strip()
        if not final_answer and artifact_payload:
            title_hint = str(artifact_payload.get("title") or "artifact").strip() or "artifact"
            final_answer = f"Your {title_hint.lower()} is ready in the preview panel."

        messages = [
            {
                "id": f"{workflow.thread_id}-user",
                "role": "user",
                "content": workflow.user_query,
                "at": workflow.created_at.isoformat() if workflow.created_at else datetime.now(timezone.utc).isoformat(),
            }
        ]
        if final_answer:
            messages.append(
                {
                    "id": f"{workflow.thread_id}-agent",
                    "role": "agent",
                    "content": final_answer,
                    "at": workflow.updated_at.isoformat() if workflow.updated_at else datetime.now(timezone.utc).isoformat(),
                }
            )

        task_status = workflow.status
        if task_status == "queued":
            task_status = "running"
        elif task_status not in {"running", "blocked", "error", "complete"}:
            task_status = "running"

        tasks.append(
            {
                "id": workflow.thread_id,
                "threadId": workflow.thread_id,
                "sessionId": workflow.session_id,
                "query": workflow.user_query,
                "workflowMode": workflow.workflow_mode or "hybrid",
                "status": task_status,
                "currentAgent": workflow.current_agent,
                "artifact": artifact_payload,
                "artifactSections": (artifact_payload or {}).get("sections", []),
                "finalAnswer": final_answer,
                "events": [],
                "messages": messages,
                "createdAt": workflow.created_at.isoformat() if workflow.created_at else datetime.now(timezone.utc).isoformat(),
            }
        )

    title = f"Chat {session_id[:8]}"
    if tasks and tasks[0].get("query"):
        q = str(tasks[0]["query"]).strip()
        if q:
            title = f"{q[:50]}{'...' if len(q) > 50 else ''} · {session_id[:8]}"

    hydrated_cache = {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "sessions": [
            {
                "id": session_id,
                "title": title,
                "memoryChainId": None,
                "createdAt": tasks[-1]["createdAt"] if tasks else datetime.now(timezone.utc).isoformat(),
                "lastUsedAt": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "tasks": tasks,
        "activeTaskId": tasks[0]["id"] if tasks else None,
        "previewOpen": bool(tasks and tasks[0].get("artifact")),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _frontend_browser_cache[(tenant_id, session_id)] = hydrated_cache
    return {"ok": True, "tenant_id": tenant_id, "session_id": session_id, "cache": hydrated_cache}


@app.get("/api/v1/runtime/checks")
async def runtime_checks() -> dict[str, object]:
    report = await check_runtime_ready()
    return {
        "ready": report.ok,
        "checks": report.details,
        "issues": report.issues,
        "model_config": current_litellm_config().as_dict(),
    }


@app.post("/api/v1/workflows/submit")
async def submit_workflow(
    request: SubmitWorkflowRequest,
    req: Request,
    session: AsyncSession = Depends(get_db)
) -> EventSourceResponse:
    if not request.user_query or not request.user_query.strip():
        raise HTTPException(status_code=422, detail="user_query cannot be empty")

    async def event_stream():
        # Step away from encode_sse to avoid the "double-bridge" JSON-in-JSON clumping.
        # engine_runner.run returns an AsyncIterator[StreamEvent].
        async for event in engine_runner.run(session, request):
            yield f"data: {event.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return EventSourceResponse(
        event_stream(),
        ping=15, # Increased ping to keep slow connections alive during heavy reasoning
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/v1/workflows/resume")
async def resume_workflow(request: ResumeWorkflowRequest, session: AsyncSession = Depends(get_db)) -> EventSourceResponse:
    repo = WorkflowRepository(session)
    workflow = await repo.get_workflow_record(request.thread_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if request.tenant_id is not None and request.tenant_id != workflow.tenant_id:
        raise HTTPException(status_code=409, detail="tenant_id does not match the stored workflow")
    snapshot = await repo.get_status(request.thread_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if snapshot.status not in {WorkflowStatus.blocked, WorkflowStatus.error}:
        raise HTTPException(status_code=409, detail="Workflow can only be resumed from blocked or error status")

    # Phase 4: validate typed answer_set before opening the SSE stream so the
    # client gets a clean HTTP 422 rather than an error buried in SSE events.
    if request.answer_set is not None:
        redis_state = await engine_runner.state_store.get_workflow_state(request.thread_id)
        validation_errors = engine_runner._validate_answer_set(request, redis_state)
        if validation_errors:
            raise HTTPException(status_code=422, detail={"errors": validation_errors})

    async def event_stream():
        async for payload in encode_sse(engine_runner.resume(session, request)):
            yield payload

    return EventSourceResponse(
        event_stream(),
        ping=10,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/v1/swarm/resume")
async def resume_swarm(request: HITLResumeRequest) -> EventSourceResponse:
    """Resume a suspended swarm after HITL answer. Streams results as SSE."""
    from agentscope_blaiq.workflows.swarm_engine import SwarmEngine
    from agentscope_blaiq.contracts.hitl import WorkflowSuspended

    swarm = SwarmEngine()
    event_queue = asyncio.Queue()

    def publish_sync(role: str, text: str, is_stream: bool = False):
        event_queue.put_nowait((role, text, is_stream))

    async def event_stream():
        # Run resume in a background task
        resume_task = asyncio.create_task(swarm.resume(request, publish=publish_sync))

        while not resume_task.done() or not event_queue.empty():
            try:
                role, text, is_stream = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                
                # Check if text is structured JSON (AgentActivity)
                data_payload = {"role": role, "text": text, "is_stream": is_stream}
                if text.startswith("{") and "metadata" in text:
                    try:
                        data_payload = json.loads(text)
                    except Exception:
                        pass
                
                yield f"data: {json.dumps(data_payload)}\n\n"
            except asyncio.TimeoutError:
                if resume_task.done():
                    break
                continue
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'detail': str(e)})}\n\n"
                break

        try:
            results = await resume_task
            yield f"data: {json.dumps({'status': 'complete', 'results': results})}\n\n"
        except WorkflowSuspended as exc:
            payload = {
                'status': 'suspended',
                'session_id': exc.session_id,
                'hitl': {'question': exc.question, 'options': exc.options, 'why': exc.why},
            }
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'status': 'error', 'detail': str(exc)})}\n\n"

    return EventSourceResponse(
        event_stream(),
        ping=10,
        headers={
            "Cache-Control": "no-cache, no-transform", 
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        },
    )


import httpx
from fastapi.responses import StreamingResponse

class ProcessWorkflowRequest(BaseModel):
    input: list[Any]
    session_id: str
    user_id: str | None = None

@app.post("/process")
async def process_workflow_proxy(
    request: ProcessWorkflowRequest, 
    req: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    AaaS Control Plane Gateway:
    Intercepts frontend requests, validates them, and securely proxies the 
    SSE stream to the internal AgentScope cluster.
    """
    # 1. Auth Validation
    # In production, extract user_id from HTTPOnly cookies or JWT
    user_id = request.user_id or "default_user"
    
    # 2. Network Routing
    # Inside docker, strategist-service runs on 8090. Locally, it's 8095.
    agentscope_host = os.environ.get("STRATEGIST_HOST", "strategist-service")
    agentscope_port = os.environ.get("STRATEGIST_PORT", "8090")
    
    # Fallback for local dev without Docker
    if settings.app_env == "development" and not os.environ.get("DOCKER_ENV"):
        agentscope_host = "localhost"
        agentscope_port = "8095"

    agentscope_url = f"http://{agentscope_host}:{agentscope_port}/process"
    
    async def stream_generator():
        # Using a long timeout since agent reasoning can take minutes
        async with httpx.AsyncClient(timeout=600.0) as client:
            try:
                async with client.stream("POST", agentscope_url, json={
                    "input": request.input,
                    "session_id": request.session_id,
                    "user_id": user_id
                }) as response:
                    async for chunk in response.aiter_bytes():
                        # Database Hook: Here we could decode the chunk, look for 
                        # metadata.kind == 'design_spec', and UPDATE the DB asynchronously.
                        yield chunk
            except Exception as e:
                import json
                error_msg = json.dumps({"metadata": {"kind": "error"}, "content": f"Control Plane Proxy Error: {str(e)}"})
                yield f"data: {error_msg}\n\n".encode("utf-8")

    return StreamingResponse(
        stream_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no" # Prevent Nginx from buffering SSE
        }
    )

@app.get("/api/v1/workflows/{thread_id}/status")
async def workflow_status(thread_id: str, session: AsyncSession = Depends(get_db)):
    snapshot = await WorkflowRepository(session).get_status(thread_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return snapshot


@app.post("/api/v1/workflows/{thread_id}/cancel")
async def cancel_workflow(thread_id: str, session: AsyncSession = Depends(get_db)):
    """Cancel/stop a running workflow immediately."""
    repo = WorkflowRepository(session)
    workflow = await repo.get_workflow_record(thread_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Request cancellation via engine
    await engine_runner.cancel(thread_id)

    # Mark as cancelled
    snapshot = await repo.get_status(thread_id)
    if snapshot and snapshot.status not in {WorkflowStatus.complete, WorkflowStatus.error}:
        await repo.state_store.mark_error(thread_id, "Workflow cancelled by user")
        await repo.update_status(thread_id, WorkflowStatus.error, error_message="Workflow cancelled by user")

    return {"ok": True, "thread_id": thread_id, "status": "cancelled"}


@app.get("/api/v1/agents/live")
async def live_agents():
    return {"agents": registry.list_live()}


@app.get("/api/v1/agent-profiles")
async def agent_profiles(
    role: str | None = Query(default=None),
    capability: str | None = Query(default=None),
    skill: str | None = Query(default=None),
    tool: str | None = Query(default=None),
    transport: str | None = Query(default=None),
    status: str | None = Query(default=None),
    artifact_family: str | None = Query(default=None),
):
    return registry.profile_catalog_response(
        role=role,
        capability=capability,
        skill=skill,
        tool=tool,
        transport=transport,
        status=status,
        artifact_family=artifact_family,
    )


@app.get("/api/v1/agent-profiles/{profile_id}")
async def agent_profile(profile_id: str):
    profile = registry.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return {
        "profile": profile.model_dump(mode="json"),
        "routing_index": profile.routing_index(),
    }


@app.post("/api/v1/agents/custom/register")
async def register_custom_agent(spec: CustomAgentSpec):
    """Register a custom agent spec. Validates against harness contracts before persisting."""
    reg = _get_user_agent_registry()
    registration = reg.register(spec)
    if not registration.harness_valid:
        raise HTTPException(
            status_code=422,
            detail={"agent_id": registration.agent_id, "errors": registration.validation_errors},
        )
    return {
        "ok": True,
        "agent_id": registration.agent_id,
        "display_name": registration.display_name,
        "registered_at": registration.registered_at.isoformat(),
        "warnings": registration.warnings,
    }


@app.get("/api/v1/agents/custom/list")
async def list_custom_agents():
    """List all registered custom agents."""
    reg = _get_user_agent_registry()
    agents = reg.list_all()
    return {
        "count": len(agents),
        "agents": [
            {
                "agent_id": s.agent_id,
                "display_name": s.display_name,
                "role": s.role,
                "model_hint": s.model_hint,
                "tags": s.tags,
                "allowed_workflows": s.allowed_workflows,
            }
            for s in agents
        ],
    }


class AgentDraftRequest(BaseModel):
    description: str = Field(min_length=5, description="Natural language description of what the agent should do")


class RemoteAgentCardRequest(BaseModel):
    card: dict[str, Any]
    source_ref: str | None = None


@app.post("/api/v1/agent-profiles/remote-a2a")
async def register_remote_agent_profile(req: RemoteAgentCardRequest):
    try:
        profile = registry.register_remote_agent_card(req.card, source_ref=req.source_ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "profile": profile.model_dump(mode="json"),
        "routing_index": profile.routing_index(),
    }


@app.post("/api/v1/agents/custom/draft")
async def draft_custom_agent(req: AgentDraftRequest):
    """Use LLM to extract a custom agent spec from a natural language description.

    Returns a pre-filled spec that can be reviewed and submitted to /register.
    """
    snapshot = registry.harness_registry.get_harness_snapshot()
    available_roles = list(snapshot.get("agents", {}).keys())
    available_tools = list(snapshot.get("tools", {}).keys())
    available_workflows = list(snapshot.get("workflows", {}).keys())

    prompt = (
        f"User wants to create a custom AI agent. Their description:\n"
        f"\"{req.description}\"\n\n"
        f"Extract a structured agent specification from this description.\n\n"
        f"Role selection guide:\n"
        f"- text_buddy: writing text content (emails, social posts, LinkedIn posts, memos, letters, proposals, summaries)\n"
        f"- content_director: planning content structure and sections (NOT writing final text)\n"
        f"- vangogh: rendering visual artifacts (posters, pitch decks, HTML)\n"
        f"- research: gathering evidence and information\n"
        f"- governance: reviewing and approving content\n"
        f"- strategist: planning workflows and routing\n\n"
        f"Available base roles: {available_roles}\n"
        f"Available tools: {available_tools}\n"
        f"Available workflows: {available_workflows}\n\n"
        f"Return ONLY valid JSON with these fields:\n"
        f'{{\n'
        f'  "agent_id": "snake_case_id (e.g. linkedin_writer)",\n'
        f'  "display_name": "Human Readable Name",\n'
        f'  "role": "closest matching role from the available roles list",\n'
        f'  "prompt": "detailed system prompt for this agent (min 20 chars)",\n'
        f'  "model_hint": "sonnet",\n'
        f'  "allowed_tools": ["pick relevant tools from available list"],\n'
        f'  "allowed_workflows": ["pick relevant workflows from available list"],\n'
        f'  "tags": ["relevant", "tags"],\n'
        f'  "artifact_family": "email|summary|social_post|memo|proposal|letter|invoice|null",\n'
        f'  "status_messages": ["3-4 short status updates (max 40 chars each) that this agent should stream while working, matching its specific persona"],\n'
        f'  "missing_info": ["list any info you need from the user to complete the spec"]\n'
        f'}}'

    )

    try:
        response = await registry.resolver.acompletion(
            "routing",
            [
                {"role": "system", "content": "You are an agent specification extractor. Return only valid JSON. No explanation."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.1,
        )
        raw = registry.resolver.extract_text(response)
        parsed = registry.resolver.safe_json_loads(raw)

        # Ensure role is valid
        if parsed.get("role") not in available_roles:
            parsed["role"] = "text_buddy"

        # Filter tools/workflows to only valid ones
        parsed["allowed_tools"] = [t for t in (parsed.get("allowed_tools") or []) if t in available_tools]
        parsed["allowed_workflows"] = [w for w in (parsed.get("allowed_workflows") or []) if w in available_workflows]

        # Fill defaults
        if not parsed.get("allowed_workflows"):
            parsed["allowed_workflows"] = ["text_artifact_v1", "direct_answer_v1"]
        if not parsed.get("allowed_tools"):
            role_harness = snapshot.get("agents", {}).get(parsed["role"], {})
            parsed["allowed_tools"] = list(role_harness.get("allowed_tools", []))

        # Add schemas from base role
        role_harness = snapshot.get("agents", {}).get(parsed["role"], {})
        parsed["input_schema"] = role_harness.get("input_schema", {"type": "object", "properties": {}})
        parsed["output_schema"] = role_harness.get("output_schema", {"type": "object", "properties": {}})

        missing = parsed.pop("missing_info", [])
        return {"ok": True, "spec": parsed, "missing_info": missing}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "spec": None, "missing_info": []}


@app.post("/api/v1/contracts/validate")
async def validate_agent_spec(spec: CustomAgentSpec):
    """Dry-run validation of a custom agent spec without persisting."""
    hr = registry.harness_registry
    ok, errors = validate_custom_agent_spec(spec, hr)
    return {"ok": ok, "agent_id": spec.agent_id, "errors": errors}


@app.get("/api/v1/contracts/snapshot")
async def contracts_snapshot():
    """Return full harness snapshot: agents, tools, and workflow templates."""
    return registry.harness_registry.get_harness_snapshot()


@app.get("/api/v1/hivemind/config")
async def hivemind_config():
    client = registry.hivemind
    return {
        "enabled": client.enabled,
        "rpc_url": client.rpc_url,
        "user_id": _parse_hivemind_user_id(client.rpc_url),
        "timeout_seconds": client.timeout_seconds,
        "poll_interval_seconds": client.poll_interval_seconds,
        "poll_attempts": client.poll_attempts,
    }


@app.post("/api/v1/hivemind/test")
async def hivemind_test(request: HivemindTestRequest):
    client = registry.hivemind
    if not client.enabled:
        raise HTTPException(status_code=409, detail="HIVE-MIND MCP is not configured")
    try:
        raw = await client.recall(query=request.query, limit=request.limit, mode=request.mode)
        payload = client._extract_tool_payload(raw)
        memories = []
        for key in ("memories", "results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                memories = [item for item in value if isinstance(item, dict)]
                break
        preview = [
            {
                "id": item.get("memory_id") or item.get("id"),
                "title": item.get("title") or item.get("name") or "Untitled memory",
                "summary": str(item.get("summary") or item.get("snippet") or item.get("content") or "")[:240],
                "project": item.get("project"),
                "source_type": item.get("source_type"),
            }
            for item in memories[:10]
        ]
        return {
            "ok": True,
            "query": request.query,
            "count": len(memories),
            "preview": preview,
            "raw": payload,
        }
    except HivemindMCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class HivemindOAuthStartRequest(BaseModel):
    code_challenge: str
    state: str
    redirect_uri: str


@app.post("/api/v1/hivemind/oauth/start")
async def hivemind_oauth_start(request: HivemindOAuthStartRequest):
    """Start Hivemind OAuth 2.1 + PKCE flow."""
    if not settings.hivemind_oauth_client_id:
        raise HTTPException(status_code=400, detail="HIVEMIND_OAUTH_CLIENT_ID not configured")

    auth_url = (
        f"{settings.hivemind_oauth_authorize_url}?"
        f"response_type=code&"
        f"client_id={settings.hivemind_oauth_client_id}&"
        f"code_challenge={request.code_challenge}&"
        f"code_challenge_method=S256&"
        f"state={request.state}&"
        f"redirect_uri={request.redirect_uri}&"
        f"scope=workspace:read%20memories:read%20memories:write&"
        f"resource={settings.hivemind_oauth_url}"
    )

    return {"auth_url": auth_url, "state": request.state}


class HivemindOAuthCallbackRequest(BaseModel):
    code: str
    state: str
    code_verifier: str
    redirect_uri: str


@app.post("/api/v1/hivemind/oauth/callback")
async def hivemind_oauth_callback(request: HivemindOAuthCallbackRequest):
    """Exchange authorization code for tokens (PKCE)."""
    import httpx

    if not settings.hivemind_oauth_client_id:
        raise HTTPException(status_code=400, detail="HIVEMIND_OAUTH_CLIENT_ID not configured")

    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        resp = await client.post(
            settings.hivemind_oauth_token_url,
            data={
                "grant_type": "authorization_code",
                "code": request.code,
                "client_id": settings.hivemind_oauth_client_id,
                "code_verifier": request.code_verifier,
                "redirect_uri": request.redirect_uri,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Token exchange failed: {resp.text}")

        token_data = resp.json()

    # Store token server-side (in memory for MVP, Redis/encrypted DB in production)
    access_token = token_data.get("access_token")
    _hivemind_oauth_tokens["default"] = access_token

    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in"),
    }


@app.get("/api/v1/hivemind/oauth/status")
async def hivemind_oauth_status():
    """Check if Hivemind is currently connected via OAuth."""
    import httpx

    # Retrieve token from in-memory store (use Redis/encrypted DB in production)
    access_token = _hivemind_oauth_tokens.get("default")

    if not access_token:
        return {
            "connected": False,
            "workspace_name": None,
            "scopes": [],
        }

    # Verify token via /oauth/connection-status
    connection_status_url = f"{settings.hivemind_oauth_url}/oauth/connection-status"

    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(
                connection_status_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "connected": True,
                    "workspace_name": data.get("workspace_name"),
                    "scopes": data.get("scopes", []),
                }
    except Exception:
        pass

    return {
        "connected": False,
        "workspace_name": None,
        "scopes": [],
    }


@app.post("/api/v1/hivemind/oauth/disconnect")
async def hivemind_oauth_disconnect():
    """Revoke Hivemind access."""
    import httpx

    if not settings.hivemind_oauth_client_id:
        raise HTTPException(status_code=400, detail="HIVEMIND_OAUTH_CLIENT_ID not configured")

    access_token = _hivemind_oauth_tokens.get("default")

    if access_token:
        # Revoke token on Hivemind server
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                await client.post(
                    settings.hivemind_oauth_revoke_url,
                    data={
                        "token": access_token,
                        "client_id": settings.hivemind_oauth_client_id,
                    },
                )
        except Exception:
            pass  # Best effort - still clear local token

        # Remove token from store
        _hivemind_oauth_tokens.pop("default", None)

    return {"ok": True}


@app.get("/api/v1/hivemind/org-info")
async def hivemind_org_info():
    """Get HiveMind organization info from stored or env credentials."""
    # Check stored credentials first, then fall back to env
    org_id = _hivemind_credentials.get("org_id") or settings.hivemind_enterprise_org_id
    user_id = _hivemind_credentials.get("user_id") or settings.hivemind_enterprise_user_id

    if not org_id:
        return {
            "org_name": "Unknown Organization",
            "memory_findings": 0,
            "web_findings": 0,
            "upload_findings": 0,
            "save_back": "Manual only",
            "configured": False,
        }

    return {
        "org_name": org_id,
        "org_id": org_id,
        "user_id": user_id,
        "memory_findings": 0,
        "web_findings": 0,
        "upload_findings": 0,
        "save_back": "Enabled via HiveMind Enterprise",
        "configured": True,
    }


@app.post("/api/v1/hivemind/credentials/set")
@app.put("/api/v1/hivemind/credentials/set")
async def hivemind_set_credentials(request: HivemindCredentialsRequest):
    """Set HiveMind enterprise credentials for this session."""
    _hivemind_credentials["api_key"] = request.api_key
    _hivemind_credentials["org_id"] = request.org_id
    _hivemind_credentials["user_id"] = request.user_id
    _hivemind_credentials["base_url"] = request.base_url or "https://core.hivemind.davinciai.eu:8050"

    # Also update hivemind_client's stored credentials
    hivemind_stored_creds.update(_hivemind_credentials)

    return {
        "ok": True,
        "message": f"HiveMind credentials configured for org: {request.org_id}",
        "org_id": request.org_id,
    }


@app.get("/api/v1/hivemind/credentials/status")
async def hivemind_credentials_status():
    """Get HiveMind credentials configuration status."""
    has_stored = bool(_hivemind_credentials.get("api_key"))
    has_env = bool(settings.hivemind_enterprise_api_key)

    return {
        "configured": has_stored or has_env,
        "source": "session" if has_stored else ("env" if has_env else "none"),
        "org_id": _hivemind_credentials.get("org_id") or settings.hivemind_enterprise_org_id,
        "user_id": _hivemind_credentials.get("user_id") or settings.hivemind_enterprise_user_id,
    }


@app.post("/api/v1/hivemind/credentials/clear")
async def hivemind_clear_credentials():
    """Clear session HiveMind credentials."""
    _hivemind_credentials.clear()
    hivemind_stored_creds.clear()
    return {"ok": True, "message": "HiveMind credentials cleared"}


@app.post("/api/v1/upload")
async def upload_file(
    file: UploadFile = File(...),
    tenant_id: str = Form(default="default"),
    thread_id: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=422, detail="filename is required")
    upload_id = str(uuid4())
    target_dir = settings.upload_dir / tenant_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file.filename
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="empty uploads cannot be used for research")
    target_path.write_bytes(content)
    validation = validate_uploaded_document(target_path)
    metadata = {"content_length": str(len(content)), "research_validation": validation}
    await UploadRepository(session).save(
        upload_id=upload_id,
        tenant_id=tenant_id,
        filename=file.filename,
        storage_path=str(target_path),
        content_type=file.content_type,
        metadata=metadata,
        thread_id=thread_id,
    )
    return {
        "status": "success",
        "upload_id": upload_id,
        "filename": file.filename,
        "storage_path": str(target_path),
        "tenant_id": tenant_id,
        "research_validation": validation,
    }


@app.get("/api/v1/artifacts/{thread_id}")
async def get_artifact(thread_id: str, session: AsyncSession = Depends(get_db)):
    artifact = await ArtifactRepository(session).get_by_thread(thread_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@app.get("/api/v1/artifacts/{thread_id}/download")
async def download_artifact(thread_id: str, session: AsyncSession = Depends(get_db)):
    artifact = await ArtifactRepository(session).get_by_thread(thread_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    html = artifact.get("html") or artifact.get("bundle_html") or ""
    if not html:
        raise HTTPException(status_code=404, detail="No HTML content in artifact")
    title = artifact.get("title", "blaiq-artifact")
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip().replace(" ", "-")[:50]
    return HTMLResponse(
        content=html,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.html"',
            "Content-Type": "text/html; charset=utf-8",
        },
    )


# ─── Brand DNA ──────────────────────────────────────────────────────────────

import json as _json
from pathlib import Path as _Path
from .brand_dna_service import BrandDnaExtractionService

_BRAND_DNA_DIR = _Path(settings.artifact_dir) / "brand_dna"
_JOBS: dict[str, dict] = {} # In-memory job tracking to replace SQL


def _default_compiled_brand_dna() -> dict[str, object]:
    return {
        "theme": "Custom Brand",
        "version": "2.0",
        "description": "",
        "tokens": {
            "primary": "#111111",
            "background": "#FFFFFF",
            "surface": "#F5F5F5",
            "border": "#D1D5DB",
            "accent_blue": "#2563EB",
            "accent_emerald": "#10B981",
            "accent_purple": "#7C3AED",
            "muted": "#6B7280",
            "ink": "#111827",
        },
        "typography": {
            "headings": "Inter, Arial, sans-serif",
            "body": "Inter, Arial, sans-serif",
            "title_massive": "text-6xl font-bold tracking-tight",
            "body_default": "text-base leading-relaxed",
        },
        "effects": [],
    }


def _coerce_brand_dna_document(tenant_id: str, payload: dict | None) -> dict | None:
    if payload is None:
        return None
    if payload.get("schema_version") == "brand-dna/v2":
        compiled = payload.get("compiled") or {
            "theme": payload.get("theme"),
            "version": payload.get("version"),
            "description": payload.get("description"),
            "tokens": payload.get("tokens", {}),
            "typography": payload.get("typography", {}),
            "effects": payload.get("effects", []),
        }
        normalized = _default_compiled_brand_dna()
        normalized.update({k: v for k, v in compiled.items() if k not in {"tokens", "typography", "effects"}})
        normalized["tokens"].update(compiled.get("tokens", {}))
        normalized["typography"].update(compiled.get("typography", {}))
        normalized["effects"] = list(compiled.get("effects", []))
        payload["compiled"] = normalized
        payload["theme"] = normalized["theme"]
        payload["version"] = normalized["version"]
        payload["description"] = normalized["description"]
        payload["tokens"] = normalized["tokens"]
        payload["typography"] = normalized["typography"]
        payload["effects"] = normalized["effects"]
        payload.setdefault("meta", {"tenant_id": tenant_id, "extraction_mode": "manual"})
        payload.setdefault("sources", [])
        payload.setdefault("evidence", {"raw_brand_dna": None, "warnings": []})
        payload.setdefault("design_readme", "")
        payload.setdefault("layers", {
            "extracted": payload["evidence"].get("raw_brand_dna"),
            "normalized": {},
            "designer_handoff": {},
            "compiled": normalized,
        })
        return payload

    compiled = _default_compiled_brand_dna()
    compiled.update({k: v for k, v in payload.items() if k not in {"tokens", "typography", "effects"}})
    compiled["tokens"].update(payload.get("tokens", {}))
    compiled["typography"].update(payload.get("typography", {}))
    compiled["effects"] = list(payload.get("effects", []))
    return {
        "schema_version": "brand-dna/v2",
        "meta": {
            "tenant_id": tenant_id,
            "extraction_mode": "manual",
        },
        "sources": [],
        "evidence": {
            "raw_brand_dna": None,
            "warnings": [],
        },
        "design_readme": "",
        "layers": {
            "extracted": None,
            "normalized": {},
            "designer_handoff": {},
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


class ExtractBrandDnaRequest(BaseModel):
    upload_ids: list[str]
    mode: str = "auto"


@app.post("/api/v1/brand-dna/{tenant_id}/extract")
async def extract_brand_dna(
    tenant_id: str,
    request: ExtractBrandDnaRequest,
    session: AsyncSession = Depends(get_db),
):
    if not request.upload_ids:
        raise HTTPException(status_code=400, detail="upload_ids are required")
    
    upload_repo = UploadRepository(session)
    job_id = str(uuid4())
    
    _JOBS[job_id] = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "status": "queued",
        "progress": 0,
        "intermediate_json": None,
        "result_json": None,
        "error_message": None
    }
    
    class MemoryRepo:
        def __init__(self, job_id): self.job_id = job_id
        async def update_job(self, jid, status=None, progress=None, intermediate_json=None, result_json=None, error_message=None):
            j = _JOBS.get(jid)
            if not j: return
            if status: j["status"] = status
            if progress is not None: j["progress"] = progress
            if intermediate_json: j["intermediate_json"] = intermediate_json
            if result_json: j["result_json"] = result_json
            if error_message: j["error_message"] = error_message

    from agentscope_blaiq.persistence.database import get_session_local
    
    async def _run():
        db_factory = get_session_local()
        db = db_factory()
        try:
            m_repo = MemoryRepo(job_id)
            u_repo = UploadRepository(db)
            service = BrandDnaExtractionService(tenant_id, m_repo, u_repo)
            await service.run_extraction(job_id, request.upload_ids)
        except Exception:
            logging.exception("Background extraction failed")
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error_message"] = "Background extraction failed"
        finally:
            await db.close()

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/v1/brand-dna/{tenant_id}/extract/{job_id}")
async def get_extraction_status(
    tenant_id: str,
    job_id: str,
):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Extraction job not found")
    if job["tenant_id"] != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "error_message": job["error_message"],
        "brand_dna": _coerce_brand_dna_document(tenant_id, _json.loads(job["result_json"])) if job["result_json"] else None,
        "intermediate": _json.loads(job["intermediate_json"]) if job["intermediate_json"] else None,
    }



@app.get("/api/v1/brand-dna/{tenant_id}")
async def get_brand_dna(tenant_id: str):
    path = _BRAND_DNA_DIR / f"{tenant_id}.json"
    if not path.exists():
        return {"tenant_id": tenant_id, "brand_dna": None}
    try:
        payload = _json.loads(path.read_text(encoding="utf-8"))
        return {"tenant_id": tenant_id, "brand_dna": _coerce_brand_dna_document(tenant_id, payload)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read brand DNA: {exc}") from exc


@app.put("/api/v1/brand-dna/{tenant_id}")
async def save_brand_dna(tenant_id: str, payload: dict):
    _BRAND_DNA_DIR.mkdir(parents=True, exist_ok=True)
    path = _BRAND_DNA_DIR / f"{tenant_id}.json"
    document = _coerce_brand_dna_document(tenant_id, payload) or _coerce_brand_dna_document(tenant_id, {})
    path.write_text(_json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"tenant_id": tenant_id, "saved": True}


@app.get("/api/v1/brand-dna/{tenant_id}/css")
async def get_brand_dna_css(tenant_id: str):
    """Return the brand DNA as a ready-to-embed CSS string for Vangogh."""
    path = _BRAND_DNA_DIR / f"{tenant_id}.json"
    if not path.exists():
        return {"tenant_id": tenant_id, "css": None}
    try:
        dna = _coerce_brand_dna_document(tenant_id, _json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {"tenant_id": tenant_id, "css": None}
    compiled = dna.get("compiled", {}) if dna else {}
    tokens = compiled.get("tokens", {})
    typo = compiled.get("typography", {})
    css_vars = "\n".join(f"  --brand-{k}: {v};" for k, v in tokens.items())
    css = f""":root {{
{css_vars}
  --brand-font-headings: {typo.get('headings', 'system-ui, sans-serif')};
  --brand-font-body: {typo.get('body', 'system-ui, sans-serif')};
}}"""
    return {"tenant_id": tenant_id, "css": css, "tokens": tokens, "typography": typo}
