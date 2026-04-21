"""Canonical message contract for BLAIQ inter-node communication.

``BlaiqMessage`` is the single typed message shape that flows between
orchestrator nodes, agents, and the frontend.  It replaces ad-hoc dicts
with a validated Pydantic model that carries identity, tracing, and
lineage metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class BlaiqMessage(BaseModel):
    """Canonical message exchanged between BLAIQ nodes and agents.

    Every node that produces user-visible output or inter-agent data
    should wrap it in a ``BlaiqMessage`` so the full conversation is
    traceable end-to-end.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_message_id: str | None = None
    thread_id: str
    session_id: str
    run_id: str = ""
    tenant_id: str = ""

    sender: str  # node name or "user"
    role: Literal["user", "assistant", "system", "tool"] = "assistant"
    content: str | Dict[str, Any] = ""
    content_type: Literal[
        "text/plain",
        "text/markdown",
        "application/json",
        "text/html",
    ] = "text/plain"

    trace_context: Dict[str, str] = Field(default_factory=dict)
    memory_refs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_log_dict(self) -> Dict[str, Any]:
        """Lightweight dict for structured logging (excludes content)."""
        return {
            "message_id": self.message_id,
            "parent_message_id": self.parent_message_id,
            "thread_id": self.thread_id,
            "sender": self.sender,
            "role": self.role,
            "content_type": self.content_type,
            "memory_refs": self.memory_refs,
            "created_at": self.created_at.isoformat(),
        }


__all__ = [
    "BlaiqMessage",
]
