"""Planner node -- analyses user query and produces an execution plan.

The planner calls a fast LLM (default ``groq/llama-3.1-8b-instant``) to
classify the query and produce a structured JSON plan.  On LLM failure it
falls back to a keyword-based heuristic so the graph never stalls.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict

from openai import AsyncOpenAI

from orchestrator.contracts.node_outputs import PlannerResult
from orchestrator.observability import get_tracer
from orchestrator.state import BlaiqGraphState
from utils.logging_utils import log_flow

logger = logging.getLogger("blaiq-core.planner")

LITELLM_PLANNER_MODEL: str = os.getenv("LITELLM_PLANNER_MODEL", "groq/llama-3.1-8b-instant")

PLANNER_SYSTEM_PROMPT = (
    "You are a task planner for BLAIQ Core. Analyze the user query and return a JSON execution plan.\n\n"
    "Return ONLY valid JSON with the following structure:\n"
    "{\n"
    '  "execution_plan": ["graphrag", "content", "governance"],\n'
    '  "entities": ["entity1", "entity2"],\n'
    '  "keywords": ["kw1", "kw2"],\n'
    '  "reasoning": "Short explanation of plan"\n'
    "}\n\n"
    "Rules:\n"
    '- If the query is a simple Q&A (no content-creation keywords like "pitch deck", '
    '"poster", "generate", "create", "design"), set execution_plan to ["graphrag", "governance"].\n'
    "- If the query involves content creation, set execution_plan to "
    '["graphrag", "content", "governance"].\n'
    '- Always include "governance" as the last step.\n'
    "- Extract relevant named entities (persons, orgs, locations, concepts) into entities.\n"
    "- Extract search keywords into keywords (translate to German if the knowledge base is German)."
)

_CONTENT_KEYWORDS = frozenset({
    "pitch deck", "poster", "generate", "create", "design",
    "presentation", "slide", "landing page", "website",
    "dashboard", "report", "infographic", "brochure",
    "flyer", "social media post", "linkedin", "article",
    "pitch-deck", "folie", "folien", "präsentation", "praesentation",
    "erstelle", "erstellen", "generiere", "designen", "landingpage",
    "webseite", "broschüre", "broschuere",
})


def _resolve_async_openai_client() -> AsyncOpenAI:
    """Build an async OpenAI-compatible client for the configured planner model."""
    model = LITELLM_PLANNER_MODEL
    if model.startswith("groq/"):
        api_key = os.getenv("GROQ_API_KEY", "")
        base_url = os.getenv("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")
    else:
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
    return AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)


def _normalize_model_name(model: str) -> str:
    """Strip provider prefix so the SDK receives a bare model id."""
    for prefix in ("openai/", "groq/"):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def _heuristic_plan(query: str) -> Dict[str, Any]:
    """Keyword-based fallback when the LLM call fails."""
    query_lower = query.lower()
    needs_content = any(kw in query_lower for kw in _CONTENT_KEYWORDS)
    plan = ["graphrag", "content", "governance"] if needs_content else ["graphrag", "governance"]
    return {
        "execution_plan": plan,
        "entities": [],
        "keywords": query_lower.split()[:10],
        "reasoning": "Heuristic fallback: keyword detection.",
    }


def _requires_creation_hitl(query: str, workflow_mode: str, execution_plan: list[str]) -> bool:
    query_lower = (query or "").lower()
    keyword_match = any(kw in query_lower for kw in _CONTENT_KEYWORDS)
    return workflow_mode == "creative" or keyword_match or ("content" in execution_plan)


async def planner_node(state: BlaiqGraphState) -> dict:
    """Analyse the user query and emit a structured execution plan."""
    tracer = get_tracer("blaiq-core.planner")
    with tracer.start_as_current_span("planner_node") as span:
        span.set_attribute("tenant.id", state.get("tenant_id", ""))
        span.set_attribute("workflow.mode", state.get("workflow_mode", "standard"))

        user_query: str = state["user_query"]
        workflow_mode: str = state.get("workflow_mode", "standard")
        thread_id: str = state.get("thread_id", "")
        session_id: str = state.get("session_id", "")
        ts_start = time.time()
        logs: list[str] = []
        log_flow(
            logger,
            "wf_node_start",
            node="planner",
            thread_id=thread_id,
            session_id=session_id,
            workflow_mode=workflow_mode,
            query_chars=len(user_query),
        )

        try:
            client = _resolve_async_openai_client()
            model_name = _normalize_model_name(LITELLM_PLANNER_MODEL)

            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_query},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=800,
            )

            raw = response.choices[0].message.content or "{}"
            plan_data = json.loads(raw)
            span.set_attribute("llm.model", _normalize_model_name(LITELLM_PLANNER_MODEL))
            log_flow(
                logger,
                "planner_llm_ok",
                model=LITELLM_PLANNER_MODEL,
                latency_s=round(time.time() - ts_start, 3),
                thread_id=thread_id,
                session_id=session_id,
            )
        except Exception as exc:
            log_flow(
                logger,
                "planner_llm_error",
                level="warning",
                error=str(exc),
                thread_id=thread_id,
                session_id=session_id,
            )
            logs.append(f"planner: LLM failed ({exc}), using heuristic fallback")
            plan_data = _heuristic_plan(user_query)

        execution_plan: list[str] = plan_data.get("execution_plan", ["graphrag", "governance"])
        entities: list[str] = plan_data.get("entities", [])
        keywords: list[str] = plan_data.get("keywords", [])
        reasoning: str = plan_data.get("reasoning", "")
        heuristic_plan = _heuristic_plan(user_query)
        strategy_plan = [step for step in (state.get("strategy_execution_plan") or []) if isinstance(step, str)]

        if workflow_mode == "creative" and "content" not in execution_plan:
            execution_plan = ["graphrag", "content", "governance"]
            reasoning = (
                f"{reasoning} Forced content step because workflow_mode=creative."
            ).strip()
        elif "content" in heuristic_plan["execution_plan"] and "content" not in execution_plan:
            execution_plan = ["graphrag", "content", "governance"]
            reasoning = (
                f"{reasoning} Forced content step because the query matched content-generation keywords."
            ).strip()

        # Ensure governance is always the final step
        if "governance" not in execution_plan:
            execution_plan.append("governance")

        # Strategist-selected plan is authoritative for node routing in hybrid mode.
        if strategy_plan:
            execution_plan = strategy_plan
            if "governance" not in execution_plan:
                execution_plan.append("governance")
            reasoning = (
                f"{reasoning} Execution plan overridden by strategist agent-capability routing."
            ).strip()
            log_flow(
                logger,
                "planner_strategy_override",
                thread_id=thread_id,
                session_id=session_id,
                strategy_plan=execution_plan,
                selected_agents=state.get("strategy_selected_agents", []),
                primary_agent=state.get("strategy_primary_agent", ""),
            )

        span.set_attribute("plan.steps", str(execution_plan))
        content_requires_hitl = _requires_creation_hitl(user_query, workflow_mode, execution_plan)
        span.set_attribute("content.requires_hitl", content_requires_hitl)

        logs.append(
            f"planner: plan={execution_plan} entities={entities} "
            f"keywords={keywords} reasoning={reasoning}"
        )
        log_flow(
            logger,
            "wf_node_complete",
            node="planner",
            thread_id=thread_id,
            session_id=session_id,
            latency_ms=int((time.time() - ts_start) * 1000),
            plan=execution_plan,
            entities=len(entities),
            keywords=len(keywords),
        )

        return PlannerResult(
            execution_plan=execution_plan,
            extracted_entities=entities,
            keywords=keywords,
            content_requires_hitl=content_requires_hitl,
            status="planning",
            current_node="planner",
            logs=logs,
        ).to_state_update()
