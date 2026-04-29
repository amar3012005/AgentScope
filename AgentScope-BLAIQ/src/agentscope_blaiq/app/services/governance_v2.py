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
        self.resolver = resolver
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
You are the BLAIQ Task Success Agent. Your mission is to confirm mission completion to the user in a friendly, conversational way.

### YOUR MISSION:
1. MISSION SUCCESS: Check if the artifact satisfies the user's intent.
2. CONVERSATIONAL RESPONSE: Instead of using "STATUS" or "FIELDS", write a single, friendly passage summarizing what was achieved.
3. CLOSING CONFIRMATION: Tell the user clearly that the work is finished as requested.
4. CALL TO ACTION: End the response by asking: "What would you like to do next?"

### STYLE GUIDELINES:
- No field labels (Review, Summary, etc.)
- No status codes
- Natural, professional, and friendly human-like prose.

### SOLVIS BRAND CONTEXT:
{brand_context}
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"The mission artifact has been generated:\n\n{artifact_content}\n\nPlease certify success and greet the user."}
        ]
        
        response = await self.resolver.acompletion("governance", messages, stream=True)

        full_content = ""
        async for chunk in response:
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", "") or ""
            if text:
                full_content += text
                yield Msg(name="GovernanceAgent", content=text, role="assistant", metadata={"is_stream": True})

        clean_content = full_content.strip()
        
        yield Msg(
            name="GovernanceAgent",
            content=clean_content,
            role="assistant",
            metadata={"kind": "governance_review", "is_stream": False}
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
    uvicorn.run(app, host="0.0.0.0", port=8094)
