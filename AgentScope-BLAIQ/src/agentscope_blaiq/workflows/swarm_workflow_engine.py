# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from agentscope_blaiq.contracts.events import StreamEvent
from agentscope_blaiq.contracts.workflow import SubmitWorkflowRequest, WorkflowStatus
from agentscope_blaiq.workflows.swarm_engine import SwarmEngine
from agentscope_blaiq.persistence.redis_state import RedisStateStore
from agentscope_blaiq.persistence.repositories import WorkflowRepository

logger = logging.getLogger("agentscope_blaiq.swarm_workflow_engine")

class SwarmWorkflowEngine:
    def __init__(self, registry: Any = None) -> None:
        self.registry = registry
        self.swarm = SwarmEngine()
        self._state_store: RedisStateStore | None = None
        # Active session guard: prevents duplicate parallel executions for the same session
        self._active_sessions: set[str] = set()

    @property
    def state_store(self) -> RedisStateStore:
        if self._state_store is None:
            self._state_store = RedisStateStore()
        return self._state_store

    @state_store.setter
    def state_store(self, value: RedisStateStore):
        self._state_store = value

    async def cancel(self, thread_id: str):
        """Cancel the workflow execution."""
        # SwarmEngine doesn't have a cancel method yet, so we just log it
        logger.info(f"Cancellation requested for swarm workflow {thread_id}")

    def _validate_answer_set(self, request: Any, state: Any) -> list[str]:
        """Validate HITL answers."""
        return []

    async def run(
        self,
        session: AsyncSession,
        request: SubmitWorkflowRequest
    ) -> AsyncIterator[StreamEvent]:
        """
        Main entry point for workflow execution via the Swarm Engine.
        """
        # Deduplicate concurrent requests for the same session (e.g. Nginx retry on timeout)
        dedup_key = request.session_id or request.thread_id
        if dedup_key in self._active_sessions:
            logger.warning(f"Duplicate run request for session {dedup_key} — dropping")
            return
        self._active_sessions.add(dedup_key)

        run_id = str(uuid4())
        sequence = 0
        repo = WorkflowRepository(session)

        # 1. Initialize workflow record in DB (legacy compatibility)
        await repo.create_workflow(request, run_id=run_id)

        # 2. Setup Event Factory helper
        def build_event(
            event_type: str, 
            agent_name: str = "system", 
            phase: str = "system", 
            data: dict = None,
            status: str = "running"
        ) -> StreamEvent:
            nonlocal sequence
            sequence += 1
            return StreamEvent(
                type=event_type,
                sequence=sequence,
                run_id=run_id,
                thread_id=request.thread_id,
                session_id=request.session_id,
                agent_name=agent_name,
                phase=phase,
                status=status,
                data=data or {},
            )

        # 3. Queue for bridging swarm events to the async iterator
        queue = asyncio.Queue()
        done_marker = object()

        async def publish_callback(role: str, text: str, is_stream: bool = False):
            # 1. Resolve phase mapping for progress tracking
            phase_map = {
                "research": "research",
                "text_buddy": "synthesis",
                "content_director": "content_director",
                "vangogh": "rendering",
                "governance": "governance",
                "oracle": "clarification"
            }
            phase = phase_map.get(role.lower(), "system")

            # 2. Handle real-time token streaming
            if is_stream:
                # OPTIMIZATION: Combine agent_thought and token_chunk for cleaner frontend state
                # If the text looks like an internal reflection vs actual output
                reflection_keywords = ["thinking", "thought", "analysis", "reflection", "executing"]
                is_reflection = any(kw in text.lower() for kw in reflection_keywords)
                
                # BLAIQ CORE FIX: Use 'workflow_event' as the unified streaming type for AgentActivityStack cards
                event_type = "workflow_event"
                
                event = build_event(
                    event_type,
                    agent_name=role,
                    phase=phase,
                    data={
                        "content": text, 
                        "role": role, 
                        "is_reflection": is_reflection,
                        "streaming": True,
                        "message": text # Ensure compatibility with getMsgText()
                    }
                )
                queue.put_nowait(event)
                return

            # 3. Detect and unwrap structural JSON events from SwarmEngine
            if text.startswith("{") and text.endswith("}"):
                try:
                    payload = json.loads(text)
                    if "type" in payload:
                        # Map special types for frontend compatibility
                        event_type = payload["type"]
                        if event_type == "workflow_blocked":
                            event_type = "hitl_required"
                        
                        event = build_event(
                            event_type,
                            agent_name=payload.get("agent_name", role),
                            phase=payload.get("phase", phase),
                            data=payload.get("data", {})
                        )
                        queue.put_nowait(event)
                        return
                except Exception:
                    pass

            # 4. Fallback: Wrap plain text as a workflow event (activity card)
            event = build_event(
                "workflow_event",
                agent_name=role,
                phase=phase,
                data={"message": text}
            )
            queue.put_nowait(event)

        # 4. Background task for Swarm execution
        async def execute_swarm():
            try:
                logger.info(f"Starting swarm execution for thread={request.thread_id}")
                # Emit initial events
                queue.put_nowait(build_event("workflow_started", agent_name="system", phase="system"))
                queue.put_nowait(build_event(
                    "planning_started", 
                    agent_name="BLAIQ-CORE", 
                    phase="planning",
                    data={"message": "BLAIQ-CORE is architecting the swarm mission..."}
                ))

                logger.info(f"Invoking swarm.run with goal: {request.user_query[:50]}...")
                # Run the swarm
                results = await self.swarm.run(
                    goal=request.user_query,
                    session_id=request.session_id,
                    artifact_family=request.artifact_family_hint.value if request.artifact_family_hint else "report",
                    publish=publish_callback,
                    with_oracle=True,
                )

                logger.info("Swarm execution successful, processing results")
                # Detect result mode:
                # - direct: strategist answered without delegating (single-turn chat)
                # - delegated: strategist service orchestrated full workflow internally
                # - sequential: fallback hardcoded sequence (research→text_buddy→governance)
                is_direct = "Strategist" in results and len(results) == 1
                is_delegated = results.get("workflow") == "delegated_to_strategist"

                if is_direct:
                    final_answer = results.get("Strategist", "")
                    artifact_title = "Direct Response"
                    artifact_phase = "chat"
                    artifact_html = ""
                    artifact_md = ""
                elif is_delegated:
                    # Full workflow already streamed via on_strategist_chunk events.
                    # Frontend collected artifacts from streaming. Signal completion only.
                    final_answer = "The mission has been completed by the BLAIQ-CORE swarm."
                    artifact_title = "Swarm Intelligence Report"
                    artifact_phase = "artifact"
                    artifact_html = ""
                    artifact_md = ""
                else:
                    final_answer = "The mission has been successfully completed and the final artifact has been governed."
                    artifact_title = "Swarm Intelligence Report"
                    artifact_phase = "text_buddy" if results.get("text_buddy") else "artifact"
                    artifact_html = results.get("vangogh", "")
                    artifact_md = results.get("text_buddy", "")

                # Emit completion
                queue.put_nowait(build_event(
                    "workflow_complete",
                    status="complete",
                    data={
                        "final_answer": final_answer,
                        "governance_report": results.get("governance") if not is_direct else None,
                        "final_artifact": {
                            "artifact_id": f"artifact-{run_id}",
                            "title": artifact_title,
                            "sections": [],
                            "html": artifact_html,
                            "markdown": artifact_md,
                            "phase": artifact_phase,
                        }
                    }
                ))
                
                # Update DB
                await repo.update_status(request.thread_id, WorkflowStatus.complete)
                logger.info("Workflow status updated to complete")

            except Exception as e:
                logger.error(f"Swarm execution failed: {e}", exc_info=True)
                queue.put_nowait(build_event(
                    "workflow_error",
                    status="error",
                    data={"error_message": str(e)}
                ))
                await repo.update_status(request.thread_id, WorkflowStatus.error, error_message=str(e))
            finally:
                self._active_sessions.discard(dedup_key)
                queue.put_nowait(done_marker)

        # Start background task
        loop = asyncio.get_running_loop()
        loop.create_task(execute_swarm())

        # 5. Yield events from queue with a fast-poll/push mechanism
        logger.info("Entering event yield loop")
        while True:
            try:
                event = await queue.get()
                if event is done_marker:
                    logger.info("Received done marker, ending event stream")
                    break
                logger.info(f"Yielding SSE event: {event.type}")
                yield event
            except asyncio.CancelledError:
                logger.info("Event stream cancelled by client")
                break
            except Exception as e:
                logger.error(f"Error yielding swarm event: {e}")
                break

    async def resume(self, session: AsyncSession, request: Any):
        # TODO: Implement resume bridge for SwarmEngine
        # For now, just a placeholder that raises not implemented
        raise NotImplementedError("Swarm resume bridge not yet implemented in SwarmWorkflowEngine")
