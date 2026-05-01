# -*- coding: utf-8 -*-
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
import json

# AgentScope Core
from agentscope.pipeline import stream_printing_messages
from agentscope.memory import InMemoryMemory
from agentscope.session import RedisSession
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

    # Create a module-level app instance for decorators to use
    _fallback_app = AgentApp(title="agentscope", description="AgentScope Runtime")
    app = _fallback_app

from agentscope_blaiq.runtime.agent_base import BaseAgent
from agentscope_blaiq.agents.deep_research.base import BlaiqDeepResearchAgent
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hooks import hitl_research_verification_hook

# Setup logging
logger = logging.getLogger("research-v2")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Phase: Setup Hivemind client and Redis state pool
    import redis.asyncio as aioredis
    
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.session = RedisSession(
        connection_pool=redis_client.connection_pool
    )
    
    # Pre-initialize shared Hivemind client
    app.state.hivemind = HivemindMCPClient(
        rpc_url=settings.hivemind_mcp_rpc_url,
        api_key=settings.hivemind_api_key,
        timeout_seconds=settings.hivemind_timeout_seconds
    )
    
    logger.info("Deep Research V2 cluster node online.")
    try:
        yield
    finally:
        await redis_client.close()
        logger.info("Deep Research V2 cluster node offline.")

# Initialize the real production app
app = AgentApp(
    app_name="DeepResearchV2",
    app_description="HIVE-MIND Powered Tree-Search Research Service",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)

@app.post("/recall")
async def quick_recall(
    request: AgentRequest,
):
    """
    Fast-path for instant Hivemind memory retrieval.
    No LLM reasoning, just direct HIVE-MIND MCP access.
    """
    # 1. Extract query
    input_msgs = request.input or []
    from agentscope.message import Msg
    input_msgs = [Msg(**m) if isinstance(m, dict) else m for m in input_msgs]
    user_query = input_msgs[-1].get_text_content() if input_msgs else ""
    
    logger.info(f"⚡ Quick Recall requested for: {user_query}")
    
    # 2. Hit Hivemind directly via the pre-initialized client
    try:
        # Phase 1: Direct Memory & Entity Lookup
        raw_results = await app.state.hivemind.recall(
            query=user_query,
            limit=10
        )
        results = app.state.hivemind._extract_tool_payload(raw_results)
        
        # 3. Return Structured JSON
        memories = results.get("memories", [])
        return {
            "message": f"Found {len(memories)} relevant memories for '{user_query}'.",
            "kind": "recall_results",
            "detail": results
        }
    except Exception as e:
        logger.error(f"Recall failed: {str(e)}")
        return {"error": f"Error during quick recall: {str(e)}"}

class DeepResearchV2(BaseAgent):
    """
    Core Research Logic: Always attempts Recall first.
    Triggers when Strategist calls research service.
    """
    @app.query(framework="agentscope")
    async def process(
        self,
        msgs,
        request: AgentRequest = None,
        **kwargs,
    ):
        """
        Core Research Logic: Always attempts Recall first.
        Triggers when Strategist calls research service.
        """
        # 1. Initialize the Deep Research Agent
        resolver = LiteLLMModelResolver.from_settings(settings)
        agent = BlaiqDeepResearchAgent(
            hivemind=app.state.hivemind,
            resolver=resolver,
        )

        # 2. Run the agent to gather and synthesize findings
        user_query = msgs[-1].get_text_content() if msgs else ""
        session_id = request.session_id if request else "unknown"
        logger.info(f"[RESEARCH START] Session {session_id} | Query: {user_query}")

        pack = await agent.gather(
            session=None,
            tenant_id="default",
            user_query=user_query,
            source_scope="all"
        )
        
        # 3. Return the synthesized report
        logger.info(f"[RESEARCH COMPLETE] Found {len(pack.sources)} sources | Summary Length: {len(pack.summary) if pack.summary else 0}")
        return Msg(
            name="Researcher",
            content=pack.summary,
            role="assistant",
            metadata={
                "kind": "synthesized_evidence",
                "confidence": pack.confidence,
                "sources": len(pack.sources)
            }
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8091)
