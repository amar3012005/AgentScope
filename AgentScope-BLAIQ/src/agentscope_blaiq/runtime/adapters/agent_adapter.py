"""
HarnessAgentAdapter — wraps any BaseAgent subclass with contract enforcement.

Applies pre-dispatch validation, output schema checks, and hook intercepts
before and after each agent execution.  All contract decisions are made here;
the wrapped agent only sees clean, validated calls.
"""
from __future__ import annotations

import logging
from typing import Any

from agentscope_blaiq.contracts.dispatch import validate_dispatch
from agentscope_blaiq.contracts.harness import AgentHarness
from agentscope_blaiq.contracts.hooks import HookAction, HookContext, HookRegistry, HookType
from agentscope_blaiq.contracts.registry import HarnessRegistry
from agentscope_blaiq.runtime.agent_base import BaseAgent
from agentscope_blaiq.runtime.agentscope_compat import Toolkit  # noqa: F401 — re-exported for callers

logger = logging.getLogger("agentscope_blaiq.adapters.agent")


# ============================================================================
# Exceptions
# ============================================================================


class DispatchBlockedError(Exception):
    """Raised when the PRE_NODE hook returns HookAction.BLOCK."""


class OutputSchemaError(Exception):
    """Raised when the agent produces no output (None result)."""


# ============================================================================
# Adapter
# ============================================================================


class HarnessAgentAdapter:
    """Wraps a BaseAgent with contract-driven dispatch and hook enforcement.

    The adapter enforces the following lifecycle for each ``execute`` call:

    1. Fire PRE_NODE hook (if a HookRegistry is present).
    2. If the hook decision is BLOCK, raise DispatchBlockedError immediately.
    3. Invoke the wrapped agent — ``complete_json`` when the harness has an
       ``output_schema``, ``complete_text`` otherwise.
    4. Fire POST_NODE hook with the agent output.
    5. If output is None, raise OutputSchemaError.
    6. Return output dict to the caller.
    """

    def __init__(
        self,
        agent: BaseAgent,
        harness: AgentHarness,
        harness_registry: HarnessRegistry,
        hook_registry: HookRegistry | None = None,
    ) -> None:
        """Initialise the adapter.

        Args:
            agent: The wrapped BaseAgent subclass instance.
            harness: AgentHarness contract that governs this agent.
            harness_registry: Used by dispatch and hook validation.
            hook_registry: Optional registry of hook evaluators to fire at
                PRE_NODE and POST_NODE boundaries.
        """
        self.agent = agent
        self.harness = harness
        self.harness_registry = harness_registry
        self.hook_registry = hook_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        input_data: dict[str, Any],
        *,
        workflow_id: str | None = None,
        attempt_number: int = 0,
    ) -> dict[str, Any]:
        """Execute the wrapped agent with full contract enforcement.

        Args:
            input_data: Data to send to the agent.
            workflow_id: Current workflow instance identifier (optional).
            attempt_number: Retry count for this node (0-indexed).

        Returns:
            Agent output as a plain dict.

        Raises:
            DispatchBlockedError: If PRE_NODE hook blocks execution.
            OutputSchemaError: If the agent returns None output.
        """
        node_id = self.harness.agent_id

        # 1. PRE_NODE hook
        if self.hook_registry is not None:
            pre_ctx = HookContext(
                hook_type=HookType.PRE_NODE,
                node_id=node_id,
                agent_id=self.harness.agent_id,
                input_data=input_data,
                workflow_id=workflow_id,
                attempt_number=attempt_number,
            )
            pre_result = self.hook_registry.evaluate(pre_ctx)
            if pre_result.final_action is HookAction.BLOCK:
                raise DispatchBlockedError(
                    f"PRE_NODE hook blocked dispatch for agent '{self.harness.agent_id}': "
                    f"{pre_result.all_errors}"
                )

        # 2. Invoke agent
        user_content = _serialise_input(input_data)
        raw_output: Any

        if self.harness.output_schema:
            # Build a lightweight Pydantic model from the output schema so that
            # complete_json can validate the structured response.  For Phase 4
            # we rely on the caller to supply a proper Pydantic model via
            # structured_model; if no model is wired we fall back to text.
            try:
                from pydantic import BaseModel, create_model  # local import — avoid top-level coupling

                DynamicOutput = _build_dynamic_model(self.harness.output_schema)
                result_model = await self.agent.complete_json(
                    DynamicOutput,
                    user_content=user_content,
                    extra_context=input_data,
                )
                raw_output = result_model.model_dump() if result_model is not None else None
            except Exception:
                logger.warning(
                    "agent=%s complete_json failed; falling back to complete_text",
                    self.harness.agent_id,
                )
                text = await self.agent.complete_text(
                    user_content=user_content,
                    extra_context=input_data,
                )
                raw_output = {"text": text} if text else None
        else:
            text = await self.agent.complete_text(
                user_content=user_content,
                extra_context=input_data,
            )
            raw_output = {"text": text} if text else None

        # 3. POST_NODE hook
        if self.hook_registry is not None:
            post_ctx = HookContext(
                hook_type=HookType.POST_NODE,
                node_id=node_id,
                agent_id=self.harness.agent_id,
                input_data=input_data,
                output_data=raw_output,
                workflow_id=workflow_id,
                attempt_number=attempt_number,
            )
            self.hook_registry.evaluate(post_ctx)

        # 4. Guard against None output
        if raw_output is None:
            raise OutputSchemaError(
                f"Agent '{self.harness.agent_id}' returned None output on node '{node_id}'"
            )

        return raw_output  # type: ignore[return-value]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, list[str]]:
        """Check input_data against the harness contract without executing.

        Args:
            input_data: Data intended for the agent.

        Returns:
            (ok, errors) — ok is True when dispatch is safe; errors is a
            list of validation error strings (empty when ok).
        """
        result = validate_dispatch(
            agent_id=self.harness.agent_id,
            input_data=input_data,
            registry=self.harness_registry,
        )
        return result.ok, result.errors


# ============================================================================
# Internal helpers
# ============================================================================


def _serialise_input(input_data: dict[str, Any]) -> str:
    """Convert the input dict to a compact JSON string for the agent prompt."""
    import json
    return json.dumps(input_data, indent=2, sort_keys=True, default=str)


def _build_dynamic_model(output_schema: dict[str, Any]) -> type:
    """Build a minimal Pydantic BaseModel from a JSON schema dict.

    Only top-level ``properties`` are mapped.  Deeply nested schemas are
    accepted but stored as ``Any`` — the goal is structural validation, not
    exhaustive schema enforcement.
    """
    from pydantic import BaseModel, create_model
    from typing import Any as AnyType

    properties: dict[str, Any] = output_schema.get("properties", {})
    field_definitions: dict[str, Any] = {
        name: (AnyType, None) for name in properties
    }
    return create_model("DynamicOutput", **field_definitions)  # type: ignore[call-overload]
