# BLAIQ Multi-Agent Architecture Migration

**Status**: Planning Phase  
**Start Date**: 2026-04-22  
**Target**: Error-free, contract-driven, seamless handoffs

---

## Executive Summary

Move BLAIQ from loosely-coupled agent prompts → contract-driven multi-agent system.

**Four layers:**
1. Workflow layer (predefined routes)
2. Agent harness layer (explicit contracts)
3. Tool harness layer (typed capabilities)
4. Core execution layer (validation + routing)

**Start with**: TextBuddy (simplest end-to-end path)

---

## Current State Gaps

- ❌ Contracts not enforced uniformly
- ❌ Agent I/O shapes not standardized
- ❌ Tools mostly agent-local, not first-class
- ❌ Workflow routes invented per-request
- ❌ Self-correction ad-hoc, not policy-driven

---

## Design Principles

| # | Principle | Why |
|---|-----------|-----|
| 1 | Workflows predefined | No inventing routes per request |
| 2 | Planner selects, not invents | Classify → pick template → map agents |
| 3 | No direct agent-agent talk | Core validates every handoff |
| 4 | Tools do the work | Agents call tools, not fake via prompts |
| 5 | Validation mandatory | Every handoff checked for completeness |

---

## Migration Phases

### Phase 1: Define Contracts (Foundation)
- `AgentHarness` schema
- `ToolHarness` schema
- `WorkflowTemplate` schema
- Add runtime validation
- **Output**: 3 TypedDicts + validation rules

### Phase 2: Canonical Workflows
- Visual Artifact Workflow
- Text Artifact Workflow
- Direct Answer Workflow
- Research Workflow
- Finance Workflow
- **Output**: 5 workflow definitions

### Phase 3: Harnessed Agents
- Convert Strategic Planner
- Convert HITL
- Convert Research
- Convert Content Director
- Convert Visual Designer
- Convert TextBuddy
- Convert Governance
- **Output**: 7 agents with explicit contracts

### Phase 4: Tool Layer
- Group tools by owner agent
- Define tool harness for each
- Register with core
- **Output**: ~30 tools with harnesses

### Phase 5: Message-Based Runtime
- All handoffs use `Msg`
- Tool calls typed
- Tool results validated
- **Output**: Clean middleware

### Phase 6: Self-Correction Policy
- Missing requirement → HITL or re-research
- Weak evidence → narrow re-run
- Invalid output → stricter retry
- Tool failure → safe retry
- **Output**: Retry policies per failure mode

### Phase 7: User-Defined Agents
- Users provide harness (not just prompt)
- Planner validates before routing
- **Output**: Safe custom agent support

---

## TextBuddy: Proof of Concept

**Why first:**
- Small, clear output surface
- Maps to small tool set
- Forces disciplined I/O
- Proves harness model without rendering complexity

**Path:**
1. Define TextBuddy harness
2. Define text artifact workflow
3. Define text tools (email, invoice, memo, proposal, social, summary)
4. Add tool harnessing
5. Refactor TextBuddy to use tools
6. Add governance validation
7. Deploy + test

---

## AgentScope Features to Reuse Now

- `Msg` (universal handoff)
- `Toolkit` (tool registration)
- `ReActAgent` (tool-using agents)
- `structured_model` (typed outputs)
- `PlanNotebook` (agent planning)
- Hooks (validation, logging)
- Middleware (tool policy)
- Sequential + fanout pipelines

---

## Success Criteria

- ✅ Every core agent has harness
- ✅ Every core tool has harness
- ✅ Workflows selected from templates (not invented)
- ✅ Message-based typed handoffs
- ✅ Planner routes custom agents safely
- ✅ Failures trigger explicit recovery
- ✅ Every run is replayable + auditable

---

## Implementation Roadmap

```
Phase 1: Contracts (1-2 weeks)
  └─ AgentHarness + ToolHarness + WorkflowTemplate defs
  └─ Validation middleware
  └─ Registry loader

Phase 2: Workflows (1 week)
  └─ 5 canonical workflows in YAML/JSON

Phase 3: TextBuddy Migration (1-2 weeks)
  └─ TextBuddy harness → structured I/O
  └─ Text tools → harnessed
  └─ End-to-end test

Phase 4: Remaining Agents (2-3 weeks)
  └─ Research + Content Director + Vangogh → harnesses
  └─ Their tools → harnesses
  └─ Integration tests

Phase 5-7: Runtime + Self-Correction + Custom Agents (2 weeks)
  └─ Message enforcement
  └─ Retry policies
  └─ Custom agent validation
```

---

## Files to Create

```
src/contracts/
  harness.py          # AgentHarness, ToolHarness, WorkflowTemplate
  validation.py       # Schema + compatibility checks
  registry.py         # Load + validate harnesses

src/workflows/
  templates.py        # 5 canonical workflows
  loader.py           # Load workflow by ID

src/harnesses/agents/
  strategic_planner.py
  hitl_agent.py
  research_agent.py
  content_director.py
  visual_designer.py
  text_buddy.py
  governance.py

src/harnesses/tools/
  text_tools.py       # email, invoice, memo, etc.
  research_tools.py   # memory, search, etc.
  visual_tools.py     # render, validate, etc.

src/core/
  router.py           # Updated to validate + route
  recovery.py         # Self-correction policies
```

---

## Next: Choose Format

Pick one:

**Option A: Linear Issues** (best for task tracking)
- Each phase → Epic
- Each deliverable → Issue
- Link to code PRs
- Track progress real-time

**Option B: Markdown + Checklist** (best for depth)
- Live in repo
- Version with code
- Link to files as you build
- Task references in journal

**Option C: Both** (recommended)
- Technical depth in Markdown
- Task tracking in Linear
- Journal appends as you close tasks

**Recommend**: Option C + start Phase 1 immediately
