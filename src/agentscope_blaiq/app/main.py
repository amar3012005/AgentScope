from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentscope_blaiq.contracts.workflow import ResumeWorkflowRequest, SubmitWorkflowRequest, WorkflowStatus
from agentscope_blaiq.persistence.database import get_db
from agentscope_blaiq.persistence.migrations import bootstrap_database
from agentscope_blaiq.persistence.repositories import ArtifactRepository, UploadRepository, WorkflowRepository
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPError
from agentscope_blaiq.runtime.registry import AgentRegistry
from agentscope_blaiq.tools.docs import validate_uploaded_document
from agentscope_blaiq.streaming.sse import encode_sse
from agentscope_blaiq.workflows.engine import WorkflowEngine
from agentscope_blaiq.runtime.hivemind_client import _stored_credentials as hivemind_stored_creds
from .model_resolver import current_litellm_config
from .runtime_checks import check_runtime_ready, check_storage_paths


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    await bootstrap_database()
    yield


app = FastAPI(title="AgentScope-BLAIQ", version="0.1.0", lifespan=lifespan)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

# CORS — allow the frontend dev server
_allowed_origins = [
    origin
    for origin in (settings.allowed_origins if hasattr(settings, "allowed_origins") else "").split(",")
    if origin.strip()
] or ["http://localhost:3002", "http://127.0.0.1:3002"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

registry = AgentRegistry()
engine_runner = WorkflowEngine(registry)

# In-memory OAuth token store (use Redis/encrypted DB in production)
_hivemind_oauth_tokens: dict[str, str] = {}

# In-memory HiveMind enterprise credentials store
_hivemind_credentials: dict[str, str] = {}


class HivemindCredentialsRequest(BaseModel):
    api_key: str
    org_id: str
    user_id: str
    base_url: str | None = None


class HivemindTestRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    mode: str = "insight"


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
async def submit_workflow(request: SubmitWorkflowRequest, session: AsyncSession = Depends(get_db)) -> EventSourceResponse:
    if not request.user_query or not request.user_query.strip():
        raise HTTPException(status_code=422, detail="user_query cannot be empty")

    async def event_stream():
        async for payload in encode_sse(engine_runner.run(session, request)):
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
        await repo.update_status(thread_id, WorkflowStatus.error, error_message="Workflow cancelled by user")

    return {"ok": True, "thread_id": thread_id, "status": "cancelled"}


@app.get("/api/v1/agents/live")
async def live_agents():
    return {"agents": registry.list_live()}


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
