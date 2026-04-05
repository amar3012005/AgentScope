"""BlaiqDeepResearchAgent — tree-search deep research with HIVE-MIND priority.

Replaces the flat ResearchAgent with a decompose-and-research pattern:
  Phase 1: HIVE-MIND deep recall (multi-pass: recall -> AI synthesis -> graph traversal)
  Phase 2: LLM decomposes query into 2-4 sub-questions based on memory gaps
  Phase 3: For each sub-question: HIVE-MIND first, web only if insufficient
  Phase 4: Synthesize summary, build EvidencePack
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscope_blaiq.contracts.evidence import (
    Citation,
    EvidenceContradiction,
    EvidenceFinding,
    EvidenceFreshness,
    EvidencePack,
    EvidenceProvenance,
    SourceRecord,
)
from agentscope_blaiq.runtime.agent_base import AgentLogSink, _noop_sink
from agentscope_blaiq.runtime.config import Settings, settings
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient, HivemindMCPError
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Limits
_MAX_SUB_QUESTIONS = 4
_MIN_SUB_QUESTIONS = 2
_MAX_RECALL_RESULTS = 10
_GRAPH_TRAVERSAL_DEPTH = 2
_WEB_RESULTS_LIMIT = 5
_MIN_FINDING_LENGTH = 20
# HIVE-MIND recall already ranks, scores, dedupes, and filters.
# Don't over-fetch — trust the ranking pipeline. Injection_text has the rich content.
_RECALL_LIMITS = {"quick": 5, "insight": 10, "panorama": 10}

# Junk patterns — same rules as ContentDirectorAgent._is_usable_finding
_JUNK_PREFIXES = ("%PDF",)
_JUNK_SUBSTRINGS = ("\x00", "\\x0")
_JUNK_PHRASES = ("smoke test", "smoke-test", "this file exists to verify")


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _is_usable_finding(summary: str) -> bool:
    """Filter out garbage findings: raw PDF bytes, smoke tests, empty content."""
    text = summary or ""
    if not text or len(text.strip()) < _MIN_FINDING_LENGTH:
        return False
    if any(text.startswith(prefix) for prefix in _JUNK_PREFIXES):
        return False
    if any(sub in text for sub in _JUNK_SUBSTRINGS):
        return False
    lower = text.lower()
    if any(phrase in lower for phrase in _JUNK_PHRASES):
        return False
    return True


def _finding_dedup_key(finding: EvidenceFinding) -> str:
    """Create a deduplication key from the finding's title and first 100 chars of summary."""
    normalized_title = finding.title.strip().lower()
    normalized_summary = finding.summary.strip().lower()[:100]
    raw = f"{normalized_title}|{normalized_summary}"
    return hashlib.md5(raw.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_memories(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract memory list from various HIVE-MIND response formats."""
    for key in ("memories", "results", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if isinstance(payload.get("memory"), dict):
        return [payload["memory"]]
    return []


def _normalize_web_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract web results from various HIVE-MIND web search response formats."""
    for key in ("results", "items", "data", "web_results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_injection_text(payload: dict[str, Any]) -> str | None:
    """Extract injection text from HIVE-MIND recall response."""
    candidates = [payload.get("injection_text"), payload.get("injectionText")]
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend([metadata.get("injection_text"), metadata.get("injectionText")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _clean_injection_line(line: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", line)
    cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.strip(" :;-")


def _injection_to_findings(injection_text: str) -> list[EvidenceFinding]:
    """Convert injection text lines into EvidenceFindings."""
    findings: list[EvidenceFinding] = []
    seen: set[str] = set()
    for raw_line in injection_text.splitlines():
        cleaned = _clean_injection_line(raw_line)
        if not cleaned or len(cleaned) < 18:
            continue
        lowered = cleaned.lower()
        # Skip section headers
        if lowered in {
            "retrieved memories", "key facts", "observation log",
            "user profile", "session context", "chain of note",
        }:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        source_id = f"injection:{hashlib.md5(cleaned.encode()).hexdigest()[:12]}"
        findings.append(EvidenceFinding(
            finding_id=f"memory:{source_id}",
            title="Memory context",
            summary=cleaned,
            source_ids=[source_id],
            confidence=0.7,
        ))
    return findings


class BlaiqDeepResearchAgent:
    """Tree-search deep research agent with HIVE-MIND as primary data source.

    Uses decompose-and-research pattern instead of flat multi-pass recall.
    Produces the same EvidencePack contract as the legacy ResearchAgent.
    """

    def __init__(
        self,
        *,
        hivemind: HivemindMCPClient | None = None,
        resolver: LiteLLMModelResolver | None = None,
        runtime_settings: Settings | None = None,
    ) -> None:
        self._settings = runtime_settings or settings
        self.hivemind = hivemind or HivemindMCPClient(
            rpc_url=self._settings.hivemind_mcp_rpc_url,
            api_key=self._settings.hivemind_api_key,
            timeout_seconds=self._settings.hivemind_timeout_seconds,
            poll_interval_seconds=self._settings.hivemind_web_poll_interval_seconds,
            poll_attempts=self._settings.hivemind_web_poll_attempts,
        )
        self.resolver = resolver or LiteLLMModelResolver.from_settings(self._settings)
        self._log_sink: AgentLogSink = _noop_sink

    def set_log_sink(self, sink: AgentLogSink) -> None:
        """Inject the live event sink for SSE streaming."""
        self._log_sink = sink

    @staticmethod
    def _recall_mode_for_query(query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in (" mode:quick", " use quick", "quick recall", "quicksearch", "fast answer")):
            return "quick"
        if any(token in lowered for token in (" mode:panorama", " use panorama", "panorama recall")):
            return "panorama"
        if any(token in lowered for token in (" mode:insight", " use insight", "insight recall")):
            return "insight"
        if any(token in lowered for token in ("history", "timeline", "evolution", "over time", "journey", "historical")):
            return "panorama"
        if any(token in lowered for token in ("analyze", "analysis", "compare", "pattern", "insight", "decision", "strategy", "relationship", "connections")):
            return "insight"
        # Default to insight — richer context than quick, 2x more memories
        return "insight"

    @classmethod
    def _recall_profile_for_query(cls, query: str) -> tuple[str, int]:
        mode = cls._recall_mode_for_query(query)
        return mode, _RECALL_LIMITS.get(mode, _MAX_RECALL_RESULTS)

    async def _log(
        self,
        message: str,
        *,
        kind: str = "status",
        visibility: str = "user",
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self._log_sink(message, kind, visibility, detail)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def gather(
        self,
        session: Any,
        tenant_id: str,
        user_query: str,
        source_scope: str,
    ) -> EvidencePack:
        """Execute deep research and return an EvidencePack.

        Args:
            session: SQLAlchemy async session (passed through, may not be used).
            tenant_id: Tenant isolation identifier.
            user_query: The research query from the user.
            source_scope: One of "web", "docs", or "all".

        Returns:
            EvidencePack with memory, web, and doc findings.
        """
        await self._log(f"Deep research started: {user_query[:80]}...", kind="status")

        # Phase 1: HIVE-MIND deep recall
        phase1_findings, phase1_sources, phase1_citations, synthesis = (
            await self._phase1_deep_recall(user_query)
        )
        await self._log(
            f"Phase 1 complete: {len(phase1_findings)} memory findings",
            kind="status",
            detail={"finding_count": len(phase1_findings)},
        )

        # Phase 2: Decompose into sub-questions
        memory_summary = synthesis or self._summarize_findings(phase1_findings)
        sub_questions = await self._phase2_decompose(user_query, memory_summary, source_scope)
        await self._log(
            f"Phase 2 complete: {len(sub_questions)} sub-questions",
            kind="thought",
            detail={"sub_questions": sub_questions},
        )

        # Phase 3: Research each sub-question
        sub_findings, sub_sources, sub_citations, web_findings, web_sources, web_citations = (
            await self._phase3_research_sub_questions(sub_questions, source_scope)
        )
        await self._log(
            f"Phase 3 complete: {len(sub_findings)} memory + {len(web_findings)} web findings",
            kind="status",
        )

        # Phase 4: Synthesize and build EvidencePack
        all_memory_findings = self._deduplicate_findings(phase1_findings + sub_findings)
        all_memory_sources = self._deduplicate_sources(phase1_sources + sub_sources)
        all_memory_citations = phase1_citations + sub_citations
        all_web_findings = self._deduplicate_findings(web_findings)
        all_web_sources = self._deduplicate_sources(web_sources)
        all_web_citations = web_citations

        # Compute overall confidence
        if all_memory_findings:
            avg_confidence = sum(f.confidence for f in all_memory_findings) / len(all_memory_findings)
        elif all_web_findings:
            avg_confidence = sum(f.confidence for f in all_web_findings) / len(all_web_findings) * 0.8
        else:
            avg_confidence = 0.2

        summary = await self._phase4_synthesize(
            user_query, all_memory_findings, all_web_findings, synthesis,
        )

        pack = EvidencePack(
            summary=summary,
            sources=all_memory_sources + all_web_sources,
            memory_findings=all_memory_findings,
            web_findings=all_web_findings,
            doc_findings=[],
            open_questions=sub_questions[:2] if avg_confidence < 0.5 else [],
            confidence=round(min(avg_confidence, 1.0), 2),
            citations=all_memory_citations + all_web_citations,
            contradictions=[],
            freshness=EvidenceFreshness(
                memory_is_fresh=bool(all_memory_findings),
                web_verified=bool(all_web_findings),
                freshness_summary=f"Deep research completed with {len(all_memory_findings)} memory and {len(all_web_findings)} web findings",
                checked_at=_now_iso(),
            ),
            provenance=EvidenceProvenance(
                memory_sources=len(all_memory_sources),
                web_sources=len(all_web_sources),
                upload_sources=0,
                graph_traversals=1 if phase1_findings else 0,
                primary_ground_truth="memory" if all_memory_findings else "web",
                save_back_eligible=bool(all_memory_findings),
            ),
            recommended_followups=[],
        )

        await self._log("Deep research complete", kind="status", detail={"confidence": pack.confidence})
        return pack

    async def answer_question(
        self,
        query: str,
        evidence: EvidencePack,
        response_depth: str | None = None,
    ) -> str:
        """Generate a final user-facing answer from an existing evidence pack.

        Uses the *vangogh* model role (Claude Sonnet) for synthesis because it
        follows structured-output and length instructions far more reliably than
        Gemini.  The system prompt leads with the hard length requirement so the
        model commits to it before reading evidence.
        """
        await self._log("Synthesizing final answer from saved evidence.", kind="thought")

        if not (evidence.memory_findings or evidence.web_findings or evidence.doc_findings):
            return "I don't have enough evidence to answer that yet."

        source_count = len(evidence.memory_findings) + len(evidence.web_findings) + len(evidence.doc_findings)
        depth_value = (response_depth or "").strip()
        depth_lower = depth_value.lower()
        if "brief" in depth_lower:
            depth_style = "brief"
            min_words = 40
        elif "technical" in depth_lower or "breakdown" in depth_lower:
            depth_style = "technical"
            min_words = 350
        elif "detailed" in depth_lower:
            depth_style = "detailed"
            min_words = 400
        else:
            depth_style = "balanced"
            min_words = 150

        findings_text = self._format_findings_for_synthesis(
            evidence.memory_findings,
            evidence.web_findings,
        )
        if evidence.doc_findings:
            findings_text = (
                f"{findings_text}\n\n### Document Findings\n"
                + "\n".join(f"- {f.title}: {f.summary}" for f in evidence.doc_findings[:10])
            )

        # ---- System prompt: length requirement FIRST, then rules ----
        if depth_style in {"detailed", "technical"}:
            length_block = (
                f"HARD REQUIREMENT: Your answer MUST be at least {min_words} words. "
                "Count carefully. Answers shorter than this will be rejected.\n\n"
                "The user chose DETAILED mode — they want a COMPREHENSIVE, multi-section answer.\n"
                "- Cover EVERY product, specification, and technical detail present in the evidence.\n"
                "- Use markdown headers (##, ###) to organize by category or product family.\n"
                "- Include specific model names, numbers, specs, features, and capabilities.\n"
                "- A short paragraph is NOT acceptable. Write at least 5 paragraphs.\n"
            )
        elif depth_style == "brief":
            length_block = "Write 1-2 concise paragraphs. Hit the key points only.\n"
        else:
            length_block = (
                f"Write at least {min_words} words in 3-5 paragraphs covering the main findings.\n"
            )

        system_prompt = (
            f"{length_block}\n"
            "You are BLAIQ, a technical knowledge assistant.\n\n"
            "Rules:\n"
            "- Use ONLY the provided evidence — do not add facts from training data.\n"
            "- Extract and list EVERY product name, model number, and spec from the evidence.\n"
            "- Group findings by product family or category.\n"
            "- Use markdown formatting: headers, bullet points, bold for product names.\n"
            "- Do not add a citations/sources section.\n"
        )

        # ---- User prompt: question first, then evidence, then reminder ----
        user_prompt = (
            f"Question: {query}\n"
            f"Response depth: {depth_style}\n\n"
            f"Evidence ({source_count} sources):\n{findings_text}\n\n"
            f"Now write the {depth_style} answer. "
            f"Remember: you MUST write at least {min_words} words."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Use vangogh role (Claude Sonnet) — follows length instructions reliably
        synthesis_role = "vangogh"

        try:
            response = await self.resolver.acompletion(
                synthesis_role,
                messages,
                max_tokens=8000 if depth_style in {"detailed", "technical"} else 2000,
                temperature=0.25,
            )
            text = self.resolver.extract_text(response).strip()
            word_count = len(text.split()) if text else 0
            logger.info("Synthesis first attempt: %d words (min=%d, depth=%s, model_role=%s)",
                        word_count, min_words, depth_style, synthesis_role)
            await self._log(f"First synthesis: {word_count} words (target: {min_words}+).", kind="thought")

            if text:
                if depth_style in {"detailed", "technical"} and word_count < min_words:
                    logger.warning(
                        "Synthesis too short (%d < %d words), retrying with stronger prompt.",
                        word_count, min_words,
                    )
                    retry_messages = [
                        {
                            "role": "system",
                            "content": (
                                f"ABSOLUTE REQUIREMENT: Write at least {min_words} words. "
                                "Your previous answer was REJECTED for being too short.\n\n"
                                "Regenerate with FAR more detail. You must:\n"
                                f"- Write at least {min_words} words (aim for {min_words + 100}).\n"
                                "- Use multi-paragraph structure with markdown headers.\n"
                                "- Cover EVERY distinct finding from the evidence.\n"
                                "- Group by product families/components with technical specifics.\n"
                                "- Stay strictly grounded in provided evidence.\n"
                                "- Do not add a sources/citations section."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Question: {query}\n"
                                f"Depth: {depth_style}\n\n"
                                f"Evidence ({source_count} sources):\n{findings_text}\n\n"
                                f"Generate the detailed answer now. MINIMUM {min_words} words."
                            ),
                        },
                    ]
                    retry = await self.resolver.acompletion(
                        synthesis_role,
                        retry_messages,
                        max_tokens=8000,
                        temperature=0.3,
                    )
                    retry_text = self.resolver.extract_text(retry).strip()
                    retry_wc = len(retry_text.split()) if retry_text else 0
                    logger.info("Synthesis retry: %d words (min=%d)", retry_wc, min_words)
                    if retry_text and retry_wc > word_count:
                        text = retry_text
                    else:
                        logger.warning(
                            "Retry did not improve length (%d vs %d). Using best attempt.",
                            retry_wc, word_count,
                        )
                await self._log("Final answer synthesis completed.", kind="decision")
                return text
        except Exception as exc:
            logger.warning("Deep research answer synthesis failed: %s", exc)

        return evidence.summary or "; ".join(f.summary for f in evidence.memory_findings[:6])

    # ------------------------------------------------------------------
    # Phase 1: HIVE-MIND Deep Recall
    # ------------------------------------------------------------------

    async def _phase1_deep_recall(
        self, query: str
    ) -> tuple[list[EvidenceFinding], list[SourceRecord], list[Citation], str | None]:
        """Multi-pass recall: direct recall -> AI synthesis -> graph traversal."""
        findings: list[EvidenceFinding] = []
        sources: list[SourceRecord] = []
        citations: list[Citation] = []
        synthesis: str | None = None

        if not self.hivemind.enabled:
            return findings, sources, citations, synthesis

        recall_mode, recall_limit = self._recall_profile_for_query(query)
        await self._log(
            f"Phase 1 recall profile selected: mode={recall_mode}, limit={recall_limit}.",
            kind="decision",
        )

        # Pass 1: Direct recall
        try:
            recall_result = await self.hivemind.recall(
                query=query, limit=recall_limit, mode=recall_mode,
            )
            payload = self.hivemind._extract_tool_payload(recall_result) if isinstance(recall_result, dict) else recall_result
            logger.info("Phase 1 recall payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
            memories = _normalize_memories(payload)
            logger.info("Phase 1 normalized memories: %d", len(memories))
            for mem in memories:
                f, s, c = self._memory_to_finding(mem)
                if f is not None:
                    findings.append(f)
                    sources.append(s)
                    citations.append(c)

            # Parse injection text — this is where the REAL detailed content lives
            # (product specs, technical details, full paragraphs). Memory titles are often
            # just meta-descriptions like "The user is discussing..."
            injection = _normalize_injection_text(payload)
            if injection:
                injection_findings = _injection_to_findings(injection)
                # Cap injection findings — HIVE-MIND already ranked them, take top 15
                injection_findings = injection_findings[:15]
                logger.info("Phase 1 injection findings: %d (capped)", len(injection_findings))
                findings.extend(injection_findings)
        except HivemindMCPError as exc:
            logger.warning("Phase 1 recall failed: %s", exc)
            await self._log(f"Memory recall error (continuing): {exc}", kind="status", visibility="debug")

        # Pass 2: AI synthesis
        try:
            ai_result = await self.hivemind.query_with_ai(question=query, context_limit=8)
            ai_payload = self.hivemind._extract_tool_payload(ai_result) if isinstance(ai_result, dict) else ai_result
            answer = ai_payload.get("answer") or ai_payload.get("text") or ""
            if isinstance(answer, str) and answer.strip():
                synthesis = answer.strip()
        except HivemindMCPError as exc:
            logger.warning("Phase 1 AI synthesis failed: %s", exc)

        # Pass 3: Graph traversal on top-scoring memories
        top_memory_ids = [f.source_ids[0] for f in findings if f.source_ids][:3]
        for memory_id in top_memory_ids:
            try:
                graph_result = await self.hivemind.traverse_graph(
                    memory_id=memory_id, depth=_GRAPH_TRAVERSAL_DEPTH,
                )
                graph_payload = (
                    self.hivemind._extract_tool_payload(graph_result)
                    if isinstance(graph_result, dict) else graph_result
                )
                graph_memories = _normalize_memories(graph_payload)
                for mem in graph_memories:
                    f, s, c = self._memory_to_finding(mem, source_prefix="graph")
                    if f is not None:
                        findings.append(f)
                        sources.append(s)
                        citations.append(c)
            except HivemindMCPError as exc:
                logger.warning("Graph traversal failed for %s: %s", memory_id, exc)

        return findings, sources, citations, synthesis

    # ------------------------------------------------------------------
    # Phase 2: Decompose Query
    # ------------------------------------------------------------------

    async def _phase2_decompose(
        self, query: str, memory_summary: str, source_scope: str,
    ) -> list[str]:
        """Use LLM to decompose query into sub-questions based on memory gaps."""
        prompt_template = _load_prompt("decompose_subtask.md")
        prompt = prompt_template.replace("{query}", query)
        prompt = prompt.replace("{memory_summary}", memory_summary or "No memory findings yet.")
        prompt = prompt.replace("{source_scope}", source_scope)

        messages = [
            {"role": "system", "content": "You are a research planner. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=1024, temperature=0.3,
            )
            text = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(text)
            sub_questions = parsed.get("sub_questions", [])
            if isinstance(sub_questions, list) and len(sub_questions) >= _MIN_SUB_QUESTIONS:
                return sub_questions[:_MAX_SUB_QUESTIONS]
        except Exception as exc:
            logger.warning("Decomposition LLM call failed: %s", exc)
            await self._log(f"Decomposition failed, using fallback: {exc}", kind="status", visibility="debug")

        # Fallback: generate basic sub-questions
        return self._fallback_decompose(query)

    @staticmethod
    def _fallback_decompose(query: str) -> list[str]:
        """Generate basic sub-questions when LLM decomposition fails."""
        return [
            f"What background context and history exists for: {query}",
            f"What are the key facts and data points relevant to: {query}",
        ]

    # ------------------------------------------------------------------
    # Phase 3: Research Sub-questions
    # ------------------------------------------------------------------

    async def _phase3_research_sub_questions(
        self,
        sub_questions: list[str],
        source_scope: str,
    ) -> tuple[
        list[EvidenceFinding], list[SourceRecord], list[Citation],
        list[EvidenceFinding], list[SourceRecord], list[Citation],
    ]:
        """Research each sub-question concurrently: memory first, web if needed."""
        tasks = [
            self._research_single_sub_question(sq, source_scope)
            for sq in sub_questions
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_mem_findings: list[EvidenceFinding] = []
        all_mem_sources: list[SourceRecord] = []
        all_mem_citations: list[Citation] = []
        all_web_findings: list[EvidenceFinding] = []
        all_web_sources: list[SourceRecord] = []
        all_web_citations: list[Citation] = []

        for result in results:
            if isinstance(result, Exception):
                logger.warning("Sub-question research failed: %s", result)
                continue
            mem_f, mem_s, mem_c, web_f, web_s, web_c = result
            all_mem_findings.extend(mem_f)
            all_mem_sources.extend(mem_s)
            all_mem_citations.extend(mem_c)
            all_web_findings.extend(web_f)
            all_web_sources.extend(web_s)
            all_web_citations.extend(web_c)

        return (
            all_mem_findings, all_mem_sources, all_mem_citations,
            all_web_findings, all_web_sources, all_web_citations,
        )

    async def _research_single_sub_question(
        self, sub_question: str, source_scope: str,
    ) -> tuple[
        list[EvidenceFinding], list[SourceRecord], list[Citation],
        list[EvidenceFinding], list[SourceRecord], list[Citation],
    ]:
        """Research a single sub-question: HIVE-MIND first, web if insufficient."""
        mem_findings: list[EvidenceFinding] = []
        mem_sources: list[SourceRecord] = []
        mem_citations: list[Citation] = []
        web_findings: list[EvidenceFinding] = []
        web_sources: list[SourceRecord] = []
        web_citations: list[Citation] = []

        # Memory recall for sub-question
        if self.hivemind.enabled:
            try:
                sub_mode, sub_limit = self._recall_profile_for_query(sub_question)
                recall_result = await self.hivemind.recall(
                    query=sub_question, limit=sub_limit, mode=sub_mode,
                )
                payload = (
                    self.hivemind._extract_tool_payload(recall_result)
                    if isinstance(recall_result, dict) else recall_result
                )
                memories = _normalize_memories(payload)
                for mem in memories:
                    f, s, c = self._memory_to_finding(mem, source_prefix="sub")
                    if f is not None:
                        mem_findings.append(f)
                        mem_sources.append(s)
                        mem_citations.append(c)
                # Skip injection text for sub-questions — Phase 1 already captured it
            except HivemindMCPError as exc:
                logger.warning("Sub-question memory recall failed for '%s': %s", sub_question[:40], exc)

        # Web search only if memory insufficient and scope allows
        memory_sufficient = len(mem_findings) >= 2
        scope_allows_web = source_scope in ("web", "all")
        if not memory_sufficient and scope_allows_web and self.hivemind.enabled:
            try:
                web_result = await self.hivemind.web_search(
                    query=sub_question, limit=_WEB_RESULTS_LIMIT,
                )
                web_payload = (
                    self.hivemind._extract_tool_payload(web_result)
                    if isinstance(web_result, dict) else web_result
                )
                results = _normalize_web_results(web_payload)
                for item in results:
                    f, s, c = self._web_result_to_finding(item)
                    if f is not None:
                        web_findings.append(f)
                        web_sources.append(s)
                        web_citations.append(c)
            except HivemindMCPError as exc:
                logger.warning("Sub-question web search failed for '%s': %s", sub_question[:40], exc)

        return mem_findings, mem_sources, mem_citations, web_findings, web_sources, web_citations

    # ------------------------------------------------------------------
    # Phase 4: Synthesize
    # ------------------------------------------------------------------

    async def _phase4_synthesize(
        self,
        query: str,
        memory_findings: list[EvidenceFinding],
        web_findings: list[EvidenceFinding],
        ai_synthesis: str | None,
    ) -> str:
        """Produce a final research summary via LLM."""
        evidence_text = self._format_findings_for_synthesis(memory_findings, web_findings)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a technical research synthesizer for enterprise knowledge.\n\n"
                    "RULES:\n"
                    "1. Extract and highlight SPECIFIC technical details: product names, model numbers, "
                    "architecture components, API endpoints, frameworks, methodologies, metrics, and specifications.\n"
                    "2. Cite sources using [memory:ID] format for every factual claim.\n"
                    "3. Structure the summary with clear sections: Overview, Key Technical Details, "
                    "Architecture/Methodology, Metrics/Results.\n"
                    "4. Preserve exact names, numbers, and technical terms from the evidence — do NOT paraphrase technical details.\n"
                    "5. If the evidence mentions company/product names, technologies, or specifications, "
                    "list them explicitly — the user wants KEY INFORMATION, not vague summaries.\n"
                    "6. Interpret any acronyms or terms based on the evidence context, NOT your training data."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"=== EVIDENCE (read first) ===\n{evidence_text}\n\n"
                    f"=== AI SYNTHESIS FROM MEMORY ===\n{ai_synthesis or 'None available'}\n\n"
                    f"=== QUESTION ===\n{query}\n\n"
                    "Generate a structured research summary (3-6 paragraphs) that:\n"
                    "- Leads with the most important technical finding\n"
                    "- Lists specific product names, technologies, specs, and metrics\n"
                    "- Attributes every claim to a source [memory:ID]\n"
                    "- Ends with key takeaways or recommended next steps"
                ),
            },
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=2048, temperature=0.3,
            )
            return self.resolver.extract_text(response)
        except Exception as exc:
            logger.warning("Synthesis LLM call failed: %s", exc)
            # Fallback: return AI synthesis or concatenated findings
            if ai_synthesis:
                return ai_synthesis
            if memory_findings:
                return "; ".join(f.summary for f in memory_findings[:5])
            if web_findings:
                return "; ".join(f.summary for f in web_findings[:5])
            return f"Research completed for: {query}. Insufficient evidence found."

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _memory_to_finding(
        self, mem: dict[str, Any], source_prefix: str = "memory",
    ) -> tuple[EvidenceFinding | None, SourceRecord, Citation]:
        """Convert a HIVE-MIND memory dict into finding/source/citation."""
        memory_id = str(mem.get("memory_id", mem.get("id", "")))
        raw_title = str(mem.get("title", "Untitled memory"))
        content = str(mem.get("content", mem.get("text", mem.get("summary", ""))))
        score = float(mem.get("score", mem.get("relevance", 0.5)))

        # HIVE-MIND titles are often meta-descriptions ("The user is discussing...")
        # Use the first meaningful sentence from content as the display title instead
        title = raw_title
        if content and (
            raw_title.startswith("The user") or
            raw_title.startswith("Fact:") or
            "no personal facts" in raw_title.lower() or
            len(raw_title) < 15
        ):
            # Extract first sentence of content as title
            first_sentence = content.split(".")[0].strip()
            if len(first_sentence) > 15:
                title = first_sentence[:120] + ("..." if len(first_sentence) > 120 else "")

        source = SourceRecord(
            source_id=memory_id,
            source_type="hivemind_memory",
            title=title,
            location=f"hivemind://{memory_id}",
            metadata={"score": str(score)},
        )
        citation = Citation(
            source_id=memory_id,
            label=title,
            excerpt=content[:200] if content else None,
        )

        if not _is_usable_finding(content):
            return None, source, citation

        finding = EvidenceFinding(
            finding_id=f"{source_prefix}:{memory_id}",
            title=title,
            summary=content,
            source_ids=[memory_id],
            confidence=min(score, 1.0),
        )
        return finding, source, citation

    def _web_result_to_finding(
        self, item: dict[str, Any],
    ) -> tuple[EvidenceFinding | None, SourceRecord, Citation]:
        """Convert a HIVE-MIND web search result into finding/source/citation."""
        url = str(item.get("url", item.get("link", "")))
        title = str(item.get("title", "Web result"))
        snippet = str(item.get("snippet", item.get("content", item.get("description", ""))))
        source_id = f"web:{hashlib.md5(url.encode()).hexdigest()[:12]}"

        source = SourceRecord(
            source_id=source_id,
            source_type="web",
            title=title,
            location=url,
        )
        citation = Citation(
            source_id=source_id,
            label=title,
            excerpt=snippet[:200] if snippet else None,
            url=url,
        )

        if not _is_usable_finding(snippet):
            return None, source, citation

        finding = EvidenceFinding(
            finding_id=f"web:{source_id}",
            title=title,
            summary=snippet,
            source_ids=[source_id],
            confidence=0.6,
        )
        return finding, source, citation

    @staticmethod
    def _summarize_findings(findings: list[EvidenceFinding]) -> str:
        """Build a brief text summary from findings for the decomposition prompt."""
        if not findings:
            return "No findings from initial recall."
        parts = [f"- {f.title}: {f.summary[:200]}" for f in findings[:15]]
        return "\n".join(parts)

    @staticmethod
    def _format_findings_for_synthesis(
        memory_findings: list[EvidenceFinding],
        web_findings: list[EvidenceFinding],
        *,
        max_memory: int = 30,
        max_web: int = 10,
        max_summary_chars: int = 600,
    ) -> str:
        """Format findings as text for the synthesis prompt.

        Applies smart filtering to maximise signal-to-noise:
        1. Skips meta-description findings ("The user is discussing...")
        2. Skips conversation log artefacts ("Assistant: I don't have")
        3. Deduplicates title == summary (shows text only once)
        4. Sorts by summary length descending (content-rich findings first)
        5. Truncates long findings to *max_summary_chars*
        """
        import re

        _NOISE_PATTERNS: list[re.Pattern[str]] = [
            re.compile(r"(?i)^the user is discussing"),
            re.compile(r"(?i)^the user (asked|mentioned|said|wants|is asking)"),
            re.compile(r"(?i)^amar (is|was) (asking|discussing|talking)"),
            re.compile(r"(?i)assistant:\s*i don'?t have"),
            re.compile(r"(?i)i don'?t have that in my memory"),
            re.compile(r"(?i)^chat:\s"),
        ]

        def _is_noise(text: str) -> bool:
            return any(p.search(text) for p in _NOISE_PATTERNS)

        def _clean_findings(raw: list[EvidenceFinding], limit: int) -> list[EvidenceFinding]:
            filtered: list[EvidenceFinding] = []
            for f in raw:
                summary = (f.summary or "").strip()
                if not summary or len(summary) < 15:
                    continue
                if _is_noise(summary):
                    continue
                if _is_noise(f.title or ""):
                    continue
                filtered.append(f)
            # Sort by summary length descending — content-rich findings first
            filtered.sort(key=lambda x: len(x.summary or ""), reverse=True)
            return filtered[:limit]

        def _format_one(f: EvidenceFinding) -> str:
            title = (f.title or "").strip()
            summary = (f.summary or "").strip()[:max_summary_chars]
            # If title duplicates or is contained in summary, skip the title
            if not title or title == summary or title in summary:
                return f"[{f.finding_id}] {summary}"
            return f"[{f.finding_id}] {title}: {summary}"

        sections: list[str] = []
        clean_memory = _clean_findings(memory_findings or [], max_memory)
        if clean_memory:
            sections.append("### Memory Findings")
            for f in clean_memory:
                sections.append(_format_one(f))
        clean_web = _clean_findings(web_findings or [], max_web)
        if clean_web:
            sections.append("### Web Findings")
            for f in clean_web:
                sections.append(_format_one(f))
        return "\n".join(sections) if sections else "No evidence available."

    @staticmethod
    def _deduplicate_findings(findings: list[EvidenceFinding]) -> list[EvidenceFinding]:
        """Remove duplicate findings based on content similarity."""
        seen: set[str] = set()
        deduped: list[EvidenceFinding] = []
        for f in findings:
            key = _finding_dedup_key(f)
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return deduped

    @staticmethod
    def _deduplicate_sources(sources: list[SourceRecord]) -> list[SourceRecord]:
        """Remove duplicate sources by source_id."""
        seen: set[str] = set()
        deduped: list[SourceRecord] = []
        for s in sources:
            if s.source_id not in seen:
                seen.add(s.source_id)
                deduped.append(s)
        return deduped
