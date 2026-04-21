"""
BLAIQ Core Temporal Worker
Wraps LangGraph orchestration in durable Temporal workflows.
Handles: workflow execution, HITL signals, status queries, and crash recovery.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from datetime import timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

from utils.logging_utils import configure_service_logging, log_flow

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = "blaiq-core-queue"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TEMPORAL_READY_PATH = Path(os.getenv("TEMPORAL_READY_PATH", "/tmp/temporal_ready"))
TEMPORAL_CONNECT_RETRIES = int(os.getenv("TEMPORAL_CONNECT_RETRIES", "60"))
TEMPORAL_CONNECT_RETRY_DELAY_SECONDS = float(
    os.getenv("TEMPORAL_CONNECT_RETRY_DELAY_SECONDS", "2")
)

logger = logging.getLogger("blaiq-temporal-worker")

_CONTENT_GENERATION_KEYWORDS = (
    "pitch deck", "pitchdeck", "poster", "flyer", "brochure", "one-pager", "one pager",
    "landing page", "webpage", "presentation", "slide deck", "slides", "visual",
    "generate poster", "create poster", "generate pitch", "create pitch", "banner",
    "infographic", "mockup", "design layout",
)


def _is_content_generation_query(query: str) -> bool:
    q = (query or "").strip().lower()
    return bool(q) and any(keyword in q for keyword in _CONTENT_GENERATION_KEYWORDS)


# --- Data classes for workflow I/O ---
@dataclass
class WorkflowInput:
    thread_id: str
    session_id: str
    tenant_id: str
    collection_name: str
    user_query: str
    room_number: str = ""
    chat_history: Optional[List[Dict[str, str]]] = None
    workflow_mode: str = "standard"
    use_template_engine: bool = False
    strategy_execution_plan: Optional[List[str]] = None
    strategy_selected_agents: Optional[List[str]] = None
    strategy_primary_agent: Optional[str] = None
    strategy_route_mode: Optional[str] = None
    strategy_reasoning: Optional[str] = None
    content_requires_hitl: bool = False


@dataclass
class WorkflowOutput:
    thread_id: str
    status: str  # complete | error | blocked
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    hitl_questions: Optional[List[str]] = None


# --- Activities ---
@activity.defn
async def run_langgraph_to_completion(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the LangGraph workflow. Returns final state dict."""
    from orchestrator.graph import build_graph

    log_flow(
        logger,
        "activity_start",
        activity="run_langgraph_to_completion",
        thread_id=input_data["thread_id"],
        session_id=input_data["session_id"],
        tenant_id=input_data["tenant_id"],
        collection_name=input_data["collection_name"],
    )
    graph = await build_graph(REDIS_URL)
    config = {"configurable": {"thread_id": input_data["thread_id"]}}
    initial_state = {
        "thread_id": input_data["thread_id"],
        "session_id": input_data["session_id"],
        "tenant_id": input_data["tenant_id"],
        "collection_name": input_data["collection_name"],
        "user_query": input_data["user_query"],
        "room_number": input_data.get("room_number", ""),
        "chat_history": input_data.get("chat_history") or [],
        "workflow_mode": input_data.get("workflow_mode", "standard"),
        "use_template_engine": bool(input_data.get("use_template_engine", False)),
        "strategy_execution_plan": input_data.get("strategy_execution_plan") or [],
        "strategy_selected_agents": input_data.get("strategy_selected_agents") or [],
        "strategy_primary_agent": input_data.get("strategy_primary_agent", ""),
        "strategy_route_mode": input_data.get("strategy_route_mode", ""),
        "strategy_reasoning": input_data.get("strategy_reasoning", ""),
        "workflow_plan": None,
        "workflow_complete": False,
        "content_requires_hitl": bool(
            input_data.get("content_requires_hitl", False)
            or _is_content_generation_query(input_data.get("user_query", ""))
            or "content" in [str(step).lower() for step in (input_data.get("strategy_execution_plan") or [])]
            or "vangogh" in str(input_data.get("strategy_primary_agent", "")).lower()
        ),
        "run_id": input_data.get("run_id", ""),
        "execution_plan": [],
        "extracted_entities": [],
        "keywords": [],
        "evidence_manifest": None,
        "content_draft": None,
        "content_director_plan": None,
        "hitl_required": False,
        "hitl_questions": [],
        "hitl_answers": {},
        "hitl_node": "",
        "hitl_mode": "",
        "post_hitl_search_prompt_template": "",
        "post_hitl_refresh_needed": False,
        "governance_report": None,
        "current_node": "",
        "status": "starting",
        "error_message": "",
        "message_id": "",
        "trace_context": {},
        "memory_refs": [],
        "logs": [],
    }

    final_state = None
    async for event in graph.astream(initial_state, config=config, stream_mode="updates"):
        final_state = event
        activity.heartbeat(json.dumps({"node": str(event)}))

    # If graph hit an interrupt (HITL), return the interrupted state
    snapshot = await graph.aget_state(config)
    if snapshot.next:  # graph is paused at interrupt
        state_values = snapshot.values
        log_flow(
            logger,
            "activity_blocked",
            activity="run_langgraph_to_completion",
            thread_id=input_data["thread_id"],
            hitl_questions=len(state_values.get("hitl_questions", [])),
        )
        return {
            "status": "blocked",
            "hitl_required": True,
            "hitl_questions": state_values.get("hitl_questions", []),
            "hitl_node": state_values.get("hitl_node", ""),
            "thread_id": input_data["thread_id"],
        }

    result = snapshot.values if snapshot else {"status": "error", "error_message": "No state produced"}
    log_flow(
        logger,
        "activity_complete",
        activity="run_langgraph_to_completion",
        thread_id=input_data["thread_id"],
        status=result.get("status", "error"),
    )
    return result


