# -*- coding: utf-8 -*-
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncGenerator

from agentscope.message import Msg
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings

logger = logging.getLogger(__name__)

class BlaiqTextBuddyAgent:
    """
    AaaS-Native Text Artifact Generator for BLAIQ.
    Optimized for local file-based blueprint retrieval (PostgreSQL stage 1).
    """
    def __init__(
        self,
        resolver: LiteLLMModelResolver,
        blueprint_dir: Optional[str] = None
    ) -> None:
        self.resolver = resolver
        self.blueprint_dir = Path(blueprint_dir or "/app/data/blueprints")
        self.model = resolver.build_agentscope_model("text_buddy")

    def _get_local_asset(self, filename: str, fallback: str) -> str:
        """Helper to read local asset files."""
        path = self.blueprint_dir / filename
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read local asset {filename}: {e}")
        return fallback

    async def generate_artifact(
        self, 
        request_text: str,
        artifact_type: str,
        evidence_brief: str,
        hitl_feedback: Optional[str] = None
    ) -> AsyncGenerator[Msg, None]:
        """
        Generates an artifact using local structural blueprints.
        """
        # 1. Local Asset Retrieval
        blueprint = self._get_local_asset(f"{artifact_type}.md", f"Standard {artifact_type} format.")
        brand_tone = self._get_local_asset("brand_tone.md", "Professional and clear.")

        # 2. Prompt Construction
        system_prompt = f"""
You are TextBuddy, the lead content engine for BLAIQ Enterprise.
Format: {artifact_type}

### BRAND IDENTITY
{brand_tone}

### STRUCTURE BLUEPRINT
{blueprint}

### EVIDENCE BRIEF
{evidence_brief}

### USER INSTRUCTIONS
{request_text}
{f"FEEDBACK: {hitl_feedback}" if hitl_feedback else ""}

### OUTPUT RULES
- Deliver the final artifact in clean Markdown.
- No conversational filler before or after the artifact.
"""
        
        # 3. Model Execution
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": request_text, "role": "user"}
        ]
        
        # Await the async model call
        response = await self.model(messages)
        
        # 4. Robust Text Extraction (AgentScope specific)
        text_content = ""
        try:
            # Try attribute first
            if hasattr(response, "text") and response.text:
                text_content = response.text
            elif hasattr(response, "content") and response.content:
                # Handle list of blocks
                for block in response.content:
                    if hasattr(block, "text"):
                        text_content += block.text
                    elif isinstance(block, dict):
                        text_content += block.get("text", "")
        except (AttributeError, KeyError):
            pass

        if not text_content:
            # Try dict-style access
            if isinstance(response, dict):
                text_content = response.get("text") or \
                               response.get("choices", [{}])[0].get("message", {}).get("content", "") or \
                               response.get("content", "")
            else:
                # Last resort: string conversion
                text_content = str(response)

        yield Msg(
            name="TextBuddy", 
            content=text_content, 
            role="assistant",
            metadata={"artifact_type": artifact_type}
        )
