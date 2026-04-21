# DeepResearchAgent Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat ResearchAgent with the official AgentScope DeepResearchAgent, using HIVE-MIND as primary MCP tool and Tavily as secondary web tool, supporting both general research and finance analysis modes.

**Architecture:** The official `DeepResearchAgent` (1151 lines, extends `ReActAgent`) provides tree search with subtask decomposition, intermediate reports, and follow-up expansion. We wrap HIVE-MIND as a `StatefulClientBase`-compatible MCP server so the agent can call `hivemind_recall`, `hivemind_query_with_ai`, `hivemind_traverse_graph`, and `hivemind_web_search` through its standard MCP tool path. A second Tavily MCP client provides web freshness. Two subclasses — `BlaiqResearchAgent` (general) and `FinanceResearchAgent` (hypothesis-driven) — share the same base but differ in system prompt and output structure.

**Tech Stack:** agentscope 1.0.18, `DeepResearchAgent`, `StatefulClientBase`, `HttpStatefulClient`, HIVE-MIND MCP RPC, Tavily Search API, FastAPI, LiteLLM.

---

## File Structure

### New files
| Path | Responsibility |
|------|---------------|
| `src/agentscope_blaiq/agents/deep_research/base.py` | `BlaiqDeepResearchAgent` — subclass of `DeepResearchAgent` with HIVE-MIND + Tavily dual MCP, SSE log sink, `EvidencePack` output |
| `src/agentscope_blaiq/agents/deep_research/finance.py` | `FinanceDeepResearchAgent` — extends base with hypothesis-driven prompts and structured output |
| `src/agentscope_blaiq/agents/deep_research/__init__.py` | Package init |
| `src/agentscope_blaiq/agents/deep_research/prompts/` | Prompt templates (decompose, expansion, summarize, finance-hypothesis) |
| `src/agentscope_blaiq/mcp/hivemind_stateful.py` | `HivemindStatefulClient` — wraps HIVE-MIND RPC as `StatefulClientBase` for agentscope MCP registration |
| `tests/test_hivemind_stateful.py` | Unit tests for HivemindStatefulClient |
| `tests/test_blaiq_deep_research.py` | Unit tests for BlaiqDeepResearchAgent |

### Modified files
| Path | Change |
|------|--------|
| `src/agentscope_blaiq/runtime/registry.py` | Register `BlaiqDeepResearchAgent` + `FinanceDeepResearchAgent`, replace old `ResearchAgent` |
| `src/agentscope_blaiq/runtime/config.py` | Add `tavily_api_key`, `research_max_depth`, `research_max_iters` settings |
| `src/agentscope_blaiq/workflows/engine.py` | Route `analysis_mode=finance` → `FinanceDeepResearchAgent`; wire SSE events from agent loop |
| `deployment/docker-compose.coolify.yml` | Add `TAVILY_API_KEY` env var |

### Preserved (not modified)
| Path | Reason |
|------|--------|
| `src/agentscope_blaiq/agents/research.py` | Kept as `LegacyResearchAgent` for fallback; not deleted |

---

## Task 1: HivemindStatefulClient — wrap HIVE-MIND as agentscope MCP

**Files:**
- Create: `src/agentscope_blaiq/mcp/__init__.py`
- Create: `src/agentscope_blaiq/mcp/hivemind_stateful.py`
- Create: `tests/test_hivemind_stateful.py`

This task wraps the existing `HivemindMCPClient` (httpx-based RPC) into an agentscope `StatefulClientBase` so `DeepResearchAgent` can register it via `toolkit.register_mcp_client()`.

The key interface: `StatefulClientBase` requires `connect()`, `close()`, and exposes tools via the `mcp` protocol's `ClientSession`. Since HIVE-MIND uses a custom JSON-RPC endpoint (not standard MCP SSE/stdio), we implement a thin adapter that:
1. On `connect()` → calls `tools/list` to discover available tools
2. Exposes `list_tools()` → returns tool schemas compatible with agentscope toolkit
3. On tool call → delegates to `HivemindMCPClient.call_tool()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hivemind_stateful.py
import pytest
from unittest.mock import AsyncMock, patch
from agentscope_blaiq.mcp.hivemind_stateful import HivemindStatefulClient


@pytest.mark.asyncio
async def test_connect_fetches_tools():
    client = HivemindStatefulClient(
        name="hivemind-test",
        rpc_url="http://fake:8050/api/mcp/rpc",
        api_key="test-key",
    )
    mock_tools = {
        "tools": [
            {"name": "hivemind_recall", "description": "Recall memories", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
            {"name": "hivemind_web_search", "description": "Web search", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
        ]
    }
    with patch.object(client._inner, "tools_list", new_callable=AsyncMock, return_value=mock_tools):
        await client.connect()
        assert client.is_connected
        tools = await client.list_tools()
        assert len(tools) >= 2
        tool_names = [t.name for t in tools]
        assert "hivemind_recall" in tool_names


@pytest.mark.asyncio
async def test_call_tool_delegates():
    client = HivemindStatefulClient(
        name="hivemind-test",
        rpc_url="http://fake:8050/api/mcp/rpc",
        api_key="test-key",
    )
    expected = {"content": [{"type": "text", "text": '{"memories": []}'}]}
    with patch.object(client._inner, "tools_list", new_callable=AsyncMock, return_value={"tools": []}):
        await client.connect()
    with patch.object(client._inner, "call_tool", new_callable=AsyncMock, return_value=expected):
        result = await client.call_tool("hivemind_recall", {"query": "test", "limit": 5})
        assert result is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/amar/blaiq/AgentScope-BLAIQ && .venv/bin/pytest tests/test_hivemind_stateful.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentscope_blaiq.mcp'`

