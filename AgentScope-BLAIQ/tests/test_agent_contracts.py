"""Tests verifying that the 3 core agents (TextBuddy, ContentDirector, Vangogh)
have properly tightened harness schemas and contract behaviours.

Contract layer only -- no agentscope runtime, no LLM calls.
"""

from __future__ import annotations

import asyncio

import pytest

from agentscope_blaiq.contracts.enforcement import (
    ContractViolationError,
    EnforcementMode,
    enforcement_check,
    set_enforcement_mode,
)
from agentscope_blaiq.contracts.messages import (
    MsgType,
    RuntimeMsg,
    make_agent_input,
    validate_msg_schema,
)
from agentscope_blaiq.contracts.recovery import (
    FailureClass,
    RetryBudget,
    classify_failure,
    resolve_recovery,
)
from agentscope_blaiq.contracts.registry import (
    HarnessRegistry,
    get_registry,
    reset_registry,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_registry()
    set_enforcement_mode(EnforcementMode.ADVISORY)
    yield  # type: ignore[misc]
    set_enforcement_mode(EnforcementMode.ADVISORY)


@pytest.fixture
def registry() -> HarnessRegistry:
    return get_registry()


# ============================================================================
# Helpers — valid payloads for each agent
# ============================================================================


def _valid_text_buddy_payload() -> dict:
    return {
        "artifact_family": "email",
        "user_query": "Write a cold outreach email",
        "evidence_pack": {
            "summary": "Market data for cold outreach",
            "sources": [{"url": "https://example.com", "title": "Source 1"}],
        },
    }


def _valid_content_director_payload() -> dict:
    return {
        "artifact_spec": {
            "family": "pitch_deck",
            "title": "Q3 Strategy",
        },
        "evidence_pack": {
            "sources": [{"url": "https://example.com", "title": "Source 1"}],
        },
    }


def _valid_vangogh_payload() -> dict:
    return {
        "content_brief": {
            "title": "Q3 Strategy Deck",
            "section_plan": [
                {
                    "section_id": "intro",
                    "title": "Introduction",
                    "objective": "Set context",
                    "evidence_refs": ["src-1"],
                    "visual_intent": "hero image",
                },
            ],
        },
        "artifact_family": "pitch_deck",
    }


# ============================================================================
# TestTextBuddyHarness
# ============================================================================


class TestTextBuddyHarness:
    """Verify text_buddy harness schema constraints."""

    def test_input_schema_requires_artifact_family_user_query_evidence(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("text_buddy")
        assert harness is not None
        required = harness.input_schema.get("required", [])
        assert "artifact_family" in required
        assert "user_query" in required
        assert "evidence_pack" in required

    def test_output_schema_requires_artifact_id_family_title_content(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("text_buddy")
        assert harness is not None
        required = harness.output_schema.get("required", [])
        assert "artifact_id" in required
        assert "family" in required
        assert "title" in required
        assert "content" in required

    def test_valid_input_passes_validation(
        self, registry: HarnessRegistry
    ) -> None:
        msg = make_agent_input(
            workflow_id="text_artifact_v1",
            node_id="text_buddy_node",
            agent_id="text_buddy",
            payload=_valid_text_buddy_payload(),
        )
        ok, errors = validate_msg_schema(msg, registry)
        assert ok, f"Validation failed: {errors}"
        assert errors == []

    def test_missing_user_query_fails(
        self, registry: HarnessRegistry
    ) -> None:
        payload = _valid_text_buddy_payload()
        del payload["user_query"]
        msg = make_agent_input(
            workflow_id="text_artifact_v1",
            node_id="text_buddy_node",
            agent_id="text_buddy",
            payload=payload,
        )
        ok, errors = validate_msg_schema(msg, registry)
        assert not ok
        assert any("user_query" in e for e in errors)

    def test_missing_evidence_pack_fails(
        self, registry: HarnessRegistry
    ) -> None:
        payload = _valid_text_buddy_payload()
        del payload["evidence_pack"]
        msg = make_agent_input(
            workflow_id="text_artifact_v1",
            node_id="text_buddy_node",
            agent_id="text_buddy",
            payload=payload,
        )
        ok, errors = validate_msg_schema(msg, registry)
        assert not ok
        assert any("evidence_pack" in e for e in errors)

    def test_output_schema_has_uncited_claims(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("text_buddy")
        assert harness is not None
        props = harness.output_schema.get("properties", {})
        assert "uncited_claims" in props

    def test_output_schema_has_governance_status_enum(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("text_buddy")
        assert harness is not None
        props = harness.output_schema.get("properties", {})
        gov_prop = props.get("governance_status", {})
        assert "enum" in gov_prop
        assert set(gov_prop["enum"]) == {"pending", "approved", "rejected"}


# ============================================================================
# TestContentDirectorHarness
# ============================================================================


class TestContentDirectorHarness:
    """Verify content_director harness schema constraints."""

    def test_input_schema_requires_artifact_spec_evidence(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("content_director")
        assert harness is not None
        required = harness.input_schema.get("required", [])
        assert "artifact_spec" in required
        assert "evidence_pack" in required

    def test_output_schema_requires_content_brief_with_section_plan(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("content_director")
        assert harness is not None
        required = harness.output_schema.get("required", [])
        assert "content_brief" in required

        brief_schema = harness.output_schema["properties"]["content_brief"]
        brief_required = brief_schema.get("required", [])
        assert "section_plan" in brief_required

    def test_section_plan_items_require_section_id_title_objective(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("content_director")
        assert harness is not None
        brief_schema = harness.output_schema["properties"]["content_brief"]
        section_plan = brief_schema["properties"]["section_plan"]
        item_schema = section_plan["items"]
        item_required = item_schema.get("required", [])
        assert "section_id" in item_required
        assert "title" in item_required
        assert "objective" in item_required

    def test_valid_input_passes_validation(
        self, registry: HarnessRegistry
    ) -> None:
        msg = make_agent_input(
            workflow_id="visual_artifact_v1",
            node_id="content_director_node",
            agent_id="content_director",
            payload=_valid_content_director_payload(),
        )
        ok, errors = validate_msg_schema(msg, registry)
        assert ok, f"Validation failed: {errors}"
        assert errors == []

    def test_missing_artifact_spec_fails(
        self, registry: HarnessRegistry
    ) -> None:
        payload = _valid_content_director_payload()
        del payload["artifact_spec"]
        msg = make_agent_input(
            workflow_id="visual_artifact_v1",
            node_id="content_director_node",
            agent_id="content_director",
            payload=payload,
        )
        ok, errors = validate_msg_schema(msg, registry)
        assert not ok
        assert any("artifact_spec" in e for e in errors)


# ============================================================================
# TestVangoghHarness
# ============================================================================


class TestVangoghHarness:
    """Verify vangogh harness schema constraints."""

    def test_input_schema_requires_content_brief_artifact_family(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("vangogh")
        assert harness is not None
        required = harness.input_schema.get("required", [])
        assert "content_brief" in required
        assert "artifact_family" in required

    def test_output_schema_requires_sections_array(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("vangogh")
        assert harness is not None
        required = harness.output_schema.get("required", [])
        assert "sections" in required
        sections_prop = harness.output_schema["properties"]["sections"]
        assert sections_prop["type"] == "array"

    def test_section_items_require_section_id_index_title_html(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("vangogh")
        assert harness is not None
        sections_prop = harness.output_schema["properties"]["sections"]
        item_schema = sections_prop["items"]
        item_required = item_schema.get("required", [])
        assert "section_id" in item_required
        assert "section_index" in item_required
        assert "title" in item_required
        assert "html_fragment" in item_required

    def test_output_schema_section_map_description(
        self, registry: HarnessRegistry
    ) -> None:
        harness = registry.get_agent("vangogh")
        assert harness is not None
        sections_prop = harness.output_schema["properties"]["sections"]
        assert "Must map 1:1" in sections_prop.get("description", "")

    def test_valid_input_passes_validation(
        self, registry: HarnessRegistry
    ) -> None:
        msg = make_agent_input(
            workflow_id="visual_artifact_v1",
            node_id="vangogh_node",
            agent_id="vangogh",
            payload=_valid_vangogh_payload(),
        )
        ok, errors = validate_msg_schema(msg, registry)
        assert ok, f"Validation failed: {errors}"
        assert errors == []

    def test_missing_content_brief_fails(
        self, registry: HarnessRegistry
    ) -> None:
        payload = _valid_vangogh_payload()
        del payload["content_brief"]
        msg = make_agent_input(
            workflow_id="visual_artifact_v1",
            node_id="vangogh_node",
            agent_id="vangogh",
            payload=payload,
        )
        ok, errors = validate_msg_schema(msg, registry)
        assert not ok
        assert any("content_brief" in e for e in errors)


# ============================================================================
# TestCrossAgentHandoff
# ============================================================================


class TestCrossAgentHandoff:
    """Verify that agent output schemas structurally match downstream input schemas."""

    def test_content_director_output_matches_vangogh_input(
        self, registry: HarnessRegistry
    ) -> None:
        cd = registry.get_agent("content_director")
        vg = registry.get_agent("vangogh")
        assert cd is not None and vg is not None

        # content_director produces content_brief; vangogh requires content_brief
        cd_output_props = cd.output_schema["properties"]
        vg_input_required = vg.input_schema.get("required", [])

        assert "content_brief" in cd_output_props
        assert "content_brief" in vg_input_required

        # content_brief from CD has section_plan; vangogh input content_brief also requires section_plan
        cd_brief = cd_output_props["content_brief"]
        vg_brief = vg.input_schema["properties"]["content_brief"]
        assert "section_plan" in cd_brief.get("properties", {})
        assert "section_plan" in vg_brief.get("properties", {})

    def test_research_output_matches_text_buddy_input(
        self, registry: HarnessRegistry
    ) -> None:
        research = registry.get_agent("research")
        tb = registry.get_agent("text_buddy")
        assert research is not None and tb is not None

        # research produces evidence_pack; text_buddy requires evidence_pack
        research_output_props = research.output_schema["properties"]
        tb_input_required = tb.input_schema.get("required", [])

        assert "evidence_pack" in research_output_props
        assert "evidence_pack" in tb_input_required

    def test_text_buddy_output_matches_governance_input(
        self, registry: HarnessRegistry
    ) -> None:
        tb = registry.get_agent("text_buddy")
        gov = registry.get_agent("governance")
        assert tb is not None and gov is not None

        # text_buddy output has artifact fields; governance input requires artifact
        tb_output_required = tb.output_schema.get("required", [])
        gov_input_required = gov.input_schema.get("required", [])

        # text_buddy outputs artifact_id, family, title, content -- governance takes "artifact" object
        assert "artifact_id" in tb_output_required
        assert "artifact" in gov_input_required

        # governance_status in text_buddy output signals readiness for governance
        tb_output_props = tb.output_schema.get("properties", {})
        assert "governance_status" in tb_output_props


# ============================================================================
# TestRecoveryForAgents
# ============================================================================


class TestRecoveryForAgents:
    """Verify failure classification and recovery resolution for agent scenarios."""

    def test_schema_mismatch_classified_correctly(self) -> None:
        # Simulate a jsonschema.ValidationError by using an error with
        # "schema" in the message (the classifier checks error string).
        error = ValueError("output schema mismatch: missing 'title'")
        fc = classify_failure(error)
        assert fc == FailureClass.SCHEMA_MISMATCH

    def test_text_buddy_timeout_classified_correctly(self) -> None:
        error = asyncio.TimeoutError()
        fc = classify_failure(error)
        assert fc == FailureClass.AGENT_TIMEOUT

    def test_governance_failure_for_vangogh(self) -> None:
        error = RuntimeError("Governance rejected artifact")
        fc = classify_failure(error, {"governance_rejected": True})
        assert fc == FailureClass.GOVERNANCE_FAILURE

    def test_weak_evidence_recovery_retries_research(self) -> None:
        budget = RetryBudget(workflow_id="wf-test")
        action = resolve_recovery(
            FailureClass.WEAK_EVIDENCE, budget, node_id="text_buddy"
        )
        assert action.rerun_upstream == "research"
        assert action.retry_same_node is False


# ============================================================================
# TestEnforcementForAgents
# ============================================================================


class TestEnforcementForAgents:
    """Verify enforcement mode behaviour for contract violations."""

    def test_advisory_mode_does_not_raise_on_invalid_payload(self) -> None:
        set_enforcement_mode(EnforcementMode.ADVISORY)
        # Should NOT raise -- advisory mode only logs
        enforcement_check(
            ok=False,
            errors=["missing required key 'user_query'"],
            context="text_buddy input validation",
        )

    def test_enforced_mode_raises_on_invalid_payload(self) -> None:
        set_enforcement_mode(EnforcementMode.ENFORCED)
        with pytest.raises(ContractViolationError) as exc_info:
            enforcement_check(
                ok=False,
                errors=["missing required key 'user_query'"],
                context="text_buddy input validation",
            )
        assert "user_query" in str(exc_info.value)
        assert exc_info.value.context == "text_buddy input validation"
