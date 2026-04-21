# BLAIQ Pipeline Architecture

This is the canonical architecture document for the BLAIQ orchestration pipeline.

It explains how a user request moves through:
- browser session state
- CORE routing and orchestration
- GraphRAG retrieval
- HITL clarification
- Vangogh rendering
- governance evaluation
- preview delivery back to the browser

The goal is not just correctness. The goal is a pipeline that is:
- legible to operators
- durable across long-lived sessions
- progressive in the UI
- tenant-safe
- template-driven for content g
_resource generationeneration
- observable end to end

---

## 1. System Shape

```
Browser
  └─ BLAIQ React app
       ├─ localStorage session + message history
       ├─ chat thread
       ├─ HITL dropup
       ├─ live plan / agents / schema / governance rails
       └─ preview rail

CORE
  └─ orchestrator_api.py
       ├─ agent registry + liveness
       ├─ strategy routing
       ├─ SSE event streaming
       ├─ Temporal / LangGraph dispatch
       └─ response assembly

Retrieval
  └─ blaiq-graph-rag
       ├─ Qdrant vector search
       ├─ Neo4j graph traversal
       ├─ keyword fallback
       ├─ planner
       └─ answer synthesis

Content
  └─ blaiq-content-agent
       ├─ template engine
       ├─ section schemas
       ├─ Brand DNA
       ├─ progressive rendering
       └─ final artifact composition

Runtime
  └─ Docker Compose / agent network / Redis / Temporal / PostgreSQL / Neo4j / Qdrant
```

---

## 2. Design Principles

1. Chat is the primary surface.
2. CORE is the operator brain, not a hidden transport layer.
3. Preview is progressive, not “final blob only.”
4. HITL is inline and sequential, not a modal interruption.
5. GraphRAG handles textual evidence and retrieval-heavy analysis.
6. Content generation is template-driven and Brand DNA aware.
7. Session continuity lives in the browser and is explicitly sent to CORE.
8. Everything important is observable in logs, timeline, and live agent state.

---

## 3. Request Lifecycle

### 3.1 User submits a request

The browser stores:
- `session_id`
- `thread_id`
- message history
- workflow mode
- current route state
- preview fragments

The browser sends the current turn to CORE together with browser-held conversation history.

Primary frontend files:
- `frontend/Da-vinci/src/components/hivemind/app/shared/blaiq-workspace-context.jsx`
- `frontend/Da-vinci/src/components/hivemind/app/shared/blaiq-client.js`

### 3.2 CORE receives and routes

CORE:
- classifies the request
- probes live agents
- builds a strategy plan
- decides the primary agent and helper agents
- starts streaming orchestration events

Core source:
- `src/orchestrator/orchestrator_api.py`

### 3.3 Retrieval path

For retrieval-heavy tasks, CORE routes to GraphRAG.

GraphRAG flow:
- planner runs first
- query is expanded
- vector search runs against Qdrant
- keyword fallback runs when needed
- results are fused and synthesized
- final answer is produced by the final model

By default in the current deployment, Neo4j graph traversal is disabled for the fast path. The system runs vector + keyword retrieval only unless `GRAPH_SEARCH_ENABLED=true` is explicitly set.

GraphRAG source:
- `src/retriever/graphrag_retriever.py`
- `src/retriever/graphrag_retriever_async_snippet.py` was removed
- `src/retriever/retriever_api_optimized.py`

### 3.4 Content / creation path

For content workflows, CORE routes to the content agent.

Content flow:
- strategist decides the route
- GraphRAG gathers evidence
- content director creates a page-by-page rendering plan
- if needed, HITL asks the operator for clarification
- first page can be gated for operator approval (continue/cancel)
- content agent renders page-by-page / section-by-section
- preview updates progressively
- governance validates the artifact
- final output is handed back

Content source:
- `src/agents/content_creator/agent.py`
- `src/agents/content_creator/template_engine.py`
- `src/agents/content_creator/section_generator.py`
- `src/agents/content_creator/templates/`

