# -*- coding: utf-8 -*-
import logging
import json
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI

# AgentScope Core
from agentscope.message import Msg
from agentscope.agent import ReActAgent
from agentscope.memory import InMemoryMemory
from agentscope.formatter import OpenAIChatFormatter
from agentscope.tool import Toolkit

# AgentScope Runtime (AaaS)
try:
    from agentscope_runtime.engine.app import AgentApp
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
    from agentscope_runtime.engine.deployers.adapter.a2a import AgentCardWithRuntimeConfig
except ImportError:
    from fastapi import FastAPI as AgentApp
    from pydantic import BaseModel
    class AgentRequest(BaseModel):
        input: list
        session_id: str
        user_id: str
    class AgentCardWithRuntimeConfig(BaseModel):
        host: str = "0.0.0.0"

from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.tools.enterprise_fleet import get_enterprise_toolkit, active_session_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("content-director-v2")


def resolve_artifact_type(msg_text: str, metadata: dict) -> str:
    t = metadata.get("artifact_type", "")
    if t == "poster":
        return "visual_poster"
    if t == "pitch_deck":
        return "visual_pitch_deck"
    if t:
        return t
    text = msg_text.lower()
    if "poster" in text:
        return "visual_poster"
    if "pitch" in text or "deck" in text or "slide" in text:
        return "visual_pitch_deck"
    return "visual_pitch_deck"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Content Director V2 online.")
    yield
    logger.info("Content Director V2 offline.")


app = AgentApp(
    app_name="ContentDirectorV2",
    app_description="Blueprint-Neutral Two-Phase Visual Orchestration Node",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)


@app.query(framework="agentscope")
async def orchestrate(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    resolver = LiteLLMModelResolver.from_settings(settings)
    model = resolver.build_agentscope_model("content_director")

    latest_msg = msgs[-1]
    if isinstance(latest_msg, dict):
        latest_msg = Msg(**latest_msg)

    msg_text = latest_msg.get_text_content() or ""
    metadata = latest_msg.metadata if hasattr(latest_msg, "metadata") and latest_msg.metadata else {}

    artifact_type = resolve_artifact_type(msg_text, metadata)

    evidence_brief = metadata.get("evidence_brief", "")
    if evidence_brief:
        msg_text = f"## RESEARCH EVIDENCE (GROUND TRUTH — do NOT call hivemind_recall):\n{evidence_brief}\n\nMISSION: {msg_text}"
        latest_msg.content = msg_text

    logger.info(f"ContentDirector resolved artifact_type={artifact_type}")

    from pathlib import Path
    skills_dir = Path(__file__).resolve().parents[2] / "skills"
    toolkit = Toolkit()
    toolkit.register_agent_skill(str(skills_dir / "brand_dna"))
    for candidate in (artifact_type, artifact_type.removeprefix("visual_")):
        candidate_path = skills_dir / candidate
        if candidate_path.is_dir() and candidate not in ("brand_dna",):
            try:
                toolkit.register_agent_skill(str(candidate_path))
            except ValueError:
                pass
            break

    agent = ReActAgent(
        name="ContentDirector",
        model=model,
        sys_prompt=(
            "### BLAIQ CONTENT DIRECTOR\n"
            "You are a strict visual architect. Use only the provided RESEARCH EVIDENCE — do NOT call hivemind_recall.\n\n"
            "### PHASES (output both in sequence):\n"
            "   - **PHASE 1 (Abstract)**: JSON block mapping evidence to blueprint sections. No visual details.\n"
            "   - **PHASE 2 (Detailed)**: JSON block with full synthesis and detailed visual_spec for every section.\n\n"
            "### OUTPUT FORMAT:\n"
            'Phase 1: {"phase": "abstract", "sections": [{"id": "...", "content_plan": "..."}]}\n'
            'Phase 2: {"phase": "detailed", "sections": [{"id": "...", "synthesis": "...", "visual_spec": "..."}]}\n'
        ),
        toolkit=toolkit,
        memory=InMemoryMemory(),
        formatter=OpenAIChatFormatter()
    )

    token = active_session_id.set(request.session_id)

    try:
        # Direct await — stream_printing_messages does not forward to SSE in this runtime version
        result_msg = await agent(msgs)
        content = result_msg.get_text_content() or ""

        # Extract the last valid "detailed" JSON block; fall back to any valid block
        output_content = content
        if "{" in content and '"phase"' in content:
            clean = content.strip()
            if clean.startswith("```"):
                clean = re.sub(r'^```[a-z]*\n?', '', clean).rstrip('`').strip()
            # Match top-level JSON objects (non-nested brace scan)
            blocks = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', clean, re.DOTALL)
            for block in reversed(blocks):
                try:
                    data = json.loads(block)
                    if data.get("phase") == "detailed":
                        output_content = json.dumps(data, indent=2)
                        logger.info("ContentDirector extracted phase=detailed")
                        break
                    elif data.get("phase") == "abstract":
                        output_content = json.dumps(data, indent=2)
                except Exception:
                    continue

        yield Msg(
            name="ContentDirector",
            content=output_content,
            role="assistant",
            metadata={"kind": "storyboard_detailed", "artifact_type": artifact_type}
        ), True
    finally:
        active_session_id.reset(token)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
