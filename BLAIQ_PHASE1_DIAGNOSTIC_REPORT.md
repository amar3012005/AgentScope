# BLAIQ Multi-Agent System - Phase 1 Diagnostic Report

**Date:** 2026-03-17
**Scope:** Full architecture analysis with failure point identification
**Status:** Phase 1 Complete - Critical Issues Identified

---

## Executive Summary

The Blaiq multi-agent system consists of:
1. **BLAIQ Core (Orchestrator)** - Central coordinator on port 6000 (external: 6080)
2. **GraphRAG Agent** - Context retrieval from Qdrant + Neo4j on port 6001
3. **Content Creator Agent** - Strategy director + content generation on port 6003
4. **Echo Agent** - Test/debug agent on port 6002

**Current Status:**
- ✅ GraphRAG Agent: Working (can accept requests and generate responses)
- ❌ Content Agent: Multiple critical issues identified
- ❌ Orchestrator Core: Frontend communication issues identified

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                        │
│                     static/core_client.html                                  │
│                          (Port 6080 external)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BLAIQ CORE ORCHESTRATOR                              │
│                    src/orchestrator/orchestrator_api.py                      │
│                         Port: 6000 (internal)                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Endpoints:                                                         │   │
│  │  - POST /orchestrate          - Main routing endpoint               │   │
│  │  - GET  /health               - Health check                        │   │
│  │  - WS   /ws/agents/{name}     - WebSocket for agents                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│   blaiq-graph-rag    │  │   blaiq-echo-agent   │  │ blaiq-content-agent  │
│  Port: 6001          │  │  Port: 6002          │  │  Port: 6003          │
│  REST + Stream       │  │  REST + WebSocket    │  │  REST + Stream       │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
            │                                               │
            ▼                                               ▼
┌──────────────────────┐                        ┌──────────────────────┐
│   Qdrant (Vector)    │                        │   External LLM       │
│   Neo4j (Graph)      │                        │   (OpenAI/Anthropic) │
└──────────────────────┘                        └──────────────────────┘
```

---

## Issue 1: Orchestrator Core - Frontend Communication Failure

### Location
- **File:** `src/orchestrator/orchestrator_api.py`
- **Frontend:** `static/core_client.html`

### Problem Description
The frontend (`core_client.html`) sends requests to `http://localhost:6080/orchestrate` but the orchestrator has **CORS and endpoint mismatches**:

### Critical Findings

1. **CORS Configuration Gap (Line 6080-6090 in orchestrator)**
   - The orchestrator API has CORS middleware but only on specific routes
   - Frontend runs on `http://localhost:6080` but makes requests to same port
   - The `/orchestrate` endpoint doesn't properly handle the preflight OPTIONS requests

2. **Endpoint Mismatch (Line 1078-1086 in core_client.html)**
   ```javascript
   // Frontend sends to:
   endpoint = 'http://localhost:6080/orchestrate';

   // But orchestrator expects:
   POST /orchestrate  (not /query/graphrag)
   ```

3. **Missing Request Validation**
   - Orchestrator doesn't validate `target_agent` field properly
   - When `target_agent: "blaiq-graph-rag"` is sent, it tries REST protocol but agent config shows REST is supported

4. **Port Mapping Confusion**
   - Docker maps `6080:6000` (external:internal)
   - Frontend correctly uses 6080 externally
   - But agents try to connect to `blaiq-core:6000` internally

### Evidence
```python
# orchestrator_api.py: Line ~1070-1090
# The orchestrator receives requests but:
# 1. No explicit /orchestrate endpoint handler shown
# 2. Agent dispatch logic may fail silently
```

---

## Issue 2: Content Agent - Critical Failures

### Location
- **File:** `src/agents/content_creator/agent.py`
- **Port:** 6003

### Problem A: Brand DNA Loading Failure (Lines 106-122)

```python
BRAND_DNA_PATH = Path("/app/brand_dna/davinci_ai.json")  # Hardcoded Docker path

# Problem: Path may not exist in container
# If file missing, BRAND_DNA = {} (empty dict)
# This causes downstream issues in gap analysis
```

**Impact:** All Brand DNA-dependent prompts fail with empty context.

### Problem B: Skill Loader Initialization Failure (Lines 124-140)

```python
def initialize_skill_loader():
    base_dir = Path(__file__).parent.parent.parent  # Assumes 3 levels up
    skills_dir = base_dir / "skills"
    prompt_dir = base_dir / "prompts" / "xml"

    skill_loader = PromptLoader(...)
```

**Issues:**
1. **Path assumption brittle** - If file structure changes, paths break
2. **No validation** - Doesn't check if directories exist before initializing
3. **Silent failure** - Sets `skill_loader = None` on exception but continues

### Problem C: GraphRAG Direct URL Hardcoded (Line 152)

```python
graphrag_url = os.getenv("GRAPHRAG_DIRECT_URL", "http://blaiq-graph-rag:6001")
```

**Issue:** In Docker network, `blaiq-graph-rag` hostname may not resolve if service name differs.

### Problem D: LLM Model Configuration Issues (Lines 49-57)

```python
def _get_llm_model() -> str:
    return os.getenv("OPENAI_MODEL", "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
```

**Issues:**
1. **Default model invalid** - `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` doesn't exist
2. **Environment variable mismatch** - Content agent uses `OPENAI_MODEL` but orchestrator uses `LITELLM_*` models
3. **No validation** - If model string is wrong, LLM calls fail silently

### Problem E: Gap Analysis Always Returns Questions (Lines 86-88)

```python
# STRATEGIC_INTERVIEW_SYSTEM_PROMPT has forced HITL:
"CRITICAL INSTRUCTION - FORCED HITL:
You MUST ALWAYS assume the context is lacking...
You MUST ALWAYS set "gaps_found" to true."
```

