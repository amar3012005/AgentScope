# BLAIQ — Session Changelog: 2026-04-24/25

## Summary

This session completed the full AgentScope-native refactor across three layers:
1. **Frontend**: ElevenLabs-style redesign, new Workflows page, active chat session overhaul
2. **Backend contracts**: Typed planner output, typed HITL, typed resume, hooks layer
3. **Agent runtime**: ReAct planner layer, PlanNotebook lifecycle, agent-profile self-declaration

---

## Frontend Changes

### New Pages

**[pages/Workflows.jsx](src/agentscope_blaiq/../../../frontend/src/components/hivemind/app/pages/Workflows.jsx)**
- 5 canonical workflow cards (visual_artifact_v1, text_artifact_v1, research_v1, direct_answer_v1, finance_v1)
- Each shows: purpose, stage pills, agent count, gate count, "Start workflow" button
- Start button calls `createNewSession()` + `setQuery(suggestedPrompt)` → navigates to session
- Route `/chat/workflows` added to App.jsx (was previously dead link from sidebar)

**[shared/ui/WorkspaceFrame.jsx](frontend/src/components/hivemind/app/shared/ui/WorkspaceFrame.jsx)**
- Shared page wrapper: warm `#fafaf9` background, title/subtitle/actions header
- All new pages use this instead of inventing their own layout

**[shared/ui/ElevenCard.jsx](frontend/src/components/hivemind/app/shared/ui/ElevenCard.jsx)**
- Shared card primitive: white background, 20px radius, half-pixel inset border, warm shadow
- `ElevenCardHeader` with icon, title, badge, actions, subtitle slots

### Active Chat Session Redesign

**[shared/run-details-panel.jsx](frontend/src/components/hivemind/app/shared/run-details-panel.jsx)**
- Rewritten: "RUN OBSERVABILITY" → "Agent activity"
- Warm white surface, soft timeline dots (black filled = complete, pulsing = running)
- Empty state: "Waiting for the first step" with soft circle icon
- No uppercase, no dark mode branches

**[shared/runtime-controls.jsx](frontend/src/components/hivemind/app/shared/runtime-controls.jsx)**
- Rewritten: SHOUTY UPPERCASE pill bar → soft white pills
- MODEL / SCOPE as rounded-full chips with hover dropdown
- Emerald dot + "Ready" (sentence case) status indicator

**[pages/Chat.jsx — ActiveTaskView](frontend/src/components/hivemind/app/pages/Chat.jsx)**
- Killed bottom "STANDARD / WORKBENCH / Security: SOC2/HIPAA / Region: EU-WEST-1" strip
- Removed dark mode branches → forced `#fafaf9` warm canvas
- Right rail drag handle softened
- Removed unused `Columns`, `Layout`, `isDayMode`, `layoutMode` vars

**[pages/Chat.jsx — ConversationArea composer](frontend/src/components/hivemind/app/pages/Chat.jsx)**
- Old: rectangular red stop + small arrow button
- New: rounded-full pill, `Ask Anything…` placeholder, black circle submit, black circle stop

**[layout/TopBar.jsx](frontend/src/components/hivemind/app/layout/TopBar.jsx)**
- Removed "Workbench" / Bot icon label
- Warm `#fafaf9/80` backdrop, pill buttons (rounded-full, sentence case)
- Control Plane variant kept with amber warning icon

### HitlDropup Improvements

**[pages/chat/HitlDropup.jsx](frontend/src/components/hivemind/app/pages/chat/HitlDropup.jsx)**
- Hides options grid for `input_type: "text"` questions
- Shows "required" badge when `question.required !== false`
- Label adapts: "Or type your own" (option) vs "Your answer" (text)

**[shared/blaiq-workspace-context.jsx — workflow_blocked handler](frontend/src/components/hivemind/app/shared/blaiq-workspace-context.jsx)**
- Prefers `clarification_bundle` from SSE event when available (Phase 3)
- Falls back to flat `questions` array for legacy sessions
- `hitl` state now carries: `bundleId`, `resumeFromNode`, `blockingStage`
- `normalizeHitlQuestion` passes through `input_type` + `required`

### Cleanup

- Removed `import '../shared/bmw-reference-theme.css'` from `BrandDna.jsx` and `Docs.jsx`
- Sidebar `/chat/workflows` link now live (was navigating to unregistered route)
- `agent_assignments` in `WorkflowPlan` now derived from task graph nodes — no more phantom `vangogh` assignment for email workflows

---

## Backend Contracts

### Phase 1 — Strategist Refactor

