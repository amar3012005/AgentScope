# orchestration-patterns

This note groups the multi-agent coordination patterns that AgentScope uses to move work between agents.

## Covered docs

- [Orchestration](https://docs.agentscope.io/building-blocks/orchestration)
- [Multi-Agent Customer Support System](https://docs.agentscope.io/tutorial/tutorial_sales_agent)

## Main patterns

- Conversation/SOP/Workflow for structured multi-step execution.
- Master-worker routing for central coordination with specialist delegation.
- Explicit routing and handoffs when task ownership must change.
- Agent-as-tool when one agent should be callable by another agent.
- Pipeline and chat room patterns for sequential and shared-state collaboration.

## What matters most

- Routing is the entry point for deciding which agent should handle a request.
- Handoffs make ownership transfer explicit instead of implicit.
- Pipelines and MsgHub-style flows are better when several agents must contribute to the same outcome.
- Multi-agent debate and concurrent agents are useful when you need parallel perspectives, not just delegation.
