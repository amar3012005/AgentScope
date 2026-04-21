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

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
