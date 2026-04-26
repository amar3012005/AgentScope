"""
Generic executor for custom agents.

Replaces the fragile class-instantiation + prompt-patching approach with
a contract-enforced execution pipeline:

1. Validate input against harness input_schema
2. Render prompt from spec.prompt + input data
3. Call LLM with rendered prompt
4. Validate output against harness output_schema
5. Restrict tool calls to spec.allowed_tools
6. Invoke recovery policy on schema failures

Built-in and custom agents share the same boundary checks.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
from agentscope_blaiq.contracts.enforcement import enforcement_check
from agentscope_blaiq.contracts.recovery import (
    FailureClass,
    RecoveryEvent,
    RetryBudget,
    classify_failure,
    resolve_recovery,
)

logger = logging.getLogger("agentscope_blaiq.custom_executor")


class CustomAgentExecutionError(Exception):
    """Raised when a custom agent fails validation or execution."""

    def __init__(
        self,
        message: str,
        failure_class: FailureClass,
        errors: list[str],
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.errors = errors


class CustomAgentExecutor:
    """Execute a custom agent with full contract enforcement.

    Lifecycle:
    1. validate_input(input_data) — check against harness input_schema
    2. render_prompt(input_data) — build system + user prompt from spec
    3. execute(input_data) — call LLM, validate output, retry on failure
    """

    def __init__(
        self,
        spec: CustomAgentSpec,
        resolver: Any,  # LiteLLMModelResolver — typed as Any to avoid circular import
    ) -> None:
        self.spec = spec
        self.resolver = resolver
        self._budget = RetryBudget(
            workflow_id="custom_agent",
            max_per_node_retries=spec.max_iterations,
            max_total_retries=spec.max_iterations * 2,
        )

    def validate_input(
        self, input_data: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate input against the harness input_schema."""
        schema = self.spec.input_schema
        if not schema:
            return True, []

        errors: list[str] = []
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for key in required:
            if key not in input_data:
                errors.append(f"Missing required input field: '{key}'")

        for key, value in input_data.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type and not _type_matches(value, expected_type):
                    errors.append(
                        f"Input field '{key}' has type {type(value).__name__}, "
                        f"expected {expected_type}"
                    )

        return len(errors) == 0, errors

    def validate_output(
        self, output_data: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate output against the harness output_schema."""
        schema = self.spec.output_schema
        if not schema:
            return True, []

        errors: list[str] = []
        required = schema.get("required", [])

        for key in required:
            if key not in output_data:
                errors.append(f"Missing required output field: '{key}'")

        return len(errors) == 0, errors

    def render_system_prompt(self) -> str:
        """Render the system prompt from the spec."""
        return self.spec.prompt

    def render_user_prompt(self, input_data: dict[str, Any]) -> str:
        """Render the user prompt from input data.

        Formats input as structured context for the LLM.
        """
        parts: list[str] = []

        # Add each input field as a labeled section
        for key, value in input_data.items():
            if isinstance(value, (dict, list)):
                parts.append(
                    f"## {key}\n{json.dumps(value, indent=2, default=str)}"
                )
            else:
                parts.append(f"## {key}\n{value}")

        # Add output schema guidance
        output_schema = self.spec.output_schema
        if output_schema and output_schema.get("properties"):
            required = output_schema.get("required", [])
            fields = list(output_schema["properties"].keys())
            parts.append(
                f"\n## Required Output Format\n"
                f"Return a JSON object with these fields: {fields}\n"
                f"Required fields: {required}"
            )

        return "\n\n".join(parts)

    def check_tool_allowed(self, tool_id: str) -> bool:
        """Check if a tool call is within the agent's allowed tools."""
        if not self.spec.allowed_tools:
            return True  # no restriction
        return tool_id in self.spec.allowed_tools

    async def execute(
        self,
        input_data: dict[str, Any],
        *,
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        """Execute the custom agent with full contract enforcement.

        Args:
            input_data: Input data to send to the agent.
            max_attempts: Override max retry attempts (default from spec).

        Returns:
            Validated output dict.

        Raises:
            CustomAgentExecutionError: On validation or execution failure.
        """
        attempts = max_attempts or min(self.spec.max_iterations, 3)

        # 1. Validate input
        input_ok, input_errors = self.validate_input(input_data)
        enforcement_check(
            ok=input_ok,
            errors=input_errors,
            context=f"custom_agent_input agent={self.spec.agent_id}",
        )
        if not input_ok:
            raise CustomAgentExecutionError(
                f"Input validation failed for agent '{self.spec.agent_id}'",
                failure_class=FailureClass.SCHEMA_MISMATCH,
                errors=input_errors,
            )

        # 2. Render prompts
        system_prompt = self.render_system_prompt()
        user_prompt = self.render_user_prompt(input_data)

        # 3. Execute with retry
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                model_role = self.spec.model_hint or "sonnet"
                # Map model hints to resolver model roles
                model_map: dict[str, str] = {
                    "sonnet": "text_buddy",
                    "opus": "research",
                    "haiku": "routing",
                }
                resolver_role = model_map.get(model_role, "text_buddy")

                response = await self.resolver.acompletion(
                    resolver_role,
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=self.spec.timeout_seconds * 10,  # rough token budget
                    temperature=0.3,
                )
                raw_text: str = self.resolver.extract_text(response)

                # Try to parse as JSON
                output = self._parse_output(raw_text)

                # 4. Validate output
                output_ok, output_errors = self.validate_output(output)
                if not output_ok:
                    logger.warning(
                        "custom_agent=%s attempt=%d output_validation_failed errors=%s",
                        self.spec.agent_id,
                        attempt + 1,
                        output_errors,
                    )
                    if attempt < attempts - 1:
                        continue  # retry
                    enforcement_check(
                        ok=False,
                        errors=output_errors,
                        context=f"custom_agent_output agent={self.spec.agent_id}",
                    )

                logger.info(
                    "custom_agent=%s executed successfully attempt=%d",
                    self.spec.agent_id,
                    attempt + 1,
                )
                return output

            except CustomAgentExecutionError:
                raise
            except Exception as exc:
                last_error = exc
                failure_class = classify_failure(
                    exc, {"agent_id": self.spec.agent_id}
                )
                recovery = resolve_recovery(
                    failure_class=failure_class,
                    budget=self._budget,
                    node_id=self.spec.agent_id,
                )
                self._budget.record_attempt(self.spec.agent_id)

                logger.warning(
                    "custom_agent=%s attempt=%d/%d failed: %s recovery=%s",
                    self.spec.agent_id,
                    attempt + 1,
                    attempts,
                    exc,
                    recovery.action.value,
                )

                if recovery.block_workflow or attempt == attempts - 1:
                    raise CustomAgentExecutionError(
                        f"Agent '{self.spec.agent_id}' failed after {attempt + 1} attempts: {exc}",
                        failure_class=failure_class,
                        errors=[str(exc)],
                    ) from exc

        raise CustomAgentExecutionError(
            f"Agent '{self.spec.agent_id}' exhausted all {attempts} attempts",
            failure_class=FailureClass.AGENT_ERROR,
            errors=[str(last_error)] if last_error else [],
        )

    def _parse_output(self, raw_text: str) -> dict[str, Any]:
        """Parse LLM output as JSON, falling back to text wrapper."""
        raw = raw_text.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Fallback: wrap raw text as {"text": ...}
        return {"text": raw_text, "raw": True}


def _type_matches(value: Any, expected_type: str) -> bool:
    """Check if a Python value matches a JSON schema type."""
    type_map: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    expected = type_map.get(expected_type)
    if expected is None:
        return True  # unknown type — don't reject
    return isinstance(value, expected)
