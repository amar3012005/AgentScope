"""
Role-based agent resolver for workflow node assignment.

Replaces hardcoded string parsing with typed profile metadata.
Scoring: role_match → required_capabilities → tool_access → artifact_affinity → custom_preference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_catalog import LiveAgentProfile


@dataclass
class AgentCandidate:
    """Scored candidate for a workflow node."""

    agent_name: str
    role: str
    score: float  # 0.0 - 1.0
    is_custom: bool
    match_reasons: list[str] = field(default_factory=list)
    disqualify_reasons: list[str] = field(default_factory=list)

    @property
    def qualified(self) -> bool:
        return len(self.disqualify_reasons) == 0 and self.score > 0


@dataclass
class ResolverResult:
    """Result of agent resolution for a node."""

    selected: str  # agent_name of winner
    candidates: list[AgentCandidate] = field(default_factory=list)
    fallback_used: bool = False  # True if no custom agent matched


class AgentResolver:
    """Resolve the best agent for a workflow node based on role, capabilities, and affinity.

    Scoring order (highest to lowest priority):
    1. Role match (required -- disqualifies if no match)
    2. Required capabilities (disqualifies if missing)
    3. Tool access (minor bonus/penalty)
    4. Artifact affinity (typed field, capability family, then tag fallback)
    5. Custom preference (custom agents preferred over built-in when qualified)
    """

    def resolve(
        self,
        candidates: list[LiveAgentProfile],
        *,
        required_role: str,
        required_capabilities: list[str] | None = None,
        artifact_family: str | None = None,
        workflow_id: str | None = None,
        required_tools: list[str] | None = None,
        default_agent: str = "",
        allow_remote: bool = False,
    ) -> ResolverResult:
        """Find the best agent for a node.

        Args:
            candidates: All live agent profiles to consider.
            required_role: Role this node needs (e.g. ``"content_director"``).
            required_capabilities: Capabilities the agent must have (optional).
            artifact_family: Artifact family being produced (optional, for affinity scoring).
            workflow_id: Current workflow template ID (optional, reserved for future use).
            required_tools: Tools the node needs (optional, for tool access check).
            default_agent: Fallback agent name if no better match found.

        Returns:
            :class:`ResolverResult` with the selected agent and scored candidates.
        """
        scored: list[AgentCandidate] = []

        for agent in candidates:
            candidate = self._score_agent(
                agent,
                required_role=required_role,
                required_capabilities=required_capabilities or [],
                artifact_family=artifact_family,
                workflow_id=workflow_id,
                required_tools=required_tools or [],
                allow_remote=allow_remote,
            )
            scored.append(candidate)

        # Sort: qualified first, then by (custom preference, score) descending
        qualified = [c for c in scored if c.qualified]
        qualified.sort(key=lambda c: (c.is_custom, c.score), reverse=True)

        if qualified:
            return ResolverResult(
                selected=qualified[0].agent_name,
                candidates=scored,
                fallback_used=False,
            )

        return ResolverResult(
            selected=default_agent,
            candidates=scored,
            fallback_used=True,
        )

    def _score_agent(
        self,
        agent: LiveAgentProfile,
        *,
        required_role: str,
        required_capabilities: list[str],
        artifact_family: str | None,
        workflow_id: str | None,
        required_tools: list[str],
        allow_remote: bool,
    ) -> AgentCandidate:
        score = 0.0
        reasons: list[str] = []
        disqualify: list[str] = []

        capability_names = [cap.name for cap in agent.capabilities]
        status_value = getattr(agent.status, "value", str(agent.status))

        if status_value == "disabled":
            disqualify.append("agent disabled")
        elif status_value == "degraded":
            score -= 0.1
            reasons.append("agent degraded")

        # ── 1. Role match (required) ──────────────────────────────────
        role_match = agent.role == required_role
        # Also accept agents whose capabilities declare the role via
        # ``supported_task_roles``.
        role_capability_match = any(
            required_role in (cap.supported_task_roles or [])
            for cap in agent.capabilities
        )

        if role_match:
            score += 0.3
            reasons.append(f"role match: {required_role}")
        elif role_capability_match:
            score += 0.2
            reasons.append(f"capability role match: {required_role}")
        else:
            disqualify.append(
                f"role mismatch: agent has '{agent.role}', need '{required_role}'"
            )

        # ── 2. Required capabilities ──────────────────────────────────
        if required_capabilities:
            missing = [
                cap for cap in required_capabilities if cap not in capability_names
            ]
            if missing:
                disqualify.append(f"missing capabilities: {missing}")
            else:
                score += 0.2
                reasons.append(f"all capabilities present: {required_capabilities}")

        # ── 3. Tool access ────────────────────────────────────────────
        if required_tools:
            missing_tools = [t for t in required_tools if t not in agent.tools]
            if missing_tools:
                disqualify.append(f"missing tools: {missing_tools}")
            else:
                score += 0.1
                reasons.append("all required tools available")

        # ── 4. Artifact affinity ──────────────────────────────────────
        if artifact_family:
            # 4a. Typed ``artifact_affinities`` field (highest priority)
            affinities: list[str] = getattr(agent, "artifact_affinities", []) or []
            has_typed_affinity = artifact_family in affinities

            if has_typed_affinity:
                score += 0.2
                reasons.append(f"artifact affinity: {artifact_family}")

            # 4b. Capability-level ``supported_artifact_families``
            cap_affinity = any(
                artifact_family in (cap.supported_artifact_families or [])
                for cap in agent.capabilities
            )
            if cap_affinity and not has_typed_affinity:
                score += 0.15
                reasons.append(f"capability artifact family: {artifact_family}")

            # 4c. Tag-based fallback
            tags: list[str] = getattr(agent, "tags", []) or []
            tag_hit = any(
                artifact_family in t or t in artifact_family for t in tags
            )
            if tag_hit and not has_typed_affinity and not cap_affinity:
                score += 0.1
                reasons.append(f"tag affinity: {artifact_family}")

        # ── 5. Custom preference ──────────────────────────────────────
        is_custom: bool = getattr(agent, "is_custom", False)
        if is_custom:
            score += 0.05
            reasons.append("custom agent preference bonus")

        transport = getattr(agent, "transport", None)
        transport_value = getattr(transport, "value", transport) or "local"
        if transport_value == "remote-a2a":
            # Removed: disqualify.append("remote transport requires an A2A execution adapter")
            # RemoteA2AProxy is now available in runtime.registry.py
            if not allow_remote:
                disqualify.append("remote transport not allowed for this node")
            
            features = getattr(agent, "runtime_features", None)
            if required_tools and not getattr(features, "tool_calling_capable", False):
                disqualify.append("remote transport cannot satisfy local tool requirements")
            if getattr(features, "structured_output_capable", True) is False:
                score -= 0.05
                reasons.append("remote transport has limited structured output support")

        current_load = float(getattr(agent, "current_load", 0.0) or 0.0)
        if current_load >= 1.0:
            disqualify.append("agent at maximum load")
        elif current_load > 0:
            score -= min(current_load * 0.1, 0.1)
            reasons.append(f"load penalty: {current_load:.2f}")

        return AgentCandidate(
            agent_name=agent.name,
            role=agent.role,
            score=round(max(score, 0.0), 3),
            is_custom=is_custom,
            match_reasons=reasons,
            disqualify_reasons=disqualify,
        )


# ── Module-level singleton ────────────────────────────────────────────
_resolver = AgentResolver()


def resolve_agent(
    candidates: list[LiveAgentProfile],
    *,
    required_role: str,
    required_capabilities: list[str] | None = None,
    artifact_family: str | None = None,
    workflow_id: str | None = None,
    required_tools: list[str] | None = None,
    default_agent: str = "",
    allow_remote: bool = False,
) -> ResolverResult:
    """Module-level convenience wrapper around :class:`AgentResolver.resolve`."""
    return _resolver.resolve(
        candidates,
        required_role=required_role,
        required_capabilities=required_capabilities,
        artifact_family=artifact_family,
        workflow_id=workflow_id,
        required_tools=required_tools,
        default_agent=default_agent,
        allow_remote=allow_remote,
    )
