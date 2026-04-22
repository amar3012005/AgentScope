"""
Harness registry for agents, tools, and workflows.

Manages loading, caching, and validation of harnesses.
"""

from __future__ import annotations

from typing import Any, Optional

from .harness import (
    AGENT_HARNESSES,
    TOOL_HARNESSES,
    AgentHarness,
    ToolHarness,
    WorkflowTemplate,
)
from .validation import validate_all_harnesses


class HarnessRegistry:
    """
    Registry for agent, tool, and workflow harnesses.

    Loads harnesses from Python constants or YAML/JSON files.
    Validates all loaded definitions.
    Provides lookup by ID.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self.agents: dict[str, AgentHarness] = {}
        self.tools: dict[str, ToolHarness] = {}
        self.workflows: dict[str, WorkflowTemplate] = {}
        self._workflows: dict[str, WorkflowTemplate] = {}
        self._validated = False

    def load_builtin_agents(self) -> None:
        """Load built-in agent harnesses."""
        self.agents.update(AGENT_HARNESSES)

    def load_builtin_tools(self) -> None:
        """Load built-in tool harnesses."""
        self.tools.update(TOOL_HARNESSES)

    def load_builtin_workflows(self) -> None:
        """Load all canonical workflow templates from WORKFLOW_TEMPLATES."""
        # Local import to avoid circular imports
        from .workflows import WORKFLOW_TEMPLATES  # noqa: PLC0415
        self._workflows.update(WORKFLOW_TEMPLATES)
        self.workflows.update(WORKFLOW_TEMPLATES)

    def add_agent(self, agent: AgentHarness) -> None:
        """Add a single agent harness."""
        self.agents[agent.agent_id] = agent
        self._validated = False

    def add_tool(self, tool: ToolHarness) -> None:
        """Add a single tool harness."""
        self.tools[tool.tool_id] = tool
        self._validated = False

    def add_workflow(self, workflow: WorkflowTemplate) -> None:
        """Add a single workflow template."""
        self.workflows[workflow.workflow_id] = workflow
        self._validated = False

    def get_agent(self, agent_id: str) -> Optional[AgentHarness]:
        """Get agent harness by ID."""
        return self.agents.get(agent_id)

    def get_tool(self, tool_id: str) -> Optional[ToolHarness]:
        """Get tool harness by ID."""
        return self.tools.get(tool_id)

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowTemplate]:
        """Get workflow template by ID."""
        return self.workflows.get(workflow_id)

    def list_agents(self) -> list[str]:
        """List all agent IDs."""
        return list(self.agents.keys())

    def list_tools(self) -> list[str]:
        """List all tool IDs."""
        return list(self.tools.keys())

    def list_workflows(self) -> list[str]:
        """List all workflow IDs."""
        return list(self.workflows.keys())

    def list_workflow_ids(self) -> list[str]:
        """Return sorted list of registered workflow IDs."""
        return sorted(self.workflows.keys())

    def get_harness_snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all registered agents, tools, and workflows."""
        return {
            "agents": {
                agent_id: harness.model_dump()
                for agent_id, harness in self.agents.items()
            },
            "tools": {
                tool_id: harness.model_dump()
                for tool_id, harness in self.tools.items()
            },
            "workflows": {
                workflow_id: workflow.model_dump()
                for workflow_id, workflow in self.workflows.items()
            },
        }

    def validate_workflow_for_agent(
        self, workflow_id: str, agent_id: str
    ) -> tuple[bool, list[str]]:
        """
        Check that a workflow exists, the agent exists, and the agent is
        listed in workflow.allowed_agents.

        Returns (True, []) if valid, (False, errors) otherwise.
        """
        errors: list[str] = []

        workflow = self.get_workflow(workflow_id)
        if workflow is None:
            errors.append(f"Workflow '{workflow_id}' not found")

        agent = self.get_agent(agent_id)
        if agent is None:
            errors.append(f"Agent '{agent_id}' not found")

        if workflow is not None and agent is not None:
            if agent_id not in workflow.allowed_agents:
                errors.append(
                    f"Agent '{agent_id}' is not in allowed_agents for workflow '{workflow_id}'"
                )

        if errors:
            return False, errors
        return True, []

    def validate_workflow_for_tool(
        self, workflow_id: str, tool_id: str
    ) -> tuple[bool, list[str]]:
        """
        Check that a workflow exists, the tool exists, and the tool's
        allowed_workflows includes this workflow_id (when allowed_workflows
        is non-empty).

        Returns (True, []) if valid, (False, errors) otherwise.
        """
        errors: list[str] = []

        workflow = self.get_workflow(workflow_id)
        if workflow is None:
            errors.append(f"Workflow '{workflow_id}' not found")

        tool = self.get_tool(tool_id)
        if tool is None:
            errors.append(f"Tool '{tool_id}' not found")

        if workflow is not None and tool is not None:
            if tool.allowed_workflows and workflow_id not in tool.allowed_workflows:
                errors.append(
                    f"Tool '{tool_id}' does not allow workflow '{workflow_id}'"
                )

        if errors:
            return False, errors
        return True, []

    def validate_all(self) -> tuple[bool, list[str]]:
        """
        Validate all loaded harnesses and their cross-references.
        Returns (is_valid, errors).
        """
        errors = validate_all_harnesses(self.agents, self.tools, self.workflows)
        self._validated = len(errors) == 0
        return self._validated, errors

    def is_valid(self) -> bool:
        """Check if registry has been validated."""
        return self._validated

    def summary(self) -> dict[str, int]:
        """Return summary of loaded harnesses."""
        return {
            "agents": len(self.agents),
            "tools": len(self.tools),
            "workflows": len(self.workflows),
            "validated": self._validated,
        }


# Global registry instance
_global_registry: Optional[HarnessRegistry] = None


def get_registry() -> HarnessRegistry:
    """Get or create the global harness registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = HarnessRegistry()
        _global_registry.load_builtin_agents()
        _global_registry.load_builtin_tools()
        _global_registry.load_builtin_workflows()
    return _global_registry


def reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _global_registry
    _global_registry = None
