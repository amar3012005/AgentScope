# -*- coding: utf-8 -*-
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from pathlib import Path
from typing import AsyncGenerator

# AgentScope Core
from agentscope.message import Msg
from agentscope.tool import Toolkit

# FastAPI Middleware
from fastapi.middleware.cors import CORSMiddleware

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

from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings


SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

class TextBuddy:
    """
    The Standalone Content Factory.
    Synthesizes text artifacts using AgentScope Skills.
    """
    def __init__(self, resolver: LiteLLMModelResolver):
        self.resolver = resolver

    async def generate_artifact(
        self,
        request_text: str,
        artifact_type: str,
        evidence_brief: str = "",
        hitl_feedback: str = ""
    ) -> AsyncGenerator[Msg, None]:

        toolkit = Toolkit()
        toolkit.register_agent_skill(str(SKILLS_DIR / "brand_tone"))

        for candidate in (artifact_type, artifact_type.removeprefix("visual_")):
            candidate_path = SKILLS_DIR / candidate
            if candidate_path.is_dir() and candidate not in ("brand_tone",):
                try:
                    toolkit.register_agent_skill(str(candidate_path))
                except ValueError:
                    pass
                break
        skill_prompt = toolkit.get_agent_skill_prompt()

        system_prompt = f"""
You are the BLAIQ Text Buddy. Synthesize high-quality professional text adhering to Solvis Brand DNA and the provided artifact blueprint.

### QUALITY DIRECTIVES:
1. PRODUCE PRODUCTION-READY OUTPUT: Your output must be the final, high-quality version of the artifact. No placeholder, no "here is a draft". 
2. ONE-SHOT EXCELLENCE: Strive to satisfy all user requirements and brand guidelines immediately in this response.
3. STRUCTURE: Use markdown headings, bullet points, and professional spacing.

AGENTSCOPE SKILLS:
{skill_prompt}

EVIDENCE (GROUND TRUTH):
{evidence_brief if evidence_brief else 'None provided.'}

FEEDBACK (IF ANY):
{hitl_feedback if hitl_feedback else 'None provided.'}

MISSION: Generate a professional {artifact_type} based on the user request.
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request_text}
        ]

        response = await self.resolver.acompletion("text_buddy", messages, stream=True)

        full_content = ""
        async for chunk in response:
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", "") or ""
            if text:
                full_content += text
                yield Msg(name="TextBuddy", content=text, role="assistant", metadata={"is_stream": True})

        # Strip markdown json block if model decided to wrap it
        clean_content = full_content.strip()
        
        yield Msg(
            name="TextBuddy",
            content=clean_content,
            role="assistant",
            metadata={"kind": "text_artifact", "artifact_type": artifact_type, "is_stream": False}
        )

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("text-buddy-v2")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Phase (File-First Mode)
    logger.info("TextBuddy V2 (AaaS-Native | File-First) cluster node online.")
    yield
    logger.info("TextBuddy V2 cluster node offline.")

app = AgentApp(
    app_name="TextBuddyV2",
    app_description="Standalone Dynamic Content Factory (Local Blueprints)",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)

# Fix 403 Forbidden for WebSockets/AaaS by allowing origins
_allowed_origins = [
    origin.strip()
    for origin in settings.allowed_origins.split(",")
    if origin.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=len(_allowed_origins) > 0 and _allowed_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class _SuppressWSProbeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not ("WebSocket /" in msg or "connection open" == msg.strip() or "connection closed" == msg.strip())

for _log_name in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(_log_name).addFilter(_SuppressWSProbeFilter())


@app.websocket("/")
async def ws_health(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.close()


@app.query(framework="agentscope")
async def write_artifact(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """
    Enterprise entry point for text artifact generation.
    """
    resolver = LiteLLMModelResolver.from_settings(settings)
    buddy = TextBuddy(resolver=resolver)

    # 2. Extract context from msgs
    latest_msg = msgs[-1]
    if isinstance(latest_msg, dict):
        latest_msg = Msg(**latest_msg)
        
    request_text = latest_msg.get_text_content()
    # Support both artifact_type and type (for robustness)
    artifact_type = latest_msg.metadata.get("artifact_type") or latest_msg.metadata.get("type", "general")
    evidence_brief = latest_msg.metadata.get("evidence_brief", "")
    hitl_feedback = latest_msg.metadata.get("hitl_feedback", "")

    logger.info(f"Generating {artifact_type} for session {request.session_id}")

    # 3. Generate Artifact (Streaming yield)
    async for item in buddy.generate_artifact(
        request_text=request_text,
        artifact_type=artifact_type,
        evidence_brief=evidence_brief,
        hitl_feedback=hitl_feedback
    ):
        yield item, True

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8093)