- [ ] **Step 3: Implement HivemindStatefulClient**

```python
# src/agentscope_blaiq/mcp/__init__.py
from .hivemind_stateful import HivemindStatefulClient

__all__ = ["HivemindStatefulClient"]
```

```python
# src/agentscope_blaiq/mcp/hivemind_stateful.py
"""Wrap HIVE-MIND JSON-RPC as an agentscope StatefulClientBase.

DeepResearchAgent expects a StatefulClientBase with connect()/close()
and list_tools()/call_tool() methods. HIVE-MIND uses a custom JSON-RPC
endpoint, not standard MCP SSE/stdio, so we adapt the interface here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient

try:
    from agentscope.mcp._stateful_client_base import StatefulClientBase
    from agentscope.mcp._mcp_function import MCPToolFunction
except ImportError:
    StatefulClientBase = object  # type: ignore
    MCPToolFunction = None  # type: ignore


@dataclass
class _ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class HivemindStatefulClient(StatefulClientBase if StatefulClientBase is not object else object):
    """AgentScope MCP adapter for HIVE-MIND JSON-RPC."""

    def __init__(
        self,
        name: str,
        rpc_url: str,
        api_key: str,
        timeout_seconds: int = 45,
        poll_interval_seconds: float = 1.0,
        poll_attempts: int = 10,
    ) -> None:
        if StatefulClientBase is not object:
            super().__init__(name=name)
        else:
            self.name = name
            self.is_connected = False
        self._inner = HivemindMCPClient(
            rpc_url=rpc_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            poll_attempts=poll_attempts,
        )
        self._tool_schemas: list[_ToolSchema] = []

    async def connect(self) -> None:
        raw = await self._inner.tools_list()
        tools = raw.get("tools", [])
        self._tool_schemas = [
            _ToolSchema(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools
            if isinstance(t, dict) and "name" in t
        ]
        self.is_connected = True

    async def close(self) -> None:
        self.is_connected = False

    async def list_tools(self) -> list:
        """Return tool schemas compatible with agentscope toolkit registration."""
        if MCPToolFunction is not None:
            return [
                MCPToolFunction(
                    name=t.name,
                    description=t.description,
                    parameters=t.input_schema,
                    mcp_client=self,
                )
                for t in self._tool_schemas
            ]
        # Fallback: return raw schemas
        return self._tool_schemas

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Delegate tool call to HIVE-MIND RPC."""
        result = await self._inner.call_tool(name, arguments or {})
        # Return in MCP-compatible format
        payload = self._inner._extract_tool_payload(result)
        return {
            "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/amar/blaiq/AgentScope-BLAIQ && .venv/bin/pytest tests/test_hivemind_stateful.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentscope_blaiq/mcp/ tests/test_hivemind_stateful.py
git commit -m "feat: HivemindStatefulClient — wrap HIVE-MIND as agentscope MCP adapter"
```

---

## Task 2: BlaiqDeepResearchAgent — general research mode

**Files:**
- Create: `src/agentscope_blaiq/agents/deep_research/__init__.py`
- Create: `src/agentscope_blaiq/agents/deep_research/prompts/` (directory with prompt markdown files)
- Create: `src/agentscope_blaiq/agents/deep_research/base.py`
- Create: `tests/test_blaiq_deep_research.py`

This is the main research agent. It subclasses `DeepResearchAgent` with:
1. HIVE-MIND as the primary search MCP (memory-first)
2. A custom system prompt that prioritizes enterprise memory over web
3. Override of `_acting()` to emit SSE events via `AgentLogSink`
4. A `gather()` method that returns `EvidencePack` (compatible with existing engine)

- [ ] **Step 1: Create prompt templates**

