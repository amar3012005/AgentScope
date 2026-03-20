---
name: agent-strategist
description: Use when a task needs multi-agent decomposition, routing, ownership boundaries, capability mapping, handoff planning, or orchestration decisions across frontend, backend, and platform work.
---

# Agent Strategist

Use this skill first when the task spans multiple parts of the system or when the right implementation owner is unclear.

## Responsibilities

- classify the request
- decide which agents should handle which parts
- define the execution order
- identify shared contracts and dependencies
- keep the system extensible for future agents

## Workflow

1. Identify whether the task is frontend, backend, platform, or mixed.
2. Break work into subproblems with a single owner per subproblem.
3. Define coordination boundaries:
   - payload shapes
   - streaming/event contracts
   - env/config dependencies
   - testing ownership
4. Prefer the smallest agent set that can complete the task cleanly.
5. For ambiguous work, document the routing decision in concise terms before editing code.

## Output Style

- State which agents are active.
- State why they are active.
- Keep the handoff explicit and short.
