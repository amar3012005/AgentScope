# -*- coding: utf-8 -*-
import logging
import json
from typing import Optional, List, Dict, Any, AsyncGenerator
from agentscope.message import Msg
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

class OracleAgent:
    """
    The Smart Human-in-the-Loop (HITL) Node.
    Analyzes the calling agent's context and formulates a rich, professional question.
    """
    def __init__(
        self,
        resolver: LiteLLMModelResolver,
    ) -> None:
        self.resolver = resolver
        self.model = resolver.build_agentscope_model("oracle")

    async def ask_human(
        self, 
        raw_question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Msg, None]:
        """
        Uses an LLM and Artifact Schemas to formulate a precise, professional question.
        """
        context = context or {}
        artifact_type = context.get("artifact_type", "unknown")
        schema_path = f"/app/data/blueprints/{artifact_type}_schema.json"
        
        schema_context = "No specific schema found for this artifact type."
        try:
            with open(schema_path, "r") as f:
                schema_context = f.read()
        except FileNotFoundError:
            logger.warning(f"No schema blueprint found at {schema_path}")

        context_str = json.dumps(context, indent=2)
        
        system_prompt = f"""
You are the BLAIQ Oracle. Your mission is to facilitate high-fidelity collaboration between the AI Fleet and the User.

### MANDATORY NARRATIVE FRAMEWORK: "Accomplishment-Blocker-Key"
You MUST formulate your response using this exact 3-part structure. DO NOT simply repeat the agent's question.

1. **ACCOMPLISHMENT**: Start by summarizing the progress made in the current mission based on the 'current_status' and 'mission' fields in the Snapshot. (e.g., "I've calculated the totals for your Solvis invoice...")
2. **BLOCKER**: Explain that you've reached a point where you cannot proceed without specific data. State the 'missing_variable' and explain its importance to the final 'artifact_type'.
3. **KEY**: Politely ask the user for the missing information so you can finalize the mission.

### ARTIFACT BLUEPRINT (TECHNICAL GUIDELINES)
Use the following schema to understand the MANDATORY requirements and REASONS for the requested data:
{schema_context}

### STRICT RULES
- **JUSTIFICATION**: Use the "Reason" from the blueprint to explain why the user's input is legally or technically critical.
- **CRITICAL**: Do NOT return a single-sentence or technical question (e.g., "What is your VAT ID?").
- **CRITICAL**: You must sound like a professional Executive Assistant.
- **CONTEXT**: Use the specific mission name and stage provided in the snapshot.

### CURRENT MISSION SNAPSHOT
{context_str}
"""
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": f"The agent is asking: '{raw_question}'. Refine this into a context-rich question.", "role": "user"}
        ]
        
        response = await self.model(messages)
        
        # Robust text extraction
        refined_question = ""
        try:
            if hasattr(response, "text") and response.text:
                refined_question = response.text
            elif hasattr(response, "content") and response.content:
                for block in response.content:
                    if hasattr(block, "text"): refined_question += block.text
                    elif isinstance(block, dict): refined_question += block.get("text", "")
        except:
            pass

        if not refined_question:
            refined_question = raw_question

        logger.info(f"Oracle formulated smart question: {refined_question}")
        
        yield Msg(
            name="Oracle", 
            content=refined_question, 
            role="assistant",
            metadata={
                "stage": "hitl_smart_intervention",
                "requires_input": True,
                "original_request": raw_question,
                "context_snapshot": context or {}
            }
        )