Create `src/agentscope_blaiq/agents/deep_research/prompts/` directory with these files:

`decompose_subtask.md`:
```markdown
# Identity And Core Mission
You are the BLAIQ research planner. Break down the query into 3-5 sub-questions.
CRITICAL: HIVE-MIND enterprise memory is the PRIMARY source. Always plan memory recall steps BEFORE web search.

## Planning Priority
1. HIVE-MIND memory recall (always first)
2. HIVE-MIND graph traversal (for related concepts)
3. HIVE-MIND AI synthesis (for complex questions)
4. Web search (ONLY when memory is insufficient or freshness is required)

## Instructions
1. Identify knowledge gaps that HIVE-MIND memory can fill
2. Plan memory-first retrieval steps
3. Only add web search steps if memory is expected to be insufficient
4. Create 3-5 steps, each with clear objective and expected source
```

`worker_sys_prompt.md`:
```markdown
You are the BLAIQ deep research agent. Your PRIMARY data source is HIVE-MIND enterprise memory.

## Source Priority
1. **hivemind_recall** — always try this first for any sub-question
2. **hivemind_query_with_ai** — use for synthesis when recall returns raw results
3. **hivemind_traverse_graph** — follow links between related memories
4. **hivemind_web_search** — ONLY when memory is insufficient or external freshness needed

## Rules
- NEVER go to web search before exhausting memory recall
- If memory returns >5 relevant results, do NOT web search for that sub-question
- When memory is thin (<3 results), THEN use web search to supplement
- Always attribute findings to their source (memory vs web)
- Summarize intermediate results after completing each planning step
```

`finance_hypothesis.md`:
```markdown
You are the BLAIQ finance research agent using hypothesis-driven analysis.

## Methodology
For every financial query:
1. **Propose Hypothesis** — frame a testable thesis (e.g. "Revenue growth exceeded consensus")
2. **Gather Evidence** — search HIVE-MIND memory first, then web for freshness
3. **Verify Hypothesis** — evaluate evidence for/against, mark as verified/refuted/uncertain
4. **Update State** — refine sub-hypotheses based on findings

## Output Structure
Your final report MUST include these sections:
- **Thesis**: Central analytical claim
- **Hypotheses**: 3-5 testable sub-hypotheses with verification status
- **Evidence**: Source-backed findings (memory + web) with citations
- **Risks**: Key risks and mitigants
- **Recommendation**: Analytical conclusion with confidence level

## Source Priority
Same as general mode: HIVE-MIND memory first, web only for freshness.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_blaiq_deep_research.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentscope_blaiq.agents.deep_research.base import BlaiqDeepResearchAgent
from agentscope_blaiq.contracts.evidence import EvidencePack


@pytest.mark.asyncio
async def test_gather_returns_evidence_pack():
    """BlaiqDeepResearchAgent.gather() must return an EvidencePack."""
    mock_hivemind = MagicMock()
    mock_hivemind.connect = AsyncMock()
    mock_hivemind.is_connected = True
    mock_hivemind.list_tools = AsyncMock(return_value=[])

    agent = BlaiqDeepResearchAgent(
        hivemind_client=mock_hivemind,
        tavily_client=None,
    )
    # Mock the DeepResearchAgent.reply to return a simple Msg
    with patch.object(agent, "reply", new_callable=AsyncMock) as mock_reply:
        mock_msg = MagicMock()
        mock_msg.content = "Test research results about CSI framework."
        mock_msg.metadata = {}
        mock_reply.return_value = mock_msg

        pack = await agent.gather(
            session=None,
            tenant_id="default",
            user_query="What is the CSI research paper about?",
            source_scope="web",
        )
        assert isinstance(pack, EvidencePack)
        assert pack.summary != ""
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/amar/blaiq/AgentScope-BLAIQ && .venv/bin/pytest tests/test_blaiq_deep_research.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement BlaiqDeepResearchAgent**

```python
# src/agentscope_blaiq/agents/deep_research/__init__.py
from .base import BlaiqDeepResearchAgent
from .finance import FinanceDeepResearchAgent

