# -*- coding: utf-8 -*-
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

# AgentScope Core
from agentscope.message import Msg

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
        
from typing import AsyncGenerator
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings

class GovernanceAgent:
    """
    The BLAIQ Governance Node.
    Ensures safety, brand alignment, and structural integrity of the final artifact.
    """
    def __init__(self, resolver: LiteLLMModelResolver, blueprint_dir: str):
        self.model = resolver.build_agentscope_model("governance")
        self.blueprint_dir = blueprint_dir

    async def review_artifact(
        self,
        artifact_content: str,
    ) -> AsyncGenerator[Msg, None]:
        
        # Load Brand Context (The "Soul" of the brand)
        brand_context = "General business professional style."
        for brand_file in ["solvis_brand_tone.md", "brand_tone.md", "brand_dna.md"]:
            try:
                import os
                path = f"{self.blueprint_dir}/{brand_file}"
                if os.path.exists(path):
                    with open(path, "r") as f:
                        brand_context = f.read()
                        break
            except Exception:
                continue

        system_prompt = f"""
You are the BLAIQ Governance Agent. Your mission is to review the final artifact for safety, brand alignment, and architectural clarity.

### SOLVIS BRAND DNA (MANDATORY CRITERIA):
{brand_context}

### YOUR TASK:
Review the following content. Provide a final, polished version of the artifact.
1. Terminology: Ensure "Energiesystem" is used instead of "Heizung".
2. Persona: Ensure the tone is human, visionary, and grounded.
3. Clarity: Ensure bullet points are used for benefits.
4. Spacing: Ensure clean, readable formatting.

If the content is already perfect, return it as is.
"""
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": f"Please review and finalize this artifact:\n\n{artifact_content}", "role": "user"}
        ]
        
        response = await self.model(messages)
        
        # Bulletproof extraction
        content = ""
        if isinstance(response, dict):
            content = response.get("text") or response.get("content") or str(response)
        else:
            content = getattr(response, "text", None) or getattr(response, "content", str(response))
        
        if isinstance(content, list):
            try:
                parts = []
                for c in content:
                    text_part = ""
                    if isinstance(c, dict):
                        text_part = c.get("text") or c.get("content", "")
                    else:
                        text_part = str(c)
                    
                    if text_part and text_part not in parts:
                        parts.append(text_part)
                # Use double newline to prevent clumping
                content = "\n\n".join(parts)
            except Exception:
                content = str(content)
        elif not isinstance(content, str):
            content = str(content)
            
        clean_content = content.strip()
        
        yield Msg(
            name="GovernanceAgent",
            content=clean_content,
            role="assistant",
            metadata={"kind": "governance_review"}
        )

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("governance-v2")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Governance V2 cluster node online.")
    yield
    logger.info("Governance V2 cluster node offline.")

app = AgentApp(
    app_name="GovernanceV2",
    app_description="Brand Safety & Quality Assurance Node",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)

@app.query(framework="agentscope")
async def process(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """
    Enterprise entry point for governance review.
    """
    resolver = LiteLLMModelResolver.from_settings(settings)
    gov_agent = GovernanceAgent(
        resolver=resolver,
        blueprint_dir="/app/data/blueprints"
    )

    latest_msg = msgs[-1]
    if isinstance(latest_msg, dict):
        latest_msg = Msg(**latest_msg)
        
    artifact_content = latest_msg.get_text_content()

    logger.info(f"Governing artifact for session {request.session_id}")

    async for item in gov_agent.review_artifact(
        artifact_content=artifact_content
    ):
        yield item, True

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
