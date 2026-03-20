---
name: frontend-experience-agent
description: Use when implementing chat UI, streaming UX, agent-state visualization, browser session handling, interactive controls, or frontend integration with BLAIQ-CORE and sub-agents.
---

# Frontend Experience Agent

Use this skill for browser-facing work and streamed user interaction.

## Responsibilities

- chat UI flows
- streaming response rendering
- agent timeline and status display
- browser session and room handling
- tenant-aware frontend payloads
- usability and accessibility of orchestration views

## Workflow

1. Treat BLAIQ-CORE as the default frontend backend unless explicitly told otherwise.
2. Keep the UI clear about which agent is active and what state the request is in.
3. Preserve streamed output behavior while adding orchestration metadata.
4. Avoid hiding critical system state from the user.
5. Test with real browser-relevant payloads, not just static markup inspection.

## Rules

- Show active agent, phase, and failure state clearly.
- Keep chat history and room identity consistent across reloads.
- Prefer simple, robust client-side state over clever abstractions.
