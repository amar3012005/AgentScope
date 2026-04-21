# BLAIQ Core — Frontend Expectations

**Version**: 1.0
**Date**: 2026-03-23
**Audience**: Frontend engineers, design system owners, product managers
**Backend Version**: Orchestrator V4 (LangGraph + Temporal)

---

## 1. Purpose

This document defines everything a frontend application must implement to integrate with the BLAIQ Core orchestrator. It covers the API contract, SSE event vocabulary, multi-tenancy isolation, authentication expectations, HITL workflows, artifact rendering, and the UX behaviors required for an enterprise-grade product.

The backend is complete. This document is the handoff specification.

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    FRONTEND APPLICATION                   │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Chat Panel  │  │  Artifact    │  │  Schema Editor │  │
│  │  (SSE stream │  │  Preview     │  │  (side panel)  │  │
│  │   consumer)  │  │  (iframe)    │  │                │  │
│  └──────┬───────┘  └──────────────┘  └────────────────┘  │
│         │                                                │
│  ┌──────┴───────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Execution   │  │  HITL        │  │  Governance    │  │
│  │  Timeline    │  │  Overlay     │  │  Badge / Panel │  │
│  └──────────────┘  └──────────────┘  └────────────────┘  │
└──────────────────────────┬───────────────────────────────┘
                           │ HTTPS + SSE
                           ▼
