# HIVE-MIND MCP Tools & API Reference

**Document Created:** 2026-04-07  
**Source:** `/src/agentscope_blaiq/runtime/hivemind_mcp.py`, `/src/agentscope_blaiq/mcp/hivemind_stateful.py`

---

## Overview

BLAIQ integrates with **HIVE-MIND** via a JSON-RPC MCP (Model Context Protocol) client. The HIVE-MIND server provides enterprise memory recall, web search, and conversation storage capabilities.

### Connection Details

| Configuration | Setting | Default |
|---------------|---------|---------|
| **RPC URL** | `hivemind_rpc_url` | `http://localhost:8050/api/mcp/rpc` |
| **API Key** | `hivemind_api_key` | (from env) |
| **Timeout** | `hivemind_timeout_seconds` | 20s |
| **Poll Interval** | `hivemind_web_poll_interval_seconds` | 1.0s |
| **Poll Attempts** | `hivemind_web_poll_attempts` | 10 |

---

## Available MCP Tools

### 1. `hivemind_recall`

**Purpose:** Recall enterprise memories relevant to a query.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query for memory recall |
| `limit` | integer | No | 20 | Maximum memories to return |
| `mode` | string | No | "insight" | Recall mode: `quick`, `insight`, `panorama` |

**Example:**
```python
result = await client.recall(
    query="Q3 2025 sales performance",
    limit=10,
    mode="insight"
)
```

**Used By:** `DeepResearchAgent`, `ResearchAgent`

---

### 2. `hivemind_query_with_ai`

**Purpose:** Run AI synthesis over enterprise memory when direct recall is insufficient.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `question` | string | Yes | - | Natural language question |
| `context_limit` | integer | No | 8 | Maximum context items to include |

**Example:**
```python
result = await client.query_with_ai(
    question="What were the main findings from the last board meeting?",
    context_limit=12
)
```

**Used By:** `ResearchAgent`, `DeepResearchAgent`

---

### 3. `hivemind_get_memory`

**Purpose:** Retrieve a specific memory by ID.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `memory_id` | string | Yes | - | UUID of the memory to retrieve |

**Example:**
```python
result = await client.get_memory(memory_id="550e8400-e29b-41d4-a716-446655440000")
```

---

### 4. `hivemind_traverse_graph`

**Purpose:** Traverse the memory graph to find related memories.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `memory_id` | string | Yes | - | Starting memory ID |
| `depth` | integer | No | 2 | Graph traversal depth (1-5) |

**Example:**
```python
result = await client.traverse_graph(
    memory_id="550e8400-e29b-41d4-a716-446655440000",
    depth=3
)
```

---

### 5. `hivemind_web_search`

**Purpose:** Search the live web through HIVE-MIND.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query |
| `domains` | string[] | No | None | Restrict to specific domains |
| `limit` | integer | No | 5 | Maximum results |

**Example:**
```python
result = await client.web_search(
    query="enterprise AI agents market size 2026",
    domains=["gartner.com", "forrester.com"],
    limit=10
)
```

**Used By:** `DeepResearchAgent`, `ResearchAgent`

---

### 6. `hivemind_web_crawl`

**Purpose:** Crawl and extract content from specific URLs.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `urls` | string[] | Yes | - | URLs to crawl |
| `depth` | integer | No | 1 | Crawl depth (linked pages) |
| `page_limit` | integer | No | 5 | Maximum pages to crawl |

**Example:**
```python
result = await client.web_crawl(
    urls=["https://example.com/report.pdf"],
    depth=2,
    page_limit=10
)
```

**Used By:** `DeepResearchAgent`

---

### 7. `hivemind_web_job_status`

**Purpose:** Check status of async web jobs (crawl/search).

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `job_id` | string | Yes | - | Job ID from async operation |

**Example:**
```python
result = await client.web_job_status(job_id="job_123456")
# Returns: {status: "completed" | "running" | "failed", payload: {...}}
```

---

### 8. `hivemind_web_usage`

**Purpose:** Check web search/crawl quota and usage.

**Parameters:** None

**Example:**
```python
result = await client.web_usage()
# Returns: {credits_remaining: 500, monthly_limit: 1000, reset_date: "2026-05-01"}
```

---

### 9. `hivemind_save_memory`

