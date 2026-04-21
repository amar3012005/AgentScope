# Vangogh Content Agent Overview

## What It Is

The Vangogh content agent is the BLAIQ content creation service. It acts as a strategic creative director that turns raw project context into a structured content brief and, when possible, a final HTML artifact.

It is not a generic text generator. Its job is to:

- understand the task,
- fetch supporting context,
- decide whether enough information exists,
- ask targeted HITL questions when needed,
- extract a structured schema,
- generate a premium HTML response.

## Core Capabilities

- Context-aware content synthesis
- GraphRAG-backed retrieval of project context
- Gap analysis and HITL gating
- Structured schema extraction for downstream rendering
- Premium HTML generation with Tailwind-based output
- REST and SSE execution modes
- WebSocket worker mode for orchestrator dispatch
- Correlation-aware logging for `session_id`, `thread_id`, `mission_id`, and `orchestrator_request_id`

## High-Level Flow

1. A task arrives through `/execute`, `/stream`, or the WebSocket worker.
2. The agent merges the payload and opportunistically extracts MCP correlation IDs from `x-mcp-envelope`.
3. It loads GraphRAG context either from orchestrator helper outputs or by calling the GraphRAG service directly.
4. It runs gap analysis against the request, checklist, and Brand DNA.
5. If the request is underspecified, it returns `blocked_on_user` with exactly 4 questions.
6. If enough context exists, it runs schema extraction.
7. It generates a premium HTML artifact from the structured schema.
8. It returns success with `html_artifact`, or an error if a stage fails.

## Request Entry Points

### `POST /execute`

Synchronous request path.

Behavior:

- builds a merged payload from `task`, `query`, and `payload`
- parses correlation IDs from `x-mcp-envelope` when present
- logs `execute_start`
- runs the full content pipeline
- returns JSON with:
  - `agent`
  - `received_task`
  - `payload`
  - `result`

### `POST /stream`

Streaming request path.

Behavior:

- emits SSE status events
- logs `stream_start`
- runs the same pipeline as `/execute`
- returns:
  - `blocked` when HITL is required
  - `success` when HTML is generated
  - `error` when a stage fails

### WebSocket Worker

The background worker connects to the core orchestrator WS endpoint and executes task messages.

Behavior:

- connects to `ws://blaiq-core:6000/ws/agents/blaiq-content-agent`
- waits for `type=task`
- runs `process_task(...)`
- sends a `type=result` message back to core

## Decision Logic

### 1. Context Source

The content agent prefers helper output from core when available:

- `strategy_helper_outputs["blaiq-graph-rag"]`

If that is missing, it calls GraphRAG directly.

### 2. Gap Analysis

The gap-analysis stage checks whether the request is specific enough to proceed.

If gaps exist, it returns:

- `status: "blocked_on_user"`
- `analysis`
- `questions` with exactly 4 items

For BLAIQ Core NotebookLM source-pack requests, those questions are forced toward:

- architecture documents to include
- evidence flow / proof sources
- GraphRAG flow / retrieval behavior
- content generator behavior and output format

### 3. Schema Extraction

If the user has provided answers, the agent sends the raw context plus answers into the schema prompt and expects strict JSON back.

The schema output includes:

- strategic pillars
- KPIs
- timeline
- target audience
- vision statement
- technical infrastructure

### 4. Design Generation

The final stage turns the structured schema into a single standalone HTML5 document.

The design prompt is tuned for:

- dark-mode UI
- Tailwind CSS classes
- bento-grid layout
- glassmorphism cards
- strong typography contrast

## Logging and Observability

The agent uses service-differentiated, relative-time logs:

- `svc=blaiq-content-agent`
- `rel=<ms since process start>`

Important flow logs include:

- `brand_dna_load_start`
- `skill_loader_init_complete`
- `execute_start`
- `stream_start`
- `task_start`
- `context_source`
- `graphrag_context_fetch_start`
- `gap_analysis_start`
- `gap_analysis_complete`
- `gap_analysis_gate`
- `design_pipeline_start`
- `design_generation_start`
- `design_generation_complete`
- `design_pipeline_error`

This keeps the logs useful without flooding them with every internal step.

## What It Is Good At

- Turning vague creative requests into a usable clarification loop
- Producing a final artifact when the request is sufficiently specified
- Carrying the right correlation IDs through the pipeline
- Working both as a direct REST service and as a worker behind core

## What It Is Not Good At Yet

- It is still dependent on a good GraphRAG result for best quality.
- The design prompt is strong, but not yet a full NotebookLM document assembler by itself.
- If the request is broad, it will correctly stop for HITL rather than inventing structure.

## Practical Summary

Vangogh is the BLAIQ content synthesis agent. It reads context, decides whether it has enough signal, asks the right questions when it does not, then produces a structured schema and a premium HTML artifact when it does.