### 3.5 HITL path

HITL is triggered only when the routed workflow requires it.

Behavior:
- questions appear one at a time
- the composer expands upward
- answers are written to browser state
- submit resumes the workflow
- rendering continues from the clarified state
- content agent emits a `post_hitl_search_prompt_template` so CORE can run a targeted post-HITL evidence refresh
- page-review HITL (`hitl_node=content_page_review`) resumes directly to content without GraphRAG refresh

The browser should never treat HITL as a page takeover.

### 3.6 Preview and render path

Rendering is progressive:
- `rendering_started`
- `section_started`
- `section_ready`
- `artifact_composed`
- `artifact_ready`

The browser should accumulate fragments and render them into the preview rail as they arrive.

### 3.7 Governance and delivery

Governance checks:
- schema correctness
- policy / brand rules
- output readiness

Final delivery happens only after governance or retrieval completion.

---

## 4. Event Contract

These are the meaningful workflow events the UI should understand:

| Event | Meaning |
|---|---|
| `wf_submit_received` | New request entered CORE |
| `wf_routing_decision` | Strategist decided the route |
| `evidence_summary` | GraphRAG produced a usable evidence summary |
| `evidence_refreshed` | GraphRAG re-ran after HITL |
| `hitl_required` | User clarification is needed |
| `wf_hitl_blocked` | Workflow is paused for HITL |
| `rendering_started` | Vangogh started artifact assembly |
| `section_started` | A section entered rendering |
| `section_ready` | A section fragment is ready to preview |
| `artifact_composed` | Final artifact body assembled |
| `artifact_ready` | Artifact is ready for display/export |
| `governance` | Validation completed |

Backend:
- `src/orchestrator/orchestrator_api.py`
- `src/orchestrator/temporal_worker.py`

Frontend:
- `frontend/Da-vinci/src/components/hivemind/app/shared/blaiq-workspace-context.jsx`
- `frontend/Da-vinci/src/components/hivemind/app/pages/Chat.jsx`

---

## 5. Live Agent Model

The UI should show two distinct things:

1. Live participants
2. Current executing stage

Live participants are persistent actors:
- Core
- Strategist
- GraphRAG
- Content Agent
- Vangogh
- Governance

Current stage is transient:
- routing
- evidence
- HITL
- rendering
- governance

Do not collapse both into a single label.

The live registry is exposed by:
- `GET /agents/live`

The browser consumes this in:
- `frontend/Da-vinci/src/components/hivemind/app/pages/AgentSwarm.jsx`

---

## 6. Model Routing

Current practical routing:

- **Graph search / planning / retrieval helpers**
  - `gemini-2.5-pro`
- **Strategic final reasoning**
  - `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`
- **Content rendering final response**
  - `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`

Rule of thumb:
- use the faster model for search/planning support
- use Claude Sonnet for the final strategic response and final synthesis
- keep the content agent template-driven rather than freeform HTML-only

Config sources:
- `.env`
- `docker-compose.agentic.yml`
- `docker-compose.optimized.yml`
- `docker-compose.coolify.yml`

---

## 7. Content Templates and Brand DNA

Artifact generation must be template-driven.

Structure:
- artifact shell
- section schemas
- section templates
- reusable blueprints (pre-qualified structure + style contracts)
- Brand DNA tokens
- final render assembly

Primary paths:
- `src/agents/content_creator/templates/base.html.j2`
- `src/agents/content_creator/templates/artifacts/pitch_deck.html.j2`
- `src/agents/content_creator/templates/artifacts/poster.html.j2`
- `src/agents/content_creator/templates/sections/`
- `src/agents/content_creator/blueprints/specs/`
- `brand_dna/davinci_ai.json`

Brand DNA should control:
- background
- surface
- border
- text
- accent
- shadow
- spacing intensity
- motif / tone

The renderer should not hardcode a white canvas unless the tenant DNA explicitly asks for it.

---

## 8. Browser State Rules