**[agents/strategic/agent.py](src/agentscope_blaiq/agents/strategic/agent.py)**

`StrategicRoute` model:
```python
class StrategicRoute(BaseModel):
    route: str                           # conversational | direct_answer | artifact
    artifact_family: ArtifactFamily
    workflow_mode: WorkflowMode
    analysis_mode: AnalysisMode
    required_capabilities: list[str]
    node_assignments: dict[str, str]     # node_id → agent_id
    required_tools_per_node: dict[str, list[str]]
    missing_requirements: list[str]
    reasoning_summary: str
```

`_plan_with_react()` — ReAct planner layer:
- Consolidates route + family + topology + task graph into single typed `StrategicRoute`
- Returns `None` on failure → `build_plan()` falls back to heuristics
- `build_plan()` prefers `react_route` fields over individual LLM calls

`build_plan()` cleanup:
- Removed `_compose_assignments()` call — assignments now derived from task graph nodes directly
- `agent_assignments` always matches `task_graph.nodes` (no phantom agents)

`_agent_routing_card()` helper + 5 new toolkit tools:
- `get_agent_profile(agent_id)` — single profile by name/profile_id
- `find_agents_by_capability(capability)` — filter catalog
- `find_agents_by_skill(skill)` — filter catalog
- `find_agents_by_tool(tool_id)` — filter catalog
- `find_agents_for_role(role, artifact_family)` — score + rank: role match (3pt) + planner_role (2pt) + artifact affinity (1pt) + ready (1pt)

Strategist toolkit now has 13 registered tools total.

### Phase 1 — PlanNotebook Lifecycle

**[runtime/agent_base.py](src/agentscope_blaiq/runtime/agent_base.py)**

New lifecycle methods on `BaseAgent`:
- `create_notebook()` → fresh `PlanNotebook`, stored as `self._notebook`
- `reset_notebook()` → discard + counter reset
- `export_notebook_snapshot()` → `dict | None` (raw internals NOT persisted)
- `restore_notebook_from_snapshot(snapshot)` → rebuild from dict, silently handles corrupt snapshots
- `revise_notebook()` → increment `_notebook_revision`
- `_create_runtime_agent(plan_notebook=None)` → accepts optional notebook, defaults to `self._notebook` or fresh one

**[contracts/workflow.py](src/agentscope_blaiq/contracts/workflow.py)**

`WorkflowPlan.planner_snapshot_json: str | None` — exported notebook snapshot stored in plan JSON.

In `build_plan()`:
- `create_notebook()` called at start of every plan
- Synthetic snapshot built from plan data when notebook has no `current_plan` (Python method path)
- `planner_snapshot_json` always populated (never null)

### Phase 2 — Validation into Hooks

**[contracts/hooks.py](src/agentscope_blaiq/contracts/hooks.py)**

New `HookType` values: `PRE_DISPATCH`, `POST_DISPATCH`, `PLANNER_GUARD`

New evaluators:
- `evaluate_pre_dispatch(ctx, harness_registry)` — wraps `validate_dispatch`, advisory WARN
- `evaluate_pre_handoff(ctx, harness_registry)` — wraps `validate_handoff`, uses `ctx.metadata["to_agent_id"]`
- `evaluate_planner_guard(ctx)` — validates node assignments against known catalog agents; BLOCK on unknown agent, WARN on missing tools

**[workflows/engine.py](src/agentscope_blaiq/workflows/engine.py)**

`_pre_dispatch_check()` + `_pre_handoff_check()` now:
- Build `HookContext` with correct fields
- Delegate to `evaluate_pre_dispatch` / `evaluate_pre_handoff`
- Interpret `HookDecision` via `enforcement_check()`

### Phase 3 — Typed HITL Contracts

**[contracts/workflow.py](src/agentscope_blaiq/contracts/workflow.py)**

```python
class ClarificationQuestion(BaseModel):
    requirement_id: str
    question: str
    why_it_matters: str | None
    answer_hint: str | None
    answer_options: list[str]
    input_type: str = "option"       # option | text | multi_select
    validation_rules: dict
    required: bool = True

class ClarificationBundle(BaseModel):
    bundle_id: str                   # UUID
    headline: str
    intro: str
    blocking_stage: str
    questions: list[ClarificationQuestion]
    expected_answer_schema: dict
    pending_node: str | None
    resume_from_node: str | None
    plan_snapshot: dict | None
    created_at: datetime

class ClarificationAnswerSet(BaseModel):
    bundle_id: str
    answers: dict[str, str]          # requirement_id → answer
    validation_errors: dict[str, str]
    completed: bool = False
```

