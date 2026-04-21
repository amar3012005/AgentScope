# BLAIQ Core — Standardised API Endpoint Contract

**Version**: 1.0.0
**Date**: 2026-03-28
**Status**: CANONICAL — Frontend and backend MUST conform to this document

---

## 1. Endpoint Inventory

### 1.1 V4 Orchestrator (Primary — Production)

| # | Method | Path | Auth | Response | Purpose |
|---|--------|------|------|----------|---------|
| 1 | POST | `/api/v4/orchestrator/submit` | API Key | SSE stream | Start a workflow |
| 2 | POST | `/api/v4/orchestrator/resume` | API Key | SSE stream | Resume HITL-blocked workflow |
| 3 | POST | `/api/v4/orchestrator/regenerate` | API Key | SSE stream | Re-generate with edited schema |
| 4 | GET | `/api/v4/orchestrator/status/{thread_id}` | API Key | JSON | Poll workflow state |
| 5 | GET | `/api/v4/orchestrator/workflows` | API Key | JSON | List recent workflows |

### 1.2 Knowledge & Upload

| # | Method | Path | Auth | Response | Purpose |
|---|--------|------|------|----------|---------|
| 6 | POST | `/upload` | None | JSON | Upload documents to knowledge base |

### 1.3 System & Discovery

| # | Method | Path | Auth | Response | Purpose |
|---|--------|------|------|----------|---------|
| 7 | GET | `/` | None | JSON | Service health |
| 8 | GET | `/agents` | None | JSON | List registered agents |
| 9 | GET | `/agents/live` | None | JSON | Live agent status with health |

### 1.4 Session History

| # | Method | Path | Auth | Response | Purpose |
|---|--------|------|------|----------|---------|
| 10 | GET | `/history/{session_id}` | None | JSON | Conversation history |
| 11 | GET | `/sessions/{session_id}/timeline` | None | JSON | Session event timeline |

### 1.5 Legacy (Supported but not primary)

| # | Method | Path | Auth | Response | Purpose |
|---|--------|------|------|----------|---------|
| 12 | POST | `/orchestrate` | None | JSON | Legacy agent routing |
| 13 | POST | `/query/graphrag` | None | JSON | Direct GraphRAG query |
| 14 | POST | `/query/graphrag/stream` | None | SSE | Streaming GraphRAG query |

### 1.6 WebSocket

| # | Method | Path | Auth | Protocol | Purpose |
|---|--------|------|------|----------|---------|
| 15 | WS | `/ws/agents/{agent_name}` | None | WebSocket | Agent-Core bidirectional |

---

## 2. V4 Endpoint Contracts (Detailed)

### 2.1 POST `/api/v4/orchestrator/submit`

**Request:**
```json
{
  "tenant_id": "string (required)",
  "user_query": "string (required, min 1 char)",
  "workflow_mode": "standard | deep_research | creative (default: standard)",
  "collection_name": "string | null (defaults to tenant_id)",
  "session_id": "string | null (auto-generated if omitted)"
}
```

**Response:** `Content-Type: text/event-stream`

SSE events emitted in order:

| Event Type | Payload | When |
|---|---|---|
| `submitted` | `{ thread_id, session_id, execution_mode }` | Immediately |
| `workflow_started` | `{ run_id, thread_id, execution_mode }` | After Temporal/LangGraph starts |
| `planning` | `{ node, status, execution_mode }` | Planner node executing |
| `evidence_ready` | `{ node, status, execution_mode }` | GraphRAG retrieval complete |
| `content_ready` | `{ node, status, execution_mode }` | Content generation complete |
| `hitl_required` | `{ questions[], thread_id, node, execution_mode }` | Workflow paused for user input |
| `governance` | `{ node, status, governance_report, execution_mode }` | Governance checks done |
| `complete` | `{ final_artifact: FinalArtifact, execution_mode }` | Workflow finished |
| `error` | `{ message, execution_mode }` | Workflow failed |
| `progress` | `{ status: "running", execution_mode }` | Heartbeat (Temporal polling) |

