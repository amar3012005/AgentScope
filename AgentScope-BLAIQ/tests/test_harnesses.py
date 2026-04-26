"""
Tests for agent, tool, and workflow harnesses.

Covers schema validation, constraint checking, and registry operations.
"""

import pytest

from agentscope_blaiq.contracts.harness import (
    AGENT_HARNESSES,
    TOOL_HARNESSES,
    AgentHarness,
    FailureMode,
    Node,
    RecoveryAction,
    RetryPolicy,
    RetryStrategy,
    ToolHarness,
    WorkflowTemplate,
)
from agentscope_blaiq.contracts.registry import HarnessRegistry, reset_registry
from agentscope_blaiq.contracts.validation import (
    check_agent_tool_compatibility,
    check_workflow_agent_compatibility,
    validate_agent_harness,
    validate_all_harnesses,
    validate_tool_harness,
    validate_workflow_template,
)


# ============================================================================
# Tests: AgentHarness Validation
# ============================================================================

class TestAgentHarnessValidation:
    """Test AgentHarness validation rules."""

    def test_valid_agent_harness(self):
        """Valid agent harness passes."""
        is_valid, errors = validate_agent_harness(AGENT_HARNESSES["strategist"])
        assert is_valid
        assert len(errors) == 0

    def test_all_builtin_agents_valid(self):
        """All built-in agents pass validation."""
        for agent_id, harness in AGENT_HARNESSES.items():
            is_valid, errors = validate_agent_harness(harness)
            assert is_valid, f"Agent '{agent_id}' failed: {errors}"

    def test_invalid_empty_agent_id(self):
        """Agent with empty ID is invalid."""
        harness = AgentHarness(agent_id="", role="test")
        is_valid, errors = validate_agent_harness(harness)
        assert not is_valid
        assert any("agent_id" in e for e in errors)

    def test_invalid_timeout(self):
        """Agent with timeout <= 0 is invalid."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AgentHarness(
                agent_id="test",
                role="test",
                timeout_seconds=0,
            )

    def test_invalid_negative_retries(self):
        """Agent with negative retries is invalid."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AgentHarness(
                agent_id="test",
                role="test",
                max_retries=-1,
            )

    def test_invalid_approval_gate_without_flag(self):
        """Agent with requires_approval=True but no approval_gate is invalid."""
        harness = AgentHarness(
            agent_id="test",
            role="test",
            requires_approval=True,
            approval_gate=None,
        )
        is_valid, errors = validate_agent_harness(harness)
        assert not is_valid
        assert any("approval_gate" in e for e in errors)


# ============================================================================
# Tests: ToolHarness Validation
# ============================================================================

class TestToolHarnessValidation:
    """Test ToolHarness validation rules."""

    def test_valid_tool_harness(self):
        """Valid tool harness passes."""
        is_valid, errors = validate_tool_harness(TOOL_HARNESSES["hivemind_recall"])
        assert is_valid
        assert len(errors) == 0

    def test_all_builtin_tools_valid(self):
        """All built-in tools pass validation."""
        for tool_id, harness in TOOL_HARNESSES.items():
            is_valid, errors = validate_tool_harness(harness)
            assert is_valid, f"Tool '{tool_id}' failed: {errors}"

    def test_invalid_empty_tool_id(self):
        """Tool with empty ID is invalid."""
        harness = ToolHarness(
            tool_id="",
            owner_agent="test",
            purpose="test",
            allowed_agents=["test"],
        )
        is_valid, errors = validate_tool_harness(harness)
        assert not is_valid
        assert any("tool_id" in e for e in errors)

    def test_invalid_empty_allowed_agents(self):
        """Tool with no allowed agents is invalid."""
        harness = ToolHarness(
            tool_id="test",
            owner_agent="test",
            purpose="test",
            allowed_agents=[],
        )
        is_valid, errors = validate_tool_harness(harness)
        assert not is_valid
        assert any("allowed_agents" in e for e in errors)

    def test_invalid_timeout(self):
        """Tool with timeout <= 0 is invalid."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ToolHarness(
                tool_id="test",
                owner_agent="test",
                purpose="test",
                allowed_agents=["test"],
                timeout_seconds=0,
            )

    def test_invalid_parallel_calls(self):
        """Tool with parallel_calls < 1 is invalid."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ToolHarness(
                tool_id="test",
                owner_agent="test",
                purpose="test",
                allowed_agents=["test"],
                max_parallel_calls=0,
            )


