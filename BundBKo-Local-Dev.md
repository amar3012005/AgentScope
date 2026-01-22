## 🚀 Quick Start (Local)

### Prerequisites

```bash
# Required
- macOS/Linux/Windows
- Docker Desktop (for Qdrant)
- Python 3.12.x (recommended)
- uv (Python package manager; optional but recommended)

# Services (local or cloud)
- Qdrant (localhost:6333 for local)
- (Optional) Neo4j (localhost:7687) — only if graph features are enabled
```

### Installation

```bash
# 1) Check Python
python3 --version           # Expect: Python 3.12.x

# 2) Create & activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows (PowerShell): .\.venv\Scripts\Activate.ps1

# 3) Upgrade pip (optional)
python -m pip install --upgrade pip
```

#### Install with uv (recommended)

```bash
# Install uv (macOS/Linux)
# Windows users: see https://docs.astral.sh/uv/
/bin/bash -c "$(curl -fsSL https://astral.sh/uv/install.sh)"

uv --version

# Create venv with Python 3.12 and sync from lockfile
uv venv --python 3.12
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
uv sync --frozen            # uses uv.lock for fully reproducible installs
# (Alternatively) uv sync   # resolves from pyproject.toml if no lockfile
```

### Environment

Create a `.env` file in the project root (minimum for local vector-only mode):

```env
# API auth (required)
API_KEY=dev-secret-123      # or: API_KEYS=key1,key2,key3

# Qdrant (local)
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_URL=                 # leave empty to prefer HOST/PORT

# OpenAI (answer LLM; optional but recommended)
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini

# Neo4j (not used in vector-only mode; safe to leave as-is)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j
```

> **Important:** If `QDRANT_URL` is set, it takes precedence over `QDRANT_HOST/PORT`.
> For local Qdrant, keep `QDRANT_URL` **empty**.
> After editing `.env`, **restart** both Uvicorn processes to reload variables.

### Start Qdrant (Docker)

```bash
docker run -d --name qdrant \
  -p 6333:6333 \
  -v qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest

# Health check
curl http://localhost:6333/ready
# Windows PowerShell: Invoke-WebRequest http://localhost:6333/ready
```

### Run APIs (two terminals)

```bash
# Terminal A — Pipeline API (upload/process)
uvicorn src.pipeline.main:app --host 0.0.0.0 --port 8000

# Terminal B — Retriever API (query/answer)
uvicorn src.retriever.retriever_api:app --host 0.0.0.0 --port 8001
```

### API Authentication (Local)

APIs require a key:

1. Add `API_KEY` (or `API_KEYS`) in `.env` (see above).
2. **Restart** both Uvicorn processes.
3. Include the header in every request:

   * `-H "x-api-key: dev-secret-123"`
   * (Some setups also accept `Authorization: Bearer <key>`)

### Smoke Test

```bash
# Prepare a tiny sample
mkdir -p data
echo "Hello GraphRAG. Tiny test about AI and RAG." > data/demo.txt

# 1) Upload
curl -X POST "http://localhost:8000/upload" \
  -H "x-api-key: dev-secret-123" \
  -F "files=@data/demo.txt"

# 2) Process (vector-only: document_processing + chunking + vector_indexing)
curl -X POST "http://localhost:8000/process" \
  -H "x-api-key: dev-secret-123" \
  -H "Content-Type: application/json" \
  -d '{"folder_path":"data/"}'

# 3) Query
curl -X POST "http://localhost:8001/query" \
  -H "x-api-key: dev-secret-123" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is this document about?"}'
```

### Common Issues

* **`python -m venv` not found** → Use `python3 -m venv` or `uv venv --python 3.12`.
  Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
* **No `requirements.txt`** → This project uses `pyproject.toml` + `uv.lock`. Use `uv sync --frozen`.
* **401 Unauthorized** → Set `API_KEY` in `.env` and pass `-H "x-api-key: ..."` on every request.
* **Connected to remote Qdrant** → Ensure `QDRANT_URL` is empty to force `localhost:6333`.
  If there's a value remaining in the shell, run `unset QDRANT_URL` (in bash/zsh), then restart.
* **Port conflicts** → Check `lsof -i :6333`/`:8000`/`:8001` and stop the conflicting process.