`ResumeWorkflowRequest` extended:
- `clarification_bundle_id: str | None`
- `answer_set: ClarificationAnswerSet | None`
- `resume_strategy: str = "continue"`  # continue | replan | restart_from_planning

**[persistence/redis_state.py](src/agentscope_blaiq/persistence/redis_state.py)**
- `WorkflowRedisState.blocked_bundle_json: str | None` — persists typed bundle
- `mark_blocked()` accepts `blocked_bundle_json` param

**[persistence/repositories.py](src/agentscope_blaiq/persistence/repositories.py)**
- `update_workflow_snapshot()` accepts `blocked_bundle_json` param, stores in state_payload

**[workflows/engine.py — workflow_blocked emission](src/agentscope_blaiq/workflows/engine.py)**
- Builds `ClarificationBundle` from questions
- SSE event `workflow_blocked` now includes `clarification_bundle` + `clarification_bundle_id`
- `blocked_bundle_json` persisted to Redis and DB

**[agents/clarification.py](src/agentscope_blaiq/agents/clarification.py)**
- `ClarificationQuestion` extended with `input_type`, `validation_rules`, `required`

### Phase 4 — Typed Resume

**[workflows/engine.py — resume](src/agentscope_blaiq/workflows/engine.py)**

`_resolve_resume_answers(request)`:
- Prefers `request.answer_set.answers` over legacy `request.answers`

`_validate_answer_set(request, redis_state)`:
- Loads stored `ClarificationBundle` from `redis_state.blocked_bundle_json`
- Validates required questions are answered
- Returns `list[str]` errors

**[app/main.py — resume endpoint](src/agentscope_blaiq/app/main.py)**
- Pre-validates `answer_set` before opening SSE stream
- Returns HTTP 422 with `{"errors": [...]}` immediately (not buried in SSE)

---

## Agent Profile Self-Declaration

**Pattern:** agent classes now declare their own profile fields. Registry reads from the class — no sync required.

**[agents/text_buddy/agent.py](src/agentscope_blaiq/agents/text_buddy/agent.py)**
```python
class TextBuddyAgent(BaseAgent):
    CAPABILITIES: list[AgentCapability] = [...]  # text_composition, brand_voice_writing, template_formatting
    SKILLS: list[AgentSkill] = [...]
    TOOLS: list[str] = ["apply_brand_voice", "select_template", "format_output"]
    PLANNER_ROLES: list[str] = ["text_buddy"]
```

**[agents/vangogh/agent.py](src/agentscope_blaiq/agents/vangogh/agent.py)**
```python
class VangoghAgent(BaseAgent):
    CAPABILITIES: list[AgentCapability] = [...]  # artifact_layout, html_css_composition
    SKILLS: list[AgentSkill] = [...]
    TOOLS: list[str] = ["artifact_contract"]
    PLANNER_ROLES: list[str] = []
```

**[agents/content_director/agent.py](src/agentscope_blaiq/agents/content_director/agent.py)**
```python
class ContentDirectorAgent(BaseAgent):
    CAPABILITIES: list[AgentCapability] = [...]  # content_distribution, section_planning
    SKILLS: list[AgentSkill] = [...]
    TOOLS: list[str] = ["content_distribution", "section_planning", "template_selection", "render_brief_generation"]
    PLANNER_ROLES: list[str] = ["content_director"]
```

**[runtime/registry.py](src/agentscope_blaiq/runtime/registry.py)** — 3 profiles now read from class:
```python
capabilities=ContentDirectorAgent.CAPABILITIES,
skills=ContentDirectorAgent.SKILLS,
tools=ContentDirectorAgent.TOOLS,
planner_roles=ContentDirectorAgent.PLANNER_ROLES,
```

To add a new capability: edit the agent class only. Propagates to planner catalog on next request.

---

## Bug Fixes

### `remote_proxy.py` — startup crash
- Pre-existing escaped triple-quote syntax errors (`\"\"\"`) caused module import failure
- Fixed by rewriting with clean docstrings

### `model_resolver.py` — JSON parse failures
- Object regex `\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}` only handled 1 nesting level
- Replaced with greedy `\{.*\}` + raw-text fallback + partial JSON attempts

### `deep_research/base.py` — decomposition failures
- `max_tokens=800` too low → JSON truncated, closing `}` missing
- System prompt "Return ONLY valid JSON" ignored by Gemini 2.5 Pro
- Decomposition prompt requested verbose fields (rationale, evidence_type, source_preference) bloating response

