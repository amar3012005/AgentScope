# API Endpoints Reference (Frontend Ready)

This document is designed for fast frontend integration: clear routes, payloads, and response shapes.

## 1) Active Base URLs

Use the same paths for either host:

- Production: `https://second.amar.blaiq.ai`
- Alternate: `https://one.amar.blaiq.ai`
- Local: `http://localhost:8020`

## 2) Auth

### Retriever routes (currently open)
No auth required right now.

### Pipeline routes (when mounted)
Use Bearer auth:

```http
Authorization: Bearer <YOUR_API_KEY>
```

Also supported: `?api_key=<YOUR_API_KEY>`.

## 3) Common Frontend Defaults

```http
Content-Type: application/json
Accept: application/json
```

For SSE streaming:

```http
Accept: text/event-stream
```

---

## 4) Retriever API (Working Now)

### 4.1 Health
- `GET /`
- Purpose: service health + metadata

Response example:
```json
{
  "status": "healthy",
  "service": "GraphRAG Retriever API (Optimized)",
  "version": "4.0.0",
  "cache_stats": {
    "enabled": true,
    "connected": true,
    "hits": 58,
    "misses": 33,
    "hit_rate": 0.637,
    "ttl": 3600
  }
}
```

### 4.2 Config
- `GET /config`
- Purpose: UI boot config

Response example:
```json
{
  "qdrant_collection": "bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn",
  "default_mode": "local",
  "rerank_enabled": false
}
```

### 4.3 Query (non-stream)
- `POST /query/graphrag`
- Purpose: one-shot answer + retrieval diagnostics

Request payload:
```json
{
  "query": "Welche Montagevorteile bietet der SolvisLeo?",
  "k": 12,
  "debug": false,
  "generate_answer": true,
  "system_prompt": null,
  "user_prompt": null,
  "entity_extraction_prompt": null,
  "collection_name": "bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn",
  "qdrant_url": null,
  "qdrant_host": null,
  "qdrant_port": null,
  "qdrant_api_key": null,
  "use_cache": false,
  "mode": "local",
  "use_reranker": true,
  "rerank_top_k": 20,
  "session_id": "sess_ui_001",
  "content_mode": "DEFAULT"
}
```

Response shape:
```json
{
  "query": "...",
  "answer": "...",
  "chunks_retrieved": 12,
  "chunks": [
    {
      "chunk_id": "...",
      "doc_id": "...",
      "chunk_index": 0,
      "score": 0.123,
      "metadata": {
        "qdrant_id": "...",
        "retrieval_rank": 1,
        "page": 3
      },
      "text": "..."
    }
  ],
  "retrieval_stats": {
    "total_candidates": 86,
    "vector_chunks": 80,
    "graph_chunks": 0,
    "keyword_chunks": 0,
    "docid_chunks": 1,
    "adjacent_chunks": 15,
    "entities_extracted": ["SolvisLeo"],
    "parallel_timings": {
      "vector_search": 0.56,
      "graph_search": 0.0,
      "keyword_search": 0.21,
      "docid_search": 0.21,
      "total_parallel": 0.56
    },
    "top_docs": ["..."],
    "filter_label": "..."
  },
  "retrieval_time": 3.99,
  "answer_time": 17.13,
  "total_time": 21.12,
  "cached": false,
  "cache_stats": {
    "enabled": true,
    "connected": true
  }
}
```

Minimal curl:
```bash
curl -sS -X POST "https://second.amar.blaiq.ai/query/graphrag" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is SolvisLeo?","k":8,"collection_name":"bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn"}'
```

### 4.4 Query (streaming SSE)
- `POST /query/graphrag/stream`
- Purpose: token streaming to chat UI

Request payload (same core fields):
```json
{
  "query": "Warum soll SolvisLeo nicht als normaler Pufferspeicher kommuniziert werden?",
  "k": 12,
  "session_id": "sess_ui_stream_001",
  "collection_name": "bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn"
}
```

SSE events you should parse:
- `{"log":"..."}`
- `{"planning":{...}}`
- `{"delta":"token text"}`
- `{"metrics":{...}}`
- `[DONE]`

Minimal curl:
```bash
curl -N -X POST "https://second.amar.blaiq.ai/query/graphrag/stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"Welche Montagevorteile bietet SolvisLeo?","k":8,"session_id":"sess_ui_stream_001","collection_name":"bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn"}'
```

### 4.5 Session history
- `GET /history/{session_id}`
- Purpose: reload past chat messages

