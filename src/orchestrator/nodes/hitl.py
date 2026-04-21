"""Human-in-the-loop interrupt node.

Uses LangGraph's ``interrupt()`` primitive to pause graph execution and
surface clarifying questions to the end user.  When the graph is resumed
via ``Command(resume=answers)``, the answers flow back through state into
the originating content node.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from langgraph.types import interrupt

from orchestrator.contracts.node_outputs import HITLResult
from orchestrator.state import BlaiqGraphState
from utils.logging_utils import log_flow

logger = logging.getLogger("blaiq-core.hitl_node")


def _normalize_answers_to_qkeys(answers: Dict[str, str], questions: list[str]) -> Dict[str, str]:
    if not isinstance(answers, dict) or not answers:
        return {}

    # Already normalized.
    if all(str(k).startswith("q") and str(k)[1:].isdigit() for k in answers.keys()):
        return {str(k): str(v) for k, v in answers.items()}

    normalized: Dict[str, str] = {}
    question_to_qkey = {q: f"q{idx+1}" for idx, q in enumerate(questions)}
    for idx, (key, value) in enumerate(answers.items()):
        qkey = question_to_qkey.get(str(key), f"q{idx+1}")
        normalized[qkey] = str(value)
    return normalized


async def hitl_node(state: BlaiqGraphState) -> dict:
    """Pause the graph and wait for human answers.

    The ``interrupt()`` call suspends execution.  When resumed the return
    value contains the user-supplied answers which are written back into
    ``hitl_answers`` so the content node can use them on its next pass.
    """
    questions: list[str] = state.get("hitl_questions", [])
    hitl_source: str = state.get("hitl_node", "unknown")
    hitl_mode: str = str(state.get("hitl_mode", "") or "").strip().lower()
    if not hitl_mode:
        hitl_mode = "page_review" if hitl_source == "content_page_review" else "clarification"
    thread_id: str = state.get("thread_id", "")
    session_id: str = state.get("session_id", "")
    logs: list[str] = [
        f"hitl_node: pausing for user input, source={hitl_source}, "
        f"questions={len(questions)}"
    ]

    log_flow(
        logger,
        "hitl_interrupt",
        thread_id=thread_id,
        session_id=session_id,
        source=hitl_source,
        question_count=len(questions),
    )

    # This call suspends the graph until Command(resume=...) is sent
    answers: Dict[str, str] = interrupt({
        "questions": questions,
        "node": hitl_source,
        "hitl_mode": hitl_mode,
    })

    if isinstance(answers, dict):
        nested_answers = answers.get("hitl_answers")
        if isinstance(nested_answers, dict) and (
            len(answers) == 1 or all(key in {"hitl_answers", "node", "questions"} for key in answers)
        ):
            answers = nested_answers

    answers = _normalize_answers_to_qkeys(answers if isinstance(answers, dict) else {}, questions)

    log_flow(
        logger,
        "hitl_resumed",
        thread_id=thread_id,
        session_id=session_id,
        source=hitl_source,
        answers_keys=list(answers.keys()) if answers else [],
    )
    logs.append(f"hitl_node: resumed with {len(answers) if answers else 0} answers")

    return HITLResult(
        hitl_answers=answers if answers else {},
        hitl_required=False,
        post_hitl_refresh_needed=bool(answers) and hitl_mode != "page_review",
        hitl_mode=hitl_mode,
        schema_version="hitl_node.v1",
        status="generating",
        current_node="hitl_node",
        logs=logs,
    ).to_state_update()
