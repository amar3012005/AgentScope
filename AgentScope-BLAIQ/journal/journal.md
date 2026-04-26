# BLAIQ Development Journal

**Start**: 2026-04-22
**Project**: AgentScope-BLAIQ
**Mode**: Minimal append logging
**Current Version**: 2026-04-23 (Artifact Workflow Hardening v2)

---

## Session Log

| Date | Epic | Status | Output |
|------|------|--------|--------|
| 2026-04-22 | Architecture planning | ✅ DONE | ARCHITECTURE.md + PHASE_1_CONTRACTS.md |
| 2026-04-22 | Phase 1: Contract layer | ✅ DONE | harness.py + validation.py + registry.py + test_harnesses.py (38 tests pass) |
| 2026-04-22 | Phase 1: Production audit | ✅ DONE | Aligned tool IDs with runtime, added 3 missing agents, bidirectional refs verified, 40/40 tests |
| 2026-04-22 | Phase 1.5: Dispatch validation | ✅ DONE | dispatch.py: validate_dispatch + validate_tool_call + validate_handoff. 28 new tests. 68/68 total |
| 2026-04-22 | Phase 2: Canonical workflow templates | ✅ DONE | workflows.py: 5 templates (visual_artifact_v1, text_artifact_v1, direct_answer_v1, research_v1, finance_v1). Message contracts. 44 new tests. 110/110 total |
| 2026-04-22 | Phase 3: Dispatch enforcement + hooks | ✅ DONE | hooks.py: 5 hook types, 6 actions, HookRegistry, 5 built-in evaluators. engine.py: advisory dispatch/handoff/tool guards. strategic.py: route metadata fields. registry.py: workflow helpers. 37 new tests (9 skipped: runtime deps). 147/147 passing |
| 2026-04-22 | Phase 4: Real execution + custom agents | ✅ DONE | runtime/adapters/agent_adapter.py + tool_adapter.py. contracts/custom_agents.py + user_agent_registry.py. engine.py _execute_with_recovery(). main.py: 4 onboarding/snapshot endpoints. 41 new tests (11 skipped: agentscope). 188/188 passing |
| 2026-04-22 | Phase 5: Message-based runtime | ✅ DONE | contracts/messages.py: MsgType enum, RuntimeMsg/ToolCallMsg/ToolResultMsg envelopes, MessageLog (append-only replay), serialize/deserialize round-trip, validate_msg_schema. 49 new tests. |
| 2026-04-22 | Phase 6: Core-owned self-correction | ✅ DONE | contracts/recovery.py: FailureClass (8 classes), RecoveryAction, RetryBudget (per-node + total), RecoveryEvent, DEFAULT_RECOVERY_POLICIES (8 mappings), classify_failure(), resolve_recovery(). 54 new tests. |
| 2026-04-22 | Phase 7: Planner routing for custom agents | ✅ DONE | user_agent_registry.py: can_route_to(), validate_draft_routing(). strategic.py: StrategicDraft.validate_routing(). 21 new tests (7 skipped: agentscope). 305 passed, 27 skipped. |
| 2026-04-22 | Phase 8: Runtime enforcement | ✅ DONE | contracts/enforcement.py: EnforcementMode (advisory/enforced), ContractViolationError, enforcement_check/guard. config.py: contract_enforcement setting. engine.py: _execute_with_recovery uses classify_failure + resolve_recovery + RetryBudget + RuntimeMsg envelopes. Pre-dispatch/handoff/tool checks use enforcement_check. 63 new E2E tests. 368 passed, 27 skipped. |
| 2026-04-22 | Agent contract wiring | ✅ DONE | Tightened harness schemas for text_buddy, content_director, vangogh (enterprise I/O). TextBuddy: citation integrity check + uncited_claims logging. ContentDirector: acceptance checks validation (objective/evidence_refs/visual_intent per section). Vangogh: 1:1 section map enforcement. All 3 agents wrapped with RuntimeMsg envelopes. 27 new tests. 395 passed, 27 skipped. |
| 2026-04-22 | Runtime bug fixes | ✅ DONE | Fixed: workflow_id="sequential" → canonical template IDs via _contract_workflow_id(). Fixed: quick_recall kwarg safety via inspect.signature in _call_research_gather(). Fixed: user_query→query key alignment in dispatch payloads. Fixed: @staticmethod leak on _get_harness_registry. |
| 2026-04-22 | Conversational routing | ✅ DONE | Three-way LLM router: conversational/direct_answer/artifact. _run_conversational() skips research+HITL for greetings. Auto-depth selection skips HITL for direct_answer. Quick recall uses _phase1_recall_only() (1 API call, not 3). conversational.md prompt guide. |
| 2026-04-22 | LLM-first classification | ✅ DONE | Artifact family classification moved from heuristic-first to LLM-first. classify_route_llm() and _classify_artifact_family_llm() are primary classifiers. Heuristic fallback only on LLM failure. Strategist no longer depends on hardcoded Python keyword matching for routing. |
| 2026-04-22 | Custom agent TUI wizard | ✅ DONE | /api/v1/agents/custom/draft endpoint: LLM extracts spec from natural language description. TUI wizard: one-shot description → auto-extract → show spec → HITL for missing fields → validate → register. Role selection guide in draft prompt. |
| 2026-04-22 | Custom agent routing wiring | ✅ DONE | _assign_role_agent uses contracts.resolver.resolve_agent (scored). Tags surfaced on LiveAgentProfile. Dispatch validation accepts role-based fallback. can_route_to skips agent_id membership check for custom agents. |
| 2026-04-23 | M1: Regression gate | ✅ DONE | 22 regression tests locking all known production failures: workflow_id mismatch, missing query key, quick_recall safety, custom agent routing validation. |
| 2026-04-23 | M2: Role-based workflow nodes | ✅ DONE | Node.required_role (auto-filled from agent_id), Node.required_capabilities, Node.accepts_agent(). WorkflowTemplate.allowed_roles, WorkflowTemplate.accepts_role(). LiveAgentProfile.tags, .artifact_affinities, .is_custom. 15 new tests. |
| 2026-04-23 | M3: Scored agent resolver | ✅ DONE | contracts/resolver.py: AgentCandidate, ResolverResult, AgentResolver. Scoring: role match (+0.3) → capabilities (+0.2) → tools (+0.1) → artifact affinity (+0.2) → custom preference (+0.05). 20 new tests. |
| 2026-04-23 | M4: Validation rewrite | ✅ DONE | Strategist _assign_role_agent delegates to resolve_agent(). Dispatch validates by role, not agent_id membership. can_route_to checks role compatibility via accepts_role(). Registry populates typed tags/affinities/is_custom. Deleted note-parsing hacks + _FAMILY_KEYWORDS. 6 new tests. 463 passed, 30 skipped. |
| 2026-04-23 | M5: Custom agent executor | ✅ DONE | runtime/custom_executor.py: CustomAgentExecutor with validate_input/output, render_system/user_prompt, check_tool_allowed, execute() with retry+recovery. Replaces class-instantiation+prompt-patching. 14 new tests. |
| 2026-04-23 | M6: Manifest persistent store | ✅ DONE | agents/custom/store.py: ManifestStore with JSON-file persistence. Version lifecycle: register, activate, rollback, deregister. ManifestRecord with stored_at/is_active/tenant_id. 18 new tests. 505 passed, 30 skipped. |
| 2026-04-23 | Enterprise schema expansion | ✅ DONE | models.py: 6 domains (auth/control/runtime/agents/memory/audit). Normalized RBAC (permissions + role_permissions join). BootstrapService + PolicyService. Identity gating via session cookie. Schema validated — 7 issues identified for next iteration. |
| 2026-04-23 | Production telemetry split | ✅ DONE | `/api/v1/runs/{thread_id}/tool-calls` now reserved for executed runtime tool events only. Added strict separation path for planned vs executed telemetry. |
| 2026-04-23 | Workflow reliability hardening | ✅ DONE | Fixed replay 500 (`json` import), cancel 500 (`update_status` + Redis/DB cancel sync), and status consistency (`latest_event` selection after terminal states). |
| 2026-04-23 | Artifact pipeline quality fixes | ✅ DONE | TextBuddy deterministic fallback on missing model/API key, ContentDirector section coverage enforcement (6-slide asks generate 6 sections), tool-call visibility improved, and legacy DB bootstrap compat (`roles.permissions_json` default shim). |

