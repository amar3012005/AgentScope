# -*- coding: utf-8 -*-
import logging
from typing import Optional, List, Dict, Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.formatter import OpenAIChatFormatter
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

class TextBuddyAgent(ReActAgent):
    """
    A robust, dynamic text artifact generator.
    Inherits from ReActAgent to support tool-calling and reasoning.
    """
    def __init__(
        self,
        name: str,
        hivemind: HivemindMCPClient,
        resolver: LiteLLMModelResolver,
        sys_prompt: Optional[str] = None,
        **kwargs
    ) -> None:
        model = resolver.get_model()
        formatter = OpenAIChatFormatter()
        # ReActAgent requires model, sys_prompt, and formatter
        super().__init__(
            name=name, 
            sys_prompt=sys_prompt or "You are TextBuddy.", 
            model=model,
            formatter=formatter,
            **kwargs
        )
        self.hivemind = hivemind
        self.resolver = resolver

    async def __call__(self, msgs: List[Msg], **kwargs) -> Msg:
        """Custom execution to pull context before reasoning."""
        latest_msg = msgs[-1]
        artifact_type = latest_msg.metadata.get("artifact_type", "general")
        evidence_brief = latest_msg.metadata.get("evidence_brief", "")
        hitl_feedback = latest_msg.metadata.get("hitl_feedback", "")

        # 1. Fetch Blueprint and Tone (Internal Logic)
        # We can also register these as tools, but for speed we do it here
        blueprint = await self._recall_blueprint(artifact_type)
        brand_tone = await self._recall_brand_tone()

        # 2. Update System Prompt with the new context
        # We don't modify self.sys_prompt permanently, we inject into the reasoning loop
        context_prompt = f"""
You are TextBuddy, the universal artifact engine for BLAIQ.
Your task is to write a high-fidelity {artifact_type} based on the evidence provided.

### BRAND VOICE
{brand_tone}

### STRUCTURAL BLUEPRINT
{blueprint if blueprint else "Follow standard professional conventions for " + artifact_type}

### EVIDENCE BRIEF
{evidence_brief}

### HITL FEEDBACK
{hitl_feedback}
"""
        # 3. Use ReActAgent's reply method (which is the reasoning loop)
        # We wrap the messages with our context
        context_msg = Msg(name="system", content=context_prompt, role="system")
        return self.reply([context_msg] + msgs)

    async def _recall_blueprint(self, artifact_type: str) -> Optional[str]:
        try:
            results = await self.hivemind.recall(
                query=f"{artifact_type} blueprint structure",
                limit=1,
                mode="insight"
            )
            memories = results.get("memories", [])
            return memories[0].get("content") if memories else None
        except Exception:
            return None

    async def _recall_brand_tone(self) -> str:
        try:
            results = await self.hivemind.recall(
                query="brand voice tone style guidelines",
                limit=1
            )
            memories = results.get("memories", [])
            return memories[0].get("content") if memories else "Professional and clear."
        except Exception:
            return "Professional and clear."