Fixes:
- `max_tokens` 800 → 2000
- `_extract_partial_decomposition()` — regex extracts `"question": "..."` from truncated JSON
- `decompose_subtask.md` — compact schema, `question` field only
- All JSON system messages → "MUST start with `{` and end with `}`. Never use ` ```json `"
- Downgraded `logger.warning` → `logger.debug` for raw response logging

**Before:** `Decomposition with plan failed` at every depth, fallback generic questions  
**After:** 3 real LLM subtasks per depth, zero failures

---

## Verified Behavior

```
planning_complete event (email request):
  artifact_family: email
  workflow_mode: sequential
  workflow_template_id: text_artifact_v1
  node_assignments: {research-web: research, research-docs: research, text_buddy: text_buddy, governance: governance}
  agent_assignments: [research-web→research, research-docs→research, text_buddy→text_buddy, governance→governance]
  planner_snapshot_json: {revision: 1, artifact_family: email, node_assignments: {...}, missing_requirements: [...]}

workflow_blocked event:
  clarification_bundle_id: f8fcc2c0-5379-4ee0-a4db-04e8972a99a4
  bundle.headline: "Let's build your BLAIQ enterprise investor pitch — I need a few details"
  bundle.blocking_stage: evidence_informed
  questions: 4 typed questions with input_type: option

deep_research:
  Decomposed into 3 subtasks (depth 0)
  Decomposed into 3 subtasks (depth 1)
  Decomposed into 3 subtasks (depth 2)
  Zero "Decomposition with plan failed" warnings
```

---

## File Index

| File | Change |
|------|--------|
| `frontend/src/App.jsx` | `/chat/workflows` route added |
| `frontend/.../pages/Workflows.jsx` | New page |
| `frontend/.../shared/ui/WorkspaceFrame.jsx` | New primitive |
| `frontend/.../shared/ui/ElevenCard.jsx` | New primitive |
| `frontend/.../shared/run-details-panel.jsx` | Full rewrite |
| `frontend/.../shared/runtime-controls.jsx` | Full rewrite |
| `frontend/.../shared/bolt-style-chat.jsx` | Kimi-style hero + pill composer |
| `frontend/.../layout/TopBar.jsx` | Softened, "Workbench" removed |
| `frontend/.../pages/Chat.jsx` | ActiveTaskView + composer rewrite |
| `frontend/.../pages/chat/HitlDropup.jsx` | input_type rendering + required badge |
| `frontend/.../shared/blaiq-workspace-context.jsx` | ClarificationBundle parsing |
| `frontend/.../pages/BrandDna.jsx` | BMW theme import removed |
| `frontend/.../pages/Docs.jsx` | BMW theme import removed |
| `src/.../contracts/workflow.py` | ClarificationBundle, ClarificationAnswerSet, ClarificationQuestion, ResumeWorkflowRequest extended |
| `src/.../contracts/hooks.py` | PRE_DISPATCH, POST_DISPATCH, PLANNER_GUARD + 3 evaluators |
| `src/.../contracts/__init__.py` | New exports |
| `src/.../agents/strategic/agent.py` | StrategicRoute, _plan_with_react, 5 lookup tools, _agent_routing_card |
| `src/.../agents/strategic/models.py` | StrategicRoute export |
| `src/.../agents/clarification.py` | ClarificationQuestion extended |
| `src/.../agents/text_buddy/agent.py` | CAPABILITIES/SKILLS/TOOLS/PLANNER_ROLES |
| `src/.../agents/vangogh/agent.py` | CAPABILITIES/SKILLS/TOOLS/PLANNER_ROLES |
| `src/.../agents/content_director/agent.py` | CAPABILITIES/SKILLS/TOOLS/PLANNER_ROLES |
| `src/.../agents/remote_proxy.py` | Syntax fix |
| `src/.../runtime/agent_base.py` | PlanNotebook lifecycle methods |
| `src/.../runtime/registry.py` | 3 profiles read from agent class constants |
| `src/.../runtime/model_resolver.py` | JSON parse hardening |
| `src/.../workflows/engine.py` | ClarificationBundle emission, typed resume, hook delegation |
| `src/.../persistence/redis_state.py` | blocked_bundle_json field |
| `src/.../persistence/repositories.py` | blocked_bundle_json persistence |
| `src/.../app/main.py` | HTTP 422 pre-validation on resume |
| `src/.../agents/deep_research/base.py` | Decomposition fixes |
| `src/.../agents/deep_research/prompts/decompose_subtask.md` | Compact prompt |
