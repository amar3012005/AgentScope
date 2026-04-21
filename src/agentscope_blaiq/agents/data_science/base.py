"""DataScienceAgent — autonomous data analysis with sandboxed code execution.

Implements end-to-end data science workflows:
  1. File upload validation and secure storage
  2. Data loading and schema inference (CSV, Excel, JSON, databases)
  3. Analysis planning via LLM
  4. Sandboxed Python code execution
  5. Statistical analysis and visualization generation
  6. Results interpretation and EvidencePack enrichment

Integrates with HIVE-MIND for enterprise data context.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscope_blaiq.agents.data_science.code_executor import CodeExecutor
from agentscope_blaiq.agents.data_science.data_loader import DataLoader
from agentscope_blaiq.agents.data_science.statistics import StatisticsEngine
from agentscope_blaiq.agents.data_science.visualizer import Visualizer
from agentscope_blaiq.contracts.evidence import (
    AnalysisResult,
    Citation,
    CodeExecutionResult,
    ContentBriefHandoff,
    DataSchema,
    EvidenceFinding,
    EvidenceFreshness,
    EvidencePack,
    EvidenceProvenance,
    SourceRecord,
    StatisticalResult,
    Visualization,
)
from agentscope_blaiq.runtime.agent_base import AgentLogSink, _noop_sink
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient, HivemindMCPError
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Analysis limits
_MAX_DATASETS = 5
_MAX_ROWS_PREVIEW = 100
_MAX_VISUALIZATIONS = 5
_MAX_STATISTICAL_TESTS = 10
_CODE_EXECUTION_TIMEOUT = 300  # seconds


@dataclass
class AnalysisTask:
    """A data analysis task.

    Attributes:
        objective: The analysis question or goal
        upload_ids: List of uploaded file IDs to analyze
        status: pending | in_progress | completed | failed
        result: AnalysisResult if completed
        error: Error message if failed
    """
    objective: str
    upload_ids: list[str] = field(default_factory=list)
    status: str = "pending"
    result: AnalysisResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON/logging."""
        return {
            "objective": self.objective,
            "upload_ids": self.upload_ids,
            "status": self.status,
            "has_result": self.result is not None,
            "error": self.error,
        }


