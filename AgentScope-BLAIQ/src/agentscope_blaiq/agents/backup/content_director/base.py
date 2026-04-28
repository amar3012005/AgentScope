# -*- coding: utf-8 -*-
import logging
import json
from typing import Optional, List, Dict, Any, AsyncGenerator

from agentscope.message import Msg
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

class ContentDirectorAgent:
    """
    The Visual Architect of the BLAIQ Pipeline.
    Takes Text Artifacts + Research Evidence and generates high-fidelity 
    Visual Prompts and Layout Instructions for the Van Gogh agent.
    """
    def __init__(
        self,
        resolver: LiteLLMModelResolver,
        blueprint_dir: str = "/app/data/blueprints"
    ) -> None:
        self.resolver = resolver
        self.blueprint_dir = Path(blueprint_dir)
        self.model = resolver.build_agentscope_model("content_director")

    def _get_local_asset(self, filename: str, fallback: str) -> str:
        """Helper to read local asset files."""
        path = self.blueprint_dir / filename
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read local asset {filename}: {e}")
        return fallback

    async def orchestrate_visuals(
        self, 
        text_artifact: str,
        evidence_brief: str,
        artifact_type: str,
    ) -> AsyncGenerator[Msg, None]:
        """
        Generates a Multi-Page Visual Storyboard with Gap Analysis.
        """
        # Load Brand DNA
        brand_dna = self._get_local_asset("brand_dna.md", "Standard modern UI/UX.")

        system_prompt = f"""
You are the Executive Content Director for BLAIQ. 
Your goal is to transform a complex text artifact into a high-fidelity, context-rich Visual Storyboard.

### BRAND DNA (MANDATORY STYLE)
{brand_dna}

### YOUR MISSION
1. **Decompose**: Break the input text into a logical multi-page/multi-section structure (e.g., Slides 1-7).
2. **Context Mapping**: Assign specific facts from the 'Evidence Context' to each specific page.
3. **Gap Analysis**: For every page, determine if the information is "Context-Rich" or "Context-Poor".
4. **Action Plan**: 
   - If Context-Poor: Propose a 'DeepResearchQuery' to fill the gap.
   - If Context-Rich: Generate a detailed 'VisualSpec' for the designer.

### OUTPUT FORMAT (JSON ONLY)
{{
  "Storyboard": [
    {{
      "PageNumber": 1,
      "Title": "The Hook",
      "CoreText": "...",
      "ContextStatus": "Rich|Poor",
      "ResearchGap": "None | Specific query if poor",
      "VisualSpec": {{
        "Composition": "...",
        "VanGoghPrompt": "...",
        "UIComponents": ["..."]
      }}
    }}
  ],
  "RequiresRefinement": boolean
}}
"""
        
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": f"Decompose this artifact into a context-rich storyboard. \nTEXT: {text_artifact}\nEVIDENCE: {evidence_brief}", "role": "user"}
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
            name="ContentDirector", 
            content=text_content, 
            role="assistant",
            metadata={"artifact_type": artifact_type, "stage": "storyboard_orchestration"}
        )
