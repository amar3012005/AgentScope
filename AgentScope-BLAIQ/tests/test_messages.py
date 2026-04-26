"""Comprehensive tests for agentscope_blaiq.contracts.messages."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from agentscope_blaiq.contracts.messages import (
    MessageLog,
    MsgType,
    RuntimeMsg,
    ToolCallMsg,
    ToolResultMsg,
    deserialize_msg,
    make_agent_input,
    make_agent_output,
    make_handoff,
    serialize_msg,
    validate_msg_schema,
)
from agentscope_blaiq.contracts.registry import (
    HarnessRegistry,
    get_registry,
    reset_registry,
)


# ============================================================================
# Helpers
# ============================================================================

_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")
_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _is_uuid_hex(value: str) -> bool:
    return bool(_UUID_HEX_RE.match(value))


def _is_iso_timestamp(value: str) -> bool:
    return bool(_ISO_UTC_RE.match(value))


# ============================================================================
# TestMsgType
# ============================================================================


class TestMsgType:
    """Tests for the MsgType enum."""

    def test_has_five_members(self) -> None:
        assert len(MsgType) == 5

    def test_expected_values(self) -> None:
        assert MsgType.AGENT_INPUT.value == "agent_input"
        assert MsgType.AGENT_OUTPUT.value == "agent_output"
        assert MsgType.TOOL_CALL.value == "tool_call"
        assert MsgType.TOOL_RESULT.value == "tool_result"
        assert MsgType.HANDOFF.value == "handoff"

    def test_str_mixin(self) -> None:
        """MsgType inherits from str -- string operations should work."""
        assert isinstance(MsgType.AGENT_INPUT, str)
        assert MsgType.AGENT_INPUT == "agent_input"
        # str() always returns the value thanks to the str mixin
        assert str(MsgType.HANDOFF) == "MsgType.HANDOFF" or str(MsgType.HANDOFF) == "handoff"
        # Equality with plain strings works regardless of format behavior
        assert MsgType.HANDOFF == "handoff"
        assert "handoff" in MsgType.HANDOFF

    def test_construct_from_value(self) -> None:
        assert MsgType("agent_output") is MsgType.AGENT_OUTPUT


# ============================================================================
# TestRuntimeMsg
# ============================================================================


class TestRuntimeMsg:
    """Tests for the RuntimeMsg dataclass."""

    def test_defaults(self) -> None:
        msg = RuntimeMsg()
        assert _is_uuid_hex(msg.msg_id)
        assert msg.msg_type is MsgType.AGENT_INPUT
        assert msg.workflow_id is None
        assert msg.node_id == ""
        assert msg.agent_id == ""
        assert msg.payload == {}
        assert _is_iso_timestamp(msg.timestamp)
        assert msg.attempt == 0
        assert msg.parent_msg_id is None
        assert msg.schema_ref is None

    def test_custom_construction(self) -> None:
        msg = RuntimeMsg(
            msg_id="abc123",
            msg_type=MsgType.AGENT_OUTPUT,
            workflow_id="wf-1",
            node_id="n1",
            agent_id="strategist",
            payload={"key": "value"},
            timestamp="2026-01-01T00:00:00Z",
            attempt=2,
            parent_msg_id="parent-1",
            schema_ref="EvidencePack",
        )
        assert msg.msg_id == "abc123"
        assert msg.msg_type is MsgType.AGENT_OUTPUT
        assert msg.workflow_id == "wf-1"
        assert msg.node_id == "n1"
        assert msg.agent_id == "strategist"
        assert msg.payload == {"key": "value"}
        assert msg.timestamp == "2026-01-01T00:00:00Z"
        assert msg.attempt == 2
        assert msg.parent_msg_id == "parent-1"
        assert msg.schema_ref == "EvidencePack"

    def test_msg_id_uniqueness(self) -> None:
        ids = {RuntimeMsg().msg_id for _ in range(100)}
        assert len(ids) == 100

    def test_timestamp_is_recent_utc(self) -> None:
        before = datetime.now(timezone.utc)
        msg = RuntimeMsg()
        after = datetime.now(timezone.utc)
        # The timestamp should end with Z (UTC)
        assert msg.timestamp.endswith("Z")
        ts = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
        assert before <= ts <= after


# ============================================================================
# TestToolCallMsg
# ============================================================================


class TestToolCallMsg:
    """Tests for the ToolCallMsg dataclass."""

    def test_defaults(self) -> None:
        msg = ToolCallMsg()
        assert _is_uuid_hex(msg.call_id)
        assert msg.tool_id == ""
        assert msg.agent_id == ""
        assert msg.args == {}
        assert msg.workflow_id is None
        assert msg.node_id == ""
        assert _is_iso_timestamp(msg.timestamp)

    def test_custom_construction(self) -> None:
        msg = ToolCallMsg(
            call_id="call-1",
            tool_id="hivemind_recall",
            agent_id="research",
            args={"query": "hello"},
            workflow_id="wf-1",
            node_id="n2",
            timestamp="2026-04-22T12:00:00Z",
        )
        assert msg.call_id == "call-1"
        assert msg.tool_id == "hivemind_recall"
        assert msg.agent_id == "research"
        assert msg.args == {"query": "hello"}
        assert msg.workflow_id == "wf-1"
        assert msg.node_id == "n2"

    def test_call_id_uniqueness(self) -> None:
        ids = {ToolCallMsg().call_id for _ in range(50)}
        assert len(ids) == 50


# ============================================================================
# TestToolResultMsg
# ============================================================================


class TestToolResultMsg:
    """Tests for the ToolResultMsg dataclass."""

    def test_defaults(self) -> None:
        msg = ToolResultMsg()
        assert msg.call_id == ""
        assert msg.tool_id == ""
        assert msg.result is None
        assert msg.ok is True
        assert msg.error is None
        assert msg.duration_ms is None
        assert _is_iso_timestamp(msg.timestamp)

    def test_ok_result(self) -> None:
        msg = ToolResultMsg(
            call_id="c1",
            tool_id="hivemind_recall",
            result={"data": [1, 2, 3]},
            ok=True,
            duration_ms=42.5,
        )
        assert msg.ok is True
        assert msg.error is None
        assert msg.result == {"data": [1, 2, 3]}
        assert msg.duration_ms == 42.5

    def test_error_result(self) -> None:
        msg = ToolResultMsg(
            call_id="c2",
            tool_id="sandbox_execute",
            result=None,
            ok=False,
            error="Timeout exceeded",
            duration_ms=30000.0,
        )
        assert msg.ok is False
        assert msg.error == "Timeout exceeded"
        assert msg.result is None

    def test_default_timestamp_is_utc(self) -> None:
        msg = ToolResultMsg()
        assert msg.timestamp.endswith("Z")


# ============================================================================
# TestFactoryHelpers
# ============================================================================


class TestFactoryHelpers:
    """Tests for make_agent_input, make_agent_output, make_handoff."""

    def test_make_agent_input_basic(self) -> None:
        msg = make_agent_input(
            workflow_id="wf-1",
            node_id="n1",
            agent_id="strategist",
            payload={"user_request": "hello"},
        )
        assert msg.msg_type is MsgType.AGENT_INPUT
        assert msg.workflow_id == "wf-1"
        assert msg.node_id == "n1"
        assert msg.agent_id == "strategist"
        assert msg.payload == {"user_request": "hello"}
        assert _is_uuid_hex(msg.msg_id)
        assert _is_iso_timestamp(msg.timestamp)
        assert msg.attempt == 0
        assert msg.schema_ref is None

    def test_make_agent_input_with_schema_ref(self) -> None:
        msg = make_agent_input(
            workflow_id=None,
            node_id="n2",
            agent_id="research",
            payload={},
            schema_ref="EvidencePack",
            attempt=3,
        )
        assert msg.workflow_id is None
        assert msg.schema_ref == "EvidencePack"
        assert msg.attempt == 3

    def test_make_agent_output_links_parent(self) -> None:
        inp = make_agent_input(
            workflow_id="wf-1",
            node_id="n1",
            agent_id="strategist",
            payload={"user_request": "plan"},
        )
        out = make_agent_output(inp, payload={"workflow_id": "wf-content"})

        assert out.msg_type is MsgType.AGENT_OUTPUT
        assert out.parent_msg_id == inp.msg_id
        assert out.workflow_id == inp.workflow_id
        assert out.node_id == inp.node_id
        assert out.agent_id == inp.agent_id
        assert out.attempt == inp.attempt
        assert out.payload == {"workflow_id": "wf-content"}
        # Output has its own unique msg_id
        assert out.msg_id != inp.msg_id

    def test_make_agent_output_with_schema_ref(self) -> None:
        inp = RuntimeMsg(agent_id="research", node_id="n1")
        out = make_agent_output(inp, payload={"summary": "done"}, schema_ref="ResearchOutput")
        assert out.schema_ref == "ResearchOutput"

    def test_make_handoff_creates_handoff_type(self) -> None:
        source = make_agent_input(
            workflow_id="wf-1",
            node_id="n1",
            agent_id="strategist",
            payload={"data": "important"},
        )
        handoff = make_handoff(source, target_node_id="n2", target_agent_id="research")

        assert handoff.msg_type is MsgType.HANDOFF
        assert handoff.parent_msg_id == source.msg_id
        assert handoff.workflow_id == source.workflow_id
        assert handoff.node_id == "n2"
        assert handoff.agent_id == "research"
        assert handoff.payload == source.payload
        assert handoff.attempt == 0

    def test_make_handoff_carries_payload(self) -> None:
        source = RuntimeMsg(
            payload={"evidence": ["a", "b"]},
            workflow_id="wf-2",
            node_id="n5",
            agent_id="content_director",
        )
        handoff = make_handoff(source, target_node_id="n6", target_agent_id="vangogh")
        assert handoff.payload == {"evidence": ["a", "b"]}


# ============================================================================
# TestSerialization
# ============================================================================


class TestSerialization:
    """Tests for serialize_msg / deserialize_msg round-trips."""

    def test_runtime_msg_round_trip(self) -> None:
        original = RuntimeMsg(
            msg_type=MsgType.AGENT_OUTPUT,
            workflow_id="wf-1",
            node_id="n1",
            agent_id="strategist",
            payload={"key": "value", "nested": {"a": 1}},
            attempt=2,
            parent_msg_id="parent-abc",
            schema_ref="StrategyOutput",
        )
        data = serialize_msg(original)
        assert data["__msg_kind__"] == "RuntimeMsg"
        assert data["msg_type"] == "agent_output"

        restored = deserialize_msg(data)
        assert isinstance(restored, RuntimeMsg)
        assert restored.msg_id == original.msg_id
        assert restored.msg_type is MsgType.AGENT_OUTPUT
        assert restored.payload == original.payload
        assert restored.parent_msg_id == original.parent_msg_id
        assert restored.schema_ref == original.schema_ref

    def test_tool_call_msg_round_trip(self) -> None:
        original = ToolCallMsg(
            tool_id="hivemind_recall",
            agent_id="research",
            args={"query": "test", "top_k": 5},
            workflow_id="wf-1",
            node_id="n3",
        )
        data = serialize_msg(original)
        assert data["__msg_kind__"] == "ToolCallMsg"

        restored = deserialize_msg(data)
        assert isinstance(restored, ToolCallMsg)
        assert restored.call_id == original.call_id
        assert restored.tool_id == "hivemind_recall"
        assert restored.args == {"query": "test", "top_k": 5}

    def test_tool_result_msg_round_trip(self) -> None:
        original = ToolResultMsg(
            call_id="call-xyz",
            tool_id="sandbox_execute",
            result={"output": "42"},
            ok=True,
            duration_ms=150.0,
        )
        data = serialize_msg(original)
        assert data["__msg_kind__"] == "ToolResultMsg"

        restored = deserialize_msg(data)
        assert isinstance(restored, ToolResultMsg)
        assert restored.call_id == "call-xyz"
        assert restored.ok is True
        assert restored.result == {"output": "42"}
        assert restored.duration_ms == 150.0

    def test_tool_result_error_round_trip(self) -> None:
        original = ToolResultMsg(
            call_id="c-err",
            tool_id="data_upload",
            ok=False,
            error="File too large",
        )
        data = serialize_msg(original)
        restored = deserialize_msg(data)
        assert isinstance(restored, ToolResultMsg)
        assert restored.ok is False
        assert restored.error == "File too large"

    def test_deserialize_missing_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Missing '__msg_kind__'"):
            deserialize_msg({"msg_id": "abc"})

    def test_deserialize_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown message kind"):
            deserialize_msg({"__msg_kind__": "SomethingElse"})

    def test_serialize_unknown_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Cannot serialize unknown"):
            serialize_msg("not a message")  # type: ignore[arg-type]

    def test_discriminator_key_present(self) -> None:
        for msg in [RuntimeMsg(), ToolCallMsg(), ToolResultMsg()]:
            data = serialize_msg(msg)
            assert "__msg_kind__" in data


# ============================================================================
# TestMessageLog
# ============================================================================


class TestMessageLog:
    """Tests for the MessageLog append-only log."""

    def test_empty_log(self) -> None:
        log = MessageLog()
        assert len(log) == 0
        assert log.messages == []

    def test_append_and_len(self) -> None:
        log = MessageLog()
        log.append(RuntimeMsg(msg_id="a"))
        log.append(ToolCallMsg(call_id="b"))
        log.append(ToolResultMsg(call_id="c"))
        assert len(log) == 3

    def test_messages_returns_copy(self) -> None:
        log = MessageLog()
        log.append(RuntimeMsg(msg_id="a"))
        msgs = log.messages
        msgs.clear()
        # Internal list should be unaffected
        assert len(log) == 1

    def test_get_chain_follows_parent_links(self) -> None:
        log = MessageLog()
        inp = make_agent_input(
            workflow_id="wf-1", node_id="n1", agent_id="strategist",
            payload={"user_request": "hi"},
        )
        out = make_agent_output(inp, payload={"plan": "done"})
        handoff = make_handoff(out, target_node_id="n2", target_agent_id="research")

        log.append(inp)
        log.append(out)
        log.append(handoff)

        chain = log.get_chain(handoff.msg_id)
        assert len(chain) == 3
        # Chronological order: inp -> out -> handoff
        assert chain[0].msg_id == inp.msg_id  # type: ignore[union-attr]
        assert chain[1].msg_id == out.msg_id  # type: ignore[union-attr]
        assert chain[2].msg_id == handoff.msg_id  # type: ignore[union-attr]

    def test_get_chain_single_message(self) -> None:
        log = MessageLog()
        msg = RuntimeMsg(msg_id="solo")
        log.append(msg)
        chain = log.get_chain("solo")
        assert len(chain) == 1

    def test_get_chain_unknown_id_returns_empty(self) -> None:
        log = MessageLog()
        assert log.get_chain("nonexistent") == []

    def test_get_by_node_filters_correctly(self) -> None:
        log = MessageLog()
        m1 = RuntimeMsg(msg_id="a", node_id="n1")
        m2 = RuntimeMsg(msg_id="b", node_id="n2")
        m3 = ToolCallMsg(call_id="c", node_id="n1")
        m4 = ToolResultMsg(call_id="d")  # no node_id
        log.append(m1)
        log.append(m2)
        log.append(m3)
        log.append(m4)

        results = log.get_by_node("n1")
        assert len(results) == 2
        ids = [
            r.msg_id if isinstance(r, RuntimeMsg) else r.call_id
            for r in results
        ]
        assert ids == ["a", "c"]

    def test_get_by_workflow_filters_correctly(self) -> None:
        log = MessageLog()
        m1 = RuntimeMsg(msg_id="a", workflow_id="wf-1")
        m2 = RuntimeMsg(msg_id="b", workflow_id="wf-2")
        m3 = ToolCallMsg(call_id="c", workflow_id="wf-1")
        m4 = ToolResultMsg(call_id="d")  # no workflow_id
        log.append(m1)
        log.append(m2)
        log.append(m3)
        log.append(m4)

        results = log.get_by_workflow("wf-1")
        assert len(results) == 2

    def test_to_replay_log_from_replay_log_round_trip(self) -> None:
        log = MessageLog()
        log.append(RuntimeMsg(
            msg_type=MsgType.AGENT_INPUT,
            workflow_id="wf-1",
            node_id="n1",
            agent_id="strategist",
            payload={"user_request": "analyze"},
        ))
        log.append(ToolCallMsg(
            tool_id="hivemind_recall",
            agent_id="research",
            args={"query": "data"},
        ))
        log.append(ToolResultMsg(
            call_id="r1",
            tool_id="hivemind_recall",
            result={"docs": []},
            ok=True,
        ))

        replay_data = log.to_replay_log()
        assert isinstance(replay_data, list)
        assert len(replay_data) == 3

        restored_log = MessageLog.from_replay_log(replay_data)
        assert len(restored_log) == 3

        # Verify message types preserved
        msgs = restored_log.messages
        assert isinstance(msgs[0], RuntimeMsg)
        assert isinstance(msgs[1], ToolCallMsg)
        assert isinstance(msgs[2], ToolResultMsg)

        # Verify data preserved
        assert msgs[0].agent_id == "strategist"  # type: ignore[union-attr]
        assert msgs[1].tool_id == "hivemind_recall"  # type: ignore[union-attr]
        assert msgs[2].ok is True  # type: ignore[union-attr]

    def test_replay_round_trip_preserves_chain(self) -> None:
        """Ensure parent_msg_id links survive serialization."""
        log = MessageLog()
        inp = make_agent_input(
            workflow_id="wf-1", node_id="n1", agent_id="strategist",
            payload={"user_request": "test"},
        )
        out = make_agent_output(inp, payload={"result": "ok"})
        log.append(inp)
        log.append(out)

        restored = MessageLog.from_replay_log(log.to_replay_log())
        chain = restored.get_chain(out.msg_id)
        assert len(chain) == 2
        assert chain[0].msg_id == inp.msg_id  # type: ignore[union-attr]


# ============================================================================
# TestValidateMsgSchema
# ============================================================================


class TestValidateMsgSchema:
    """Tests for validate_msg_schema using real registry harnesses."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        """Reset global registry before each test."""
        reset_registry()

    def _registry(self) -> HarnessRegistry:
        return get_registry()

    def test_valid_agent_input_passes(self) -> None:
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_INPUT,
            agent_id="strategist",
            payload={"user_request": "Analyze this topic"},
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is True
        assert errors == []

    def test_missing_required_field_fails(self) -> None:
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_INPUT,
            agent_id="strategist",
            payload={},  # missing "user_request"
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is False
        assert any("user_request" in e for e in errors)

    def test_wrong_type_fails(self) -> None:
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_INPUT,
            agent_id="strategist",
            payload={"user_request": 12345},  # should be string
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is False
        assert any("expected type" in e for e in errors)

    def test_output_schema_validation(self) -> None:
        reg = self._registry()
        # Strategist output requires workflow_id (string) and workflow_plan (object)
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_OUTPUT,
            agent_id="strategist",
            payload={"workflow_id": "wf-content", "query": "test query", "workflow_plan": {"steps": []}},
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is True
        assert errors == []

    def test_output_schema_missing_required_fails(self) -> None:
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_OUTPUT,
            agent_id="strategist",
            payload={},  # missing workflow_id and workflow_plan
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is False
        assert len(errors) >= 2

    def test_unknown_agent_fails(self) -> None:
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_INPUT,
            agent_id="nonexistent_agent_xyz",
            payload={"data": "test"},
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is False
        assert any("not found" in e for e in errors)

    def test_tool_call_type_skips_validation(self) -> None:
        """TOOL_CALL messages are not validated against agent schemas."""
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.TOOL_CALL,
            agent_id="strategist",
            payload={},
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is True
        assert errors == []

    def test_handoff_type_skips_validation(self) -> None:
        """HANDOFF messages are not validated against agent schemas."""
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.HANDOFF,
            agent_id="strategist",
            payload={},
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is True
        assert errors == []

    def test_valid_payload_with_optional_fields(self) -> None:
        """Extra fields in payload that aren't in schema should be fine."""
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_INPUT,
            agent_id="strategist",
            payload={
                "user_request": "do the thing",
                "extra_field": "should not cause error",
            },
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is True

    def test_wrong_type_on_optional_field(self) -> None:
        """A declared property with wrong type should fail even if not required."""
        reg = self._registry()
        msg = RuntimeMsg(
            msg_type=MsgType.AGENT_INPUT,
            agent_id="strategist",
            payload={
                "user_request": "ok",
                "agent_catalog": "should be array, not string",
            },
        )
        valid, errors = validate_msg_schema(msg, reg)
        assert valid is False
        assert any("agent_catalog" in e for e in errors)
