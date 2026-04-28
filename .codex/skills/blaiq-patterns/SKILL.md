---
name: blaiq-patterns
description: Coding patterns extracted from the BLAIQ / AgentScope-BLAIQ repository
version: 1.0.0
source: local-git-analysis
analyzed_commits: 200
---

# BLAIQ / AgentScope-BLAIQ Patterns

## Commit Conventions

This project uses **conventional commits** with optional scopes:

- `feat(scope):` — new feature, scope is subsystem (e.g. `contracts`, `workstation`)
- `fix:` — bug fix
- `perf:` — performance improvement
- `chore(scope):` — maintenance / housekeeping
- `docs:` — documentation only
- `refactor:` — code restructuring without behaviour change
- `test:` — test additions / fixes

Scope is always lowercase and matches the top-level package or subsystem name.

## Code Architecture

```
AgentScope-BLAIQ/
├── src/agentscope_blaiq/
│   ├── agents/           # Specialist agents (each is a subpackage)
│   │   ├── <agent>/
│   │   │   ├── agent.py       # Agent class (extends BaseAgent)
│   │   │   ├── models.py      # Pydantic I/O models
│   │   │   ├── runtime.py     # Async execution logic
│   │   │   ├── tools/         # Tool functions registered into Toolkit
│   │   │   └── prompts/       # Prompt builders / loaders
│   ├── contracts/        # Shared Pydantic schemas + enforcement rules
│   ├── runtime/          # BaseAgent, registry, config, model resolver
│   ├── workflows/        # Workflow engine + routing
│   ├── persistence/      # SQLite DB, Redis state, repositories
│   ├── streaming/        # SSE streaming layer
│   ├── artifacts/        # Output artifact templates (React+shadcn)
│   ├── mcp_integration/  # MCP client adapters
│   └── app/              # FastAPI app, routes, bootstrap
├── tests/                # pytest tests — one file per feature/agent
├── deployment/           # Dockerfiles, docker-compose, nginx configs
└── journal/              # Phase-based development log
```

## Agent Subpackage Pattern

Every agent follows this canonical structure — no exceptions:

```python
# agent.py
from __future__ import annotations
from pydantic import BaseModel, Field
from agentscope.tool import Toolkit
from agentscope_blaiq.runtime.agent_base import BaseAgent

class MyOutputModel(BaseModel):
    result: str
    issues: list[str] = Field(default_factory=list)

class MyAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="MyAgent",
            role="<role-slug>",
            sys_prompt="...",
            **kwargs,
        )

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        self.register_tool(
            toolkit,
            tool_id="my_tool",
            fn=self._my_tool_impl,
            description="...",
        )
        return toolkit

    async def run(self, ...) -> MyOutputModel:
        await self.log_user("Starting...")
        await self.log("Detail message", kind="status")
        ...
```

Key rules:
- Always `from __future__ import annotations`
- `build_toolkit()` registers tools via `self.register_tool()`
- Use `self.tool_response(...)` to wrap tool return values
- Use `await self.log_user(...)` for user-visible messages
- Use `await self.log(..., kind="status"|"thought"|"decision")` for internal logs
- Async throughout — no sync `run()` methods

## Contracts Layer

All cross-agent data shapes live in `contracts/`. Patterns:

```python
# Always Pydantic BaseModel + Field with defaults
from pydantic import BaseModel, Field

class EvidencePack(BaseModel):
    citations: list[Citation] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)

class WorkflowDispatch(BaseModel):
    agent_id: str
    workflow_id: str
    payload: dict = Field(default_factory=dict)
```

- `dispatch.py` — dispatch validation rules
- `enforcement.py` — runtime enforcement hooks
- `hooks.py` — pre/post execution hooks
- `workflows.py` — canonical workflow templates
- `artifact.py` — `TextArtifact`, `VisualArtifact` output contracts
- `evidence.py` — `EvidencePack`, `Citation` evidence models

## Evidence-First Architecture

Every agent output must be linked to evidence:

```python
# Evidence flows: memory → docs → web
evidence = EvidencePack(citations=[...])
# Pass to governance for validation
report = await governance.review(artifact, evidence)
assert report.approved
```

Governance agent only approves artifacts with evidence linked to citations.

## Testing Patterns

- Test files in `AgentScope-BLAIQ/tests/`
- Naming: `test_<feature_or_agent>.py`
- `conftest.py` for shared fixtures
- Every agent has its own test file
- Contracts + dispatch + enforcement have dedicated test files
- E2E workflow tests: `test_e2e_workflow.py`, `test_e2e_contracts.py`

```bash
# Run tests from AgentScope-BLAIQ/
cd AgentScope-BLAIQ && uv run pytest tests/ -x
```

## Workflows

### Adding a New Agent

1. Create `src/agentscope_blaiq/agents/<name>/` subpackage
2. Implement `agent.py` (extends `BaseAgent`), `models.py`, `runtime.py`, `tools/`, `prompts/`
3. Add compat shim: `agents/<name>.py` → `from agents.<name>.agent import <Name>Agent`
4. Register in `agents/__init__.py` — lazy load via `_LAZY_EXPORTS`
5. Wire into `runtime/registry.py`
6. Add test file `tests/test_<name>.py`
7. Journal the phase in `journal/journal.md`

### Adding a New Contract

1. Create `contracts/<name>.py` with Pydantic models
2. Export from `contracts/__init__.py`
3. Add validation/enforcement in `contracts/enforcement.py` if needed
4. Add tests in `tests/test_contracts.py` or new `tests/test_<name>.py`

### Phase-Based Development

Features land in numbered phases. Each phase:
1. Implement in commits with `feat(<scope>): Phase N ...`
2. Add journal entry to `journal/journal.md`
3. Update `ARCHITECTURE.md` if contracts or routing change

## Deployment

- Dev: `deployment/docker-compose.dev.yml`
- Prod (Coolify): `deployment/docker-compose.coolify.yml`
- Env vars in `deployment/.env.example` — copy to `.env`, never commit secrets
- Frontend builds via Node.js in `deployment/Dockerfile.frontend`
- Python service in `deployment/Dockerfile`

## Model Routing

- All LLM calls via `runtime/model_resolver.py`
- Models configured via env vars (e.g. `LITELLM_PLANNER_MODEL`)
- Use full model names + `custom_llm_provider="openai"` when routing through BLAIQ proxy
- `acompletion()` for async LLM calls in agents

## Persistence

- SQLite via `persistence/database.py` + `persistence/repositories.py`
- Redis for ephemeral state via `persistence/redis_state.py`
- Schema migrations in `persistence/migrations.py` — always backward-compatible
- Seed data in `persistence/seed.py`
