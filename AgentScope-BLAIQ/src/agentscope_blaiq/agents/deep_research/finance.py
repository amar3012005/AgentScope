"""FinanceDeepResearchAgent — hypothesis-driven finance research mode.

Extends BlaiqDeepResearchAgent with a finance-specific gather() flow:
  1. HIVE-MIND deep recall (inherited)
  2. Propose hypotheses from memory context (LLM)
  3. Test each hypothesis via HIVE-MIND + optional web search
  4. Verify status: verified / refuted / uncertain
  5. Build structured finance summary (THESIS / HYPOTHESES / EVIDENCE / RISKS / RECOMMENDATION)

Returns the same EvidencePack contract as the base agent.
"""

from __future__ import annotations

import asyncio
import logging
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
_WEB_RESULTS_PER_HYPOTHESIS = 3


class FinanceDeepResearchAgent(BlaiqDeepResearchAgent):
    """Hypothesis-driven finance research agent.

    Used when ``analysis_mode=finance`` in the orchestration workflow.
    Produces an EvidencePack whose ``summary`` field contains structured
    finance analysis: THESIS / HYPOTHESES / EVIDENCE / RISKS / RECOMMENDATION.
    """

    async def gather(
        self,
        session: Any,
        tenant_id: str,
        user_query: str,
        source_scope: str,
    ) -> EvidencePack:
        """Execute hypothesis-driven finance research.

        Args:
            session: SQLAlchemy async session (passed through).
            tenant_id: Tenant isolation identifier.
            user_query: The finance research query from the user.
            source_scope: One of "web", "docs", or "all".

        Returns:
            EvidencePack with finance-structured summary.
        """
        await self._log(f"Finance research started: {user_query[:80]}...", kind="status")

        # ------------------------------------------------------------------
        # Phase 1: HIVE-MIND deep recall (inherited)
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
        # Phase 2: Propose hypotheses from memory context
        # ------------------------------------------------------------------
        evidence_summary = self._summarize_findings(phase1_findings)
        hypotheses = await self._propose_hypotheses(user_query, tenant_id, evidence_summary)
        await self._log(
            f"Phase 2 (hypotheses) complete: {len(hypotheses)} hypotheses proposed",
            kind="thought",
            detail={"hypotheses": [h["statement"] for h in hypotheses]},
        )

        # ------------------------------------------------------------------
        # Phase 3: Test each hypothesis
        # ------------------------------------------------------------------
        all_test_findings: list[EvidenceFinding] = []
        all_web_findings: list[EvidenceFinding] = []

        test_tasks = [
            self._test_hypothesis(h, source_scope) for h in hypotheses
        ]
        test_results = await asyncio.gather(*test_tasks, return_exceptions=True)

        for i, result in enumerate(test_results):
            if isinstance(result, Exception):
                logger.warning("Hypothesis test failed for H%d: %s", i + 1, result)
                hypotheses[i]["status"] = "uncertain"
                hypotheses[i]["evidence"] = []
                continue
            mem_findings, web_findings, status = result
            hypotheses[i]["status"] = status
            hypotheses[i]["evidence"] = [f.summary[:120] for f in mem_findings + web_findings]
            all_test_findings.extend(mem_findings)
            all_web_findings.extend(web_findings)

        await self._log(
            f"Phase 3 (testing) complete: {len(all_test_findings)} memory + {len(all_web_findings)} web findings",
            kind="status",
        )

        # ------------------------------------------------------------------
        # Phase 4: Verify hypothesis status (already done inline above)
        # ------------------------------------------------------------------
        verified_count = sum(1 for h in hypotheses if h.get("status") == "verified")
        refuted_count = sum(1 for h in hypotheses if h.get("status") == "refuted")
        await self._log(
            f"Phase 4 (verify): {verified_count} verified, {refuted_count} refuted, "
            f"{len(hypotheses) - verified_count - refuted_count} uncertain",
            kind="status",
        )

        # ------------------------------------------------------------------
        # Phase 5: Build finance summary
        # ------------------------------------------------------------------
        all_memory = self._deduplicate_findings(phase1_findings + all_test_findings)
        all_web = self._deduplicate_findings(all_web_findings)
        all_sources = self._deduplicate_sources(phase1_sources)

        summary = self._build_finance_summary(
            user_query, hypotheses, all_memory, all_web, synthesis,
        )

        # Confidence: weighted by hypothesis outcomes
        if hypotheses:
            hypothesis_confidence = (
                verified_count * 0.9 + refuted_count * 0.6
                + (len(hypotheses) - verified_count - refuted_count) * 0.3
            ) / len(hypotheses)
        elif all_memory:
            hypothesis_confidence = 0.5
        else:
            hypothesis_confidence = 0.2

        pack = EvidencePack(
            summary=summary,
            sources=all_sources,
            memory_findings=all_memory,
            web_findings=all_web,
            doc_findings=[],
            open_questions=[
                h["statement"] for h in hypotheses if h.get("status") == "uncertain"
            ],
            confidence=round(min(hypothesis_confidence, 1.0), 2),
            citations=phase1_citations,
            contradictions=[],
            freshness=EvidenceFreshness(
                memory_is_fresh=bool(all_memory),
                web_verified=bool(all_web),
                freshness_summary=(
                    f"Finance research: {len(all_memory)} memory, "
                    f"{len(all_web)} web findings; "
                    f"{verified_count}/{len(hypotheses)} hypotheses verified"
                ),
                checked_at=_now_iso(),
            ),
            provenance=EvidenceProvenance(
                memory_sources=len(all_sources),
                web_sources=len(all_web),
                upload_sources=0,
                graph_traversals=1 if phase1_findings else 0,
                primary_ground_truth="memory" if all_memory else "web",
                save_back_eligible=bool(all_memory),
            ),
            recommended_followups=[],
        )

        await self._log(
            "Finance research complete",
            kind="status",
            detail={"confidence": pack.confidence, "hypotheses_tested": len(hypotheses)},
        )
        return pack

    # ------------------------------------------------------------------
    # Hypothesis proposal
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

    # ------------------------------------------------------------------
    # Hypothesis testing
    # ------------------------------------------------------------------

    async def _test_hypothesis(
        self,
        hypothesis: dict[str, Any],
        source_scope: str,
    ) -> tuple[list[EvidenceFinding], list[EvidenceFinding], str]:
        """Test a single hypothesis via HIVE-MIND query + optional web search.

        Returns:
            Tuple of (memory_findings, web_findings, status).
            Status is one of: "verified", "refuted", "uncertain".
        """
        search_query = hypothesis.get("search_query", hypothesis.get("statement", ""))
        source_priority = hypothesis.get("source_priority", "both")
        mem_findings: list[EvidenceFinding] = []
        web_findings: list[EvidenceFinding] = []

        # HIVE-MIND query for the hypothesis
        if self.hivemind.enabled:
            try:
                recall_result = await self.hivemind.recall(
                    query=search_query, limit=10, mode="insight",
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
                    hypothesis.get("id", "?"), exc,
                )

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
                    hypothesis.get("id", "?"), exc,
                )

        # Determine verification status
        total_evidence = len(mem_findings) + len(web_findings)
        status = self._determine_hypothesis_status(total_evidence)
        return mem_findings, web_findings, status

    @staticmethod
    def _determine_hypothesis_status(evidence_count: int) -> str:
        """Classify hypothesis status based on evidence count.

        Returns:
            "verified" if >= _MIN_EVIDENCE_VERIFIED pieces of evidence,
            "refuted" if zero evidence found,
            "uncertain" otherwise.
        """
        if evidence_count >= _MIN_EVIDENCE_VERIFIED:
            return "verified"
        if evidence_count == 0:
            return "refuted"
        return "uncertain"

    # ------------------------------------------------------------------
    # Finance summary builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_finance_summary(
        query: str,
        hypotheses: list[dict[str, Any]],
        memory_findings: list[EvidenceFinding],
        web_findings: list[EvidenceFinding],
        ai_synthesis: str | None,
    ) -> str:
        """Build structured finance summary in THESIS/HYPOTHESES/EVIDENCE/RISKS/RECOMMENDATION format."""
        sections: list[str] = []

        # THESIS
        sections.append("## THESIS")
        if ai_synthesis:
            sections.append(ai_synthesis)
        else:
            sections.append(f"Analysis of: {query}")
        sections.append("")

        # HYPOTHESES
        sections.append("## HYPOTHESES")
        for h in hypotheses:
            status_icon = {
                "verified": "[VERIFIED]",
                "refuted": "[REFUTED]",
                "uncertain": "[UNCERTAIN]",
            }.get(h.get("status", "uncertain"), "[UNCERTAIN]")
            sections.append(f"- **{h.get('id', '?')}** {status_icon}: {h.get('statement', 'N/A')}")
            evidence_items = h.get("evidence", [])
            if evidence_items:
                for ev in evidence_items[:3]:
                    sections.append(f"  - Evidence: {ev}")
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
        refuted = [h for h in hypotheses if h.get("status") == "refuted"]
        uncertain = [h for h in hypotheses if h.get("status") == "uncertain"]
        if refuted:
            for h in refuted:
                sections.append(f"- {h.get('statement', 'N/A')} (refuted — insufficient evidence)")
        if uncertain:
            for h in uncertain:
                sections.append(f"- {h.get('statement', 'N/A')} (uncertain — needs further investigation)")
        if not refuted and not uncertain:
            sections.append("No significant risks identified from hypothesis testing.")
        sections.append("")

        # RECOMMENDATION
        sections.append("## RECOMMENDATION")
        verified_count = sum(1 for h in hypotheses if h.get("status") == "verified")
        total = len(hypotheses)
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