┌──────────────────────────────────────────────────────────┐
│              BLAIQ CORE ORCHESTRATOR (port 6080)         │
│                                                          │
│  POST /api/v4/orchestrator/submit      → SSE stream      │
│  POST /api/v4/orchestrator/resume      → SSE stream      │
│  GET  /api/v4/orchestrator/status/:id  → JSON            │
│  GET  /api/v4/orchestrator/workflows   → JSON            │
│  POST /api/v4/orchestrator/regenerate  → SSE stream      │
│  GET  /agents                          → JSON            │
│  POST /upload                          → JSON            │
└──────────────────────────────────────────────────────────┘
```

---

## 3. API Contract

### 3.1 Base URL

```
Production:  https://<deployment-domain>
Local dev:   http://localhost:6080
```

All V4 endpoints are prefixed with `/api/v4/orchestrator/`.

### 3.2 Authentication (Required for Production)

The backend currently accepts API keys via three transports (checked in order):

| Transport | Header / Parameter |
|---|---|
| Custom header | `X-API-Key: <key>` |
| Query parameter | `?api_key=<key>` |
| Bearer token | `Authorization: Bearer <key>` |

**Frontend expectation**: Store the API key in a secure, httpOnly cookie or session storage. Never hardcode it. Include the `X-API-Key` header on every request.

**Multi-tenant auth (production)**: The frontend must associate each authenticated user with a `tenant_id`. This tenant_id controls:
- Which Qdrant vector collection is searched
- Which Neo4j graph partition (filter_label) is queried
- Which uploaded documents are visible
- Which workflow history is returned

The backend does NOT enforce tenant isolation at the auth layer today. The frontend MUST NOT allow a user to submit a `tenant_id` they do not own. Production deployments must add middleware that derives `tenant_id` from the authenticated session, not from the request body.

### 3.3 Endpoints

#### POST `/api/v4/orchestrator/submit`

Submits a workflow and returns an SSE stream.

**Request:**
```json
{
  "tenant_id": "acme-corp",
  "user_query": "Create a pitch deck for our Q3 product launch",
  "workflow_mode": "standard",
  "collection_name": "acme_knowledge_base",
  "session_id": "optional-uuid-for-history"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | string | Yes | Identifies the tenant. Controls data isolation. |
| `user_query` | string | Yes | The user's natural language request. Min 1 char. |
| `workflow_mode` | string | No | `"standard"` (default), `"deep_research"`, or `"creative"`. Creative forces content generation even for Q&A queries. |
| `collection_name` | string | No | Overrides the Qdrant collection. Defaults to `tenant_id`. |
| `session_id` | string | No | Groups multiple requests into a conversation session. Auto-generated if omitted. |

**Response**: `Content-Type: text/event-stream` (see Section 4 for event vocabulary).

#### POST `/api/v4/orchestrator/resume`

Resumes a paused (HITL-blocked) workflow with user answers.

**Request:**
```json
{
  "thread_id": "47b20076-24c4-4c52-98ca-7d94de377176",
  "agent_node": "content_node",
  "answers": {
    "q1": "Enterprise CIOs and VP Engineering",
    "q2": "Modern minimal with dark premium aesthetic",
    "q3": "Pitch deck (7 slides)",
    "q4": "Use all available GraphRAG evidence"
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `thread_id` | string | Yes | The thread_id from the `submitted` event. |
| `agent_node` | string | No | Which node requested HITL (from `hitl_required` event). Default: `"content_node"`. |
| `answers` | object | Yes | Key-value pairs of user answers. At least one answer required. Keys are `q1`, `q2`, etc. |

**Validation errors:**
- `404` — Thread not found
- `409` — Thread is not in blocked state
- `422` — Empty answers

**Response**: SSE stream (same event vocabulary as `/submit`). Resumes from where the workflow paused.

#### GET `/api/v4/orchestrator/status/{thread_id}`

Returns the current state of a workflow thread.

**Response:**
```json
{
  "thread_id": "47b20076-...",
  "execution_mode": "temporal",
  "status": "complete",
  "current_node": "governance_node",
  "hitl_required": false,
  "hitl_questions": [],
  "error_message": "",
  "final_artifact": { ... },
  "updated_at": "2026-03-23T09:19:46.018Z"
}
```

| Field | Type | Description |
|---|---|---|
| `thread_id` | string | The workflow identifier. |
| `execution_mode` | string | `"temporal"` or `"direct"`. |
| `status` | string | One of: `queued`, `dispatching`, `running`, `blocked_on_user`, `resuming`, `complete`, `error`. |
| `current_node` | string | Last active graph node: `planner`, `graphrag_node`, `content_node`, `hitl`, `governance_node`. |
| `hitl_required` | boolean | True if the workflow is paused waiting for user input. |
| `hitl_questions` | string[] | The questions the user must answer (populated when `hitl_required` is true). |
| `error_message` | string | Error details (populated when `status` is `"error"`). |
| `final_artifact` | object or null | The canonical result object (see Section 5). Populated when status is `complete` or `error`. |
| `updated_at` | string | ISO 8601 timestamp of the last state transition. |

#### GET `/api/v4/orchestrator/workflows`

Lists recent workflow threads. Useful for session history.

**Response:**
```json
{
  "workflows": [
    {
      "workflow_id": "blaiq-47b20076-...",
      "run_id": "29aefec9-...",
      "status": "2",
      "start_time": "2026-03-23T09:15:00+00:00"
    }
  ]
}
```

#### POST `/api/v4/orchestrator/regenerate`

Re-generates content with an edited schema without re-running GraphRAG retrieval.

**Request:**
```json
{
  "thread_id": "47b20076-...",
  "patched_schema": {
    "strategic_pillars": ["AI-First Infrastructure", "Developer Experience"],
    "kpis": ["3.3x speed improvement", "<100ms response time"],
    "target_audience": "Enterprise CIOs",
    "vision_statement": "Make enterprise search instant",
    "timeline": "Q1-Q4 2026"
  },
  "workflow_mode": "standard"
}
```

**Response**: SSE stream with `regen_complete` event containing the new `html_artifact`.

#### POST `/upload`

Upload documents to the knowledge base.

**Request**: `multipart/form-data`
- `file`: Binary file (PDF, DOCX, TXT, MD). Max 50MB.
- `tenant_id`: String (optional, defaults to `"default"`)
- `metadata`: JSON string (optional custom metadata)

**Response:**
```json
{
  "status": "success",
  "request_id": "...",
  "filename": "report.pdf",
  "file_size": 245678,
  "processing_result": { ... }
}
```

#### GET `/agents`

Lists all registered agents with their capabilities.

---

## 4. SSE Event Vocabulary

Every SSE frame is formatted as `data: {json}\n\n`. The stream terminates with `data: [DONE]\n\n`.

### 4.1 Event Types

| Event | When | Key Payload Fields | Frontend Action |
|---|---|---|---|
| `submitted` | Immediately on POST | `thread_id`, `session_id`, `execution_mode` | Store thread_id. Show "Workflow started" in timeline. |
| `workflow_started` | After Temporal/LangGraph init | `run_id`, `thread_id` | Update timeline with execution details. |
| `planning` | Planner node executing | `node`, `status` | Show "Planning workflow..." step. |
| `evidence_ready` | GraphRAG retrieval complete | `node` | Show "Evidence retrieved" step. |
| `content_ready` | Content generation complete (no HITL) | `content_draft` | Show "Content generated" step. Optionally preview draft. |
| `hitl_required` | Workflow paused for user input | `questions[]`, `thread_id`, `node` | Open HITL overlay. Show "Paused — waiting for input" in timeline. |
| `signal_sent` | Resume signal delivered | — | Show "Signal sent" in timeline. |
| `resuming` | Workflow resuming after HITL | — | Show "Resuming..." in timeline. |
| `governance` | Governance checks complete | `governance_report` | Show pass/fail badge in timeline. |
| `complete` | Workflow terminal (success or error) | `final_artifact` | Render artifact. Close timeline. Enable input. |
| `error` | Workflow terminal (error) | `message` | Show error in timeline and chat. Enable input. |
| `progress` | Heartbeat (Temporal polling) | `status` | No visible action. Keeps SSE connection alive. |

### 4.2 SSE Consumption Pattern

The frontend must use `fetch` with `ReadableStream` (not `EventSource`, because POST bodies are required):

```javascript
const response = await fetch(url, {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
  body: JSON.stringify(payload),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split("\n");
  buffer = lines.pop();  // keep incomplete line

  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const raw = line.slice(6).trim();
    if (raw === "[DONE]") { onStreamDone(); return; }
    handleEvent(JSON.parse(raw));
  }
}
```

### 4.3 Reconnection

If the SSE connection drops mid-stream:
1. Call `GET /api/v4/orchestrator/status/{thread_id}` to check current state.
2. If `status === "blocked_on_user"` → show HITL overlay with `hitl_questions`.
3. If `status === "complete"` → render `final_artifact`.
4. If `status === "running"` → reconnect is not supported (workflow will complete and result is queryable via status).

---

## 5. FinalArtifact — The Canonical Result Object

Every completed workflow produces a `FinalArtifact`. This is the ONLY object the frontend should read for final output. Do not fallback to `governance_report`, `content_draft`, or `evidence_manifest` individually.

```typescript
interface FinalArtifact {
  kind: "content" | "evidence_only" | "error";
  mission_id: string;
  validation_passed: boolean;

  // Governance
  governance_report: GovernanceReport | null;

  // Content artifacts (populated when kind === "content")
  artifact_uri: string | null;   // Redis claim-check URI for large artifacts
  html_artifact: string | null;  // Inline HTML (null if claim-checked)
  schema_data: ContentSchema | null;
  skills_used: string[];
  brand_dna_version: string;

  // Evidence artifacts (populated when kind === "evidence_only")
  answer: string | null;

  // Error info (populated when kind === "error")
  error_message: string | null;
}

interface GovernanceReport {
  mission_id: string;
  validation_passed: boolean;
  policy_checks: PolicyCheck[];
  violations: string[];
  approved_output: string | null;  // Governance-approved HTML (if available)
  timestamp: string;
}

interface PolicyCheck {
  rule: string;     // "schema_completeness" | "tenant_isolation" | "brand_palette" | "content_safety"
  passed: boolean;
  detail: string;   // Empty if passed, explanation if failed
}

interface ContentSchema {
  strategic_pillars: string[];
  kpis: string[];
  target_audience: string;
  vision_statement: string;
  timeline: string;
}
```

### 5.1 Rendering Logic

```
if (artifact.kind === "error") {
  → Show error_message in chat and timeline
  → If governance_report exists, show which checks failed
}

if (artifact.kind === "evidence_only") {
  → Render artifact.answer as markdown in chat
  → Show governance badge (passed/failed)
}

if (artifact.kind === "content") {
  → Prefer artifact.governance_report.approved_output over artifact.html_artifact
    (approved_output is the governance-verified version)
  → If neither exists and artifact_uri is set, resolve via status endpoint
  → Render HTML in a sandboxed iframe
  → Show schema_data in the Schema Editor panel
  → Show governance badge
  → Show skills_used as tags
}
```

### 5.2 Claim Check Resolution

When `html_artifact` is null but `artifact_uri` starts with `redis://`, the HTML was too large for inline state (>50KB). The `governance_report.approved_output` will contain the full HTML if governance passed. If neither is available, call `GET /api/v4/orchestrator/status/{thread_id}` which resolves claim-check URIs before returning.

---

## 6. Multi-Tenancy

### 6.1 Tenant Isolation Model

```
Tenant A (acme-corp)          Tenant B (globex-inc)
├── Qdrant Collection:        ├── Qdrant Collection:
│   acme-corp                 │   globex-inc
├── Neo4j filter_label:       ├── Neo4j filter_label:
│   acme-corp                 │   globex-inc
├── Uploaded Documents:       ├── Uploaded Documents:
│   data/acme-corp/           │   data/globex-inc/
├── Workflow History:         ├── Workflow History:
│   (filtered by tenant)      │   (filtered by tenant)
└── Brand DNA:                └── Brand DNA:
    brand_dna/acme.json           brand_dna/globex.json
```

### 6.2 Frontend Responsibilities

1. **Tenant Selection**: On login, resolve the user's tenant_id from the auth provider (SSO, JWT claim, or org membership). Never let the user type a tenant_id into a form.

2. **Tenant Header**: Include `tenant_id` in every `submit` and `upload` request body. The backend uses this to scope all vector search, graph traversal, and document access.

3. **Tenant Switching**: If a user belongs to multiple tenants (enterprise admin), provide a tenant switcher in the sidebar or header. On switch:
   - Clear the chat history
   - Reset the execution timeline
   - Re-fetch `/agents` for the new tenant's agent registry
   - Update the collection_name to match the new tenant

4. **Cross-Tenant Prevention**: The frontend must never display workflows, documents, or artifacts from a tenant the user does not belong to. Filter `/workflows` results by tenant on the client side as a defense-in-depth measure.

### 6.3 Tenant Configuration

Each tenant may have custom:
- Brand DNA (colors, typography, logo, voice)
- Agent registry (which agents are available)
- Workflow modes (which modes are enabled)
- Upload limits (max file size, allowed formats)
- LLM model routing (which models to use)

The backend resolves these from `TENANT_CONFIG_MAP_JSON` env var or per-tenant env overrides. The frontend should call `GET /` (health endpoint) on load to discover the tenant's configuration.

---

## 7. HITL (Human-in-the-Loop) UX Requirements

### 7.1 When HITL Triggers

The content agent (Vangogh) performs a gap analysis on every content creation request. If required information is missing (target audience, design style, output format, evidence preferences), it returns `status: "blocked_on_user"` with exactly 4 questions.

### 7.2 Question Format

```json
{
  "type": "hitl_required",
  "questions": [
    "Who is the primary target audience for this content?",
    "What visual style and design aesthetic do you prefer?",
    "What output format best suits your needs?",
    "How should we use the available knowledge base evidence?"
  ],
  "thread_id": "47b20076-...",
  "node": "content_node"
}
```

Questions are always an array of plain strings. The frontend should render them with smart defaults (chips/suggestions) based on keyword detection in the question text.

### 7.3 UX Expectations

**Must-have:**
- Show all questions simultaneously (not one at a time). Users are enterprise professionals — they can handle 4 fields at once.
- Clearly indicate the workflow is **paused, not failed**. Use language like "Waiting for your input" with a pause icon, not a spinner or error state.
- Preserve the thread_id across the pause. The user must be able to close the tab, return later, and resume (Temporal persists the state).
- After submission, stream the resumed workflow events into the same execution timeline. Do not create a new timeline or session.
- If the content agent blocks again (second-round HITL), re-open the overlay with new questions.

**Should-have:**
- Quick-option chips below each question (e.g., "Enterprise CIOs", "Modern minimal", "Pitch deck").
- Pre-fill answers from user profile or previous sessions.
- "Skip" option that sends a default answer (e.g., "Use your best judgment").
- Keyboard navigation (Tab between fields, Enter to submit).

**Nice-to-have:**
- Rich input types: dropdown for format selection, color picker for style, slider for evidence depth.
- Show the GraphRAG evidence summary alongside the questions so the user can make informed decisions.
- Auto-save draft answers to localStorage in case of accidental navigation.

### 7.4 Resume Flow

```
User answers questions
  → POST /api/v4/orchestrator/resume { thread_id, answers }
  → SSE stream begins:
      resuming → signal_sent → content_ready → governance → complete
  → Final artifact rendered in preview pane
```

---

## 8. Artifact Rendering

### 8.1 HTML Artifacts (Pitch Decks, Landing Pages, Dashboards)

The content agent generates full HTML documents with:
- Tailwind CSS (loaded via CDN `unpkg.com/@tailwindcss/browser@4`)
- Google Fonts (Space Grotesk, Bebas Neue)
- CSS animations (pulse, float, gradients)
- Responsive layout (mobile-first grid)
- Brand colors from Da'Vinci brand DNA (#FF4500 primary, #0a0a0a background)

**Rendering approach:**
```html
<iframe
  id="artifact-preview"
  sandbox="allow-scripts allow-same-origin"
  srcdoc="...html_artifact..."
  style="width:100%; height:600px; border:none; border-radius:12px;"
></iframe>
```

Use `sandbox="allow-scripts allow-same-origin"` to allow Tailwind CSS to execute while preventing the artifact from accessing parent DOM or making network requests to other origins.

**Do NOT** render HTML via `innerHTML` or `dangerouslySetInnerHTML`. Always use an iframe with sandbox.

### 8.2 Text Artifacts (Evidence-Only Responses)

When `kind === "evidence_only"`, the `answer` field contains a markdown-formatted text response from the GraphRAG retriever. Render using a markdown parser (e.g., marked.js, markdown-it).

### 8.3 Artifact Actions

After rendering an artifact, provide these actions:

| Action | Behavior |
|---|---|
| **Download HTML** | Save `html_artifact` as a `.html` file |
| **Copy to Clipboard** | Copy the raw HTML to clipboard |
| **Open in New Tab** | Open artifact in a new browser tab for full-screen preview |
| **Edit Schema** | Open the Schema Editor panel (see Section 9) |
| **Regenerate** | POST to `/regenerate` with edited schema |
| **Share** | Generate a shareable link (requires backend support — future) |

---

## 9. Schema Editor

### 9.1 Purpose

Every content artifact is generated from a `ContentSchema` that defines the strategic pillars, KPIs, target audience, vision statement, and timeline. The Schema Editor lets enterprise users review and tweak these values, then regenerate the artifact without re-running the entire pipeline.

### 9.2 Layout

```
┌──────────────────────────────────┐
│ 📋 Content Schema                │
├──────────────────────────────────┤
│                                  │
│ Vision Statement                 │
│ ┌──────────────────────────────┐ │
│ │ Editable textarea            │ │
│ └──────────────────────────────┘ │
│                                  │
│ Target Audience                  │
│ ┌──────────────────────────────┐ │
│ │ Editable textarea            │ │
│ └──────────────────────────────┘ │
│                                  │
│ KPIs                             │
│ ┌────────┐ ┌────────┐ ┌──────┐  │
│ │ 3.3x ✕ │ │ <100ms✕│ │ + Add│  │
│ └────────┘ └────────┘ └──────┘  │
│                                  │
│ Strategic Pillars                │
│ ┌────────────────┐ ┌──────────┐ │
│ │ AI-First Infra✕│ │ DevEx  ✕ │ │
│ └────────────────┘ └──────────┘ │
│                                  │
│ Timeline                         │
│ ┌──────────────────────────────┐ │
│ │ Q1-Q4 2026                   │ │
│ └──────────────────────────────┘ │
│                                  │
│ [↻ Regenerate with edits]        │
└──────────────────────────────────┘
```

### 9.3 Regeneration Flow

```
User edits KPIs in Schema Editor
  → Click "Regenerate with edits"
  → POST /api/v4/orchestrator/regenerate {
      thread_id, patched_schema, workflow_mode
    }
  → SSE stream with regen_complete event
  → New HTML artifact replaces previous in iframe
  → Schema Editor updates with any LLM-refined values
```

---

## 10. Execution Timeline

### 10.1 Purpose

Enterprise users need transparency into what the AI is doing. The execution timeline shows named steps as they happen, with timestamps, status indicators, and the ability to expand details.

### 10.2 Step States

| State | Visual | Description |
|---|---|---|
| `active` | Pulsing orange dot | Currently executing |
| `done` | Green dot | Completed successfully |
| `blocked` | Yellow dot | Waiting for user input |
| `warning` | Yellow dot | Completed with warnings (e.g., governance violations) |
| `failed` | Red dot | Failed with error |

### 10.3 Step Labels (mapped from SSE events)

| Event | Label |
|---|---|
| `submitted` | Workflow submitted |
| `workflow_started` | Temporal workflow started (run: {run_id}) |
| `planning` | Planning execution strategy... |
| `evidence_ready` | GraphRAG: Evidence retrieved |
| `content_ready` | Vangogh: Content generated |
| `hitl_required` | Paused — waiting for your input |
| `resuming` | Resuming with your answers... |
| `signal_sent` | Signal delivered to workflow |
| `governance` | Governance: {passed ? "All checks passed" : violations} |
| `complete` | Complete |
| `error` | Error: {message} |

### 10.4 Position and Behavior

- Fixed position: right side of the viewport, vertically centered.
- Auto-scrolls to the latest step.
- Collapsible to minimize screen space.
- Persists across HITL pauses (same timeline, not a new one).
- Shows elapsed time per step (optional).

---

## 11. Governance Display

### 11.1 Governance Badge

After every `complete` event, show a governance badge:

```
✅ Governance Passed (4/4 checks)
```
or
```
⚠️ Governance: 1 violation — "Off-brand colours detected"
```

### 11.2 Governance Detail Panel (expandable)

| Check | Status | Detail |
|---|---|---|
| Schema Completeness | ✅ Passed | — |
| Tenant Isolation | ✅ Passed | — |
| Brand Palette | ⚠️ Failed | Off-brand colours: #123456, #abcdef |
| Content Safety | ✅ Passed | — |

### 11.3 Governance Failure UX

When governance fails:
1. Show the violation details in the governance panel.
2. The artifact is still generated but NOT governance-approved.
3. Offer two actions:
   - **"Regenerate"** — re-run content generation with stricter brand constraints.
   - **"Override"** — accept the artifact despite governance warnings (audit-logged).

---

## 12. Session Management

### 12.1 Session Identity

Each workflow submission creates a `session_id` (auto-generated or provided by the frontend). Sessions group related workflows for conversation history.

### 12.2 Session Persistence

- `thread_id`: Identifies a single workflow run. Persists in Temporal (survives container restarts).
- `session_id`: Groups workflows. Stored in Redis with configurable TTL.

### 12.3 Session History

The frontend should maintain a session history sidebar showing:
- Recent thread_ids with timestamps
- Status indicator (complete, blocked, error)
- Click to load the thread's final_artifact via `GET /status/{thread_id}`

### 12.4 Multi-Tab Support

Multiple browser tabs sharing the same session must not corrupt state. Use `thread_id` (not session_id) as the primary workflow identifier. Each tab should track its own active `thread_id`.

---

## 13. Upload and Knowledge Base Management

### 13.1 File Upload UX

```
┌──────────────────────────────────┐
│ 📁 Knowledge Base                │
├──────────────────────────────────┤
│                                  │
│  ┌──────────────────────────┐    │
│  │  Drag & drop files here  │    │
│  │  or click to browse      │    │
│  │                          │    │
│  │  PDF, DOCX, TXT, MD     │    │
│  │  Max 50MB per file       │    │
│  └──────────────────────────┘    │
│                                  │
│  Recent uploads:                 │
│  ✅ report_q3.pdf (2.3MB)       │
│  ✅ strategy_2026.docx (1.1MB)  │
│  ⏳ analysis.pdf (processing)   │
│                                  │
└──────────────────────────────────┘
```

### 13.2 Upload Flow

1. User drops file → `POST /upload` with `multipart/form-data`
2. Backend chunks, embeds, and indexes in Qdrant + Neo4j
3. Frontend shows progress (processing, complete, error)
4. Uploaded documents are immediately searchable in the next `submit` request

---

## 14. Error Handling

### 14.1 Error Categories

| Category | HTTP Status | Frontend Behavior |
|---|---|---|
| Validation error | 422 | Show field-level error messages |
| Thread not found | 404 | "This workflow no longer exists. Start a new one." |
| Thread not blocked | 409 | "This workflow is not waiting for input." |
| LLM timeout | SSE `error` | "The AI model timed out. Try again or simplify your request." |
| Service unavailable | 503 | "BLAIQ Core is temporarily unavailable. Retrying..." |
| Network error | — | "Connection lost. Checking status..." → poll `/status` |

### 14.2 Recovery Patterns

1. **SSE connection drop**: Poll `/status/{thread_id}` to recover state.
2. **HITL timeout**: The workflow persists in Temporal indefinitely. The user can resume hours or days later.
3. **Double submission**: The backend uses idempotency keys. Submitting the same request twice produces the same workflow, not a duplicate.
4. **Stale thread**: If a thread is older than 24 hours, the Redis claim-check artifacts may have expired. Show "Artifact expired — regenerate to create a fresh version."

---

## 15. Performance Expectations

| Metric | Target | Notes |
|---|---|---|
| Time to first SSE event | <500ms | `submitted` event should arrive within 500ms of POST |
| Planner latency | 1-3s | Fast LLM model (Groq or GPT-4o-mini) |
| GraphRAG retrieval | 2-8s | Depends on collection size and query complexity |
| Content generation | 15-45s | Claude Sonnet generates full HTML |
| Governance validation | <100ms | In-process regex + schema checks |
| Total golden path (no HITL) | 20-60s | End-to-end from submit to complete |
| HITL resume to complete | 15-45s | Content generation + governance after resume |

The frontend should show the execution timeline immediately (within 500ms) to avoid perceived latency. Never show a blank screen or spinning wheel for more than 2 seconds.

---

## 16. Responsive Design Requirements

### 16.1 Breakpoints

| Breakpoint | Layout |
|---|---|
| Desktop (>1280px) | Three-column: sidebar + chat + schema panel |
| Tablet (768-1280px) | Two-column: sidebar collapses to icons, chat + schema |
| Mobile (<768px) | Single column: chat only, sidebar as drawer, HITL overlay full-screen |

### 16.2 Critical Mobile Considerations

- HITL overlay must be full-screen on mobile (no bento grid — stack questions vertically).
- Artifact preview uses full viewport width on mobile.
- Execution timeline collapses to a single-line progress bar on mobile.
- Upload area must support mobile file picker.

---

## 17. Accessibility Requirements

| Requirement | Implementation |
|---|---|
| Keyboard navigation | Tab through all interactive elements. Enter to submit forms. Escape to close overlays. |
| Screen reader support | All dynamic content updates announced via `aria-live` regions. Timeline steps use `role="status"`. |
| Color contrast | All text meets WCAG AA (4.5:1 for normal text, 3:1 for large text). Dark mode primary: `#FF4500` on `#0a0a0a` passes at 4.6:1. |
| Focus management | HITL overlay traps focus. On close, focus returns to the chat input. |
| Reduced motion | Respect `prefers-reduced-motion`. Disable timeline animations, pulse effects, and floating orbs. |

---

## 18. Technology Recommendations

The current frontend is vanilla JS in a single HTML file. For production enterprise deployment, consider:

| Concern | Recommendation |
|---|---|
| **Framework** | Next.js 15 or Nuxt 4 (SSR for SEO, RSC for performance) |
| **State management** | Zustand or Jotai (lightweight, works with SSE streams) |
| **Styling** | Tailwind CSS v4 (matches artifact output) |
| **SSE handling** | Custom hook wrapping `fetch` + `ReadableStream` (not EventSource — need POST) |
| **Markdown rendering** | `react-markdown` with `remark-gfm` plugin |
| **HTML sandbox** | `<iframe srcDoc={html} sandbox="allow-scripts" />` |
| **Schema editor** | React Hook Form or Formik with tag-input component |
| **Testing** | Playwright for E2E, Vitest for unit tests |
| **Deployment** | Vercel (frontend) + Docker (backend) or unified K8s |

---

## 19. Checklist: Frontend MVP Acceptance

- [ ] User can submit a query and see SSE events streaming into an execution timeline.
- [ ] HITL overlay opens with all questions visible. User can answer and resume.
- [ ] Resumed workflow streams into the same timeline (no page reload).
- [ ] Second-round HITL re-opens the overlay with new questions.
- [ ] Final artifact renders in a sandboxed iframe.
- [ ] Schema Editor shows editable fields. "Regenerate" produces a new artifact.
- [ ] Governance badge shows pass/fail with expandable detail.
- [ ] Error states show descriptive messages and re-enable input.
- [ ] Completed thread is queryable via status endpoint.
- [ ] Multi-tenant: tenant_id is included in every request.
- [ ] File upload works with progress feedback.
- [ ] Works on desktop (1280px+) and tablet (768px+).
- [ ] Keyboard accessible (Tab, Enter, Escape).
- [ ] No hardcoded API keys in frontend code.
- [ ] SSE reconnection handles dropped connections gracefully.