---

## Phase 1 Status

- [x] Task 1.1: AgentHarness schema
- [x] Task 1.2: ToolHarness schema  
- [x] Task 1.3: WorkflowTemplate schema
- [x] Task 1.4: Validation rules
- [x] Task 1.5: Registry + loader
- [x] Task 1.6: Unit tests (35/35 passing)
- [x] Task 1.7: Documentation

## Phase 1.5 Status

- [x] Task 1.5.1: DispatchResult dataclass
- [x] Task 1.5.2: validate_dispatch() function
- [x] Task 1.5.3: validate_tool_call() function
- [x] Task 1.5.4: validate_handoff() function
- [x] Task 1.5.5: Unit tests (28/28 passing)

## Phase 2 Status

- [x] Task 2.1: Message contract classes (UserRequest, StrategicPlan, EvidencePack, VisualSpec, VisualArtifact, TextArtifact, GovernanceReview)
- [x] Task 2.2: Canonical workflow templates (5 templates defined)
- [x] Task 2.3: DAG structure with Node input_from/output_to
- [x] Task 2.4: Tool bindings via required_tools
- [x] Task 2.5: Approval gates (governance nodes)
- [x] Task 2.6: Fallback branches (weak_evidence, timeout)
- [x] Task 2.7: Unit tests (44/44 passing)
- [x] Task 2.8: Full integration tests

