from __future__ import annotations

import hashlib
import inspect
import json
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar
from uuid import uuid4

from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock
from agentscope.plan import PlanNotebook
from agentscope.tool import ToolResponse, Toolkit
from pydantic import BaseModel

from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

T = TypeVar("T", bound=BaseModel)

# Type alias for the event sink callback that agents use to stream live logs.
# The engine injects a concrete implementation bound to the SSE publish() closure.
AgentLogSink = Callable[[str, str, str, dict[str, Any] | None], Awaitable[None]]
# signature: (message: str, message_kind: str, visibility: str, detail: dict | None) -> None


async def _noop_sink(_msg: str, _kind: str, _vis: str, _detail: dict[str, Any] | None = None) -> None:
    """Default no-op sink when no event publisher is wired."""


class BaseAgent:
    """Shared AgentScope-backed runtime wrapper for BLAIQ specialist agents."""

    def __init__(
        self,
        *,
        name: str,
        role: str,
        sys_prompt: str,
        resolver: LiteLLMModelResolver | None = None,
        toolkit: Toolkit | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.sys_prompt = sys_prompt
        self.resolver = resolver or LiteLLMModelResolver.from_settings(settings)
        self._shared_toolkit = toolkit
        self._log_sink: AgentLogSink = _noop_sink
        self._notebook: PlanNotebook | None = None
        self._notebook_revision: int = 0
        self.status_messages: list[str] = []
        self.last_history: list[Msg] = []

    def set_log_sink(self, sink: AgentLogSink) -> None:
        """Inject the live event sink. Called by the engine before each run."""
        self._log_sink = sink

    async def log_starting(self) -> None:
        """Log the first status message to indicate the agent has started."""
        if self.status_messages:
            await self.log_user(self.status_messages[0])
        else:
            # Fallback for agents without custom status messages
            await self.log_user(f"{self.name} is starting...")

    async def _universal_acting_hook(self, *args: Any, **kwargs: Any) -> None:
        """Internal hook to automatically notify visibility of 'acting' state."""
        agent_name = str(getattr(self, "name", "") or kwargs.get("agent_name") or self.__class__.__name__)
        await self.log(
            f"{agent_name} is starting an action...",
            kind="agent_log",
            visibility="user",
            detail={
                "object": "status",
                "status": "acting",
                "agent": agent_name,
                "detail": "Executing logic loop..."
            }
        )

    # ── PlanNotebook lifecycle ────────────────────────────────────────────────

    def create_notebook(self) -> PlanNotebook:
        """Create a fresh PlanNotebook and store it on the agent.

        The notebook is reused across calls to ``_create_runtime_agent`` so the
        planner accumulates state within a single planning session rather than
        starting from scratch on every ReAct iteration.
        """
        self._notebook = PlanNotebook()
        self._notebook_revision = 0
        return self._notebook

    def reset_notebook(self) -> None:
        """Discard the current notebook and its revision counter."""
        self._notebook = None
        self._notebook_revision = 0

    def export_notebook_snapshot(self) -> dict[str, Any] | None:
        """Export the current plan as a plain dict snapshot.

        Raw PlanNotebook internals are NOT persisted — only the structured
        ``current_plan`` model is included so the snapshot can be stored in
        workflow state JSON safely.

        Returns ``None`` when no notebook or plan exists yet.
        """
        if self._notebook is None or self._notebook.current_plan is None:
            return None
        plan = self._notebook.current_plan
        return {
            "current_plan": plan.model_dump(mode="json"),
            "revision": self._notebook_revision,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "agent": self.name,
        }

    def restore_notebook_from_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Rebuild a PlanNotebook from an exported snapshot dict.

        Creates a fresh notebook and seeds ``current_plan`` from the snapshot.
        Falls back silently when the snapshot is malformed so resume paths
        never hard-fail due to a missing or corrupt plan snapshot.
        """
        try:
            from agentscope.plan._plan_notebook import Plan  # local import avoids circular
            notebook = PlanNotebook()
            plan_data = snapshot.get("current_plan")
            if plan_data:
                notebook.current_plan = Plan.model_validate(plan_data)
            self._notebook = notebook
            self._notebook_revision = int(snapshot.get("revision", 0))
        except Exception:
            self._notebook = PlanNotebook()
            self._notebook_revision = 0

    def revise_notebook(self) -> None:
        """Increment the revision counter after a planning update."""
        self._notebook_revision += 1

    # ─────────────────────────────────────────────────────────────────────────

    def register_tool(
        self,
        toolkit: Any,
        *,
        tool_id: str,
        fn: Callable[..., Any],
        description: str = "",
    ) -> None:
        """Register a tool with runtime telemetry wrapping."""
        wrapped = self.instrument_tool(tool_id, fn)
        # AgentScope extracts metadata from __name__ and __doc__
        wrapped.__name__ = tool_id
        wrapped.__doc__ = description
        
        toolkit.register_tool_function(wrapped)

    async def log(
        self,
        message: str,
        *,
        kind: str = "status",
        visibility: str = "user",
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Emit a live agent_log event to the SSE stream.

        Args:
            message: Human-readable message for the frontend chat.
            kind: One of thought, tool_call, tool_result, status, decision, artifact, review.
            visibility: 'user' for frontend chat, 'log' for logs panel, 'debug' for operator console.
            detail: Optional structured payload.
        """
        await self._log_sink(message, kind, visibility, detail)

    async def log_user(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        """Emit a user-visible status message to the agent card on the frontend.

        Use this for meaningful progress updates the user should see.
        Use ``log()`` with ``visibility='log'`` for internal/debug messages.
        """
        await self._log_sink(message, "status", "user", detail)

    @staticmethod
    def _redact_tool_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        def _preview(value: Any) -> Any:
            if isinstance(value, dict):
                return {str(key): _preview(val) for key, val in list(value.items())[:8]}
            if isinstance(value, list):
                return [_preview(item) for item in value[:8]]
            if isinstance(value, tuple):
                return [_preview(item) for item in list(value[:8])]
            text = str(value)
            if len(text) > 180:
                return text[:177] + "..."
            return text

        return {str(key): _preview(value) for key, value in kwargs.items()}

    @staticmethod
    def _summarize_tool_result(result: Any) -> Any:
        if result is None:
            return {"kind": "none"}
        if isinstance(result, (str, int, float, bool)):
            text = str(result)
            return text[:300] + ("..." if len(text) > 300 else "")
        if isinstance(result, dict):
            return {
                "kind": "dict",
                "keys": list(result.keys())[:12],
            }
        if isinstance(result, (list, tuple)):
            return {
                "kind": "list",
                "length": len(result),
            }
        metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            return {
                "kind": type(result).__name__,
                "metadata_keys": list(metadata.keys())[:12],
            }
        text = str(result)
        return {
            "kind": type(result).__name__,
            "text": text[:300] + ("..." if len(text) > 300 else ""),
        }

    def instrument_tool(
        self,
        tool_id: str,
        fn: Callable[..., Any],
    ) -> Callable[..., Awaitable[Any]]:
        """Wrap a tool callable with structured runtime telemetry."""

        async def _wrapped(**kwargs: Any) -> Any:
            correlation_id = uuid4().hex
            started_at = time.perf_counter()
            input_preview = self._redact_tool_kwargs(kwargs)
            input_hash = hashlib.sha256(
                json.dumps(input_preview, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            await self.log(
                f"Tool {tool_id} started.",
                kind="tool_call_started",
                visibility="debug",
                detail={
                    "call_id": correlation_id,
                    "tool_id": tool_id,
                    "agent_name": self.name,
                    "input_hash": input_hash,
                    "input_preview": input_preview,
                },
            )
            try:
                result = fn(**kwargs)
                if inspect.isawaitable(result):
                    result = await result
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                await self.log(
                    f"Tool {tool_id} finished.",
                    kind="tool_call_finished",
                    visibility="debug",
                    detail={
                        "call_id": correlation_id,
                        "tool_id": tool_id,
                        "agent_name": self.name,
                        "input_hash": input_hash,
                        "input_preview": input_preview,
                        "output_summary": self._summarize_tool_result(result),
                        "duration_ms": duration_ms,
                    },
                )
                return result
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                await self.log(
                    f"Tool {tool_id} failed: {type(exc).__name__}.",
                    kind="tool_call_failed",
                    visibility="debug",
                    detail={
                        "call_id": correlation_id,
                        "tool_id": tool_id,
                        "agent_name": self.name,
                        "input_hash": input_hash,
                        "input_preview": input_preview,
                        "duration_ms": duration_ms,
                        "error_code": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise

        _wrapped.__name__ = tool_id
        return _wrapped

    def build_toolkit(self) -> Toolkit:
        return self._shared_toolkit or Toolkit()

    def _create_runtime_agent(
        self,
        plan_notebook: PlanNotebook | None = None,
        *,
        name: str | None = None,
        sys_prompt: str | None = None,
        role: str | None = None,
        model_role: str | None = None,
        toolkit: Toolkit | None = None,
        memory: InMemoryMemory | None = None,
        formatter: OpenAIChatFormatter | None = None,
        max_iters: int = 6,
        parallel_tool_calls: bool = True,
    ) -> ReActAgent:
        """Create a ReActAgent for one invocation.

        ``plan_notebook`` — pass an existing notebook to continue a prior
        planning session; pass ``None`` (default) to let the agent use
        ``self._notebook`` when set, or create a fresh one otherwise.
        """
        notebook = plan_notebook or self._notebook or PlanNotebook()
        agent = ReActAgent(
            name=name or self.name,
            sys_prompt=sys_prompt or self.sys_prompt,
            model=self.resolver.build_agentscope_model(model_role or role or self.role),
            formatter=formatter or OpenAIChatFormatter(),
            toolkit=toolkit or self.build_toolkit(),
            memory=memory or InMemoryMemory(),
            plan_notebook=notebook,
            max_iters=max_iters,
            parallel_tool_calls=parallel_tool_calls,
        )
        
        # Register the universal 'acting' notification hook for all ReAct loops
        agent.register_instance_hook(
            hook_type="pre_acting",
            hook_name="blaiq_live_status",
            hook=self._universal_acting_hook
        )

        # Disable AgentScope's built-in console printer so raw tool_use /
        # tool_result blocks do not leak into backend stdout.
        if hasattr(agent, "_disable_console_output"):
            agent._disable_console_output = True
        return agent

    def make_msg(self, content: Any, role: str = "assistant", **metadata: Any) -> Msg:
        sender_name = "user" if role == "user" else self.name
        msg = Msg(sender_name, content, role, metadata=metadata or None)
        if metadata:
            msg.metadata = {**(msg.metadata or {}), **metadata}
        return msg

    async def reply(self, msg: Msg | str, *, extra_context: dict[str, Any] | None = None) -> Msg:
        agent = self._create_runtime_agent()
        user_text = msg.content if isinstance(msg, Msg) else str(msg)
        runtime_msg = self.make_msg(
            self._build_user_prompt(user_text, extra_context or {}),
            role="user",
            phase="request",
        )
        response = await agent.reply(runtime_msg)
        
        # Store history for telemetry/TUI inspection
        history = agent.memory.get_memory()
        if inspect.isawaitable(history):
            self.last_history = await history
        else:
            self.last_history = history
        
        return response

    async def complete_text(
        self,
        *,
        user_content: str,
        extra_context: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        del temperature, max_tokens  # AgentScope model settings are role-scoped at construction time.
        agent = self._create_runtime_agent()
        response = await agent.reply(
            self.make_msg(
                self._build_user_prompt(user_content, extra_context or {}),
                role="user",
                phase="request",
            ),
        )
        return self._extract_msg_text(response)

    async def complete_json(
        self,
        model: type[T],
        *,
        user_content: str,
        extra_context: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        del temperature, max_tokens
        agent = self._create_runtime_agent()
        response = await agent.reply(
            self.make_msg(
                self._build_user_prompt(user_content, extra_context or {}),
                role="user",
                phase="request",
            ),
            structured_model=model,
        )
        if response.metadata:
            return model.model_validate(response.metadata)
        payload = self.resolver.safe_json_loads(self._extract_msg_text(response))
        return model.model_validate(payload)

    def _build_user_prompt(self, user_content: str, extra_context: dict[str, Any]) -> str:
        if not extra_context:
            return user_content
        context_blob = json.dumps(extra_context, indent=2, sort_keys=True, default=str)
        return f"{user_content}\n\nContext:\n{context_blob}"

    @staticmethod
    def tool_response(payload: Any, *, metadata: dict[str, Any] | None = None) -> ToolResponse:
        text = json.dumps(payload, indent=2, sort_keys=True, default=str) if not isinstance(payload, str) else payload
        return ToolResponse(
            content=[TextBlock(type="text", text=text)],
            metadata=metadata or (payload if isinstance(payload, dict) else {"value": payload}),
        )

    @staticmethod
    def _extract_msg_text(msg: Msg) -> str:
        if isinstance(msg.content, str):
            return msg.content.strip()
        if isinstance(msg.content, list):
            text_parts: list[str] = []
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
                else:
                    text_parts.append(str(block))
            return "\n".join(part for part in text_parts if part).strip()
        return str(msg.content).strip()