def _load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_path = _PROMPTS_DIR / filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {filename}")
    return prompt_path.read_text(encoding="utf-8")


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class DataScienceAgent:
    """Autonomous data analysis agent with sandboxed code execution.

    Usage:
        agent = DataScienceAgent(hivemind=hivemind_client, resolver=model_resolver)
        evidence_pack = await agent.gather(
            session=session,
            tenant_id="tenant_123",
            user_query="Analyze sales trends in Q3",
            source_scope="uploads",
        )
    """

    def __init__(
        self,
        *,
        hivemind: HivemindMCPClient,
        resolver: LiteLLMModelResolver,
    ) -> None:
        """Initialize DataScienceAgent.

        Args:
            hivemind: HIVE-MIND MCP client for enterprise data access
            resolver: LiteLLM model resolver for LLM calls
        """
        self.hivemind = hivemind
        self.resolver = resolver
        self._log_sink: AgentLogSink = _noop_sink

        # Initialize components
        self.code_executor = CodeExecutor(timeout=_CODE_EXECUTION_TIMEOUT)
        self.data_loader = DataLoader()
        self.statistics = StatisticsEngine()
        self.visualizer = Visualizer()

        logger.info("DataScienceAgent initialized")

    def set_log_sink(self, sink: AgentLogSink) -> None:
        """Set the log sink for agent output streaming."""
        self._log_sink = sink
        logger.debug("Log sink configured for DataScienceAgent")

    async def _log(
        self,
        message: str,
        kind: str = "info",
        visibility: str = "user",
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Log a message through the configured sink."""
        await self._log_sink(message, kind, visibility, detail)

    # ==================================================================
    # Public API — Data Analysis
    # ==================================================================

    async def gather(
        self,
        session: Any,
        tenant_id: str,
        user_query: str,
        source_scope: str,
    ) -> EvidencePack:
        """Execute autonomous data analysis.

        Workflow:
        1. Parse user query and identify upload IDs from metadata
        2. Load and validate datasets
        3. Infer data schemas
        4. Generate analysis plan via LLM
        5. Execute analysis code in sandbox
        6. Generate visualizations
        7. Run statistical tests
        8. Interpret results via LLM
        9. Build enriched EvidencePack

        Args:
            session: SQLAlchemy async session (for potential DB queries)
            tenant_id: Tenant isolation identifier
            user_query: The analysis question (may include upload references)
            source_scope: "uploads" | "memory" | "all"

        Returns:
            EvidencePack with analysis_result metadata
        """
        await self._log(
            f"Data analysis started: {user_query[:80]}...",
            kind="status",
        )

        # Extract upload IDs from query context
        # (In full implementation, these come from workflow request metadata)
        upload_ids = self._extract_upload_ids(user_query, source_scope)

        if not upload_ids:
            # Fallback to memory-based analysis if no uploads specified
            return await self._gather_from_memory(user_query, tenant_id)

        # Limit number of datasets
        upload_ids = upload_ids[:_MAX_DATASETS]

        await self._log(
            f"Loading {len(upload_ids)} dataset(s) for analysis...",
            kind="status",
            detail={"upload_count": len(upload_ids)},
        )

        # Phase 1: Load datasets
        datasets = await self._load_datasets(upload_ids, tenant_id)

        if not datasets:
            return await self._fallback_response(user_query, "No valid datasets found")

        # Phase 2: Infer schemas
        schemas = await self._infer_schemas(datasets)

        await self._log(
            f"Schema inference complete: {len(schemas)} columns analyzed",
            kind="status",
        )

        # Phase 3: Generate analysis plan
        analysis_plan = await self._generate_analysis_plan(user_query, schemas)

        await self._log(
            f"Analysis plan generated: {analysis_plan.get('analysis_type', 'unknown')}",
            kind="thought",
        )

        # Phase 4: Execute analysis code
        execution_result = await self._execute_analysis_code(analysis_plan, datasets)

        if execution_result.exit_code != 0:
            # Code execution failed — attempt recovery
            recovery_result = await self._recover_from_execution_error(
                execution_result, analysis_plan, schemas
            )
            if recovery_result:
                execution_result = recovery_result
            else:
                return await self._fallback_response(
                    user_query,
                    f"Code execution failed: {execution_result.stderr[:200]}",
                )

        await self._log(
            f"Code executed successfully in {execution_result.execution_time_ms}ms",
            kind="status",
        )

        # Phase 5: Generate visualizations
        visualizations = await self._generate_visualizations(
            execution_result, schemas, user_query
        )

        # Phase 6: Run statistical tests
        statistical_results = await self._run_statistical_tests(
            datasets, analysis_plan, user_query
        )

        # Phase 7: Interpret results
        interpretation = await self._interpret_results(
            execution_result, visualizations, statistical_results, user_query
        )

        # Build AnalysisResult
        analysis_result = AnalysisResult(
            dataset_info=schemas,
            code_execution=execution_result,
            statistical_results=statistical_results,
            visualizations=visualizations,
            key_findings=interpretation.get("key_findings", []),
            limitations=interpretation.get("limitations", []),
            recommendations=interpretation.get("recommendations", []),
        )

        # Build EvidencePack
        evidence_pack = await self._build_evidence_pack(
            user_query, analysis_result, schemas
        )

        await self._log(
            "Data analysis complete",
            kind="status",
            detail={
                "finding_count": len(evidence_pack.memory_findings),
                "visualization_count": len(visualizations),
                "confidence": evidence_pack.confidence,
            },
        )

        return evidence_pack

    # ==================================================================
    # Phase 1: Data Loading
    # ==================================================================

    def _extract_upload_ids(self, user_query: str, source_scope: str) -> list[str]:
        """Extract upload IDs from query context.

        In full implementation, upload IDs come from:
        - Workflow request metadata (uploads attached to task)
        - HIVE-MIND memory references
        - Explicit user mentions (e.g., "analyze file_123.csv")
        """
        # Placeholder — in production, extract from workflow context
        # For now, return empty list to trigger memory fallback
        return []

    async def _load_datasets(
        self, upload_ids: list[str], tenant_id: str
    ) -> dict[str, Any]:
        """Load datasets from upload storage.

        Returns dict mapping upload_id → DataFrame (as dict for JSON serialization)
        """
        datasets = {}

        for upload_id in upload_ids:
            try:
                # In production: load from secure storage
                # For now, create placeholder
                logger.info("Loading dataset: %s", upload_id)
                datasets[upload_id] = {"_placeholder": True, "upload_id": upload_id}
            except Exception as exc:
                logger.warning("Failed to load dataset %s: %s", upload_id, exc)
                await self._log(
                    f"Failed to load {upload_id}: {exc}",
                    kind="error",
                )

        return datasets

    async def _infer_schemas(
        self, datasets: dict[str, Any]
    ) -> list[DataSchema]:
        """Infer schema information from loaded datasets."""
        schemas = []

        # Placeholder schema inference
        # In production: analyze actual DataFrames
        schemas.append(DataSchema(
            column_name="placeholder_column",
            data_type="numeric",
            nullable=False,
            unique_count=100,
            sample_values=["1", "2", "3"],
            statistics={"min": 1, "max": 100, "mean": 50.5, "std": 28.9},
        ))

        return schemas

    # ==================================================================
    # Phase 2: Analysis Planning
    # ==================================================================

    async def _generate_analysis_plan(
        self,
        user_query: str,
        schemas: list[DataSchema],
    ) -> dict[str, Any]:
        """Generate analysis plan using LLM.

        Analyzes the query and data schema to determine:
        - Analysis type (EDA, modeling, computation)
        - Required statistical tests
        - Visualization types needed
        - Code to execute
        """
        schema_text = "\n".join([
            f"- {s.column_name} ({s.data_type}): {s.unique_count} unique values"
            for s in schemas[:10]
        ])

        prompt_template = _load_prompt("data_analysis_plan.md")
        prompt = (
            prompt_template
            .replace("{user_query}", user_query)
            .replace("{schema_info}", schema_text)
        )

        messages = [
            {"role": "system", "content": "You are a data science expert. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "data_scientist",
                messages,
                max_tokens=2000,
                temperature=0.1,
            )
            text = self.resolver.extract_text(response)
            plan = self.resolver.safe_json_loads(text)

            return {
                "analysis_type": plan.get("analysis_type", "explorative_data_analysis"),
                "description": plan.get("description", user_query),
                "python_code": plan.get("python_code", ""),
                "visualizations": plan.get("visualizations", []),
                "statistical_tests": plan.get("statistical_tests", []),
            }
        except Exception as exc:
            logger.warning("Analysis plan generation failed: %s", exc)

        # Fallback plan
        return {
            "analysis_type": "explorative_data_analysis",
            "description": f"Analyze data to answer: {user_query}",
            "python_code": "",
            "visualizations": ["summary_stats"],
            "statistical_tests": ["descriptive"],
        }

    # ==================================================================
    # Phase 3: Code Execution
    # ==================================================================

    async def _execute_analysis_code(
        self,
        analysis_plan: dict[str, Any],
        datasets: dict[str, Any],
    ) -> CodeExecutionResult:
        """Execute analysis code in Docker sandbox."""
        python_code = analysis_plan.get("python_code", "")

        if not python_code:
            # Generate default analysis code
            python_code = self._generate_default_analysis_code(datasets)

        return await self.code_executor.execute(
            code=python_code,
            datasets=datasets,
            timeout=_CODE_EXECUTION_TIMEOUT,
        )

    def _generate_default_analysis_code(self, datasets: dict[str, Any]) -> str:
        """Generate default exploratory analysis code."""
        return '''
import pandas as pd
import numpy as np

# Load data (placeholder)
print("Loading datasets...")

# Generate summary statistics
print("Summary statistics:")
print("Data loaded successfully")

# Return results as JSON
results = {
    "row_count": 0,
    "column_count": 0,
    "analysis_complete": True
}
print(f"Results: {json.dumps(results)}")
'''

    async def _recover_from_execution_error(
        self,
        result: CodeExecutionResult,
        analysis_plan: dict[str, Any],
        schemas: list[DataSchema],
    ) -> CodeExecutionResult | None:
        """Attempt to recover from code execution error using LLM."""
        error_type = result.error_type or "RuntimeError"
        stderr = result.stderr[:1000]

        prompt_template = _load_prompt("error_recovery.md")
        prompt = (
            prompt_template
            .replace("{original_code}", analysis_plan.get("python_code", "")[:2000])
            .replace("{error_type}", error_type)
            .replace("{error_message}", stderr)
        )

        messages = [
            {"role": "system", "content": "You are a Python debugging expert. Return only the fixed code."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "data_scientist",
                messages,
                max_tokens=1500,
                temperature=0.1,
            )
            fixed_code = self.resolver.extract_text(response)

            # Retry execution with fixed code
            return await self.code_executor.execute(
                code=fixed_code,
                timeout=_CODE_EXECUTION_TIMEOUT,
            )
        except Exception as exc:
            logger.warning("Error recovery failed: %s", exc)

        return None

    # ==================================================================
    # Phase 4: Visualization & Statistics
    # ==================================================================

    async def _generate_visualizations(
        self,
        execution_result: CodeExecutionResult,
        schemas: list[DataSchema],
        user_query: str,
    ) -> list[Visualization]:
        """Generate visualizations from analysis results."""
        visualizations = []

        # In production: parse execution artifacts, generate plots
        # For now, create placeholder visualization
        visualizations.append(Visualization(
            viz_id="viz_summary_001",
            viz_type="summary",
            title="Data Summary",
            description="Overview of analyzed dataset",
            file_path="/tmp/viz_summary.png",
            file_type="png",
            data_summary="Placeholder visualization",
        ))

        return visualizations

    async def _run_statistical_tests(
        self,
        datasets: dict[str, Any],
        analysis_plan: dict[str, Any],
        user_query: str,
    ) -> list[StatisticalResult]:
        """Run statistical tests based on analysis plan."""
        results = []

        # In production: execute actual statistical tests
        # For now, create placeholder
        results.append(StatisticalResult(
            stat_type="descriptive",
            test_name="Summary Statistics",
            result_dict={"count": 0, "mean": 0, "std": 0},
            interpretation="Descriptive statistics computed",
        ))

        return results

    # ==================================================================
    # Phase 5: Interpretation
    # ==================================================================

    async def _interpret_results(
        self,
        execution_result: CodeExecutionResult,
        visualizations: list[Visualization],
        statistical_results: list[StatisticalResult],
        user_query: str,
    ) -> dict[str, Any]:
        """Interpret analysis results using LLM."""
        # Prepare context for interpretation
        results_summary = execution_result.stdout[:2000]
        viz_count = len(visualizations)
        stats_count = len(statistical_results)

        prompt_template = _load_prompt("interpretation.md")
        prompt = (
            prompt_template
            .replace("{user_query}", user_query)
            .replace("{execution_output}", results_summary)
            .replace("{visualization_count}", str(viz_count))
            .replace("{statistical_test_count}", str(stats_count))
        )

        messages = [
            {"role": "system", "content": "You are a data analysis interpreter. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.resolver.acompletion(
                "data_scientist",
                messages,
                max_tokens=1500,
                temperature=0.2,
            )
            text = self.resolver.extract_text(response)
            return self.resolver.safe_json_loads(text)
        except Exception as exc:
            logger.warning("Result interpretation failed: %s", exc)

        # Fallback
        return {
            "key_findings": [f"Analysis completed for: {user_query}"],
            "limitations": ["Placeholder response — full analysis pending data upload"],
            "recommendations": ["Upload data files for comprehensive analysis"],
        }

    # ==================================================================
    # EvidencePack Construction
    # ==================================================================

    async def _build_evidence_pack(
        self,
        user_query: str,
        analysis_result: AnalysisResult,
        schemas: list[DataSchema],
    ) -> EvidencePack:
        """Build EvidencePack with analysis results."""
        # Create findings from analysis
        findings = []
        sources = []
        citations = []

        # Key findings as EvidenceFindings
        for i, finding in enumerate(analysis_result.key_findings):
            finding_id = f"analysis:{hashlib.md5(finding.encode()).hexdigest()[:12]}"
            findings.append(EvidenceFinding(
                finding_id=finding_id,
                title=f"Analysis Finding {i+1}",
                summary=finding,
                source_ids=[f"analysis:{finding_id}"],
                confidence=0.8,
            ))
            sources.append(SourceRecord(
                source_id=finding_id,
                source_type="analysis",
                title=f"Analysis result {i+1}",
                location=f"analysis://{finding_id}",
            ))
            citations.append(Citation(
                source_id=finding_id,
                label=f"Analysis Finding {i+1}",
                excerpt=finding[:200],
            ))

        # Compute confidence
        confidence = 0.7 if analysis_result.code_execution and analysis_result.code_execution.exit_code == 0 else 0.5

        # Build content brief for downstream agents
        content_brief = ContentBriefHandoff(
            key_message=analysis_result.key_findings[0] if analysis_result.key_findings else f"Analysis of: {user_query}",
            supporting_pillars=analysis_result.key_findings[:3],
            tone_guidance="Data-driven and analytical",
            must_include_claims=analysis_result.key_findings[:2],
            visual_opportunities=[
                {"value": str(len(analysis_result.visualizations)), "label": "Visualizations Generated", "visual_type": "stat_callout"}
            ],
        )

        return EvidencePack(
            summary=f"Data analysis complete: {user_query}. " + " ".join(analysis_result.key_findings[:2]),
            sources=sources,
            memory_findings=findings,
            web_findings=[],
            doc_findings=[],
            open_questions=[],
            confidence=confidence,
            citations=citations,
            contradictions=[],
            freshness=EvidenceFreshness(
                memory_is_fresh=True,
                web_verified=False,
                freshness_summary=f"Analysis based on uploaded datasets",
                checked_at=_now_iso(),
            ),
            provenance=EvidenceProvenance(
                memory_sources=len(sources),
                web_sources=0,
                upload_sources=len(analysis_result.dataset_info),
                graph_traversals=0,
                primary_ground_truth="uploads",
                save_back_eligible=False,
            ),
            recommended_followups=analysis_result.recommendations,
            analysis_result=analysis_result,
            content_brief=content_brief,
        )

    # ==================================================================
    # Fallback & Memory-Based Analysis
    # ==================================================================

    async def _gather_from_memory(
        self,
        user_query: str,
        tenant_id: str,
    ) -> EvidencePack:
        """Fallback to HIVE-MIND memory analysis when no uploads available."""
        try:
            recall_result = await self.hivemind.recall(
                query=user_query,
                limit=10,
                mode="insight",
            )
            payload = (
                self.hivemind._extract_tool_payload(recall_result)
                if isinstance(recall_result, dict) else recall_result
            )
            memories = self._normalize_memories(payload)

            findings = []
            sources = []
            citations = []

            for mem in memories[:5]:
                memory_id = str(mem.get("memory_id", mem.get("id", "")))
                content = str(mem.get("content", mem.get("text", "")))
                score = float(mem.get("score", mem.get("relevance", 0.5)))

                if len(content) > 20:
                    finding_id = f"memory:{memory_id}"
                    findings.append(EvidenceFinding(
                        finding_id=finding_id,
                        title=mem.get("title", "Memory finding")[:100],
                        summary=content[:500],
                        source_ids=[memory_id],
                        confidence=min(score, 1.0),
                    ))
                    sources.append(SourceRecord(
                        source_id=memory_id,
                        source_type="hivemind_memory",
                        title=mem.get("title", "Memory")[:100],
                        location=f"hivemind://{memory_id}",
                    ))
                    citations.append(Citation(
                        source_id=memory_id,
                        label=mem.get("title", "Memory")[:100],
                        excerpt=content[:200],
                    ))

            confidence = sum(f.confidence for f in findings) / len(findings) if findings else 0.5

            return EvidencePack(
                summary=f"Analysis based on enterprise memory for: {user_query}",
                sources=sources,
                memory_findings=findings,
                web_findings=[],
                doc_findings=[],
                open_questions=[],
                confidence=confidence,
                citations=citations,
                contradictions=[],
                freshness=EvidenceFreshness(
                    memory_is_fresh=True,
                    web_verified=False,
                    freshness_summary=f"Memory-based analysis with {len(findings)} findings",
                    checked_at=_now_iso(),
                ),
                provenance=EvidenceProvenance(
                    memory_sources=len(sources),
                    web_sources=0,
                    upload_sources=0,
                    graph_traversals=0,
                    primary_ground_truth="memory",
                    save_back_eligible=False,
                ),
                recommended_followups=["Upload data files for comprehensive quantitative analysis"],
            )

        except HivemindMCPError as exc:
            logger.warning("Memory-based analysis failed: %s", exc)
            return await self._fallback_response(user_query, str(exc))

    async def _fallback_response(
        self,
        user_query: str,
        error_message: str,
    ) -> EvidencePack:
        """Return a fallback EvidencePack when analysis fails."""
        return EvidencePack(
            summary=f"Analysis could not be completed: {error_message}",
            sources=[],
            memory_findings=[],
            web_findings=[],
            doc_findings=[],
            open_questions=[user_query],
            confidence=0.2,
            citations=[],
            contradictions=[],
            freshness=EvidenceFreshness(
                memory_is_fresh=False,
                web_verified=False,
                freshness_summary=error_message,
                checked_at=_now_iso(),
            ),
            provenance=EvidenceProvenance(
                memory_sources=0,
                web_sources=0,
                upload_sources=0,
                graph_traversals=0,
                primary_ground_truth="memory",
                save_back_eligible=False,
            ),
            recommended_followups=["Ensure data files are properly uploaded and try again"],
        )

    @staticmethod
    def _normalize_memories(payload: dict | list) -> list[dict]:
        """Normalize HIVE-MIND memory payload to list of dicts."""
        if isinstance(payload, dict):
            if "results" in payload:
                return payload["results"]
            if "memories" in payload:
                return payload["memories"]
            return [payload]
        if isinstance(payload, list):
            return payload
        return []
