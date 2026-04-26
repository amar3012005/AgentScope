"""BlaiqDeepResearchAgent — tree-search deep research with HIVE-MIND priority.

Implements the official AgentScope Deep Research pattern:
  - Stack-based task decomposition & expansion
  - Deep search with recursive information filling
  - Self-reflection on failures
  - Intermediate report generation with citations

Extends with HIVE-MIND enterprise memory integration:
  - Phase 1: HIVE-MIND deep recall (multi-pass)
  - Phase 2: LLM decomposes query into subtasks
  - Phase 3: Research each subtask (memory-first, web-if-needed)
  - Phase 4: Synthesize final report from intermediate drafts
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscope_blaiq.contracts.evidence import (
    Citation,
    ContentBriefHandoff,
    ContentHook,
    EvidenceContradiction,
    EvidenceFinding,
    EvidenceFreshness,
    EvidencePack,
    EvidenceProvenance,
    ResearchCacheEntry,
    RiskFlag,
    SourceRecord,
    StructuredInsight,
)
from agentscope_blaiq.runtime.agent_base import AgentLogSink, _noop_sink
from agentscope_blaiq.runtime.config import Settings, settings
from agentscope_blaiq.runtime.hivemind_client import get_hivemind_client
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient, HivemindMCPError
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class Subtask:
    """A research subtask with stack-based management.

    Attributes:
        objective: The research question or goal
        working_plan: Specific steps to complete this subtask
        knowledge_gaps: What information is missing
        status: pending | in_progress | completed | failed | reflected
        findings: Evidence gathered for this subtask
        parent_id: Parent task ID (None for root tasks)
        depth: Depth in task tree (0 for root)
        reflection_count: Number of times this task was reflected upon
    """
    objective: str
    working_plan: str | None = None
    knowledge_gaps: str | None = None
    status: str = "pending"
    findings: list[EvidenceFinding] = field(default_factory=list)
    parent_id: str | None = None
    depth: int = 0
    reflection_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON/logging."""
        return {
            "objective": self.objective,
            "working_plan": self.working_plan,
            "knowledge_gaps": self.knowledge_gaps,
            "status": self.status,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "finding_count": len(self.findings),
            "reflection_count": self.reflection_count,
        }


# Limits
_MAX_SUB_QUESTIONS = 3      # max branches per decomposition step
_MIN_SUB_QUESTIONS = 2
_MAX_TASK_DEPTH = 2        # depth 0→1→2 = max 3+9 = 12 research tasks
_MAX_TOTAL_TASKS = 12      # hard cap: never exceed this many tasks total


def _extract_partial_decomposition(text: str) -> dict:
    """Recover sub_questions from a truncated / fence-wrapped LLM response.

    Used when ``safe_json_loads`` fails (typically because max_tokens was hit
    and the closing braces are missing).  Pulls ``"question"`` strings out of
    the partial payload so research can still proceed with partial decomposition.
    """
    import re
    # Strip markdown fences first
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip())
    stripped = re.sub(r"\s*```\s*$", "", stripped)

    # Extract every "question": "..." value from the partial JSON
    questions_found = re.findall(r'"question"\s*:\s*"([^"]{10,})"', stripped)

    sub_questions = [{"question": q} for q in questions_found[:_MAX_SUB_QUESTIONS]]
    return {"sub_questions": sub_questions, "knowledge_gaps_summary": ""}
_MAX_RECALL_RESULTS = 10
_GRAPH_TRAVERSAL_DEPTH = 2
_WEB_RESULTS_LIMIT = 5
_MIN_FINDING_LENGTH = 20
_MAX_REFLECTIONS_PER_TASK = 2  # Avoid infinite reflection loops
# _MAX_TASK_DEPTH defined at top of file (value: 2)
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