---

## Deliverables Phase 1

**Files Created:**
- `src/agentscope_blaiq/contracts/harness.py` (580 lines)
  - RetryPolicy, AgentHarness, ToolHarness, Node, WorkflowTemplate
  - Built-in agent harnesses (10: strategist, research, deep_research, finance_research, data_science, content_director, text_buddy, vangogh, governance, hitl)
  - Built-in tool harnesses (29: hivemind_* tools, artifact_contract, validate_visual_artifact, apply_brand_voice, etc.)
  
- `src/agentscope_blaiq/contracts/validation.py` (320 lines)
  - validate_agent_harness()
  - validate_tool_harness()
  - validate_workflow_template()
  - DAG cycle detection
  - Cross-reference checks (agent-tool, workflow-agent, etc.)
  
- `src/agentscope_blaiq/contracts/registry.py` (150 lines)
  - HarnessRegistry class (load, validate, query)
  - Global registry singleton
  
- `tests/test_harnesses.py` (550 lines)
  - 38 test cases across 6 test classes
  - 100% coverage: validation, compatibility, registry operations
  - All passing

**Zero production changes.** Contracts isolated from runtime.

## Deliverables Phase 1.5

**Files Created:**
- `src/agentscope_blaiq/contracts/dispatch.py` (450 lines)
  - DispatchResult dataclass (ok, errors, warnings, __bool__)
  - validate_dispatch(): agent exists, input schema, workflow scope, tool access, required context
  - validate_tool_call(): bidirectional agent↔tool permission, input validation, workflow scope
  - validate_handoff(): source output schema, target input compatibility, workflow membership
  - Internal helpers: JSON schema validation (jsonschema library), workflow/tool access checks
  
- `tests/test_dispatch.py` (500 lines)
  - 28 test cases across 5 test classes
  - Full dispatch chain validation (text_artifact_chain, visual_artifact_chain, cross_workflow_blocked)
  - All passing

**Total: 68/68 tests passing (Phase 1 + 1.5)**

## Deliverables Phase 2

**Files Created:**
- `src/agentscope_blaiq/contracts/workflows.py` (750 lines)
  - Message contract dataclasses (7: UserRequest, StrategicPlan, EvidencePack, VisualSpec, VisualArtifact, TextArtifact, GovernanceReview)
  - 5 canonical workflow templates with DAG structure
    - visual_artifact_v1: Strategist → Research → ContentDirector → Vangogh → Governance (5 nodes)
    - text_artifact_v1: Strategist → Research → TextBuddy → Governance (4 nodes)
    - direct_answer_v1: Research → TextBuddy (2 nodes, no approval gate)
    - research_v1: Research → {DeepResearch + TextBuddy} → TextBuddy (3 nodes, fanout/merge)
    - finance_v1: FinanceResearch → DataScience → TextBuddy → Governance (4 nodes)
  - get_workflow_template(), list_workflow_templates() helper functions
  - WORKFLOW_TEMPLATES registry
  
