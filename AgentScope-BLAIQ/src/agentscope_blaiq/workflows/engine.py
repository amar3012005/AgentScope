from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentscope_blaiq.contracts.artifact import ArtifactSection, TextArtifact, VisualArtifact
from agentscope_blaiq.contracts.events import StreamEvent
from agentscope_blaiq.contracts.evidence import EvidencePack, EvidenceFinding, SourceRecord, Citation
from agentscope_blaiq.agents.backup.clarification import ClarificationPrompt
from agentscope_blaiq.persistence.database import get_session_local
from agentscope_blaiq.contracts.workflow import (
    AgentType,
    AnalysisMode,
    ArtifactSpec,
    ClarificationAnswerSet,
    ClarificationBundle,
    ClarificationQuestion as ContractClarificationQuestion,
    RequirementStage,
    ResumeWorkflowRequest,
    SubmitWorkflowRequest,
    WorkflowMode,
    WorkflowPlan,
    WorkflowStatus,
)
from agentscope_blaiq.persistence.redis_state import BranchRedisState, RedisStateStore, WorkflowRedisState
from agentscope_blaiq.persistence.repositories import (
    AgentRunRepository,
    ArtifactRepository,
    EvidenceRepository,
    WorkflowRepository,
)
from agentscope_blaiq.agents.skills import load_brand_voice
from agentscope_blaiq.contracts.workflow import TEXT_ARTIFACT_FAMILIES as TEXT_FAMILIES
from agentscope_blaiq.contracts.dispatch import validate_dispatch, validate_handoff, validate_tool_call
from agentscope_blaiq.contracts.hooks import (
    HookAction,
    HookContext,
    HookType,
    evaluate_planner_guard,
    evaluate_pre_dispatch,
    evaluate_pre_handoff,
)
from agentscope_blaiq.contracts.enforcement import enforcement_check
from agentscope_blaiq.contracts.recovery import (
    classify_failure, resolve_recovery, RetryBudget, RecoveryEvent, FailureClass,
)
from agentscope_blaiq.contracts.messages import make_agent_input, make_agent_output, RuntimeMsg
from agentscope_blaiq.contracts.harness import canonicalize_workflow_template_id
from agentscope_blaiq.contracts.registry import HarnessRegistry
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.registry import AgentRegistry
from agentscope_blaiq.tools.artifacts import persist_artifact_files
from agentscope_blaiq.workflows.context_chain import format_prior_context

EventPublisher = Callable[[StreamEvent], Awaitable[StreamEvent]]
logger = logging.getLogger("agentscope_blaiq.workflow")


def _parse_hivemind_user_id(rpc_url: str | None) -> str | None:
    if not rpc_url:
        return None
    try:
        path = urlparse(rpc_url).path.strip("/")
        parts = path.split("/")
        if "servers" in parts:
            idx = parts.index("servers")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    except Exception:
        return None
    return None


def _make_agent_log_sink(
    events: "EventFactory",
    publish: EventPublisher,
    agent_name: str,
    phase: str,
    node_id: str | None = None,
):
    """Create a log sink bound to a specific agent and phase.

    The sink emits agent_log events through the SSE stream so the
    frontend can render live messages from the agent while it works.
    """

    async def sink(
        message: str,
        message_kind: str = "status",
        visibility: str = "user",
        detail: dict[str, Any] | None = None,
    ) -> None:
        event_type = "agent_log"
        if message_kind in {"tool_call", "tool_result", "tool_error", "tool_call_started", "tool_call_finished", "tool_call_failed"}:
            event_type = message_kind
        # The frontend user stream should stay focused on clear progress states.
        # Internal reasoning, tooling, and review telemetry remains available in
        # the logs panel via visibility="log".
        _non_user_kinds = {
            "thought",
            "decision",
            "artifact",
            "review",
            "tool_call",
            "tool_result",
            "tool_error",
            "tool_call_started",
            "tool_call_finished",
            "tool_call_failed",
        }
        if visibility == "user" and message_kind in _non_user_kinds:
            visibility = "log"
        data = {
            "message": message,
            "message_kind": message_kind,
            "visibility": visibility,
        }
        if node_id is not None:
            data["node_id"] = node_id
        if detail:
            data["detail"] = detail
        await publish(
            events.build(
                event_type,
                agent_name=agent_name,
                phase=phase,
                data=data,
            )
        )

    return sink


def _collect_missing_requirement_prompts(plan: WorkflowPlan, *, stage: RequirementStage | None = None) -> list[str]:
    prompts: list[str] = []
    for item in plan.requirements_checklist.items:
        if not item.must_have or item.status == "filled":
            continue
        if stage is not None and item.blocking_stage != stage:
            continue
        prompts.append(item.text)
    return prompts




@dataclass
class BranchResult:
    branch_id: str
    evidence: EvidencePack | None = None
    section: ArtifactSection | None = None
    error_message: str | None = None


@dataclass
class WorkflowExecutionResult:
    evidence: EvidencePack | None = None
    artifact: VisualArtifact | None = None
    governance_report: dict[str, Any] | None = None
    final_answer: str | None = None
    final_answer_display: str | None = None


@dataclass
class WorkflowRunContext:
    session: AsyncSession
    session_factory: async_sessionmaker[AsyncSession]
    persistence_lock: asyncio.Lock
    request: SubmitWorkflowRequest
    plan: WorkflowPlan
    resume_answers: dict[str, str]
    run_id: str
    workflow_mode: WorkflowMode
    registry: AgentRegistry
    repo: WorkflowRepository
    artifact_repo: ArtifactRepository
    evidence_repo: EvidenceRepository
    agent_run_repo: AgentRunRepository
    state_store: RedisStateStore
    is_resume: bool = False
    resume_cursor: str | None = None
    last_completed_node: str | None = None
    prior_turns: dict[str, Any] | None = None
    re_run_from_planning: bool = False

    @property
    def resume_from_post_research_hitl(self) -> bool:
        return (
            self.is_resume
            and self.resume_cursor in {"hitl_evidence", "hitl_depth"}
            and self.last_completed_node == "research"
        )


class EventFactory:
    def __init__(self, request: SubmitWorkflowRequest, run_id: str) -> None:
        self.request = request
        self.run_id = run_id
        self.sequence = 0

    def build(
        self,
        event_type: str,
        agent_name: str = "system",
        phase: str = "system",
        status: str = "running",
        data: dict[str, Any] | None = None,
        visibility: str = "user",
    ) -> StreamEvent:
        self.sequence += 1
        return StreamEvent(
            type=event_type,
            sequence=self.sequence,
            run_id=self.run_id,
            thread_id=self.request.thread_id,
            session_id=self.request.session_id,
            tenant_id=self.request.tenant_id,
            agent_name=agent_name,
            phase=phase,
            status=status,
            visibility=visibility,
            data=data or {},
        )


