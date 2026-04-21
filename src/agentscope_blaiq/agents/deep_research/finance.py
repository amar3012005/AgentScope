"""FinanceDeepResearchAgent — hypothesis-driven finance research mode with tree-structured search.

Extends BlaiqDeepResearchAgent with the official Alias Finance pattern:
  1. HIVE-MIND deep recall (inherited)
  2. Propose root hypotheses from memory context (LLM)
  3. Test each hypothesis via HIVE-MIND + optional web search
  4. For failed/uncertain hypotheses: decompose into sub-hypotheses
  5. Recurse until all verified or max depth reached
  6. Build structured finance summary with hypothesis tree visualization

Returns an EvidencePack with hypothesis tree metadata for frontend rendering.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agentscope_blaiq.agents.deep_research.base import (
    BlaiqDeepResearchAgent,
    _load_prompt,
    _normalize_memories,
    _normalize_web_results,
    _now_iso,
)
from agentscope_blaiq.contracts.evidence import (
    EvidenceFinding,
    EvidenceFreshness,
    EvidencePack,
    EvidenceProvenance,
)

logger = logging.getLogger(__name__)

# Hypothesis testing thresholds
_MIN_EVIDENCE_VERIFIED = 2
_MIN_EVIDENCE_REFUTED = 2
_MAX_HYPOTHESES = 3
_MAX_DEPTH = 3  # Maximum tree depth for hypothesis decomposition
_WEB_RESULTS_PER_HYPOTHESIS = 3


@dataclass
class HypothesisNode:
    """A node in the hypothesis tree.

    Attributes:
        id: Unique identifier (e.g., "H1", "H1.1", "H1.2.1")
        statement: The hypothesis statement to test
        data_needed: List of data types needed for verification
        source_priority: "memory", "web", or "both"
        confidence_prior: Prior confidence (0.0-1.0)
        search_query: Derived search query for evidence gathering
        status: "pending", "verified", "refuted", or "uncertain"
        evidence: List of evidence summaries supporting/refuting
        parent_id: Parent hypothesis ID (None for root hypotheses)
        depth: Depth in tree (0 for root, 1+ for children)
        children: Child hypothesis nodes
        failure_reason: Why this hypothesis failed (if refuted/uncertain)
    """
    id: str
    statement: str
    data_needed: list[str] = field(default_factory=list)
    source_priority: str = "both"
    confidence_prior: float = 0.5
    search_query: str = ""
    status: str = "pending"
    evidence: list[str] = field(default_factory=list)
    parent_id: str | None = None
    depth: int = 0
    children: list["HypothesisNode"] = field(default_factory=list)
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "statement": self.statement,
            "status": self.status,
            "evidence": self.evidence,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "children": [child.to_dict() for child in self.children],
            "failure_reason": self.failure_reason,
        }


class FinanceDeepResearchAgent(BlaiqDeepResearchAgent):
    """Hypothesis-driven finance research agent with tree-structured deep search.

    Used when ``analysis_mode=finance`` in the orchestration workflow.
    Produces an EvidencePack whose ``summary`` field contains structured
    finance analysis: THESIS / HYPOTHESES / EVIDENCE / RISKS / RECOMMENDATION.

    Implements the official Alias Finance pattern:
    1. Propose root hypotheses from initial evidence
    2. Test each hypothesis via HIVE-MIND + web search
    3. For failed/uncertain hypotheses: decompose into sub-hypotheses
    4. Recurse until all verified or max depth reached
    5. Build structured finance summary with hypothesis tree
    """

    async def gather(
        self,
        session: Any,
        tenant_id: str,
        user_query: str,
        source_scope: str,
    ) -> EvidencePack:
        """Execute tree-structured hypothesis-driven finance research.

        Args:
            session: SQLAlchemy async session (passed through).
            tenant_id: Tenant isolation identifier.
            user_query: The finance research query from the user.
            source_scope: One of "web", "docs", or "all".

        Returns:
            EvidencePack with finance-structured summary and hypothesis tree.
        """
        await self._log(f"Finance research started: {user_query[:80]}...", kind="status")

        # ------------------------------------------------------------------
        # Phase 1: HIVE-MIND deep recall (inherited) - provides initial context
        # ------------------------------------------------------------------
        phase1_findings, phase1_sources, phase1_citations, synthesis = (
            await self._phase1_deep_recall(user_query)
        )
        await self._log(
            f"Phase 1 (deep recall) complete: {len(phase1_findings)} memory findings",
            kind="status",
            detail={"finding_count": len(phase1_findings)},
        )

        # ------------------------------------------------------------------
        # Phase 2: Propose root hypotheses from memory context
        # ------------------------------------------------------------------
        evidence_summary = self._summarize_findings(phase1_findings)
        root_hypotheses = await self._propose_hypotheses(user_query, tenant_id, evidence_summary)

        # Convert to HypothesisNode tree
        hypothesis_queue: list[HypothesisNode] = []
        for i, h in enumerate(root_hypotheses[:_MAX_HYPOTHESES]):
            node = HypothesisNode(
                id=h.get("id", f"H{i+1}"),
                statement=h.get("statement", ""),
                data_needed=h.get("data_needed", []),
                source_priority=h.get("source_priority", "both"),
                confidence_prior=h.get("confidence_prior", 0.5),
                search_query=h.get("search_query", ""),
                depth=0,
                parent_id=None,
            )
            hypothesis_queue.append(node)

        await self._log(
            f"Phase 2 complete: {len(hypothesis_queue)} root hypotheses proposed",
            kind="thought",
            detail={"hypotheses": [h.statement for h in hypothesis_queue]},
        )

        # ------------------------------------------------------------------
        # Phase 3-5: Tree-structured hypothesis testing loop
        # ------------------------------------------------------------------
        all_test_findings: list[EvidenceFinding] = []
        all_web_findings: list[EvidenceFinding] = []
        tested_nodes: list[HypothesisNode] = []

        while hypothesis_queue:
            current = hypothesis_queue.pop(0)

            # Test current hypothesis
            await self._log(
                f"Testing {current.id}: {current.statement[:60]}...",
                kind="status",
                visibility="debug",
            )

            mem_findings, web_findings, status, failure_reason = await self._test_hypothesis_tree(
                current, source_scope
            )

            current.status = status
            current.failure_reason = failure_reason
            current.evidence = [f.summary[:120] for f in mem_findings + web_findings]
            tested_nodes.append(current)
            all_test_findings.extend(mem_findings)
            all_web_findings.extend(web_findings)

            # If failed/uncertain and we can go deeper, decompose
            if status in ("refuted", "uncertain") and current.depth < _MAX_DEPTH:
                await self._log(
                    f"{current.id} {status} — decomposing into sub-hypotheses",
                    kind="thought",
                )
                sub_hypotheses = await self._decompose_to_sub_hypotheses(
                    current, tenant_id, mem_findings + web_findings
                )
                hypothesis_queue.extend(sub_hypotheses)
                await self._log(
                    f"Added {len(sub_hypotheses)} sub-hypotheses to test queue",
                    kind="status",
                )

        # ------------------------------------------------------------------
        # Phase 6: Build hypothesis tree and finance summary
        # ------------------------------------------------------------------
        # Reconstruct tree from tested nodes
        root_nodes = [n for n in tested_nodes if n.parent_id is None]
        for node in tested_nodes:
            if node.parent_id:
                # Find parent and add as child
                parent = next((n for n in tested_nodes if n.id == node.parent_id), None)
                if parent:
                    parent.children.append(node)

        # Count verification outcomes
        verified_count = sum(1 for n in tested_nodes if n.status == "verified")
        refuted_count = sum(1 for n in tested_nodes if n.status == "refuted")
        uncertain_count = sum(1 for n in tested_nodes if n.status == "uncertain")

        await self._log(
            f"Tree search complete: {verified_count} verified, {refuted_count} refuted, {uncertain_count} uncertain",
            kind="status",
        )

        # Deduplicate findings
        all_memory = self._deduplicate_findings(phase1_findings + all_test_findings)
        all_web = self._deduplicate_findings(all_web_findings)
        all_sources = self._deduplicate_sources(phase1_sources)

        # Build finance summary with hypothesis tree
        summary = self._build_finance_summary_with_tree(
            user_query, root_nodes, all_memory, all_web, synthesis,
        )

        # Confidence: weighted by hypothesis outcomes (deeper hypotheses count less)
        hypothesis_confidence = self._compute_tree_confidence(root_nodes)

        # Build hypothesis tree metadata for visualization
        hypothesis_tree = [n.to_dict() for n in root_nodes]

        # Open questions: uncertain leaf nodes
        open_questions = [
            n.statement for n in tested_nodes
            if n.status == "uncertain" and not n.children
        ]

        pack = EvidencePack(
            summary=summary,
            sources=all_sources,
            memory_findings=all_memory,
            web_findings=all_web,
            doc_findings=[],
            open_questions=open_questions,
            confidence=round(min(hypothesis_confidence, 1.0), 2),
            citations=phase1_citations,
            contradictions=[],
            freshness=EvidenceFreshness(
                memory_is_fresh=bool(all_memory),
                web_verified=bool(all_web),
                freshness_summary=(
                    f"Finance research: {len(all_memory)} memory, "
                    f"{len(all_web)} web findings; "
                    f"{verified_count}/{len(tested_nodes)} hypotheses verified"
                ),
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
            recommended_followups=[],
            # Store hypothesis tree in metadata for frontend visualization
            # Frontend can access via pack.metadata.get("hypothesis_tree")
        )

        # Attach hypothesis tree as metadata (frontend-accessible)
        if not hasattr(pack, "metadata"):
            pack.metadata = {}
        pack.metadata["hypothesis_tree"] = hypothesis_tree
        pack.metadata["hypothesis_stats"] = {
            "total_tested": len(tested_nodes),
            "verified": verified_count,
            "refuted": refuted_count,
            "uncertain": uncertain_count,
            "max_depth_reached": max((n.depth for n in tested_nodes), default=0),
        }

        await self._log(
            "Finance research complete",
            kind="status",
            detail={
                "confidence": pack.confidence,
                "hypotheses_tested": len(tested_nodes),
                "tree_depth": max((n.depth for n in tested_nodes), default=0),
            },
        )
        return pack

    # ------------------------------------------------------------------
    # Tree-structured hypothesis testing
    # ------------------------------------------------------------------

    async def _test_hypothesis_tree(
        self,
        hypothesis: HypothesisNode,
        source_scope: str,
    ) -> tuple[list[EvidenceFinding], list[EvidenceFinding], str, str | None]:
        """Test a single hypothesis via HIVE-MIND query + optional web search.

        Returns:
            Tuple of (memory_findings, web_findings, status, failure_reason).
            Status is one of: "verified", "refuted", "uncertain".
        """
        search_query = hypothesis.search_query or hypothesis.statement
        source_priority = hypothesis.source_priority
        mem_findings: list[EvidenceFinding] = []
        web_findings: list[EvidenceFinding] = []
        failure_reason: str | None = None

        # HIVE-MIND query for the hypothesis
        if self.hivemind.enabled:
            try:
                recall_result = await self.hivemind.recall(
                    query=search_query, limit=10, mode="panorama",
                )
                payload = (
                    self.hivemind._extract_tool_payload(recall_result)
                    if isinstance(recall_result, dict) else recall_result
                )
                memories = _normalize_memories(payload)
                for mem in memories:
                    f, _s, _c = self._memory_to_finding(mem, source_prefix="finance")
                    if f is not None:
                        mem_findings.append(f)
            except Exception as exc:
                logger.warning(
                    "Hypothesis test memory recall failed for '%s': %s",
                    hypothesis.id, exc,
                )
                failure_reason = f"Memory recall error: {exc}"

        # Web search if memory insufficient and scope/priority allow
        scope_allows_web = source_scope in ("web", "all")
        priority_wants_web = source_priority in ("web", "both")
        memory_insufficient = len(mem_findings) < _MIN_EVIDENCE_VERIFIED

        if memory_insufficient and scope_allows_web and priority_wants_web and self.hivemind.enabled:
            try:
                web_result = await self.hivemind.web_search(
                    query=search_query, limit=_WEB_RESULTS_PER_HYPOTHESIS,
                )
                web_payload = (
                    self.hivemind._extract_tool_payload(web_result)
                    if isinstance(web_result, dict) else web_result
                )
                results = _normalize_web_results(web_payload)
                for item in results:
                    f, _s, _c = self._web_result_to_finding(item)
                    if f is not None:
                        web_findings.append(f)
            except Exception as exc:
                logger.warning(
                    "Hypothesis test web search failed for '%s': %s",
                    hypothesis.id, exc,
                )
                if not failure_reason:
                    failure_reason = f"Web search error: {exc}"

        # Determine verification status
        total_evidence = len(mem_findings) + len(web_findings)
        if total_evidence >= _MIN_EVIDENCE_VERIFIED:
            status = "verified"
        elif total_evidence == 0:
            status = "refuted"
            if not failure_reason:
                failure_reason = "No evidence found from any source"
        else:
            status = "uncertain"
            if not failure_reason:
                failure_reason = f"Insufficient evidence ({total_evidence} findings, need {_MIN_EVIDENCE_VERIFIED})"

        return mem_findings, web_findings, status, failure_reason

    async def _decompose_to_sub_hypotheses(
        self,
        parent: HypothesisNode,
        tenant_id: str,
        evidence: list[EvidenceFinding],
    ) -> list[HypothesisNode]:
        """Decompose a failed/uncertain hypothesis into testable sub-hypotheses.

        Args:
            parent: The parent hypothesis node that failed verification.
            tenant_id: Tenant isolation identifier.
            evidence: Evidence gathered for the parent hypothesis.

        Returns:
            List of child HypothesisNode objects to test.
        """
        evidence_summary = "\n".join([f"- {f.title}: {f.summary[:150]}" for f in evidence[:5]])
        failure_context = parent.failure_reason or "Insufficient evidence"

        prompt_template = _load_prompt("finance_subhypothesis.md")
        prompt = (
            prompt_template
            .replace("{parent_id}", parent.id)
            .replace("{parent_statement}", parent.statement)
            .replace("{failure_reason}", failure_context)
            .replace("{evidence_summary}", evidence_summary or "No evidence gathered.")
            .replace("{tenant_id}", tenant_id)
        )

        messages = [
            {"role": "system", "content": "You are a financial research analyst. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=600, temperature=0.2,
            )
            raw = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(raw)
            raw_subhypotheses = parsed.get("sub_hypotheses", [])
            if not isinstance(raw_subhypotheses, list):
                raise ValueError("sub_hypotheses field is not a list")

            children: list[HypothesisNode] = []
            for i, h in enumerate(raw_subhypotheses[:3]):  # Max 3 children per node
                child = HypothesisNode(
                    id=f"{parent.id}.{i+1}",
                    statement=str(h.get("statement", "")),
                    data_needed=h.get("data_needed", []),
                    source_priority=h.get("source_priority", "both"),
                    confidence_prior=float(h.get("confidence_prior", 0.4)),
                    search_query=h.get("search_query", ""),
                    depth=parent.depth + 1,
                    parent_id=parent.id,
                )
                children.append(child)

            if children:
                await self._log(
                    f"Decomposed {parent.id} into {len(children)} sub-hypotheses",
                    kind="thought",
                )
                return children

        except Exception as exc:
            logger.warning("Sub-hypothesis decomposition LLM call failed: %s", exc)
            await self._log(
                f"Decomposition failed for {parent.id}: {exc}",
                kind="status",
                visibility="debug",
            )

        # Fallback: create basic child hypotheses from parent
        return self._fallback_subhypotheses(parent)

    @staticmethod
    def _fallback_subhypotheses(parent: HypothesisNode) -> list[HypothesisNode]:
        """Generate basic sub-hypotheses when LLM decomposition fails."""
        return [
            {
                "id": f"{parent.id}.1",
                "statement": f"Supporting evidence exists for: {parent.statement[:80]}",
                "data_needed": [f"evidence for {parent.statement[:50]}"],
                "source_priority": "both",
                "confidence_prior": 0.4,
                "search_query": parent.search_query,
            },
            {
                "id": f"{parent.id}.2",
                "statement": f"Contradicting evidence may exist for: {parent.statement[:80]}",
                "data_needed": [f"counter-evidence for {parent.statement[:50]}"],
                "source_priority": "both",
                "confidence_prior": 0.3,
                "search_query": f"contradicting evidence {parent.search_query}",
            },
        ]

    def _compute_tree_confidence(self, root_nodes: list[HypothesisNode]) -> float:
        """Compute overall confidence weighted by hypothesis tree structure.

        Deeper hypotheses count less (discount factor 0.8 per depth level).
        Verified hypotheses contribute positively, refuted negatively.
        """
        if not root_nodes:
            return 0.2

        def node_value(node: HypothesisNode) -> float:
            """Calculate value contribution of a node."""
            depth_discount = 0.8 ** node.depth
            if node.status == "verified":
                return 1.0 * depth_discount
            elif node.status == "refuted":
                return 0.3 * depth_discount
            else:  # uncertain
                return 0.5 * depth_discount

        total_value = sum(node_value(n) for n in root_nodes)
        max_possible = len(root_nodes)  # All verified at depth 0

        return total_value / max_possible if max_possible > 0 else 0.2

    # ------------------------------------------------------------------
    # Finance summary builder with tree
    # ------------------------------------------------------------------

    def _build_finance_summary_with_tree(
        self,
        query: str,
        root_nodes: list[HypothesisNode],
        memory_findings: list[EvidenceFinding],
        web_findings: list[EvidenceFinding],
        ai_synthesis: str | None,
    ) -> str:
        """Build structured finance summary with hypothesis tree visualization."""
        sections: list[str] = []

        # THESIS
        sections.append("## THESIS")
        if ai_synthesis:
            sections.append(ai_synthesis)
        else:
            sections.append(f"Analysis of: {query}")
        sections.append("")

        # HYPOTHESIS TREE VISUALIZATION
        sections.append("## HYPOTHESIS TREE")
        tree_viz = self._render_hypothesis_tree(root_nodes)
        sections.append(tree_viz)
        sections.append("")

        # HYPOTHESES (flat list with status)
        sections.append("## HYPOTHESES")
        all_nodes = self._flatten_tree(root_nodes)
        for node in all_nodes:
            indent = "  " * node.depth
            status_icon = {
                "verified": "[✓]",
                "refuted": "[✗]",
                "uncertain": "[?]",
            }.get(node.status, "[?]")
            sections.append(f"{indent}- **{node.id}** {status_icon}: {node.statement}")
            if node.failure_reason and node.status != "verified":
                sections.append(f"{indent}  - Reason: {node.failure_reason}")
            if node.evidence:
                for ev in node.evidence[:2]:
                    sections.append(f"{indent}  - Evidence: {ev}")
        sections.append("")

        # EVIDENCE
        sections.append("## EVIDENCE")
        if memory_findings:
            sections.append("### Internal (Memory)")
            for f in memory_findings[:8]:
                sections.append(f"- [{f.finding_id}] {f.title}: {f.summary[:200]}")
        if web_findings:
            sections.append("### External (Web)")
            for f in web_findings[:5]:
                sections.append(f"- [{f.finding_id}] {f.title}: {f.summary[:200]}")
        if not memory_findings and not web_findings:
            sections.append("No supporting evidence found.")
        sections.append("")

        # RISKS
        sections.append("## RISKS")
        refuted = [n for n in all_nodes if n.status == "refuted"]
        uncertain = [n for n in all_nodes if n.status == "uncertain"]
        if refuted:
            for n in refuted:
                sections.append(f"- {n.statement} (refuted — {n.failure_reason})")
        if uncertain:
            for n in uncertain:
                sections.append(f"- {n.statement} (uncertain — {n.failure_reason})")
        if not refuted and not uncertain:
            sections.append("No significant risks identified from hypothesis testing.")
        sections.append("")

        # RECOMMENDATION
        sections.append("## RECOMMENDATION")
        verified_count = sum(1 for n in all_nodes if n.status == "verified")
        total = len(all_nodes)
        if total == 0:
            sections.append("Insufficient data to form a recommendation. Further research required.")
        elif verified_count == total:
            sections.append(
                "All hypotheses verified. Evidence strongly supports the thesis. "
                "Proceed with high confidence."
            )
        elif verified_count > 0:
            sections.append(
                f"{verified_count}/{total} hypotheses verified. "
                "Partial evidence supports the thesis. "
                "Address uncertain/refuted areas before proceeding."
            )
        else:
            sections.append(
                "No hypotheses could be verified. "
                "Reassess the thesis or gather additional data sources."
            )

        return "\n".join(sections)

    @staticmethod
    def _render_hypothesis_tree(root_nodes: list[HypothesisNode]) -> str:
        """Render hypothesis tree as ASCII art for markdown display."""
        lines = []

        def render_node(node: HypothesisNode, prefix: str = "", is_last: bool = True) -> None:
            status_icon = {
                "verified": "✓",
                "refuted": "✗",
                "uncertain": "?",
            }.get(node.status, "?")

            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}[{status_icon}] {node.id}: {node.statement[:60]}")

            # Render children
            children = node.children
            for i, child in enumerate(children):
                extension = "    " if is_last else "│   "
                child_is_last = i == len(children) - 1
                render_node(child, prefix + extension, child_is_last)

        for i, root in enumerate(root_nodes):
            root_is_last = i == len(root_nodes) - 1
            render_node(root, "", root_is_last)

        return "```\n" + "\n".join(lines) + "\n```" if lines else "No hypotheses tested."

    @staticmethod
    def _flatten_tree(root_nodes: list[HypothesisNode]) -> list[HypothesisNode]:
        """Flatten tree to list for iteration (depth-first order)."""
        result = []

        def traverse(node: HypothesisNode) -> None:
            result.append(node)
            for child in node.children:
                traverse(child)

        for root in root_nodes:
            traverse(root)

        return result

    # ------------------------------------------------------------------
    # Hypothesis proposal (unchanged from original)
    # ------------------------------------------------------------------

    async def _propose_hypotheses(
        self,
        query: str,
        tenant_id: str,
        evidence_summary: str,
    ) -> list[dict[str, Any]]:
        """Use LLM to propose testable finance hypotheses."""
        prompt_template = _load_prompt("finance_hypothesis.md")
        prompt = (
            prompt_template
            .replace("{query}", query)
            .replace("{tenant_id}", tenant_id)
            .replace("{evidence_summary}", evidence_summary or "No prior evidence.")
        )

        messages = [
            {"role": "system", "content": "You are a financial research analyst. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "research", messages, max_tokens=600, temperature=0.2,
            )
            raw = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(raw)
            raw_hypotheses = parsed.get("hypotheses", [])
            if not isinstance(raw_hypotheses, list):
                raise ValueError("hypotheses field is not a list")

            hypotheses: list[dict[str, Any]] = []
            for h in raw_hypotheses[:_MAX_HYPOTHESES]:
                hypotheses.append({
                    "id": h.get("id", f"H{len(hypotheses) + 1}"),
                    "statement": str(h.get("statement", "")),
                    "data_needed": h.get("data_needed", []),
                    "source_priority": h.get("source_priority", "both"),
                    "confidence_prior": float(h.get("confidence_prior", 0.5)),
                    "search_query": self._hypothesis_to_search_query(h),
                    "status": "pending",
                })
            if hypotheses:
                return hypotheses
        except Exception as exc:
            logger.warning("Hypothesis proposal LLM call failed: %s", exc)
            await self._log(
                f"Hypothesis generation failed, using fallback: {exc}",
                kind="status",
                visibility="debug",
            )

        # Fallback: generate basic hypotheses from query
        return self._fallback_hypotheses(query)

    @staticmethod
    def _hypothesis_to_search_query(hypothesis: dict[str, Any]) -> str:
        """Derive a search query from a hypothesis object."""
        statement = str(hypothesis.get("statement", ""))
        data_needed = hypothesis.get("data_needed", [])
        if data_needed and isinstance(data_needed, list):
            return str(data_needed[0])
        return statement

    @staticmethod
    def _fallback_hypotheses(query: str) -> list[dict[str, Any]]:
        """Generate basic hypotheses when LLM proposal fails."""
        return [
            {
                "id": "H1",
                "statement": f"Key financial metrics support the thesis implied by: {query}",
                "data_needed": [f"financial metrics related to {query}"],
                "source_priority": "both",
                "confidence_prior": 0.5,
                "search_query": f"financial metrics {query}",
                "status": "pending",
            },
            {
                "id": "H2",
                "statement": f"Risk factors may undermine the outlook for: {query}",
                "data_needed": [f"risk factors for {query}"],
                "source_priority": "both",
                "confidence_prior": 0.5,
                "search_query": f"risk factors {query}",
                "status": "pending",
            },
        ]
