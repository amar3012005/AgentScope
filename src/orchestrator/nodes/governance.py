"""Governance validation node -- enforces brand safety and schema integrity.

Runs entirely in-process (no external service).  Loads the brand DNA file
and validates the graph output against schema completeness, tenant isolation,
brand palette compliance, and basic content safety rules.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

from orchestrator.contracts.manifests import GovernanceReport, PolicyCheck
from orchestrator.contracts.node_outputs import GovernanceResult
from orchestrator.observability import get_tracer
from orchestrator.state import BlaiqGraphState
from utils.logging_utils import log_flow

logger = logging.getLogger("blaiq-core.governance_node")

BRAND_DNA_PATH: str = os.getenv("BRAND_DNA_PATH", "brand_dna/davinci_ai.json")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379")

# Basic blocklist for content safety (extend as needed)
_HARMFUL_PATTERNS: list[str] = [
    r"\b(murder|suicide|bomb(?:ing)?|weapon(?:s|ry)?)\b",
    r"\b(phishing|malware|ransomware)\b",
    r"\b(racial slur placeholder)\b",
]


def _load_brand_dna() -> Dict[str, Any]:
    """Load brand DNA JSON, returning empty dict on failure."""
    path = Path(BRAND_DNA_PATH)
    if not path.exists():
        logger.warning("brand_dna_not_found path=%s", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("brand_dna_load_error err=%s", exc)
        return {}


def _check_schema_completeness(
    evidence: Optional[Dict[str, Any]],
    content: Optional[Dict[str, Any]],
) -> PolicyCheck:
    """Verify that required fields are present in output manifests."""
    missing: list[str] = []
    if evidence:
        for field in ("mission_id", "query"):
            if not evidence.get(field):
                missing.append(f"evidence.{field}")
    if content:
        for field in ("mission_id",):
            if not content.get(field):
                missing.append(f"content.{field}")
        # Must have either inline HTML or an artifact URI
        if not content.get("html_artifact") and not content.get("artifact_uri"):
            missing.append("content.html_artifact|artifact_uri")

    passed = len(missing) == 0
    return PolicyCheck(
        rule="schema_completeness",
        passed=passed,
        detail="" if passed else f"Missing fields: {', '.join(missing)}",
    )


def _check_tenant_isolation(
    state: BlaiqGraphState,
    evidence: Optional[Dict[str, Any]],
) -> PolicyCheck:
    """Ensure response data belongs to the requesting tenant."""
    expected = state.get("collection_name", "")
    if not evidence or not expected:
        return PolicyCheck(rule="tenant_isolation", passed=True, detail="No evidence to check")

    # Check if any chunk references a different tenant scope
    chunks = evidence.get("chunks") or []
    foreign: list[str] = []
    for chunk in chunks:
        fname = chunk.get("original_filename", "")
        # Heuristic: if filename encodes a different collection prefix, flag it
        if fname and expected not in fname and chunk.get("doc_id", "").split("/")[0] not in (expected, ""):
            foreign.append(chunk.get("chunk_id", "unknown"))

    passed = len(foreign) == 0
    return PolicyCheck(
        rule="tenant_isolation",
        passed=passed,
        detail="" if passed else f"Foreign chunks detected: {foreign[:5]}",
    )


def _check_brand_palette(
    html: Optional[str],
    brand_dna: Dict[str, Any],
) -> PolicyCheck:
    """If HTML exists, verify colors belong to the brand token palette."""
    if not html or not brand_dna:
        return PolicyCheck(rule="brand_palette", passed=True, detail="No HTML or brand DNA to check")

    # Extract allowed colours from brand DNA
    palette: list[str] = []
    colors_section = brand_dna.get("colors", brand_dna.get("brand_colors", brand_dna.get("palette", {})))
    if isinstance(colors_section, dict):
        for value in colors_section.values():
            if isinstance(value, str):
                palette.append(value.lower())
            elif isinstance(value, dict):
                palette.extend(v.lower() for v in value.values() if isinstance(v, str))
    elif isinstance(colors_section, list):
        palette.extend(c.lower() for c in colors_section if isinstance(c, str))

    if not palette:
        return PolicyCheck(rule="brand_palette", passed=True, detail="No palette defined in brand DNA")

    # Find hex colours in HTML
    hex_colors_in_html = set(re.findall(r"#[0-9a-fA-F]{3,8}", html))
    off_brand: list[str] = []
    for color in hex_colors_in_html:
        normalised = color.lower()
        # Expand 3-char hex to 6-char for comparison
        if len(normalised) == 4:
            normalised = f"#{normalised[1]*2}{normalised[2]*2}{normalised[3]*2}"
        # Common safe colours (white, black, transparent greys) are always OK
        if normalised in ("#ffffff", "#000000", "#fff", "#000", "#f5f5f5", "#e5e5e5", "#333333", "#666666", "#999999"):
            continue
        if normalised not in palette:
            off_brand.append(color)

    passed = len(off_brand) == 0
    return PolicyCheck(
        rule="brand_palette",
        passed=passed,
        detail="" if passed else f"Off-brand colours: {off_brand[:10]}",
    )


def _check_content_safety(text: str) -> PolicyCheck:
    """Basic regex scan for obviously harmful content."""
    if not text:
        return PolicyCheck(rule="content_safety", passed=True, detail="No text to check")

    violations: list[str] = []
    for pattern in _HARMFUL_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            violations.extend(matches[:3])

    passed = len(violations) == 0
    return PolicyCheck(
        rule="content_safety",
        passed=passed,
        detail="" if passed else f"Flagged terms: {violations[:10]}",
    )


async def _resolve_json_artifact(artifact_uri: str) -> Optional[Dict[str, Any]]:
    if not artifact_uri.startswith("redis://"):
        return None

    redis_key = artifact_uri.replace("redis://", "", 1)
    try:
        async with aioredis.from_url(REDIS_URL) as redis_client:
            raw = await redis_client.get(redis_key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception as exc:
        logger.warning("governance_resolve_json_error key=%s err=%s", redis_key, exc)
        return None


async def _resolve_text_artifact(artifact_uri: str) -> Optional[str]:
    if not artifact_uri.startswith("redis://"):
        return None

    redis_key = artifact_uri.replace("redis://", "", 1)
    try:
        async with aioredis.from_url(REDIS_URL) as redis_client:
            raw = await redis_client.get(redis_key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)
    except Exception as exc:
        logger.warning("governance_resolve_text_error key=%s err=%s", redis_key, exc)
        return None


async def _resolve_claim_checked_payloads(
    evidence: Optional[Dict[str, Any]],
    content: Optional[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    resolved_evidence = dict(evidence) if evidence else None
    resolved_content = dict(content) if content else None

    if resolved_evidence and resolved_evidence.get("artifact_uri") and not resolved_evidence.get("chunks"):
        loaded_evidence = await _resolve_json_artifact(resolved_evidence["artifact_uri"])
        if loaded_evidence:
            loaded_evidence.setdefault("artifact_uri", resolved_evidence["artifact_uri"])
            resolved_evidence = loaded_evidence

    if resolved_content and resolved_content.get("artifact_uri") and not resolved_content.get("html_artifact"):
        loaded_html = await _resolve_text_artifact(resolved_content["artifact_uri"])
        if loaded_html is not None:
            resolved_content["html_artifact"] = loaded_html

    return resolved_evidence, resolved_content


async def governance_node(state: BlaiqGraphState) -> dict:
    """Validate outputs against brand, schema, tenant, and safety policies."""
    tracer = get_tracer("blaiq-core.governance")
    with tracer.start_as_current_span("governance_node") as span:
        span.set_attribute("tenant.id", state.get("tenant_id", ""))

        evidence: Optional[Dict[str, Any]] = state.get("evidence_manifest")
        content: Optional[Dict[str, Any]] = state.get("content_draft")
        thread_id: str = state.get("thread_id", "")
        session_id: str = state.get("session_id", "")
        logs: list[str] = []
        ts_start = time.time()
        log_flow(
            logger,
            "wf_node_start",
            node="governance",
            thread_id=thread_id,
            session_id=session_id,
            has_evidence=bool(evidence),
            has_content=bool(content),
        )

        brand_dna = _load_brand_dna()
        evidence, content = await _resolve_claim_checked_payloads(evidence, content)

        checks: list[PolicyCheck] = []

        # 1. Schema completeness
        checks.append(_check_schema_completeness(evidence, content))

        # 2. Tenant isolation
        checks.append(_check_tenant_isolation(state, evidence))

        # 3. Brand palette (only if content has HTML)
        html_artifact = content.get("html_artifact") if content else None
        checks.append(_check_brand_palette(html_artifact, brand_dna))

        # 4. Content safety on all textual output
        combined_text = ""
        if evidence:
            combined_text += evidence.get("answer", "")
        if html_artifact:
            combined_text += " " + html_artifact
        checks.append(_check_content_safety(combined_text))

        # Aggregate
        violations = [c.detail for c in checks if not c.passed]
        all_passed = all(c.passed for c in checks)

        span.set_attribute("governance.passed", all_passed)
        span.set_attribute("governance.violations", len(violations))

        mission_id = ""
        if evidence:
            mission_id = evidence.get("mission_id", "")
        elif content:
            mission_id = content.get("mission_id", "")

        report = GovernanceReport(
            mission_id=mission_id,
            validation_passed=all_passed,
            policy_checks=checks,
            violations=violations,
            approved_output=html_artifact if all_passed and html_artifact else None,
        )

        report_dict = report.model_dump(mode="json")
        latency = time.time() - ts_start

        if all_passed:
            logs.append(f"governance_node: PASSED ({len(checks)} checks in {latency:.2f}s)")
            log_flow(
                logger,
                "governance_passed",
                checks=len(checks),
                latency_s=round(latency, 3),
                thread_id=thread_id,
                session_id=session_id,
            )
        else:
            logs.append(
                f"governance_node: FAILED — {len(violations)} violation(s): "
                f"{'; '.join(violations[:5])}"
            )
            log_flow(
                logger,
                "governance_failed",
                level="warning",
                violation_count=len(violations),
                violations=violations[:5],
                thread_id=thread_id,
                session_id=session_id,
            )

        log_flow(
            logger,
            "wf_node_complete",
            node="governance",
            thread_id=thread_id,
            session_id=session_id,
            latency_ms=int((time.time() - ts_start) * 1000),
            passed=all_passed,
            checks=len(checks),
            violations=len(violations),
        )

        final_status = "complete" if all_passed else "error"
        error_msg = ""
        if not all_passed:
            error_msg = f"Governance validation failed: {'; '.join(violations[:3])}"

        return GovernanceResult(
            governance_report=report_dict,
            status=final_status,
            current_node="governance_node",
            error_message=error_msg,
            logs=logs,
        ).to_state_update()
