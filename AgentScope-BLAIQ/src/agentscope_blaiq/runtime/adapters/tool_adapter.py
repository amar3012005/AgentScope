"""
HarnessToolAdapter — wraps tool functions with ToolHarness schema validation.

Each adapter validates kwargs against the harness input_schema before
delegating to the real callable, ensuring contract enforcement at the
tool boundary without modifying tool implementations.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import time
from typing import Any, Awaitable, Callable
from uuid import uuid4

import jsonschema

from agentscope_blaiq.contracts.harness import ToolHarness
from agentscope_blaiq.runtime.agentscope_compat import Toolkit

logger = logging.getLogger("agentscope_blaiq.adapters.tool")
ToolTelemetrySink = Callable[[str, str, str, dict[str, Any] | None], Awaitable[None]]


class HarnessToolAdapter:
    """Wraps a tool callable with ToolHarness input schema validation.

    When registered with a Toolkit via ``register_with_toolkit``, the
    validated wrapper is called instead of the raw function — preventing
    contract-violating inputs from ever reaching the tool implementation.
    """

    def __init__(
        self,
        harness: ToolHarness,
        fn: Callable[..., Any],
        *,
        telemetry_sink: ToolTelemetrySink | None = None,
        telemetry_context: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the adapter.

        Args:
            harness: ToolHarness contract that governs this tool.
            fn: The underlying tool callable to wrap.
        """
        self.harness = harness
        self.fn = fn
        self.telemetry_sink = telemetry_sink
        self.telemetry_context = telemetry_context or {}
        # Build a named standalone function so toolkit introspection sees the
        # correct tool_id and __name__ assignment works (bound methods disallow it).
        self._validated_fn = self._build_named_wrapper()

    def register_with_toolkit(self, toolkit: Any) -> None:
        """Register the validated wrapper with an AgentScope Toolkit.

        Args:
            toolkit: Any object that exposes ``register_tool_function``.
                Typically an agentscope ``Toolkit`` or the compat shim.
        """
        # AgentScope Toolkit signatures differ across versions. Prefer the
        # explicit `name=` form, then fall back to a positional call, and
        # finally rename the wrapper for minimal compat shims.
        attempts = (
            lambda: toolkit.register_tool_function(
                self._validated_fn,
                group_name="basic",
                func_name=self.harness.tool_id,
            ),
            lambda: toolkit.register_tool_function(
                self._validated_fn,
                name=self.harness.tool_id,
            ),
            lambda: toolkit.register_tool_function(
                self._validated_fn,
                "basic",
                None,
                self.harness.tool_id,
            ),
        )

        last_error: Exception | None = None
        for attempt in attempts:
            try:
                attempt()
                return
            except (TypeError, ValueError, AttributeError) as exc:
                last_error = exc

        try:
            toolkit.register_tool_function(self._validated_fn)
        except Exception:
            if last_error is not None:
                raise last_error
            raise

    @staticmethod
    def _redact_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        def _preview(value: Any) -> Any:
            if isinstance(value, dict):
                return {str(key): _preview(val) for key, val in list(value.items())[:8]}
            if isinstance(value, list):
                return [_preview(item) for item in value[:8]]
            if isinstance(value, tuple):
                return [_preview(item) for item in list(value[:8])]
            text = str(value)
            return text[:180] + ("..." if len(text) > 180 else "")

        return {str(key): _preview(value) for key, value in kwargs.items()}

    @staticmethod
    def _summarize_result(result: Any) -> Any:
        if result is None:
            return {"kind": "none"}
        if isinstance(result, (str, int, float, bool)):
            text = str(result)
            return text[:300] + ("..." if len(text) > 300 else "")
        if isinstance(result, dict):
            return {"kind": "dict", "keys": list(result.keys())[:12]}
        if isinstance(result, (list, tuple)):
            return {"kind": "list", "length": len(result)}
        metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            return {"kind": type(result).__name__, "metadata_keys": list(metadata.keys())[:12]}
        text = str(result)
        return {"kind": type(result).__name__, "text": text[:300] + ("..." if len(text) > 300 else "")}

    async def _emit_tool_telemetry(self, kind: str, detail: dict[str, Any]) -> None:
        if self.telemetry_sink is None:
            return
        payload = {**self.telemetry_context, **detail, "tool_id": self.harness.tool_id}
        await self.telemetry_sink(
            f"Tool {self.harness.tool_id} {kind.replace('_', ' ')}.",
            kind,
            "debug",
            payload,
        )

    def _build_named_wrapper(self) -> Callable[..., Any]:
        """Return a standalone async function with __name__ = tool_id."""
        tool_id = self.harness.tool_id
        description = self.harness.description

        async def _wrapper(**kwargs: Any) -> Any:
            return await self._raw_validated(**kwargs)

        _wrapper.__name__ = tool_id
        _wrapper.__qualname__ = tool_id
        _wrapper.__doc__ = description
        return _wrapper

    async def _raw_validated(self, **kwargs: Any) -> Any:
        """Validate kwargs then delegate to the wrapped callable.

        Schema validation is performed when ``harness.input_schema`` is
        non-empty.  Validation failures raise ``jsonschema.ValidationError``
        so the calling agent receives a structured error rather than a silent
        bad call.

        Args:
            **kwargs: Tool keyword arguments from the agent.

        Returns:
            Whatever the underlying tool callable returns.

        Raises:
            jsonschema.ValidationError: If kwargs violate the input schema.
        """
        if self.harness.input_schema:
            try:
                jsonschema.validate(instance=kwargs, schema=self.harness.input_schema)
            except jsonschema.ValidationError as exc:
                logger.warning(
                    "tool=%s input validation failed: %s",
                    self.harness.tool_id,
                    exc.message,
                )
                raise
        call_id = uuid4().hex
        started_at = time.perf_counter()
        input_preview = self._redact_kwargs(kwargs)
        input_hash = hashlib.sha256(
            json.dumps(input_preview, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        await self._emit_tool_telemetry(
            "tool_call_started",
            {
                "call_id": call_id,
                "input_hash": input_hash,
                "input_preview": input_preview,
            },
        )
        try:
            result = self.fn(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            await self._emit_tool_telemetry(
                "tool_call_finished",
                {
                    "call_id": call_id,
                    "input_hash": input_hash,
                    "input_preview": input_preview,
                    "output_summary": self._summarize_result(result),
                    "duration_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )
            return result
        except Exception as exc:
            await self._emit_tool_telemetry(
                "tool_call_failed",
                {
                    "call_id": call_id,
                    "input_hash": input_hash,
                    "input_preview": input_preview,
                    "duration_ms": int((time.perf_counter() - started_at) * 1000),
                    "error_code": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise


# ============================================================================
# Factory
# ============================================================================


def build_toolkit_from_harnesses(
    tool_harnesses: list[ToolHarness],
    tool_fns: dict[str, Callable[..., Any]],
) -> Toolkit:
    """Build a Toolkit with harness-validated wrappers for every matched tool.

    Only tools whose ``tool_id`` is present in ``tool_fns`` are registered;
    harnesses without a matching callable are silently skipped (logged at
    DEBUG level).

    Args:
        tool_harnesses: List of ToolHarness contracts to enforce.
        tool_fns: Mapping from tool_id to the actual callable.

    Returns:
        A Toolkit instance pre-populated with validated tool wrappers.
    """
    toolkit = Toolkit()
    for harness in tool_harnesses:
        fn = tool_fns.get(harness.tool_id)
        if fn is None:
            logger.debug(
                "build_toolkit_from_harnesses: no callable for tool_id=%s — skipped",
                harness.tool_id,
            )
            continue
        adapter = HarnessToolAdapter(harness=harness, fn=fn)
        adapter.register_with_toolkit(toolkit)
        logger.debug("Registered harness-validated tool: %s", harness.tool_id)
    return toolkit