Browser state is the source of truth for the current session.

Persist in `localStorage`:
- session id
- thread id
- chat history
- workflow mode
- preview fragments
- timeline
- active route

The browser should send:
- current user turn
- full or recent conversation history
- session identifiers

This avoids dependence on server cache for long-lived conversations.

Frontend implementation:
- `frontend/Da-vinci/src/components/hivemind/app/shared/blaiq-workspace-context.jsx`

---

## 9. Reliability and Failure Modes

### 9.1 GraphRAG slow path

Symptoms:
- graph search timeouts
- planner empty output
- fallback to full search
- long answer generation time

Mitigations:
- shorter graph timeout
- graceful fallback to vector/keyword retrieval
- planner output normalization
- disable cache where stale results are risky

### 9.2 HITL not appearing

Symptoms:
- content workflow should ask questions but does not

Mitigation:
- derive `content_requires_hitl` from the routed plan, not only raw query text
- propagate that flag into Temporal and LangGraph initial state

### 9.3 Preview shows raw code or a blank shell

Symptoms:
- HTML is shown as text
- preview rail is black/empty

Mitigation:
- normalize escaped HTML
- strip code fences
- render section fragments progressively
- show a loading canvas until the first fragment arrives

### 9.4 ASGI stream completion errors

Symptoms:
- `ASGI callable returned without completing response`

Mitigation:
- handle cancellation cleanly in stream generators
- make sure final events and `[DONE]` are emitted
- avoid leaving the connection half-open on errors

---

## 10. Services and Ports

| Service | Purpose | Typical Port |
|---|---|---|
| `blaiq-core` | Orchestrator / API gateway | `6080` |
| `blaiq-graph-rag` | Retrieval and evidence | `6001` |
| `blaiq-content-agent` | Rendering and artifact creation | `6003` |
| `blaiq-echo-agent` | Utility / echo / fallback | `6002` |
| `blaiq-redis` | Session / cache / workflow support | `6379` |
| `blaiq-temporal` | Workflow engine | `7233` |
| `blaiq-temporal-db` | Temporal persistence | `5432` |
| `hivemind-qdrant` | Vector DB | `6333` |
| `neo4j.api.blaiq.ai` | Graph DB | `7687/7689` |

Useful endpoints:
- `GET /agents/live`
- `POST /orchestrate`
- `POST /query/graphrag`
- `POST /query/graphrag/stream`
- `GET /healthz` on GraphRAG

---

## 11. Recommended Runtime Sequence

1. Browser submits a request with session history.
2. CORE creates or resumes the workflow.
3. Strategist decides route and live participants.
4. GraphRAG retrieves evidence if needed.
5. HITL opens only if clarification is required.
6. Content agent renders section by section.
7. Browser preview updates on each fragment.
8. Governance validates output.
9. Final response is delivered.

If the request is retrieval-only, steps 5-8 are skipped.

---

## 12. What To Edit When Something Breaks

| Problem | Primary file |
|---|---|
| Routing is wrong | `src/orchestrator/orchestrator_api.py` |
| HITL never appears | `src/orchestrator/temporal_worker.py` |
| GraphRAG is slow or empty | `src/retriever/graphrag_retriever.py` |
| Preview is broken | `frontend/Da-vinci/src/components/hivemind/app/shared/blaiq-workspace-context.jsx` |
| Live agents are missing | `src/orchestrator/orchestrator_api.py` + `frontend/Da-vinci/src/components/hivemind/app/pages/AgentSwarm.jsx` |
| Artifact HTML is plain text | `src/agents/content_creator/template_engine.py` and `src/agents/content_creator/templates/` |
| Brand styling is wrong | `brand_dna/davinci_ai.json` and base templates |

---

## 13. Short Version

The BLAIQ pipeline is:

**browser history + session state → CORE routing → GraphRAG evidence → HITL if needed → Vangogh rendering → governance → progressive preview / final answer**

That is the system. Everything else is implementation detail.
