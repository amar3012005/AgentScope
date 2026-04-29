# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable, Optional

from agentscope.agent import AgentBase
from agentscope.message import Msg
from agentscope.pipeline import MsgHub

from agentscope_blaiq.contracts.hitl import HITLResumeRequest, SwarmSuspendedState, WorkflowSuspended
from agentscope_blaiq.persistence.redis_state import RedisStateStore
from agentscope_blaiq.tools.enterprise_fleet import BlaiqEnterpriseFleet

logger = logging.getLogger("blaiq.swarm_engine")


class ServiceProxyAgent(AgentBase):
    """
    Wraps a remote AaaS container as a local AgentBase participant.
    MsgHub sees it as a peer agent. Internally it calls the HTTP service.
    """

    def __init__(
        self,
        name: str,
        role: str,
        fleet: BlaiqEnterpriseFleet,
        session_id: str,
    ) -> None:
        super().__init__()
        self.name = name
        self.role = role
        self.fleet = fleet
        self.session_id = session_id

    async def observe(self, _msg: Msg | list[Msg] | None) -> None:
        pass  # MsgHub broadcast — no local memory needed, context passed via metadata

    async def __call__(self, msg: Msg, on_chunk: Optional[Callable[[str], Any]] = None) -> Msg:
        return await self.reply(msg, on_chunk=on_chunk)

    async def reply(self, msg: Msg, on_chunk: Optional[Callable[[str], Any]] = None) -> Msg:
        goal = msg.get_text_content() if msg else ""
        metadata = getattr(msg, "metadata", {}) or {}

        try:
            if self.role == "research":
                result = await self.fleet.research_evidence(goal, self.session_id, on_chunk=on_chunk)
                text = _extract(result)
                return Msg(
                    name=self.name,
                    content=text,
                    role="assistant",
                    metadata={"kind": "evidence", "evidence_brief": text},
                )

            elif self.role == "text_buddy":
                evidence = metadata.get("evidence_brief", "")
                artifact_type = metadata.get("artifact_type", "report")
                result = await self.fleet.synthesize_text(
                    goal=goal,
                    evidence_brief=evidence,
                    artifact_type=artifact_type,
                    session_id=self.session_id,
                    on_chunk=on_chunk
                )
                text = _extract(result)
                return Msg(
                    name=self.name,
                    content=text,
                    role="assistant",
                    metadata={"kind": "text_artifact"},
                )

            elif self.role == "content_director":
                artifact = metadata.get("text_artifact") or goal
                evidence = metadata.get("evidence_brief", "")
                result = await self.fleet.orchestrate_visuals(
                    text_artifact=artifact,
                    evidence_brief=evidence,
                    session_id=self.session_id,
                    on_chunk=on_chunk
                )
                text = _extract(result)
                return Msg(
                    name=self.name,
                    content=text,
                    role="assistant",
                    metadata={"kind": "visual_spec"},
                )

            elif self.role == "vangogh":
                # VanGogh translates spec into code. Content is the spec.
                spec = msg.content or metadata.get("visual_spec", goal)
                brand_dna = ""
                try:
                    with open("/Users/amar/blaiq/AgentScope-BLAIQ/data/blueprints/brand_dna.md", "r") as f:
                        brand_dna = f.read()
                except Exception:
                    pass

                result = await self.fleet.render_visuals(
                    visual_spec=spec,
                    session_id=self.session_id,
                    brand_dna=brand_dna,
                    on_chunk=on_chunk
                )
                text = _extract(result)
                return Msg(
                    name=self.name,
                    content=text,
                    role="assistant",
                    metadata={"kind": "render_result"},
                )

            elif self.role == "oracle":
                evidence = metadata.get("evidence_brief", goal)
                artifact_type = metadata.get("artifact_type", "report")
                result = await self.fleet.ask_oracle_hitl(
                    question=goal,
                    session_id=self.session_id,
                    artifact_type=artifact_type,
                    evidence=evidence,
                    on_chunk=on_chunk,
                )
                text = _extract(result)
                # Detect HITL metadata emitted by oracle service
                oracle_meta: dict[str, Any] = {}
                if hasattr(result, "metadata") and result.metadata:
                    oracle_meta = result.metadata
                
                # If the text itself looks like JSON (some services return raw JSON strings)
                if not oracle_meta and "{" in text:
                    try:
                        oracle_meta = json.loads(text)
                    except Exception:
                        pass

                return Msg(
                    name=self.name,
                    content=text,
                    role="assistant",
                    metadata={
                        "kind": "hitl_request",
                        "requires_input": oracle_meta.get("requires_input", True),
                        "options": oracle_meta.get("options", []),
                        "why_it_matters": oracle_meta.get("why_it_matters", ""),
                    },
                )

            elif self.role == "governance":
                # Governance should review the 'latest' artifact.
                # If we have a render result, review that; else review text.
                artifact = metadata.get("render_result") or metadata.get("text_artifact", goal)
                result = await self.fleet.govern_artifact(
                    artifact_content=artifact,
                    session_id=self.session_id,
                    on_chunk=on_chunk
                )
                text = _extract(result)
                return Msg(
                    name=self.name,
                    content=text,
                    role="assistant",
                    metadata={"kind": "governance_report"},
                )

            elif self.role == "Strategist" or self.role == "strategist":
                result = await self.fleet.architect_mission(goal, self.session_id, on_chunk=on_chunk)
                text = _extract(result)
                return Msg(
                    name=self.name,
                    content=text,
                    role="assistant",
                )

            else:
                return Msg(
                    name=self.name,
                    content=f"[{self.role}] No handler for role.",
                    role="assistant",
                )

        except Exception as e:
            logger.error(f"[{self.name}] proxy call failed: {e}")
            return Msg(
                name=self.name,
                content=f"[{self.role}] Service error: {e}",
                role="assistant",
                metadata={"kind": "error"},
            )

