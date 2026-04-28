# -*- coding: utf-8 -*-
import asyncio
import logging
import json
from typing import Any, Dict, List, Optional, AsyncGenerator
from datetime import datetime, timezone
from uuid import uuid4

from agentscope_blaiq.contracts.workflow import (
    WorkflowPlan, WorkflowStatus, RequirementStage, 
    WorkflowExecutionResult, WorkflowNode, TaskRole
)
from agentscope_blaiq.contracts.events import StreamEvent
from agentscope_blaiq.persistence.redis_state import RedisStateStore, WorkflowRedisState
from agentscope_blaiq.tools.enterprise_fleet import BlaiqEnterpriseFleet

logger = logging.getLogger("blaiq.engine_v2")

class WorkflowEngineV2:
    """
    The BLAIQ Orchestration Engine (V2).
    A streamlined, state-aware runner for strategic Task Graphs.
    Focuses on Strategic Gates and Service-Native execution.
    """
    def __init__(self, state_store: RedisStateStore):
        self.state_store = state_store
        self.fleet = BlaiqEnterpriseFleet()
        self.event_factory = None # Injected at runtime
        self._sequence_counter = 0

    async def execute(
        self, 
        plan: WorkflowPlan, 
        session_id: str,
        publish: Any # SSE event publisher
    ) -> WorkflowExecutionResult:
        """
        Main execution loop for a workflow plan.
        """
        logger.info(f"EngineV2 starting execution for session {session_id}")
        
        # 1. Initialize State
        state = await self.state_store.get_workflow_state(session_id)
        if not state:
            state = WorkflowRedisState(
                thread_id=session_id,
                session_id=session_id,
                tenant_id="default",
                workflow_mode=plan.workflow_mode,
                user_query=plan.summary,
                status=WorkflowStatus.running
            )
            await self.state_store.set_workflow_state(state)
        
        # results mapping for Engine logic (not in Redis model yet, so we store in a local tracker or results dict)
        # Note: In a real production system, this would be serialized to state.
        node_results = {}
        
        nodes_to_run = self._get_pending_nodes(plan, [state.last_completed_node] if state.last_completed_node else [])
        
        for node in nodes_to_run:
            # Check Strategic Gates BEFORE running the node
            if await self._should_block_at_gate(node, plan, session_id, publish):
                logger.info(f"EngineV2 blocked at gate for node {node.node_id}")
                return WorkflowExecutionResult(status=WorkflowStatus.blocked)

            # Execute the node logic via Fleet Tools
            result = await self._run_node(node, plan, session_id, publish, node_results)
            
            # Record progress
            state.last_completed_node = node.node_id
            node_results[node.node_id] = result
            await self.state_store.set_workflow_state(state)

        return WorkflowExecutionResult(status=WorkflowStatus.complete, results=node_results)

    async def _should_block_at_gate(
        self, 
        node: WorkflowNode, 
        plan: WorkflowPlan, 
        session_id: str,
        publish: Any
    ) -> bool:
        """
        Enforces Strategic Intervention Gates.
        """
        # Gate 1: Priority Gate (Post-Research)
        if node.task_role == TaskRole.content_director and self._has_pending_requirement(plan, RequirementStage.before_storyboard):
            await self._trigger_oracle(session_id, "Priority Gate: Reviewing evidence before storyboarding.", publish)
            return True

        # Gate 2: Design Approval Gate (Post-Director)
        if node.task_role == TaskRole.vangogh and self._has_pending_requirement(plan, RequirementStage.before_render):
            await self._trigger_oracle(session_id, "Design Approval Gate: Reviewing storyboard before rendering visuals.", publish)
            return True

        # Gate 3: Emphasis Gate (Pre-Synthesis)
        if node.task_role == TaskRole.text_buddy and self._has_pending_requirement(plan, RequirementStage.before_synthesis):
            await self._trigger_oracle(session_id, "Emphasis Gate: Any points to stress in the final text?", publish)
            return True

        return False

    async def _run_node(
        self,
        node: WorkflowNode,
        plan: WorkflowPlan,
        session_id: str,
        publish: Any,
        node_results: Dict[str, Any] = None,
    ) -> Any:
        """
        Dispatches node execution to the appropriate Fleet Agent with full context.
        """
        # 1. Prepare Context from Prior Nodes
        prior_context = self._build_node_context(node, node_results or {})
        
        await publish(self._make_event(
            "agent_started", 
            node.node_id, 
            f"Orchestrating {node.task_role} for {plan.artifact_family.value}...",
            session_id=session_id,
            detail={"role": node.task_role, "session_id": session_id}
        ))
        
        # 2. Execution Routing
        try:
            if node.task_role == TaskRole.research:
                result = await self.fleet.research_evidence(plan.summary, session_id)
            
            elif node.task_role == TaskRole.content_director:
                result = await self.fleet.orchestrate_visuals(
                    text_artifact=prior_context.get("text_artifact", plan.summary),
                    evidence_brief=prior_context.get("evidence", ""),
                    session_id=session_id
                )
            
            elif node.task_role == TaskRole.text_buddy:
                result = await self.fleet.synthesize_text(
                    goal=plan.summary,
                    evidence_brief=prior_context.get("evidence", ""),
                    artifact_type=node.inputs.get("artifact_type", plan.artifact_family.value),
                    session_id=session_id
                )
            
            elif node.task_role == TaskRole.vangogh:
                result = await self.fleet.render_visuals(
                    visual_spec=prior_context.get("storyboard", ""),
                    session_id=session_id
                )
            
            elif node.task_role in [TaskRole.oracle, TaskRole.hitl]:
                # Human-in-the-loop / Oracle gate
                question = node.purpose or node.inputs.get("question", "The AI fleet needs your input to proceed.")
                result = await self.fleet.ask_human(question, session_id)
                
            elif node.task_role == TaskRole.governance:
                result = await self.fleet.govern_artifact(
                    artifact_content=prior_context.get("text_artifact", plan.summary),
                    session_id=session_id
                )
            else:
                raise ValueError(f"Unknown TaskRole: {node.task_role}")

            await publish(self._make_event(
                "agent_completed", 
                node.node_id, 
                f"{node.task_role} successfully completed phase.",
                session_id=session_id,
                detail={"status": "success"}
            ))
            return result

        except Exception as e:
            logger.error(f"Execution failed at node {node.node_id}: {e}")
            await publish(self._make_event(
                "agent_failed", 
                node.node_id, 
                f"Execution error in {node.task_role}: {str(e)}",
                session_id=session_id,
                detail={"error": str(e)}
            ))
            raise

    def _build_node_context(self, node: WorkflowNode, results: Dict[str, Any]) -> Dict[str, Any]:
        """Collects outputs from completed upstream nodes."""
        context: Dict[str, Any] = {}
        for dep_id in node.depends_on:
            if dep_id in results:
                context[dep_id] = results[dep_id]

        def _extract_text(v: Any) -> str:
            if v is None:
                return ""
            if hasattr(v, "content") and v.content:
                part = v.content[0]
                return str(getattr(part, "text", part.get("text", str(part)) if isinstance(part, dict) else str(part)))
            if isinstance(v, dict) and "content" in v and v["content"]:
                part = v["content"][0]
                return str(part.get("text", str(part)))
            return str(v)

        context["evidence"] = next((_extract_text(v) for k, v in results.items() if "research" in k.lower()), "")
        context["text_artifact"] = next((_extract_text(v) for k, v in results.items() if "text_buddy" in k.lower()), "")
        context["storyboard"] = next((_extract_text(v) for k, v in results.items() if "content_director" in k.lower()), "")
        return context

    async def _trigger_oracle(self, session_id: str, message: str, publish: Any):
        """Triggers the Oracle HITL intervention."""
        await publish(self._make_event("hitl_required", "oracle", message, requires_input=True))

    def _get_pending_nodes(self, plan: WorkflowPlan, completed: List[str]) -> List[WorkflowNode]:
        """Simple topological sort / filter."""
        # This is a placeholder for actual DAG sorting
        return [n for n in plan.task_graph.nodes if n.node_id not in completed]

    def _has_pending_requirement(self, plan: WorkflowPlan, stage: RequirementStage) -> bool:
        """Checks if there are any unfilled requirements for a given stage."""
        for item in plan.requirements_checklist.items:
            if item.blocking_stage == stage and item.status == "pending":
                return True
        return False

    def _make_event(self, event_type: str, node_id: str, message: str, session_id: str = "default", **kwargs) -> StreamEvent:
        """Utility for creating SSE events."""
        self._sequence_counter += 1
        return StreamEvent(
            type=event_type,
            sequence=self._sequence_counter,
            thread_id=session_id,
            session_id=session_id,
            data={
                "node_id": node_id,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **kwargs
            }
        )
