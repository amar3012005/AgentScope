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


def _create_decorator_app() -> AgentApp:
    try:
        return AgentApp(app_name="agentscope", app_description="AgentScope Runtime")
    except TypeError:
        return AgentApp(title="agentscope", description="AgentScope Runtime")


_fallback_app = _create_decorator_app()
app = _fallback_app

from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings

import json
from typing import Optional, Dict, Any, AsyncGenerator

from agentscope_blaiq.runtime.agent_base import BaseAgent

class OracleAgent(BaseAgent):
    """
    The Smart Human-in-the-Loop (HITL) Node.
    Analyzes the calling agent's context and formulates a rich, professional question.
    """
    def __init__(
        self,
        resolver: LiteLLMModelResolver | None = None,
    ) -> None:
        if resolver:
            self.model = resolver.build_agentscope_model("oracle")
        else:
            self.model = None

    async def ask(
        self,
        msgs,
        request: AgentRequest = None,
        **kwargs,
    ):
        """
        Suspends workflow and waits for user input.
        """
        resolver = LiteLLMModelResolver.from_settings(settings)
        self.model = resolver.build_agentscope_model("oracle")

        latest_msg = msgs[-1]
        if isinstance(latest_msg, dict):
            latest_msg = Msg(**latest_msg)
            
        metadata = latest_msg.metadata or {}
        raw_question = latest_msg.content

        logger.info(f"Refining HITL question for session {request.session_id}")

        # Oracle review is a one-shot LLM call, wrap it for telemetry
        await self._universal_acting_hook(agent_name="Oracle", phase="consulting_hive-mind")

        async for item in self.ask_human_internal(
            raw_question=raw_question,
            context=metadata,
        ):
            yield item, True

    async def ask_human_internal(
        self, 
        raw_question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Msg, None]:
        """
        Uses an LLM and Artifact Schemas to formulate a precise, professional question.
        """
        context = context or {}
        artifact_type = context.get("artifact_type", "unknown")
        
        # Blueprint Loading (Flexible Pathing)
        blueprint_content = ""
        # Normalize mapping (e.g. pitch track -> visual_pitch_deck)
        mapping = {
            "pitch track": "visual_pitch_deck",
            "pitch deck": "visual_pitch_deck",
            "presentation": "visual_pitch_deck"
        }
        mapped_type = mapping.get(artifact_type.lower(), artifact_type)
        
        possible_paths = [
            f"/app/data/blueprints/{mapped_type}.md",
            f"data/blueprints/{mapped_type}.md"
        ]
        
        for path in possible_paths:
            try:
                with open(path, "r") as f:
                    blueprint_content = f.read()
                    logger.info(f"Oracle loaded blueprint: {path}")
                    break
            except Exception:
                continue

        # Evidence Parsing (Turning facts into buttons)
        evidence_summary = context.get("detail", {}).get("memories", [])
        answer_options = []
        if evidence_summary:
            for mem in evidence_summary[:3]:
                text = mem.get("text", "")[:40] + "..."
                answer_options.append(f"Focus on: {text}")
        answer_options.append("I'll provide custom direction")

        system_prompt = f"""
You are the BLAIQ Oracle. Refine AI questions into strategic B2B choices.
Your goal is to bridge Research and the Content Director.

### ARTIFACT BLUEPRINT
{blueprint_content if blueprint_content else "No blueprint found."}

### MISSION CONTEXT
- Mission: {context.get('mission', 'active')}
- Artifact Type: {artifact_type}

### TASK
Based on the raw evidence and the blueprint, formulate a high-fidelity question.
You MUST provide:
1. **REFINED QUESTION**: A strategic, professional question.
2. **WHY IT MATTERS**: A 1-sentence justification of how this choice impacts the {artifact_type}.
3. **OPTIONS**: 3-4 distinct paths forward based on the evidence.

### OUTPUT STRUCTURE (JSON)
{{
  "question": "...",
  "why_it_matters": "...",
  "options": ["...", "..."]
}}
"""
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": f"Evidence: {raw_question}", "role": "user"}
        ]
        
        response = await self.model(messages)
        logger.info(f"Oracle received response. Type: {type(response)}")
        
        # Robust JSON Extraction
        output_data = {}
        content = ""
        try:
            blocks = getattr(response, "content", None)
            if isinstance(blocks, str): content = blocks
            elif isinstance(blocks, list):
                for b in blocks:
                    if isinstance(b, dict): content += b.get("text", "")
                    elif hasattr(b, "text"): content += str(b.text)
            
            if not content:
                content = getattr(response, "text", "")
            
            # Robust JSON cleaning
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()
            
            logger.info(f"Oracle cleaned content: {content[:200]}...")
            
            # Find JSON in content
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                output_data = json.loads(json_match.group(0))
                logger.info("Oracle successfully parsed JSON response.")
            else:
                logger.warning("Oracle could not find JSON in response. Using fallback.")
        except Exception as e:
            logger.error(f"Oracle parsing failed: {e}")

        refined_question = output_data.get("question") or raw_question
        final_options = output_data.get("options") or answer_options
        why_matters = output_data.get("why_it_matters") or "Critical for mission alignment."

        logger.info(f"Oracle formulation complete. Question: {refined_question[:50]}...")

        yield Msg(
            name="Oracle",
            content=f"{refined_question}\n\n**Why it matters:** {why_matters}",
            role="assistant",
            metadata={
                "kind": "hitl_request",
                "stage": "hitl_strategic_intervention",
                "requires_input": True,
                "options": final_options,
                "why_it_matters": why_matters,
                "artifact_type": artifact_type,
            }
        )

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oracle-v2")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Oracle HITL Node online.")
    yield
    logger.info("Oracle HITL Node offline.")

