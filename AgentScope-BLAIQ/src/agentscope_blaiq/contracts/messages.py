"""
Message envelope contracts for the agent runtime.

Defines the canonical message types used for agent I/O, tool calls, tool
results, and handoffs. All types are plain dataclasses -- no runtime imports,
no agentscope dependency. This keeps the contracts layer lightweight,
serializable, and testable in isolation.

Key types:
    - MsgType: enum of message kinds (agent_input, agent_output, tool_call, ...)
    - RuntimeMsg: the canonical envelope for all agent communication
    - ToolCallMsg: specialized envelope for tool invocations
    - ToolResultMsg: envelope for tool execution results
    - MessageLog: append-only log supporting replay and chain traversal

Helper functions:
    - make_agent_input / make_agent_output / make_handoff: factory constructors
    - serialize_msg / deserialize_msg: JSON-safe round-trip serialization
    - validate_msg_schema: validates payload against declared harness schema
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Union
from uuid import uuid4

# Only contracts-layer imports -- no runtime dependencies.
from .registry import HarnessRegistry


# ============================================================================
# Enums
# ============================================================================


class MsgType(str, Enum):
    """Kind of message flowing through the runtime."""

    AGENT_INPUT = "agent_input"
    AGENT_OUTPUT = "agent_output"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    HANDOFF = "handoff"


# ============================================================================
# Message dataclasses
# ============================================================================


def _utc_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    """Generate a compact UUID-4 hex string."""
    return uuid4().hex


@dataclass
class RuntimeMsg:
    """Canonical envelope for agent I/O.

    Every message exchanged between agents, or between an agent and the
    orchestrator, is wrapped in a ``RuntimeMsg``. The ``parent_msg_id``
    field links an output back to the input that produced it, enabling
    full chain-of-custody tracing.

    Attributes:
        msg_id: Unique identifier (uuid4 hex).
        msg_type: Discriminator for the message kind.
        workflow_id: Owning workflow, or ``None`` for ad-hoc messages.
        node_id: DAG node that produced / will consume this message.
        agent_id: Agent that sent or will receive this message.
        payload: The actual data -- schema varies by ``schema_ref``.
        timestamp: ISO-8601 UTC timestamp.
        attempt: Retry counter (0 = first attempt).
        parent_msg_id: Links an output to its originating input.
        schema_ref: Optional name of the contract the payload conforms to
            (e.g. ``"EvidencePack"``).
    """

    msg_id: str = field(default_factory=_new_id)
    msg_type: MsgType = MsgType.AGENT_INPUT
    workflow_id: str | None = None
    node_id: str = ""
    agent_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_iso)
    attempt: int = 0
    parent_msg_id: str | None = None
    schema_ref: str | None = None


@dataclass
class ToolCallMsg:
    """Specialized envelope for a tool invocation.

    Attributes:
        call_id: Unique call identifier (uuid4 hex).
        tool_id: Registered tool being called.
        agent_id: Agent that initiated the call.
        args: Arguments passed to the tool.
        workflow_id: Owning workflow, or ``None``.
        node_id: DAG node context.
        timestamp: ISO-8601 UTC timestamp.
    """

    call_id: str = field(default_factory=_new_id)
    tool_id: str = ""
    agent_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    workflow_id: str | None = None
    node_id: str = ""
    timestamp: str = field(default_factory=_utc_iso)


@dataclass
class ToolResultMsg:
    """Envelope for a tool execution result.

    The ``call_id`` matches the originating :class:`ToolCallMsg` so the
    caller can correlate request/response pairs.

    Attributes:
        call_id: Matches the originating ``ToolCallMsg.call_id``.
        tool_id: Tool that produced this result.
        result: The tool's return value (arbitrary).
        ok: ``True`` if the call succeeded.
        error: Error description when ``ok`` is ``False``.
        duration_ms: Wall-clock execution time in milliseconds.
        timestamp: ISO-8601 UTC timestamp.
    """

    call_id: str = ""
    tool_id: str = ""
    result: Any = None
    ok: bool = True
    error: str | None = None
    duration_ms: float | None = None
    timestamp: str = field(default_factory=_utc_iso)


# Union type for all message kinds.
AnyMsg = Union[RuntimeMsg, ToolCallMsg, ToolResultMsg]


# ============================================================================
# Factory helpers
# ============================================================================


def make_agent_input(
    workflow_id: str | None,
    node_id: str,
    agent_id: str,
    payload: dict[str, Any],
    schema_ref: str | None = None,
    attempt: int = 0,
) -> RuntimeMsg:
    """Create an ``AGENT_INPUT`` runtime message.

    Args:
        workflow_id: Owning workflow ID (may be ``None``).
        node_id: DAG node that will consume this input.
        agent_id: Target agent ID.
        payload: Input data for the agent.
        schema_ref: Optional schema name for payload validation.
        attempt: Retry counter (0 = first attempt).

    Returns:
        A fully populated :class:`RuntimeMsg` with ``msg_type=AGENT_INPUT``.
    """
    return RuntimeMsg(
        msg_type=MsgType.AGENT_INPUT,
        workflow_id=workflow_id,
        node_id=node_id,
        agent_id=agent_id,
        payload=payload,
        schema_ref=schema_ref,
        attempt=attempt,
    )


def make_agent_output(
    input_msg: RuntimeMsg,
    payload: dict[str, Any],
    schema_ref: str | None = None,
) -> RuntimeMsg:
    """Create an ``AGENT_OUTPUT`` linked to its originating input.

    The ``parent_msg_id`` is set to ``input_msg.msg_id`` so the full
    request/response chain can be reconstructed.

    Args:
        input_msg: The input message this output responds to.
        payload: Output data from the agent.
        schema_ref: Optional schema name for payload validation.

    Returns:
        A :class:`RuntimeMsg` with ``msg_type=AGENT_OUTPUT`` and
        ``parent_msg_id`` pointing to *input_msg*.
    """
    return RuntimeMsg(
        msg_type=MsgType.AGENT_OUTPUT,
        workflow_id=input_msg.workflow_id,
        node_id=input_msg.node_id,
        agent_id=input_msg.agent_id,
        payload=payload,
        parent_msg_id=input_msg.msg_id,
        schema_ref=schema_ref,
        attempt=input_msg.attempt,
    )


def make_handoff(
    source_msg: RuntimeMsg,
    target_node_id: str,
    target_agent_id: str,
) -> RuntimeMsg:
    """Create a ``HANDOFF`` message routing control to a new node/agent.

    Args:
        source_msg: The message whose output triggers the handoff.
        target_node_id: Node ID to hand off to.
        target_agent_id: Agent ID that will receive control.

    Returns:
        A :class:`RuntimeMsg` with ``msg_type=HANDOFF``, carrying the
        source payload forward and linking via ``parent_msg_id``.
    """
    return RuntimeMsg(
        msg_type=MsgType.HANDOFF,
        workflow_id=source_msg.workflow_id,
        node_id=target_node_id,
        agent_id=target_agent_id,
        payload=source_msg.payload,
        parent_msg_id=source_msg.msg_id,
        attempt=0,
    )


# ============================================================================
# Serialization
# ============================================================================

# Discriminator key used in serialized dicts.
_MSG_KIND_KEY = "__msg_kind__"


def serialize_msg(msg: AnyMsg) -> dict[str, Any]:
    """Serialize a message to a JSON-safe dictionary.

    Adds a ``__msg_kind__`` discriminator so :func:`deserialize_msg` can
    reconstruct the correct type.

    Args:
        msg: Any of :class:`RuntimeMsg`, :class:`ToolCallMsg`, or
            :class:`ToolResultMsg`.

    Returns:
        A plain ``dict`` suitable for ``json.dumps``.

    Raises:
        TypeError: If *msg* is not a recognised message type.
    """
    if isinstance(msg, RuntimeMsg):
        return {
            _MSG_KIND_KEY: "RuntimeMsg",
            "msg_id": msg.msg_id,
            "msg_type": msg.msg_type.value,
            "workflow_id": msg.workflow_id,
            "node_id": msg.node_id,
            "agent_id": msg.agent_id,
            "payload": msg.payload,
            "timestamp": msg.timestamp,
            "attempt": msg.attempt,
            "parent_msg_id": msg.parent_msg_id,
            "schema_ref": msg.schema_ref,
        }
    if isinstance(msg, ToolCallMsg):
        return {
            _MSG_KIND_KEY: "ToolCallMsg",
            "call_id": msg.call_id,
            "tool_id": msg.tool_id,
            "agent_id": msg.agent_id,
            "args": msg.args,
            "workflow_id": msg.workflow_id,
            "node_id": msg.node_id,
            "timestamp": msg.timestamp,
        }
    if isinstance(msg, ToolResultMsg):
        return {
            _MSG_KIND_KEY: "ToolResultMsg",
            "call_id": msg.call_id,
            "tool_id": msg.tool_id,
            "result": msg.result,
            "ok": msg.ok,
            "error": msg.error,
            "duration_ms": msg.duration_ms,
            "timestamp": msg.timestamp,
        }
    raise TypeError(f"Cannot serialize unknown message type: {type(msg).__name__}")


def deserialize_msg(data: dict[str, Any]) -> AnyMsg:
    """Reconstruct a message from a serialized dictionary.

    Expects the ``__msg_kind__`` discriminator produced by
    :func:`serialize_msg`.

    Args:
        data: Dictionary previously produced by :func:`serialize_msg`.

    Returns:
        The appropriate message dataclass instance.

    Raises:
        ValueError: If the discriminator is missing or unrecognised.
    """
    kind = data.get(_MSG_KIND_KEY)
    if kind is None:
        raise ValueError(
            "Missing '__msg_kind__' discriminator -- cannot deserialize"
        )

    if kind == "RuntimeMsg":
        return RuntimeMsg(
            msg_id=data["msg_id"],
            msg_type=MsgType(data["msg_type"]),
            workflow_id=data.get("workflow_id"),
            node_id=data.get("node_id", ""),
            agent_id=data.get("agent_id", ""),
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", ""),
            attempt=data.get("attempt", 0),
            parent_msg_id=data.get("parent_msg_id"),
            schema_ref=data.get("schema_ref"),
        )
    if kind == "ToolCallMsg":
        return ToolCallMsg(
            call_id=data["call_id"],
            tool_id=data.get("tool_id", ""),
            agent_id=data.get("agent_id", ""),
            args=data.get("args", {}),
            workflow_id=data.get("workflow_id"),
            node_id=data.get("node_id", ""),
            timestamp=data.get("timestamp", ""),
        )
    if kind == "ToolResultMsg":
        return ToolResultMsg(
            call_id=data["call_id"],
            tool_id=data.get("tool_id", ""),
            result=data.get("result"),
            ok=data.get("ok", True),
            error=data.get("error"),
            duration_ms=data.get("duration_ms"),
            timestamp=data.get("timestamp", ""),
        )
    raise ValueError(f"Unknown message kind: {kind!r}")


# ============================================================================
# MessageLog -- append-only log for replay
# ============================================================================


class MessageLog:
    """Append-only message log supporting replay and chain traversal.

    All messages appended to the log are stored in insertion order.
    Provides efficient lookup by ``msg_id`` (for chain traversal),
    ``node_id``, and ``workflow_id``.

    Thread safety: *not* thread-safe. External synchronisation is
    required for concurrent access.
    """

    def __init__(self) -> None:
        """Initialise an empty message log."""
        self._messages: list[AnyMsg] = []
        self._index_by_id: dict[str, AnyMsg] = {}

    @property
    def messages(self) -> list[AnyMsg]:
        """Return the ordered list of all messages (read-only view)."""
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def append(self, msg: AnyMsg) -> None:
        """Append a message to the log.

        Args:
            msg: A :class:`RuntimeMsg`, :class:`ToolCallMsg`, or
                :class:`ToolResultMsg` to record.
        """
        self._messages.append(msg)
        # Index by the message's primary ID for chain traversal.
        msg_id = _get_msg_id(msg)
        if msg_id:
            self._index_by_id[msg_id] = msg

    def get_chain(self, msg_id: str) -> list[AnyMsg]:
        """Follow ``parent_msg_id`` links to reconstruct a causal chain.

        Returns messages in chronological order (earliest first).
        Only :class:`RuntimeMsg` instances carry ``parent_msg_id``; tool
        messages are terminal in the chain.

        Args:
            msg_id: Starting message ID to trace backwards from.

        Returns:
            Ordered list from root to the message identified by *msg_id*.
        """
        chain: list[AnyMsg] = []
        current_id: str | None = msg_id

        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            msg = self._index_by_id.get(current_id)
            if msg is None:
                break
            chain.append(msg)
            # Only RuntimeMsg has parent_msg_id.
            if isinstance(msg, RuntimeMsg):
                current_id = msg.parent_msg_id
            else:
                break

        chain.reverse()
        return chain

    def get_by_node(self, node_id: str) -> list[AnyMsg]:
        """Return all messages associated with a given DAG node.

        Args:
            node_id: The node ID to filter by.

        Returns:
            Messages in insertion order matching the node.
        """
        return [
            m for m in self._messages
            if _get_node_id(m) == node_id
        ]

    def get_by_workflow(self, workflow_id: str) -> list[AnyMsg]:
        """Return all messages belonging to a workflow.

        Args:
            workflow_id: The workflow ID to filter by.

        Returns:
            Messages in insertion order matching the workflow.
        """
        return [
            m for m in self._messages
            if _get_workflow_id(m) == workflow_id
        ]

    def to_replay_log(self) -> list[dict[str, Any]]:
        """Serialize the full log for persistence / replay.

        Returns:
            A list of JSON-safe dictionaries, one per message.
        """
        return [serialize_msg(m) for m in self._messages]

    @classmethod
    def from_replay_log(cls, data: list[dict[str, Any]]) -> MessageLog:
        """Reconstruct a :class:`MessageLog` from serialized data.

        Args:
            data: List of dicts previously produced by
                :meth:`to_replay_log`.

        Returns:
            A new :class:`MessageLog` containing all deserialized messages.
        """
        log = cls()
        for item in data:
            log.append(deserialize_msg(item))
        return log


# ============================================================================
# Schema validation
# ============================================================================


def validate_msg_schema(
    msg: RuntimeMsg,
    registry: HarnessRegistry,
) -> tuple[bool, list[str]]:
    """Validate a RuntimeMsg payload against the declared agent schema.

    For ``AGENT_INPUT`` messages the payload is checked against the
    agent's ``input_schema``; for ``AGENT_OUTPUT`` against
    ``output_schema``. Other message types are considered valid by
    default (tool call/result schemas are validated elsewhere).

    This performs a lightweight check for required top-level keys only.
    Full JSON-Schema validation can be layered on top.

    Args:
        msg: The runtime message to validate.
        registry: The harness registry containing agent definitions.

    Returns:
        A ``(is_valid, errors)`` tuple. An empty error list means valid.
    """
    errors: list[str] = []

    harness = registry.get_agent(msg.agent_id)
    if harness is None:
        errors.append(f"Agent '{msg.agent_id}' not found in registry")
        return False, errors

    if msg.msg_type == MsgType.AGENT_INPUT:
        schema = harness.input_schema
    elif msg.msg_type == MsgType.AGENT_OUTPUT:
        schema = harness.output_schema
    else:
        # Other message types are not validated against agent schemas.
        return True, []

    # Check required keys from the JSON schema.
    required_keys: list[str] = schema.get("required", [])
    for key in required_keys:
        if key not in msg.payload:
            errors.append(
                f"Missing required key '{key}' in {msg.msg_type.value} "
                f"payload for agent '{msg.agent_id}'"
            )

    # Check declared property types (shallow, top-level only).
    properties: dict[str, Any] = schema.get("properties", {})
    for key, prop_schema in properties.items():
        if key not in msg.payload:
            continue
        expected_type = prop_schema.get("type")
        value = msg.payload[key]
        if expected_type and not _type_matches(value, expected_type):
            errors.append(
                f"Key '{key}' in {msg.msg_type.value} payload for "
                f"agent '{msg.agent_id}' expected type '{expected_type}', "
                f"got {type(value).__name__}"
            )

    return len(errors) == 0, errors


# ============================================================================
# Internal helpers
# ============================================================================

_JSON_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _type_matches(value: Any, json_type: str) -> bool:
    """Check if *value* matches the JSON-Schema *json_type* string."""
    allowed = _JSON_TYPE_MAP.get(json_type)
    if allowed is None:
        # Unknown type -- pass through.
        return True
    return isinstance(value, allowed)


def _get_msg_id(msg: AnyMsg) -> str:
    """Extract the primary ID from any message type."""
    if isinstance(msg, RuntimeMsg):
        return msg.msg_id
    if isinstance(msg, (ToolCallMsg, ToolResultMsg)):
        return msg.call_id
    return ""


def _get_node_id(msg: AnyMsg) -> str:
    """Extract node_id from any message type."""
    if isinstance(msg, (RuntimeMsg, ToolCallMsg)):
        return msg.node_id
    return ""


def _get_workflow_id(msg: AnyMsg) -> str | None:
    """Extract workflow_id from any message type."""
    if isinstance(msg, (RuntimeMsg, ToolCallMsg)):
        return msg.workflow_id
    return None
