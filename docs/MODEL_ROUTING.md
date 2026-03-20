# BLAIQ Model Routing Documentation

This document outlines how models are routed and selected throughout the BLAIQ system for different tasks.

---

## Overview

BLAIQ uses a prefix-based routing system to determine which SDK/client to use for LLM calls:

- **`groq/`** prefix → Groq SDK (fast inference, Llama models)
- **`openai/`** prefix or no prefix → OpenAI-compatible SDK (BLAIQ proxy)
- **`vertex_ai/`** prefix → OpenAI-compatible SDK (Google Vertex AI models via proxy)

---

## Available Models

The following models are configured for routing in the BLAIQ system:

| Model | Provider | Best For |
|-------|----------|----------|
| `vertex_ai/claude-sonnet-4-6@default` | Google Vertex AI | Complex code generation, UI/Tailwind design |
| `aws-cris/eu.anthropic.claude-sonnet-4-6` | AWS Bedrock | High-quality reasoning, fallback code tasks |
| `gpt-4o-mini` | OpenAI (via BLAIQ proxy) | Fast planning, analysis, lightweight tasks |
| `gemini-2.5-pro` | Google (via BLAIQ proxy) | High-quality answers, multilingual content |
| `gpt-5.2` | OpenAI (via BLAIQ proxy) | Latest GPT capabilities, general tasks |
| `ovh-Qwen3-32B` | OVH Cloud | Fast alternative, budget-conscious workloads |
| `groq/llama-3.1-8b-instant` | Groq | Ultra-fast inference, pre-retrieval tasks |
| `groq/llama-3.3-70b-versatile` | Groq | Balanced quality/speed for post-retrieval |

---

## Model Selection by Task

### 1. GraphRAG Retriever Pipeline

**File:** `src/retriever/graphrag_retriever.py`

| Stage | Purpose | Default Model | Environment Variable | Why This Model |
|-------|---------|---------------|---------------------|----------------|
| **Pre-Retrieval** | Entity extraction, search term expansion | `groq/llama-3.1-8b-instant` | `LITELLM_PRE_MODEL` | Fast, cheap for simple extraction tasks |
| **Planner** | Query classification, search strategy | `groq/llama-3.1-8b-instant` | `LITELLM_PLANNER_MODEL` | Determines which search methods to use (vector/graph/keyword) |
| **Post-Retrieval** | Answer synthesis, citation generation | `openai/gpt-4o` | `LITELLM_POST_MODEL` | High-quality answers with proper citations |

### 2. Optimized Retriever API

**File:** `src/retriever/retriever_api_optimized.py`

| Task | Default Model | Environment Variable | Notes |
|------|---------------|---------------------|-------|
| Streaming Response | Same as Post-Retrieval | `LITELLM_POST_MODEL` | Uses `_invoke_llm_stream()` for SSE |
| COT (Chain of Thought) | Same as Planner | `LITELLM_PLANNER_MODEL` | For analytical queries |

### 3. Content Creator Agent

**File:** `src/agents/content_creator/agent.py`

| Task Type | Default Model | Environment Variable | Why This Model |
|-----------|---------------|---------------------|----------------|
| **Design/Code Generation** | `vertex_ai/claude-sonnet-4-6@default` | `CONTENT_DESIGN_MODEL` | Claude 4.6 Sonnet excels at complex HTML/Tailwind generation |
| **Gap Analysis/Strategy** | `gpt-4o-mini` | `CONTENT_ANALYSIS_MODEL` | Fast, cost-effective for analysis |
| **Fallback** | `gpt-4o-mini` | `OPENAI_MODEL` | General purpose fallback |

### 4. Orchestrator API

**File:** `src/orchestrator/orchestrator_api.py`

| Task | Default Model | Environment Variable | Purpose |
|------|---------------|---------------------|---------|
| Strategic Planning | `openai/gpt-4o-mini` | `LITELLM_STRATEGIST_MODEL` | Agent orchestration, task routing |
| Fallback | Same as Planner | `LITELLM_PLANNER_MODEL` | Uses planner if strategist not set |

### 5. Entity Finder (Pipeline)

**File:** `src/pipeline/entity_finder.py`

| Task | Default Model | Environment Variable |
|------|---------------|---------------------|
| Entity Extraction | `gpt-4o-mini` | `OPENAI_MODEL` |

### 6. Legacy RAG Retriever

**File:** `src/retriever/rag_retriever.py`

| Task | Default Model | Environment Variable |
|------|---------------|---------------------|
| Answer Generation | `gpt-4o-mini` | `OPENAI_MODEL` |
| Fallback | User-specified | `OPENAI_FALLBACK_MODEL` |

---

## Environment Variables Reference

### Core Model Variables

| Variable | Default | Used By | Description |
|----------|---------|---------|-------------|
| `LITELLM_PLANNER_MODEL` | `groq/llama-3.1-8b-instant` | GraphRAG Retriever | Query classification and planning |
| `LITELLM_PRE_MODEL` | `groq/llama-3.1-8b-instant` | GraphRAG Retriever | Pre-retrieval entity extraction |
| `LITELLM_POST_MODEL` | `openai/gpt-4o` | GraphRAG Retriever | Answer synthesis |
| `LITELLM_REFORMAT_MODEL` | `groq/llama-3.3-70b-versatile` | GraphRAG Retriever | Response reformatting (if enabled) |
| `LITELLM_STRATEGIST_MODEL` | `openai/gpt-4o-mini` | Orchestrator | Strategic planning |
| `OPENAI_MODEL` | `gpt-4o-mini` | Various Agents | General purpose default |
| `OPENAI_FALLBACK_MODEL` | None | All modules | Fallback on primary failure |

