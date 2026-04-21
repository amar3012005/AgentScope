"""Content generation node -- delegates to the content-creator agent.

Resolves evidence from Redis when a claim-check URI is present, forwards
the payload to the content agent, and handles HITL interruptions when the
agent signals ``status: blocked_on_user``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
import redis.asyncio as aioredis

from orchestrator.contracts.envelope import MCPEnvelope
from orchestrator.contracts.node_outputs import ContentResult
from orchestrator.contracts.manifests import PitchDeckDraft, ContentSchema
from orchestrator.observability import get_trace_headers, get_tracer
from orchestrator.state import BlaiqGraphState
from orchestrator.utils.schema_normalization import build_content_schema
from utils.logging_utils import log_flow

logger = logging.getLogger("blaiq-core.content_node")

BLAIQ_CONTENT_URL: str = os.getenv("BLAIQ_CONTENT_URL", "http://blaiq-content-agent:6003")
CONTENT_TIMEOUT: int = int(os.getenv("BLAIQ_CONTENT_TIMEOUT_SECONDS", "300"))
REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379")
API_KEY: str = os.getenv("API_KEY", "")
CLAIM_CHECK_THRESHOLD: int = 50_000  # bytes
PREVIEW_PUBSUB_PREFIX: str = os.getenv("BLAIQ_PREVIEW_PUBSUB_PREFIX", "blaiq:preview:")


def _preview_channel(thread_id: str) -> str:
    return f"{PREVIEW_PUBSUB_PREFIX}{thread_id}"


async def _resolve_evidence(state: BlaiqGraphState) -> Optional[Dict[str, Any]]:
    """Fetch full evidence manifest from Redis if a claim-check URI is set."""
    manifest = state.get("evidence_manifest")
    if not manifest:
        return None

    artifact_uri = manifest.get("artifact_uri")
    if not artifact_uri and manifest.get("chunks"):
        return manifest

    if artifact_uri and artifact_uri.startswith("redis://"):
        redis_key = artifact_uri.replace("redis://", "", 1)
        try:
            async with aioredis.from_url(REDIS_URL) as redis_client:
                raw = await redis_client.get(redis_key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("evidence_resolve_error key=%s err=%s", redis_key, exc)

    return manifest


async def content_node(state: BlaiqGraphState) -> dict:
    """Call the content-creator agent and handle HITL flow."""
    tracer = get_tracer("blaiq-core.content")
    with tracer.start_as_current_span("content_node") as span:
        span.set_attribute("tenant.id", state.get("tenant_id", ""))
        span.set_attribute("hitl_retry", bool(state.get("hitl_answers")))

        user_query: str = state["user_query"]
        tenant_id: str = state["tenant_id"]
        collection_name: str = state["collection_name"]
        thread_id: str = state["thread_id"]
        session_id: str = state["session_id"]
        room_number: str = state.get("room_number", "")
        run_id: str = state.get("run_id", "")
        hitl_answers: dict = state.get("hitl_answers", {})
        content_requires_hitl: bool = bool(state.get("content_requires_hitl"))
        hitl_node: str = str(state.get("hitl_node", "") or "")
        chat_history: list[dict[str, str]] = state.get("chat_history", [])

        logs: list[str] = []
        ts_start = time.time()
        log_flow(
            logger,
            "wf_node_start",
            node="content",
            thread_id=thread_id,
            session_id=session_id,
            tenant_id=tenant_id,
            collection_name=collection_name,
            has_hitl_answers=bool(hitl_answers),
        )

        # Resolve full evidence
        evidence = await _resolve_evidence(state)
        evidence_context = ""
        if evidence:
            evidence_context = evidence.get("answer", "")
            chunks = evidence.get("chunks") or []
            if chunks:
                chunk_texts = [c.get("text", "") for c in chunks[:10]]
                evidence_context += "\n\n" + "\n---\n".join(chunk_texts)

        # Build MCP envelope
        envelope = MCPEnvelope.create(
            thread_id=thread_id,
            intent="generate_content",
            tenant_id=tenant_id,
            collection_name=collection_name,
            payload={"query": user_query},
            run_id=run_id,
        )

        # Build request payload
        payload: Dict[str, Any] = {
            "evidence_context": evidence_context,
            "tenant_id": tenant_id,
            "collection_name": collection_name,
            "room_number": room_number,
            "chat_history": chat_history,
        }
        if bool(state.get("use_template_engine")):
            payload["_use_template_engine"] = True
        if content_requires_hitl and not hitl_answers:
            payload["_require_hitl"] = True
        page_review_decision = ""
        if hitl_node == "content_page_review" and hitl_answers:
            page_review_decision = " ".join(str(v) for v in hitl_answers.values()).strip().lower()
            if any(token in page_review_decision for token in ("cancel", "stop", "no", "reject")):
                logs.append("content_node: page review cancelled by user")
                return ContentResult(
                    content_draft=state.get("content_draft"),
                    artifact_manifest=state.get("content_draft"),
                    hitl_required=False,
                    status="complete",
                    current_node="content_node",
                    hitl_mode="page_review",
                    schema_version="content_node.v1",
                    recovery_hint="User cancelled page review before rendering remaining pages.",
                    logs=logs,
                ).to_state_update()
            payload["_page_review_approved"] = True
            payload["_hitl_mode"] = "page_review"
        elif hitl_answers:
            payload["answers"] = hitl_answers
            payload["_hitl_mode"] = "clarification"

        request_body: Dict[str, Any] = {
            "task": user_query,
            "session_id": session_id,
            "payload": payload,
        }

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
            "x-mcp-envelope": envelope.to_header_value(),
            "x-idempotency-key": envelope.idempotency_key,
        }
        headers.update(get_trace_headers())

        streamed_events: list[Dict[str, Any]] = []

        def _normalize_stream_event(raw_event: Dict[str, Any]) -> Dict[str, Any]:
            event = dict(raw_event)
            if "type" in event and "normalized_type" not in event:
                event["normalized_type"] = event["type"]
            return event

        async def _consume_stream(
            client: httpx.AsyncClient,
            redis_client: Any,
        ) -> tuple[Dict[str, Any], int]:
            final_data: Dict[str, Any] = {}
            status_code: int = 0
            async with client.stream(
                "POST",
                f"{BLAIQ_CONTENT_URL}/stream",
                json=request_body,
                headers={**headers, "Accept": "text/event-stream"},
            ) as resp:
                resp.raise_for_status()
                status_code = resp.status_code
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    trimmed = line.strip()
                    if trimmed == "data: [DONE]":
                        break
                    if not trimmed.startswith("data: "):
                        continue
                    try:
                        event = json.loads(trimmed[6:])
                    except Exception:
                        continue
                    final_data = event if isinstance(event, dict) else final_data
                    normalized_type = str(event.get("normalized_type") or event.get("type") or "")
                    if normalized_type in {
                        "artifact_type_resolved",
                        "rendering_started",
                        "section_started",
                        "section_ready",
                        "artifact_composed",
                        "slide_metadata",
                        "artifact_ready",
                        "hitl_required",
                    }:
                        normalized = _normalize_stream_event(event)
                        normalized.setdefault("thread_id", thread_id)
                        normalized.setdefault("session_id", session_id)
                        streamed_events.append(normalized)
                        # Publish for orchestrator SSE bridging (browser progressive preview).
                        try:
                            await redis_client.publish(
                                _preview_channel(thread_id),
                                json.dumps(normalized, ensure_ascii=True),
                            )
                        except Exception:
                            pass
            return final_data, status_code

        try:
            status_code = 0
            async with aioredis.from_url(REDIS_URL) as redis_client:
                async with httpx.AsyncClient(timeout=httpx.Timeout(CONTENT_TIMEOUT)) as client:
                    if bool(state.get("use_template_engine")):
                        data, status_code = await _consume_stream(client, redis_client)
                    else:
                        resp = await client.post(
                            f"{BLAIQ_CONTENT_URL}/execute",
                            json=request_body,
                            headers=headers,
                        )
                        resp.raise_for_status()
                        status_code = resp.status_code
                        data = resp.json()

            latency = time.time() - ts_start
            log_flow(
                logger,
                "content_call_ok",
                latency_s=round(latency, 3),
                status_code=status_code,
                thread_id=thread_id,
                session_id=session_id,
                mission_id=envelope.mission_id,
                idempotency_key=envelope.idempotency_key,
            )

            result_payload = data.get("result") if isinstance(data, dict) and isinstance(data.get("result"), dict) else data
            if isinstance(result_payload, dict) and streamed_events:
                result_payload.setdefault("streamed_events", streamed_events)

            # Normalize streaming final events into the same shape as /execute.
            if isinstance(result_payload, dict) and bool(state.get("use_template_engine")):
                normalized_type = str(result_payload.get("normalized_type") or result_payload.get("type") or "")
                if normalized_type == "hitl_required":
                    result_payload = {
                        "status": "blocked_on_user",
                        "message": result_payload.get("message", ""),
                        "analysis": result_payload.get("analysis", ""),
                        "questions": result_payload.get("questions", []),
                        "hitl_questions": result_payload.get("questions", []),
                        "agent_node": result_payload.get("agent_node", "content_node"),
                        "post_hitl_search_prompt_template": result_payload.get(
                            "post_hitl_search_prompt_template", ""
                        ),
                        "streamed_events": streamed_events,
                    }
                elif normalized_type == "artifact_ready":
                    result_payload = {
                        "status": "success",
                        "message": result_payload.get("message", ""),
                        "html_artifact": result_payload.get("html_artifact", ""),
                        "schema_data": result_payload.get("schema_data", {}),
                        "skills_used": result_payload.get("skills_used", []),
                        "brand_dna_version": result_payload.get("brand_dna_version", "2.0"),
                        "streamed_events": streamed_events,
                    }

            # Check for HITL block
            if result_payload.get("status") == "blocked_on_user":
                questions = result_payload.get("questions", result_payload.get("hitl_questions", []))
                post_hitl_template = str(result_payload.get("post_hitl_search_prompt_template", "") or "")
                blocking_node = str(result_payload.get("agent_node", "content_node") or "content_node")
                log_flow(
                    logger,
                    "content_hitl_blocked",
                    thread_id=thread_id,
                    session_id=session_id,
                    mission_id=envelope.mission_id,
                    question_count=len(questions) if isinstance(questions, list) else 0,
                )
                span.set_attribute("hitl.questions_count", len(questions) if isinstance(questions, list) else 0)
                logs.append(f"content_node: HITL required, {len(questions)} questions")
                log_flow(
                    logger,
                    "wf_node_blocked",
                    node="content",
                    thread_id=thread_id,
                    session_id=session_id,
                    hitl_questions=len(questions) if isinstance(questions, list) else 0,
                )
                return ContentResult(
                    hitl_required=True,
                    hitl_questions=questions,
                    hitl_node=blocking_node,
                    hitl_mode="page_review" if blocking_node == "content_page_review" else "clarification",
                    post_hitl_search_prompt_template=post_hitl_template,
                    recovery_hint="Resume with the inline HITL answers; GraphRAG refresh is only required for clarification mode.",
                    schema_version="content_node.v1",
                    status="blocked",
                    current_node="content_node",
                    logs=logs,
                ).to_state_update()

            # Build pitch deck draft from response
            html_artifact = result_payload.get(
                "html_artifact",
                result_payload.get("html", result_payload.get("artifact", "")),
            )
            schema_raw = result_payload.get("schema", result_payload.get("schema_data", {}))
            schema_data = build_content_schema(schema_raw)

            draft = PitchDeckDraft(
                mission_id=envelope.mission_id,
                html_artifact=html_artifact,
                schema_data=schema_data,
                skills_used=result_payload.get("skills_used", []),
                brand_dna_version=result_payload.get("brand_dna_version", "2.0"),
            )

            draft_dict = draft.model_dump(mode="json")

            # Claim check for large HTML artifacts
            if html_artifact and len(html_artifact.encode()) > CLAIM_CHECK_THRESHOLD:
                redis_key = f"artifact:content:{envelope.mission_id}"
                try:
                    async with aioredis.from_url(REDIS_URL) as redis_client:
                        await redis_client.set(redis_key, html_artifact.encode(), ex=3600)
                    draft_dict["artifact_uri"] = f"redis://{redis_key}"
                    draft_dict["html_artifact"] = None
                    log_flow(
                        logger,
                        "claim_check_content",
                        key=redis_key,
                        thread_id=thread_id,
                        session_id=session_id,
                        mission_id=envelope.mission_id,
                    )
                except Exception as redis_exc:
                    log_flow(
                        logger,
                        "claim_check_redis_error",
                        level="warning",
                        error=str(redis_exc),
                        thread_id=thread_id,
                        session_id=session_id,
                        mission_id=envelope.mission_id,
                    )

            span.set_attribute("html.size_bytes", len(html_artifact.encode()) if html_artifact else 0)

            logs.append(
                f"content_node: draft generated, html_len={len(html_artifact) if html_artifact else 0}, "
                f"skills={draft.skills_used}"
            )
            log_flow(
                logger,
                "wf_node_complete",
                node="content",
                thread_id=thread_id,
                session_id=session_id,
                latency_ms=int((time.time() - ts_start) * 1000),
                html_chars=len(html_artifact) if html_artifact else 0,
                skills=draft.skills_used,
            )

            return ContentResult(
                content_draft=draft_dict,
                artifact_manifest=draft_dict,
                hitl_required=False,
                hitl_mode="page_review" if hitl_node == "content_page_review" else "clarification",
                schema_version="content_node.v1",
                status="generating",
                current_node="content_node",
                logs=logs,
            ).to_state_update()

        except Exception as exc:
            logger.exception(
                "event=content_node_error thread_id=%s session_id=%s err=%s",
                thread_id,
                session_id,
                str(exc),
            )
            logs.append(f"content_node: ERROR — {exc}")
            log_flow(
                logger,
                "wf_node_error",
                level="error",
                node="content",
                thread_id=thread_id,
                session_id=session_id,
                error=str(exc),
            )
            return ContentResult(
                content_draft=None,
                artifact_manifest=None,
                status="error",
                current_node="content_node",
                error_message=f"Content generation failed: {exc}",
                recovery_hint="Retry the request or reduce artifact complexity; malformed section JSON now falls back per section.",
                schema_version="content_node.v1",
                logs=logs,
            ).to_state_update()