def _avg_conf(findings: list[EvidenceFinding]) -> float:
    """Compute average confidence for a finding set with a safe empty fallback."""
    if not findings:
        return 0.0
    return sum(f.confidence for f in findings) / len(findings)


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
    # Public API — Stack-based Deep Research
    # ------------------------------------------------------------------

    async def gather(
        self,
        session: Any,
        tenant_id: str,
        user_query: str,
        source_scope: str,
        quick_recall: bool = False,
    ) -> EvidencePack:
        """Execute stack-based deep research with reflection and intermediate reports.

        Implements the official AgentScope Deep Research pattern:
        1. Initial HIVE-MIND recall for context
        2. Push root task onto stack
        3. While stack not empty:
           a. Pop current task
           b. Decompose if needed (push children)
           c. Research (memory-first, web-if-needed)
           d. Reflect on failures
           e. Update intermediate report
        4. Synthesize final report from intermediate drafts

        Args:
            session: SQLAlchemy async session (passed through, may not be used).
            tenant_id: Tenant isolation identifier.
            user_query: The research query from the user.
            source_scope: One of "web", "docs", or "all".
            quick_recall: If True, skip deep research tree and return only HIVE-MIND recall.

        Returns:
            EvidencePack with memory, web, and doc findings.
        """
        if quick_recall:
            # Quick mode: just HIVE-MIND recall, no decomposition tree
            return await self._quick_recall_gather(user_query, source_scope)

        await self._log(f"Deep research started: {user_query[:80]}...", kind="status")

        # Initialize task stack and intermediate report
        task_stack: list[Subtask] = []
        completed_tasks: list[Subtask] = []
        intermediate_report: list[str] = []
        all_findings: list[EvidenceFinding] = []
        all_sources: list[SourceRecord] = []
        all_citations: list[Citation] = []
        all_web_findings: list[EvidenceFinding] = []
        all_web_sources: list[SourceRecord] = []
        all_web_citations: list[Citation] = []

        # Phase 1: Initial HIVE-MIND recall for context
        phase1_findings, phase1_sources, phase1_citations, synthesis = (
            await self._phase1_deep_recall(user_query)
        )
        all_findings.extend(phase1_findings)
        all_sources.extend(phase1_sources)
        all_citations.extend(phase1_citations)

        await self._log(
            f"Phase 1 (recall) complete: {len(phase1_findings)} memory findings",
            kind="status",
            detail={"finding_count": len(phase1_findings)},
        )

        # Phase 2: Create root task and decompose
        root_task = Subtask(
            objective=user_query,
            working_plan=None,  # Will be filled by decomposition
            knowledge_gaps=None,
            status="pending",
            depth=0,
        )
        task_stack.append(root_task)

        await self._log("Phase 2 (task stack) initialized with root task", kind="status")

        # Phase 3: Stack-based research loop
        reflection_failures: list[str] = []
        processed_objectives: set[str] = set()  # Track to avoid infinite loops

        def normalize_objective(obj: str) -> str:
            """Normalize objective for duplicate detection."""
            # Lowercase, strip whitespace, remove common prefixes
            normalized = obj.lower().strip()
            # Remove "what is/are" prefixes for comparison
            normalized = re.sub(r'^(what\s+is|what\s+are|how\s+to|describe|explain|summarize)\s+', '', normalized)
            # Remove trailing question marks and extra spaces
            normalized = normalized.rstrip('?').strip()
            # Hash long objectives for efficient comparison
            if len(normalized) > 100:
                return hashlib.md5(normalized.encode()).hexdigest()
            return normalized

        tasks_started = 0
        while task_stack:
            # Hard cap: never exceed _MAX_TOTAL_TASKS research tasks.
            # Prevents exponential explosion (branching_factor^depth tasks).
            if tasks_started >= _MAX_TOTAL_TASKS:
                await self._log(
                    f"Task cap reached ({_MAX_TOTAL_TASKS}). Proceeding to synthesis.",
                    kind="status",
                    visibility="user",
                )
                break

            current = task_stack.pop()

            # Skip if we've already processed this objective (prevent infinite loops)
            objective_key = normalize_objective(current.objective)
            if objective_key in processed_objectives:
                await self._log(
                    f"Skipping duplicate task: {current.objective[:50]}...",
                    kind="status",
                    visibility="debug",
                )
                continue
            processed_objectives.add(objective_key)

            await self._log(
                f"Processing task: {current.objective[:60]}... (depth={current.depth}, status={current.status})",
                kind="status",
                visibility="debug",
            )

            # Step 3a: Decompose if plan is empty and not too deep
            if not current.working_plan and current.depth < _MAX_TASK_DEPTH:
                await self._log(f"Decomposing task at depth {current.depth}", kind="thought")
                memory_summary = synthesis or self._summarize_findings(all_findings)
                decomposition = await self._phase2_decompose_with_plan(
                    current.objective, memory_summary, source_scope, current.depth
                )
                current.working_plan = decomposition.get("working_plan")
                current.knowledge_gaps = decomposition.get("knowledge_gaps")
                current.status = "in_progress"

                # Push subtasks if decomposition produced children
                if decomposition.get("sub_questions"):
                    for i, sq in enumerate(decomposition["sub_questions"][:_MAX_SUB_QUESTIONS]):
                        child = Subtask(
                            objective=sq if isinstance(sq, str) else sq.get("question", str(sq)),
                            parent_id=current.objective[:20],
                            depth=current.depth + 1,
                        )
                        task_stack.append(child)
                    await self._log(
                        f"Decomposed into {len(decomposition['sub_questions'])} subtasks",
                        kind="thought",
                    )
                    # Mark parent as in_progress but don't complete it yet - will be done when all children complete
                    continue  # Process children first
            elif not current.working_plan and current.depth >= _MAX_TASK_DEPTH:
                # At max depth, force a simple working plan to avoid decomposition loop
                current.working_plan = f"Research and summarize: {current.objective}"
                current.knowledge_gaps = "None - final synthesis step"
                current.status = "in_progress"

            # Step 3b: Research current task
            tasks_started += 1
            current.status = "in_progress"
            await self._log(f"Researching: {current.objective[:50]}...", kind="status")

            findings, sources, citations, web_findings, web_sources, web_citations = (
                await self._research_with_deep_search(current.objective, source_scope)
            )

            current.findings = findings
            all_findings.extend(findings)
            all_sources.extend(sources)
            all_citations.extend(citations)
            all_web_findings.extend(web_findings)
            all_web_sources.extend(web_sources)
            all_web_citations.extend(web_citations)

            # Step 3c: Check if research was sufficient
            if len(findings) + len(web_findings) < 2:
                # Insufficient results — reflect on failure
                if current.reflection_count >= _MAX_REFLECTIONS_PER_TASK:
                    current.status = "failed"
                    reflection_failures.append(f"Max reflections reached for: {current.objective[:50]}")
                    await self._log(f"Task failed (max reflections): {current.objective[:50]}", kind="status")
                else:
                    current.reflection_count += 1
                    current.status = "reflected"

                    reflection = await self._reflect_on_failure(
                        current.objective,
                        current.working_plan or "",
                        current.knowledge_gaps or "",
                        f"Insufficient evidence: {len(findings)} memory + {len(web_findings)} web findings",
                    )

                    if reflection.get("recommendation") == "decompose" and current.depth < _MAX_TASK_DEPTH:
                        # Decompose into subtasks
                        for sq in reflection.get("decomposition_questions", [])[:_MAX_SUB_QUESTIONS]:
                            child = Subtask(
                                objective=sq,
                                parent_id=current.objective[:20],
                                depth=current.depth + 1,
                            )
                            task_stack.append(child)
                        await self._log(f"Reflected → decomposed into {len(reflection.get('decomposition_questions', []))} subtasks", kind="thought")
                        continue
                    elif reflection.get("recommendation") == "rephrase":
                        current.objective = reflection.get("rephrased_plan", current.objective)
                        task_stack.append(current)  # Retry with rephrased objective
                        await self._log("Reflected → rephrased objective, retrying", kind="thought")
                        continue
                    else:
                        current.status = "failed"
                        await self._log(f"Task failed after reflection: {reflection.get('root_cause', 'unknown')}", kind="status")
            else:
                # Sufficient results — mark complete
                current.status = "completed"
                completed_tasks.append(current)

                # Update intermediate report
                report_section = await self._update_intermediate_report(
                    current.objective,
                    current.working_plan or "",
                    findings + web_findings,
                )
                intermediate_report.append(report_section)

                await self._log(
                    f"Task completed: {len(findings)} memory + {len(web_findings)} web findings",
                    kind="status",
                )

        # Phase 4: Synthesize final report
        await self._log(
            f"Research loop complete: {len(completed_tasks)} tasks completed, {len(reflection_failures)} failed",
            kind="status",
        )

        # Deduplicate findings
        all_memory = self._deduplicate_findings(all_findings)
        all_web = self._deduplicate_findings(all_web_findings)
        all_sources = self._deduplicate_sources(all_sources)

        # Compute confidence
        if all_memory:
            avg_confidence = sum(f.confidence for f in all_memory) / len(all_memory)
        elif all_web:
            avg_confidence = sum(f.confidence for f in all_web) / len(all_web) * 0.8
        else:
            avg_confidence = 0.2

        # Final synthesis
        summary = await self._phase4_synthesize(
            user_query, all_memory, all_web, synthesis,
        )

        pack = EvidencePack(
            summary=summary,
            sources=all_sources,
            memory_findings=all_memory,
            web_findings=all_web,
            doc_findings=[],
            open_questions=[t.objective for t in completed_tasks if len(t.findings) < 2],
            confidence=round(min(avg_confidence, 1.0), 2),
            citations=all_citations + all_web_citations,
            contradictions=[],
            freshness=EvidenceFreshness(
                memory_is_fresh=bool(all_memory),
                web_verified=bool(all_web),
                freshness_summary=f"Deep research: {len(all_memory)} memory + {len(all_web)} web findings from {len(completed_tasks)} tasks",
                checked_at=_now_iso(),
            ),
            provenance=EvidenceProvenance(
                memory_sources=len(all_sources),
                web_sources=len(all_web),
                upload_sources=0,
                graph_traversals=1 if phase1_findings else 0,
                primary_ground_truth="memory" if all_memory else "web",
                save_back_eligible=False,
            ),
            recommended_followups=reflection_failures,
        )

        # Enrich pack with structured insights, hooks, and content brief
        pack = await self._enrich_evidence_pack(pack, user_query)

        # Store findings in HiveMind for future recalls
        await self._store_findings_in_hivemind(user_query, pack)

        await self._log("Deep research complete", kind="status", detail={"confidence": pack.confidence})
        return pack

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
                save_back_eligible=False,  # disabled — never save back to HIVE-MIND
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
            "LANGUAGE: Write the ENTIRE response in German (Deutsch). All headings, "
            "body text, and bullet points must be in German. Preserve proper nouns, "
            "product names (e.g. SolvisMax), and technical identifiers in their original form. "
            "Use formal register (\"Sie\" form).\n\n"
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

    async def _quick_recall_gather(
        self, user_query: str, source_scope: str,
    ) -> EvidencePack:
        """Quick HIVE-MIND recall only - no deep research tree.

        Use this for standard queries where full research decomposition
        is not needed. Runs ONLY direct recall (Pass 1) — skips AI synthesis
        and graph traversal for speed (~4s instead of ~14s).
        """
        await self._log(f"Quick recall started: {user_query[:80]}...", kind="status")

        # Fast recall: Pass 1 only (no AI synthesis, no graph traversal)
        findings, sources, citations, synthesis = await self._phase1_recall_only(user_query)

        await self._log(
            f"Quick recall complete: {len(findings)} memory findings",
            kind="status",
        )

        # Deduplicate findings
        all_memory = self._deduplicate_findings(findings)
        all_sources = self._deduplicate_sources(sources)

        # Compute confidence
        if all_memory:
            avg_confidence = sum(f.confidence for f in all_memory) / len(all_memory)
        else:
            avg_confidence = 0.3

        # Build EvidencePack with just recall results
        pack = EvidencePack(
            summary=synthesis or f"Quick recall found {len(all_memory)} relevant memories",
            sources=all_sources,
            memory_findings=all_memory,
            web_findings=[],
            doc_findings=[],
            open_questions=[],
            confidence=round(min(avg_confidence, 1.0), 2),
            citations=citations,
            contradictions=[],
            structured_insights=[],
            content_hooks=[],
            risk_flags=[],
        )

        # Store findings in HiveMind
        await self._store_findings_in_hivemind(user_query, pack)

        return pack

    async def _phase1_recall_only(
        self, query: str
    ) -> tuple[list[EvidenceFinding], list[SourceRecord], list[Citation], str | None]:
        """Single-pass recall: direct HIVE-MIND recall only.

        Skips AI synthesis (Pass 2) and graph traversal (Pass 3) for speed.
        Used by _quick_recall_gather for direct_answer workflows where latency
        matters more than exhaustive evidence coverage.
        """
        findings: list[EvidenceFinding] = []
        sources: list[SourceRecord] = []
        citations: list[Citation] = []

        if not self.hivemind.enabled:
            return findings, sources, citations, None

        recall_mode, recall_limit = self._recall_profile_for_query(query)
        await self._log(
            f"Phase 1 recall profile selected: mode={recall_mode}, limit={recall_limit}.",
            kind="decision",
        )

        try:
            await self._log(
                "Calling hivemind_recall",
                kind="tool_call",
                detail={"tool_id": "hivemind_recall", "mode": recall_mode, "limit": recall_limit},
            )
            recall_result = await self.hivemind.recall(
                query=query, limit=recall_limit, mode=recall_mode,
            )
            payload = self.hivemind._extract_tool_payload(recall_result) if isinstance(recall_result, dict) else recall_result
            await self._log(
                "hivemind_recall completed",
                kind="tool_result",
                detail={"tool_id": "hivemind_recall", "memory_count": len(_normalize_memories(payload))},
            )
            logger.info("Phase 1 recall payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
            memories = _normalize_memories(payload)
            logger.info("Phase 1 normalized memories: %d", len(memories))
            for mem in memories:
                f, s, c = self._memory_to_finding(mem)
                if f is not None:
                    findings.append(f)
                    sources.append(s)
                    citations.append(c)

            injection = _normalize_injection_text(payload)
            if injection:
                first_chars = injection.lstrip()[:20]
                is_structured = first_chars.startswith(("{", "[", "<user-profile", "<", '"'))
                if not is_structured:
                    injection_findings = _injection_to_findings(injection)[:15]
                    logger.info("Phase 1 injection findings: %d (prose content)", len(injection_findings))
                    findings.extend(injection_findings)
                else:
                    logger.info("Phase 1 injection text skipped: structured metadata, not prose")
        except HivemindMCPError as exc:
            logger.warning("Phase 1 recall failed: %s", exc)
            await self._log(f"Memory recall error (continuing): {exc}", kind="status", visibility="debug")

        # Build a simple summary from findings instead of calling AI synthesis
        synthesis = None
        if findings:
            top_titles = [f.title for f in findings[:5] if f.title]
            synthesis = f"Found {len(findings)} relevant memories: {', '.join(top_titles)}"

        return findings, sources, citations, synthesis

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
            await self._log(
                "Calling hivemind_recall",
                kind="tool_call",
                detail={"tool_id": "hivemind_recall", "mode": recall_mode, "limit": recall_limit},
            )
            recall_result = await self.hivemind.recall(
                query=query, limit=recall_limit, mode=recall_mode,
            )
            payload = self.hivemind._extract_tool_payload(recall_result) if isinstance(recall_result, dict) else recall_result
            await self._log(
                "hivemind_recall completed",
                kind="tool_result",
                detail={"tool_id": "hivemind_recall", "memory_count": len(_normalize_memories(payload))},
            )
            logger.info("Phase 1 recall payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
            memories = _normalize_memories(payload)
            logger.info("Phase 1 normalized memories: %d", len(memories))
            for mem in memories:
                f, s, c = self._memory_to_finding(mem)
                if f is not None:
                    findings.append(f)
                    sources.append(s)
                    citations.append(c)

            # Injection text: only useful if it's prose/bullet content (quick mode).
            # Insight mode returns JSON dumps or XML user-profile — parsing those creates
            # garbage findings from raw metadata fields. Structured memories already have
            # the real content via _memory_to_finding().
            injection = _normalize_injection_text(payload)
            if injection:
                first_chars = injection.lstrip()[:20]
                is_structured = first_chars.startswith(("{", "[", "<user-profile", "<", '"'))
                if not is_structured:
                    injection_findings = _injection_to_findings(injection)[:15]
                    logger.info("Phase 1 injection findings: %d (prose content)", len(injection_findings))
                    findings.extend(injection_findings)
                else:
                    logger.info("Phase 1 injection text skipped: structured metadata, not prose")
        except HivemindMCPError as exc:
            logger.warning("Phase 1 recall failed: %s", exc)
            await self._log(f"Memory recall error (continuing): {exc}", kind="status", visibility="debug")

        # Pass 2: AI synthesis
        try:
            await self._log(
                "Calling hivemind_query_with_ai",
                kind="tool_call",
                detail={"tool_id": "hivemind_query_with_ai", "context_limit": 8},
            )
            ai_result = await self.hivemind.query_with_ai(question=query, context_limit=8)
            ai_payload = self.hivemind._extract_tool_payload(ai_result) if isinstance(ai_result, dict) else ai_result
            await self._log(
                "hivemind_query_with_ai completed",
                kind="tool_result",
                detail={"tool_id": "hivemind_query_with_ai", "has_answer": bool((ai_payload or {}).get("answer"))},
            )
            answer = ai_payload.get("answer") or ai_payload.get("text") or ""
            if isinstance(answer, str) and answer.strip():
                synthesis = answer.strip()
        except HivemindMCPError as exc:
            logger.warning("Phase 1 AI synthesis failed: %s", exc)

        # Pass 3: Graph traversal on top-scoring memories
        top_memory_ids = [f.source_ids[0] for f in findings if f.source_ids][:3]
        for memory_id in top_memory_ids:
            try:
                await self._log(
                    "Calling hivemind_traverse_graph",
                    kind="tool_call",
                    detail={"tool_id": "hivemind_traverse_graph", "memory_id": memory_id, "depth": _GRAPH_TRAVERSAL_DEPTH},
                )
                graph_result = await self.hivemind.traverse_graph(
                    memory_id=memory_id, depth=_GRAPH_TRAVERSAL_DEPTH,
                )
                graph_payload = (
                    self.hivemind._extract_tool_payload(graph_result)
                    if isinstance(graph_result, dict) else graph_result
                )
                await self._log(
                    "hivemind_traverse_graph completed",
                    kind="tool_result",
                    detail={"tool_id": "hivemind_traverse_graph", "memory_id": memory_id, "memory_count": len(_normalize_memories(graph_payload))},
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
            {"role": "system", "content": "You are a research planner. Your response MUST start with { and end with }. Never use ```json or any markdown. Never add text before or after the JSON braces. Raw JSON only."},
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
        return self._fallback_decompose(query, depth=0)

    @staticmethod
    def _fallback_decompose(query: str, depth: int = 0) -> list[str]:
        """Generate basic sub-questions when LLM decomposition fails.

        Varies questions based on depth to avoid infinite loops.
        At max depth (4+), returns a single synthesis question that will complete.
        """
        # Depth-based question templates to avoid repetition
        depth_templates = [
            # Depth 0 - High-level overview
            [
                f"What is the historical background and context of: {query}",
                f"What are the main components and aspects of: {query}",
            ],
            # Depth 1 - Facts and details
            [
                f"What key facts and data points exist about: {query}",
                f"What are the important characteristics of: {query}",
            ],
            # Depth 2 - Analysis and relationships
            [
                f"What relationships and connections exist for: {query}",
                f"What factors influence or affect: {query}",
            ],
            # Depth 3 - Implications and outcomes
            [
                f"What are the implications and consequences of: {query}",
                f"What outcomes or results are associated with: {query}",
            ],
            # Depth 4+ - Final synthesis (terminate recursion - single item = no further decomposition)
            [f"Final synthesis: {query}"],
        ]

        # Use template for current depth, or last one if deeper
        template_idx = min(depth, len(depth_templates) - 1)
        return depth_templates[template_idx]

    # ------------------------------------------------------------------
    # Stack-based Research Helpers (Official AgentScope Pattern)
    # ------------------------------------------------------------------

    async def _phase2_decompose_with_plan(
        self, query: str, memory_summary: str, source_scope: str, depth: int = 0,
    ) -> dict[str, Any]:
        """Decompose query with working plan and knowledge gaps (stack-based).

        Returns dict with:
        - sub_questions: list of sub-task objectives
        - working_plan: specific steps to complete
        - knowledge_gaps: what information is missing
        """
        prompt_template = _load_prompt("decompose_subtask.md")
        prompt = prompt_template.replace("{query}", query)
        prompt = prompt.replace("{memory_summary}", memory_summary or "No memory findings yet.")
        prompt = prompt.replace("{source_scope}", source_scope)

        messages = [
            {"role": "system", "content": "You are a research planner. Your response MUST start with { and end with }. Never use ```json or any markdown. Never add text before or after the JSON braces. Raw JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=2000, temperature=0.5,
            )
            text = self.resolver.extract_text(response)

            logger.debug("Decomposition LLM response (raw): %s", text[:300] if text else "(EMPTY)")

            # Primary parse — handles complete JSON
            try:
                parsed = self.resolver.safe_json_loads(text)
            except Exception:
                # Secondary: extract partial sub_questions from truncated JSON.
                # Captures question strings even when the closing braces are missing.
                parsed = _extract_partial_decomposition(text)

            sub_questions = parsed.get("sub_questions", [])
            if isinstance(sub_questions, list) and len(sub_questions) >= 1:
                working_plan = "\n".join([
                    f"{i+1}. Research: {sq.get('question', str(sq)) if isinstance(sq, dict) else sq}"
                    for i, sq in enumerate(sub_questions[:_MAX_SUB_QUESTIONS])
                ])
                return {
                    "sub_questions": sub_questions[:_MAX_SUB_QUESTIONS],
                    "working_plan": working_plan,
                    "knowledge_gaps": parsed.get("knowledge_gaps_summary", ""),
                }
        except Exception as exc:
            logger.debug("Decomposition with plan failed: %s", exc)

        # Fallback - vary questions by depth to avoid infinite loops
        fallback_questions = self._fallback_decompose(query, depth)
        return {
            "sub_questions": fallback_questions,
            "working_plan": "\n".join([f"{i+1}. {q}" for i, q in enumerate(fallback_questions)]),
            "knowledge_gaps": "Insufficient context to identify specific gaps",
        }

    async def _research_with_deep_search(
        self, objective: str, source_scope: str,
    ) -> tuple[
        list[EvidenceFinding], list[SourceRecord], list[Citation],
        list[EvidenceFinding], list[SourceRecord], list[Citation],
    ]:
        """Research with deep search: memory-first, then web with follow-up extraction.

        Implements recursive information filling:
        1. HIVE-MIND memory recall
        2. If insufficient: web search
        3. Analyze if results are sufficient
        4. If gaps remain: extract from specific URLs or search again
        """
        mem_findings: list[EvidenceFinding] = []
        mem_sources: list[SourceRecord] = []
        mem_citations: list[Citation] = []
        web_findings: list[EvidenceFinding] = []
        web_sources: list[SourceRecord] = []
        web_citations: list[Citation] = []

        # Step 1: Memory recall
        if self.hivemind.enabled:
            try:
                mode, limit = self._recall_profile_for_query(objective)
                recall_result = await self.hivemind.recall(
                    query=objective, limit=limit, mode=mode,
                )
                payload = (
                    self.hivemind._extract_tool_payload(recall_result)
                    if isinstance(recall_result, dict) else recall_result
                )
                memories = _normalize_memories(payload)
                for mem in memories:
                    f, s, c = self._memory_to_finding(mem, source_prefix="memory")
                    if f is not None:
                        mem_findings.append(f)
                        mem_sources.append(s)
                        mem_citations.append(c)
            except HivemindMCPError as exc:
                logger.warning("Memory recall failed for '%s': %s", objective[:40], exc)

        # Check if memory is sufficient
        if len(mem_findings) >= 3:
            return mem_findings, mem_sources, mem_citations, web_findings, web_sources, web_citations

        # Step 2: Web search if memory insufficient
        if source_scope in ("web", "all") and self.hivemind.enabled:
            try:
                web_result = await self.hivemind.web_search(
                    query=objective, limit=_WEB_RESULTS_LIMIT * 2,
                )
                web_payload = (
                    self.hivemind._extract_tool_payload(web_result)
                    if isinstance(web_result, dict) else web_result
                )
                results = _normalize_web_results(web_payload)

                # Step 3: Deep search follow-up analysis
                followup_decision = await self._analyze_deep_search_followup(
                    objective, objective, str(results)[:2000], ""
                )

                if followup_decision.get("is_sufficient", False):
                    # Results are sufficient — extract findings
                    for item in results:
                        f, s, c = self._web_result_to_finding(item)
                        if f is not None:
                            web_findings.append(f)
                            web_sources.append(s)
                            web_citations.append(c)
                else:
                    # Results insufficient — extract from specific URLs or search again
                    urls = followup_decision.get("url", [])
                    if urls and isinstance(urls, list):
                        # Extract from specific URLs
                        for url in urls[:3]:
                            try:
                                crawl_result = await self.hivemind.web_crawl(url=url)
                                crawl_payload = (
                                    self.hivemind._extract_tool_payload(crawl_result)
                                    if isinstance(crawl_result, dict) else crawl_result
                                )
                                content = crawl_payload.get("content", "") or crawl_payload.get("text", "")
                                if content:
                                    f = EvidenceFinding(
                                        finding_id=f"webcrawl:{hashlib.md5(url.encode()).hexdigest()[:12]}",
                                        title=f"Extracted from {url[:50]}",
                                        summary=content[:500],
                                        source_ids=[f"webcrawl:{url}"],
                                        confidence=0.7,
                                    )
                                    web_findings.append(f)
                                    web_sources.append(SourceRecord(
                                        source_id=f"webcrawl:{url}",
                                        source_type="web_crawl",
                                        url=url,
                                    ))
                            except Exception as e:
                                logger.warning("URL extraction failed for %s: %s", url, e)
                    else:
                        # Try alternative search
                        new_query = followup_decision.get("subtask", objective)
                        retry_result = await self.hivemind.web_search(
                            query=new_query, limit=_WEB_RESULTS_LIMIT,
                        )
                        retry_payload = (
                            self.hivemind._extract_tool_payload(retry_result)
                            if isinstance(retry_result, dict) else retry_result
                        )
                        retry_results = _normalize_web_results(retry_payload)
                        for item in retry_results:
                            f, s, c = self._web_result_to_finding(item)
                            if f is not None:
                                web_findings.append(f)
                                web_sources.append(s)
                                web_citations.append(c)

            except HivemindMCPError as exc:
                logger.warning("Web search failed for '%s': %s", objective[:40], exc)

        return mem_findings, mem_sources, mem_citations, web_findings, web_sources, web_citations

    async def _analyze_deep_search_followup(
        self, objective: str, search_query: str, search_results: str, knowledge_gaps: str,
    ) -> dict[str, Any]:
        """Analyze whether search results need follow-up extraction."""
        prompt_template = _load_prompt("deep_search_followup.md")
        prompt = (
            prompt_template
            .replace("{objective}", objective)
            .replace("{search_query}", search_query)
            .replace("{search_results}", search_results[:3000])
            .replace("{knowledge_gaps}", knowledge_gaps or "None specified")
            .replace("{working_plan}", "Research the objective")
        )

        messages = [
            {"role": "system", "content": "You are a deep search analyst. Your response MUST start with { and end with }. Never use ```json or any markdown. Never add text before or after the JSON braces. Raw JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=800, temperature=0.3,
            )
            text = self.resolver.extract_text(response)
            return self.resolver.safe_json_loads(text)
        except Exception as exc:
            logger.warning("Deep search followup analysis failed: %s", exc)

        # Default: assume sufficient
        return {"is_sufficient": True, "reasoning": "Unable to analyze, assuming sufficient"}

    async def _reflect_on_failure(
        self, objective: str, working_plan: str, knowledge_gaps: str, failure_description: str,
    ) -> dict[str, Any]:
        """Reflect on research failure and recommend corrective action."""
        prompt_template = _load_prompt("research_reflection.md")
        prompt = (
            prompt_template
            .replace("{objective}", objective)
            .replace("{working_plan}", working_plan or "No plan specified")
            .replace("{knowledge_gaps}", knowledge_gaps or "None specified")
            .replace("{failure_description}", failure_description)
            .replace("{steps_attempted}", "Memory recall and web search attempted")
        )

        messages = [
            {"role": "system", "content": "You are a research quality controller. Your response MUST start with { and end with }. Never use ```json or any markdown. Never add text before or after the JSON braces. Raw JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=1000, temperature=0.2,
            )
            text = self.resolver.extract_text(response)
            return self.resolver.safe_json_loads(text)
        except Exception as exc:
            logger.warning("Reflection failed: %s", exc)

        # Fallback: recommend decomposition
        return {
            "failure_type": "insufficient_results",
            "root_cause": "Search returned insufficient evidence",
            "recommendation": "decompose",
            "decomposition_questions": [
                f"What specific data exists about: {objective[:50]}",
                f"What are the key components or aspects of: {objective[:50]}",
            ],
            "reasoning": "Fallback: decompose into narrower subtasks",
        }

    async def _update_intermediate_report(
        self, objective: str, working_plan: str, findings: list[EvidenceFinding],
    ) -> str:
        """Update intermediate report with findings from completed task."""
        prompt_template = _load_prompt("intermediate_report.md")

        findings_text = "\n".join([
            f"- [{f.finding_id}] {f.title}: {f.summary[:200]}"
            for f in findings[:10]
        ])

        prompt = (
            prompt_template
            .replace("{objective}", objective)
            .replace("{working_plan}", working_plan or "Research completed")
            .replace("{tool_results}", findings_text or "No findings recorded")
        )

        messages = [
            {"role": "system", "content": "You are a research synthesizer. Return markdown report."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=2000, temperature=0.3,
            )
            return self.resolver.extract_text(response)
        except Exception as exc:
            logger.warning("Intermediate report update failed: %s", exc)

        # Fallback: simple summary
        return f"\n## Completed: {objective}\n\n{len(findings)} findings gathered.\n"

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

    async def _store_findings_in_hivemind(self, query: str, pack: EvidencePack) -> None:
        """Store research findings in HiveMind for future recalls."""
        try:
            client = get_hivemind_client()
            findings_dict = {
                "memory_count": len(pack.memory_findings),
                "web_count": len(pack.web_findings),
                "doc_count": len(pack.doc_findings),
                "confidence": pack.confidence,
                "summary": pack.summary,
                "findings": [
                    {
                        "type": "memory",
                        "title": f.title,
                        "summary": f.summary,
                        "confidence": f.confidence,
                    }
                    for f in pack.memory_findings[:5]
                ] + [
                    {
                        "type": "web",
                        "title": f.title,
                        "summary": f.summary,
                        "confidence": f.confidence,
                    }
                    for f in pack.web_findings[:5]
                ],
            }
            result = await client.store_memory(query, findings_dict)
            if result.get("ok"):
                await self._log("Findings stored in HiveMind", kind="status")
            else:
                logger.warning(f"Failed to store findings in HiveMind: {result.get('error')}")
        except Exception as exc:
            logger.warning(f"HiveMind storage error: {exc}")

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

    # ------------------------------------------------------------------
    # Evidence Enrichment — Downstream Agent Optimization
    # ------------------------------------------------------------------

    async def _enrich_evidence_pack(
        self,
        pack: EvidencePack,
        user_query: str,
    ) -> EvidencePack:
        """Enrich EvidencePack with structured insights, hooks, and content brief.

        Called after research completes, before returning to workflow engine.
        Adds:
        - structured_insights: Content-ready insights with audience tagging
        - content_hooks: Narrative hooks for content creation
        - risk_flags: Compliance/legal flags for governance
        - content_brief: Structured handoff for ContentDirector
        - cache_entry: Cache metadata for reuse
        """
        all_findings = pack.memory_findings + pack.web_findings + pack.doc_findings

        # Extract structured insights
        pack.structured_insights = await self._extract_structured_insights(all_findings, user_query)

        # Extract content hooks
        pack.content_hooks = await self._extract_content_hooks(all_findings, user_query)

        # Identify risk flags
        pack.risk_flags = await self._identify_risk_flags(all_findings, user_query)

        # Generate content brief handoff
        pack.content_brief = await self._generate_content_brief(pack, user_query)

        # Create cache entry
        pack.cache_entry = await self._create_cache_entry(pack, user_query)

        return pack

    async def _extract_structured_insights(
        self,
        findings: list[EvidenceFinding],
        query: str,
    ) -> list[StructuredInsight]:
        """Extract structured, content-ready insights from findings.

        Uses LLM to identify key claims, evidence, metrics, and opportunities.
        Tags each insight with audience relevance and quotable flag.
        """
        if not findings:
            return []

        findings_text = "\n".join([
            f"[{f.finding_id}] {f.title}: {f.summary}"
            for f in findings[:20]  # Limit context
        ])

        prompt = f"""You are extracting structured insights from research findings for content creation.

=== FINDINGS ===
{findings_text}

=== QUERY ===
{query}

Extract 3-7 key insights that content creators can use directly. For each insight:
- insight: Clear 1-2 sentence statement
- insight_type: "key_claim" | "supporting_evidence" | "metric" | "comparison" | "risk" | "opportunity"
- audience_relevance: ["investor"] | ["customer"] | ["technical"] | ["executive"] | multiple
- confidence: 0-1 based on source quality
- source_refs: List of finding IDs that support this
- quotable: true if this is a strong, standalone statement
- narrative_hook: How this connects to a bigger story

Return JSON array of insights."""

        try:
            response = await self.resolver.acompletion(
                "research",
                [{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.2,
            )
            text = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(text)

            if isinstance(parsed, list):
                return [StructuredInsight(**item) for item in parsed if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("Insight extraction failed: %s", exc)

        # Fallback: create basic insights from top findings
        insights = []
        for f in findings[:5]:
            insights.append(StructuredInsight(
                insight=f.summary[:200],
                insight_type="supporting_evidence",
                audience_relevance=["general"],
                confidence=f.confidence,
                source_refs=[f.finding_id],
                quotable=len(f.summary) < 100,
            ))
        return insights

    async def _extract_content_hooks(
        self,
        findings: list[EvidenceFinding],
        query: str,
    ) -> list[ContentHook]:
        """Extract narrative hooks for content creation.

        Identifies problem/solution/proof/urgency angles from evidence.
        """
        if not findings:
            return []

        findings_text = "\n".join([f.summary[:300] for f in findings[:15]])

        prompt = f"""You are identifying content hooks — narrative angles that make compelling content.

=== FINDINGS ===
{findings_text}

=== QUERY ===
{query}

Identify 2-5 content hooks. For each:
- hook_type: "problem" | "solution" | "proof" | "urgency" | "contrast" | "social_proof"
- description: The hook statement (1-2 sentences)
- supporting_evidence: List of finding IDs
- emotional_weight: "low" | "medium" | "high"

Return JSON array of hooks."""

        try:
            response = await self.resolver.acompletion(
                "research",
                [{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.3,
            )
            text = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(text)

            if isinstance(parsed, list):
                return [ContentHook(**item) for item in parsed if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("Content hook extraction failed: %s", exc)

        return []

    async def _identify_risk_flags(
        self,
        findings: list[EvidenceFinding],
        query: str,
    ) -> list[RiskFlag]:
        """Identify compliance, legal, reputational, and accuracy risks.

        Flags claims that need qualification or governance review.
        """
        if not findings:
            return []

        # Check for contradictions first
        risk_flags = []

        # Look for potential accuracy risks (low confidence, conflicting sources)
        low_confidence = [f for f in findings if f.confidence < 0.4]
        if low_confidence:
            risk_flags.append(RiskFlag(
                risk_type="accuracy",
                description="Some findings have low confidence scores and may need verification",
                severity="medium",
                affected_claims=[f.finding_id for f in low_confidence],
                mitigation="Qualify claims with uncertainty language; seek primary sources",
            ))

        # Check for contradictions in the pack
        # (This could be enhanced with contradiction detection logic)

        # LLM-based risk detection
        findings_text = "\n".join([f.summary[:200] for f in findings[:20]])

        prompt = f"""You are identifying potential risks in research findings that content/governance teams should know about.

=== FINDINGS ===
{findings_text}

=== QUERY ===
{query}

Identify any risk flags. Consider:
- compliance: Regulatory or policy concerns
- legal: Potential liability or legal exposure
- reputational: Claims that could backfire if wrong
- accuracy: Unverified or hard-to-verify claims
- sensitivity: Topics requiring careful framing

Return JSON array with:
- risk_type: one of above
- description: What the risk is
- severity: "low" | "medium" | "high" | "critical"
- affected_claims: List of finding IDs
- mitigation: How to handle this risk

Return empty array if no significant risks identified."""

        try:
            response = await self.resolver.acompletion(
                "research",
                [{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.2,
            )
            text = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(text)

            if isinstance(parsed, list):
                llm_flags = [RiskFlag(**item) for item in parsed if isinstance(item, dict)]
                risk_flags.extend(llm_flags)
        except Exception as exc:
            logger.warning("Risk flag detection failed: %s", exc)

        return risk_flags

    async def _generate_content_brief(
        self,
        pack: EvidencePack,
        query: str,
    ) -> ContentBriefHandoff:
        """Generate a structured handoff brief for ContentDirector.

        Translates research findings into content creation guidance.
        """
        all_findings = pack.memory_findings + pack.web_findings + pack.doc_findings

        if not all_findings:
            return ContentBriefHandoff(
                key_message=f"Research on '{query}' yielded insufficient evidence",
                supporting_pillars=[],
            )

        findings_text = "\n".join([f.summary[:200] for f in all_findings[:15]])

        prompt = f"""You are creating a content handoff brief for a ContentDirector agent.

=== EVIDENCE SUMMARY ===
{pack.summary}

=== KEY FINDINGS ===
{findings_text}

=== QUERY ===
{query}

Create a ContentBriefHandoff with:
- key_message: One sentence — the core message content must convey
- supporting_pillars: 2-4 key supporting points (bullet format)
- audience_angles: Dict mapping audience -> how to frame for them
  - "investor": ROI/growth framing
  - "customer": benefit/solution framing
  - "technical": how it works framing
  - "executive": strategic impact framing
- recommended_structure: Suggested section order (e.g., ["problem", "solution", "proof", "cta"])
- tone_guidance: Tone recommendation based on evidence (professional, urgent, optimistic, etc.)
- must_include_claims: 2-4 specific claims that MUST appear in content
- avoid_claims: Claims to avoid or qualify (if any)
- visual_opportunities: Data points that would work well as visuals
  - Each: {{"value": "40%", "label": "Market Growth", "visual_type": "stat_callout"}}

Return JSON object."""

        try:
            response = await self.resolver.acompletion(
                "research",
                [{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.25,
            )
            text = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(text)

            if isinstance(parsed, dict):
                return ContentBriefHandoff(**parsed)
        except Exception as exc:
            logger.warning("Content brief generation failed: %s", exc)

        # Fallback: basic brief from summary
        return ContentBriefHandoff(
            key_message=pack.summary[:200],
            supporting_pillars=[f.summary[:100] for f in all_findings[:3]],
            tone_guidance="professional and evidence-based",
            must_include_claims=[f.summary[:80] for f in all_findings[:2]],
        )

    async def _create_cache_entry(
        self,
        pack: EvidencePack,
        query: str,
    ) -> ResearchCacheEntry:
        """Create a cache entry for this research result.

        Enables reuse of research for similar queries within freshness window.
        """
        from datetime import timedelta

        query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc)

        # Determine cache TTL based on query type
        # Time-sensitive queries get shorter TTL
        time_sensitive_keywords = ["quarter", "latest", "recent", "current", "2026", "2025"]
        is_time_sensitive = any(kw in query.lower() for kw in time_sensitive_keywords)
        ttl_hours = 6 if is_time_sensitive else 72  # 6 hours vs 3 days

        # Identify freshness tags — data elements that may go stale
        freshness_tags = []
        for f in pack.memory_findings[:5] + pack.web_findings[:5]:
            # Look for metrics, dates, numbers
            if any(c.isdigit() for c in f.summary):
                freshness_tags.append(f.finding_id)

        return ResearchCacheEntry(
            query_hash=query_hash,
            cached_at=now.isoformat(),
            expires_at=(now + timedelta(hours=ttl_hours)).isoformat(),
            query=query,
            evidence_pack_summary=pack.summary[:500],
            freshness_tags=freshness_tags,
        )
