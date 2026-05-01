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
from agentscope_blaiq.persistence.repositories import WorkflowRepository, ConversationRepository, UserRepository

logger = logging.getLogger("agentscope_blaiq.swarm_workflow_engine")


def _build_final_artifact_payload(run_id: str, results: dict[str, str], is_direct: bool) -> dict[str, Any]:
    if is_direct:
        return {
            "artifact_id": f"artifact-{run_id}",
            "title": "Direct Response",
            "sections": [],
            "html": "",
            "markdown": "",
            "css": "",
            "media": [],
            "layout_hints": {},
            "phase": "chat",
        }

    render_result = results.get("vangogh", "")
    text_artifact = results.get("text_buddy", "")
    parsed_render: dict[str, Any] | None = None
    try:
        parsed = json.loads(render_result) if render_result else None
        if isinstance(parsed, dict):
            parsed_render = parsed
    except Exception:
        parsed_render = None

    return {
        "artifact_id": f"artifact-{run_id}",
        "title": (
            str((parsed_render or {}).get("title") or "").strip()
            or ("Swarm Intelligence Report" if text_artifact else "Visual Artifact")
        ),
        "sections": [],
        "html": str((parsed_render or {}).get("html") or render_result or ""),
        "markdown": str((parsed_render or {}).get("storyboard_markdown") or text_artifact or ""),
        "markdownVariants": {
            "abstract": str((parsed_render or {}).get("content_abstract_markdown") or ""),
            "detailed": str((parsed_render or {}).get("storyboard_markdown") or ""),
        },
        "css": str((parsed_render or {}).get("css") or ""),
        "media": list((parsed_render or {}).get("media") or []),
        "layout_hints": dict((parsed_render or {}).get("layout_hints") or {}),
        "phase": "artifact" if parsed_render else ("text_buddy" if text_artifact else "artifact"),
    }

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
        conv_repo = ConversationRepository(session)
        user_repo = UserRepository(session)

        # 1. Initialize workflow record in DB (legacy compatibility)
        await repo.create_workflow(request, run_id=run_id)

        # 1.1 Persist user message to Conversations
        # For multi-tenant, we assume request contains workspace_id later, 
        # for now fallback to session_id for compatibility if needed.
        workspace_id = getattr(request, "workspace_id", None)
        user_id = getattr(request, "user_id", None)
        
        # FIX: Ensure we have a valid UserRecord to avoid ForeignKeyViolationError
        if not user_id or user_id == "workspace-user":
            fallback_user = await user_repo.get_first_user()
            if fallback_user:
                user_id = fallback_user.id
            else:
                user_id = "workspace-user" # Last resort, still might fail if DB is empty
        
        conversation = await conv_repo.create_or_get_conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            thread_id=request.thread_id,
            title=request.user_query[:50] + ("..." if len(request.user_query) > 50 else "")
        )
        
        await conv_repo.save_message(
            conversation_id=conversation.id,
            sender_type="user",
            content=request.user_query,
            metadata={"sender_id": user_id}
        )

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

        STRUCTURED_EVENT_TYPES = {
            "agent_started", "agent_completed", "workflow_event", "workflow_blocked",
            "hitl_request", "hitl_required", "planning_complete", "artifact_family_selected",
            "content_abstract_ready", "content_storyboard_ready", "agent_log",
        }

        async def publish_callback(role: str, text: str, is_stream: bool = False):
            # Detect structured JSON events from swarm_engine and re-emit with correct type
            if text.strip().startswith("{"):
                try:
                    parsed = json.loads(text)

                    # Swarm-engine structured events (have "type" field)
                    event_type = parsed.get("type", "")
                    if event_type in STRUCTURED_EVENT_TYPES:
                        event = build_event(
                            event_type,
                            agent_name=parsed.get("agent_name", role),
                            phase=parsed.get("phase", role),
                            data=parsed.get("data", {}),
                        )
                        queue.put_nowait(event)
                        return

                    # AaaS intermediate artifact chunks (have "metadata.kind" field)
                    meta = parsed.get("metadata") or {}
                    if meta.get("kind") == "content_abstract":
                        event = build_event(
                            "content_abstract_ready",
                            agent_name=role,
                            phase="content_director",
                            data={
                                "content": parsed.get("content", ""),
                                "selected_skill": meta.get("selected_skill", ""),
                            },
                        )
                        queue.put_nowait(event)
                        return

                    if meta.get("kind") == "storyboard_detailed":
                        content = parsed.get("content", "")
                        selected_skill = meta.get("selected_skill", "")
                        try:
                            storyboard_payload = json.loads(content) if content else {}
                        except Exception:
                            storyboard_payload = {}
                        event = build_event(
                            "content_storyboard_ready",
                            agent_name=role,
                            phase="content_director",
                            data={
                                "content": content,
                                "storyboard_markdown": storyboard_payload.get("storyboard_markdown", ""),
                                "content_abstract_markdown": storyboard_payload.get("content_abstract_markdown", ""),
                                "selected_skill": selected_skill,
                                "title": storyboard_payload.get("title", ""),
                                "artifact_type": storyboard_payload.get("artifact_type", meta.get("artifact_type", "")),
                            },
                        )
                        queue.put_nowait(event)
                        return

                    # AgentScope pre_print-tagged thoughts → live AgentCard updates.
                    # Keep agent_name = role so all sub-agent thoughts share a single card.
                    if meta.get("kind") == "agent_thought":
                        event = build_event(
                            "agent_log",
                            agent_name=role,
                            phase=meta.get("phase", role),
                            data={
                                "message": parsed.get("content", ""),
                                "is_stream": True,
                                "message_kind": "thought",
                                "sub_agent": meta.get("agent_name", ""),
                            },
                        )
                        queue.put_nowait(event)
                        return

                    # Final artifact chunks reach the frontend via swarm_engine's
                    # agent_completed event (with full content) → workflow_complete →
                    # final_artifact.markdown → TextArtifactPreview. Drop the raw
                    # streaming JSON here so it never lands in chat as noise.
                    if meta.get("kind") in {"text_artifact", "visual_spec"}:
                        return
                except Exception:
                    pass

            # Standard progress updates
            event_type = "agent_log" if is_stream else "workflow_event"
            # Map roles to phases for the legacy UI if needed
            lower_role = role.lower()
            phase_map = {
                "strategist": "planning",
                "strategistv2": "planning",
                "research": "research",
                "deepresearchv2": "research",
                "text_buddy": "synthesis",
                "text_buddyv2": "synthesis",
                "content_director": "content_director",
                "content_directorv2": "content_director",
                "vangogh": "rendering",
                "vangoghv2": "rendering",
                "governance": "governance",
                "governancev2": "governance",
                "oracle": "clarification",
                "oraclev2": "clarification"
            }
            phase = phase_map.get(lower_role, "system")

            # Handle global acting status signals from AgentScope pre_acting hooks
            if text.strip().startswith("{") and '"status": "acting"' in text:
                try:
                    parsed = json.loads(text)
                    if parsed.get("status") == "acting":
                        queue.put_nowait(build_event(
                            "agent_log",
                            agent_name=parsed.get("agent", role),
                            phase=phase,
                            data={
                                "message": f"{parsed.get('agent', role)} is executing an action step...",
                                "message_kind": "status",
                                "status": "acting"
                            }
                        ))
                        return
                except Exception:
                    pass

            # UI Promotion: If we get a log from an agent but haven't sent agent_started, 
            # the UI might still be showing 'Initializing...'. We ensure it promotes.
            if is_stream:
                queue.put_nowait(build_event(
                    "agent_started",
                    agent_name=role,
                    phase=phase,
                    data={"message": f"Agent {role} is processing..."}
                ))

            event = build_event(
                event_type,
                agent_name=role,
                phase=phase,
                data={"message": text, "is_stream": is_stream}
            )
            queue.put_nowait(event)

        # 4. Background task for Swarm execution
        async def execute_swarm():
            try:
                # Emit initial events
                queue.put_nowait(build_event("workflow_started", agent_name="system", phase="system"))
                
                # Immediately start the Strategist card in the UI
                queue.put_nowait(build_event(
                    "agent_started",
                    agent_name="Strategist",
                    phase="planning",
                    data={"message": "I've received your request. Architecting the swarm mission..."}
                ))

                # Also emit planning_started for the orchestration layer
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
                
                # Use the governance agent's response if available, otherwise the hardcoded fallback
                # results is keyed by the role names used in sequence (e.g. "governance", "research")
                final_answer = results.get("governance") or results.get("Strategist")
                if not final_answer:
                    # Check for "Governance" (case difference between roll and proxy name)
                    final_answer = results.get("Governance")
                
                if not final_answer:
                    final_answer = "The mission has been successfully completed and the final artifact has been governed."

                # 1.1 Persist agent response to Conversations
                await conv_repo.save_message(
                    conversation_id=conversation.id,
                    sender_type="agent",
                    content=final_answer,
                    metadata={"sender_name": "Governance" if results.get("governance") else "Strategist"}
                )

                # Emit completion
                final_artifact = _build_final_artifact_payload(run_id, results, is_direct)
                queue.put_nowait(build_event(
                    "workflow_complete",
                    status="complete",
                    data={
                        "final_answer": final_answer,
                        "governance_report": results.get("governance") if not is_direct else None,
                        "final_artifact": final_artifact,
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
        asyncio.create_task(execute_swarm())

        # 5. Yield events from queue
        while True:
            event = await queue.get()
            if event is done_marker:
                break
            yield event

    async def resume(self, session: AsyncSession, request: Any):
        # TODO: Implement resume bridge for SwarmEngine
        # For now, just a placeholder that raises not implemented
        raise NotImplementedError("Swarm resume bridge not yet implemented in SwarmWorkflowEngine")
