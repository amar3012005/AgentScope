# BLAIQ Frontend-Backend Integration Fixes

## Changes Made

### 1. CORS Added to All Services
The following files were updated to add CORS middleware:

- ✅ `src/orchestrator/orchestrator_api.py` - Already had CORS
- ✅ `src/agents/echo/agent.py` - Added CORS
- ✅ `src/agents/content_creator/agent.py` - Already had CORS
- ✅ `src/retriever/retriever_api_optimized.py` - Already had CORS
- ✅ `src/pipeline/pipeline_api.py` - Added CORS

### 2. Frontend Ports Fixed
Updated `static/core_client.html` and `static/agents.html`:
- Orchestrator: `6080` (was `6000`)
- Echo Agent: `6002` (was `8001`)
- Content Creator: `6003` (was `8002`)
- GraphRAG: `6001`

### 3. Health Check Added
Frontend now checks all services on page load and shows status in logs.

### 4. File Upload Added
Added document upload functionality to `static/core_client.html`:
- Upload section in sidebar with drag-and-drop support
- Supports PDF, DOCX, TXT, MD files
- Files are chunked, embedded, and stored in Qdrant
- Entities extracted and stored in Neo4j
- Upload status feedback in UI

## How to Apply Changes

### Step 1: Restart Docker Containers
The code changes require container restart to take effect:

```bash
cd /Users/amar/blaiq

# Stop existing containers
docker-compose -f docker-compose.agentic.yml down

# Rebuild and start
docker-compose -f docker-compose.agentic.yml up --build -d

# Wait for services to be healthy (about 30-60 seconds)
docker-compose -f docker-compose.agentic.yml ps
```

### Step 2: Verify Services
Check all services are running:

```bash
# Check orchestrator
curl http://localhost:6080/

# Check GraphRAG
curl http://localhost:6001/

# Check Echo Agent
curl http://localhost:6002/

# Check Content Creator
curl http://localhost:6003/
```

### Step 3: Test Frontend

1. Open `http://localhost:6080/static/api_test.html` for quick API testing
2. Open `http://localhost:6080/static/core_client.html` for the main chat UI

### Step 4: Test File Upload

1. Open `http://localhost:6080/static/core_client.html`
2. Look for the "Knowledge Base" section in the left sidebar
3. Click the upload area or drag-and-drop files
4. Supported formats: PDF, DOCX, TXT, MD
5. Watch the upload status and logs for processing results

**Upload via API:**
```bash
curl -X POST http://localhost:6080/upload \
  -F "file=@/path/to/document.pdf" \
  -F "tenant_id=default"
```

## Port Mapping Reference

| Service | Container Port | Host Port | URL |
|---------|---------------|-----------|-----|
| Orchestrator | 6000 | 6080 | http://localhost:6080 |
| GraphRAG | 6001 | 6001 | http://localhost:6001 |
| Echo Agent | 6002 | 6002 | http://localhost:6002 |
| Content Creator | 6003 | 6003 | http://localhost:6003 |

## API Endpoints

### Orchestrator
- `GET /` - Health check
- `GET /agents` - List all agents
- `GET /agents/live` - List live agents
- `POST /orchestrate` - Main orchestration endpoint
- `POST /upload` - Upload documents for processing (PDF, DOCX, TXT, MD)

**Payload format for /orchestrate:**
```json
{
  "task": "your message here",
  "target_agent": "blaiq-graph-rag",
  "payload": {},
  "protocol": "auto",
  "method": "POST"
}
```

**Upload format (multipart/form-data):**
```
POST /upload
Content-Type: multipart/form-data

Fields:
- file: (binary file content)
- tenant_id: (optional, default: "default")
- metadata: (optional JSON string)
```

### Echo Agent
- `GET /` - Health check
- `POST /execute` - Echo endpoint

**Payload format:**
```json
{
  "task": "message to echo",
  "payload": {}
}
```

### Content Creator
- `GET /` - Health check
- `POST /execute` - Content generation endpoint

**Payload format:**
```json
{
  "task": "create a poster for...",
  "payload": {}
}
```

## Troubleshooting

### 422 Unprocessable Entity
If you get this error, check:
1. Content-Type header is set to `application/json`
2. Request body is valid JSON
3. Required fields are present (at minimum `task`)

### CORS Errors
If you see CORS errors in browser console:
1. Make sure containers are rebuilt with the changes
2. Check that CORS middleware is added to the service
3. Verify you're accessing the right port

### Connection Refused
If you get connection errors:
1. Check containers are running: `docker-compose -f docker-compose.agentic.yml ps`
2. Verify port mappings: `docker-compose -f docker-compose.agentic.yml config`
3. Check service logs: `docker logs blaiq-core`

## Testing

Use the test page at `/static/api_test.html` to verify:
- All services respond to GET requests
- POST to /orchestrate works
- POST to /execute works for agents

## Next Steps

Once everything is working:
1. Use the main chat UI at `/static/core_client.html`
2. Select an agent from the sidebar (Echo or Content Creator)
3. Or send a message without selecting to route through GraphRAG
4. Upload documents via the Knowledge Base section in the sidebar
5. Check the logs panel (bottom right) for real-time status
