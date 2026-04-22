# Phase 1: Contract Definitions

**Objective**: Define the three core schemas. No refactoring yet. Just types.

**Duration**: 1-2 weeks  
**Output**: 3 files + validation + tests

---

## Task Breakdown

### Task 1.1: AgentHarness Schema

**File**: `src/contracts/harness.py`

**Define**:
```python
class AgentHarness(TypedDict):
    agent_id: str                           # e.g., "strategic_planner"
    role: str                               # "classifier and router"
    input_schema: dict                      # JSON schema
    output_schema: dict                     # JSON schema
    required_context: list[str]             # ["user_request", "agent_catalog"]
    optional_context: list[str]             # ["evidence", "memory"]
    allowed_workflows: list[str]            # ["text_artifact", "visual_artifact"]
    allowed_tools: list[str]                # ["memory_recall", "web_search"]
    dependencies: list[str]                 # ["research_agent"]
    retry_policy: RetryPolicy
    failure_modes: dict[str, str]           # "MissingInput" → "ask_hitl"
    approval_gate: Optional[str]            # None or "governance"
    artifact_families: list[str]            # ["email", "memo"]
    timeout_seconds: int                    # 30
    max_retries: int                        # 3
```

**Subtasks**:
- [ ] Define `AgentHarness` TypedDict
- [ ] Define `RetryPolicy` TypedDict
- [ ] Define all failure modes enum
- [ ] Write docstring per field
- [ ] Add 3 examples (planner, research, textbuddy)

**Test**: Load 3 example harnesses, validate schema, pass.

---

### Task 1.2: ToolHarness Schema

**File**: `src/contracts/harness.py` (same file)

**Define**:
```python
class ToolHarness(TypedDict):
    tool_id: str                            # e.g., "email_generator"
    owner_agent: str                        # e.g., "text_buddy"
    purpose: str                            # "generate professional emails"
    input_schema: dict                      # JSON schema
    output_schema: dict                     # JSON schema
    side_effects: list[str]                 # ["updates_memory", "writes_artifact"]
    idempotent: bool                        # True → safe to retry
    allowed_agents: list[str]               # ["text_buddy"]
    allowed_workflows: list[str]            # ["text_artifact_v1"]
    validation_rules: dict[str, str]        # "email_count" → "must_be_1"
    timeout_seconds: int                    # 10
    max_parallel_calls: int                 # 1
    requires_approval: bool                 # False or "governance"
```

**Subtasks**:
- [ ] Define `ToolHarness` TypedDict
- [ ] Define side effects enum
- [ ] Write docstring per field
- [ ] Add 3 examples (email, memo, summary)

**Test**: Load 3 tool harnesses, validate, pass.

---

### Task 1.3: WorkflowTemplate Schema

**File**: `src/contracts/harness.py` (same file)

**Define**:
```python
class Node(TypedDict):
    node_id: str                            # e.g., "research"
    agent_id: str                           # e.g., "research_agent"
    input_from: list[str]                   # ["start"] or ["planner"]
    output_to: list[str]                    # ["hitl", "content_director"]
    required_tools: list[str]               # ["memory_recall", "web_search"]
    approval_gate: Optional[str]            # None or "governance"
    conditional_branches: Optional[dict]    # {"success": "next", "failed": "hitl"}

class WorkflowTemplate(TypedDict):
    workflow_id: str                        # e.g., "text_artifact_v1"
    purpose: str                            # "generate professional text documents"
    entry_conditions: dict[str, str]        # "task_family" → "text_generation"
    nodes: list[Node]                       # Directed acyclic graph
    allowed_agents: list[str]               # ["strategic_planner", "text_buddy"]
    required_handoffs: list[tuple]          # [("planner", "research")]
    approval_gates: list[str]               # ["governance"]
    fallback_branches: dict[str, str]       # "weak_evidence" → "replan"
    version: str                            # "v1"
```

**Subtasks**:
- [ ] Define `Node` TypedDict
- [ ] Define `WorkflowTemplate` TypedDict
- [ ] Write docstring per field
- [ ] Add 5 examples (text, visual, research, direct, finance)

**Test**: Load 5 workflow templates, validate DAG, pass.

---

### Task 1.4: Validation Rules

**File**: `src/contracts/validation.py`

**Implement**:
- [ ] `validate_agent_harness(harness)` → bool + errors
- [ ] `validate_tool_harness(tool)` → bool + errors
- [ ] `validate_workflow_template(workflow)` → bool + errors
- [ ] `check_workflow_dag()` → bool + cycles
- [ ] `check_agent_tool_compatibility(agent, tool)` → bool
- [ ] `check_workflow_agent_compatibility(workflow, agent)` → bool

**Rules to enforce**:
- Agent I/O schema must be valid JSON schema
- Tool must be in agent's `allowed_tools` list
- Agent must be in tool's `allowed_agents` list
- Workflow must form a DAG (no cycles)
- All referenced nodes must exist
- No orphaned agents in workflow
- Timeout must be > 0
- Retry must be >= 0

**Test**: 10 test cases (5 valid, 5 invalid). All pass.

---

### Task 1.5: Registry + Loader

**File**: `src/contracts/registry.py`

**Implement**:
```python
class HarnessRegistry:
    agents: dict[str, AgentHarness]
    tools: dict[str, ToolHarness]
    workflows: dict[str, WorkflowTemplate]
    
    def load_from_yaml(path: str) → None
    def get_agent(agent_id: str) → AgentHarness
    def get_tool(tool_id: str) → ToolHarness
    def get_workflow(workflow_id: str) → WorkflowTemplate
    def validate_all() → list[str]  # errors
```

**Subtasks**:
- [ ] Create `AGENT_REGISTRY.yaml`
- [ ] Create `TOOL_REGISTRY.yaml`
- [ ] Create `WORKFLOW_REGISTRY.yaml`
- [ ] Implement loader
- [ ] Add caching + hot reload

**Test**: Load all 3 registries, validate all, pass.

---

### Task 1.6: Unit Tests

**File**: `tests/test_harnesses.py`

**Coverage**:
- [ ] Load and validate agent harness (5 cases)
- [ ] Load and validate tool harness (5 cases)
- [ ] Load and validate workflow (5 cases)
- [ ] Reject invalid schema (5 cases)
- [ ] Check DAG validation (3 cases)
- [ ] Check compatibility rules (5 cases)

**Target**: 80%+ coverage. All pass.

---

### Task 1.7: Documentation

**File**: `PHASE_1_CONTRACTS.md` (this file, extend)

- [ ] Document each schema with examples
- [ ] Document validation rules
- [ ] Document registry loading
- [ ] Document adding a new agent/tool/workflow

---

## Validation Checklist

Before moving to Phase 2:
- [ ] All 3 schemas compile + pass type check
- [ ] All registries load + validate
- [ ] All validation rules enforced
- [ ] 80%+ test coverage
- [ ] No import errors
- [ ] Documentation complete
- [ ] Journal updated

---

## Success Metrics

- ✅ Can load any harness from YAML without error
- ✅ Invalid harnesses rejected with clear errors
- ✅ Workflow DAG validated (no cycles)
- ✅ Agent-tool compatibility enforced
- ✅ 50 new lines of typed contracts
- ✅ Zero production changes (contracts only)

---

## Next: Phase 2

Once Phase 1 is done:
- Use contract layer to define 5 canonical workflows
- No agent refactoring yet
- Just workflow definitions in YAML