# Initialize the real production app
app = AgentApp(
    app_name="OracleV2",
    app_description="Human-in-the-Loop Orchestration Node",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)

@app.query(framework="agentscope")
async def ask(
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """
    Suspends workflow and waits for user input.
    """
    resolver = LiteLLMModelResolver.from_settings(settings)
    oracle = OracleAgent(resolver=resolver)

    latest_msg = msgs[-1]
    logger.info(f"DEBUG: Raw latest_msg: {latest_msg}")
    
    context = {} # Initialize default
    
    # Handle different message formats (dict, Msg, etc.)
    if hasattr(latest_msg, "metadata") and latest_msg.metadata:
        context = latest_msg.metadata
    elif isinstance(latest_msg, dict) and "metadata" in latest_msg and latest_msg["metadata"]:
        context = latest_msg["metadata"]
    else:
        # Check if metadata is in the content list as a dedicated part
        content = getattr(latest_msg, "content", [])
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict): continue
                
                # Check for explicit data/metadata types
                if part.get("type") == "data":
                    context = part.get("data", {})
                    break
                elif "metadata" in part:
                    context = part["metadata"]
                    break
                # Check for stringified JSON in text parts (AaaS flattening fallback)
                elif part.get("text") and part["text"].strip().startswith("{"):
                    try:
                        potential_json = json.loads(part["text"])
                        if isinstance(potential_json, dict) and ("mission" in potential_json or "current_status" in potential_json):
                            context = potential_json
                            break
                    except Exception:
                        pass
        else:
            context = {}
            
    question = ""
    if hasattr(latest_msg, "get_text_content"):
        # Filter out the JSON part from the question text if possible
        raw_text = latest_msg.get_text_content()
        # If it's a multi-part message, only take the first non-JSON part
        if isinstance(content, list):
            for part in content:
                txt = part.get("text", "")
                if txt and not txt.strip().startswith("{"):
                    question = txt
                    break
        if not question: question = raw_text
    elif isinstance(latest_msg, dict):
        question = latest_msg.get("content", "")
        if isinstance(question, list):
            question = "".join([p.get("text", "") for p in question if isinstance(p, dict) and p.get("type") == "text" and not p.get("text", "").strip().startswith("{")])

    logger.info(f"Triggering Smart HITL for session {request.session_id}. Context keys: {list(context.keys())}")

    async for item in oracle.ask_human_internal(
        raw_question=question,
        context=context
    ):
        yield item, True

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
