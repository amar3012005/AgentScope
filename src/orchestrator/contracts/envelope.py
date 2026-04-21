"""MCP Envelope for inter-agent communication.

Defines the canonical message envelope used by all BLAIQ agents to exchange
work requests.  The envelope carries identity, intent, payload, constraints,
and governance policy references so that every hop in a multi-agent workflow
is fully traceable and auditable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ConstraintConfig(BaseModel):
    """Runtime constraints attached to a mission envelope."""

    model_config = ConfigDict(extra="forbid")

    hitl_required: bool = False
    read_only: bool = False
    timeout_seconds: int = 180
    max_tokens: int = 1200


class MCPEnvelope(BaseModel):
    """Canonical inter-agent message envelope.

    Every agent-to-agent call is wrapped in an ``MCPEnvelope`` so the
    orchestrator can enforce idempotency, tracing, and governance policies
    uniformly.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: str = Field(default_factory=lambda: str(uuid4()))
    idempotency_key: str = Field(
        ...,
        description="sha256(thread_id + intent + payload_hash)[:16]",
    )
    thread_id: str
    run_id: str = ""  # Temporal workflow run ID
    tenant_id: str
    collection_name: str  # Qdrant collection = Neo4j filter_label
    intent: str  # e.g. "retrieve_evidence" | "generate_pitch_deck"
    payload: Dict[str, Any] = Field(default_factory=dict)
    constraints: ConstraintConfig = Field(default_factory=ConstraintConfig)
    policy_refs: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        *,
        thread_id: str,
        intent: str,
        tenant_id: str,
        collection_name: str,
        payload: Dict[str, Any] | None = None,
        run_id: str = "",
        constraints: ConstraintConfig | None = None,
        policy_refs: List[str] | None = None,
    ) -> MCPEnvelope:
        """Build an envelope with an auto-generated idempotency key.

        The key is derived from ``sha256(thread_id:intent:sorted_payload)[:16]``
        to ensure deterministic deduplication for identical requests.
        """
        payload = payload or {}
        idempotency_key = hashlib.sha256(
            f"{thread_id}:{intent}:{json.dumps(payload, sort_keys=True)}".encode()
        ).hexdigest()[:16]

        return cls(
            thread_id=thread_id,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            collection_name=collection_name,
            intent=intent,
            payload=payload,
            run_id=run_id,
            constraints=constraints or ConstraintConfig(),
            policy_refs=policy_refs or [],
        )

    def to_header_value(self) -> str:
        """Serialize the envelope safely for HTTP headers.

        HTTP header values are ASCII-only. Escaping non-ASCII characters keeps
        the envelope JSON intact while avoiding client-side encoding failures.
        """
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
        )


__all__ = [
    "ConstraintConfig",
    "MCPEnvelope",
]
