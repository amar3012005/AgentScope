from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
from agentscope_blaiq.runtime.registry import AgentRegistry


def test_custom_text_buddy_appears_in_live_catalog() -> None:
    registry = AgentRegistry()
    spec = CustomAgentSpec(
        agent_id="custom_writer",
        display_name="Custom Writer",
        prompt="You are a highly specific enterprise writing agent for board-facing summaries.",
        role="text_buddy",
        input_schema={
            "type": "object",
            "properties": {"user_query": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
        },
        allowed_tools=["apply_brand_voice", "select_template", "format_output"],
        allowed_workflows=["text_artifact_v1"],
        artifact_family="summary",
    )

    registration = registry.user_agent_registry.register(spec)

    assert registration.harness_valid is True
    assert any(profile.name == "custom_writer" for profile in registry.list_live_profiles())


def test_custom_text_buddy_runtime_agent_uses_custom_prompt() -> None:
    registry = AgentRegistry()
    spec = CustomAgentSpec(
        agent_id="custom_writer_runtime",
        display_name="Custom Writer Runtime",
        prompt="You are a custom text_buddy agent that writes in a strict investor-update tone.",
        role="text_buddy",
        input_schema={
            "type": "object",
            "properties": {"user_query": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
        },
        allowed_tools=["apply_brand_voice", "select_template", "format_output"],
        allowed_workflows=["text_artifact_v1"],
        artifact_family="summary",
    )
    registry.user_agent_registry.register(spec)

    agent = registry.get_agent("custom_writer_runtime")

    assert agent is not None
    assert agent.name == "Custom Writer Runtime"
    assert agent.role == "text_buddy"
    assert "investor-update tone" in agent.sys_prompt
