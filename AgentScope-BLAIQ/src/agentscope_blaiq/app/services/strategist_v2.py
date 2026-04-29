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
import json
import re
import os
import uuid
from contextlib import asynccontextmanager
from enum import Enum
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
from agentscope_blaiq.contracts.hitl import WorkflowSuspended
from agentscope_blaiq.contracts.aaas import MissionPlan, MissionNode, NodeRole
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hooks import pre_flight_variable_check_hook
from agentscope_blaiq.workflows.swarm_engine import SwarmEngine
from agentscope_blaiq.persistence.redis_state import RedisStateStore
from agentscope_blaiq.tools.enterprise_fleet import get_enterprise_toolkit, get_strategist_toolkit, active_session_id

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("strategist-v2")

_DIRECT_GREETING_PATTERN = re.compile(
    r"^\s*(hi|hello|hey|yo|good\s+(morning|afternoon|evening)|who\s+are\s+you)\s*[!.?]*\s*$",
    re.IGNORECASE,
)


def _stringify_agent_event_content(content: object) -> str:
    """Normalize AgentScope message content into a user-visible string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = (
                    block.get("text")
                    or block.get("thinking")
                    or block.get("output")
                    or block.get("name")
                )
                if text:
                    parts.append(str(text))
                continue
            text = (
                getattr(block, "text", None)
                or getattr(block, "thinking", None)
                or getattr(block, "output", None)
            )
            if text:
                parts.append(str(text))
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def _is_direct_greeting(user_goal: str) -> bool:
    return bool(_DIRECT_GREETING_PATTERN.match(user_goal or ""))

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
    is_direct: bool = Field(default=False, description="Whether this is a direct response (no mission needed)")
    direct_response: Optional[str] = Field(default=None, description="The content for the direct response if is_direct is True")
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

_PLANNING_SYSTEM_PROMPT = """\
You are BLAIQ-CORE, the high-level Mission Architect for an enterprise AI swarm.

Your ONLY job: analyse the user goal and output a JSON MissionPlan. NEVER write the artifact itself.

OUTPUT FORMAT — respond with ONLY valid JSON matching this schema exactly:
{
  "is_direct": false,
  "direct_response": null,
  "workflow_mode": "sequential",
  "artifact_family": "text",
  "task_graph": {
    "mode": "sequential",
    "artifact_family": "text",
    "required_nodes": ["research", "text_buddy", "governance"],
    "hitl_gates": []
  },
  "requirements_checklist": {
    "research_required": true,
    "evidence_threshold": "sufficient",
    "oracle_on_ambiguous": true
  },
  "success_criteria": ["Artifact produced", "Brand-aligned"],
  "notes": []
}