**Purpose:** Save new memory to HIVE-MIND.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `title` | string | Yes | - | Memory title |
| `content` | string | Yes | - | Memory content |
| `tags` | string[] | No | None | Tags for categorization |
| `project` | string | No | None | Project association |

**Example:**
```python
result = await client.save_memory(
    title="Q1 2026 Product Launch Results",
    content="The product launch exceeded targets by 35%...",
    tags=["product", "launch", "q1-2026"],
    project="alpha-launch"
)
```

---

### 10. `hivemind_save_conversation`

**Purpose:** Save conversation history to HIVE-MIND.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `title` | string | Yes | - | Conversation title |
| `messages` | object[] | Yes | - | Array of {role, content} objects |
| `tags` | string[] | No | None | Tags for categorization |
| `project` | string | No | None | Project association |

**Example:**
```python
result = await client.save_conversation(
    title="User research session #42",
    messages=[
        {"role": "user", "content": "What are the key metrics?"},
        {"role": "assistant", "content": "The key metrics are..."}
    ],
    tags=["research", "user-interview"],
    project="discovery"
)
```

---

## API Endpoints (FastAPI Backend)

### BLAIQ API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/healthz` | Storage health |
| `GET` | `/readyz` | Runtime readiness |
| `POST` | `/api/v1/workflows/submit` | Submit workflow |
| `POST` | `/api/v1/workflows/resume` | Resume workflow |
| `GET` | `/api/v1/workflows/{thread_id}` | Get workflow status |
| `GET` | `/api/v1/workflows/{thread_id}/sse` | SSE stream |
| `POST` | `/api/v1/uploads` | Upload file |
| `GET` | `/api/v1/uploads/{upload_id}` | Get upload info |
| `GET` | `/api/v1/artifacts/{artifact_id}` | Get artifact |
| `GET` | `/api/v1/brand-dna/{tenant_id}` | Get brand DNA |

### HIVE-MIND RPC Endpoint

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `{rpc_url}` | JSON-RPC 2.0 calls |

**JSON-RPC Request Format:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "hivemind_recall",
    "arguments": {"query": "...", "limit": 10}
  },
  "id": 1
}
```

**JSON-RPC Response Format:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "content": [{"type": "text", "text": "{...}"}]
  },
  "id": 1
}
```

---

## Usage in BLAIQ Agents

### ResearchAgent (`/src/agentscope_blaiq/agents/research.py`)

```python
class ResearchAgent(AgentBase):
    def __init__(self):
        # Register HIVE-MIND tools
        toolkit.register_tool_function(
            self._tool_hivemind_recall,
            func_name="hivemind_recall",
            func_description="Recall enterprise memories"
        )
        toolkit.register_tool_function(
            self._tool_hivemind_query_with_ai,
            func_name="hivemind_query_with_ai",
            func_description="Run synthesis over enterprise memory"
        )
        toolkit.register_tool_function(
            self._tool_hivemind_web_search,
            func_name="hivemind_web_search",
            func_description="Search the live web"
        )
        toolkit.register_tool_function(
            self._tool_hivemind_web_crawl,
            func_name="hivemind_web_crawl",
            func_description="Crawl URLs"
        )
```

### DeepResearchAgent (`/src/agentscope_blaiq/agents/deep_research/base.py`)

```python
class DeepResearchAgent(AgentBase):
    async def _phase1_deep_recall(self, query: str):
        # Uses hivemind_recall with different modes
        direct_memories = await self.hivemind.recall(
            query=query,
            limit=20,
            mode="quick"
        )
        
        # Uses hivemind_web_search for fresh data
        web_results = await self.hivemind.web_search(
            query=query,
            limit=10
        )
```

### WorkflowEngine (`/src/agentscope_blaiq/workflows/engine.py`)

```python
# In _run_research_phase:
evidence = await research_agent.gather(
    ctx.session,
    ctx.request.tenant_id,
    ctx.request.user_query,
    ctx.request.source_scope,
    quick_recall=(ctx.request.analysis_mode == AnalysisMode.standard)
)
```

---

## Recall Modes

HIVE-MIND supports three recall modes:

| Mode | Use Case | Speed | Depth |
|------|----------|-------|-------|
| `quick` | Fast memory lookup | <1s | Direct match only |
| `insight` | Default balanced mode | 2-5s | Graph traversal + synthesis |
| `panorama` | Comprehensive research | 10-30s | Full graph + web + AI synthesis |

