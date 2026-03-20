---
name: platform-devops-agent
description: Use when working on Docker, Docker Compose, service discovery, env propagation, runtime networking, deployment configuration, health checks, logging, or enterprise-scale agent platform operations.
---

# Platform DevOps Agent

Use this skill for containerized runtime and deployment concerns.

## Responsibilities

- Dockerfiles and Compose
- service ports and networking
- env propagation and secrets handling
- health checks and startup ordering
- observability and operational logging
- deployment readiness for multi-agent systems

## Workflow

1. Make runtime dependencies explicit in Compose.
2. Ensure envs required for routing and tenancy are visible inside the right containers.
3. Prefer safe browser-accessible ports for user-facing services.
4. Validate with `docker compose config`, rebuilds, health checks, and logs.
5. Optimize for adding future agents without rewiring the platform each time.

## Rules

- Keep container networking predictable.
- Avoid hidden local-only assumptions.
- Expose operational failure modes clearly in logs.