def _extract(result: Any) -> str:
    """Helper to extract text from Msg or strings."""
    if not result:
        return ""
    if isinstance(result, str):
        text = result
    elif hasattr(result, "content"):
        content = result.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list) and len(content) > 0:
            # Handle AgentScope list of parts
            text = ""
            for part in content:
                if isinstance(part, dict):
                    text += part.get("text", "")
                elif hasattr(part, "text"):
                    text += str(part.text)
                elif isinstance(part, str):
                    text += part
        else:
            text = str(content)
    elif hasattr(result, "get_text_content"):
        text = result.get_text_content() or ""
    else:
        text = str(result)

    # INTELLIGENT JSON EXTRACTION:
    # If the text contains multiple JSON blocks (e.g. Phase 1 and Phase 2 concatenated),
    # we must extract the LAST valid one, as that is the high-fidelity deliverable.
    if "{" in text and "}" in text:
        # Find all top-level-ish JSON blocks
        blocks = re.findall(r'\{.*\}', text, re.DOTALL)
        if blocks:
            # Try to parse the last one first
            candidate = blocks[-1].strip()
            try:
                # Verify it's actually JSON
                json.loads(candidate)
                return candidate
            except Exception:
                # If the last block is partial, look for any valid JSON block from the end
                for block in reversed(blocks):
                    try:
                        json.loads(block)
                        return block
                    except Exception:
                        continue
    return text