### Content Agent Specific

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_DESIGN_MODEL` | `vertex_ai/claude-sonnet-4-6@default` | HTML/UI generation |
| `CONTENT_ANALYSIS_MODEL` | `gpt-4o-mini` | Gap analysis |
| `GAP_ANALYSIS_MODEL` | `gpt-4o-mini` | Strategic analysis |

### Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | Required | API key for BLAIQ proxy |
| `OPENAI_API_BASE_URL` | `https://api.openai.com/v1` | Proxy endpoint |
| `GROQ_API_KEY` | Required if using Groq | Groq API key |

---

## How to Override Defaults

### Method 1: Environment File (.env)

Create or edit `.env` in the project root:

```bash
# Use Claude 4.6 for post-retrieval (high quality answers)
LITELLM_POST_MODEL=vertex_ai/claude-sonnet-4-6@default

# Use GPT-4o-mini for fast planning
LITELLM_PLANNER_MODEL=openai/gpt-4o-mini

# Set fallback for resilience
OPENAI_FALLBACK_MODEL=gemini-2.5-pro
```

### Method 2: Docker Compose Override

In `docker-compose.optimized.yml` or `docker-compose.agentic.yml`:

```yaml
services:
  retriever:
    environment:
      - LITELLM_POST_MODEL=vertex_ai/claude-sonnet-4-6@default
      - LITELLM_PLANNER_MODEL=gpt-4o-mini
```

### Method 3: Runtime Override (Per Request)

Some APIs accept model override in the request payload (check specific endpoint docs).

---

## Model Selection Strategy

### Cost-Optimized Setup (Development)

```bash
LITELLM_PRE_MODEL=groq/llama-3.1-8b-instant
LITELLM_PLANNER_MODEL=groq/llama-3.1-8b-instant
LITELLM_POST_MODEL=groq/llama-3.3-70b-versatile
OPENAI_MODEL=gpt-4o-mini
```

### Quality-Optimized Setup (Production)

```bash
LITELLM_PRE_MODEL=gpt-4o-mini
LITELLM_PLANNER_MODEL=gpt-4o
LITELLM_POST_MODEL=vertex_ai/claude-sonnet-4-6@default
OPENAI_FALLBACK_MODEL=gemini-2.5-pro
```

### Balanced Setup (Recommended)

```bash
LITELLM_PRE_MODEL=groq/llama-3.1-8b-instant      # Fast, cheap
LITELLM_PLANNER_MODEL=gpt-4o-mini                # Fast, good enough
LITELLM_POST_MODEL=openai/gpt-4o                 # High quality
OPENAI_FALLBACK_MODEL=gemini-2.5-pro             # Reliable fallback
```

---

## Provider Routing Logic

The routing is handled in `src/retriever/graphrag_retriever.py` by `_resolve_model_and_client()`:

```python
def _resolve_model_and_client(model: str):
    """
    Route to correct SDK client based on model prefix.
    """
    if "/" not in model:
        # Infer from model name
        if model.startswith("llama-") or model.startswith("mixtral-"):
            return _get_groq_client(), model
        else:
            return _get_openai_client(), model

    if model.startswith("groq/"):
        return _get_groq_client(), model.replace("groq/", "", 1)
    elif model.startswith("openai/"):
        return _get_openai_client(), model.replace("openai/", "", 1)
    else:
        # vertex_ai/, aws-cris/, etc. → OpenAI-compatible client
        return _get_openai_client(), model
```

---

## Special Handling

### Anthropic Models (Claude)

Claude models require special handling:
- Temperature forced to `1` (required by Bedrock/LiteLLM for thinking modes)
- `reasoning_effort` parameter is stripped
- Model name detection: contains "claude" or "anthropic"

### Reasoning Models (O1, QwQ)

- Temperature parameter is removed
- `max_tokens` mapped to `max_completion_tokens`
- Extended timeout (300s)

### Fallback Mechanism

If a model call fails:
1. Error is logged with `log_llm_event()`
2. If `OPENAI_FALLBACK_MODEL` is set and differs from current model, retry with fallback
3. If no fallback configured, exception is raised

---

## Debugging Model Selection

Set `DEBUG_LLM=true` to see model routing in logs:

```bash
DEBUG_LLM=true python src/retriever/graphrag_retriever.py
```

Log output includes:
- Provider (Groq/OpenAI)
- Model name
- Duration
- Token usage (if available)

---

## Related Files

| File | Purpose |
|------|---------|
| `src/retriever/graphrag_retriever.py` | Core retriever, `_invoke_llm()`, `_resolve_model_and_client()` |
| `src/retriever/retriever_api_optimized.py` | API layer, logging config at startup |
| `src/agents/content_creator/agent.py` | Content agent model selection |
| `src/orchestrator/orchestrator_api.py` | Orchestrator model selection |
| `src/pipeline/entity_finder.py` | Pipeline entity extraction |
| `src/retriever/rag_retriever.py` | Legacy retriever |
| `.env.example` | Example environment configuration |
| `docker-compose.optimized.yml` | Docker environment overrides |
| `docker-compose.agentic.yml` | Agentic deployment config |