@activity.defn
async def resume_langgraph_with_answers(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Resume a paused LangGraph workflow with HITL answers.

    Returns the final state dict, which may still have ``hitl_required=True``
    if the content agent blocks again (second-round HITL).
    """
    from orchestrator.graph import build_graph
    from langgraph.types import Command

    log_flow(
        logger,
        "activity_start",
        activity="resume_langgraph_with_answers",
        thread_id=input_data["thread_id"],
        answers_keys=list((input_data.get("answers") or {}).keys()),
    )
    graph = await build_graph(REDIS_URL)
    config = {"configurable": {"thread_id": input_data["thread_id"]}}
    answers = input_data.get("answers", {})

    final_state = None
    async for event in graph.astream(
        Command(resume=answers),
        config=config,
        stream_mode="updates",
    ):
        final_state = event
        activity.heartbeat(json.dumps({"node": str(event)}))

    # Check if graph hit another interrupt (second-round HITL)
    snapshot = await graph.aget_state(config)
    if snapshot and snapshot.next:
        state_values = snapshot.values
        log_flow(
            logger,
            "activity_blocked",
            activity="resume_langgraph_with_answers",
            thread_id=input_data["thread_id"],
            hitl_questions=len(state_values.get("hitl_questions", [])),
        )
        return {
            "status": "blocked",
            "hitl_required": True,
            "hitl_questions": state_values.get("hitl_questions", []),
            "hitl_node": state_values.get("hitl_node", ""),
            "thread_id": input_data["thread_id"],
        }

    result = snapshot.values if snapshot else {"status": "error", "error_message": "Resume failed"}
    log_flow(
        logger,
        "activity_complete",
        activity="resume_langgraph_with_answers",
        thread_id=input_data["thread_id"],
        status=result.get("status", "error"),
    )
    return result


# --- Workflow ---
@workflow.defn
class BlaiqOrchestrationWorkflow:
    def __init__(self) -> None:
        self._status: str = "queued"
        self._current_node: str = ""
        self._hitl_required: bool = False
        self._hitl_questions: List[str] = []
        self._hitl_answers: Optional[Dict[str, str]] = None
        self._error_message: str = ""
        self._result: Optional[Dict[str, Any]] = None

    @workflow.run
    async def run(self, wf_input: WorkflowInput) -> WorkflowOutput:
        self._status = "dispatching"

        input_dict = {
            "thread_id": wf_input.thread_id,
            "session_id": wf_input.session_id,
            "tenant_id": wf_input.tenant_id,
            "collection_name": wf_input.collection_name,
            "user_query": wf_input.user_query,
            "workflow_mode": wf_input.workflow_mode,
            "use_template_engine": wf_input.use_template_engine,
            "strategy_execution_plan": wf_input.strategy_execution_plan or [],
            "strategy_selected_agents": wf_input.strategy_selected_agents or [],
            "strategy_primary_agent": wf_input.strategy_primary_agent or "",
            "strategy_route_mode": wf_input.strategy_route_mode or "",
            "strategy_reasoning": wf_input.strategy_reasoning or "",
            "content_requires_hitl": wf_input.content_requires_hitl,
            "run_id": workflow.info().run_id,
        }

        # Run LangGraph
        self._status = "running"
        try:
            state = await workflow.execute_activity(
                run_langgraph_to_completion,
                input_dict,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
            )
        except Exception as exc:
            self._status = "error"
            self._error_message = str(exc)
            return WorkflowOutput(
                thread_id=wf_input.thread_id,
                status="error",
                error_message=str(exc),
            )

        self._result = state

        # HITL loop: keep blocking and resuming until workflow completes
        while state.get("hitl_required"):
            self._status = "blocked_on_user"
            self._hitl_required = True
            self._hitl_questions = state.get("hitl_questions", [])
            self._current_node = "hitl"

            # Wait indefinitely for human input (Temporal persists this state)
            await workflow.wait_condition(lambda: self._hitl_answers is not None)

            self._status = "resuming"
            self._hitl_required = False
            self._hitl_questions = []

            resume_input = {
                "thread_id": wf_input.thread_id,
                "answers": self._hitl_answers,
            }
            # Reset answers so the loop can detect a new signal
            self._hitl_answers = None

            try:
                state = await workflow.execute_activity(
                    resume_langgraph_with_answers,
                    resume_input,
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(minutes=2),
                )
            except Exception as exc:
                self._status = "error"
                self._error_message = str(exc)
                return WorkflowOutput(
                    thread_id=wf_input.thread_id,
                    status="error",
                    error_message=str(exc),
                )

            self._result = state
            # Loop will check state.get("hitl_required") again

        # Terminal state
        terminal_status = state.get("status", "complete")
        self._status = terminal_status
        self._current_node = state.get("current_node", "")
        if state.get("error_message"):
            self._error_message = state["error_message"]

        return WorkflowOutput(
            thread_id=wf_input.thread_id,
            status=terminal_status,
            result=state.get("governance_report") or state.get("evidence_manifest") or state.get("content_draft"),
            error_message=state.get("error_message"),
        )

    @workflow.signal
    async def submit_hitl_answers(self, answers: Dict[str, str]) -> None:
        self._hitl_answers = answers

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "status": self._status,
            "current_node": self._current_node,
            "hitl_required": self._hitl_required,
            "hitl_questions": self._hitl_questions,
            "error_message": self._error_message,
            "result": self._result,
        }


# --- Worker entrypoint ---
async def main() -> None:
    last_exc: Exception | None = None
    with contextlib.suppress(Exception):
        TEMPORAL_READY_PATH.unlink()
    log_flow(
        logger,
        "worker_boot",
        queue=TEMPORAL_TASK_QUEUE,
        temporal_host=TEMPORAL_HOST,
        namespace=TEMPORAL_NAMESPACE,
    )
    for attempt in range(1, TEMPORAL_CONNECT_RETRIES + 1):
        try:
            client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
            TEMPORAL_READY_PATH.write_text("ready\n", encoding="utf-8")
            log_flow(logger, "temporal_connected", host=TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE, attempt=attempt)
            break
        except Exception as exc:
            last_exc = exc
            log_flow(
                logger,
                "temporal_connect_retry",
                level="warning",
                attempt=attempt,
                max_attempts=TEMPORAL_CONNECT_RETRIES,
                host=TEMPORAL_HOST,
                error=str(exc),
            )
            if attempt == TEMPORAL_CONNECT_RETRIES:
                raise
            await asyncio.sleep(TEMPORAL_CONNECT_RETRY_DELAY_SECONDS)
    else:
        raise RuntimeError(f"Failed to connect to Temporal: {last_exc}")

    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[BlaiqOrchestrationWorkflow],
        activities=[run_langgraph_to_completion, resume_langgraph_with_answers],
    )
    log_flow(logger, "worker_start", queue=TEMPORAL_TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    configure_service_logging("blaiq-temporal-worker")
    asyncio.run(main())