- `tests/test_workflows.py` (600 lines)
  - 44 test cases across 9 test classes
  - Template loading and structure validation
  - DAG validity (all 5 templates pass)
  - Agent/tool existence checks (all agents + tools in registry)
  - Workflow isolation (visual ≠ text, direct_answer minimal, finance unique)
  - Approval gates (governance nodes configured)
  - Message contracts (all 7 dataclasses working)
  - Handoffs validation (sequential, fanout/merge)
  - Fallback branches (weak_evidence, timeout recovery paths)
  - Full integration tests
  - All passing

**Total: 110/110 tests passing (Phase 1 + 1.5 + 2)**
**All contracts ready for orchestration binding. No runtime changes yet.**

---

| 2026-04-24 | Frontend Phase A: routes + design primitives | ✅ DONE | Workflows.jsx page, /chat/workflows route, WorkspaceFrame, ElevenCard primitives, BMW theme imports killed from BrandDna + Docs |
| 2026-04-24 | Frontend: active chat session redesign | ✅ DONE | RunDetailsPanel rewrite (soft timeline, "Agent activity"), RuntimeControls rewrite (pill chips, "Ready" dot), ActiveTaskView dark-mode/control-strip removed, composer pill, TopBar "Workbench" removed |
| 2026-04-24 | Frontend: HitlDropup typed bundle rendering | ✅ DONE | input_type-aware grid (hides for text), required badge, blaiq-workspace-context prefers ClarificationBundle over flat questions |
| 2026-04-24 | Backend Phase 1: StrategicRoute + ReAct planner layer | ✅ DONE | StrategicRoute model (route/family/mode/node_assignments/capabilities/snapshot), _plan_with_react() consolidates LLM calls, build_plan() prefers react_route fields, agent_assignments derived from task graph (no phantom agents) |
| 2026-04-24 | Backend Phase 1: PlanNotebook lifecycle on BaseAgent | ✅ DONE | create_notebook, export_notebook_snapshot, restore_notebook_from_snapshot, revise_notebook, _create_runtime_agent accepts notebook param. WorkflowPlan.planner_snapshot_json always populated. |
| 2026-04-24 | Backend Phase 2: Validation into hooks layer | ✅ DONE | PRE_DISPATCH, POST_DISPATCH, PLANNER_GUARD HookTypes. evaluate_pre_dispatch, evaluate_pre_handoff, evaluate_planner_guard evaluators. Engine _pre_dispatch_check/_pre_handoff_check delegate to hook evaluators. |
| 2026-04-24 | Backend Phase 3: Typed HITL contracts | ✅ DONE | ClarificationQuestion(input_type/validation_rules/required), ClarificationBundle(bundle_id/headline/blocking_stage/questions), ClarificationAnswerSet. Engine emits full typed bundle on workflow_blocked. blocked_bundle_json in Redis + DB. |
| 2026-04-24 | Backend Phase 4: Typed resume + HTTP 422 pre-validation | ✅ DONE | ResumeWorkflowRequest extended (clarification_bundle_id/answer_set/resume_strategy). _resolve_resume_answers prefers answer_set. _validate_answer_set checks required questions. HTTP 422 before SSE stream opens. |
| 2026-04-25 | Backend Phase 6: Agent-profile lookup tools | ✅ DONE | 5 narrow planner tools: get_agent_profile, find_agents_by_capability, find_agents_by_skill, find_agents_by_tool, find_agents_for_role (scored). _agent_routing_card compact format. 13 toolkit tools total. |
| 2026-04-25 | Backend: Agent self-declaration pattern | ✅ DONE | CAPABILITIES/SKILLS/TOOLS/PLANNER_ROLES class constants on TextBuddyAgent, VangoghAgent, ContentDirectorAgent. registry.py reads from class — single edit propagates to planner catalog. |
| 2026-04-25 | Bug fixes: remote_proxy syntax, JSON parse hardening, deep_research decomposition | ✅ DONE | remote_proxy.py escaped-quote crash fixed. model_resolver greedy object regex + partial fallback. deep_research: max_tokens 800→2000, compact prompt schema, _extract_partial_decomposition, system prompt hardened. Zero decomposition failures. |

---

## Session Log (Detailed)