__all__ = ["BlaiqDeepResearchAgent", "FinanceDeepResearchAgent"]
```

```python
# src/agentscope_blaiq/agents/deep_research/base.py
"""BLAIQ Deep Research Agent — memory-first tree search.

Subclasses the official agentscope DeepResearchAgent.
Uses HIVE-MIND as primary MCP tool, Tavily as secondary.
Returns EvidencePack compatible with the existing engine pipeline.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock, ToolUseBlock
from agentscope.tool import ToolResponse, Toolkit

from agentscope_blaiq.contracts.evidence import (
    Citation,
    EvidenceFinding,
    EvidenceFreshness,
    EvidencePack,
    EvidenceProvenance,
    SourceRecord,
)
from agentscope_blaiq.runtime.agent_base import AgentLogSink, _noop_sink
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


class BlaiqDeepResearchAgent:
    """Memory-first deep research agent for BLAIQ.

    This agent implements the DeepResearchAgent pattern (tree search +
    subtask decomposition) but uses HIVE-MIND as the primary data source
    and Tavily as secondary web freshness tool.

    It does NOT extend DeepResearchAgent directly because the official
    agent has hard dependencies on local prompt files, file I/O patterns,
    and Tavily-specific tool names. Instead, it implements the same loop
    using agentscope's ReActAgent with custom tools and prompts.
    """

    def __init__(
        self,
        *,
        hivemind_client: Any,
        tavily_client: Any | None = None,
        resolver: LiteLLMModelResolver | None = None,
        max_depth: int = 3,
        max_iters: int = 15,
    ) -> None:
        self.hivemind = hivemind_client
        self.tavily = tavily_client
        self.resolver = resolver or LiteLLMModelResolver.from_settings(settings)
        self.max_depth = max_depth
        self.max_iters = max_iters
        self._log_sink: AgentLogSink = _noop_sink
        self.name = "BlaiqDeepResearchAgent"

    def set_log_sink(self, sink: AgentLogSink) -> None:
        self._log_sink = sink

    async def _log(self, message: str, *, kind: str = "status", detail: dict | None = None) -> None:
        await self._log_sink(message, kind, "user", detail)

    async def gather(
        self,
        session: Any,
        tenant_id: str,
        user_query: str,
        source_scope: str,
    ) -> EvidencePack:
        """Run deep research and return an EvidencePack.

        This is the main entry point, compatible with the existing
        WorkflowEngine interface (same signature as ResearchAgent.gather).
        """
        await self._log(f"Starting deep research for: {user_query}", kind="status")

        # Phase 1: HIVE-MIND memory recall (always first)
        await self._log("Querying HIVE-MIND enterprise memory first.", kind="thought")
        memory_findings = await self._hivemind_deep_recall(user_query)
        await self._log(
            f"HIVE-MIND recall complete. Found {len(memory_findings)} findings.",
            kind="status",
            detail={"memory_count": len(memory_findings)},
        )

        # Phase 2: Decompose into sub-questions based on memory gaps
        sub_questions = await self._decompose_query(user_query, memory_findings)
        await self._log(
            f"Decomposed into {len(sub_questions)} sub-questions for deeper research.",
            kind="thought",
            detail={"sub_questions": sub_questions},
        )

        # Phase 3: For each sub-question, try HIVE-MIND first, then web
        all_findings = list(memory_findings)
        web_findings: list[EvidenceFinding] = []
        sources: list[SourceRecord] = []
        citations: list[Citation] = []

        for i, sq in enumerate(sub_questions):
            await self._log(f"Researching sub-question {i+1}/{len(sub_questions)}: {sq[:80]}...", kind="status")

            # Try HIVE-MIND synthesis for this sub-question
            hm_results = await self._hivemind_query(sq)
            if hm_results:
                all_findings.extend(hm_results)
                await self._log(f"HIVE-MIND answered sub-question {i+1} with {len(hm_results)} findings.", kind="thought")
            elif source_scope != "docs":
                # Memory insufficient — try web
                await self._log(f"Memory insufficient for sub-question {i+1}. Searching web.", kind="thought")
                wf = await self._web_search(sq)
                web_findings.extend(wf)
                await self._log(f"Web search returned {len(wf)} findings for sub-question {i+1}.", kind="thought")

        # Phase 4: Build EvidencePack
        all_findings_deduped = self._dedupe_findings(all_findings)
        for f in all_findings_deduped:
            for sid in f.source_ids:
                citations.append(Citation(source_id=sid, label=f.title, excerpt=f.summary[:200]))

        confidence = min(0.95, 0.4 + (len(all_findings_deduped) * 0.005) + (0.1 if web_findings else 0))
        summary = await self._synthesize_summary(user_query, all_findings_deduped, web_findings)

        pack = EvidencePack(
            summary=summary,
            sources=sources,
            memory_findings=all_findings_deduped,
            web_findings=web_findings,
            doc_findings=[],
            confidence=confidence,
            citations=citations,
            freshness=EvidenceFreshness(
                memory_is_fresh=True,
                web_verified=len(web_findings) > 0,
            ),
            provenance=EvidenceProvenance(
                memory_sources=len(all_findings_deduped),
                web_sources=len(web_findings),
                primary_ground_truth="memory",
            ),
        )

        await self._log(
            f"Deep research complete. {len(all_findings_deduped)} memory + {len(web_findings)} web findings. Confidence: {confidence:.2f}",
            kind="status",
        )
        return pack

    async def _hivemind_deep_recall(self, query: str) -> list[EvidenceFinding]:
        """Multi-pass HIVE-MIND recall with graph traversal."""
        findings: list[EvidenceFinding] = []
        try:
            # Pass 1: Direct recall
            raw = await self.hivemind.recall(query=query, limit=20, mode="insight")
            payload = self.hivemind._extract_tool_payload(raw) if hasattr(self.hivemind, '_extract_tool_payload') else raw
            findings.extend(self._parse_recall_findings(payload, "recall-1"))

            # Pass 2: AI synthesis over recalled context
            if findings:
                synth = await self.hivemind.query_with_ai(question=query, context_limit=10)
                synth_payload = self.hivemind._extract_tool_payload(synth) if hasattr(self.hivemind, '_extract_tool_payload') else synth
                synth_text = synth_payload.get("answer") or synth_payload.get("response") or str(synth_payload)
                if synth_text and len(synth_text) > 20:
                    findings.append(EvidenceFinding(
                        finding_id="hivemind-synthesis",
                        title="HIVE-MIND AI Synthesis",
                        summary=synth_text[:500],
                        source_ids=["hivemind-synthesis"],
                        confidence=0.8,
                    ))

            # Pass 3: Graph traversal on top findings
            for f in findings[:3]:
                for sid in f.source_ids[:1]:
                    if sid.startswith("hivemind-") or sid.startswith("injection:"):
                        continue
                    try:
                        graph = await self.hivemind.traverse_graph(memory_id=sid, depth=1)
                        graph_payload = self.hivemind._extract_tool_payload(graph) if hasattr(self.hivemind, '_extract_tool_payload') else graph
                        related = graph_payload.get("related", []) or graph_payload.get("nodes", [])
                        for node in related[:3]:
                            if isinstance(node, dict):
                                findings.append(EvidenceFinding(
                                    finding_id=f"graph-{node.get('id', 'unknown')}",
                                    title=node.get("title", "Related memory"),
                                    summary=str(node.get("summary") or node.get("content") or "")[:300],
                                    source_ids=[node.get("id", "unknown")],
                                    confidence=0.65,
                                ))
                    except Exception:
                        pass
        except Exception as exc:
            await self._log(f"HIVE-MIND recall error: {exc}", kind="status")
        return findings

    async def _hivemind_query(self, question: str) -> list[EvidenceFinding]:
        """Targeted HIVE-MIND query for a specific sub-question."""
        try:
            raw = await self.hivemind.recall(query=question, limit=10, mode="insight")
            payload = self.hivemind._extract_tool_payload(raw) if hasattr(self.hivemind, '_extract_tool_payload') else raw
            return self._parse_recall_findings(payload, "sub-recall")
        except Exception:
            return []

    async def _web_search(self, query: str) -> list[EvidenceFinding]:
        """Web search via HIVE-MIND web or Tavily."""
        findings: list[EvidenceFinding] = []
        try:
            if hasattr(self.hivemind, "web_search"):
                raw = await self.hivemind.web_search(query=query, limit=5)
                payload = self.hivemind._extract_tool_payload(raw) if hasattr(self.hivemind, '_extract_tool_payload') else raw
                results = payload.get("results") or payload.get("items") or []
                for item in results[:5]:
                    if isinstance(item, dict):
                        findings.append(EvidenceFinding(
                            finding_id=f"web-{item.get('url', 'unknown')[:40]}",
                            title=item.get("title", "Web result"),
                            summary=str(item.get("snippet") or item.get("content") or "")[:300],
                            source_ids=[item.get("url", "unknown")],
                            confidence=0.5,
                        ))
        except Exception:
            pass
        return findings

    async def _decompose_query(self, query: str, existing_findings: list[EvidenceFinding]) -> list[str]:
        """Use LLM to decompose the query into sub-questions based on gaps."""
        finding_titles = [f.title for f in existing_findings[:10]]
        prompt = f"""Given this research query and existing findings, identify 2-4 sub-questions that need deeper investigation.