Terminal frame: `data: [DONE]\n\n`

**Error codes:**
- `422` — Validation error (missing tenant_id, empty query)

---

### 2.2 POST `/api/v4/orchestrator/resume`

**Request:**
```json
{
  "thread_id": "string (required)",
  "agent_node": "string (default: content_node)",
  "answers": { "q1": "answer1", "q2": "answer2" }
}
```

**IMPORTANT:** Answer keys MUST be `q1`, `q2`, `q3`, `q4` — NOT the question text.

**Response:** SSE stream (same event vocabulary as `/submit`)

Additional events after resume:

| Event Type | Payload | When |
|---|---|---|
| `resuming` | `{ thread_id, execution_mode }` | Resume initiated |
| `signal_sent` | `{ thread_id, execution_mode }` | Temporal signal delivered |

**Error codes:**
- `404` — Thread not found
- `409` — Thread is not blocked (cannot resume)
- `422` — Empty answers

---

### 2.3 POST `/api/v4/orchestrator/regenerate`

**Request:**
```json
{
  "thread_id": "string (required)",
  "patched_schema": {
    "vision_statement": "string",
    "target_audience": "string",
    "kpis": ["string"],
    "strategic_pillars": ["string"],
    "timeline": "string"
  },
  "workflow_mode": "standard | deep_research | creative (default: standard)"
}
```

**Response:** SSE stream with events:

| Event Type | Payload | When |
|---|---|---|
| `regen_started` | `{ thread_id }` | Regeneration initiated |
| `regen_complete` | `{ html_artifact, schema_data }` | New artifact ready |
| `error` | `{ message }` | Regeneration failed |

Terminal: `data: [DONE]\n\n`

---

### 2.4 GET `/api/v4/orchestrator/status/{thread_id}`

**Response:**
```json
{
  "thread_id": "string",
  "execution_mode": "temporal | direct",
  "status": "queued | dispatching | running | blocked_on_user | resuming | complete | error",
  "current_node": "planner | graphrag_node | content_node | hitl | governance_node",
  "hitl_required": false,
  "hitl_questions": [],
  "error_message": "",
  "final_artifact": null,
  "updated_at": "2026-03-28T10:00:00Z"
}
```

**Error codes:**
- `404` — Thread not found

---

### 2.5 GET `/api/v4/orchestrator/workflows`

**Response:**
```json
{
  "workflows": [
    {
      "workflow_id": "blaiq-{thread_id}",
      "run_id": "string",
      "status": "string",
      "start_time": "ISO timestamp | null"
    }
  ]
}
```

---

## 3. Canonical Data Models

### 3.1 FinalArtifact

```typescript
interface FinalArtifact {
  kind: "content" | "evidence_only" | "error";
  mission_id: string;
  validation_passed: boolean;
  governance_report: GovernanceReport | null;
  artifact_uri: string | null;
  html_artifact: string | null;
  schema_data: ContentSchema | null;
  skills_used: string[];
  brand_dna_version: string;
  answer: string | null;
  error_message: string | null;
}
```

### 3.2 GovernanceReport

```typescript
interface GovernanceReport {
  mission_id: string;
  validation_passed: boolean;
  policy_checks: PolicyCheck[];
  violations: string[];
  approved_output: string | null;
  timestamp: string;
}

interface PolicyCheck {
  rule: "schema_completeness" | "tenant_isolation" | "brand_palette" | "content_safety";
  passed: boolean;
  detail: string;
}
```

### 3.3 ContentSchema

```typescript
interface ContentSchema {
  strategic_pillars: string[];
  kpis: string[];
  target_audience: string;
  vision_statement: string;
  timeline: string;
}
```

---

## 4. Authentication

### 4.1 API Key Transport

| Transport | Header/Param | Priority |
|---|---|---|
| Custom header | `X-API-Key: <key>` | 1 (checked first) |
| Query parameter | `?api_key=<key>` | 2 |
| Bearer token | `Authorization: Bearer <key>` | 3 |

