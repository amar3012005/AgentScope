
"""LangGraph workflow definition for BLAIQ Core Orchestrator.

Builds a ``StateGraph[BlaiqGraphState]`` with the following topology::

    START -> planner -> (route) -> graphrag -> (route) -> content -> (route) -> governance -> END
                                        |                     |                     ^
                                        +-- governance <------+   hitl <-----------+
                                                                   |
                                                                   +-> graphrag -> content (refresh loop)

The graph is compiled with an ``AsyncRedisSaver`` checkpointer so that
every state snapshot is durably persisted and HITL interrupts survive
process restarts.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.redis import AsyncRedisSaver

from orchestrator.nodes.planner import planner_node
from orchestrator.nodes.graphrag import graphrag_node
from orchestrator.nodes.content import content_node
from orchestrator.nodes.hitl import hitl_node
from orchestrator.nodes.governance import governance_node
from orchestrator.state import BlaiqGraphState

logger = logging.getLogger("blaiq-core.graph")
_GRAPH_CACHE: dict[str, CompiledStateGraph] = {}
_GRAPH_CACHE_LOCK: asyncio.Lock | None = None


def _get_graph_cache_lock() -> asyncio.Lock:
    global _GRAPH_CACHE_LOCK
    if _GRAPH_CACHE_LOCK is None:
        _GRAPH_CACHE_LOCK = asyncio.Lock()
    return _GRAPH_CACHE_LOCK


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_plan(state: BlaiqGraphState) -> str:
    """Decide next node after the planner based on the execution plan."""
    plan: list[str] = state.get("execution_plan", [])
    if "graphrag" in plan:
        return "graphrag"
    if "content" in plan:
        return "content"
    return "governance"


def route_after_evidence(state: BlaiqGraphState) -> str:
    """Decide next node after GraphRAG retrieval."""
    plan: list[str] = state.get("execution_plan", [])
    if "content" in plan:
        return "content"
    return "governance"


def route_after_content(state: BlaiqGraphState) -> str:
    """Decide whether content needs HITL or proceeds to governance."""
    if state.get("hitl_required"):
        return "hitl"
    return "governance"


def route_after_hitl(state: BlaiqGraphState) -> str:
    """After HITL, refresh evidence before content whenever GraphRAG is in plan."""
    # Page-review HITL is a UX control step, not an evidence-clarification step.
    # Resume should return directly to content generation without GraphRAG refresh.
    hitl_mode = str(state.get("hitl_mode", "")).strip().lower()
    hitl_node = str(state.get("hitl_node", "")).strip().lower()
    if hitl_mode == "page_review" or hitl_node == "content_page_review":
        return "content"
    plan: list[str] = state.get("execution_plan", [])
    if "graphrag" in plan:
        return "graphrag"
    return "content"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

async def build_graph(redis_url: str) -> CompiledStateGraph:
    """Construct and compile the BLAIQ orchestrator LangGraph.

    The function is async because ``AsyncRedisSaver`` requires its
    ``asetup()`` coroutine to be awaited before the checkpointer can be
    used.

    Parameters
    ----------
    redis_url:
        Connection string for the Redis instance used by both the
        ``AsyncRedisSaver`` checkpointer and claim-check artifact storage.

    Returns
    -------
    CompiledStateGraph
        A compiled LangGraph ready to be invoked with
        ``graph.ainvoke(initial_state, config)``.
    """
    cached = _GRAPH_CACHE.get(redis_url)
    if cached is not None:
        return cached

    lock = _get_graph_cache_lock()
    async with lock:
        cached = _GRAPH_CACHE.get(redis_url)
        if cached is not None:
            return cached

        workflow = StateGraph(BlaiqGraphState)

        # Register nodes
        workflow.add_node("planner", planner_node)
        workflow.add_node("graphrag", graphrag_node)
        workflow.add_node("content", content_node)
        workflow.add_node("hitl", hitl_node)
        workflow.add_node("governance", governance_node)

        # Edges
        workflow.add_edge(START, "planner")

        workflow.add_conditional_edges(
            "planner",
            route_after_plan,
            {"graphrag": "graphrag", "content": "content", "governance": "governance"},
        )

        workflow.add_conditional_edges(
            "graphrag",
            route_after_evidence,
            {"content": "content", "governance": "governance"},
        )

        workflow.add_conditional_edges(
            "content",
            route_after_content,
            {"hitl": "hitl", "governance": "governance"},
        )

        # After HITL answers, refresh GraphRAG evidence before returning to content.
        workflow.add_conditional_edges(
            "hitl",
            route_after_hitl,
            {"graphrag": "graphrag", "content": "content"},
        )

        # Governance is the terminal node
        workflow.add_edge("governance", END)

        # Compile with durable Redis checkpointer
        checkpointer = AsyncRedisSaver(redis_url=redis_url)
        await checkpointer.asetup()
        compiled = workflow.compile(checkpointer=checkpointer)

        logger.info("graph_compiled nodes=%s", list(workflow.nodes.keys()))
        _GRAPH_CACHE[redis_url] = compiled
        return compiled


__all__ = [
    "build_graph",
]
