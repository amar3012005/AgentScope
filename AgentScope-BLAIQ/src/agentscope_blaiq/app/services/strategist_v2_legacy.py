# -*- coding: utf-8 -*-
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
import json

# AgentScope Core
from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter # Using OpenAI formatter as standard
from agentscope.pipeline import stream_printing_messages
from agentscope.memory import InMemoryMemory
from agentscope.session import RedisSession

# AgentScope Runtime (AaaS)
try:
    from agentscope_runtime.engine.app import AgentApp
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
    from agentscope_runtime.engine.deployers.adapter.a2a import AgentCardWithRuntimeConfig
except ImportError:
    # Fallback for environment check - in production these must be installed
    from fastapi import FastAPI as AgentApp
    from pydantic import BaseModel
    class AgentRequest(BaseModel):
        query: str
        session_id: str
        user_id: str
    class AgentCardWithRuntimeConfig(BaseModel):
        host: str = "0.0.0.0"

from agentscope_blaiq.contracts.aaas import MissionPlan, MissionNode, NodeRole
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hooks import pre_flight_variable_check_hook
from agentscope_blaiq.workflows.engine_v2 import WorkflowEngineV2
from agentscope_blaiq.persistence.redis_state import RedisStateStore

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("strategist-v2")

# Register global pre-flight hook for all ReActAgents in the cluster
ReActAgent.register_class_hook(
    hook_type="pre_reply",
    hook_name="blaiq_pre_flight_check",
    hook=pre_flight_variable_check_hook
)

# Define Lifecycle for State Management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize the production Redis session pool
    import redis.asyncio as aioredis
    
    # Use the shared BLAIQ redis URL
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    
    app.state.session = RedisSession(
        connection_pool=redis_client.connection_pool
    )
    logger.info(f"Connected to Redis session store at {settings.redis_url}")
    
    try:
        yield
    finally:
        await redis_client.close()
        logger.info("AgentApp session store shut down.")

# Initialize the Official AgentApp
app = AgentApp(
    app_name="StrategistV2",
    app_description="Strategic Architect for BLAIQ Enterprise Workflows",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)

# Implementation of the Strategic Logic
@app.query(framework="agentscope")
async def build_mission_plan(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """
    Official AaaS Query Handler.
    Handles rehydration, Re-Act reasoning, and state persistence.
    """
    session_id = request.session_id
    user_id = request.user_id or "default_user"

    # 1. Setup the model and tools
    resolver = LiteLLMModelResolver.from_settings(settings)
    model = resolver.build_agentscope_model("strategic")
    
    # Cast messages to Msg objects if they are dicts
    from agentscope.message import Msg
    msgs = [Msg(**m) if isinstance(m, dict) else m for m in msgs]
    
    # 2. Instantiate the Re-Act Agent with Enterprise Fleet Tools
    from agentscope_blaiq.tools.enterprise_fleet import get_enterprise_toolkit
    
    agent = ReActAgent(
        name="StrategistV2",
        model=model,
        sys_prompt=(
            "### BLAIQ MASTER ORCHESTRATOR\n"
            "You are the central brain and routing architect of the BLAIQ enterprise fleet. Your job is to analyze the user's request, determine the necessary workflow DAG (Directed Acyclic Graph), and orchestrate the specialized agents to fulfill the mission.\n\n"
            "### THE SPECIALIST FLEET (TOOLS AVAILABLE):\n"
            "- **Research**: Use 'hivemind_recall' or 'research_evidence' to gather facts and build an evidence brief.\n"
            "- **Text Buddy**: Use 'synthesize_text' to write copy, emails, reports, or text artifacts.\n"
            "- **Content Director**: Use 'orchestrate_visuals' to convert text artifacts into visual storyboards and layout logic.\n"
            "- **Van Gogh**: Use 'render_visuals' to generate UI code (React/Tailwind) and asset prompts based on a visual storyboard.\n"
            "- **Oracle (HITL)**: Use 'ask_human' to suspend the pipeline and ask the user for critical missing information or explicit approval.\n"
            "- **Governance**: Use 'govern_artifact' for final quality assurance.\n\n"
            "### ORCHESTRATION RULES:\n"
            "1. **Dynamic Routing**: Do NOT run the entire pipeline unless requested. If the user asks for a text report, stop after Text Buddy. If they ask for a landing page, go all the way to Van Gogh.\n"
            "2. **Research-First**: Always call 'hivemind_recall' or 'research_evidence' BEFORE attempting to synthesize content. Never hallucinate facts.\n"
            "3. **Prudent Oracle Usage**: Do NOT call 'ask_human' on your first thought. Only call it if Research yields absolutely zero context, or if you need human approval on a controversial/strategic pivot. You MUST pass the specific 'artifact_type' in the metadata.\n"
            "4. **Chaining**: Pass the output of one agent as the input to the next (e.g., pass Research evidence to Text Buddy; pass Text Buddy output to Content Director).\n\n"
            "### OUTPUT DISCIPLINE\n"
            "Conclude every orchestration loop with a 'FINAL MISSION REPORT' containing:\n"
            "- MISSION STATUS: (Success/Blocked/Completed)\n"
            "- ACCOMPLISHMENTS: (What nodes you successfully triggered)\n"
            "- NEXT STEPS: (What happens next, or 'Mission Accomplished')\n"
        ),
        memory=InMemoryMemory(),
        formatter=OpenAIChatFormatter(),
        toolkit=get_enterprise_toolkit(),
    )

    # 3. Load agent state from Redis (Persistence)
    await app.state.session.load_session_state(
        session_id=session_id,
        user_id=user_id,
        agent=agent,
    )

    # CORE FIX: Set the session ID in context to prevent LLM hallucinations in tool calls
    from agentscope_blaiq.tools.enterprise_fleet import active_session_id as session_ctx
    token = session_ctx.set(session_id)

    try:
        # 4. Stream the reasoning and output back to the Mission UI
        # This is the official AgentScope streaming pattern
        async for msg, last in stream_printing_messages(
            agents=[agent],
            coroutine_task=agent(msgs),
        ):
            yield msg, last

    except asyncio.CancelledError:
        logger.warning(f"Strategist session {session_id} was interrupted by user.")
        await agent.interrupt()
        raise

    finally:
        # 5. Save the updated state (Memory & Thinking progress) back to Redis
        await app.state.session.save_session_state(
            session_id=session_id,
            user_id=user_id,
            agent=agent,
        )
        
        # 6. Check if we should hand off to Engine V2 for execution
        # If the agent produced a valid MissionPlan/WorkflowPlan, we execute it.
        # This is the "Service-Native" execution path.
        if hasattr(agent, "_notebook") and agent._notebook and agent._notebook.current_plan:
            logger.info(f"Strategist drafting complete. Handoff to EngineV2 for session {session_id}")
            state_store = RedisStateStore(redis_url=settings.redis_url)
            engine = WorkflowEngineV2(state_store=state_store)
            
            # Note: In a real implementation, we'd wrap the yield in a publisher
            # For now, we'll just log the handoff
            # await engine.execute(agent._notebook.current_plan, session_id, lambda e: logger.info(f"Engine Event: {e}"))

# Add the Production Interruption endpoint
@app.post("/stop")
async def stop_strategist(request: AgentRequest):
    """Allows the frontend to kill a runaway planning session."""
    await app.stop_chat(
        user_id=request.user_id,
        session_id=request.session_id,
    )
    return {"status": "success", "message": "Planning interrupted."}

if __name__ == "__main__":
    import uvicorn
    # In production, this runs in a standalone container
    uvicorn.run(app, host="0.0.0.0", port=8090)