### 4.2 Multi-Tenancy

Every request MUST include `tenant_id`:
- V4 endpoints: In request body
- GET endpoints: As query parameter
- Upload: As form field

---

## 5. SSE Stream Protocol

### 5.1 Frame Format

```
data: {"type": "event_type", ...payload}\n\n
```

### 5.2 Terminal Frame

```
data: [DONE]\n\n
```

### 5.3 Complete Event Type Vocabulary

| Type | Endpoints | Meaning |
|---|---|---|
| `submitted` | submit | Workflow accepted |
| `workflow_started` | submit | Temporal/LangGraph running |
| `planning` | submit | Planner node active |
| `evidence_ready` | submit, resume | GraphRAG done |
| `content_ready` | submit, resume | Content agent done |
| `hitl_required` | submit, resume | Paused for user input |
| `signal_sent` | resume | Temporal signal delivered |
| `resuming` | resume | Resume in progress |
| `governance` | submit, resume | Governance checks done |
| `complete` | submit, resume | Final result with `final_artifact` |
| `error` | all | Failure |
| `progress` | submit, resume | Heartbeat (Temporal polling) |
| `regen_started` | regenerate | Regeneration started |
| `regen_complete` | regenerate | New artifact ready |

---

## 6. Known Mismatches (Frontend ↔ Backend)

### 6.1 CRITICAL

| # | Issue | Impact | Fix |
|---|---|---|---|
| 1 | **HITL answer key format** — vanilla `hitl.ts` uses question text as key, backend expects `q1/q2/q3/q4` | Resume fails silently | Fix `hitl.ts` to use `q${i+1}` keys |
| 2 | **Duplicate SSE clients** — `api/sse.ts` AND `features/orchestration/api.ts` both implement streaming | Code confusion, potential divergence | Delete or deprecate `features/orchestration/api.ts` |
| 3 | **Missing tenant_id** — `features/orchestration/api.ts:resumeRun()` does NOT add tenant_id | Backend may reject or misroute | Add tenant_id injection |

### 6.2 HIGH

| # | Issue | Impact | Fix |
|---|---|---|---|
| 4 | **No auth on V4 endpoints** — backend does NOT enforce `verify_api_key` on V4 routes | Security gap | Add `Depends(verify_api_key)` |
| 5 | **Endpoint prefix inconsistency** — `/agents` and `/upload` not versioned under `/api/v4/` | Breaks if backend reorganizes | Add versioned aliases |
| 6 | **No retry logic** — all API calls fail on first network error | Poor UX on flaky connections | Add exponential backoff |

### 6.3 MEDIUM

| # | Issue | Impact | Fix |
|---|---|---|---|
| 7 | **Stale vanilla JS components** — `src/components/*.ts` files may shadow React components | Build confusion | Delete if React is canonical |
| 8 | **workflow_mode default in 3 places** — not centralized | Could diverge | Use single constant |
| 9 | **No pagination on /workflows** — frontend loads all, backend caps at 50 | Fine for MVP | Add pagination param later |

---

## 7. Port Map

| Service | Internal | External | URL |
|---|---|---|---|
| blaiq-core | 6000 | 6080 | `http://localhost:6080` |
| blaiq-graph-rag | 6001 | 6001 | `http://localhost:6001` |
| blaiq-echo-agent | 6002 | 6002 | `http://localhost:6002` |
| blaiq-content-agent | 6003 | 6003 | `http://localhost:6003` |
| temporal | 7233 | 7233 | gRPC |
| temporal UI | 8088 | 8088 | `http://localhost:8088` |
| temporal-db | 5432 | 5433 | Postgres |
| redis | 6379 | 6006 | Redis |

**Frontend:**
- Production: `http://localhost:6080/app/`
- Dev: `http://localhost:5173/app/`
- Legacy: `http://localhost:6080/static/core_client.html`
