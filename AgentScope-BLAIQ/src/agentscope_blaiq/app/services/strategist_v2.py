# -*- coding: utf-8 -*-
"""
StrategistV2 — Master Orchestrator (Refactored)

Uses AgentScope's Master-Worker Pattern with:
- structured_model for schema-validated MissionPlan output
- Agent-as-Tool for worker delegation
- Evidence quality evaluation for event-driven Oracle escalation
- Direct handoff to WorkflowEngineV2 for execution
"""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

# AgentScope Core
from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from agentscope.memory import InMemoryMemory
from agentscope.pipeline import stream_printing_messages
from agentscope.session import RedisSession
from agentscope.tool import Toolkit, ToolResponse

# AgentScope Runtime (AaaS)
try:
    from agentscope_runtime.engine.app import AgentApp
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
    from agentscope_runtime.engine.deployers.adapter.a2a import AgentCardWithRuntimeConfig
except ImportError:
    from fastapi import FastAPI as AgentApp
    from pydantic import BaseModel
    class AgentRequest(BaseModel):
        query: str
        session_id: str
        user_id: str
    class AgentCardWithRuntimeConfig(BaseModel):
        host: str = "0.0.0.0"

# BLAIQ Internal
from agentscope_blaiq.contracts.aaas import MissionPlan, MissionNode, NodeRole
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hooks import pre_flight_variable_check_hook
from agentscope_blaiq.workflows.swarm_engine import SwarmEngine
from agentscope_blaiq.persistence.redis_state import RedisStateStore
from agentscope_blaiq.tools.enterprise_fleet import get_enterprise_toolkit, active_session_id

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("strategist-v2")

# Register global pre-flight hook for all ReActAgents in the cluster
ReActAgent.register_class_hook(
    hook_type="pre_reply",
    hook_name="blaiq_pre_flight_check",
    hook=pre_flight_variable_check_hook
)


# ─────────────────────────────────────────────
# Structured Output Models
# ─────────────────────────────────────────────

class WorkflowMode(str, Enum):
    SEQUENTIAL = "sequential"
    FANOUT = "fanout"
    CONDITIONAL = "conditional"

class ArtifactFamily(str, Enum):
    TEXT = "text"
    VISUAL = "visual"
    CODE = "code"
    REPORT = "report"

class RequirementStage(str, Enum):
    PRE_RESEARCH = "pre_research"
    POST_RESEARCH = "post_research"
    PRE_SYNTHESIS = "pre_synthesis"
    PRE_RENDER = "pre_render"

class TaskGraph(BaseModel):
    """Structured task decomposition for the mission."""
    mode: WorkflowMode = Field(description="Execution pattern: sequential, fanout, or conditional")
    artifact_family: ArtifactFamily = Field(description="Primary output type")
    required_nodes: list[NodeRole] = Field(description="Ordered list of specialist nodes to invoke")
    hitl_gates: list[RequirementStage] = Field(
        default_factory=list,
        description="Stages where human approval is required"
    )

class RequirementsChecklist(BaseModel):
    """Pre-flight requirements for mission success."""
    research_required: bool = Field(description="Whether research must run first")
    evidence_threshold: str = Field(
        default="sufficient",
        description="Minimum evidence quality: sufficient, partial, or none"
    )
    oracle_on_ambiguous: bool = Field(
        default=True,
        description="Fire Oracle if research yields ambiguous or insufficient context"
    )

class MissionPlanOutput(BaseModel):
    """Schema-validated mission plan produced by the Strategist."""
    workflow_mode: WorkflowMode = Field(description="How to execute the pipeline")
    artifact_family: ArtifactFamily = Field(description="What type of artifact to produce")
    task_graph: TaskGraph = Field(description="Decomposed task graph with node ordering")
    requirements_checklist: RequirementsChecklist = Field(description="Pre-flight requirements")
    success_criteria: list[str] = Field(description="Measurable success conditions")
    notes: list[str] = Field(default_factory=list, description="Additional context or constraints")


# ─────────────────────────────────────────────
# Evidence Quality Evaluator
# ─────────────────────────────────────────────

class EvidenceEvaluator:
    """Evaluates research evidence quality to determine if Oracle escalation is needed."""

    INSUFFICIENT_INDICATORS = [
        "no data", "no results", "could not find", "insufficient",
        "limited information", "no relevant", "empty", "none found",
        "no evidence", "unavailable", "not found"
    ]

    @classmethod
    def evaluate(cls, evidence_text: str) -> tuple[bool, str]:
        """
        Returns (should_fire_oracle, reason).
        Fires Oracle if evidence is insufficient for proceeding.
        """
        if not evidence_text or len(evidence_text.strip()) < 50:
            return True, "Evidence too short or empty — insufficient context for synthesis"

        lower = evidence_text.lower()
        for indicator in cls.INSUFFICIENT_INDICATORS:
            if indicator in lower:
                return True, f"Evidence flagged: '{indicator}' — Oracle escalation recommended"

        return False, "Evidence appears sufficient — proceeding to synthesis"