Response example:
```json
{
  "session_id": "sess_ui_stream_001",
  "tenant": "bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn",
  "history": [
    {"role": "user", "content": "...", "timestamp": 1772019718.4},
    {"role": "assistant", "content": "...", "timestamp": 1772019729.1}
  ]
}
```

### 4.6 Cache management
- `GET /cache/stats`
- `POST /cache/clear`

---

## 5) Debug Route (Local-Only in your current setup)

Available on local container:
- `POST /query/graphrag/debug`

Not currently exposed on `second.amar.blaiq.ai` OpenAPI.

Request:
```json
{
  "query": "What is SolvisLeo?",
  "k": 8,
  "generate_answer": false,
  "collection_name": "bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn"
}
```

Response:
```json
{
  "query": "...",
  "chunks_retrieved": 8,
  "retrieval_stats": {"...": "..."},
  "top_chunks": [{"doc_id": "...", "text": "..."}]
}
```

---

## 6) Pipeline API (When You Expose It)

Current `second.amar.blaiq.ai` does not mount pipeline routes yet. Once mounted, use these payloads.

### 6.1 Upload files
- `POST /upload`
- `multipart/form-data`

Form fields:
- `files` (repeatable)
- `folder_path` (e.g., `data/solvis`)
- `metadata` (JSON string, optional)

Example:
```bash
curl -sS -X POST "https://<pipeline-host>/upload" \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -F "files=@/absolute/path/doc1.pdf" \
  -F "files=@/absolute/path/doc2.txt" \
  -F "folder_path=data/solvis" \
  -F 'metadata={"doc1.pdf":{"created_user_name":"Amar","department":"Product"}}'
```

### 6.2 Start processing
- `POST /process`

Request payload:
```json
{
  "folder_path": "data/solvis",
  "steps": {
    "document_processing": true,
    "entity_extraction": false,
    "chunking": true,
    "vector_indexing": true,
    "entity_linking": false,
    "neo4j_ingestion": false
  },
  "force_reprocess": false,
  "quality_threshold": 0.5,
  "chunking_method": "semantic_embedding",
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "entity_extraction_config": null,
  "entity_template": null,
  "relationship_template": null,
  "qdrant_url": null,
  "collection_name": "bundb_app_blaiq_ai_knowledgeglobal_421771263939368kqddYuPaFFkbH-Mll4RPn",
  "recreate_collection": false,
  "neo4j_config": null,
  "cleanup": "none"
}
```

Response:
```json
{
  "job_id": "job_1772020000000",
  "status": "queued",
  "message": "Processing ...",
  "folder_path": "data/solvis"
}
```

### 6.3 Poll job status
- `GET /status/{job_id}`

Response:
```json
{
  "job_id": "job_...",
  "status": "queued|processing|completed|failed",
  "message": "Status: processing",
  "progress": {},
  "folder_path": "data/solvis",
  "error": null,
  "errors": null,
  "error_details": null
}
```

### 6.4 Get final result
- `GET /result/{job_id}`

### 6.5 File tree / flat list
- `GET /get-user-files?folder_name=data/solvis`
- `GET /get-user-files-flat?folder_name=data/solvis&page=1&limit=50&search=...`

### 6.6 Delete actions
- `POST /delete-file`
```json
{
  "folder_name": "data/solvis",
  "filenames": ["doc1.pdf", "doc2.txt"]
}
```

- `POST /delete-folder`
```json
{
  "folder_name": "data/solvis"
}
```

### 6.7 DB cleanup for a document
- `DELETE /document/qdrant?doc_id=<doc_id>&collection_name=<collection>&filter_label=<tenant>`
- `DELETE /document/neo4j?doc_id=<doc_id>&filter_label=<tenant>`

---

## 7) Frontend Feature Mapping

- Chat ask button: `POST /query/graphrag`
- Streaming chat mode: `POST /query/graphrag/stream`
- Conversation restore: `GET /history/{session_id}`
- Show retrieval diagnostics panel: read `retrieval_stats` in non-stream response
- Clear server cache button (admin): `POST /cache/clear`
- System status badge: `GET /` + `GET /config`
- Ingestion UI (when pipeline exposed): `/upload`, `/process`, `/status/{job_id}`, `/result/{job_id}`

---

## 8) Current Non-Working Paths (avoid in frontend)

- `/retriever/*` on `second.amar.blaiq.ai` (404)
- `/pipeline/*` on `second.amar.blaiq.ai` (404)
- `/query/rag` (not in optimized retriever)
- `/status` on retriever (not in optimized retriever)

Use root-based retriever routes listed above.