class WorkflowEngine:
    def __init__(
        self,
        registry: AgentRegistry,
        state_store: RedisStateStore | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.registry = registry
        self.state_store = state_store or RedisStateStore()
        self.session_factory = session_factory or get_session_local()
        self._cancellation_requests: set[str] = set()  # Track cancelled thread_ids
        self._harness_registry: HarnessRegistry | None = None  # Phase 3: lazy harness registry

    def _get_harness_registry(self) -> HarnessRegistry:
        """Lazy-load the harness registry for dispatch validation."""
        if self._harness_registry is None:
            self._harness_registry = self.registry.harness_registry
        return self._harness_registry

    @staticmethod
    def _assigned_agent_name(
        ctx: WorkflowRunContext,
        node_id: str,
        default_agent: str,
    ) -> str:
        for node in ctx.plan.task_graph.nodes:
            if node.node_id == node_id and node.assigned_to:
                return node.assigned_to
        return default_agent

    def _resolve_runtime_agent(
        self,
        ctx: WorkflowRunContext,
        node_id: str,
        default_agent: str,
    ) -> tuple[str, Any]:
        agent_name = self._assigned_agent_name(ctx, node_id, default_agent)
        agent = self.registry.get_agent(agent_name)
        if agent is None:
            agent_name = default_agent
            agent = self.registry.get_agent(default_agent)
        if agent is None:
            raise RuntimeError(f"Agent '{agent_name}' is not available in the runtime registry.")
        return agent_name, agent

    @staticmethod
    def _contract_workflow_id_for_request(request: SubmitWorkflowRequest) -> str | None:
        if request.analysis_mode == AnalysisMode.finance:
            return "finance_v1"
        if request.analysis_mode == AnalysisMode.data_science:
            return "data_science_v1"
        if request.artifact_family_hint is not None:
            if request.artifact_family_hint.value in TEXT_FAMILIES:
                return "text_artifact_v1"
            return "visual_artifact_v1"
        return None

    def _contract_workflow_id(self, ctx: WorkflowRunContext) -> str | None:
        workflow_id = getattr(ctx.plan, "workflow_template_id", None)
        if workflow_id:
            return canonicalize_workflow_template_id(workflow_id)
        return canonicalize_workflow_template_id(self._contract_workflow_id_for_request(ctx.request))

    def _default_research_agent_name(self, ctx: WorkflowRunContext) -> str:
        mode = ctx.request.analysis_mode
        if mode == AnalysisMode.finance:
            return "finance_research"
        if mode == AnalysisMode.data_science:
            return "data_science"
        return "deep_research"

    def _resolve_research_runtime_agent(self, ctx: WorkflowRunContext) -> tuple[str, Any]:
        default_name = self._default_research_agent_name(ctx)
        assigned_name = self._assigned_agent_name(ctx, "research", default_name)
        agent = self.registry.get_agent(assigned_name)
        if agent is None:
            agent = self.registry.get_agent(default_name)
            assigned_name = default_name
        if agent is None:
            agent = self.registry.get_agent("research")
            assigned_name = "research"
        if agent is None:
            raise RuntimeError("No research-capable agent is available in the runtime registry.")
        return assigned_name, agent

    @staticmethod
    async def _call_research_gather(
        agent: Any,
        session: Any,
        tenant_id: str,
        query: str,
        source_scope: str,
        *,
        quick_recall: bool,
    ) -> EvidencePack:
        signature = inspect.signature(agent.gather)
        kwargs: dict[str, Any] = {}
        if "session" in signature.parameters:
            kwargs["session"] = session
        if "tenant_id" in signature.parameters:
            kwargs["tenant_id"] = tenant_id
        if "query" in signature.parameters:
            kwargs["query"] = query
        elif "user_query" in signature.parameters:
            kwargs["user_query"] = query
        if "source_scope" in signature.parameters:
            kwargs["source_scope"] = source_scope
        elif "scope" in signature.parameters:
            kwargs["scope"] = source_scope
        if "quick_recall" in signature.parameters:
            kwargs["quick_recall"] = quick_recall
        return await agent.gather(**kwargs)

    @staticmethod
    def _extract_followup_research_requests(slides_data: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(slides_data, dict):
            return []
        metadata = slides_data.get("metadata")
        if not isinstance(metadata, dict):
            return []
        requests = metadata.get("followup_research_requests")
        if not isinstance(requests, list):
            return []
        return [item for item in requests if isinstance(item, dict) and item.get("request")]

    @staticmethod
    def _extract_slide_followup_requests(slides_data: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(slides_data, dict):
            return []
        slides = slides_data.get("slides")
        if not isinstance(slides, list):
            return []

        requests: list[dict[str, Any]] = []
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            slide_requests = slide.get("research_requests")
            if not isinstance(slide_requests, list) or not slide_requests:
                continue
            request_text = next((str(item).strip() for item in slide_requests if str(item).strip()), "")
            if not request_text:
                continue
            slide_title = str(
                slide.get("headline")
                or slide.get("title")
                or slide.get("subtitle")
                or f"Slide {index + 1}"
            ).strip()
            requests.append(
                {
                    "slide_index": index,
                    "slide_title": slide_title or f"Slide {index + 1}",
                    "request": request_text,
                }
            )
        return requests

    @staticmethod
    def _format_followup_research_query(user_query: str, group: dict[str, Any]) -> str:
        slide_titles = group.get("slide_titles") or []
        if not slide_titles and group.get("slide_title"):
            slide_titles = [group.get("slide_title")]
        titles = ", ".join(str(title) for title in slide_titles if title)
        request = str(group.get("request") or "").strip()
        return (
            f"User request: {user_query}\n"
            f"Slide group: {titles or 'n/a'}\n"
            f"Follow-up research request: {request}\n"
            "Return only compact evidence that helps the content director sharpen those slides."
        )

    async def _emit_step_summary(
        self,
        events: EventFactory,
        publish: EventPublisher,
        *,
        step: str,
        phase: str,
        summary: dict[str, Any],
    ) -> None:
        logger.info(
            "[workflow] step_summary step=%s phase=%s summary=%s",
            step,
            phase,
            json.dumps(summary, ensure_ascii=False, default=str),
        )
        await publish(
            events.build(
                "workflow_step_summary",
                agent_name="system",
                phase=phase,
                data={"step": step, "summary": summary},
            )
        )

    def _strategist_research_handoff(self, ctx: WorkflowRunContext) -> dict[str, Any]:
        return {
            "workflow_id": self._contract_workflow_id(ctx) or "",
            "query": ctx.request.user_query,
            "source_scope": ctx.request.source_scope,
            "workflow_plan": ctx.plan.model_dump(mode="json"),
            "task_graph": ctx.plan.task_graph.model_dump(mode="json"),
            "missing_requirements": list(getattr(ctx.plan, "missing_requirements", [])),
        }

    def _pre_dispatch_check(
        self,
        agent_id: str,
        input_data: dict[str, Any],
        *,
        workflow_id: str | None = None,
        tools_requested: list[str] | None = None,
    ) -> None:
        """Validate an agent dispatch via the PRE_DISPATCH hook evaluator.

        Advisory-only — logs WARN on failure, never raises.
        """
        ctx = HookContext(
            hook_type=HookType.PRE_DISPATCH,
            node_id=agent_id,
            agent_id=agent_id,
            input_data=input_data,
            workflow_id=workflow_id,
            metadata={"tools_requested": tools_requested or []},
        )
        decision = evaluate_pre_dispatch(ctx, self._get_harness_registry())
        if decision.action != HookAction.PROCEED:
            enforcement_check(
                ok=decision.action not in {HookAction.BLOCK},
                errors=decision.errors,
                context=f"dispatch agent={agent_id} workflow={workflow_id}",
                warnings=decision.warnings,
            )

    def _pre_handoff_check(
        self,
        from_agent_id: str,
        to_agent_id: str,
        output_data: dict[str, Any],
        *,
        workflow_id: str | None = None,
    ) -> None:
        """Validate a handoff via the PRE_DISPATCH hook evaluator (handoff variant).

        Advisory-only — logs WARN on failure, never raises.
        """
        ctx = HookContext(
            hook_type=HookType.PRE_DISPATCH,
            node_id=from_agent_id,
            agent_id=from_agent_id,
            input_data={},
            output_data=output_data,
            workflow_id=workflow_id,
            metadata={"to_agent_id": to_agent_id},
        )
        decision = evaluate_pre_handoff(ctx, self._get_harness_registry())
        if decision.action != HookAction.PROCEED:
            enforcement_check(
                ok=decision.action not in {HookAction.BLOCK},
                errors=decision.errors,
                context=f"handoff from={from_agent_id} to={to_agent_id} workflow={workflow_id}",
                warnings=decision.warnings,
            )

    def _pre_tool_call_check(
        self,
        agent_id: str,
        tool_id: str,
        tool_input: dict[str, Any],
        *,
        workflow_id: str | None = None,
    ) -> None:
        """Validate a tool call against harness contracts.

        Advisory-only in Phase 3 — logs violations, does not raise.
        """
        result = validate_tool_call(
            agent_id=agent_id,
            tool_id=tool_id,
            tool_input=tool_input,
            registry=self._get_harness_registry(),
            workflow_id=workflow_id,
        )
        enforcement_check(
            ok=result.ok,
            errors=result.errors,
            context=f"tool_call agent={agent_id} tool={tool_id} workflow={workflow_id}",
            warnings=result.warnings,
        )

    async def _execute_with_recovery(
        self,
        agent_id: str,
        run_fn: Callable[[], Awaitable[Any]],
        input_data: dict[str, Any],
        *,
        workflow_id: str | None = None,
        node_id: str | None = None,
        max_attempts: int = 3,
        retry_budget: RetryBudget | None = None,
    ) -> Any:
        """Execute run_fn with failure classification and policy-driven recovery.

        Enhanced from Phase 4 blind retry to Phase 8 contract-aware recovery:
        1. Wraps input/output in RuntimeMsg envelopes for traceability.
        2. Classifies failures via contracts.recovery.classify_failure().
        3. Consults resolve_recovery() for deterministic recovery action.
        4. Respects per-workflow RetryBudget when provided.
        5. Logs RecoveryEvent for each failure.

        Args:
            agent_id: Agent being executed.
            run_fn: Zero-argument async callable that performs the agent work.
            input_data: Data being sent to the agent.
            workflow_id: Current workflow instance identifier.
            node_id: Current node identifier (defaults to agent_id).
            max_attempts: Maximum execution attempts (default 3).
            retry_budget: Optional per-workflow retry budget tracker.

        Returns:
            Whatever run_fn returns on success.

        Raises:
            Exception: Re-raises the last exception if recovery says BLOCK
                or all attempts exhausted.
        """
        effective_node_id = node_id or agent_id
        budget = retry_budget or RetryBudget(workflow_id=workflow_id or "anonymous")

        # Create input envelope for traceability
        input_msg = make_agent_input(
            workflow_id=workflow_id,
            node_id=effective_node_id,
            agent_id=agent_id,
            payload=input_data,
        )
        logger.debug(
            "execute_with_recovery: input_msg=%s agent=%s node=%s",
            input_msg.msg_id, agent_id, effective_node_id,
        )

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            self._pre_dispatch_check(agent_id, input_data, workflow_id=workflow_id)
            try:
                result = await run_fn()

                # Wrap output in envelope
                output_msg = make_agent_output(
                    input_msg=input_msg,
                    payload=result if isinstance(result, dict) else {"result": result},
                )
                logger.debug(
                    "execute_with_recovery: output_msg=%s parent=%s",
                    output_msg.msg_id, output_msg.parent_msg_id,
                )
                return result
            except Exception as exc:  # noqa: BLE001 — intentional catch-all for recovery loop
                last_exc = exc
                # Classify the failure
                context = {"agent_id": agent_id, "node_id": effective_node_id}
                failure_class = classify_failure(exc, context)

                # Check budget
                if not budget.can_retry(effective_node_id):
                    failure_class = FailureClass.UNKNOWN  # budget exhausted overrides

                # Get recovery decision
                recovery = resolve_recovery(
                    failure_class=failure_class,
                    budget=budget,
                    node_id=effective_node_id,
                )

                # Log structured recovery event
                event = RecoveryEvent.create(
                    workflow_id=workflow_id,
                    node_id=effective_node_id,
                    agent_id=agent_id,
                    failure_class=failure_class,
                    recovery_action=recovery,
                    attempt_number=attempt,
                    budget_remaining=budget.remaining(effective_node_id),
                    error_message=str(exc),
                )
                logger.warning(
                    "recovery_event: %s failure=%s action=%s attempt=%d/%d budget_remaining=%d",
                    event.event_id,
                    failure_class.value,
                    recovery.action.value,
                    attempt + 1,
                    max_attempts,
                    event.budget_remaining,
                )

                budget.record_attempt(effective_node_id)

                # Act on recovery decision
                if recovery.block_workflow:
                    raise
                if attempt == max_attempts - 1:
                    raise

        raise last_exc  # type: ignore[misc]

    async def cancel(self, thread_id: str) -> None:
        """Request cancellation of a running workflow."""
        self._cancellation_requests.add(thread_id)
        logger.info("Cancellation requested for thread %s", thread_id)

    def _is_cancelled(self, thread_id: str) -> bool:
        """Check if workflow cancellation was requested."""
        return thread_id in self._cancellation_requests

    def _clear_cancellation(self, thread_id: str) -> None:
        """Clear cancellation flag after workflow completes."""
        self._cancellation_requests.discard(thread_id)

    def _resolve_enterprise_user_id(self) -> str | None:
        if settings.hivemind_enterprise_user_id:
            return settings.hivemind_enterprise_user_id
        rpc_url = getattr(getattr(self.registry, "hivemind", None), "rpc_url", None)
        return _parse_hivemind_user_id(rpc_url)

    async def _write_enterprise_user_turn(self, request: SubmitWorkflowRequest) -> tuple[int | None, str | None]:
        hivemind = getattr(self.registry, "hivemind", None)
        if not hivemind or not getattr(hivemind, "enterprise_chat_enabled", False):
            return None, request.memory_chain_id
        if not request.session_id or not request.user_query:
            return None, request.memory_chain_id

        user_id = self._resolve_enterprise_user_id()
        if not user_id:
            logger.warning("Skipping enterprise user turn write: no user_id available")
            return None, request.memory_chain_id

        enterprise_state = (request.metadata or {}).get("enterprise_chat", {}) if isinstance(request.metadata, dict) else {}
        is_new_chat = not bool(request.memory_chain_id)
        turn_number = None if is_new_chat else enterprise_state.get("next_turn_number") or 2

        result = await hivemind.save_enterprise_chat_turn(
            sid=request.session_id,
            turn="user",
            content=request.user_query,
            is_new_chat=is_new_chat,
            turn_number=turn_number,
            idempotency_key=f"{request.session_id}-user-{turn_number or 1}",
            user_id=user_id,
            metadata={"thread_id": request.thread_id, "tenant_id": request.tenant_id},
        )
        current_turn_number = result.turn_number or turn_number or 1
        request.memory_chain_id = result.turn_memory_id or request.memory_chain_id
        request.metadata = {
            **(request.metadata or {}),
            "enterprise_chat": {
                "turn_number": current_turn_number,
                "next_turn_number": current_turn_number + 1,
                "last_turn_memory_id": result.turn_memory_id,
                "user_write_status": result.status,
            },
        }
        return current_turn_number, request.memory_chain_id

    async def _write_enterprise_agent_turn(self, request: SubmitWorkflowRequest, final_answer: str) -> str | None:
        hivemind = getattr(self.registry, "hivemind", None)
        if not hivemind or not getattr(hivemind, "enterprise_chat_enabled", False):
            return request.memory_chain_id
        if not request.session_id or not final_answer:
            return request.memory_chain_id

        user_id = self._resolve_enterprise_user_id()
        if not user_id:
            logger.warning("Skipping enterprise agent turn write: no user_id available")
            return request.memory_chain_id

        enterprise_state = (request.metadata or {}).get("enterprise_chat", {}) if isinstance(request.metadata, dict) else {}
        turn_number = enterprise_state.get("turn_number") or 1
        result = await hivemind.save_enterprise_chat_turn(
            sid=request.session_id,
            turn="agent",
            content=final_answer,
            is_new_chat=False,
            turn_number=turn_number,
            idempotency_key=f"{request.session_id}-agent-{turn_number}",
            user_id=user_id,
            metadata={"thread_id": request.thread_id, "tenant_id": request.tenant_id},
        )
        request.memory_chain_id = result.turn_memory_id or request.memory_chain_id
        request.metadata = {
            **(request.metadata or {}),
            "enterprise_chat": {
                **enterprise_state,
                "last_turn_memory_id": result.turn_memory_id,
                "agent_write_status": result.status,
            },
        }
        return request.memory_chain_id

    @staticmethod
    async def _load_brand_dna(tenant_id: str) -> dict[str, Any] | None:
        from agentscope_blaiq.runtime.config import settings
        from pathlib import Path
        path = Path(settings.artifact_dir) / "brand_dna" / f"{tenant_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _load_brand_voice_text(tenant_id: str) -> str:
        """Load brand voice markdown for a tenant."""
        return load_brand_voice(tenant_id)

    async def run(self, session: AsyncSession, request: SubmitWorkflowRequest):
        if isinstance(session, AsyncSession):
            async with self.session_factory() as workflow_session:
                async for event in self._run_workflow(session=workflow_session, request=request, resume_request=None):
                    yield event
            return
        async for event in self._run_workflow(session=session, request=request, resume_request=None):
                yield event

    @staticmethod
    def _resolve_resume_answers(request: ResumeWorkflowRequest) -> dict[str, str]:
        """Extract the canonical answers dict from a resume request.

        Prefers the typed ``answer_set`` (Phase 4+) over the legacy flat
        ``answers`` dict so both paths keep working during the rollout.
        """
        if request.answer_set is not None and request.answer_set.answers:
            return dict(request.answer_set.answers)
        return dict(request.answers)

    @staticmethod
    def _validate_answer_set(
        request: ResumeWorkflowRequest,
        redis_state: Any | None,
    ) -> list[str]:
        """Validate a typed ``ClarificationAnswerSet`` against the stored bundle.

        Returns a list of error strings (empty = valid).  Skips validation when
        no typed ``answer_set`` is present so legacy resume paths are unaffected.
        """
        if request.answer_set is None:
            return []
        if redis_state is None:
            return []
        bundle_json: str | None = getattr(redis_state, "blocked_bundle_json", None)
        if not bundle_json:
            return []
        try:
            bundle = ClarificationBundle.model_validate_json(bundle_json)
        except Exception:
            return []

        errors: list[str] = []
        provided = {
            k.strip(): str(v).strip()
            for k, v in request.answer_set.answers.items()
            if str(v).strip()
        }
        for q in bundle.questions:
            if q.required and q.requirement_id not in provided:
                errors.append(
                    f"Required question '{q.requirement_id}' has no answer."
                )
        return errors

    async def resume(self, session: AsyncSession, request: ResumeWorkflowRequest):
        repo = WorkflowRepository(session, self.state_store)
        workflow = await repo.get_workflow_record(request.thread_id)
        if workflow is None:
            raise ValueError("Workflow not found")
        snapshot = await repo.get_status(request.thread_id)
        if snapshot is None:
            raise ValueError("Workflow not found")
        if snapshot.status not in {WorkflowStatus.blocked, WorkflowStatus.error}:
            raise ValueError("Workflow can only be resumed from blocked or error status")

        submit_request = await repo.build_submit_request(request.thread_id)
        if submit_request is None:
            raise ValueError("Workflow not found")
        if request.tenant_id is not None and request.tenant_id != submit_request.tenant_id:
            raise ValueError("tenant_id does not match the stored workflow")

        resume_reason = request.resume_reason or f"retry from {snapshot.status.value}"

        # Phase 4: validate typed answer_set when provided.
        if request.answer_set is not None:
            redis_state = await self.state_store.get_workflow_state(request.thread_id)
            validation_errors = self._validate_answer_set(request, redis_state)
            if validation_errors:
                raise ValueError(
                    "Resume blocked — answer validation failed: "
                    + "; ".join(validation_errors)
                )

        if isinstance(session, AsyncSession):
            async with self.session_factory() as workflow_session:
                async for event in self._run_workflow(
                    session=workflow_session,
                    request=submit_request,
                    resume_request=request,
                    resume_reason=resume_reason,
                    previous_status=snapshot.status.value,
                    previous_run_id=snapshot.run_id,
                ):
                    yield event
            return
        async for event in self._run_workflow(
            session=session,
            request=submit_request,
            resume_request=request,
            resume_reason=resume_reason,
            previous_status=snapshot.status.value,
            previous_run_id=snapshot.run_id,
        ):
                yield event

    async def _run_workflow(
        self,
        *,
        session: AsyncSession,
        request: SubmitWorkflowRequest,
        resume_request: ResumeWorkflowRequest | None,
        resume_reason: str | None = None,
        previous_status: str | None = None,
        previous_run_id: str | None = None,
    ):
        repo = WorkflowRepository(session, self.state_store)
        artifact_repo = ArtifactRepository(session)
        evidence_repo = EvidenceRepository(session)
        agent_run_repo = AgentRunRepository(session)

        is_resume = resume_request is not None
        resume_cursor: str | None = None
        last_completed_node: str | None = None
        run_id = str(uuid4())
        events = EventFactory(request, run_id)
        queue: asyncio.Queue[StreamEvent | object] = asyncio.Queue()
        done_marker = object()
        persistence_lock = asyncio.Lock()

        async def publish(event: StreamEvent) -> StreamEvent:
            async with persistence_lock:
                await repo.append_event(event)
            logger.info(
                "workflow_event type=%s phase=%s agent=%s status=%s thread_id=%s data=%s",
                event.type,
                event.phase,
                event.agent_name,
                event.status,
                event.thread_id,
                self._summarize_event_data(event),
            )
            await queue.put(event)
            return event

        def make_agent_log_sink(agent_name: str, phase: str, node_id: str | None = None):
            return _make_agent_log_sink(events, publish, agent_name, phase, node_id=node_id or phase)

        if not is_resume:
            await repo.create_workflow(request, run_id=run_id, workflow_plan_json=None)
            try:
                user_turn_number, updated_memory_chain_id = await self._write_enterprise_user_turn(request)
                if updated_memory_chain_id:
                    request.memory_chain_id = updated_memory_chain_id
                if user_turn_number is not None:
                    logger.info("Saved enterprise user turn sid=%s turn_number=%s", request.session_id, user_turn_number)
            except Exception as exc:
                logger.warning("Failed to save enterprise user turn: %s", exc)
            await self.state_store.set_workflow_state(
                WorkflowRedisState(
                    thread_id=request.thread_id,
                    run_id=run_id,
                    tenant_id=request.tenant_id,
                    session_id=request.session_id,
                    workflow_mode=request.workflow_mode,
                    analysis_mode=request.analysis_mode,
                    artifact_type=request.artifact_type,
                    source_scope=request.source_scope,
                    user_query=request.user_query,
                    analysis_subject=request.analysis_subject,
                    analysis_objective=request.analysis_objective,
                    analysis_horizon=request.analysis_horizon,
                    analysis_benchmark=request.analysis_benchmark,
                    memory_chain_id=request.memory_chain_id,
                    workflow_plan_json=None,
                    status=WorkflowStatus.queued,
                    current_node="planning",
                    current_phase="planning",
                    current_agent="strategist",
                )
            )

        else:
            current_state = await self.state_store.get_workflow_state(request.thread_id)
            if current_state is not None:
                resume_cursor = current_state.resume_cursor
                last_completed_node = current_state.last_completed_node
            if current_state is None:
                await self.state_store.set_workflow_state(
                    WorkflowRedisState(
                        thread_id=request.thread_id,
                        run_id=run_id,
                        tenant_id=request.tenant_id,
                        session_id=request.session_id,
                        workflow_mode=request.workflow_mode,
                        analysis_mode=request.analysis_mode,
                        artifact_type=request.artifact_type,
                        source_scope=request.source_scope,
                        user_query=request.user_query,
                        analysis_subject=request.analysis_subject,
                        analysis_objective=request.analysis_objective,
                        analysis_horizon=request.analysis_horizon,
                        analysis_benchmark=request.analysis_benchmark,
                        memory_chain_id=request.memory_chain_id,
                        workflow_plan_json=None,
                        status=WorkflowStatus.queued,
                        current_node="planning",
                        current_phase="planning",
                        current_agent="strategist",
                    )
                )
            await self.state_store.mark_resumed(
                request.thread_id,
                run_id=run_id,
                resume_reason=resume_reason,
            )
            await self._update_workflow_snapshot(
                repo,
                request.thread_id,
                run_id=run_id,
                status=WorkflowStatus.queued,
                current_node="planning",
                current_phase="planning",
                current_agent="strategist",
                latest_event="workflow_resumed" if is_resume else "workflow_submitted",
                workflow_mode=request.workflow_mode,
                analysis_mode=request.analysis_mode,
                workflow_plan_json=None,
                error_message=None,
                final_artifact_json=None,
            )

        async def execute() -> None:
            plan: WorkflowPlan | None = None
            workflow_mode = request.workflow_mode
            try:
                await publish(
                    events.build(
                        "workflow_resumed" if is_resume else "workflow_submitted",
                        phase="workflow",
                        data=(
                            {
                                "workflow_mode": workflow_mode.value,
                                "resume_reason": resume_reason,
                                "previous_status": previous_status,
                                "previous_run_id": previous_run_id,
                            }
                            if is_resume
                            else {"workflow_mode": workflow_mode.value}
                        ),
                    )
                )
                if is_resume:
                    _resolved = self._resolve_resume_answers(resume_request) if resume_request is not None else {}
                    await publish(
                        events.build(
                            "resume_accepted",
                            agent_name="strategist",
                            phase="planning",
                            data={
                                "answers": _resolved,
                                "resume_reason": resume_reason,
                                "resume_strategy": getattr(resume_request, "resume_strategy", "continue") if resume_request else "continue",
                                "clarification_bundle_id": getattr(resume_request, "clarification_bundle_id", None) if resume_request else None,
                            },
                        )
                    )
                await publish(
                    events.build(
                        "planning_started",
                        agent_name="strategist",
                        phase="planning",
                        data={"workflow_mode": workflow_mode.value},
                    )
                )
                await self._maybe_set_log_sink(self.registry.strategist, make_agent_log_sink("strategist", "planning", "planning"))
                plan = await self._resolve_plan(request, repo, is_resume=is_resume)
                workflow_mode = plan.workflow_mode
                await self._update_workflow_snapshot(
                    repo,
                    request.thread_id,
                    run_id=run_id,
                    status=WorkflowStatus.queued,
                    current_node="planning",
                    current_phase="planning",
                    current_agent="strategist",
                    latest_event="planning_started",
                    workflow_mode=workflow_mode,
                    workflow_plan_json=plan.model_dump_json(),
                    error_message=None,
                    final_artifact_json=None,
                )
                await self.state_store.set_workflow_state(
                    WorkflowRedisState(
                        thread_id=request.thread_id,
                        run_id=run_id,
                        tenant_id=request.tenant_id,
                        session_id=request.session_id,
                        workflow_mode=workflow_mode,
                        analysis_mode=request.analysis_mode,
                        artifact_type=request.artifact_type,
                        source_scope=request.source_scope,
                        user_query=request.user_query,
                        analysis_subject=request.analysis_subject,
                        analysis_objective=request.analysis_objective,
                        analysis_horizon=request.analysis_horizon,
                        analysis_benchmark=request.analysis_benchmark,
                        workflow_plan_json=plan.model_dump_json(),
                        status=WorkflowStatus.queued,
                        current_node="planning",
                        current_phase="planning",
                        current_agent="strategist",
                    )
                )

                ctx = WorkflowRunContext(
                    session=session,
                    session_factory=self.session_factory,
                    persistence_lock=persistence_lock,
                    request=request,
                    plan=plan,
                    resume_answers=self._resolve_resume_answers(resume_request) if resume_request is not None else {},
                    run_id=run_id,
                    workflow_mode=workflow_mode,
                    registry=self.registry,
                    repo=repo,
                    artifact_repo=artifact_repo,
                    evidence_repo=evidence_repo,
                    agent_run_repo=agent_run_repo,
                    state_store=self.state_store,
                    is_resume=is_resume,
                    re_run_from_planning=getattr(request, "re_run_from_planning", False),
                    resume_cursor=resume_cursor,
                    last_completed_node=last_completed_node,
                    prior_turns=(request.metadata or {}).get("prior_turns"),
                )
                result = await self._execute_workflow(
                    ctx,
                    events,
                    publish,
                    emit_initial_events=False,
                )

                # Signal strategist completion for continuous UI flow
                await publish(
                    events.build(
                        "agent_log",
                        agent_name="strategist",
                        phase="planning",
                        status="completed",
                        data={"message": "Strategic plan finalized. Intelligence grid initialized."},
                    )
                )

                workflow_state = await self.state_store.get_workflow_state(request.thread_id)
                if workflow_state is not None and workflow_state.status == WorkflowStatus.blocked:
                    if result.evidence is not None:
                        evidence_id = str(uuid4())
                        await evidence_repo.save(request.thread_id, request.tenant_id, evidence_id, result.evidence)
                    return

                if result.evidence is not None:
                    evidence_id = str(uuid4())
                    await evidence_repo.save(request.thread_id, request.tenant_id, evidence_id, result.evidence)

                persisted_artifact = result.artifact
                if persisted_artifact is not None:
                    governance_status = "approved"
                    if result.governance_report is not None and not result.governance_report.get("approved", False):
                        governance_status = "revision_required"
                    persisted_artifact = persisted_artifact.model_copy(update={"governance_status": governance_status})
                    self._pre_tool_call_check(
                        "vangogh",
                        "persist_artifact_files",
                        {
                            "thread_id": request.thread_id,
                            "artifact": persisted_artifact.model_dump(mode="json"),
                        },
                        workflow_id=canonicalize_workflow_template_id(
                            getattr(plan, "workflow_template_id", None)
                            or self._contract_workflow_id_for_request(request)
                        ),
                    )
                    html_path, css_path = persist_artifact_files(request.thread_id, persisted_artifact)
                    await artifact_repo.save(request.thread_id, request.tenant_id, persisted_artifact, html_path, css_path)
                    await repo.set_final_artifact(request.thread_id, persisted_artifact)

                await self._update_workflow_snapshot(
                    repo,
                    request.thread_id,
                    run_id=run_id,
                    status=WorkflowStatus.complete,
                    current_node="workflow_complete",
                    current_phase="workflow",
                    current_agent="system",
                    latest_event="workflow_complete",
                    analysis_mode=request.analysis_mode,
                    final_artifact_json=persisted_artifact.model_dump_json() if persisted_artifact is not None else None,
                    final_answer=result.final_answer,
                )
                await self.state_store.set_workflow_state(
                    WorkflowRedisState(
                        thread_id=request.thread_id,
                        run_id=run_id,
                        tenant_id=request.tenant_id,
                        session_id=request.session_id,
                        workflow_mode=workflow_mode,
                        analysis_mode=request.analysis_mode,
                        artifact_type=request.artifact_type,
                        source_scope=request.source_scope,
                        user_query=request.user_query,
                        analysis_subject=request.analysis_subject,
                        analysis_objective=request.analysis_objective,
                        analysis_horizon=request.analysis_horizon,
                        analysis_benchmark=request.analysis_benchmark,
                        memory_chain_id=request.memory_chain_id,
                        workflow_plan_json=plan.model_dump_json(),
                        status=WorkflowStatus.complete,
                        current_node="workflow_complete",
                        current_phase="workflow",
                        current_agent="system",
                        final_artifact_json=persisted_artifact.model_dump_json() if persisted_artifact is not None else None,
                        final_answer=result.final_answer,
                    )
                )
                await publish(
                    events.build(
                        "workflow_complete",
                        phase="workflow",
                        status="complete",
                        data={
                            "workflow_mode": workflow_mode.value,
                            "final_artifact": persisted_artifact.model_dump() if persisted_artifact is not None else None,
                            "final_answer": result.final_answer,
                            "final_answer_display": result.final_answer_display or result.final_answer,
                            "evidence_pack": result.evidence.model_dump() if result.evidence is not None else None,
                            "governance_report": result.governance_report,
                            "memory_chain_id": request.memory_chain_id,
                        },
                    )
                )

                if request.session_id and result.final_answer:
                    try:
                        updated_memory_chain_id = await self._write_enterprise_agent_turn(
                            request,
                            result.final_answer_display or result.final_answer,
                        )
                        if updated_memory_chain_id:
                            request.memory_chain_id = updated_memory_chain_id
                        logger.info("Saved enterprise agent turn sid=%s memory_chain_id=%s", request.session_id, request.memory_chain_id or "n/a")
                    except Exception as hivemind_exc:
                        logger.warning("Failed to save enterprise agent turn: %s", hivemind_exc)
            except Exception as exc:
                await self._update_workflow_snapshot(
                    repo,
                    request.thread_id,
                    run_id=run_id,
                    status=WorkflowStatus.error,
                    current_node="workflow_error",
                    current_phase="workflow",
                    current_agent="system",
                    latest_event="workflow_error",
                    error_message=str(exc),
                )
                await self.state_store.mark_error(request.thread_id, str(exc))
                await publish(
                    events.build(
                        "workflow_error",
                        phase="workflow",
                        status="error",
                        data={"error_message": str(exc)},
                    )
                )
            finally:
                await queue.put(done_marker)

        task = asyncio.create_task(execute())
        while True:
            item = await queue.get()
            if item is done_marker:
                break
            yield item
        await task

    async def _resolve_plan(self, request: SubmitWorkflowRequest, repo: WorkflowRepository, *, is_resume: bool) -> WorkflowPlan:
        # For simple resumes (answers/blocked), reuse the exact same plan.
        # For re-run retries, we want to RE-PLAN (to iterate on style/sections) but skip RESEARCH.
        if is_resume and not request.re_run_from_planning:
            workflow = await repo.get_workflow_record(request.thread_id)
            if workflow is not None and workflow.workflow_plan_json:
                try:
                    return WorkflowPlan.model_validate_json(workflow.workflow_plan_json)
                except Exception:
                    pass
        # Log sink is injected by the caller's publish closure via make_agent_log_sink.
        strategist = self.registry.strategist
        build_plan = getattr(strategist, "build_plan")
        self._pre_dispatch_check(
            "strategist",
            {
                "user_request": request.user_query,
                "agent_catalog": [agent.model_dump(mode="json") for agent in self.registry.list_live_profiles()],
            },
            workflow_id=self._contract_workflow_id_for_request(request),
        )
        signature = inspect.signature(build_plan)
        kwargs: dict[str, Any] = {}
        if "agent_catalog" in signature.parameters:
            kwargs["agent_catalog"] = self.registry.list_live_profiles()
        if "user_registry" in signature.parameters:
            kwargs["user_registry"] = self.registry.user_agent_registry
        if kwargs:
            return await build_plan(request, **kwargs)
        return await build_plan(request)

    @staticmethod
    async def _maybe_set_log_sink(agent: Any, sink: Any) -> None:

        setter = getattr(agent, "set_log_sink", None)
        if callable(setter):
            setter(sink)

        # Persona-Linked Status Logs: give immediate, context-aware feedback
        starter = getattr(agent, "log_starting", None)
        if callable(starter):
            await starter()


    def _get_research_agent(self, ctx: WorkflowRunContext) -> Any:
        """Return the appropriate research agent based on analysis_mode.

        - finance         → finance_research  (hypothesis-driven)
        - data_science    → data_science       (code execution + analysis)
        - standard/all    → deep_research      (tree-search, depth-capped at 2)
        - fallback        → research           (flat recall)
        """
        mode = ctx.request.analysis_mode
        if mode == AnalysisMode.finance:
            agent = getattr(self.registry, "finance_research", None)
            if agent is not None:
                return agent
        elif mode == AnalysisMode.data_science:
            agent = getattr(self.registry, "data_science", None)
            if agent is not None:
                return agent
        else:
            agent = getattr(self.registry, "deep_research", None)
            if agent is not None:
                return agent
        return self.registry.research

    @staticmethod
    async def _update_workflow_snapshot(repo: WorkflowRepository, thread_id: str, **kwargs: Any) -> None:
        update = getattr(repo, "update_workflow_snapshot", None)
        if not callable(update):
            return
        signature = inspect.signature(update)
        filtered = {key: value for key, value in kwargs.items() if key in signature.parameters}
        await update(thread_id, **filtered)

    @staticmethod
    def _task_graph_node(plan: WorkflowPlan, node_id: str) -> Any | None:
        for node in plan.task_graph.nodes:
            if node.node_id == node_id:
                return node
        return None

    @staticmethod
    def _missing_requirements(
        plan: WorkflowPlan,
        answers: dict[str, str] | None = None,
        *,
        stages: set[RequirementStage] | None = None,
    ) -> list[str]:
        provided = {key.strip(): str(value).strip() for key, value in (answers or {}).items() if str(value).strip()}
        missing: list[str] = []
        for item in plan.requirements_checklist.items:
            if not item.must_have:
                continue
            if item.status == "filled":
                continue
            if stages is not None and item.blocking_stage not in stages:
                continue
            if item.requirement_id in provided:
                continue
            missing.append(item.requirement_id)
        return missing

    @staticmethod
    def _event_stage_label(stages: set[RequirementStage]) -> str:
        if stages == {RequirementStage.before_research}:
            return "initial"
        if stages == {RequirementStage.evidence_informed, RequirementStage.before_render}:
            return "evidence_informed"
        return "general"

    @staticmethod
    def _blocked_question(plan: WorkflowPlan, missing_ids: list[str]) -> str:
        texts = []
        for item in plan.requirements_checklist.items:
            if item.requirement_id in missing_ids:
                texts.append(item.text)
        return " ".join(texts).strip() or "Please provide the missing requirements to continue."

    async def _build_clarification_prompt(
        self,
        ctx: WorkflowRunContext,
        missing_ids: list[str],
        evidence: EvidencePack,
        make_agent_log_sink: Callable[[str, str], Any],
    ) -> ClarificationPrompt:
        hitl_name = self._assigned_agent_name(ctx, "hitl", "hitl")
        _, hitl = self._resolve_runtime_agent(ctx, "hitl", "hitl")
        await self._maybe_set_log_sink(hitl, make_agent_log_sink(hitl_name, "clarification"))
        self.registry.mark_agent_busy(hitl_name, "clarification")
        try:
            generate_prompt = getattr(hitl, "generate_prompt")
            signature = inspect.signature(generate_prompt)
            kwargs = {
                "user_query": ctx.request.user_query,
                "artifact_family": ctx.plan.artifact_family,
                "requirements": ctx.plan.requirements_checklist,
                "missing_requirement_ids": missing_ids,
                "evidence_summary": evidence.summary,
                "target_audience": ctx.request.target_audience,
                "delivery_channel": ctx.request.delivery_channel,
                "brand_context": ctx.request.brand_context,
            }
            if "evidence" in signature.parameters:
                kwargs["evidence"] = evidence
            self._pre_handoff_check(
                "research",
                hitl_name,
                {
                    "evidence_pack": evidence.model_dump(mode="json"),
                    "missing_requirements": [{"id": r} for r in missing_ids] if missing_ids else [],
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            self._pre_dispatch_check(
                hitl_name,
                {
                    "missing_requirements": [{"id": r} for r in missing_ids] if missing_ids else [],
                    "evidence_summary": evidence.summary if evidence else "",
                    "workflow_family": ctx.plan.artifact_family.value,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            return await generate_prompt(**kwargs)
        finally:
            self.registry.mark_agent_ready(hitl_name, "idle")

    async def _load_latest_evidence(self, evidence_repo: EvidenceRepository, thread_id: str) -> EvidencePack | None:
        records = await evidence_repo.list_for_thread(thread_id)
        if not records:
            return None
        latest = records[-1]
        try:
            return EvidencePack.model_validate_json(latest.evidence_json)
        except Exception:
            return None

    async def _emit_catalog_snapshot(self, publish: EventPublisher, events: EventFactory) -> None:
        await publish(
            events.build(
                "agent_catalog_snapshot",
                agent_name="strategist",
                phase="planning",
                data={"agents": [agent.model_dump(mode="json") for agent in self.registry.list_live_profiles()]},
            )
        )

    async def _emit_evidence_signals(self, publish: EventPublisher, events: EventFactory, evidence: EvidencePack) -> None:
        if evidence.contradictions:
            await publish(
                events.build(
                    "contradictions_detected",
                    agent_name="research",
                    phase="research",
                    data={
                        "count": len(evidence.contradictions),
                        "contradictions": [item.model_dump() for item in evidence.contradictions],
                    },
                )
            )

    async def _run_content_director(
        self,
        ctx: WorkflowRunContext,
        events: EventFactory,
        publish: EventPublisher,
        *,
        evidence: EvidencePack,
    ) -> dict[str, Any]:
        node_id = "content_director"
        content_director_name = self._assigned_agent_name(ctx, node_id, "content_director")
        await self._set_branch(
            ctx,
            branch_id=node_id,
            agent_name=content_director_name,
            branch_kind="content_director",
            status="running",
            current_phase="content_director",
            input_json={
                "artifact_family": ctx.plan.artifact_family.value,
                "requirements": ctx.plan.requirements_checklist.model_dump(),
                "resume_answers": ctx.resume_answers,
            },
        )
        await publish(
            events.build(
                "content_director_started",
                agent_name=content_director_name,
                phase="content_director",
                data={"artifact_family": ctx.plan.artifact_family.value, "node_id": node_id},
            )
        )
        content_director_name, content_director = self._resolve_runtime_agent(ctx, node_id, "content_director")
        await self._maybe_set_log_sink(content_director, _make_agent_log_sink(events, publish, content_director_name, "content_director", node_id))
        self.registry.mark_agent_busy(content_director_name, "content_director")
        self._pre_handoff_check(
            "research",
            content_director_name,
            {"evidence_pack": evidence.model_dump(mode="json")},
            workflow_id=self._contract_workflow_id(ctx),
        )
        self._pre_dispatch_check(
            content_director_name,
            {
                "user_query": ctx.request.user_query,
                "evidence_summary": evidence.summary,
                "artifact_spec": (ctx.plan.artifact_spec or ArtifactSpec(family=ctx.plan.artifact_family)).model_dump(mode="json"),
                "requirements": ctx.plan.requirements_checklist.model_dump(mode="json"),
                "hitl_answers": ctx.resume_answers,
                "evidence_pack": evidence.model_dump(mode="json"),
            },
            workflow_id=self._contract_workflow_id(ctx),
        )
        artifact_spec = ctx.plan.artifact_spec or ArtifactSpec(family=ctx.plan.artifact_family)
        
        # New ReAct-based execution path
        try:
            react_msg = await content_director.reply(
                ctx.request.user_query,
                extra_context={
                    "artifact_family": ctx.plan.artifact_family.value,
                    "requirements": ctx.plan.requirements_checklist.model_dump_json(),
                    "evidence_summary": evidence.summary,
                    "hitl_answers": ctx.resume_answers,
                    "evidence_pack": evidence.model_dump(mode="json"),
                }
            )
            extracted = self._extract_brief_from_react(react_msg)
            if extracted:
                brief = ArtifactBrief.model_validate(extracted)
                artifact_brief = brief.model_dump(mode="json")
                if hasattr(content_director, "_artifact_brief_to_content_brief"):
                    legacy_brief = content_director._artifact_brief_to_content_brief(
                        artifact_brief=brief,
                        artifact_spec=artifact_spec,
                        hitl_answers=ctx.resume_answers,
                    )
                    content_brief = legacy_brief.model_dump(mode="json")
                else:
                    content_brief = artifact_brief
            else:
                raise ValueError("No structured brief in ReAct response")
                
        except Exception as react_exc:
            logger.warning("ReAct execution failed (%s); falling back to legacy direct planning.", react_exc)
            if hasattr(content_director, "plan_artifact_brief"):
                brief = await content_director.plan_artifact_brief(
                    user_query=ctx.request.user_query,
                    evidence_summary=evidence.summary,
                    artifact_spec=artifact_spec,
                    requirements=ctx.plan.requirements_checklist,
                    hitl_answers=ctx.resume_answers,
                    evidence_pack=evidence,
                )
                artifact_brief = brief.model_dump(mode="json")
                if hasattr(content_director, "_artifact_brief_to_content_brief"):
                    legacy_brief = content_director._artifact_brief_to_content_brief(
                        artifact_brief=brief,
                        artifact_spec=artifact_spec,
                        hitl_answers=ctx.resume_answers,
                    )
                    content_brief = legacy_brief.model_dump(mode="json")
                else:
                    content_brief = artifact_brief
            else:
                legacy_brief = await content_director.plan_content(
                    user_query=ctx.request.user_query,
                    evidence_summary=evidence.summary,
                    artifact_spec=artifact_spec,
                    requirements=ctx.plan.requirements_checklist,
                    hitl_answers=ctx.resume_answers,
                    evidence_pack=evidence,
                )
                content_brief = legacy_brief.model_dump(mode="json")
                artifact_brief = content_brief

        await self._update_workflow_snapshot(
            ctx.repo,
            ctx.request.thread_id,
            run_id=ctx.run_id,
            current_node="content_director",
            current_phase="content_director",
            current_agent=content_director_name,
            latest_event="content_director_completed",
            content_director_output_json=json.dumps(artifact_brief, default=str),
            last_completed_node="content_director",
        )
        workflow_state = await self.state_store.get_workflow_state(ctx.request.thread_id)
        if workflow_state is not None:
            workflow_state.current_node = "content_director"
            workflow_state.current_phase = "content_director"
            workflow_state.current_agent = content_director_name
            workflow_state.content_director_output_json = json.dumps(artifact_brief, default=str)
            workflow_state.last_completed_node = "content_director"
            workflow_state.updated_at = utc_now()
            await self.state_store.set_workflow_state(workflow_state)
        await publish(
            events.build(
                "content_director_completed",
                agent_name=content_director_name,
                phase="content_director",
                data={"artifact_brief": artifact_brief, "content_brief": content_brief},
            )
        )
        self.registry.mark_agent_ready(content_director_name, "idle")
        await self._complete_branch(ctx, branch_id=node_id, output_json=artifact_brief)
        return artifact_brief

    async def _run_text_buddy_pipeline(
        self,
        ctx: WorkflowRunContext,
        events: EventFactory,
        publish: EventPublisher,
        *,
        evidence: EvidencePack,
    ) -> WorkflowExecutionResult:
        """Run the text artifact pipeline: research_final_recall → text_buddy → governance."""
        # Check for cancellation at pipeline entry
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (text_buddy_pipeline start)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="text_buddy", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        effective_evidence = evidence

        # ── Phase 2: Research Final Recall (only on resume/HITL) ──
        if ctx.resume_answers:
            node_id = "research_final_recall"
            research_name, research_agent = self._resolve_research_runtime_agent(ctx)
            await self._set_branch(
                ctx,
                branch_id=node_id,
                agent_name=research_name,
                branch_kind="research",
                status="running",
                current_phase="research",
                input_json={
                    "original_query": ctx.request.user_query,
                    "hitl_answers": ctx.resume_answers,
                },
            )
            await publish(
                events.build(
                    "agent_started",
                    agent_name=research_name,
                    phase="research",
                    data={"node_id": node_id, "purpose": "Refining research with user feedback"},
                )
            )
            # Visible user-facing log so the frontend shows this phase.
            answer_summary = "; ".join(
                f"{k.split(':')[-1].replace('_', ' ')}: {v}"
                for k, v in list(ctx.resume_answers.items())[:3]
                if str(v).strip()
            )
            await publish(
                events.build(
                    "agent_log",
                    agent_name=research_name,
                    phase="research",
                    status="running",
                    data={
                        "message": f"Re-researching with your answers: {answer_summary or 'HITL context applied'}",
                        "message_kind": "status",
                        "visibility": "user",
                        "node_id": node_id,
                    },
                )
            )

            # Combine original query with HITL answers for an optimized recall request
            hitl_context = " ".join([f"{k}: {v}" for k, v in ctx.resume_answers.items()])
            combined_query = f"{ctx.request.user_query} | Additional context: {hitl_context}"

            try:
                # Perform the second research pass
                new_evidence = await self._call_research_gather(
                    research_agent,
                    ctx.session,
                    ctx.request.tenant_id,
                    combined_query,
                    ctx.request.source_scope or "all",
                    quick_recall=True,  # HITL re-research = fast recall with enriched query
                )
                # Merge with initial evidence packs
                effective_evidence = self._merge_evidence(evidence, new_evidence)
                merged_count = len(effective_evidence.findings) if hasattr(effective_evidence, "findings") else "?"
                await publish(
                    events.build(
                        "agent_log",
                        agent_name=research_name,
                        phase="research",
                        status="running",
                        data={
                            "message": f"Research refinement complete — {merged_count} findings ready for composition.",
                            "message_kind": "status",
                            "visibility": "user",
                            "node_id": node_id,
                        },
                    )
                )
                await publish(events.build("agent_completed", agent_name=research_name, phase="research", data={"evidence_pack": effective_evidence.model_dump()}))
                # Signal research refinement completion
                await publish(
                    events.build(
                        "agent_log",
                        agent_name=research_name,
                        phase="research",
                        status="completed",
                        data={"message": "Research refined with your feedback. Composition starting..."},
                    )
                )
            except Exception as exc:
                logger.warning("Research final recall failed, proceeding with prior evidence: %s", exc)
            finally:
                await self._complete_branch(ctx, branch_id=node_id, output_json=effective_evidence.model_dump())

        brand_voice = self._load_brand_voice_text(ctx.request.tenant_id)

        # ── Text Buddy composition ──
        node_id = "text_buddy"
        text_buddy_name = self._assigned_agent_name(ctx, node_id, "text_buddy")
        await self._set_branch(
            ctx,
            branch_id=node_id,
            agent_name=text_buddy_name,
            branch_kind="text_buddy",
            status="running",
            current_phase="text_buddy",
            input_json={
                "artifact_family": ctx.plan.artifact_family.value,
                "node_id": node_id,
                "pipeline": "text_buddy",
            },
        )
        text_buddy_run = await ctx.agent_run_repo.create_run(
            thread_id=ctx.request.thread_id,
            tenant_id=ctx.request.tenant_id,
            agent_name=text_buddy_name,
            agent_type=AgentType.text_buddy.value,
            branch_id=node_id,
            input_json={"query": ctx.request.user_query, "artifact_family": ctx.plan.artifact_family.value},
        )
        await publish(
            events.build(
                "agent_started",
                agent_name=text_buddy_name,
                phase="text_buddy",
                data={"artifact_family": ctx.plan.artifact_family.value, "node_id": node_id, "pipeline": "text_buddy"},
            )
        )

        text_buddy_name, text_buddy = self._resolve_runtime_agent(ctx, node_id, "text_buddy")
        await self._maybe_set_log_sink(text_buddy, _make_agent_log_sink(events, publish, text_buddy_name, "text_buddy", "text_buddy"))
        self.registry.mark_agent_busy(text_buddy_name, "text_buddy")
        prior_context = format_prior_context(ctx.prior_turns)
        self._pre_handoff_check(
            "research",
            text_buddy_name,
            {
                "artifact_family": ctx.plan.artifact_family.value,
                "evidence_pack": effective_evidence.model_dump(mode="json"),
                "user_query": ctx.request.user_query,
            },
            workflow_id=self._contract_workflow_id(ctx),
        )
        try:
            self._pre_dispatch_check(
                text_buddy_name,
                {
                    "user_query": ctx.request.user_query,
                    "artifact_family": ctx.plan.artifact_family.value,
                    "evidence_pack": evidence.model_dump(mode="json"),
                    "hitl_answers": ctx.resume_answers,
                    "brand_voice": brand_voice,
                    "tenant_id": ctx.request.tenant_id,
                    "prior_context": prior_context,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            text_artifact = await text_buddy.compose(
                user_query=ctx.request.user_query,
                artifact_family=ctx.plan.artifact_family.value,
                evidence_pack=evidence,
                hitl_answers=ctx.resume_answers,
                brand_voice=brand_voice,
                tenant_id=ctx.request.tenant_id,
                prior_context=prior_context,
            )
        finally:
            self.registry.mark_agent_ready(text_buddy_name, "idle")

        text_artifact_dict = text_artifact.model_dump()
        await ctx.agent_run_repo.mark_complete(text_buddy_run.run_id, text_artifact_dict)

        await self._update_workflow_snapshot(
            ctx.repo,
            ctx.request.thread_id,
            run_id=ctx.run_id,
            current_node="text_buddy",
            current_phase="text_buddy",
            current_agent=text_buddy_name,
            latest_event="agent_completed",
            last_completed_node="text_buddy",
        )
        workflow_state = await self.state_store.get_workflow_state(ctx.request.thread_id)
        if workflow_state is not None:
            workflow_state.current_node = "text_buddy"
            workflow_state.current_phase = "text_buddy"
            workflow_state.current_agent = text_buddy_name
            workflow_state.last_completed_node = "text_buddy"
            workflow_state.updated_at = utc_now()
            await self.state_store.set_workflow_state(workflow_state)

        await publish(
            events.build(
                "agent_completed",
                agent_name=text_buddy_name,
                phase="text_buddy",
                data={"text_artifact": text_artifact_dict},
            )
        )
        # Signal text buddy completion
        await publish(
            events.build(
                "agent_log",
                agent_name=text_buddy_name,
                phase="text_buddy",
                status="completed",
                data={"message": "Content composition complete. Passing to Governance for review."},
            )
        )
        await self._complete_branch(ctx, branch_id=node_id, output_json=text_artifact_dict)

        # ── Emit answer preview before governance so frontend streams immediately ──
        # Use completion_summary (task description) not the raw artifact content.
        await publish(
            events.build(
                "answer_preview",
                agent_name=text_buddy_name,
                phase="text_buddy",
                status="running",
                data={
                    "content": text_artifact.completion_summary or (
                        f"I've composed a {ctx.plan.artifact_family.value.replace('_', ' ')} for your request. "
                        "The artifact is ready in the preview panel."
                    ),
                    "artifact_family": ctx.plan.artifact_family.value,
                    "governance_pending": True,
                },
            )
        )

        # ── Governance review of the text artifact ──
        governance_branch_id = "governance"
        governance_name = self._assigned_agent_name(ctx, governance_branch_id, "governance")
        await self._set_branch(
            ctx,
            branch_id=governance_branch_id,
            agent_name=governance_name,
            branch_kind="governance",
            status="running",
            current_phase="governance",
            input_json={"artifact_id": text_artifact.artifact_id, "evidence_refs": text_artifact.evidence_refs},
        )
        governance_run = await ctx.agent_run_repo.create_run(
            thread_id=ctx.request.thread_id,
            tenant_id=ctx.request.tenant_id,
            agent_name=governance_name,
            agent_type=AgentType.governance.value,
            branch_id=governance_branch_id,
            input_json={"artifact_id": text_artifact.artifact_id, "evidence_refs": text_artifact.evidence_refs},
        )
        await publish(events.build("governance_started", agent_name=governance_name, phase="governance"))
        _, governance_agent = self._resolve_runtime_agent(ctx, governance_branch_id, "governance")
        await self._maybe_set_log_sink(governance_agent, _make_agent_log_sink(events, publish, governance_name, "governance", "governance"))

        self.registry.mark_agent_busy(governance_name, "governance")
        self._pre_handoff_check(
            text_buddy_name,
            governance_name,
            text_artifact.model_dump(mode="json"),
            workflow_id=self._contract_workflow_id(ctx),
        )
        try:
            self._pre_dispatch_check(
                governance_name,
                {
                    "artifact": text_artifact.model_dump(mode="json"),
                    "evidence_pack": evidence.model_dump(mode="json"),
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            governance_report = (await governance_agent.review_text(text_artifact, evidence)).model_dump()
        except Exception as exc:
            logger.warning("Governance review failed for text artifact: %s", exc)
            governance_report = {"approved": True, "issues": [], "readiness_score": 0.5, "notes": [f"Governance review error: {exc}"]}
        finally:
            self.registry.mark_agent_ready(governance_name, "idle")

        await publish(events.build("governance_complete", agent_name=governance_name, phase="governance", data={"governance_report": governance_report}))
        # Signal governance completion
        await publish(
            events.build(
                "agent_log",
                agent_name=governance_name,
                phase="governance",
                status="completed",
                data={"message": "Governance review complete. Document finalized."},
            )
        )
        await ctx.agent_run_repo.mark_complete(governance_run.run_id, governance_report)
        await self._complete_branch(ctx, branch_id=governance_branch_id, output_json=governance_report)

        return WorkflowExecutionResult(
            evidence=evidence,
            final_answer=text_artifact.content,
            final_answer_display=text_artifact.completion_summary or (
                f"I've composed a {ctx.plan.artifact_family.value.replace('_', ' ')} for your request. "
                "The artifact is ready in the preview panel."
            ),
            governance_report=governance_report,
        )

    async def _maybe_block_for_requirements(
        self,
        ctx: WorkflowRunContext,
        events: EventFactory,
        publish: EventPublisher,
        *,
        evidence: EvidencePack,
        stages: set[RequirementStage],
        pending_node: str,
    ) -> WorkflowExecutionResult | None:
        missing = self._missing_requirements(ctx.plan, ctx.resume_answers, stages=stages)
        if not missing:
            return None
        stage_label = self._event_stage_label(stages)
        try:
            clarification = await self._build_clarification_prompt(
                ctx,
                missing,
                evidence,
                lambda agent_name, phase: _make_agent_log_sink(events, publish, agent_name, phase, node_id=pending_node),
            )
        except Exception:
            clarification = None
        # ── Build typed ClarificationBundle (Phase 3) ──────────────────────
        if clarification is not None:
            blocked_question = clarification.blocked_question or self._blocked_question(ctx.plan, missing)
            contract_questions = [
                ContractClarificationQuestion(
                    requirement_id=q.requirement_id,
                    question=q.question,
                    why_it_matters=q.why_it_matters,
                    answer_hint=q.answer_hint,
                    answer_options=list(q.answer_options) if hasattr(q, "answer_options") else [],
                    input_type=getattr(q, "input_type", "option"),
                    required=getattr(q, "required", True),
                )
                for q in clarification.questions
            ]
            expected_answer_schema = clarification.expected_answer_schema or {
                q.requirement_id: q.question for q in contract_questions
            }
        else:
            blocked_question = self._blocked_question(ctx.plan, missing)
            contract_questions = [
                ContractClarificationQuestion(
                    requirement_id=item.requirement_id,
                    question=item.text,
                    why_it_matters=None,
                    answer_hint=item.text,
                    input_type="text",
                    required=item.must_have,
                )
                for item in ctx.plan.requirements_checklist.items
                if item.requirement_id in missing
            ]
            expected_answer_schema = {
                item.requirement_id: item.text
                for item in ctx.plan.requirements_checklist.items
                if item.requirement_id in missing
            }

        # Typed bundle — replaces the ad-hoc blocked_question string.
        # Kept alongside legacy fields for backward compat during rollout.
        bundle = ClarificationBundle(
            headline=clarification.headline if clarification is not None else "Clarification needed",
            intro=clarification.intro if clarification is not None else "Please help fill the remaining requirements.",
            blocking_stage=stage_label,
            questions=contract_questions,
            expected_answer_schema=expected_answer_schema,
            pending_node=pending_node,
            resume_from_node=pending_node,
        )
        bundle_json = bundle.model_dump_json()

        # Legacy flat questions list — kept for existing frontend consumers.
        questions = [
            {
                "requirement_id": q.requirement_id,
                "question": q.question,
                "why_it_matters": q.why_it_matters,
                "answer_hint": q.answer_hint,
                "answer_options": q.answer_options,
                "input_type": q.input_type,
                "required": q.required,
            }
            for q in contract_questions
        ]

        await self._set_branch(
            ctx,
            branch_id=pending_node,
            agent_name="strategist",
            branch_kind="hitl",
            status="blocked",
            current_phase="planning",
            input_json={"missing_requirements": missing, "clarification_stage": stage_label},
        )
        await publish(
            events.build(
                "workflow_blocked",
                agent_name="hitl",
                phase="clarification",
                status="blocked",
                data={
                    "artifact_family": ctx.plan.artifact_family.value,
                    "clarification_stage": stage_label,
                    "prompt_headline": bundle.headline,
                    "prompt_intro": bundle.intro,
                    "blocked_question": blocked_question,
                    "questions": questions,
                    "expected_answer_schema": {"answers": expected_answer_schema},
                    "pending_node": pending_node,
                    "missing_requirements": missing,
                    # Phase 3: typed bundle for structured frontend rendering
                    "clarification_bundle": bundle.model_dump(mode="json"),
                    "clarification_bundle_id": bundle.bundle_id,
                },
            )
        )
        await self._update_workflow_snapshot(
            ctx.repo,
            ctx.request.thread_id,
            run_id=ctx.run_id,
            status=WorkflowStatus.blocked,
            current_node="hitl",
            current_phase="planning",
            current_agent="strategist",
            latest_event="workflow_blocked",
            error_message=blocked_question,
            artifact_family=ctx.plan.artifact_family.value,
            blocked_question=blocked_question,
            expected_answer_schema={"answers": expected_answer_schema},
            resume_cursor=pending_node,
            last_completed_node="research" if stage_label == "evidence_informed" else "planning",
            requirements_checklist_json=ctx.plan.requirements_checklist.model_dump_json(),
            blocked_bundle_json=bundle_json,
        )
        await self.state_store.mark_blocked(
            ctx.request.thread_id,
            blocked_question,
            blocked_question=blocked_question,
            expected_answer_schema={"answers": expected_answer_schema},
            pending_node=pending_node,
            resume_cursor=pending_node,
            last_completed_node="research" if stage_label == "evidence_informed" else "planning",
            requirements_checklist_json=ctx.plan.requirements_checklist.model_dump_json(),
            artifact_family=ctx.plan.artifact_family.value,
            blocked_bundle_json=bundle_json,
        )
        workflow_state = await self.state_store.get_workflow_state(ctx.request.thread_id)
        if workflow_state is not None:
            workflow_state.current_node = pending_node
            workflow_state.current_phase = "planning"
            workflow_state.current_agent = "strategist"
            workflow_state.status = WorkflowStatus.blocked
            workflow_state.updated_at = utc_now()
            await self.state_store.set_workflow_state(workflow_state)
        return WorkflowExecutionResult(evidence=evidence, artifact=None, governance_report=None)

    @staticmethod
    def _summarize_event_data(event: StreamEvent) -> str:
        data = event.data or {}
        if event.type == "planning_complete":
            plan = data.get("plan") or {}
            summary = str(plan.get("summary") or "").strip()
            task_count = len(plan.get("tasks") or [])
            return json.dumps(
                {
                    "workflow_mode": plan.get("workflow_mode"),
                    "summary": summary,
                    "notes": plan.get("notes") or [],
                    "task_count": task_count,
                },
                ensure_ascii=False,
            )
        if event.type in {"parallel_branch_started", "parallel_branch_completed"}:
            return json.dumps(
                {
                    "branch": data.get("branch"),
                    "branch_kind": data.get("branch_kind"),
                },
                ensure_ascii=False,
            )
        if event.type == "artifact_section_ready":
            return json.dumps(
                {
                    "section_id": data.get("section_id"),
                    "title": data.get("title"),
                },
                ensure_ascii=False,
            )
        return json.dumps(list(data.keys()), ensure_ascii=False)

    def _extract_brief_from_react(self, msg: Any) -> dict | None:
        """Try to extract a JSON ArtifactBrief from a ReActAgent response Msg."""
        from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
        # Note: LiteLLMModelResolver context should be available here
        resolver = LiteLLMModelResolver.from_settings(settings)
        
        # 1. Check metadata (if structured_output_capable was used)
        if hasattr(msg, "metadata") and msg.metadata and "artifact_brief" in msg.metadata:
            return msg.metadata["artifact_brief"]
            
        # 2. Extract from raw text
        text = msg.content if hasattr(msg, "content") else str(msg)
        try:
            raw_json = resolver.safe_json_loads(text)
            if isinstance(raw_json, dict):
                # Look for nested artifact_brief or return the whole dict if it fits
                return raw_json.get("artifact_brief") or raw_json
        except Exception:
            pass
        return None

        if event.type == "workflow_error":
            return json.dumps({"error_message": data.get("error_message")}, ensure_ascii=False)
        if event.type == "workflow_complete":
            artifact = data.get("final_artifact") or {}
            return json.dumps(
                {
                    "workflow_mode": data.get("workflow_mode"),
                    "artifact_title": artifact.get("title"),
                    "governance_status": artifact.get("governance_status"),
                },
                ensure_ascii=False,
            )
        if "message" in data:
            return json.dumps({"message": data.get("message")}, ensure_ascii=False)
        if "workflow_mode" in data:
            return json.dumps({"workflow_mode": data.get("workflow_mode")}, ensure_ascii=False)
        return json.dumps(data, ensure_ascii=False) if data else "{}"

    async def _execute_workflow(
        self,
        ctx: WorkflowRunContext,
        events: EventFactory,
        publish: EventPublisher,
        *,
        entry_event_type: str = "workflow_submitted",
        entry_data: dict[str, Any] | None = None,
        emit_initial_events: bool = True,
    ) -> WorkflowExecutionResult:
        emit_planning_replay = not ctx.resume_from_post_research_hitl
        if emit_initial_events:
            await publish(events.build(entry_event_type, phase="workflow", data=entry_data or {"workflow_mode": ctx.workflow_mode.value}))
            logger.info(
                "[workflow] planning_started thread_id=%s workflow_mode=%s artifact_family=%s",
                ctx.request.thread_id,
                ctx.workflow_mode.value,
                ctx.plan.artifact_family.value,
            )
            await publish(events.build("planning_started", agent_name="strategist", phase="planning", data={"workflow_mode": ctx.workflow_mode.value}))
        if emit_planning_replay:
            await publish(events.build("planning_complete", agent_name="strategist", phase="planning", data={"plan": ctx.plan.model_dump()}))
            logger.info(
                "[workflow] planning_complete required_sections=%s coverage_score=%.3f missing_required_ids=%s",
                list(ctx.plan.artifact_spec.required_sections) if ctx.plan.artifact_spec else [],
                ctx.plan.requirements_checklist.coverage_score,
                ctx.plan.requirements_checklist.missing_required_ids,
            )
            await self._emit_step_summary(
                events,
                publish,
                step="planning",
                phase="planning",
                summary={
                    "artifact_family": ctx.plan.artifact_family.value,
                    "required_sections": list(ctx.plan.artifact_spec.required_sections) if ctx.plan.artifact_spec else [],
                    "coverage_score": ctx.plan.requirements_checklist.coverage_score,
                    "missing_required_ids": ctx.plan.requirements_checklist.missing_required_ids,
                },
            )
            await publish(
                events.build(
                    "artifact_family_selected",
                    agent_name="strategist",
                    phase="planning",
                    data={"artifact_family": ctx.plan.artifact_family.value, "artifact_spec": ctx.plan.artifact_spec.model_dump() if ctx.plan.artifact_spec else None},
                )
            )
            await publish(events.build("requirements_check_started", agent_name="strategist", phase="planning", data={"artifact_family": ctx.plan.artifact_family.value}))
            await publish(
                events.build(
                    "requirements_check_completed",
                    agent_name="strategist",
                    phase="planning",
                    data={
                        "artifact_family": ctx.plan.artifact_family.value,
                        "requirements_checklist": ctx.plan.requirements_checklist.model_dump(),
                        "missing_requirements": ctx.plan.requirements_checklist.missing_required_ids,
                    },
                )
            )
            await self._emit_catalog_snapshot(publish, events)
        await self._update_workflow_snapshot(
            ctx.repo,
            ctx.request.thread_id,
            run_id=ctx.run_id,
            status=WorkflowStatus.running,
            current_node="planning",
            current_phase="planning",
            current_agent="strategist",
            latest_event="planning_complete",
            workflow_mode=ctx.workflow_mode,
            workflow_plan_json=ctx.plan.model_dump_json(),
            artifact_family=ctx.plan.artifact_family.value,
            requirements_checklist_json=ctx.plan.requirements_checklist.model_dump_json(),
            task_graph_json=ctx.plan.task_graph.model_dump_json(),
            pending_node="research",
            resume_cursor="research",
        )

        # Check for cancellation after planning
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (after planning)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="workflow", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        if ctx.workflow_mode == WorkflowMode.sequential:
            return await self._run_sequential(ctx, events, publish)
        if ctx.workflow_mode == WorkflowMode.parallel:
            return await self._run_parallel(ctx, events, publish)
        return await self._run_hybrid(ctx, events, publish)

    async def _run_sequential(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher) -> WorkflowExecutionResult:
        # Check for cancellation
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (in sequential phase)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="research", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        if getattr(ctx.plan, "conversational", False):
            return await self._run_conversational(ctx, events, publish)
        if ctx.plan.direct_answer:
            return await self._run_direct_answer(ctx, events, publish)
        branch_id = "sequential-research"
        research_name, _ = self._resolve_research_runtime_agent(ctx)
        skip_research = ctx.resume_answers or ctx.re_run_from_planning
        evidence = await self._load_latest_evidence(ctx.evidence_repo, ctx.request.thread_id) if skip_research else None
        if evidence is None:
            await self._set_branch(
                ctx,
                branch_id=branch_id,
                agent_name=research_name,
                branch_kind="research",
                status="running",
                current_phase="research",
                input_json={"query": ctx.request.user_query, "scope": ctx.request.source_scope},
            )
            research_run = await ctx.agent_run_repo.create_run(
                thread_id=ctx.request.thread_id,
                tenant_id=ctx.request.tenant_id,
                agent_name=research_name,
                agent_type=AgentType.research.value,
                branch_id=branch_id,
                input_json={"query": ctx.request.user_query, "scope": ctx.request.source_scope},
            )

            await publish(events.build("agent_started", agent_name=research_name, phase="research", data={"branch_id": branch_id}))
            self.registry.mark_agent_busy(research_name, "research")
            research_name, research_agent = self._resolve_research_runtime_agent(ctx)
            await self._maybe_set_log_sink(research_agent, _make_agent_log_sink(events, publish, research_name, "research", "research"))
            # Quick recall for standard mode; full tree for deep_research/finance
            quick_recall = ctx.request.analysis_mode == AnalysisMode.standard
            self._pre_handoff_check(
                "strategist",
                research_name,
                self._strategist_research_handoff(ctx),
                workflow_id=self._contract_workflow_id(ctx),
            )
            self._pre_dispatch_check(
                research_name,
                {
                    "tenant_id": ctx.request.tenant_id,
                    "query": ctx.request.user_query,
                    "source_scope": ctx.request.source_scope,
                    "quick_recall": quick_recall,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            evidence = await self._call_research_gather(
                research_agent,
                ctx.session,
                ctx.request.tenant_id,
                ctx.request.user_query,
                ctx.request.source_scope,
                quick_recall=quick_recall,
            )
            self.registry.mark_agent_ready(research_name, "idle")
            await publish(
                events.build(
                    "agent_completed",
                    agent_name=research_name,
                    phase="research",
                    data={"branch_id": branch_id, "evidence_pack": evidence.model_dump()},
                )
            )
            await self._emit_evidence_signals(publish, events, evidence)
            await ctx.agent_run_repo.mark_complete(research_run.run_id, evidence.model_dump())
            await self._complete_branch(ctx, branch_id=branch_id, output_json=evidence.model_dump())

            # Signal research completion for continuous UI flow
            await publish(
                events.build(
                    "agent_log",
                    agent_name=research_name,
                    phase="research",
                    status="completed",
                    data={"message": f"Research complete. Found {len(evidence.findings)} key findings across {len(evidence.sources)} sources."},
                )
            )

        if not ctx.resume_from_post_research_hitl:
            blocked = await self._maybe_block_for_requirements(
                ctx,
                events,
                publish,
                evidence=evidence,
                stages={RequirementStage.before_render, RequirementStage.evidence_informed},
                pending_node="hitl_evidence",
            )
            if blocked is not None:
                return blocked

        # Route to text pipeline or visual pipeline based on artifact family
        if ctx.plan.artifact_family.value in TEXT_FAMILIES:
            # Check for cancellation before text pipeline
            if self._is_cancelled(ctx.request.thread_id):
                logger.info("Workflow cancelled by user (before text_buddy phase)")
                self._clear_cancellation(ctx.request.thread_id)
                await publish(events.build("workflow_cancelled", phase="text_buddy", data={"reason": "User requested cancellation"}))
                return WorkflowExecutionResult()
            return await self._run_text_buddy_pipeline(ctx, events, publish, evidence=evidence)

        # Check for cancellation before artifact pipeline
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (before artifact pipeline)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="artifact", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        artifact_result = await self._run_react_pipeline(ctx, events, publish, evidence=evidence)
        if not artifact_result.sections_emitted:
            await self._emit_artifact_sections(ctx, events, publish, artifact_result.artifact, parallel=False)

        # Check for cancellation before governance
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (before governance phase)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="governance", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        governance = await self._review_artifact(ctx, events, publish, artifact=artifact_result.artifact, evidence=evidence)
        return WorkflowExecutionResult(evidence=evidence, artifact=artifact_result.artifact, governance_report=governance.report)

    @staticmethod
    def _format_streamable_direct_answer(answer: str, evidence: EvidencePack, question: str) -> str:
        memory_count = len(evidence.memory_findings)
        web_count = len(evidence.web_findings)
        doc_count = len(evidence.doc_findings)
        source_count = len(evidence.sources)

        analysis_lines = []
        if evidence.summary:
            analysis_lines.append(f"- Evidence summary: {evidence.summary}")
        analysis_lines.append(f"- Sources reviewed: {memory_count + web_count + doc_count} total ({memory_count} memory, {web_count} web, {doc_count} documents)")
        if evidence.provenance.primary_ground_truth:
            analysis_lines.append(f"- Primary ground truth: {evidence.provenance.primary_ground_truth}")
        if evidence.contradictions:
            analysis_lines.append(f"- Contradictions detected: {len(evidence.contradictions)}")
        if evidence.open_questions:
            analysis_lines.append(f"- Open questions: {' | '.join(evidence.open_questions[:3])}")
        if evidence.recommended_followups:
            analysis_lines.append(f"- Recommended follow-up: {evidence.recommended_followups[0]}")
        if question:
            analysis_lines.append(f"- User request: {question}")

        source_lines = []
        for source in evidence.sources[:12]:
            source_label = source.title or source.location or source.source_id
            extra_parts = [source.source_type, source.location]
            detail = ", ".join(part for part in extra_parts if part)
            if detail:
                source_lines.append(f"- [Source: {source_label}, {detail}]")
            else:
                source_lines.append(f"- [Source: {source_label}]")
        if not source_lines:
            source_lines.append("- [Source: No source list available]")

        return (
            "## Analysis\n"
            f"{chr(10).join(analysis_lines) if analysis_lines else '- Evidence assembled.'}\n\n"
            "**ANSWER**:\n"
            f"{answer.strip()}\n\n"
            "## Confidence\n"
            f"Score: {evidence.confidence:.2f}\n"
            f"Evidence Chunks: {memory_count + web_count + doc_count}\n"
            f"Source Documents: {source_count}\n\n"
            "## Sources (GraphRAG)\n"
            f"{chr(10).join(source_lines)}\n"
        )

    async def _run_conversational(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher) -> WorkflowExecutionResult:
        """Handle conversational messages directly — fast LLM call, no text_buddy overhead."""
        from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

        fallback = "Hello! I'm BLAIQ — your AI research and content assistant. How can I help you today?"
        await publish(events.build("agent_started", agent_name="BLAIQ-CORE", phase="conversational"))

        prior_context_text = format_prior_context(ctx.prior_turns, max_total_chars=1500)
        system_prompt = (
            "You are BLAIQ, a sharp and capable AI assistant. "
            "Respond naturally — warm, direct, and concise. "
            "No markdown headers or bullet lists for greetings or chitchat. "
            "Keep greetings to 1-2 sentences. For capability questions, be specific and confident."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        user_content = ctx.request.user_query
        if prior_context_text:
            user_content = f"[Prior context]\n{prior_context_text}\n\n{user_content}"
        messages.append({"role": "user", "content": user_content})

        answer = fallback
        try:
            resolver = LiteLLMModelResolver.from_settings(settings)
            response = await resolver.acompletion("routing", messages, max_tokens=300)
            answer = (response.choices[0].message.content or "").strip() or fallback
        except Exception as exc:
            logger.warning("Conversational direct LLM call failed: %s", exc)
        finally:
            await publish(events.build("agent_completed", agent_name="BLAIQ-CORE", phase="conversational"))

        return WorkflowExecutionResult(
            final_answer=answer,
            final_answer_display=answer,
        )

    async def _run_direct_answer(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher) -> WorkflowExecutionResult:
        branch_id = "research-answer"
        research_name, direct_research_agent = self._resolve_research_runtime_agent(ctx)

        # On resume (user answered depth question), load saved evidence — don't re-research
        evidence = None
        if ctx.resume_answers:
            evidence = await self._load_latest_evidence(ctx.evidence_repo, ctx.request.thread_id)

        if evidence is None:
            await self._set_branch(
                ctx,
                branch_id=branch_id,
                agent_name=research_name,
                branch_kind="research",
                status="running",
                current_phase="research",
                input_json={"query": ctx.request.user_query, "scope": ctx.request.source_scope, "response_mode": "direct_answer"},
            )
            research_run = await ctx.agent_run_repo.create_run(
                thread_id=ctx.request.thread_id,
                tenant_id=ctx.request.tenant_id,
                agent_name=research_name,
                agent_type=AgentType.research.value,
                branch_id=branch_id,
                input_json={"query": ctx.request.user_query, "scope": ctx.request.source_scope, "response_mode": "direct_answer"},
            )
            await publish(events.build("agent_started", agent_name=research_name, phase="research", data={"branch_id": branch_id}))
            self.registry.mark_agent_busy(research_name, "research")
            await self._maybe_set_log_sink(direct_research_agent, _make_agent_log_sink(events, publish, research_name, "research", "research"))
            # Quick recall for standard mode; full tree for deep_research/finance
            quick_recall = ctx.request.analysis_mode == AnalysisMode.standard
            self._pre_handoff_check(
                "strategist",
                research_name,
                self._strategist_research_handoff(ctx),
                workflow_id=self._contract_workflow_id(ctx),
            )
            self._pre_dispatch_check(
                research_name,
                {
                    "tenant_id": ctx.request.tenant_id,
                    "query": ctx.request.user_query,
                    "source_scope": ctx.request.source_scope,
                    "quick_recall": quick_recall,
                    "response_mode": "direct_answer",
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            evidence = await self._call_research_gather(
                direct_research_agent,
                ctx.session,
                ctx.request.tenant_id,
                ctx.request.user_query,
                ctx.request.source_scope,
                quick_recall=quick_recall,
            )
            await publish(
                events.build(
                    "agent_completed",
                    agent_name=research_name,
                    phase="research",
                    data={"branch_id": branch_id, "evidence_pack": evidence.model_dump()},
                )
            )
            await self._emit_evidence_signals(publish, events, evidence)
            self.registry.mark_agent_ready(research_name, "idle")
            await ctx.agent_run_repo.mark_complete(research_run.run_id, evidence.model_dump())

        source_count = len(evidence.memory_findings) + len(evidence.web_findings) + len(evidence.doc_findings)
        # Skip HITL depth question for direct_answer — auto-select depth based on source count
        skip_hitl_depth = getattr(ctx.plan, "direct_answer", False)
        if skip_hitl_depth and not ctx.resume_answers:
            # Auto-set depth: brief for ≤3 sources, detailed for more
            if source_count <= 3:
                ctx.resume_answers = {"field:response_depth": "Brief executive answer"}
            else:
                ctx.resume_answers = {"field:response_depth": f"Detailed product summary — cover all {source_count} sources"}
            logger.info("direct_answer: auto-selected depth for %d sources, skipping HITL", source_count)
        if not ctx.resume_answers and source_count > 0:
            from agentscope_blaiq.agents.backup.clarification import ClarificationPrompt, ClarificationQuestion

            depth_question = ClarificationQuestion(
                requirement_id="field:response_depth",
                question=f"I found {source_count} sources. How detailed should the response be?",
                why_it_matters="This controls how long and how detailed the final answer should be.",
                answer_hint="Choose a response depth",
                answer_options=[
                    f"Detailed product summary — cover all {source_count} sources with product families, counts, and specifics",
                    "Full technical breakdown — 3-5 paragraphs with deeper product and system detail",
                    "Brief executive answer — 1-2 paragraphs with the shortest useful response",
                ],
            )
            hitl_prompt = ClarificationPrompt(
                headline=f"Found {source_count} sources — how detailed?",
                intro="The research is complete. Choose how thorough the final answer should be before I synthesize it.",
                questions=[depth_question],
                blocked_question=depth_question.question,
                expected_answer_schema={"field:response_depth": depth_question.question},
            )
            blocked_question = hitl_prompt.blocked_question
            expected_schema = {"answers": hitl_prompt.expected_answer_schema}

            await ctx.evidence_repo.save(ctx.request.thread_id, ctx.request.tenant_id, str(uuid4()), evidence)
            await self._update_workflow_snapshot(
                ctx.repo,
                ctx.request.thread_id,
                run_id=ctx.run_id,
                status=WorkflowStatus.blocked,
                current_node="hitl_depth",
                current_phase="clarification",
                current_agent="hitl",
                latest_event="workflow_blocked",
                error_message=blocked_question,
                blocked_question=blocked_question,
                expected_answer_schema=expected_schema,
                resume_cursor="hitl_depth",
                last_completed_node="research",
            )
            await self.state_store.mark_blocked(
                ctx.request.thread_id,
                blocked_question,
                blocked_question=blocked_question,
                expected_answer_schema=expected_schema,
                pending_node="hitl_depth",
                resume_cursor="hitl_depth",
                last_completed_node="research",
                artifact_family="custom",
            )
            workflow_state = await self.state_store.get_workflow_state(ctx.request.thread_id)
            if workflow_state is not None:
                workflow_state.current_node = "hitl_depth"
                workflow_state.current_phase = "clarification"
                workflow_state.current_agent = "hitl"
                workflow_state.status = WorkflowStatus.blocked
                workflow_state.updated_at = utc_now()
                await self.state_store.set_workflow_state(workflow_state)

            await publish(
                events.build(
                    "workflow_blocked",
                    agent_name="hitl",
                    phase="clarification",
                    status="blocked",
                    data={
                        "artifact_family": "custom",
                        "clarification_stage": "response_depth",
                        "prompt_headline": hitl_prompt.headline,
                        "prompt_intro": hitl_prompt.intro,
                        "blocked_question": blocked_question,
                        "questions": [q.model_dump() for q in hitl_prompt.questions],
                        "expected_answer_schema": expected_schema,
                        "pending_node": "hitl_depth",
                        "missing_requirements": ["field:response_depth"],
                    },
                )
            )
            return WorkflowExecutionResult(evidence=evidence)

        # ── Final text synthesis uses text_buddy (deep_research stays evidence-only) ──
        depth_answer = (ctx.resume_answers or {}).get("field:response_depth", "")
        prior_context_text = format_prior_context(ctx.prior_turns, max_total_chars=1500)
        text_buddy_name, text_buddy = self._resolve_runtime_agent(ctx, "text_buddy", "text_buddy")
        await self._maybe_set_log_sink(
            text_buddy,
            _make_agent_log_sink(events, publish, text_buddy_name, "conversational", "text_buddy"),
        )
        await publish(events.build("agent_started", agent_name=text_buddy_name, phase="conversational"))
        self.registry.mark_agent_busy(text_buddy_name, "text_buddy")
        try:
            self._pre_handoff_check(
                research_name,
                text_buddy_name,
                {
                    "artifact_family": "summary",
                    "evidence_pack": evidence.model_dump(mode="json"),
                    "user_query": ctx.request.user_query,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            self._pre_dispatch_check(
                text_buddy_name,
                {
                    "user_query": ctx.request.user_query,
                    "artifact_family": "summary",
                    "evidence_pack": evidence.model_dump(mode="json"),
                    "hitl_answers": ctx.resume_answers,
                    "brand_voice": self._load_brand_voice_text(ctx.request.tenant_id),
                    "tenant_id": ctx.request.tenant_id,
                    "prior_context": prior_context_text,
                    "response_depth": depth_answer or None,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            text_artifact = await text_buddy.compose(
                user_query=ctx.request.user_query,
                artifact_family="summary",
                evidence_pack=evidence,
                hitl_answers=ctx.resume_answers,
                brand_voice=self._load_brand_voice_text(ctx.request.tenant_id),
                tenant_id=ctx.request.tenant_id,
                prior_context=prior_context_text,
            )
            final_answer = (text_artifact.content or "").strip()
            if not final_answer:
                final_answer = evidence.summary or "; ".join(f.summary for f in evidence.memory_findings[:5])
        except Exception as exc:
            logger.exception("Direct-answer text_buddy synthesis failed: %s", exc)
            final_answer = evidence.summary or "; ".join(f.summary for f in evidence.memory_findings[:5])
        finally:
            self.registry.mark_agent_ready(text_buddy_name, "idle")
            await publish(events.build("agent_completed", agent_name=text_buddy_name, phase="conversational"))

        final_answer_display = self._format_streamable_direct_answer(final_answer, evidence, ctx.request.user_query)

        await self._complete_branch(
            ctx,
            branch_id=branch_id,
            output_json={
                "final_answer": final_answer,
                "final_answer_display": final_answer_display,
            },
        )
        return WorkflowExecutionResult(evidence=evidence, final_answer=final_answer, final_answer_display=final_answer_display)

    async def _run_parallel(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher) -> WorkflowExecutionResult:
        # Check for cancellation
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (in parallel phase)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="research", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        skip_research = ctx.resume_answers or ctx.re_run_from_planning
        merged_evidence = await self._load_latest_evidence(ctx.evidence_repo, ctx.request.thread_id) if skip_research else None
        branch_ids = ["research-web", "research-docs"]
        replay_research_merge = not (ctx.resume_from_post_research_hitl and merged_evidence is not None)
        if merged_evidence is None:
            branch_jobs = [
                asyncio.create_task(self._research_branch(ctx, events, publish, branch_kind="web")),
                asyncio.create_task(self._research_branch(ctx, events, publish, branch_kind="docs")),
            ]

            results: list[BranchResult] = []
            for task in asyncio.as_completed(branch_jobs):
                results.append(await task)

            if any(result.error_message for result in results):
                raise RuntimeError("; ".join(result.error_message for result in results if result.error_message))

            merged_evidence = self._merge_evidence(*(result.evidence for result in results if result.evidence is not None))
            branch_ids = [result.branch_id for result in results]
        if replay_research_merge:
            await publish(
                events.build(
                    "fanin_started",
                    agent_name="strategist",
                    phase="fanin",
                    data={"branches": branch_ids},
                )
            )
            await publish(events.build("fanin_completed", agent_name="strategist", phase="fanin", data={"evidence_pack": merged_evidence.model_dump()}))
            await self._emit_evidence_signals(publish, events, merged_evidence)

        if not ctx.resume_from_post_research_hitl:
            blocked = await self._maybe_block_for_requirements(
                ctx,
                events,
                publish,
                evidence=merged_evidence,
                stages={RequirementStage.before_render, RequirementStage.evidence_informed},
                pending_node="hitl_evidence",
            )
            if blocked is not None:
                return blocked

        # Route to text pipeline or visual pipeline based on artifact family
        if ctx.plan.artifact_family.value in TEXT_FAMILIES:
            # Check for cancellation before text pipeline
            if self._is_cancelled(ctx.request.thread_id):
                logger.info("Workflow cancelled by user (before text_buddy phase in parallel)")
                self._clear_cancellation(ctx.request.thread_id)
                await publish(events.build("workflow_cancelled", phase="text_buddy", data={"reason": "User requested cancellation"}))
                return WorkflowExecutionResult()
            # Pre-synthesis emphasis gate
            blocked = await self._maybe_block_for_requirements(
                ctx, events, publish, evidence=merged_evidence,
                stages={RequirementStage.before_synthesis},
                pending_node="hitl_pre_synthesis",
            )
            if blocked is not None: return blocked
            return await self._run_text_buddy_pipeline(ctx, events, publish, evidence=merged_evidence)

        # Check for cancellation before artifact pipeline
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (before artifact pipeline in parallel)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="artifact", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        artifact_result = await self._run_react_pipeline(ctx, events, publish, evidence=merged_evidence)
        if not artifact_result.sections_emitted:
            await self._emit_artifact_sections(ctx, events, publish, artifact_result.artifact, parallel=True)

        # Check for cancellation before governance
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (before governance phase in parallel)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="governance", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        governance = await self._review_artifact(ctx, events, publish, artifact=artifact_result.artifact, evidence=merged_evidence)
        return WorkflowExecutionResult(evidence=merged_evidence, artifact=artifact_result.artifact, governance_report=governance.report)

    async def _run_hybrid(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher) -> WorkflowExecutionResult:
        # Check for cancellation
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (in hybrid phase)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="research", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        skip_research = ctx.resume_answers or ctx.re_run_from_planning
        merged_evidence = await self._load_latest_evidence(ctx.evidence_repo, ctx.request.thread_id) if skip_research else None
        branch_ids = ["research-web", "research-docs"]
        replay_research_merge = not (ctx.resume_from_post_research_hitl and merged_evidence is not None)
        if merged_evidence is None:
            branch_jobs = [
                asyncio.create_task(self._research_branch(ctx, events, publish, branch_kind="web")),
                asyncio.create_task(self._research_branch(ctx, events, publish, branch_kind="docs")),
            ]

            results: list[BranchResult] = []
            for task in asyncio.as_completed(branch_jobs):
                results.append(await task)

            if any(result.error_message for result in results):
                raise RuntimeError("; ".join(result.error_message for result in results if result.error_message))

            merged_evidence = self._merge_evidence(*(result.evidence for result in results if result.evidence is not None))
            branch_ids = [result.branch_id for result in results]
        if replay_research_merge:
            await publish(
                events.build(
                    "fanin_started",
                    agent_name="strategist",
                    phase="fanin",
                    data={"branches": branch_ids},
                )
            )
            await publish(events.build("fanin_completed", agent_name="strategist", phase="fanin", data={"evidence_pack": merged_evidence.model_dump()}))
            await self._emit_evidence_signals(publish, events, merged_evidence)

        if not ctx.resume_from_post_research_hitl:
            blocked = await self._maybe_block_for_requirements(
                ctx,
                events,
                publish,
                evidence=merged_evidence,
                stages={
                    RequirementStage.before_render, 
                    RequirementStage.before_storyboard,
                    RequirementStage.evidence_informed
                },
                pending_node="hitl_post_research",
            )
            if blocked is not None:
                return blocked

        # Route to text pipeline or visual pipeline based on artifact family
        if ctx.plan.artifact_family.value in TEXT_FAMILIES:
            # Check for cancellation before text pipeline
            if self._is_cancelled(ctx.request.thread_id):
                logger.info("Workflow cancelled by user (before text_buddy phase in hybrid)")
                self._clear_cancellation(ctx.request.thread_id)
                await publish(events.build("workflow_cancelled", phase="text_buddy", data={"reason": "User requested cancellation"}))
                return WorkflowExecutionResult()
            # Pre-synthesis emphasis gate
            blocked = await self._maybe_block_for_requirements(
                ctx, events, publish, evidence=merged_evidence,
                stages={RequirementStage.before_synthesis},
                pending_node="hitl_pre_synthesis",
            )
            if blocked is not None: return blocked
            return await self._run_text_buddy_pipeline(ctx, events, publish, evidence=merged_evidence)

        # Check for cancellation before artifact pipeline
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (before artifact pipeline in hybrid)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="artifact", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        artifact_result = await self._run_react_pipeline(ctx, events, publish, evidence=merged_evidence)
        if not artifact_result.sections_emitted:
            await self._emit_artifact_sections(ctx, events, publish, artifact_result.artifact, parallel=True)

        # Check for cancellation before governance
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (before governance phase in hybrid)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="governance", data={"reason": "User requested cancellation"}))
            return WorkflowExecutionResult()

        governance = await self._review_artifact(ctx, events, publish, artifact=artifact_result.artifact, evidence=merged_evidence)
        return WorkflowExecutionResult(evidence=merged_evidence, artifact=artifact_result.artifact, governance_report=governance.report)

    async def _research_branch(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher, branch_kind: str) -> BranchResult:
        branch_id = f"research-{branch_kind}"
        research_name = self._assigned_agent_name(ctx, "research", "research")
        await self._set_branch(
            ctx,
            branch_id=branch_id,
            agent_name=research_name,
            branch_kind=branch_kind,
            status="running",
            current_phase="research",
            input_json={"query": ctx.request.user_query, "scope": branch_kind},
        )
        result = BranchResult(branch_id=branch_id)
        if isinstance(ctx.session, AsyncSession):
            branch_session_cm = ctx.session_factory()
        else:
            branch_session_cm = _PassthroughAsyncContext(ctx.session)

        async with branch_session_cm as branch_session:
            branch_agent_run_repo = AgentRunRepository(branch_session)
            async with ctx.persistence_lock:
                agent_run = await branch_agent_run_repo.create_run(
                    thread_id=ctx.request.thread_id,
                    tenant_id=ctx.request.tenant_id,
                    agent_name=research_name,
                    agent_type=AgentType.research.value,
                    branch_id=branch_id,
                    input_json={"query": ctx.request.user_query, "scope": branch_kind},
                )
            try:
                await publish(
                    events.build(
                        "parallel_branch_started",
                        agent_name=research_name,
                        phase="research",
                        data={"branch": branch_id, "branch_kind": branch_kind},
                    )
                )
                scope = "web" if branch_kind == "web" else "docs"
                research_name, branch_research_agent = self._resolve_research_runtime_agent(ctx)
                await self._maybe_set_log_sink(branch_research_agent, _make_agent_log_sink(events, publish, research_name, "research", "research"))
                # Quick recall for standard mode; full tree for deep_research/finance
                quick_recall = ctx.request.analysis_mode == AnalysisMode.standard
                self._pre_handoff_check(
                    "strategist",
                    research_name,
                    self._strategist_research_handoff(ctx),
                    workflow_id=self._contract_workflow_id(ctx),
                )
                self._pre_dispatch_check(
                    research_name,
                    {
                        "tenant_id": ctx.request.tenant_id,
                        "query": ctx.request.user_query,
                        "source_scope": scope,
                        "quick_recall": quick_recall,
                    },
                    workflow_id=self._contract_workflow_id(ctx),
                )
                evidence = await self._call_research_gather(
                    branch_research_agent,
                    branch_session,
                    ctx.request.tenant_id,
                    ctx.request.user_query,
                    scope,
                    quick_recall=quick_recall,
                )
                result.evidence = evidence
                await publish(
                    events.build(
                        "parallel_branch_completed",
                        agent_name=research_name,
                        phase="research",
                        data={"branch": branch_id, "branch_kind": branch_kind, "evidence_pack": evidence.model_dump()},
                    )
                )
                async with ctx.persistence_lock:
                    await branch_agent_run_repo.mark_complete(agent_run.run_id, evidence.model_dump())
                await self._complete_branch(ctx, branch_id=branch_id, output_json=evidence.model_dump())
                return result
            except Exception as exc:
                result.error_message = str(exc)
                async with ctx.persistence_lock:
                    await branch_agent_run_repo.mark_failed(agent_run.run_id, str(exc))
                await self._fail_branch(ctx, branch_id=branch_id, error_message=str(exc))
                return result

    async def _run_react_pipeline(
        self,
        ctx: WorkflowRunContext,
        events: EventFactory,
        publish: EventPublisher,
        *,
        evidence: EvidencePack,
    ) -> "_ArtifactOutcome":
        """New React+shadcn pipeline: plan_slides -> generate_from_slides."""
        # Check for cancellation at pipeline entry
        if self._is_cancelled(ctx.request.thread_id):
            logger.info("Workflow cancelled by user (react_pipeline start)")
            self._clear_cancellation(ctx.request.thread_id)
            await publish(events.build("workflow_cancelled", phase="artifact", data={"reason": "User requested cancellation"}))
            return _ArtifactOutcome()

        # 1. Load Brand DNA
        brand_dna = await self._load_brand_dna(ctx.request.tenant_id)

        # 2. Content Director: plan_slides (fallback to plan_content for older interfaces/tests)
        node_id = "content_director"
        content_director_name = self._assigned_agent_name(ctx, node_id, "content_director")
        await self._set_branch(
            ctx,
            branch_id=node_id,
            agent_name=content_director_name,
            branch_kind="content_director",
            status="running",
            current_phase="content_director",
            input_json={
                "artifact_family": ctx.plan.artifact_family.value,
                "pipeline": "react_slides",
            },
        )
        await publish(
            events.build(
                "content_director_started",
                agent_name=content_director_name,
                phase="content_director",
                data={"artifact_family": ctx.plan.artifact_family.value, "node_id": node_id, "pipeline": "react_slides"},
            )
        )
        logger.info(
            "[workflow] content_director_started artifact_family=%s node_id=%s pipeline=%s",
            ctx.plan.artifact_family.value,
            node_id,
            "react_slides",
        )
        content_director_name, content_director = self._resolve_runtime_agent(ctx, node_id, "content_director")
        await self._maybe_set_log_sink(content_director, _make_agent_log_sink(events, publish, content_director_name, "content_director", node_id))
        self.registry.mark_agent_busy(content_director_name, "content_director")
        user_query_with_context = ctx.request.user_query
        if ctx.prior_turns:
            prior_summary = format_prior_context(ctx.prior_turns, max_total_chars=1000)
            if prior_summary:
                user_query_with_context = (
                    f"=== PRIOR CONVERSATION CONTEXT (Reference Only) ===\n{prior_summary}\n"
                    f"=== END PRIOR CONTEXT ===\n\n"
                    f"Current request: {ctx.request.user_query}"
                )
        self._pre_handoff_check(
            "research",
            content_director_name,
            {"evidence_pack": evidence.model_dump(mode="json")},
            workflow_id=self._contract_workflow_id(ctx),
        )
        if hasattr(content_director, "plan_slides"):
            self._pre_dispatch_check(
                content_director_name,
                {
                    "user_query": user_query_with_context,
                    "artifact_family": ctx.plan.artifact_family.value,
                    "evidence_pack": evidence.model_dump(mode="json"),
                    "hitl_answers": ctx.resume_answers,
                    "brand_dna": brand_dna,
                    "tenant_id": ctx.request.tenant_id,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            slides_data = await content_director.plan_slides(
                user_query=user_query_with_context,
                artifact_family=ctx.plan.artifact_family.value,
                evidence_pack=evidence,
                hitl_answers=ctx.resume_answers,
                brand_dna=brand_dna,
                tenant_id=ctx.request.tenant_id,
                required_sections=(ctx.plan.artifact_spec.required_sections if ctx.plan.artifact_spec else None),
            )
            slides_dict = slides_data.model_dump()
        else:
            self._pre_dispatch_check(
                content_director_name,
                {
                    "user_query": ctx.request.user_query,
                    "evidence_summary": evidence.summary,
                    "artifact_spec": ctx.plan.artifact_spec.model_dump(mode="json") if ctx.plan.artifact_spec else None,
                    "requirements": ctx.plan.requirements_checklist.model_dump(mode="json"),
                    "hitl_answers": ctx.resume_answers,
                    "evidence_pack": evidence.model_dump(mode="json"),
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            slides_data = await content_director.plan_content(
                user_query=ctx.request.user_query,
                evidence_summary=evidence.summary,
                artifact_spec=ctx.plan.artifact_spec,
                requirements=ctx.plan.requirements_checklist,
                hitl_answers=ctx.resume_answers,
                evidence_pack=evidence,
            )
            slides_dict = slides_data.model_dump()
        await self._update_workflow_snapshot(
            ctx.repo,
            ctx.request.thread_id,
            run_id=ctx.run_id,
            current_node="content_director",
            current_phase="content_director",
            current_agent=content_director_name,
            latest_event="content_director_completed",
            content_director_output_json=json.dumps(slides_dict, default=str),
            last_completed_node="content_director",
        )
        workflow_state = await self.state_store.get_workflow_state(ctx.request.thread_id)
        if workflow_state is not None:
            workflow_state.current_node = "content_director"
            workflow_state.current_phase = "content_director"
            workflow_state.current_agent = content_director_name
            workflow_state.content_director_output_json = json.dumps(slides_dict, default=str)
            workflow_state.last_completed_node = "content_director"
            workflow_state.updated_at = utc_now()
            await self.state_store.set_workflow_state(workflow_state)
        await publish(
            events.build(
                "content_director_completed",
                agent_name=content_director_name,
                phase="content_director",
                data={"slides_data": slides_dict},
            )
        )
        logger.info(
            "[workflow] content_director_completed slide_count=%d slide_titles=%s has_followup_research=%s",
            len(slides_dict.get("slides", [])) if isinstance(slides_dict, dict) else 0,
            [
                str(slide.get("headline") or slide.get("title") or f"Slide {index + 1}")
                for index, slide in enumerate(slides_dict.get("slides", []))
                if isinstance(slide, dict)
            ] if isinstance(slides_dict, dict) else [],
            bool(self._extract_slide_followup_requests(slides_dict)),
        )
        await self._emit_step_summary(
            events,
            publish,
            step="content_director",
            phase="content_director",
            summary={
                "slide_count": len(slides_dict.get("slides", [])) if isinstance(slides_dict, dict) else 0,
                "slide_titles": [
                    str(slide.get("headline") or slide.get("title") or f"Slide {index + 1}")
                    for index, slide in enumerate(slides_dict.get("slides", []))
                    if isinstance(slide, dict)
                ] if isinstance(slides_dict, dict) else [],
                "has_followup_research": bool(self._extract_slide_followup_requests(slides_dict)),
            },
        )
        await publish(
            events.build(
                "artifact_blueprint_ready",
                agent_name=content_director_name,
                phase="content_director",
                data={
                    "artifact_family": ctx.plan.artifact_family.value,
                    "slide_count": len(slides_dict.get("slides", []) if isinstance(slides_dict, dict) else []),
                    "slide_titles": [
                        str(slide.get("headline") or slide.get("title") or f"Slide {index + 1}")
                        for index, slide in enumerate(slides_dict.get("slides", []))
                        if isinstance(slide, dict)
                    ],
                },
            )
        )
        self.registry.mark_agent_ready(content_director_name, "idle")
        await self._complete_branch(ctx, branch_id=node_id, output_json=slides_dict)

        followup_requests = self._extract_slide_followup_requests(slides_dict)
        if followup_requests:
            followup_name, followup_agent = self._resolve_research_runtime_agent(ctx)
            self.registry.mark_agent_busy(followup_name, "research")
            await publish(
                events.build(
                    "content_director_followup_research_started",
                    agent_name=followup_name,
                    phase="research",
                    data={
                        "group_count": len(followup_requests),
                        "slide_titles": [item.get("slide_title") for item in followup_requests],
                        "mode": "per_slide_parallel",
                    },
                )
            )
            logger.info(
                "[workflow] followup_research_started group_count=%d slide_titles=%s mode=%s",
                len(followup_requests),
                [item.get("slide_title") for item in followup_requests],
                "per_slide_parallel",
            )
            followup_evidences: list[EvidencePack] = []
            try:
                async def _run_slide_recall(item: dict[str, Any]) -> tuple[str, EvidencePack]:
                    query = self._format_followup_research_query(ctx.request.user_query, item)
                    async with ctx.session_factory() as followup_session:
                        evidence_pack = await self._call_research_gather(
                            followup_agent,
                            followup_session,
                            ctx.request.tenant_id,
                            query,
                            ctx.request.source_scope,
                            quick_recall=True,
                        )
                    return str(item.get("slide_title") or "Slide"), evidence_pack

                tasks = [
                    asyncio.create_task(_run_slide_recall(item))
                    for item in followup_requests[:6]
                ]
                for task in asyncio.as_completed(tasks):
                    slide_title, evidence_pack = await task
                    followup_evidences.append(evidence_pack)
                    logger.info(
                        "[workflow] followup_research_slide_completed slide_title=%s evidence_confidence=%.3f",
                        slide_title,
                        evidence_pack.confidence,
                    )
                    await publish(
                        events.build(
                            "content_director_slide_research_completed",
                            agent_name=followup_name,
                            phase="research",
                            data={
                                "slide_title": slide_title,
                                "evidence_confidence": evidence_pack.confidence,
                            },
                        )
                    )
            finally:
                self.registry.mark_agent_ready(followup_name, "idle")
            if followup_evidences:
                evidence = self._merge_evidence(evidence, *followup_evidences)
                await publish(
                    events.build(
                        "content_director_followup_research_completed",
                        agent_name=followup_name,
                        phase="research",
                        data={
                            "group_count": len(followup_requests),
                            "merged_evidence": evidence.model_dump(),
                        },
                    )
                )
                logger.info(
                    "[workflow] followup_research_completed group_count=%d merged_confidence=%.3f",
                    len(followup_requests),
                    evidence.confidence,
                )
                await self._emit_step_summary(
                    events,
                    publish,
                    step="followup_research",
                    phase="research",
                    summary={
                        "group_count": len(followup_requests),
                        "slide_titles": [item.get("slide_title") for item in followup_requests],
                        "confidence": evidence.confidence,
                    },
                )

        # 3. Vangogh: generate_from_slides (React bundle pipeline)
        branch_id = "artifact"
        vangogh_name = self._assigned_agent_name(ctx, "vangogh", "vangogh")
        await self._set_branch(
            ctx,
            branch_id=branch_id,
            agent_name=vangogh_name,
            branch_kind="artifact",
            status="running",
            current_phase="artifact",
            input_json={"user_query": ctx.request.user_query, "pipeline": "react_bundle"},
        )
        agent_run = await ctx.agent_run_repo.create_run(
            thread_id=ctx.request.thread_id,
            tenant_id=ctx.request.tenant_id,
            agent_name=vangogh_name,
            agent_type=AgentType.vangogh.value,
            branch_id=branch_id,
            input_json={"user_query": ctx.request.user_query, "pipeline": "react_bundle"},
        )
        await publish(events.build("artifact_started", agent_name=vangogh_name, phase="artifact", data={"branch": branch_id, "pipeline": "react_bundle"}))
        logger.info(
            "[workflow] artifact_render_started branch=%s pipeline=%s",
            branch_id,
            "react_bundle",
        )
        vangogh_name, vangogh_agent = self._resolve_runtime_agent(ctx, "vangogh", "vangogh")
        self.registry.mark_agent_busy(vangogh_name, "artifact")
        await self._maybe_set_log_sink(vangogh_agent, _make_agent_log_sink(events, publish, vangogh_name, "artifact", "vangogh"))

        self._pre_handoff_check(
            "content_director",
            vangogh_name,
            slides_dict,
            workflow_id=self._contract_workflow_id(ctx),
        )
        if hasattr(vangogh_agent, "generate_from_slides"):
            self._pre_dispatch_check(
                vangogh_name,
                {
                    "slides_data": slides_dict,
                    "user_query": ctx.request.user_query,
                    "evidence_pack": evidence.model_dump(mode="json"),
                    "brand_dna": brand_dna,
                    "artifact_family": ctx.plan.artifact_family.value,
                    "tenant_id": ctx.request.tenant_id,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            artifact = await vangogh_agent.generate_from_slides(
                slides_data=slides_dict,
                user_query=ctx.request.user_query,
                evidence=evidence,
                brand_dna=brand_dna,
                artifact_family=ctx.plan.artifact_family.value,
                tenant_id=ctx.request.tenant_id,
            )
        else:
            self._pre_dispatch_check(
                vangogh_name,
                {
                    "user_query": ctx.request.user_query,
                    "evidence_pack": evidence.model_dump(mode="json"),
                    "content_brief": slides_dict,
                    "brand_dna": brand_dna,
                },
                workflow_id=self._contract_workflow_id(ctx),
            )
            artifact = await vangogh_agent.generate(
                user_query=ctx.request.user_query,
                evidence=evidence,
                content_brief=slides_dict,
                brand_dna=brand_dna,
            )
        self.registry.mark_agent_ready(vangogh_name, "idle")
        await publish(
            events.build(
                "artifact_ready",
                agent_name=vangogh_name,
                phase="artifact",
                data={"artifact_manifest": artifact.model_dump(exclude={"html", "css"}), "pipeline": "react_bundle"},
            )
        )
        logger.info(
            "[workflow] artifact_render_completed artifact_id=%s section_count=%d evidence_ref_count=%d",
            artifact.artifact_id,
            len(artifact.sections),
            len(artifact.evidence_refs),
        )
        await self._emit_step_summary(
            events,
            publish,
            step="artifact_render",
            phase="artifact",
            summary={
                "artifact_id": artifact.artifact_id,
                "section_count": len(artifact.sections),
                "evidence_ref_count": len(artifact.evidence_refs),
            },
        )
        await ctx.agent_run_repo.mark_complete(agent_run.run_id, artifact.model_dump())
        await self._complete_branch(ctx, branch_id=branch_id, output_json=artifact.model_dump())

        return WorkflowEngine._ArtifactOutcome(artifact=artifact, sections_emitted=False)

    @dataclass
    class _ArtifactOutcome:
        artifact: VisualArtifact
        sections_emitted: bool = False

    @dataclass
    class _GovernanceOutcome:
        report: dict[str, Any]

    async def _generate_artifact(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher, evidence: EvidencePack, content_brief: dict[str, Any] | None = None) -> _ArtifactOutcome:
        branch_id = "artifact"
        vangogh_name, vangogh_agent = self._resolve_runtime_agent(ctx, "vangogh", "vangogh")
        await self._set_branch(
            ctx,
            branch_id=branch_id,
            agent_name=vangogh_name,
            branch_kind="artifact",
            status="running",
            current_phase="artifact",
            input_json={"user_query": ctx.request.user_query, "evidence_summary": evidence.summary},
        )
        agent_run = await ctx.agent_run_repo.create_run(
            thread_id=ctx.request.thread_id,
            tenant_id=ctx.request.tenant_id,
            agent_name=vangogh_name,
            agent_type=AgentType.vangogh.value,
            branch_id=branch_id,
            input_json={"user_query": ctx.request.user_query, "evidence_summary": evidence.summary},
        )

        await publish(events.build("artifact_started", agent_name=vangogh_name, phase="artifact", data={"branch": branch_id}))
        self.registry.mark_agent_busy(vangogh_name, "artifact")
        await self._maybe_set_log_sink(vangogh_agent, _make_agent_log_sink(events, publish, vangogh_name, "artifact", "vangogh"))

        _section_emitted_count = 0

        async def _on_section_ready(section: ArtifactSection) -> None:
            nonlocal _section_emitted_count
            _section_emitted_count += 1
            await self._section_branch(ctx, events, publish, section, emit_parallel_events=False)

        # Load Brand DNA for the tenant so Vangogh generates branded artifacts
        brand_dna = await self._load_brand_dna(ctx.request.tenant_id)

        self._pre_handoff_check(
            "content_director" if content_brief is not None else "research",
            vangogh_name,
            content_brief or evidence.model_dump(mode="json"),
            workflow_id=self._contract_workflow_id(ctx),
        )
        self._pre_dispatch_check(
            vangogh_name,
            {
                "user_query": ctx.request.user_query,
                "evidence_pack": evidence.model_dump(mode="json"),
                "content_brief": content_brief,
                "brand_dna": brand_dna,
            },
            workflow_id=self._contract_workflow_id(ctx),
        )
        artifact = await vangogh_agent.generate(
            ctx.request.user_query,
            evidence,
            content_brief=content_brief,
            on_section_ready=_on_section_ready,
            brand_dna=brand_dna,
        )
        self.registry.mark_agent_ready(vangogh_name, "idle")
        await publish(
            events.build(
                "artifact_ready",
                agent_name=vangogh_name,
                phase="artifact",
                data={"artifact_manifest": artifact.model_dump(exclude={"html", "css"})},
            )
        )
        await ctx.agent_run_repo.mark_complete(agent_run.run_id, artifact.model_dump())
        await self._complete_branch(ctx, branch_id=branch_id, output_json=artifact.model_dump())
        return WorkflowEngine._ArtifactOutcome(artifact=artifact, sections_emitted=_section_emitted_count > 0)

    async def _emit_artifact_sections(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher, artifact: VisualArtifact, parallel: bool) -> None:
        if not artifact.sections:
            return

        if parallel:
            tasks = [
                asyncio.create_task(self._section_branch(ctx, events, publish, section, emit_parallel_events=True))
                for section in artifact.sections
            ]
            results = [await task for task in asyncio.as_completed(tasks)]
        else:
            results = []
            for section in artifact.sections:
                results.append(await self._section_branch(ctx, events, publish, section, emit_parallel_events=False))

        if any(result.error_message for result in results):
            raise RuntimeError("; ".join(result.error_message for result in results if result.error_message))

    async def _section_branch(
        self,
        ctx: WorkflowRunContext,
        events: EventFactory,
        publish: EventPublisher,
        section: ArtifactSection,
        *,
        emit_parallel_events: bool,
    ) -> BranchResult:
        branch_id = f"artifact-section-{section.section_id}"
        vangogh_name = self._assigned_agent_name(ctx, "vangogh", "vangogh")
        await self._set_branch(
            ctx,
            branch_id=branch_id,
            agent_name=vangogh_name,
            branch_kind="artifact-section",
            status="running",
            current_phase="artifact",
            input_json=section.model_dump(),
        )
        branch = BranchResult(branch_id=branch_id, section=section)
        try:
            if emit_parallel_events:
                await publish(
                    events.build(
                        "parallel_branch_started",
                        agent_name=vangogh_name,
                        phase="artifact",
                        data={"branch": branch_id, "section_id": section.section_id},
                    )
                )
            await publish(
                events.build(
                    "artifact_section_ready",
                    agent_name=vangogh_name,
                    phase="artifact",
                    data={
                        "section_id": section.section_id,
                        "section_index": section.section_index,
                        "title": section.title,
                        "summary": section.summary,
                        "html_fragment": section.html_fragment,
                        "section_data": section.section_data,
                    },
                )
            )
            if emit_parallel_events:
                await publish(
                    events.build(
                        "parallel_branch_completed",
                        agent_name=vangogh_name,
                        phase="artifact",
                        data={"branch": branch_id, "section_id": section.section_id},
                    )
                )
            await self._complete_branch(ctx, branch_id=branch_id, output_json=section.model_dump())
            return branch
        except Exception as exc:
            branch.error_message = str(exc)
            await self._fail_branch(ctx, branch_id=branch_id, error_message=str(exc))
            return branch

    async def _review_artifact(self, ctx: WorkflowRunContext, events: EventFactory, publish: EventPublisher, artifact: VisualArtifact, evidence: EvidencePack) -> _GovernanceOutcome:
        branch_id = "governance"
        governance_name = self._assigned_agent_name(ctx, branch_id, "governance")
        await self._set_branch(
            ctx,
            branch_id=branch_id,
            agent_name=governance_name,
            branch_kind="governance",
            status="running",
            current_phase="governance",
            input_json={"artifact_id": artifact.artifact_id, "evidence_refs": artifact.evidence_refs},
        )
        agent_run = await ctx.agent_run_repo.create_run(
            thread_id=ctx.request.thread_id,
            tenant_id=ctx.request.tenant_id,
            agent_name=governance_name,
            agent_type=AgentType.governance.value,
            branch_id=branch_id,
            input_json={"artifact_id": artifact.artifact_id, "evidence_refs": artifact.evidence_refs},
        )
        await publish(events.build("governance_started", agent_name=governance_name, phase="governance"))
        logger.info(
            "[workflow] governance_started artifact_id=%s evidence_refs=%d",
            artifact.artifact_id,
            len(artifact.evidence_refs),
        )
        _, governance_agent = self._resolve_runtime_agent(ctx, branch_id, "governance")
        await self._maybe_set_log_sink(governance_agent, _make_agent_log_sink(events, publish, governance_name, "governance", "governance"))
        self._pre_handoff_check(
            "vangogh",
            governance_name,
            artifact.model_dump(mode="json"),
            workflow_id=self._contract_workflow_id(ctx),
        )
        self._pre_dispatch_check(
            governance_name,
            {
                "artifact": artifact.model_dump(mode="json"),
                "evidence_pack": evidence.model_dump(mode="json"),
            },
            workflow_id=self._contract_workflow_id(ctx),
        )
        report = (await governance_agent.review(artifact, evidence)).model_dump()
        await publish(events.build("governance_complete", agent_name=governance_name, phase="governance", data={"governance_report": report}))
        logger.info(
            "[workflow] governance_completed approved=%s readiness_score=%s issues=%s",
            report.get("approved"),
            report.get("readiness_score"),
            report.get("issues", []),
        )
        await self._emit_step_summary(
            events,
            publish,
            step="governance",
            phase="governance",
            summary={
                "approved": report.get("approved"),
                "readiness_score": report.get("readiness_score"),
                "issues": report.get("issues", []),
            },
        )
        await ctx.agent_run_repo.mark_complete(agent_run.run_id, report)
        await self._complete_branch(ctx, branch_id=branch_id, output_json=report)
        return WorkflowEngine._GovernanceOutcome(report=report)

    def _merge_evidence(self, *evidences: EvidencePack) -> EvidencePack:
        cleaned = [e for e in evidences if e is not None]
        if not cleaned:
            return EvidencePack(summary="No evidence gathered.", confidence=0.0)

        source_by_id: dict[str, SourceRecord] = {}
        citations_by_id: dict[str, Citation] = {}
        web_findings_by_id: dict[str, EvidenceFinding] = {}
        doc_findings_by_id: dict[str, EvidenceFinding] = {}
        open_questions: list[str] = []
        summary_parts: list[str] = []
        confidence = 0.0

        for evidence in cleaned:
            if evidence.summary:
                summary_parts.append(evidence.summary)
            for source in evidence.sources:
                source_by_id[source.source_id] = source
            for finding in evidence.web_findings:
                web_findings_by_id[finding.finding_id] = finding
            for finding in evidence.doc_findings:
                doc_findings_by_id[finding.finding_id] = finding
            for question in evidence.open_questions:
                if question not in open_questions:
                    open_questions.append(question)
            for citation in evidence.citations:
                citations_by_id[citation.source_id] = citation
            confidence = max(confidence, evidence.confidence)

        return EvidencePack(
            summary=" ".join(summary_parts).strip() or "Merged evidence pack.",
            sources=list(source_by_id.values()),
            web_findings=list(web_findings_by_id.values()),
            doc_findings=list(doc_findings_by_id.values()),
            open_questions=open_questions,
            confidence=confidence,
            citations=list(citations_by_id.values()),
        )

    async def _set_branch(
        self,
        ctx: WorkflowRunContext,
        *,
        branch_id: str,
        agent_name: str,
        branch_kind: str,
        status: str,
        current_phase: str | None,
        input_json: dict[str, Any] | None = None,
    ) -> None:
        state = BranchRedisState(
            thread_id=ctx.request.thread_id,
            run_id=ctx.run_id,
            branch_id=branch_id,
            agent_name=agent_name,
            branch_kind=branch_kind,
            status=status,
            current_phase=current_phase,
            input_json=json.dumps(input_json or {}, default=str),
        )
        await ctx.state_store.set_branch_state(state)
        workflow_state = await ctx.state_store.get_workflow_state(ctx.request.thread_id)
        if workflow_state is not None:
            if branch_id not in workflow_state.branch_ids:
                workflow_state.branch_ids.append(branch_id)
            workflow_state.current_node = branch_id
            workflow_state.current_agent = agent_name
            workflow_state.current_phase = current_phase
            await ctx.state_store.set_workflow_state(workflow_state)

    async def _complete_branch(self, ctx: WorkflowRunContext, *, branch_id: str, output_json: dict[str, Any]) -> None:
        current = await ctx.state_store.get_branch_state(ctx.request.thread_id, branch_id)
        if current is None:
            return
        current.status = "complete"
        current.output_json = json.dumps(output_json, default=str)
        current.finished_at = utc_now()
        current.updated_at = utc_now()
        await ctx.state_store.set_branch_state(current)

    async def _fail_branch(self, ctx: WorkflowRunContext, *, branch_id: str, error_message: str) -> None:
        current = await ctx.state_store.get_branch_state(ctx.request.thread_id, branch_id)
        if current is None:
            return
        current.status = "error"
        current.error_message = error_message
        current.finished_at = utc_now()
        current.updated_at = utc_now()
        await ctx.state_store.set_branch_state(current)


def utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


class _PassthroughAsyncContext:
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False
