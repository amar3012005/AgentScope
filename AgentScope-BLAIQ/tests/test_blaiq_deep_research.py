"""Tests for BlaiqDeepResearchAgent."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentscope_blaiq.agents.deep_research.base import (
    BlaiqDeepResearchAgent,
    _finding_dedup_key,
    _is_usable_finding,
    _injection_to_findings,
)
from agentscope_blaiq.contracts.evidence import EvidenceFinding, EvidencePack
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient, HivemindMCPError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeHivemindClient(HivemindMCPClient):
    """In-memory fake for HIVE-MIND MCP that returns predictable results."""

    def __init__(self) -> None:
        super().__init__(rpc_url="https://example.com/mcp", api_key="test-key")
        self.recall_queries: list[str] = []
        self.recall_modes: list[str] = []
        self.web_queries: list[str] = []
        self.ai_questions: list[str] = []
        self.traversed_ids: list[str] = []

    async def recall(self, *, query: str, limit: int = 20, mode: str = "insight") -> dict[str, Any]:
        self.recall_queries.append(query)
        self.recall_modes.append(mode)
        lower = query.lower()
        if "background" in lower or "history" in lower:
            return {
                "memories": [
                    {
                        "memory_id": "mem-bg-1",
                        "title": "Background context",
                        "content": "BLAIQ is an AI-powered content generation platform built by Da'vinci Solutions.",
                        "score": 0.85,
                    }
                ]
            }
        if "key facts" in lower or "data points" in lower:
            return {
                "memories": [
                    {
                        "memory_id": "mem-facts-1",
                        "title": "Key product facts",
                        "content": "BLAIQ supports multi-tenant workflows with HIVE-MIND memory integration.",
                        "score": 0.82,
                    }
                ]
            }
        return {
            "memories": [
                {
                    "memory_id": "mem-main-1",
                    "title": "Primary research result",
                    "content": "Enterprise research capabilities include deep memory search and web augmentation.",
                    "score": 0.90,
                },
                {
                    "memory_id": "mem-main-2",
                    "title": "Secondary research result",
                    "content": "The platform uses GraphRAG for knowledge graph traversal and retrieval.",
                    "score": 0.78,
                },
            ]
        }

    async def query_with_ai(self, *, question: str, context_limit: int = 8) -> dict[str, Any]:
        self.ai_questions.append(question)
        return {"answer": "Synthesized answer from HIVE-MIND AI: BLAIQ provides enterprise research."}

    async def traverse_graph(self, *, memory_id: str, depth: int = 2) -> dict[str, Any]:
        self.traversed_ids.append(memory_id)
        return {
            "memories": [
                {
                    "memory_id": f"graph-{memory_id}",
                    "title": f"Graph traversal from {memory_id}",
                    "content": f"Related context discovered via graph from {memory_id}.",
                    "score": 0.65,
                }
            ]
        }

    async def web_search(self, *, query: str, domains: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        self.web_queries.append(query)
        return {
            "results": [
                {
                    "url": "https://example.com/result",
                    "title": "Web research result",
                    "snippet": "External web information about enterprise AI research platforms.",
                }
            ]
        }


class FakeHivemindNoMemory(FakeHivemindClient):
    """Returns empty memories to trigger web fallback."""

    async def recall(self, *, query: str, limit: int = 20, mode: str = "insight") -> dict[str, Any]:
        self.recall_queries.append(query)
        self.recall_modes.append(mode)
        return {"memories": []}

    async def query_with_ai(self, *, question: str, context_limit: int = 8) -> dict[str, Any]:
        self.ai_questions.append(question)
        return {"answer": ""}

    async def traverse_graph(self, *, memory_id: str, depth: int = 2) -> dict[str, Any]:
        return {"memories": []}


class FlakyHivemindClient(FakeHivemindClient):
    """Fails on first recall call, succeeds after."""

    def __init__(self) -> None:
        super().__init__()
        self._recall_call_count = 0

    async def recall(self, *, query: str, limit: int = 20, mode: str = "insight") -> dict[str, Any]:
        self._recall_call_count += 1
        if self._recall_call_count == 1:
            raise HivemindMCPError("simulated timeout")
        return await super().recall(query=query, limit=limit, mode=mode)


def _make_fake_llm_response(text: str) -> MagicMock:
    """Build a mock LiteLLM response."""
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message = MagicMock()
    mock.choices[0].message.content = text
    return mock


def _build_agent(
    hivemind: HivemindMCPClient | None = None,
    decompose_response: dict[str, Any] | None = None,
    synthesis_response: str | None = None,
) -> BlaiqDeepResearchAgent:
    """Build agent with mocked LLM resolver."""
    hm = hivemind or FakeHivemindClient()
    agent = BlaiqDeepResearchAgent(hivemind=hm)

    decompose = decompose_response or {
        "sub_questions": [
            "What background context and history exists for this topic?",
            "What are the key facts and data points relevant to this query?",
        ],
        "reasoning": "These sub-questions cover history and current facts.",
    }
    synth = synthesis_response or "Comprehensive research summary based on memory and web findings."

    call_count = {"n": 0}

    async def fake_acompletion(role: str, messages: list[dict], **kwargs: Any) -> Any:
        call_count["n"] += 1
        # First call is decomposition, second is synthesis
        if call_count["n"] == 1:
            return _make_fake_llm_response(json.dumps(decompose))
        return _make_fake_llm_response(synth)

    agent.resolver = MagicMock()
    agent.resolver.acompletion = AsyncMock(side_effect=fake_acompletion)
    agent.resolver.extract_text = lambda resp: resp.choices[0].message.content
    agent.resolver.extract_json_text = lambda text: text
    agent.resolver.safe_json_loads = lambda text: json.loads(text)

    return agent


# ---------------------------------------------------------------------------
# Unit tests: filtering and dedup helpers
# ---------------------------------------------------------------------------

class TestIsUsableFinding:
    def test_empty_string(self) -> None:
        assert _is_usable_finding("") is False

    def test_short_string(self) -> None:
        assert _is_usable_finding("too short") is False

    def test_pdf_prefix(self) -> None:
        assert _is_usable_finding("%PDF-1.4 some binary content here") is False

    def test_null_bytes(self) -> None:
        assert _is_usable_finding("some content with \x00 null bytes inside") is False

    def test_smoke_test(self) -> None:
        assert _is_usable_finding("This is a smoke test file for the system") is False

    def test_file_exists_to_verify(self) -> None:
        assert _is_usable_finding("This file exists to verify upload pipeline works") is False

    def test_valid_finding(self) -> None:
        assert _is_usable_finding("BLAIQ provides enterprise research and content generation capabilities.") is True


class TestFindingDedup:
    def test_same_content_same_key(self) -> None:
        f1 = EvidenceFinding(finding_id="a", title="Title", summary="Same summary content here for testing dedup")
        f2 = EvidenceFinding(finding_id="b", title="Title", summary="Same summary content here for testing dedup")
        assert _finding_dedup_key(f1) == _finding_dedup_key(f2)

    def test_different_content_different_key(self) -> None:
        f1 = EvidenceFinding(finding_id="a", title="Title A", summary="First unique summary content")
        f2 = EvidenceFinding(finding_id="b", title="Title B", summary="Second unique summary content")
        assert _finding_dedup_key(f1) != _finding_dedup_key(f2)


class TestInjectionToFindings:
    def test_extracts_findings_from_injection(self) -> None:
        injection = """
        <user-profile>
        Key Facts:
        - You are currently working on BLAIQ and HIVE-MIND this quarter.
        - You are a founder at DaVinci AI Solutions.
        </user-profile>
        """
        findings = _injection_to_findings(injection)
        assert len(findings) >= 2
        assert any("BLAIQ" in f.summary for f in findings)
        assert all(f.source_ids[0].startswith("injection:") for f in findings)

    def test_skips_short_lines(self) -> None:
        findings = _injection_to_findings("short\nanother")
        assert len(findings) == 0

    def test_deduplicates_lines(self) -> None:
        injection = "This is a long enough line to pass filter.\nThis is a long enough line to pass filter."
        findings = _injection_to_findings(injection)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# Integration tests: gather() flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_returns_evidence_pack() -> None:
    agent = _build_agent()
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="What is BLAIQ's enterprise research capability?",
        source_scope="all",
    )
    assert isinstance(pack, EvidencePack)
    assert pack.summary
    assert pack.confidence > 0


@pytest.mark.asyncio
async def test_gather_populates_memory_findings() -> None:
    hivemind = FakeHivemindClient()
    agent = _build_agent(hivemind=hivemind)
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Tell me about BLAIQ",
        source_scope="all",
    )
    assert len(pack.memory_findings) > 0
    # Phase 1 direct recall should have produced findings
    assert any("mem-main" in f.finding_id for f in pack.memory_findings)


@pytest.mark.asyncio
async def test_gather_uses_ai_synthesis() -> None:
    hivemind = FakeHivemindClient()
    agent = _build_agent(hivemind=hivemind)
    await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Tell me about BLAIQ",
        source_scope="all",
    )
    assert len(hivemind.ai_questions) == 1


@pytest.mark.asyncio
async def test_gather_traverses_graph() -> None:
    hivemind = FakeHivemindClient()
    agent = _build_agent(hivemind=hivemind)
    await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Tell me about BLAIQ",
        source_scope="all",
    )
    # Should traverse graph for top memories from phase 1
    assert len(hivemind.traversed_ids) > 0


@pytest.mark.asyncio
async def test_sub_question_decomposition_works() -> None:
    hivemind = FakeHivemindClient()
    custom_decompose = {
        "sub_questions": [
            "What is the architecture of BLAIQ?",
            "What are the key integrations?",
            "What deployment options exist?",
        ],
        "reasoning": "Testing 3 sub-questions.",
    }
    agent = _build_agent(hivemind=hivemind, decompose_response=custom_decompose)
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Give me a complete overview of BLAIQ",
        source_scope="all",
    )
    # Sub-questions should have triggered additional recall queries
    # Phase 1 does 1 recall, plus 3 sub-question recalls
    assert len(hivemind.recall_queries) >= 4


@pytest.mark.asyncio
async def test_deduplication_removes_duplicates() -> None:
    agent = _build_agent()
    findings = [
        EvidenceFinding(finding_id="a", title="Same Title", summary="Same summary content for dedup testing"),
        EvidenceFinding(finding_id="b", title="Same Title", summary="Same summary content for dedup testing"),
        EvidenceFinding(finding_id="c", title="Different", summary="Totally different finding content here"),
    ]
    deduped = agent._deduplicate_findings(findings)
    assert len(deduped) == 2


@pytest.mark.asyncio
async def test_gather_with_web_fallback_when_memory_empty() -> None:
    hivemind = FakeHivemindNoMemory()
    agent = _build_agent(hivemind=hivemind)
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="What is the latest AI news?",
        source_scope="web",
    )
    # With no memory, web search should be triggered for sub-questions
    assert len(hivemind.web_queries) > 0
    assert len(pack.web_findings) > 0


@pytest.mark.asyncio
async def test_gather_docs_scope_skips_web() -> None:
    hivemind = FakeHivemindNoMemory()
    agent = _build_agent(hivemind=hivemind)
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Search internal docs only",
        source_scope="docs",
    )
    # "docs" scope should not trigger web search
    assert len(hivemind.web_queries) == 0


@pytest.mark.asyncio
async def test_gather_continues_when_recall_fails() -> None:
    hivemind = FlakyHivemindClient()
    agent = _build_agent(hivemind=hivemind)
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Tell me about BLAIQ",
        source_scope="all",
    )
    # Phase 1 recall fails, but sub-question recalls succeed
    assert isinstance(pack, EvidencePack)
    assert pack.summary


@pytest.mark.asyncio
async def test_gather_provenance_tracks_sources() -> None:
    hivemind = FakeHivemindClient()
    agent = _build_agent(hivemind=hivemind)
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Tell me about BLAIQ",
        source_scope="all",
    )
    assert pack.provenance.memory_sources > 0
    assert pack.provenance.primary_ground_truth == "memory"
    assert pack.provenance.graph_traversals >= 1


@pytest.mark.asyncio
async def test_gather_freshness_info() -> None:
    agent = _build_agent()
    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Tell me about BLAIQ",
        source_scope="all",
    )
    assert pack.freshness.memory_is_fresh is True
    assert pack.freshness.checked_at is not None


@pytest.mark.asyncio
async def test_set_log_sink() -> None:
    agent = _build_agent()
    log_messages: list[str] = []

    async def capture_sink(msg: str, kind: str, vis: str, detail: dict | None = None) -> None:
        log_messages.append(msg)

    agent.set_log_sink(capture_sink)
    await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Test logging",
        source_scope="all",
    )
    assert len(log_messages) > 0
    assert any("Deep research" in m for m in log_messages)


@pytest.mark.asyncio
async def test_fallback_decompose() -> None:
    subs = BlaiqDeepResearchAgent._fallback_decompose("What is quantum computing?")
    assert len(subs) == 2
    assert all("quantum computing" in s.lower() for s in subs)


@pytest.mark.asyncio
async def test_gather_handles_llm_decompose_failure() -> None:
    """When LLM decomposition fails, fallback sub-questions are used."""
    hivemind = FakeHivemindClient()
    agent = BlaiqDeepResearchAgent(hivemind=hivemind)

    async def failing_acompletion(role: str, messages: list[dict], **kwargs: Any) -> Any:
        raise RuntimeError("LLM unavailable")

    agent.resolver = MagicMock()
    agent.resolver.acompletion = AsyncMock(side_effect=failing_acompletion)
    agent.resolver.extract_text = lambda resp: ""
    agent.resolver.safe_json_loads = lambda text: {}

    pack = await agent.gather(
        session=None,
        tenant_id="tenant-1",
        user_query="Test with broken LLM",
        source_scope="all",
    )
    # Should still produce a pack using fallback decomposition and fallback synthesis
    assert isinstance(pack, EvidencePack)
    assert pack.summary
