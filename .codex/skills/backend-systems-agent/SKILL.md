---
name: backend-systems-agent
description: Use when implementing or modifying APIs, orchestration services, GraphRAG, tenant routing, auth, persistence, streaming backends, or service-to-service contracts in the BLAIQ backend.
---

# Backend Systems Agent

Use this skill for server-side logic and internal agent integration.

## Responsibilities

- FastAPI endpoints
- orchestrator logic
- GraphRAG and retrieval flows
- tenant-aware routing
- memory/session handling
- REST and WebSocket service contracts
- validation, logging, and backend state machines

## Workflow

1. Trace the request path end to end before changing code.
2. Preserve contract compatibility unless the user asked for a breaking change.
3. Make tenant, session, and agent-routing behavior explicit in payloads and logs.
4. Prefer deterministic interfaces over hidden implicit behavior.
5. Verify with syntax checks, targeted requests, and container/runtime logs.

## Rules

- Keep agent payloads explicit.
- Prefer typed request models.
- Log routing, failures, and state transitions clearly.
- Design for future sub-agents instead of hardcoding one-off behavior.