class SwarmEngine:
    """
    BLAIQ v3 Swarm Orchestration Engine.

    Follows AgentScope's Master-Worker Pattern:
    - Strategist (Master) coordinates mission execution
    - ServiceProxyAgents (Workers) handle specialized tasks
    - Oracle is EVENT-DRIVEN: fires only when context is insufficient
    - Sequential pipeline for standard flows with dynamic Oracle insertion

    AgentScope Reference:
    - Master-Worker Pattern: https://docs.agentscope.io/building-blocks/orchestration#master-worker-pattern
    - Sequential Pipeline: https://docs.agentscope.io/building-blocks/orchestration#sequential-pipeline
    - Agent Hooks: https://docs.agentscope.io/building-blocks/agent#agent-hooks
    """

    # Roles executed in order for standard report/text missions
    REPORT_SEQUENCE = ["research", "text_buddy", "governance"]
    VISUAL_SEQUENCE = ["research", "content_director", "vangogh", "governance"]

    def __init__(self) -> None:
        self.fleet = BlaiqEnterpriseFleet()

    def _build_proxies(self, roles: list[str], session_id: str) -> dict[str, ServiceProxyAgent]:
        return {
            role: ServiceProxyAgent(
                name=role.replace("_", " ").title(),
                role=role,
                fleet=self.fleet,
                session_id=session_id,
            )
            for role in roles
        }

    def _choose_sequence(self, artifact_family: str) -> list[str]:
        visual_families = {"pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page"}
        if artifact_family in visual_families:
            return self.VISUAL_SEQUENCE
        return self.REPORT_SEQUENCE

    def _should_fire_oracle(self, role_output: str, role_name: str) -> tuple[bool, str]:
        """
        Event-driven Oracle trigger: decides if context is insufficient.

        Returns (should_fire, reason) based on:
        - Empty or error outputs from previous role
        - Explicit "INSUFFICIENT_CONTEXT" markers in output
        - Missing critical data patterns

        This aligns with AgentScope's Master-Worker pattern where the
        coordinator (Strategist/SwarmEngine) decides when to escalate.
        """
        if not role_output or not role_output.strip():
            return True, f"{role_name} returned empty output"

        error_indicators = [
            "Error:", "error:", "failed:", "no relevant data",
            "INSUFFICIENT_CONTEXT", "context_missing", "research_failed",
            "could not find", "no information", "no data",
        ]
        output_lower = role_output.lower()
        for indicator in error_indicators:
            if indicator.lower() in output_lower:
                return True, f"{role_name} output indicates insufficient context: {indicator}"

        return False, ""

    async def _safe_publish(self, publish: Optional[Callable], role: str, text: str, is_stream: bool = False):
        """Safely call publish callback whether it is sync or async."""
        if not publish:
            return
        if asyncio.iscoroutinefunction(publish):
            await publish(role, text, is_stream=is_stream)
        else:
            publish(role, text, is_stream=is_stream)

    async def run(
        self,
        goal: str,
        session_id: str,
        artifact_family: str = "report",
        publish: Optional[Callable] = None,
        with_oracle: bool = True,
        prefilled_results: Optional[dict[str, Any]] = None,
        start_from_role: Optional[str] = None,
        skip_planning: bool = False,
    ) -> dict[str, Any]:
        """
        Execute swarm mission. Returns dict of {role: output_text}.
        publish: optional async callable(role, text) for SSE/TUI progress.
        with_oracle: enable event-driven Oracle (fires when context is insufficient).
        prefilled_results: results already completed (for resume after HITL).
        start_from_role: skip roles before this one (for resume after HITL).
        skip_planning: whether to bypass the initial strategist assessment.
        """
        # 1. Master Strategist Assessment (Fast Track)
        # Check if this is a conversational query that can be answered directly
        if not prefilled_results and not start_from_role and not skip_planning:
            try:
                if publish:
                    await self._safe_publish(publish, "Strategist", json.dumps({
                        "type": "agent_thought",
                        "agent_name": "Strategist",
                        "data": {"message": "Deconstructing mission requirements and architecting the swarm path..."}
                    }))
                
                # Call strategist service with chunk-based streaming callback
                async def on_strategist_chunk(chunk: str):
                    if publish:
                        # Only stream if it's not a JSON block (to avoid UI flicker)
                        if not chunk.strip().startswith("{"):
                            await self._safe_publish(publish, "Strategist", chunk, is_stream=True)

                plan_raw = await self.fleet.architect_mission(goal, session_id, on_chunk=on_strategist_chunk)
                logger.info(f"Strategist assessment received. Length: {len(plan_raw)}")
                
                # Robust JSON extraction for is_direct
                if "is_direct" in plan_raw:
                    try:
                        # Extract JSON block if it's buried in text
                        # Use findall to handle multiple JSON blocks if they exist
                        matches = re.findall(r'\{[^{}]*"is_direct":\s*(true|True)[^{}]*\}', plan_raw, re.DOTALL | re.IGNORECASE)
                        
                        # Fallback to a more broad search if the specific one fails
                        if not matches:
                            matches = re.findall(r'\{[^{}]*\}', plan_raw, re.DOTALL)

                        for m in matches:
                            try:
                                # Re-construct the full block if findall only got the group
                                full_match = m if m.startswith("{") else next(match.group(0) for match in re.finditer(r'\{[^{}]*"is_direct":\s*(true|True)[^{}]*\}', plan_raw, re.DOTALL | re.IGNORECASE))
                                plan_data = json.loads(full_match)
                                if plan_data.get("is_direct"):
                                    direct_answer = plan_data.get("direct_response") or "I am BLAIQ-CORE, your enterprise swarm intelligence."
                                    logger.info(f"Direct response detected from strategist: {direct_answer[:50]}...")
                                    if publish:
                                        await self._safe_publish(publish, "Strategist", direct_answer)
                                    return {"Strategist": direct_answer}
                            except Exception:
                                continue
                        
                        logger.info("Found 'is_direct' keyword but no matching JSON block with is_direct=True.")
                    except Exception as e:
                        logger.warning(f"Failed to parse direct response JSON: {e}")
                else:
                    logger.info("No 'is_direct' keyword found in strategist response.")
            except Exception as e:
                logger.warning(f"Strategist fast-track assessment failed: {e}")

        base_sequence = self._choose_sequence(artifact_family)

        proxies = self._build_proxies(base_sequence, session_id)

        results: dict[str, str] = dict(prefilled_results or {})
        initial_msg = Msg(
            name="user",
            content=goal,
            role="user",
            metadata={"artifact_type": artifact_family, "session_id": session_id},
        )
        store = RedisStateStore()

        async with MsgHub(
            participants=list(proxies.values()),
            announcement=initial_msg,
            enable_auto_broadcast=True,
        ):
            # Build dynamic sequence: insert oracle after research if with_oracle enabled
            sequence = list(base_sequence)
            oracle_inserted = False

            for role in sequence:
                if start_from_role and role in results and role != start_from_role:
                    continue

                proxy = proxies[role]

                # Clear previous start_from_role if we reached it
                if start_from_role == role:
                    start_from_role = None

                # 1. Emit START EVENT for the frontend progress/timeline
                await self._safe_publish(publish, role, json.dumps({
                    "type": "agent_started",
                    "agent_name": role,
                    "phase": role,
                    "data": {"message": f"Starting {role.replace('_', ' ').title()}..."}
                }))

                evidence = results.get("research", "")
                text_artifact = results.get("text_buddy", "")
                visual_spec = results.get("content_director", "")
                render_result = results.get("vangogh", "")

                await self._safe_publish(publish, role, json.dumps({
                    "type": "agent_thought",
                    "agent_name": role,
                    "data": {"message": f"Processing internal context for {role.replace('_', ' ')}..."}
                }))

                current_content = goal
                if role == "content_director":
                    current_content = text_artifact or goal
                elif role == "vangogh":
                    current_content = visual_spec or goal
                elif role == "governance":
                    current_content = render_result or text_artifact or goal

                active_msg = Msg(
                    name="user",
                    content=current_content,
                    role="user",
                    metadata={
                        "artifact_type": artifact_family,
                        "session_id": session_id,
                        "evidence_brief": evidence,
                        "text_artifact": text_artifact,
                        "visual_spec": visual_spec,
                        "render_result": render_result,
                    },
                )

                async def on_chunk(chunk: str, _role: str = role):
                    await self._safe_publish(publish, _role, chunk, is_stream=True)

                reply = await proxy(active_msg, on_chunk=on_chunk)
                reply_text = _extract(reply)
                reply_meta = getattr(reply, "metadata", {}) or {}

                # 3. Emit COMPLETION EVENT with final metadata (triggers Oracle dropup if kind=hitl_request)
                if publish:
                    await self._safe_publish(publish, role, json.dumps({
                        "type": "agent_completed",
                        "agent_name": role,
                        "phase": role,
                        "data": {
                            "message": f"{role.replace('_', ' ').title()} finished.",
                            "content": reply_text,
                            **reply_meta
                        }
                    }))

                # 4. Handle HITL suspension: oracle or strategist signals hitl_request
                if reply_meta.get("kind") == "hitl_request" and reply_meta.get("requires_input"):
                    # Emit BLOCKED EVENT for UI dropup
                    await self._safe_publish(publish, role, json.dumps({
                        "type": "workflow_blocked",
                        "agent_name": role,
                        "phase": role,
                        "data": {
                            "blocked_question": reply_text,
                            **reply_meta
                        }
                    }))
                    # Find what role comes after oracle to resume from
                    try:
                        next_role = sequence[sequence.index(role) + 1]
                    except (ValueError, IndexError):
                        # If oracle was inserted dynamically, the next role is whatever was supposed to run after research
                        if role == "oracle":
                            next_role = "text_buddy" if artifact_family not in {"pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page"} else "content_director"
                        else:
                            next_role = role

                    suspension = SwarmSuspendedState(
                        session_id=session_id,
                        goal=goal,
                        artifact_family=artifact_family,
                        completed_results=dict(results),
                        resume_from_role=next_role,
                        hitl_question=reply.get_text_content() or "",
                        hitl_options=reply_meta.get("options", []),
                        hitl_why=reply_meta.get("why_it_matters", ""),
                    )
                    await store.save_swarm_suspension(suspension)
                    logger.info(f"Swarm suspended for HITL: session={session_id} resume_from={next_role}")
                    raise WorkflowSuspended(
                        session_id=session_id,
                        question=suspension.hitl_question,
                        options=suspension.hitl_options,
                        why=suspension.hitl_why,
                    )

                results[role] = reply.get_text_content() or ""


                # EVENT-DRIVEN ORACLE: Check if context is insufficient after research
                if with_oracle and role == "research" and not oracle_inserted:
                    should_fire, reason = self._should_fire_oracle(results["research"], "Research")
                    if should_fire:
                        await self._safe_publish(publish, "oracle", f"[Event-Driven] Oracle triggered: {reason}")

                        # Create oracle proxy
                        oracle_proxy = ServiceProxyAgent(
                            name="Oracle",
                            role="oracle",
                            fleet=self.fleet,
                            session_id=session_id,
                        )
                        
                        oracle_msg = Msg(
                            name="user",
                            content=f"Context insufficient after research: {reason}\n\nOriginal goal: {goal}\n\nEvidence so far: {results.get('research', '')}",
                            role="user",
                            metadata={
                                "artifact_type": artifact_family,
                                "session_id": session_id,
                                "evidence_brief": results.get("research", ""),
                            },
                        )

                        async def oracle_on_chunk(chunk: str):
                            await self._safe_publish(publish, "oracle", chunk, is_stream=True)

                        oracle_reply = await oracle_proxy(oracle_msg, on_chunk=oracle_on_chunk)
                        oracle_reply_meta = getattr(oracle_reply, "metadata", {}) or {}

                        # Check if Oracle itself needs HITL
                        if oracle_reply_meta.get("kind") == "hitl_request" and oracle_reply_meta.get("requires_input"):
                            suspension = SwarmSuspendedState(
                                session_id=session_id,
                                goal=goal,
                                artifact_family=artifact_family,
                                completed_results=dict(results),
                                resume_from_role="text_buddy" if artifact_family not in {"pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page"} else "content_director",
                                hitl_question=oracle_reply.get_text_content() or "",
                                hitl_options=oracle_reply_meta.get("options", []),
                                hitl_why=oracle_reply_meta.get("why_it_matters", ""),
                            )
                            await store.save_swarm_suspension(suspension)
                            logger.info(f"Swarm suspended for HITL (Oracle): session={session_id}")
                            raise WorkflowSuspended(
                                session_id=session_id,
                                question=suspension.hitl_question,
                                options=suspension.hitl_options,
                                why=suspension.hitl_why,
                            )

                        results["oracle"] = oracle_reply.get_text_content() or ""
                        await self._safe_publish(publish, "oracle", results["oracle"])

                        oracle_inserted = True

        return results

    async def resume(self, request: HITLResumeRequest, publish: Optional[Callable] = None) -> dict[str, Any]:
        """Resume a suspended swarm after HITL answer is provided."""
        store = RedisStateStore()
        state = await store.load_swarm_suspension(request.session_id)
        if state is None:
            raise ValueError(f"No suspended swarm found for session {request.session_id}")

        await store.delete_swarm_suspension(request.session_id)

        enriched_goal = (
            f"USER DIRECTION: {request.answer}\n\n"
            f"ORIGINAL GOAL: {state.goal}"
        )
        return await self.run(
            goal=enriched_goal,
            session_id=request.session_id,
            artifact_family=state.artifact_family,
            publish=publish,
            with_oracle=False,
            prefilled_results=state.completed_results,
            start_from_role=state.resume_from_role,
        )