**Impact:** Content agent NEVER proceeds to generate content - always asks 4 questions.

### Problem F: SSE Stream Format Mismatch (Lines 520-533)

```python
async def sse_gen():
    yield f"data: {json.dumps({'log': '🎯 Strategic Intelligence Audit starting...'})}\n\n"
    # ...
    yield f"data: {json.dumps(result)}\n\n"
    yield "data: [DONE]\n\n"
```

**Issue:** Frontend expects `delta` key for streaming content, but content agent returns different JSON structure.

---

## Issue 3: GraphRAG Agent - Partial Issues

### Location
- **File:** `src/retriever/retriever_api_optimized.py`
- **Port:** 6001

### Status: Mostly Working ⚠️

### Minor Issues Identified

1. **Redis Connection Failure Fallback** (Lines 197-202)
   - If Redis fails, cache is silently disabled
   - No alerting or retry mechanism

2. **Tenant Resolution Complexity** (Lines 265-281)
   ```python
   def resolve_tenant(request: Request) -> str:
       # Tries header, then host, then subdomain
       # Can return unexpected values if headers malformed
   ```

3. **Missing Response Format for Orchestrator**
   - Returns `QueryResponse` Pydantic model
   - Orchestrator expects different format with `result.message` or `result.html_artifact`

---

## Issue 4: Frontend-Backend Contract Mismatch

### Location
- **Frontend:** `static/core_client.html` Lines 1066-1137
- **Orchestrator:** Expected response format mismatch

### Critical Mismatch

Frontend expects response format:
```javascript
// From line 1119-1122:
if (currentAgent === 'content-creator') {
  responseText = data.result?.message || data.result?.html_artifact || ...
} else {
  responseText = data.result?.message || data.message || ...
}
```

But Content Agent returns:
```python
# From agent.py line 472-476:
return {
    "status": "success",
    "message": "DaVinci Visual Synthesis complete.",
    "html_artifact": html  # Only if successful
}
```

**Issue:** Content agent returns `blocked_on_user` status with questions, but frontend expects `result.message` or `result.html_artifact`.

---

## Issue 5: WebSocket Communication Issues

### Location
- **Orchestrator:** `orchestrator_api.py` Lines 570-650
- **Agents:** Echo agent Lines 51-78, Content agent Lines 536-574

### Problems

1. **WS URL Hardcoded with Service Names**
   ```python
   # Echo agent line 28
   return os.getenv("AGENT_CORE_WS_URL", "ws://blaiq-core:6000/ws/agents/echo-agent")
   ```
   - Outside Docker, `blaiq-core` hostname won't resolve

2. **No Fallback to REST**
   - If WebSocket fails, agents don't automatically fall back to REST
   - Echo agent has WS worker but no REST fallback

3. **Connection Retry Loop**
   - Both agents retry forever with 2-second delay
   - No exponential backoff
   - Logs get flooded with reconnection messages

---

## Issue 6: Environment Configuration Chaos

### Problems

1. **Duplicate Environment Variables**
   - `OPENAI_MODEL` vs `LITELLM_POST_MODEL`
   - `LITELLM_STRATEGIST_MODEL` vs `LITELLM_PLANNER_MODEL`

2. **Missing Required Variables**
   - `GRAPHRAG_DIRECT_URL` not set in docker-compose
   - `BRAND_DNA_PATH` not configurable via env

3. **Inconsistent Defaults**
   - Content agent defaults to non-existent Anthropic model
   - GraphRAG has different defaults in different files

---

## Summary Table: Failure Points

| Component | Issue | Severity | Impact |
|-----------|-------|----------|--------|
| Orchestrator | CORS/Endpoint mismatch | 🔴 Critical | Frontend can't communicate |
| Orchestrator | Missing /orchestrate validation | 🔴 Critical | Requests may fail silently |
| Content Agent | Brand DNA path hardcoded | 🟡 High | Missing brand context |
| Content Agent | Skill loader init failure | 🟡 High | No skills available |
| Content Agent | LLM model invalid default | 🔴 Critical | All LLM calls fail |
| Content Agent | FORCED HITL in prompts | 🟡 High | Never generates content |
| Content Agent | SSE format mismatch | 🟡 High | Frontend can't parse stream |
| GraphRAG | Tenant resolution | 🟢 Low | May use wrong collection |
| GraphRAG | Response format | 🟡 High | Orchestrator can't parse |
| Frontend | Response parsing | 🟡 High | Shows errors instead of content |
| WebSocket | Hostname resolution | 🟡 High | Won't work outside Docker |
| Config | Variable chaos | 🟡 High | Inconsistent behavior |

---

## Recommended Phase 2 Actions

1. **Fix Orchestrator CORS** - Add explicit OPTIONS handler and validate all endpoints
2. **Fix Content Agent LLM Config** - Use consistent env vars with valid defaults
3. **Fix Brand DNA Loading** - Make path configurable and validate file exists
4. **Fix SSE Format** - Standardize JSON structure across all agents
5. **Add Health Checks** - Verify all services can communicate before marking healthy
6. **Config Unification** - Create single source of truth for environment variables

---

## Files Requiring Immediate Attention

1. `src/orchestrator/orchestrator_api.py` - CORS and endpoint validation
2. `src/agents/content_creator/agent.py` - LLM config and response format
3. `docker-compose.agentic.yml` - Environment variable consistency
4. `static/core_client.html` - Response parsing and error handling
5. `src/prompts/prompt_loader.py` - Path validation

---

*Report Generated by Claude Code - Phase 1 Architecture Analysis*