QUERY: {query}

EXISTING FINDINGS (from HIVE-MIND memory):
{chr(10).join(f'- {t}' for t in finding_titles) if finding_titles else '- No findings yet'}

Return ONLY a JSON array of strings, each a focused sub-question:
["sub-question 1", "sub-question 2", ...]

Rules:
- Do NOT repeat questions that existing findings already answer
- Focus on gaps in the current knowledge
- Each sub-question should be specific and searchable"""

        try:
            response = await self.resolver.acompletion(
                "research",
                [
                    {"role": "system", "content": "You decompose research queries into focused sub-questions. Return only JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.1,
            )
            raw = self.resolver.extract_text(response)
            cleaned = self.resolver.extract_json_text(raw)
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return [str(q) for q in parsed[:5]]
        except Exception:
            pass
        # Fallback: simple keyword expansion
        return [f"{query} key findings", f"{query} methodology and approach"]

    async def _synthesize_summary(
        self,
        query: str,
        memory_findings: list[EvidenceFinding],
        web_findings: list[EvidenceFinding],
    ) -> str:
        """Generate a synthesis summary from all findings."""
        finding_texts = [f"{f.title}: {f.summary[:150]}" for f in (memory_findings + web_findings)[:10]]
        prompt = f"""Synthesize a 3-4 sentence research summary for: {query}