# ─────────────────────────────────────────────
# Lifecycle Management
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.session = RedisSession(connection_pool=redis_client.connection_pool)
    app.state.redis_client = redis_client
    logger.info(f"Connected to Redis session store at {settings.redis_url}")

    try:
        yield
    finally:
        await redis_client.close()
        logger.info("AgentApp session store shut down.")


# ─────────────────────────────────────────────
# AgentApp Initialization
# ─────────────────────────────────────────────

app = AgentApp(
    app_name="StrategistV2",
    app_description="Master Orchestrator for BLAIQ Enterprise Workflows",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)


# ─────────────────────────────────────────────
# Master Orchestrator Query Handler
# ─────────────────────────────────────────────

@app.query(framework="agentscope")
async def build_mission_plan(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """
    Master Orchestrator Query Handler.

    1. Produces a schema-validated MissionPlan via structured_model
    2. Evaluates evidence quality for Oracle escalation
    3. Hands off execution to WorkflowEngineV2
    4. Streams events back to the client
    """
    session_id = request.session_id
    user_id = request.user_id or "default_user"

    # 1. Setup model
    resolver = LiteLLMModelResolver.from_settings(settings)
    model = resolver.build_agentscope_model("strategic")

    # Cast messages to Msg objects
    msgs = [Msg(**m) if isinstance(m, dict) else m for m in msgs]
    user_goal = msgs[0].content if msgs else ""

    # 2. Instantiate the Master Orchestrator Agent
    # Minimal system prompt — orchestration logic is handled by structured_model and framework
    agent = ReActAgent(
        name="StrategistMaster",
        model=model,
        sys_prompt=(
            "You are the BLAIQ Master Orchestrator. "
            "Analyze the user's goal and produce a structured MissionPlan. "
            "Always require research before synthesis. "
            "Enable Oracle escalation when evidence may be ambiguous. "
            "Decompose the task into an ordered list of specialist nodes."
        ),
        memory=InMemoryMemory(),
        formatter=OpenAIChatFormatter(),
        toolkit=get_enterprise_toolkit(),
    )

    # 3. Load session state from Redis
    await app.state.session.load_session_state(
        session_id=session_id,
        user_id=user_id,
        agent=agent,
    )

    # Set session context for tool calls
    token = active_session_id.set(session_id)

    try:
        # 4. Produce structured MissionPlan
        plan_response = await agent(
            Msg("user", user_goal, "user"),
            structured_model=MissionPlanOutput,
        )

        # Extract the structured plan from metadata
        plan_data = plan_response.metadata
        if not plan_data:
            yield Msg(
                "StrategistMaster",
                "ERROR: Failed to produce a structured mission plan.",
                "assistant"
            ), True
            return

        # 5. Convert structured plan to MissionPlan contract
        mission_plan = _build_mission_contract(plan_data, session_id)

        # 6. Evaluate evidence quality (if research already ran)
        evidence_text = _extract_evidence_from_memory(agent)
        should_fire_oracle, oracle_reason = EvidenceEvaluator.evaluate(evidence_text)

        if should_fire_oracle:
            logger.info(f"Oracle escalation triggered: {oracle_reason}")
            # Inject Oracle node into the task graph
            _inject_oracle_node(mission_plan, oracle_reason)

        # 7. Stream the plan back to the client
        yield Msg(
            "StrategistMaster",
            f"Mission plan created: {mission_plan.title} "
            f"(Nodes: {[n.role.value for n in mission_plan.topology]})",
            "assistant"
        ), False

        # 8. Handoff to SwarmEngine for execution (MsgHub + ServiceProxyAgent pattern)
        logger.info(f"Handoff to SwarmEngine for session {session_id}")
        engine = SwarmEngine()

        async def swarm_publisher(role: str, text: str, is_stream: bool = False):
            """Publish SwarmEngine events back to the streaming client."""
            if is_stream:
                return  # Skip streaming chunks for now
            if text.startswith("Starting"):
                yield Msg("Engine", f"▶ {role}: {text}", "assistant"), False
            else:
                yield Msg("Engine", f"✔ {role}: Completed", "assistant"), False

        try:
            results = await engine.run(
                goal=user_goal,
                session_id=session_id,
                artifact_family=mission_plan.artifact_type,
                publish=lambda role, text, is_stream=False: asyncio.create_task(
                    _async_yield_from_publisher(swarm_publisher, role, text, is_stream)
                ),
                with_oracle=True,
            )

            # Stream final results
            for role, output in results.items():
                if output:
                    yield Msg(
                        role.replace("_", " ").title(),
                        output,
                        "assistant"
                    ), False

            # Final status
            yield Msg(
                "StrategistMaster",
                f"MISSION STATUS: Completed\n"
                f"ARTIFACT: {mission_plan.artifact_type}\n"
                f"NODES EXECUTED: {len(results)}",
                "assistant"
            ), True

        except Exception as e:
            logger.error(f"SwarmEngine execution failed: {e}")
            yield Msg(
                "StrategistMaster",
                f"MISSION FAILED: {e}",
                "assistant"
            ), True

    except asyncio.CancelledError:
        logger.warning(f"Strategist session {session_id} was interrupted by user.")
        await agent.interrupt()
        raise

    finally:
        # Save session state back to Redis
        await app.state.session.save_session_state(
            session_id=session_id,
            user_id=user_id,
            agent=agent,
        )
        active_session_id.reset(token)


# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

async def _async_yield_from_publisher(publisher, role: str, text: str, is_stream: bool = False):
    """Bridge between SwarmEngine's publish callback and the async generator yield."""
    async for msg, is_last in publisher(role, text, is_stream):
        pass  # Publisher handles yielding internally


def _build_mission_contract(plan_data: dict, session_id: str) -> MissionPlan:
    """Convert structured LLM output into a MissionPlan contract."""
    task_graph = plan_data.get("task_graph", {})
    requirements = plan_data.get("requirements_checklist", {})
    required_nodes = task_graph.get("required_nodes", ["research"])

    # Build topology from required nodes
    topology = []
    for i, role_str in enumerate(required_nodes):
        try:
            role = NodeRole(role_str)
        except ValueError:
            # Map common aliases to actual NodeRole values
            alias_map = {
                "text": "text_buddy",
                "synthesis": "text_buddy",
                "composition": "text_buddy",
                "visual": "content_director",
                "storyboard": "content_director",
                "render": "vangogh",
                "image": "vangogh",
                "governance": "governance",
                "review": "governance",
                "oracle": "oracle",
                "hitl": "oracle",
                "research": "research",
            }
            role = NodeRole(alias_map.get(role_str.lower(), "planning"))

        topology.append(MissionNode(
            node_id=f"node_{i}",
            role=role,
            service_endpoint=f"service_{role.value}",
            purpose=f"Execute {role.value} stage",
            depends_on=[f"node_{i-1}"] if i > 0 else [],
        ))

    return MissionPlan(
        mission_id=session_id,
        title=f"Mission: {plan_data.get('artifact_family', 'general')}",
        artifact_type=plan_data.get("artifact_family", "text"),
        topology=topology,
        success_criteria=plan_data.get("success_criteria", ["Artifact produced"]),
        notes=plan_data.get("notes", []),
    )


def _extract_evidence_from_memory(agent: ReActAgent) -> str:
    """Extract research evidence from agent memory for quality evaluation."""
    if not hasattr(agent, "memory") or not agent.memory:
        return ""

    # Get recent messages from memory
    try:
        memory_content = agent.memory.get_memory()
        evidence_parts = []
        for msg in memory_content:
            content = msg.content if hasattr(msg, "content") else str(msg)
            if any(kw in str(content).lower() for kw in ["evidence", "research", "findings", "data"]):
                evidence_parts.append(str(content))
        return " ".join(evidence_parts)
    except Exception:
        return ""


def _inject_oracle_node(mission_plan: MissionPlan, reason: str) -> None:
    """Inject an Oracle (HITL) node into the mission topology after research."""
    oracle_node = MissionNode(
        node_id="node_oracle",
        role=NodeRole.ORACLE,
        service_endpoint="service_oracle",
        purpose=f"HITL escalation: {reason}",
        depends_on=["node_0"],  # Depends on first node (typically research)
    )

    # Insert after the first node (research)
    if len(mission_plan.topology) > 0:
        mission_plan.topology.insert(1, oracle_node)
        # Update dependencies for subsequent nodes
        for i, node in enumerate(mission_plan.topology[2:], start=2):
            node.depends_on = [f"node_{i-1}"]


# ─────────────────────────────────────────────
# Production Interruption Endpoint
# ─────────────────────────────────────────────

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
    uvicorn.run(app, host="0.0.0.0", port=8090)
