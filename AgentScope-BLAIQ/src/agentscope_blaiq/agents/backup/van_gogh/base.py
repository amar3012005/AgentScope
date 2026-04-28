# -*- coding: utf-8 -*-
import logging
from typing import Optional, List, Dict, Any, AsyncGenerator
from agentscope.message import Msg
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

class VanGoghAgent:
    """
    The Visual Execution Node (Van Gogh).
    Implements the VisualSpec provided by the Content Director.
    Outputs Image Prompts, Layout Code (React/Tailwind), or SVG assets.
    """
    def __init__(
        self,
        resolver: LiteLLMModelResolver,
    ) -> None:
        self.resolver = resolver
        self.model = resolver.build_agentscope_model("van_gogh")

    async def render_artifact(
        self, 
        visual_spec: Dict[str, Any],
        brand_dna: str = "",
    ) -> AsyncGenerator[Msg, None]:
        """
        Executes the visual design for a single page or component.
        """
        system_prompt = f"""
You are Van Gogh, the BLAIQ Visual Design Agent.
Your goal is to turn a 'VisualSpec' into a production-ready artifact.

### BRAND DNA (REQUIRED STYLE)
{brand_dna}

### INPUT SPEC
{visual_spec}

### YOUR MISSION
Depending on the spec, you must provide:
1. **VisualAsset**: A descriptive prompt for a DALL-E/Flux image generator.
2. **UIMarkup**: High-quality React/Tailwind code for the layout.
3. **DesignRationale**: Why this design works for the specific context.

### OUTPUT FORMAT (JSON ONLY)
{{
  "AssetPrompt": "...",
  "HTMLCode": "...",
  "Rationale": "..."
}}
"""
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": "Render this design spec.", "role": "user"}
        ]
        
        response = await self.model(messages)
        
        # Robust extraction
        text_content = ""
        try:
            if hasattr(response, "text") and response.text:
                text_content = response.text
            elif hasattr(response, "content") and response.content:
                for block in response.content:
                    if hasattr(block, "text"): text_content += block.text
                    elif isinstance(block, dict): text_content += block.get("text", "")
        except:
            pass

        yield Msg(
            name="VanGogh", 
            content=text_content, 
            role="assistant",
            metadata={"stage": "design_execution"}
        )