# ============================================================================
# Tests: WorkflowTemplate Validation
# ============================================================================

class TestWorkflowTemplateValidation:
    """Test WorkflowTemplate validation rules."""

    def test_valid_workflow_minimal(self):
        """Minimal valid workflow passes."""
        nodes = [
            Node(
                node_id="start",
                agent_id="strategist",
                input_from=["start"],
                output_to=["end"],
            ),
        ]
        workflow = WorkflowTemplate(
            workflow_id="test_v1",
            purpose="test workflow",
            nodes=nodes,
            allowed_agents=["strategist"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert is_valid, f"Errors: {errors}"

    def test_invalid_empty_workflow_id(self):
        """Workflow with empty ID is invalid."""
        workflow = WorkflowTemplate(
            workflow_id="",
            purpose="test",
            nodes=[],
            allowed_agents=["test"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert not is_valid
        assert any("workflow_id" in e for e in errors)

    def test_invalid_no_nodes(self):
        """Workflow with no nodes is invalid."""
        workflow = WorkflowTemplate(
            workflow_id="test",
            purpose="test",
            nodes=[],
            allowed_agents=["test"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert not is_valid
        assert any("nodes must be non-empty" in e for e in errors)

    def test_invalid_duplicate_node_ids(self):
        """Workflow with duplicate node IDs is invalid."""
        nodes = [
            Node(node_id="a", agent_id="strategist", input_from=["start"], output_to=[]),
            Node(node_id="a", agent_id="research", input_from=["start"], output_to=[]),
        ]
        workflow = WorkflowTemplate(
            workflow_id="test",
            purpose="test",
            nodes=nodes,
            allowed_agents=["strategist", "research"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert not is_valid
        assert any("unique" in e for e in errors)

    def test_invalid_nonexistent_input_reference(self):
        """Node with invalid input_from reference is invalid."""
        nodes = [
            Node(
                node_id="a",
                agent_id="strategist",
                input_from=["nonexistent"],
                output_to=["b"],
            ),
            Node(
                node_id="b",
                agent_id="research",
                input_from=["a"],
                output_to=[],
            ),
        ]
        workflow = WorkflowTemplate(
            workflow_id="test",
            purpose="test",
            nodes=nodes,
            allowed_agents=["strategist", "research"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert not is_valid
        assert any("input_from" in e for e in errors)

    def test_invalid_cycle_in_workflow(self):
        """Workflow with cycle is invalid."""
        nodes = [
            Node(
                node_id="a",
                agent_id="strategist",
                input_from=["start"],
                output_to=["b"],
            ),
            Node(
                node_id="b",
                agent_id="research",
                input_from=["a"],
                output_to=["a"],  # Cycle back!
            ),
        ]
        workflow = WorkflowTemplate(
            workflow_id="test",
            purpose="test",
            nodes=nodes,
            allowed_agents=["strategist", "research"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert not is_valid
        assert any("cycle" in e.lower() for e in errors)

    def test_valid_linear_workflow(self):
        """Valid linear workflow (A -> B -> C) passes."""
        nodes = [
            Node(
                node_id="planner",
                agent_id="strategist",
                input_from=["start"],
                output_to=["research"],
            ),
            Node(
                node_id="research",
                agent_id="research",
                input_from=["planner"],
                output_to=["governance"],
            ),
            Node(
                node_id="governance",
                agent_id="governance",
                input_from=["research"],
                output_to=["end"],
            ),
        ]
        workflow = WorkflowTemplate(
            workflow_id="linear_v1",
            purpose="test",
            nodes=nodes,
            allowed_agents=["strategist", "research", "governance"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert is_valid, f"Errors: {errors}"

    def test_valid_parallel_workflow(self):
        """Valid parallel workflow passes."""
        nodes = [
            Node(
                node_id="planner",
                agent_id="strategist",
                input_from=["start"],
                output_to=["research", "content"],
            ),
            Node(
                node_id="research",
                agent_id="research",
                input_from=["planner"],
                output_to=["governance"],
                parallel_group="parallel_group_1",
            ),
            Node(
                node_id="content",
                agent_id="content_director",
                input_from=["planner"],
                output_to=["governance"],
                parallel_group="parallel_group_1",
            ),
            Node(
                node_id="governance",
                agent_id="governance",
                input_from=["research", "content"],
                output_to=["end"],
            ),
        ]
        workflow = WorkflowTemplate(
            workflow_id="parallel_v1",
            purpose="test",
            nodes=nodes,
            allowed_agents=["strategist", "research", "content_director", "governance"],
        )
        is_valid, errors = validate_workflow_template(workflow)
        assert is_valid, f"Errors: {errors}"


# ============================================================================
# Tests: Compatibility Checks
# ============================================================================

class TestCompatibilityChecks:
    """Test cross-reference compatibility checks."""

    def test_agent_can_use_tool(self):
        """Agent can use tool if both allow it."""
        agent = AGENT_HARNESSES["text_buddy"]
        tool = TOOL_HARNESSES["apply_brand_voice"]
        is_compatible, error = check_agent_tool_compatibility(agent, tool)
        assert is_compatible
        assert error is None

    def test_agent_cannot_use_tool_not_in_allowed(self):
        """Agent cannot use tool not in allowed_tools."""
        agent = AGENT_HARNESSES["research"]
        tool = TOOL_HARNESSES["apply_brand_voice"]
        is_compatible, error = check_agent_tool_compatibility(agent, tool)
        assert not is_compatible
        assert error is not None

    def test_research_can_use_hivemind_recall(self):
        """Research agent can use hivemind_recall."""
        agent = AGENT_HARNESSES["research"]
        tool = TOOL_HARNESSES["hivemind_recall"]
        is_compatible, error = check_agent_tool_compatibility(agent, tool)
        assert is_compatible
        assert error is None

    def test_deep_research_can_use_hivemind_recall(self):
        """Deep research agent can use hivemind_recall."""
        agent = AGENT_HARNESSES["deep_research"]
        tool = TOOL_HARNESSES["hivemind_recall"]
        is_compatible, error = check_agent_tool_compatibility(agent, tool)
        assert is_compatible
        assert error is None

    def test_governance_cannot_use_research_tools(self):
        """Governance cannot use research tools."""
        agent = AGENT_HARNESSES["governance"]
        tool = TOOL_HARNESSES["hivemind_recall"]
        is_compatible, error = check_agent_tool_compatibility(agent, tool)
        assert not is_compatible

    def test_agent_in_workflow_agents(self):
        """Agent in workflow allowed_agents passes."""
        agent = AGENT_HARNESSES["strategist"]
        workflow = WorkflowTemplate(
            workflow_id="test",
            purpose="test",
            nodes=[],
            allowed_agents=["strategist"],
        )
        is_compatible, error = check_workflow_agent_compatibility(workflow, agent)
        assert is_compatible
        assert error is None

    def test_agent_not_in_workflow_agents(self):
        """Agent not in workflow allowed_agents fails."""
        agent = AGENT_HARNESSES["strategist"]
        workflow = WorkflowTemplate(
            workflow_id="test",
            purpose="test",
            nodes=[],
            allowed_agents=["research"],
        )
        is_compatible, error = check_workflow_agent_compatibility(workflow, agent)
        assert not is_compatible
        assert error is not None


# ============================================================================
# Tests: Registry
# ============================================================================

class TestHarnessRegistry:
    """Test HarnessRegistry operations."""

    def test_registry_load_builtin_agents(self):
        """Registry loads built-in agents."""
        registry = HarnessRegistry()
        registry.load_builtin_agents()
        assert len(registry.agents) > 0
        assert registry.get_agent("strategist") is not None

    def test_registry_load_builtin_tools(self):
        """Registry loads built-in tools."""
        registry = HarnessRegistry()
        registry.load_builtin_tools()
        assert len(registry.tools) > 0
        assert registry.get_tool("hivemind_recall") is not None

    def test_registry_add_agent(self):
        """Registry can add custom agents."""
        registry = HarnessRegistry()
        agent = AgentHarness(agent_id="custom", role="test")
        registry.add_agent(agent)
        assert registry.get_agent("custom") == agent

    def test_registry_add_tool(self):
        """Registry can add custom tools."""
        registry = HarnessRegistry()
        tool = ToolHarness(
            tool_id="custom",
            owner_agent="custom",
            purpose="test",
            allowed_agents=["custom"],
        )
        registry.add_tool(tool)
        assert registry.get_tool("custom") == tool

    def test_registry_validate_builtin(self):
        """Registry validates built-in harnesses."""
        registry = HarnessRegistry()
        registry.load_builtin_agents()
        registry.load_builtin_tools()
        is_valid, errors = registry.validate_all()
        assert is_valid, f"Validation errors: {errors}"

    def test_registry_list_agents(self):
        """Registry lists agent IDs."""
        registry = HarnessRegistry()
        registry.load_builtin_agents()
        agents = registry.list_agents()
        assert len(agents) > 0
        assert "strategist" in agents

    def test_registry_summary(self):
        """Registry provides summary."""
        registry = HarnessRegistry()
        registry.load_builtin_agents()
        registry.load_builtin_tools()
        summary = registry.summary()
        assert summary["agents"] > 0
        assert summary["tools"] > 0
        assert summary["workflows"] == 0


# ============================================================================
# Tests: Cross-Reference Validation
# ============================================================================

class TestCrossReferenceValidation:
    """Test cross-reference validation."""

    def test_validate_all_harnesses_builtin(self):
        """validate_all_harnesses passes for built-in harnesses."""
        errors = validate_all_harnesses(AGENT_HARNESSES, TOOL_HARNESSES, {})
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_invalid_agent_allowed_tool_not_exists(self):
        """Agent with non-existent allowed_tool is caught."""
        agent = AgentHarness(
            agent_id="bad",
            role="test",
            allowed_tools=["nonexistent_tool"],
        )
        errors = validate_all_harnesses({"bad": agent}, {}, {})
        assert any("allowed_tool" in e and "not found" in e for e in errors)

    def test_invalid_tool_owner_agent_not_exists(self):
        """Tool with non-existent owner_agent is caught."""
        tool = ToolHarness(
            tool_id="bad",
            owner_agent="nonexistent",
            purpose="test",
            allowed_agents=["test"],
        )
        errors = validate_all_harnesses({}, {"bad": tool}, {})
        assert any("owner_agent" in e and "not found" in e for e in errors)

    def test_invalid_workflow_agent_not_exists(self):
        """Workflow with non-existent agent is caught."""
        workflow = WorkflowTemplate(
            workflow_id="bad",
            purpose="test",
            nodes=[
                Node(
                    node_id="a",
                    agent_id="nonexistent",
                    input_from=["start"],
                    output_to=[],
                ),
            ],
            allowed_agents=["nonexistent"],
        )
        errors = validate_all_harnesses({}, {}, {"bad": workflow})
        assert any("agent" in e and "not found" in e for e in errors)
