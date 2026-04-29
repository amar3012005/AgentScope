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
from agentscope_blaiq.persistence.repositories import WorkflowRepository

logger = logging.getLogger("agentscope_blaiq.swarm_workflow_engine")

class SwarmWorkflowEngine:
    """
    Bridge between BLAIQ's Gateway (main.py) and the AgentScope Swarm Architecture.
    
    This class implements the same 'run' and 'resume' interface as the legacy WorkflowEngine
    but delegates the actual execution to SwarmEngine.
    """

    def __init__(self, registry: Any = None) -> None:
        self.registry = registry
        self.swarm = SwarmEngine()
        # Stub for state store compatibility
        from agentscope_blaiq.persistence.redis_state import RedisStateStore
        from agentscope_blaiq.runtime.config import settings
        self.state_store = RedisStateStore()

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
            # Check if text is structured JSON (Swarm Events)
            if text.startswith("{"):
                try:
                    raw_data = json.loads(text)
                    event_type = raw_data.get("type")
                    
                    if event_type in ["agent_started", "agent_completed", "workflow_blocked", "agent_thought"]:
                        # Map internal swarm phases to frontend phases
                        phase_map = {
                            "research": "research",
                            "text_buddy": "synthesis",
                            "content_director": "content_director",
                            "vangogh": "rendering",
                            "governance": "governance",
                            "oracle": "clarification"
                        }
                        role_key = role.lower()
                        phase = phase_map.get(role_key, raw_data.get("phase", "system"))
                        
                        # Data payload mapping
                        event_data = raw_data.get("data", {})
                        
                        # Handle specific event logic for the frontend
                        mapped_type = event_type
                        if event_type == "agent_started":
                            mapped_type = "agent_log"
                            event_data["message_kind"] = "status"
                        elif event_type == "agent_thought":
                            mapped_type = "agent_log"
                            event_data["message_kind"] = "thought"
                        elif event_type == "workflow_blocked":
                            mapped_type = "hitl_required" # Frontend expectation

                        event = build_event(
                            mapped_type,
                            agent_name=role,
                            phase=phase,
                            data=event_data
                        )
                        queue.put_nowait(event)
                        return
                    
                    # Legacy AgentActivity check
                    meta = raw_data.get("metadata", {})
                    if meta.get("kind") == "agent_activity":
                        # ... existing meta handling ...
                        phase = meta.get("phase", "system")
                        event = build_event(
                            "agent_log",
                            agent_name=role,
                            phase=phase,
                            data={
                                "message": f"Agent {role} is in phase: {phase}",
                                "message_kind": "status",
                                "visibility": "user",
                                "detail": meta
                            }
                        )
                        queue.put_nowait(event)
                        return
                except Exception:
                    pass

            # Standard progress updates or tokens
            if is_stream:
                # Direct token pass-through for high-speed UI
                event = build_event(
                    "token_chunk",
                    agent_name=role,
                    phase=role.lower(),
                    data={"text": text, "role": role}
                )
                queue.put_nowait(event)
                return

            # Fallback for plain text messages
            phase_map = {
                "research": "research",
                "text_buddy": "synthesis",
                "content_director": "content_director",
                "vangogh": "rendering",
                "governance": "governance",
                "oracle": "clarification"
            }
            phase = phase_map.get(role.lower(), "system")

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
                # Emit initial events
                queue.put_nowait(build_event("workflow_started", agent_name="system", phase="system"))
                queue.put_nowait(build_event(
                    "planning_started", 
                    agent_name="BLAIQ-CORE", 
                    phase="planning",
                    data={"message": "BLAIQ-CORE is architecting the swarm mission..."}
                ))

                # Run the swarm
                results = await self.swarm.run(
                    goal=request.user_query,
                    session_id=request.session_id,
                    artifact_family=request.artifact_family_hint.value if request.artifact_family_hint else "report",
                    publish=publish_callback,
                    with_oracle=True,
                )

                # Check if it was a direct response (fast track)
                is_direct = "Strategist" in results and len(results) == 1
                final_answer = results.get("Strategist") if is_direct else "The mission has been successfully completed and the final artifact has been governed."

                # Emit completion
                queue.put_nowait(build_event(
                    "workflow_complete",
                    status="complete",
                    data={
                        "final_answer": final_answer,
                        "governance_report": results.get("governance") if not is_direct else None,
                        "final_artifact": {
                            "artifact_id": f"artifact-{run_id}",
                            "title": "Direct Response" if is_direct else "Swarm Intelligence Report",
                            "sections": [],
                            "html": results.get("vangogh", "") if not is_direct else "",
                            "markdown": results.get("text_buddy", "") if not is_direct else "",
                            "phase": "chat" if is_direct else ("text_buddy" if results.get("text_buddy") else "artifact")
                        }
                    }
                ))
                
                # Update DB
                await repo.update_status(request.thread_id, WorkflowStatus.complete)

            except Exception as e:
                logger.error(f"Swarm execution failed: {e}")
                queue.put_nowait(build_event(
                    "workflow_error",
                    status="error",
                    data={"error_message": str(e)}
                ))
                await repo.update_status(request.thread_id, WorkflowStatus.error, error_message=str(e))
            finally:
                queue.put_nowait(done_marker)

        # Start background task
        loop = asyncio.get_running_loop()
        loop.create_task(execute_swarm())

        # 5. Yield events from queue with a fast-poll/push mechanism
        while True:
            # wait_for 0.05 to ensure we don't block too long on an empty queue
            # and allow the event loop to breathe for the background task
            try:
                event = await queue.get()
                if event is done_marker:
                    break
                yield event
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error yielding swarm event: {e}")
                break

    async def resume(self, session: AsyncSession, request: Any):
        # TODO: Implement resume bridge for SwarmEngine
        # For now, just a placeholder that raises not implemented
        raise NotImplementedError("Swarm resume bridge not yet implemented in SwarmWorkflowEngine")