**BLAIQ Integration:**
- `analysis_mode=standard` → `quick_recall=True` → Uses quick mode
- `analysis_mode=deep_research` → `quick_recall=False` → Uses insight/panorama

---

## Error Handling

```python
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPError

try:
    result = await client.recall(query="...")
except HivemindMCPError as e:
    # Handle: not configured, timeout, HTTP error, RPC error
    logger.error(f"HIVE-MIND error: {e}")
except httpx.TimeoutException:
    # Handle timeout
except httpx.HTTPStatusError:
    # Handle HTTP errors (4xx, 5xx)
```

---

## Configuration (Environment Variables)

```bash
# .env

# HIVE-MIND connection
HIVEMIND_RPC_URL=http://localhost:8050/api/mcp/rpc
HIVEMIND_API_KEY=your-api-key-here

# Timeouts
HIVEMIND_TIMEOUT_SECONDS=20
HIVEMIND_WEB_POLL_INTERVAL_SECONDS=1.0
HIVEMIND_WEB_POLL_ATTEMPTS=10
```

---

## Testing

```python
# Test HIVE-MIND connection
import asyncio
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient

async def test_hivemind():
    client = HivemindMCPClient(
        rpc_url="http://localhost:8050/api/mcp/rpc",
        api_key="test-key"
    )
    
    # List available tools
    tools = await client.tools_list()
    print(f"Available tools: {tools}")
    
    # Test recall
    result = await client.recall(query="test", limit=5)
    print(f"Recall result: {result}")
    
    # Test web search
    web_result = await client.web_search(query="AI agents", limit=3)
    print(f"Web result: {web_result}")

asyncio.run(test_hivemind())
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     BLAIQ Backend                            │
│                                                              │
│  ┌────────────────┐    ┌──────────────────┐                │
│  │  ResearchAgent │    │ DeepResearchAgent│                │
│  │                │    │                  │                │
│  │  - recall()    │    │  - recall()      │                │
│  │  - web_search()│    │  - web_search()  │                │
│  │  - web_crawl() │    │  - web_crawl()   │                │
│  └───────┬────────┘    └────────┬─────────┘                │
│          │                      │                           │
│          └──────────┬───────────┘                           │
│                     │                                        │
│            ┌────────▼────────┐                              │
│            │ HivemindMCPClient│                              │
│            │  (JSON-RPC)     │                              │
│            └────────┬────────┘                              │
│                     │                                        │
└─────────────────────┼────────────────────────────────────────┘
                      │ HTTP POST (JSON-RPC 2.0)
                      │ Authorization: Bearer {api_key}
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    HIVE-MIND Server                          │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐ │
│  │  Memory Store  │  │  Web Search    │  │  Graph DB    │ │
│  │   (Qdrant)     │  │   (Tavily)     │  │  (Neo4j)     │ │
│  └────────────────┘  └────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────┐
│              HIVE-MIND MCP Quick Reference                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  RECALL                                                      │
│  ├─ hivemind_recall(query, limit=20, mode="insight")        │
│  ├─ hivemind_query_with_ai(question, context_limit=8)       │
│  ├─ hivemind_get_memory(memory_id)                          │
│  └─ hivemind_traverse_graph(memory_id, depth=2)             │
│                                                              │
│  WEB                                                         │
│  ├─ hivemind_web_search(query, domains?, limit=5)           │
│  ├─ hivemind_web_crawl(urls, depth=1, page_limit=5)         │
│  ├─ hivemind_web_job_status(job_id)                         │
│  └─ hivemind_web_usage()                                    │
│                                                              │
│  SAVE                                                        │
│  ├─ hivemind_save_memory(title, content, tags?, project?)   │
│  └─ hivemind_save_conversation(title, messages, tags?, ...) │
│                                                              │
│  MODES: quick | insight | panorama                          │
│  POLLING: 1s interval, 10 attempts max                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

**Related Files:**
- `/src/agentscope_blaiq/runtime/hivemind_mcp.py` - HTTP client
- `/src/agentscope_blaiq/mcp/hivemind_stateful.py` - AgentScope MCP adapter
- `/src/agentscope_blaiq/runtime/registry.py` - Agent registry with HIVE-MIND
- `/src/agentscope_blaiq/agents/research.py` - Research agent usage
- `/src/agentscope_blaiq/agents/deep_research/base.py` - Deep research usage
