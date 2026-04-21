# agent-and-tool-stack

This note groups the agent execution stack, tool stack, and extension points that sit around them.

## Covered docs

- [Agent](https://docs.agentscope.io/basic-concepts/agent)
- [Tool](https://docs.agentscope.io/basic-concepts/tool)
- [Message](https://docs.agentscope.io/basic-concepts/msg)
- [Agent runtime](https://docs.agentscope.io/building-blocks/agent)
- [Tool capabilities](https://docs.agentscope.io/building-blocks/tool-capabilities)

## Main themes

- Agents are independent entities that reason, observe, and act.
- ReActAgent is the default operational agent for tool-using workflows.
- Hooks, state/session management, A2A, and realtime support are the main runtime extension layers.
- Tools are normalized through Toolkit, middleware, MCP integration, and skills.

## Practical reading order

1. Read `basic-concepts/agent` for the mental model.
2. Read `building-blocks/agent` for the operational features.
3. Read `basic-concepts/tool` and `building-blocks/tool-capabilities` for external action and extensibility.
4. Read `basic-concepts/msg` last if you want the message object details behind the orchestration flow.
