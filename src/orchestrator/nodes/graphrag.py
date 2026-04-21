"""GraphRAG retrieval node -- fetches evidence from the GraphRAG agent.

Sends the user query to the GraphRAG micro-service, parses the response into
an ``EvidenceManifest``, and applies the Claim Check pattern when the payload
exceeds the inline size threshold.
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
from orchestrator.contracts.manifests import ChunkReference, EvidenceManifest
from orchestrator.contracts.node_outputs import RetrievalResult
from orchestrator.observability import get_trace_headers, get_tracer
from orchestrator.state import BlaiqGraphState
from utils.logging_utils import log_flow

logger = logging.getLogger("blaiq-core.graphrag_node")

BLAIQ_GRAPHRAG_URL: str = os.getenv("BLAIQ_GRAPHRAG_URL", "http://blaiq-graph-rag:6001")
GRAPHRAG_TIMEOUT: int = int(os.getenv("BLAIQ_GRAPHRAG_TIMEOUT_SECONDS", "180"))
REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379")
API_KEY: str = os.getenv("API_KEY", "")
CLAIM_CHECK_THRESHOLD: int = 50_000  # bytes


async def graphrag_node(state: BlaiqGraphState) -> dict:
    """Call the GraphRAG retrieval service and package the evidence manifest."""
    tracer = get_tracer("blaiq-core.graphrag")
    with tracer.start_as_current_span("graphrag_node") as span:
        span.set_attribute("tenant.id", state.get("tenant_id", ""))
        span.set_attribute("collection_name", state.get("collection_name", ""))

        user_query: str = state["user_query"]
        collection_name: str = state["collection_name"]
        tenant_id: str = state["tenant_id"]
        thread_id: str = state["thread_id"]
        session_id: str = state["session_id"]
        room_number: str = state.get("room_number", "")
        run_id: str = state.get("run_id", "")
        keywords: list[str] = state.get("keywords", [])
        entities: list[str] = state.get("extracted_entities", [])
        hitl_answers: dict = state.get("hitl_answers", {})
        post_hitl_template: str = str(state.get("post_hitl_search_prompt_template", "") or "").strip()
        chat_history: list[dict[str, str]] = state.get("chat_history", [])

        logs: list[str] = []
        ts_start = time.time()
        log_flow(
            logger,
            "wf_node_start",
            node="graphrag",
            thread_id=thread_id,
            session_id=session_id,
            tenant_id=tenant_id,
            collection_name=collection_name,
            query_chars=len(user_query),
        )

        # Build MCP envelope
        retrieval_query = user_query
        if hitl_answers:
            hitl_context = "; ".join([f"{k}: {v}" for k, v in hitl_answers.items()])
            if post_hitl_template:
                retrieval_query = (
                    f"{post_hitl_template}\n\n"
                    f"HITL Clarifications:\n{hitl_context}\n\n"
                    f"Original Request:\n{user_query}"
                )
            else:
                retrieval_query = f"{user_query}\n\nHITL Clarifications:\n{hitl_context}"

        envelope = MCPEnvelope.create(
            thread_id=thread_id,
            intent="retrieve_evidence_after_hitl" if hitl_answers else "retrieve_evidence",
            tenant_id=tenant_id,
            collection_name=collection_name,
            payload={
                "query": retrieval_query,
                "entities": entities,
                "keywords": keywords,
                "answers": hitl_answers if hitl_answers else {},
            },
            run_id=run_id,
        )

        request_body: Dict[str, Any] = {
            "query": retrieval_query,
            "collection_name": collection_name,
            "k": int(os.getenv("BLAIQ_GRAPHRAG_TOP_K", "8")),
            "generate_answer": "content" not in (state.get("execution_plan") or []),
            "include_graph": True,
            "session_id": session_id,
            "room_number": room_number,
            "chat_history": chat_history,
            "use_cache": (not hitl_answers) and (not chat_history),
        }

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
            "x-mcp-envelope": envelope.to_header_value(),
            "x-idempotency-key": envelope.idempotency_key,
        }
        headers.update(get_trace_headers())

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(GRAPHRAG_TIMEOUT)) as client:
                resp = await client.post(
                    f"{BLAIQ_GRAPHRAG_URL}/query/graphrag",
                    json=request_body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            log_flow(
                logger,
                "graphrag_call_ok",
                latency_s=round(time.time() - ts_start, 3),
                status_code=resp.status_code,
                thread_id=thread_id,
                session_id=session_id,
                mission_id=envelope.mission_id,
                idempotency_key=envelope.idempotency_key,
            )

            # Build evidence manifest from response
            chunks: list[Dict[str, Any]] | None = None
            raw_chunks = data.get("chunks") or data.get("sources") or []
            if raw_chunks:
                chunks = [
                    ChunkReference(
                        chunk_id=c.get("chunk_id", c.get("id", "")),
                        doc_id=c.get("doc_id", c.get("document_id", "")),
                        text=c.get("text", c.get("content", "")),
                        original_filename=c.get("original_filename", c.get("filename", "")),
                        score=float(c.get("score", 0.0)),
                        retrieval_method=c.get("retrieval_method", "hybrid"),
                    ).model_dump()
                    for c in raw_chunks
                ]

            manifest = EvidenceManifest(
                mission_id=envelope.mission_id,
                query=user_query,
                answer=data.get("answer", data.get("response", "")),
                chunks=[ChunkReference(**c) for c in chunks] if chunks else None,
                summary=data.get("summary", {}),
                graph=data.get("graph"),
                retrieval_stats=data.get("retrieval_stats", {}),
            )

            manifest_dict = manifest.model_dump(mode="json")

            # Claim check: offload large manifests to Redis
            artifact_uri: Optional[str] = None
            manifest_bytes = json.dumps(manifest_dict).encode()
            if len(manifest_bytes) > CLAIM_CHECK_THRESHOLD:
                redis_key = f"artifact:evidence:{envelope.mission_id}"
                try:
                    async with aioredis.from_url(REDIS_URL) as redis_client:
                        await redis_client.set(redis_key, manifest_bytes, ex=3600)
                    artifact_uri = f"redis://{redis_key}"
                    # Strip heavy chunks from state copy
                    manifest_dict["artifact_uri"] = artifact_uri
                    manifest_dict["chunks"] = None
                    log_flow(
                        logger,
                        "claim_check_stored",
                        key=redis_key,
                        size_bytes=len(manifest_bytes),
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

            span.set_attribute("chunks.retrieved", len(raw_chunks))
            span.set_attribute("latency_ms", int((time.time() - ts_start) * 1000))

            logs.append(
                f"graphrag_node: retrieved {len(raw_chunks)} chunks, "
                f"answer_len={len(manifest.answer)}, claim_check={'yes' if artifact_uri else 'no'}"
            )
            log_flow(
                logger,
                "wf_node_complete",
                node="graphrag",
                thread_id=thread_id,
                session_id=session_id,
                latency_ms=int((time.time() - ts_start) * 1000),
                chunks=len(raw_chunks),
                answer_chars=len(manifest.answer),
                claim_check=bool(artifact_uri),
            )

            return RetrievalResult(
                evidence_manifest=manifest_dict,
                post_hitl_refresh_needed=bool(hitl_answers),
                status="retrieving",
                current_node="graphrag_node",
                logs=logs,
            ).to_state_update()

        except Exception as exc:
            logger.exception(
                "event=graphrag_node_error thread_id=%s session_id=%s err=%s",
                thread_id,
                session_id,
                str(exc),
            )
            logs.append(f"graphrag_node: ERROR — {exc}")
            log_flow(
                logger,
                "wf_node_error",
                level="error",
                node="graphrag",
                thread_id=thread_id,
                session_id=session_id,
                error=str(exc),
            )
            return RetrievalResult(
                evidence_manifest=None,
                status="error",
                current_node="graphrag_node",
                error_message=f"GraphRAG retrieval failed: {exc}",
                logs=logs,
            ).to_state_update()