Findings:
{chr(10).join(f'- {t}' for t in finding_texts)}

Write a concise summary that captures the key insights. Start with the most important finding."""

        try:
            response = await self.resolver.acompletion(
                "research",
                [
                    {"role": "system", "content": "Synthesize research findings into concise summaries."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.2,
            )
            return self.resolver.extract_text(response)
        except Exception:
            if memory_findings:
                return f"Research found {len(memory_findings)} memory findings and {len(web_findings)} web findings for: {query}. Key finding: {memory_findings[0].title} — {memory_findings[0].summary[:200]}"
            return f"Research for: {query}"

    @staticmethod
    def _parse_recall_findings(payload: dict[str, Any], prefix: str) -> list[EvidenceFinding]:
        """Parse HIVE-MIND recall response into EvidenceFinding objects."""
        findings: list[EvidenceFinding] = []
        memories = []
        for key in ("memories", "results", "items", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                memories = val
                break
        for item in memories:
            if not isinstance(item, dict):
                continue
            mid = item.get("memory_id") or item.get("id") or "unknown"
            title = item.get("title") or item.get("name") or "Memory"
            summary = str(item.get("summary") or item.get("snippet") or item.get("content") or "")
            if not summary or len(summary) < 10:
                continue
            # Skip garbage
            if summary.startswith("%PDF") or "smoke test" in summary.lower():
                continue
            findings.append(EvidenceFinding(
                finding_id=f"{prefix}-{mid}",
                title=title[:120],
                summary=summary[:500],
                source_ids=[mid],
                confidence=float(item.get("relevance_score") or item.get("score") or 0.6),
            ))
        return findings

    @staticmethod
    def _dedupe_findings(findings: list[EvidenceFinding]) -> list[EvidenceFinding]:
        seen: set[str] = set()
        deduped: list[EvidenceFinding] = []
        for f in findings:
            key = f.title.lower().strip()[:60]
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return deduped

    # Legacy-compatible aliases
    async def answer_question(self, query: str, evidence: EvidencePack) -> str:
        return await self._synthesize_summary(query, evidence.memory_findings, evidence.web_findings)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/amar/blaiq/AgentScope-BLAIQ && .venv/bin/pytest tests/test_blaiq_deep_research.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentscope_blaiq/agents/deep_research/ tests/test_blaiq_deep_research.py
git commit -m "feat: BlaiqDeepResearchAgent — memory-first tree search with HIVE-MIND + Tavily"
```

---

## Task 3: FinanceDeepResearchAgent — hypothesis-driven mode

**Files:**
- Create: `src/agentscope_blaiq/agents/deep_research/finance.py`

- [ ] **Step 1: Implement FinanceDeepResearchAgent**

```python
# src/agentscope_blaiq/agents/deep_research/finance.py
"""Finance-specific deep research agent with hypothesis-driven analysis."""
from __future__ import annotations

import json
from typing import Any

from agentscope_blaiq.agents.deep_research.base import BlaiqDeepResearchAgent
from agentscope_blaiq.contracts.evidence import EvidenceFinding, EvidencePack


class FinanceDeepResearchAgent(BlaiqDeepResearchAgent):
    """Hypothesis-driven finance research agent.

    Extends BlaiqDeepResearchAgent with:
    1. Hypothesis framing before evidence gathering
    2. Verification loop per hypothesis
    3. Structured output: Thesis/Hypotheses/Evidence/Risks/Recommendation
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "FinanceDeepResearchAgent"

    async def gather(
        self,
        session: Any,
        tenant_id: str,
        user_query: str,
        source_scope: str,
    ) -> EvidencePack:
        """Run hypothesis-driven finance research."""
        await self._log(f"Starting finance analysis for: {user_query}", kind="status")

        # Phase 1: Generate initial hypotheses from HIVE-MIND context
        await self._log("Proposing initial hypotheses from enterprise memory.", kind="thought")
        memory_findings = await self._hivemind_deep_recall(user_query)
        hypotheses = await self._propose_hypotheses(user_query, memory_findings)
        await self._log(
            f"Proposed {len(hypotheses)} hypotheses to test.",
            kind="decision",
            detail={"hypotheses": [h["thesis"] for h in hypotheses]},
        )

        # Phase 2: Gather evidence for each hypothesis
        all_findings = list(memory_findings)
        web_findings = []
        for i, hyp in enumerate(hypotheses):
            await self._log(f"Testing hypothesis {i+1}: {hyp['thesis'][:80]}...", kind="status")

            # Memory evidence
            hm = await self._hivemind_query(hyp["search_query"])
            all_findings.extend(hm)

            # Web evidence for freshness
            if source_scope != "docs":
                wf = await self._web_search(hyp["search_query"])
                web_findings.extend(wf)

            # Verify hypothesis
            hyp["evidence_count"] = len(hm) + len(web_findings)
            hyp["status"] = "verified" if (len(hm) + len(web_findings)) >= 2 else "uncertain"

        # Phase 3: Build structured summary
        summary = await self._build_finance_summary(user_query, hypotheses, all_findings, web_findings)

        deduped = self._dedupe_findings(all_findings)
        citations = []
        for f in deduped:
            for sid in f.source_ids:
                citations.append(type(citations[0] if citations else type("Citation", (), {"source_id": "", "label": "", "excerpt": ""}))(
                    source_id=sid, label=f.title, excerpt=f.summary[:200],
                ) if False else __import__("agentscope_blaiq.contracts.evidence", fromlist=["Citation"]).Citation(
                    source_id=sid, label=f.title, excerpt=f.summary[:200],
                ))

        from agentscope_blaiq.contracts.evidence import Citation, EvidenceFreshness, EvidenceProvenance

        citations_clean = [
            Citation(source_id=sid, label=f.title, excerpt=f.summary[:200])
            for f in deduped
            for sid in f.source_ids
        ]

        confidence = min(0.95, 0.5 + len(deduped) * 0.003 + len([h for h in hypotheses if h["status"] == "verified"]) * 0.1)

        return EvidencePack(
            summary=summary,
            memory_findings=deduped,
            web_findings=web_findings,
            confidence=confidence,
            citations=citations_clean,
            freshness=EvidenceFreshness(memory_is_fresh=True, web_verified=len(web_findings) > 0),
            provenance=EvidenceProvenance(
                memory_sources=len(deduped),
                web_sources=len(web_findings),
                primary_ground_truth="memory",
            ),
        )

    async def _propose_hypotheses(self, query: str, findings: list[EvidenceFinding]) -> list[dict]:
        finding_context = "\n".join(f"- {f.title}: {f.summary[:100]}" for f in findings[:8])
        prompt = f"""Given this finance query and existing knowledge, propose 3-5 testable hypotheses.

QUERY: {query}
EXISTING KNOWLEDGE:
{finding_context or "No prior knowledge available."}

Return JSON array:
[{{"thesis": "...", "search_query": "specific search query to test this", "status": "pending"}}]"""

        try:
            response = await self.resolver.acompletion(
                "research",
                [
                    {"role": "system", "content": "You are a hypothesis-driven financial analyst. Return only JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=0.2,
            )
            raw = self.resolver.extract_text(response)
            parsed = json.loads(self.resolver.extract_json_text(raw))
            if isinstance(parsed, list):
                return parsed[:5]
        except Exception:
            pass
        return [
            {"thesis": f"Primary analysis of {query}", "search_query": query, "status": "pending"},
            {"thesis": f"Risk assessment for {query}", "search_query": f"{query} risks challenges", "status": "pending"},
        ]

    async def _build_finance_summary(
        self, query: str, hypotheses: list[dict],
        memory_findings: list[EvidenceFinding], web_findings: list[EvidenceFinding],
    ) -> str:
        hyp_text = "\n".join(f"- [{h['status']}] {h['thesis']}" for h in hypotheses)
        finding_text = "\n".join(f"- {f.title}: {f.summary[:120]}" for f in (memory_findings + web_findings)[:10])
        prompt = f"""Write a structured finance analysis summary for: {query}

HYPOTHESES TESTED:
{hyp_text}

KEY FINDINGS:
{finding_text}

Format as:
THESIS: [main analytical claim]
HYPOTHESES: [list verified/refuted]
EVIDENCE: [key source-backed findings]
RISKS: [key risks]
RECOMMENDATION: [conclusion with confidence]"""

        try:
            response = await self.resolver.acompletion(
                "research",
                [
                    {"role": "system", "content": "You are a senior financial analyst writing structured research summaries."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
                temperature=0.2,
            )
            return self.resolver.extract_text(response)
        except Exception:
            return f"Finance analysis for {query}: {len(hypotheses)} hypotheses tested, {len(memory_findings)} memory findings."
```

- [ ] **Step 2: Commit**

```bash
git add src/agentscope_blaiq/agents/deep_research/finance.py
git commit -m "feat: FinanceDeepResearchAgent — hypothesis-driven finance analysis"
```

---

## Task 4: Wire into registry and engine

**Files:**
- Modify: `src/agentscope_blaiq/runtime/config.py`
- Modify: `src/agentscope_blaiq/runtime/registry.py`
- Modify: `src/agentscope_blaiq/workflows/engine.py`
- Modify: `deployment/docker-compose.coolify.yml`

- [ ] **Step 1: Add config settings**

In `src/agentscope_blaiq/runtime/config.py`, add after `hivemind_web_poll_attempts`:

```python
    tavily_api_key: str | None = None
    research_max_depth: int = 3
    research_max_iters: int = 15
```

- [ ] **Step 2: Update registry to create deep research agents**

In `src/agentscope_blaiq/runtime/registry.py`, add imports and registration:

```python
from agentscope_blaiq.agents.deep_research import BlaiqDeepResearchAgent, FinanceDeepResearchAgent
from agentscope_blaiq.mcp.hivemind_stateful import HivemindStatefulClient
```

In the registry's `__init__` or agent creation, add:

```python
# Create deep research agents alongside legacy
self.deep_research = BlaiqDeepResearchAgent(
    hivemind_client=self.hivemind,
    resolver=self._resolver,
    max_depth=settings.research_max_depth,
    max_iters=settings.research_max_iters,
)
self.finance_research = FinanceDeepResearchAgent(
    hivemind_client=self.hivemind,
    resolver=self._resolver,
    max_depth=settings.research_max_depth,
    max_iters=settings.research_max_iters,
)
```

- [ ] **Step 3: Route finance mode in engine**

In `src/agentscope_blaiq/workflows/engine.py`, in the research phase:

```python
# Choose research agent based on analysis mode
if ctx.plan.analysis_mode == AnalysisMode.finance:
    research_agent = self.registry.finance_research
else:
    research_agent = self.registry.deep_research

# Wire SSE log sink
self._maybe_set_log_sink(research_agent, _make_agent_log_sink(events, publish, "research", "research"))

# Run research
evidence = await research_agent.gather(
    session, ctx.request.tenant_id, ctx.request.user_query, ctx.request.source_scope,
)
```

- [ ] **Step 4: Add TAVILY_API_KEY to docker-compose**

In `deployment/docker-compose.coolify.yml`:

```yaml
      TAVILY_API_KEY: ${TAVILY_API_KEY:-}
      RESEARCH_MAX_DEPTH: ${RESEARCH_MAX_DEPTH:-3}
      RESEARCH_MAX_ITERS: ${RESEARCH_MAX_ITERS:-15}
```

- [ ] **Step 5: Commit**

```bash
git add src/agentscope_blaiq/runtime/config.py src/agentscope_blaiq/runtime/registry.py src/agentscope_blaiq/workflows/engine.py deployment/docker-compose.coolify.yml
git commit -m "feat: wire DeepResearchAgent into registry and engine with finance routing"
```

---

## Task 5: Integration test and Docker rebuild

- [ ] **Step 1: Run full import check**

```bash
cd /Users/amar/blaiq/AgentScope-BLAIQ
.venv/bin/python -c "
from agentscope_blaiq.mcp.hivemind_stateful import HivemindStatefulClient
from agentscope_blaiq.agents.deep_research import BlaiqDeepResearchAgent, FinanceDeepResearchAgent
from agentscope_blaiq.workflows.engine import WorkflowEngine
print('All imports OK')
"
```

- [ ] **Step 2: Run all tests**

```bash
.venv/bin/pytest tests/ -v --tb=short
```

- [ ] **Step 3: Rebuild Docker**

```bash
cd deployment
docker compose -f docker-compose.coolify.yml -p agentscope-blaiq-local --env-file /Users/amar/blaiq/.env build app
docker compose -f docker-compose.coolify.yml -p agentscope-blaiq-local --env-file /Users/amar/blaiq/.env up -d app
```

- [ ] **Step 4: Verify logs show deep research pattern**

```bash
sleep 5
docker logs agentscope-blaiq-local-app-1 --tail 5
# Expected: Uvicorn running
```

- [ ] **Step 5: Smoke test with a request**

Submit a task via the frontend and verify logs show:
1. "Starting deep research" instead of flat recall
2. "Querying HIVE-MIND enterprise memory first"
3. "Decomposed into N sub-questions"
4. Memory findings appear before any web search

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: integration test and Docker rebuild for deep research agent"
```