Rules:
- artifact_family: "text" | "visual" | "code" | "report"
- required_nodes: ordered list from ["research","text_buddy","content_director","vangogh","governance","oracle"]
- For emails/summaries/posts: ["research","text_buddy","governance"]
- For pitch decks/landing pages/visuals: ["research","content_director","vangogh","governance"]
- If user says hello/who are you: set is_direct=true, direct_response="brief greeting", required_nodes=[]
- Output ONLY JSON. No markdown. No explanation.
"""


@app.query(framework="agentscope")
async def build_mission_plan(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """
    Master Orchestrator — streams planning tokens in real-time via resolver.acompletion(stream=True).
    Removes ReActAgent+structured_model silent 49s gap. Events flow immediately.
    """
    session_id = request.session_id
    resolver = LiteLLMModelResolver.from_settings(settings)

    msgs = [Msg(**m) if isinstance(m, dict) else m for m in msgs]
    user_goal = msgs[0].get_text_content() if msgs else ""

    # ── 1. Immediate start signal ──────────────────────────────────────────
    yield Msg("StrategistMaster", json.dumps({
        "type": "agent_started",
        "agent_name": "Strategist",
        "phase": "planning",
        "data": {"message": "BLAIQ-CORE is architecting the mission..."}
    }), "assistant"), False

    # ── 2. Greeting fast path (instant, no LLM call) ───────────────────────
    if _is_direct_greeting(user_goal):
        direct_response = "Hello! I'm BLAIQ-CORE, your Mission Architect. How can I help?"
        for word in direct_response.split():
            yield Msg("StrategistMaster", json.dumps({
                "type": "workflow_event",
                "agent_name": "Strategist",
                "phase": "planning",
                "data": {"content": word + " ", "streaming": True}
            }), "assistant"), False
        yield Msg("StrategistMaster", json.dumps({
            "type": "agent_completed",
            "agent_name": "Strategist",
            "data": {"is_direct": True, "direct_response": direct_response}
        }), "assistant"), True
        return

    # ── 3. Stream planning LLM call — real-time token emission ────────────
    messages = [
        {"role": "system", "content": _PLANNING_SYSTEM_PROMPT},
        {"role": "user", "content": user_goal},
    ]

    accumulated = ""
    try:
        response = await resolver.acompletion("strategic", messages, stream=True)
        async for chunk in response:
            delta = chunk.choices[0].delta
            token = getattr(delta, "content", "") or ""
            if token:
                accumulated += token
                yield Msg("StrategistMaster", json.dumps({
                    "type": "workflow_event",
                    "agent_name": "Strategist",
                    "phase": "planning",
                    "data": {"content": token, "streaming": True, "is_reflection": True}
                }), "assistant"), False
    except Exception as e:
        logger.error(f"Planning LLM call failed: {e}")
        yield Msg("StrategistMaster", f"ERROR: Planning failed: {e}", "assistant"), True
        return

    # ── 4. Parse plan from streamed response ──────────────────────────────
    try:
        plan_data = resolver.safe_json_loads(accumulated)
    except Exception:
        plan_data = None

    if not plan_data:
        yield Msg("StrategistMaster", "ERROR: Failed to parse mission plan from LLM response.", "assistant"), True
        return

    # ── 5. Direct response: stream word-by-word then signal completion ─────
    if plan_data.get("is_direct"):
        response_text = plan_data.get("direct_response") or "How can I help you today?"
        for word in response_text.split():
            yield Msg("StrategistMaster", json.dumps({
                "type": "workflow_event",
                "agent_name": "Strategist",
                "phase": "planning",
                "data": {"content": word + " ", "streaming": True}
            }), "assistant"), False
        yield Msg("StrategistMaster", json.dumps({
            "type": "agent_completed",
            "agent_name": "Strategist",
            "data": {"is_direct": True, "direct_response": response_text}
        }), "assistant"), True
        return

    # ── 6. Build MissionPlan contract and emit planning_complete ──────────
    mission_plan = _build_mission_contract(plan_data, session_id)

    yield Msg("StrategistMaster", json.dumps({
        "type": "planning_complete",
        "data": {
            "plan": {
                "title": mission_plan.title,
                "artifact_type": mission_plan.artifact_type,
                "tasks": [
                    {"id": node.node_id, "label": node.role.value.replace("_", " ").title(), "status": "pending"}
                    for node in mission_plan.topology
                ]
            }
        }
    }), "assistant"), False

    # ── 7. Handoff to SwarmEngine ─────────────────────────────────────────
    logger.info(f"Handoff to SwarmEngine for session {session_id}")
    engine = SwarmEngine()
    event_queue = asyncio.Queue()

    def swarm_publish_sync(role: str, text: str, is_stream: bool = False):
        event_queue.put_nowait((role, text, is_stream))

    # Run engine in a background task so we can yield from the queue
    swarm_task = asyncio.create_task(engine.run(
        goal=user_goal,
        session_id=session_id,
        artifact_family=mission_plan.artifact_type,
        publish=swarm_publish_sync,
        with_oracle=True,
        skip_planning=True,
    ))

    while not swarm_task.done() or not event_queue.empty():
        try:
            role, text, is_stream = await asyncio.wait_for(event_queue.get(), timeout=0.1)

            if text.strip().startswith("{"):
                try:
                    json.loads(text)
                    yield Msg(role.replace("_", " ").title(), text, "assistant"), False
                    continue
                except Exception:
                    pass

            yield Msg(role.replace("_", " ").title(), text, "assistant"), is_stream
        except asyncio.TimeoutError:
            if swarm_task.done():
                break
            continue
        except Exception as e:
            logger.error(f"Error yielding from swarm queue: {e}")
            break

        # Check for task result/exceptions
        try:
            results = await swarm_task
            
            # Final status
            yield Msg(
                "StrategistMaster",
                f"MISSION STATUS: Completed\n"
                f"ARTIFACT: {mission_plan.artifact_type}\n"
                f"NODES EXECUTED: {len(results)}",
                "assistant"
            ), True

        except WorkflowSuspended as exc:
            logger.info(f"Swarm suspended for HITL (Strategist): {exc.session_id}")
            
            # Persist state if not already saved (e.g. if triggered during planning)
            # This ensures resume_mission can find it.
            try:
                from agentscope_blaiq.contracts.hitl import SwarmSuspendedState
                store = RedisStateStore()
                # Check if it's already there
                existing = await store.get_swarm_suspension(exc.session_id)
                if not existing:
                    suspension = SwarmSuspendedState(
                        session_id=exc.session_id,
                        goal=user_goal,
                        artifact_family="report", # Default
                        completed_results={},
                        resume_from_role="research", # Start from scratch with new info
                        hitl_question=exc.question,
                        hitl_options=exc.options,
                        hitl_why=exc.why,
                    )
                    await store.save_swarm_suspension(suspension)
                    logger.info(f"Saved planning-phase suspension state for {exc.session_id}")
            except Exception as e:
                logger.warning(f"Failed to save backup suspension state: {e}")

            # Emit a structured HITL request message for the frontend
            hitl_payload = json.dumps({
                "metadata": {
                    "kind": "hitl_request",
                    "session_id": exc.session_id,
                    "requires_input": True,
                    "options": exc.options,
                    "why_it_matters": exc.why
                },
                "content": exc.question
            })
            yield Msg("Oracle", hitl_payload, "assistant"), True

        except Exception as e:
            logger.error(f"SwarmEngine execution failed: {e}")
            yield Msg(
                "StrategistMaster",
                f"MISSION FAILED: {str(e)}",
                "assistant"
            ), True


# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

async def _async_yield_from_publisher(publisher, role: str, text: str, is_stream: bool = False):
    """OBSOLETE: Replaced by Queue pattern in build_mission_plan."""
    pass


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


async def _extract_evidence_from_memory(agent: ReActAgent) -> str:
    """Extract research evidence from agent memory for quality evaluation."""
    if not hasattr(agent, "memory") or not agent.memory:
        return ""

    # Get recent messages from memory
    try:
        memory_content = agent.memory.get_memory()
        # AgentScope InMemoryMemory.get_memory() is async — await if needed
        if asyncio.iscoroutine(memory_content):
            memory_content = await memory_content
        evidence_parts = []
        for msg in (memory_content or []):
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
