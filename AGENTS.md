# AGENTS.md

## Default Agent Team

For work inside `/Users/amar/blaiq`, use this four-agent team by default unless the user explicitly asks otherwise:

1. `agent-strategist`
2. `backend-systems-agent`
3. `frontend-experience-agent`
4. `platform-devops-agent`

## How To Use Them

- Start with `agent-strategist` to classify the task, decide ownership, and identify coordination points.
- Use `backend-systems-agent` for APIs, orchestration, retrieval, memory, auth, and service contracts.
- Use `frontend-experience-agent` for chat UI, streaming UX, agent state displays, and interaction flows.
- Use `platform-devops-agent` for Docker, Compose, networking, envs, deployment, runtime health, and scaling.

## Team Contract

- Treat the four agents as a standing team for this repository.
- For cross-cutting tasks, combine them instead of handling work as a single undifferentiated agent.
- Prefer explicit ownership:
  - routing and decomposition -> `agent-strategist`
  - server and orchestration logic -> `backend-systems-agent`
  - browser and user-facing interaction -> `frontend-experience-agent`
  - containers and runtime environment -> `platform-devops-agent`

## Skill Paths

- `/Users/amar/blaiq/.codex/skills/agent-strategist/SKILL.md`
- `/Users/amar/blaiq/.codex/skills/backend-systems-agent/SKILL.md`
- `/Users/amar/blaiq/.codex/skills/frontend-experience-agent/SKILL.md`
- `/Users/amar/blaiq/.codex/skills/platform-devops-agent/SKILL.md`
