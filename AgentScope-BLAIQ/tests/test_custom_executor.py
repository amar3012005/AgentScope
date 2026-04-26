"""
Tests for CustomAgentExecutor — validation, rendering, tool checks, parsing.

No agentscope imports. No LLM calls (execute() tests skipped — those need runtime).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
from agentscope_blaiq.runtime.custom_executor import CustomAgentExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(
    *,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
    prompt: str = "You are a helpful assistant for testing purposes only.",
) -> CustomAgentSpec:
    """Build a minimal CustomAgentSpec for testing."""
    return CustomAgentSpec(
        agent_id="test_agent",
        display_name="Test Agent",
        prompt=prompt,
        role="text_buddy",
        input_schema=input_schema
        or {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        output_schema=output_schema
        or {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        allowed_tools=allowed_tools or [],
    )


def _make_executor(
    *,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
    prompt: str = "You are a helpful assistant for testing purposes only.",
) -> CustomAgentExecutor:
    """Build an executor with a dummy resolver (not used in sync tests)."""
    spec = _make_spec(
        input_schema=input_schema,
        output_schema=output_schema,
        allowed_tools=allowed_tools,
        prompt=prompt,
    )
    return CustomAgentExecutor(spec=spec, resolver=None)


# ===========================================================================
# TestCustomAgentExecutor
# ===========================================================================


class TestCustomAgentExecutor:
    """Unit tests for CustomAgentExecutor boundary checks."""

    # -----------------------------------------------------------------------
    # Input validation
    # -----------------------------------------------------------------------

    def test_validate_input_passes_valid(self) -> None:
        """Spec with required 'query', input has 'query' -> ok."""
        executor = _make_executor()
        ok, errors = executor.validate_input({"query": "hello"})
        assert ok is True
        assert errors == []

    def test_validate_input_fails_missing_required(self) -> None:
        """Missing required field -> errors."""
        executor = _make_executor()
        ok, errors = executor.validate_input({})
        assert ok is False
        assert len(errors) == 1
        assert "Missing required input field: 'query'" in errors[0]

    def test_validate_input_fails_wrong_type(self) -> None:
        """Wrong type -> errors."""
        executor = _make_executor()
        ok, errors = executor.validate_input({"query": 42})
        assert ok is False
        assert len(errors) == 1
        assert "expected string" in errors[0]

    # -----------------------------------------------------------------------
    # Output validation
    # -----------------------------------------------------------------------

    def test_validate_output_passes_valid(self) -> None:
        """Valid output -> ok."""
        executor = _make_executor()
        ok, errors = executor.validate_output({"answer": "world"})
        assert ok is True
        assert errors == []

    def test_validate_output_fails_missing_required(self) -> None:
        """Missing required output field -> errors."""
        executor = _make_executor()
        ok, errors = executor.validate_output({"other_field": "value"})
        assert ok is False
        assert len(errors) == 1
        assert "Missing required output field: 'answer'" in errors[0]

    # -----------------------------------------------------------------------
    # Prompt rendering
    # -----------------------------------------------------------------------

    def test_render_system_prompt(self) -> None:
        """Returns spec.prompt verbatim."""
        prompt = "You are a helpful assistant for testing purposes only."
        executor = _make_executor(prompt=prompt)
        assert executor.render_system_prompt() == prompt

    def test_render_user_prompt_includes_fields(self) -> None:
        """User prompt includes input field labels."""
        executor = _make_executor()
        rendered = executor.render_user_prompt(
            {"query": "what is AI", "context": "general knowledge"}
        )
        assert "## query" in rendered
        assert "what is AI" in rendered
        assert "## context" in rendered
        assert "general knowledge" in rendered

    def test_render_user_prompt_includes_output_guidance(self) -> None:
        """User prompt includes required output fields when output_schema has properties."""
        executor = _make_executor(
            output_schema={
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["answer"],
            }
        )
        rendered = executor.render_user_prompt({"query": "test"})
        assert "Required Output Format" in rendered
        assert "answer" in rendered
        assert "confidence" in rendered

    # -----------------------------------------------------------------------
    # Tool restriction
    # -----------------------------------------------------------------------

    def test_check_tool_allowed_passes(self) -> None:
        """Tool in allowed_tools -> True."""
        executor = _make_executor(allowed_tools=["tavily_search", "calculator"])
        assert executor.check_tool_allowed("tavily_search") is True

    def test_check_tool_allowed_rejects(self) -> None:
        """Tool not in allowed_tools -> False."""
        executor = _make_executor(allowed_tools=["tavily_search"])
        assert executor.check_tool_allowed("dangerous_tool") is False

    def test_check_tool_allowed_empty_means_any(self) -> None:
        """Empty allowed_tools -> True (no restriction)."""
        executor = _make_executor(allowed_tools=[])
        assert executor.check_tool_allowed("any_tool") is True

    # -----------------------------------------------------------------------
    # Output parsing
    # -----------------------------------------------------------------------

    def test_parse_output_json(self) -> None:
        """Valid JSON -> parsed dict."""
        executor = _make_executor()
        result = executor._parse_output('{"answer": "hello"}')
        assert result == {"answer": "hello"}

    def test_parse_output_markdown_fenced_json(self) -> None:
        """```json ... ``` -> parsed dict."""
        executor = _make_executor()
        raw = '```json\n{"answer": "hello"}\n```'
        result = executor._parse_output(raw)
        assert result == {"answer": "hello"}

    def test_parse_output_plain_text_fallback(self) -> None:
        """Non-JSON -> {"text": ..., "raw": True}."""
        executor = _make_executor()
        raw = "This is just plain text, not JSON at all."
        result = executor._parse_output(raw)
        assert result["raw"] is True
        assert result["text"] == raw
