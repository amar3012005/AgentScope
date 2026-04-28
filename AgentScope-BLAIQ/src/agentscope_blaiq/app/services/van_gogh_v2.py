# -*- coding: utf-8 -*-
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
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
import json
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings

class VanGogh:
    """
    The Visual Execution Node.
    Translates Storyboard pages into Image Prompts and React Code.
    """
    def __init__(self, resolver: LiteLLMModelResolver):
        self.model = resolver.build_agentscope_model("vangogh")

    async def render_artifact(
        self,
        visual_spec: str,
        brand_dna: str
    ) -> AsyncGenerator[Msg, None]:
        
        system_prompt = f"""
You are the BLAIQ Visual Designer (Van Gogh). Your mission is to transform a detailed Visual Specification into a high-fidelity, interactive digital experience.

### BRAND DNA (MANDATORY DESIGN SYSTEM):
{brand_dna}

### YOUR TASKS:
1. **MULTI-SLIDE UI/UX**: If the spec defines multiple slides/sections, you MUST write a React component that includes navigation (tabs, arrows, or scroll-spy) to experience every slide.
2. **IMAGE PROMPTS**: Generate a high-fidelity DALL-E 3 prompt for EVERY major section or slide. Ensure visual consistency across all prompts.
3. **GLASSMORPHISM**: Use Tailwind CSS to implement the 'Glassmorphism' style (backdrop-blur, semi-transparent borders, vibrant gradients) as defined in the Brand DNA.
4. **COMPONENT ARCHITECTURE**: The 'ui_code' must be a single-file React component (using Tailwind) that is visually stunning and responsive.

### OUTPUT FORMAT:
You MUST output a valid JSON object:
{{
  "image_prompts": [
    {{"id": "slide_1", "prompt": "..."}},
    {{"id": "slide_2", "prompt": "..."}}
  ],
  "ui_code": "```jsx\\n...\\n```",
  "design_rationale": "Explanation of how the UX flows and how the Brand DNA was applied."
}}
"""
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": f"VISUAL SPECIFICATION:\n{visual_spec}", "role": "user"}
        ]
        
        response = await self.model(messages)
        
        # Bulletproof extraction: handles ChatResponse, Msg, or raw dict
        content = ""
        if isinstance(response, dict):
            content = response.get("text") or response.get("content") or str(response)
        else:
            content = getattr(response, "text", None) or getattr(response, "content", str(response))
        
        # Handle list-based content blocks
        if isinstance(content, list):
            try:
                content = " ".join([str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content])
            except Exception:
                content = str(content)
        elif not isinstance(content, str):
            content = str(content)
            
        metadata = metadata or {}
        # Parse the JSON response
        try:
            # Strip potential markdown fences if the model added them
            clean_content = content.strip()
            if clean_content.startswith("```"):
                clean_content = re.sub(r'^```[a-z]*\n?', '', clean_content).rstrip('`').strip()
            
            data = json.loads(clean_content)
            logger.info("VanGogh successfully parsed design JSON")
            yield Msg(
                name="VanGogh",
                content=json.dumps(data, indent=2),
                role="assistant",
                metadata={"kind": "design_spec", "artifact_type": metadata.get("artifact_type"), "detail": data}
            ), True
            return # Ensure we never yield twice
        except Exception as e:
            logger.error(f"VanGogh JSON parse failed: {e}")
            # Fallback to raw content if JSON fails
            yield Msg(
                name="VanGogh",
                content=content,
                role="assistant",
                metadata={"kind": "design_spec", "artifact_type": metadata.get("artifact_type")}
            ), True
            return

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("van-gogh-v2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Van Gogh Design Node online.")
    yield
    logger.info("Van Gogh Design Node offline.")

app = AgentApp(
    app_name="VanGoghV2",
    app_description="Visual Execution & Design Node",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)

@app.query(framework="agentscope")
async def render(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """
    Renders design specs into assets and code.
    """
    resolver = LiteLLMModelResolver.from_settings(settings)
    designer = VanGogh(resolver=resolver)

    latest_msg = msgs[-1]
    if isinstance(latest_msg, dict):
        latest_msg = Msg(**latest_msg)
        
    visual_spec = latest_msg.content
    brand_dna = latest_msg.metadata.get("brand_dna", "")

    logger.info(f"Rendering design for session {request.session_id}")

    async for item in designer.render_artifact(
        visual_spec=visual_spec,
        brand_dna=brand_dna
    ):
        yield item, True

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
