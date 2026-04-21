# BLAIQ Pipeline - Hybrid Orchestration, Retrieval, and Rendering System

A production pipeline that combines browser-held conversation state, CORE orchestration, GraphRAG retrieval, template-driven artifact rendering, HITL clarification, and governance into one progressive workflow.

If you only read one architecture doc, read [docs/PIPELINE_ARCHITECTURE.md](docs/PIPELINE_ARCHITECTURE.md).

---

## 🚀 API Quick Reference

### Live Endpoints (Production)

- **Pipeline API**: https://second.amar.blaiq.ai/pipeline
- **Retriever API**: https://second.amar.blaiq.ai/retriever
- **Qdrant Vector DB**: https://qdrant.api.blaiq.ai

**Note**: All endpoints are secured with HTTPS and Let's Encrypt certificates.

### Authentication

All API endpoints require authentication via API key:
```bash
-H "X-API-Key: ************"
```

---

## 📋 Table of Contents

1. [API Documentation (Pipeline)](#-api-documentation)
   - [Upload with Metadata](#1-upload-documents-with-metadata)
   - [Folder Path Management](#understanding-folder_path)
   - [File Management](#-file-management-api-new)
   - [Pipeline Processing](#3-start-pipeline-processing)
   - [Database Document Deletion](#-database-document-deletion)
   - [Direct Qdrant Access](#-direct-qdrant-access)
2. [Retriever API (NEW)](#-retriever-api)
   - [RAG Query (Vector + Keyword)](#1-rag-query-vector--keyword)
   - [GraphRAG Query (Graph + Vector + Keyword)](#2-graphrag-query-graph--vector--keyword)
   - [Graph Visualization](#graph-visualization)
   - [Custom Prompts](#custom-prompts)
3. [Metadata System](#-metadata-system)
4. [Multi-Tenant Isolation](#-multi-tenant-isolation)
5. [System Overview](#-system-overview)
6. [Configuration](#-configuration)
7. [Deployment](#-deployment)
8. [Monitoring & Logging](#-monitoring--logging)
9. [Security Best Practices](#-security-best-practices)

---

## 🌐 API Documentation

### Pipeline API Examples

Base URL: `https://second.amar.blaiq.ai/pipeline`  
Version: `2.3.0`

#### 1. Upload Documents with Metadata

**Endpoint**: `POST /upload`

Upload documents with flexible metadata that will be stored in Qdrant for filtering and retrieval.

**Supported formats**: PDF, DOCX, PPTX, XLSX, TXT, MD
```bash
# Upload with metadata
curl -X POST "https://second.amar.blaiq.ai/pipeline/upload" \
  -H "X-API-Key: ************" \
  -F "files=@report_q1.pdf" \
  -F "files=@meeting_notes.txt" \
  -F "folder_path=data/user01" \
  -F 'metadata={
    "report_q1.pdf": {
      "created_at": "2025-10-28T10:30:00Z",
      "created_user_id": "user_123",
      "created_user_name": "Oliver Ilnicki",
      "department": "Engineering",
      "project": "GraphRAG",
      "priority": "high",
      "tags": "quarterly,finance"
    },
    "meeting_notes.txt": {
      "created_at": "2025-10-28T14:00:00Z",
      "created_user_id": "user_456",
      "created_user_name": "Jane Smith",
      "department": "Sales",
      "meeting_type": "team_sync"
    }
  }'
```

**Response**:
```json
{
  "uploaded": 2,
  "failed": 0,
  "folder_path": "data/user01",
  "files": [
    {
      "filename": "report_q1.pdf",
      "saved_as": "report_q1.pdf",
      "path": "data/user01/report_q1.pdf",
      "size_bytes": 245678,
      "metadata": {
        "created_at": "2025-10-28T10:30:00Z",
        "created_user_id": "user_123",
        "department": "Engineering",
        "project": "GraphRAG",
        "priority": "high"
      }
    }
  ],
  "errors": null
}
```

**Directory Structure After Upload**:
```
data/
└── user01/
    ├── report_q1.pdf
    ├── meeting_notes.txt
    └── _metadata/
        ├── report_q1.pdf.json
        └── meeting_notes.txt.json
```

#### Understanding `folder_path`

The `folder_path` parameter is **critical** for organizing multi-tenant or multi-project data:

**Key Principles**:
1. **Upload and Process must use the SAME `folder_path`**
2. Files and metadata are stored in `{folder_path}/`
3. Pipeline creates `{folder_path}/_pipeline/` for processing artifacts
4. Metadata stored in `{folder_path}/_metadata/`

**Examples**:

**Single User/Project** (default):
```bash
# Upload
-F "folder_path=data"  # or omit (defaults to "data")

# Process
"folder_path": "data"
```

**Multi-User Setup**:
```bash
# Upload for User 1
-F "folder_path=data/user01"

# Process User 1's documents
"folder_path": "data/user01"

# Upload for User 2
-F "folder_path=data/user02"

# Process User 2's documents
"folder_path": "data/user02"
```

**Multi-Tenant/Project Structure**:
```bash
# Customer A, Project X
-F "folder_path=data/customers/acme_corp/project_x"

# Customer B, Q1 Reports
-F "folder_path=data/customers/techstart/reports/q1_2025"
```

**⚠️ Common Mistake**:
```bash
# ❌ WRONG - Mismatched paths
curl ... -F "folder_path=data/user01"  # Upload
{"folder_path": "data"}                # Process - WRONG!

# ✅ CORRECT - Matching paths
curl ... -F "folder_path=data/user01"  # Upload
{"folder_path": "data/user01"}         # Process - CORRECT!
```

#### 2. Upload Without Metadata
```bash
# Simple upload (metadata will be empty but structure preserved)
curl -X POST "https://second.amar.blaiq.ai/pipeline/upload" \
  -H "X-API-Key: ************" \
  -F "files=@document.pdf" \
  -F "folder_path=data/user01"
```

Metadata file `data/user01/_metadata/document.pdf.json` will contain `{}`.

---

## 📁 File Management API (NEW)

The Pipeline API now includes comprehensive file management capabilities with built-in security features.

### 🔒 Security Features

- **Path Traversal Protection**: Prevents `..` and absolute paths
- **Root Protection**: Cannot delete the `data/` root directory
- **Scope Isolation**: All operations restricted to `data/` directory
- **Validation**: All paths validated before operations

---

### 1. Get File Tree Structure

**Endpoint**: `GET /get-user-files`

Retrieve a hierarchical tree structure of files and folders (like Unix `tree` command).

**Query Parameters**:
- `folder_name` (optional): Folder path to list (default: `"data"`)
```bash
# Get entire data directory structure
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files?folder_name=data" \
  -H "X-API-Key: ************"

# Get specific user's files
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files?folder_name=data/user01" \
  -H "X-API-Key: ************"
```

**Response**:
```json
{
  "folder_name": "data/user01",
  "total_files": 5,
  "total_directories": 2,
  "total_size_bytes": 2097152,
  "tree": [
    {
      "name": "reports",
      "type": "directory",
      "path": "user01/reports",
      "size_bytes": 524288,
      "children": [
        {
          "name": "report_2024.docx",
          "type": "file",
          "path": "user01/reports/report_2024.docx",
          "size_bytes": 524288,
          "children": null
        }
      ]
    },
    {
      "name": "document1.pdf",
      "type": "file",
      "path": "user01/document1.pdf",
      "size_bytes": 1048576,
      "children": null,
      "metadata": {
        "fileId": "11764778724071e_hdL79Q3UapiHjZoLia1",
        "created_user_id": 1,
        "created_user_name": "BundB Master",
        "created_at": "2025-12-03T16:18:44.071Z",
        "fileName": "document1.pdf"
      }
    },
    {
      "name": "notes.txt",
      "type": "file",
      "path": "user01/notes.txt",
      "size_bytes": 524288,
      "children": null,
      "metadata": null
    }
  ]
}
```

**Note**: The API automatically includes `metadata` field for each file by reading `{folder_path}/_metadata/{filename}.json`. The metadata structure is fully customizable based on your frontend requirements.

**Use Cases**:
- Display user's uploaded files in UI
- Audit file organization
- Calculate storage usage per user
- Browse folder structure before processing

---

### 2. Get Flat File List (Paginated)

**Endpoint**: `GET /get-user-files-flat`

Retrieve a flat, paginated list of files with optional search filtering. Unlike `/get-user-files` which returns hierarchical tree structure, this endpoint provides a simple list view optimized for table displays and pagination.

**Query Parameters**:
- `folder_name` (optional): Folder path to list (default: `"data"`)
- `page` (optional): Page number, 1-based (default: `1`)
- `limit` (optional): Items per page, max 200 (default: `50`)
- `search` (optional): Search string, min 2 characters (filters by filename, created_user_name, created_user_id)

**Sorting**: Files are sorted by **newest first** using `metadata.created_at` (ISO timestamp, if available), otherwise falls back to filesystem modification time (`mtime`).

```bash
# Get first page (50 items)
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files-flat?folder_name=data/user01" \
  -H "X-API-Key: ************"

# Get second page with custom limit
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files-flat?folder_name=data/user01&page=2&limit=100" \
  -H "X-API-Key: ************"

# Search for specific files
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files-flat?folder_name=data&search=report" \
  -H "X-API-Key: ************"
```

**Response**:
```json
{
  "folder_name": "data/user01",
  "total_files": 23,
  "total_directories": 3,
  "total_size_bytes": 5242880,
  "page": 1,
  "limit": 50,
  "has_more": false,
  "files": [
    {
      "name": "document1.pdf",
      "type": "file",
      "path": "user01/document1.pdf",
      "size_bytes": 1048576,
      "children": null,
      "metadata": {
        "fileId": "11764778724071e_hdL79Q3UapiHjZoLia1",
        "created_user_id": 1,
        "created_user_name": "BundB Master",
        "created_at": "2025-12-03T16:18:44.071Z",
        "fileName": "document1.pdf"
      }
    },
    {
      "name": "report_2024.docx",
      "type": "file",
      "path": "user01/reports/report_2024.docx",
      "size_bytes": 524288,
      "children": null,
      "metadata": {
        "created_user_id": 2,
        "created_user_name": "Oliver Ilnicki",
        "department": "Engineering"
      }
    }
  ]
}
```

**Key Differences from `/get-user-files`**:

| Feature | `/get-user-files` | `/get-user-files-flat` |
|---------|-------------------|------------------------|
| Structure | Hierarchical tree | Flat list |
| Pagination | No | Yes (page, limit) |
| Search | No | Yes (filename, metadata) |
| Directories | Included in tree | Excluded from list |
| Use Case | Folder browsing | Table display, infinite scroll |

**Use Cases**:
- Display paginated file tables in UI
- Implement infinite scroll or "Load More" functionality
- Search for files by name or creator
- Optimize performance for large directories (1000+ files)
- Build file management dashboards

---

### 3. Delete Multiple Files

**Endpoint**: `POST /delete-file`

Delete multiple files from a specific folder. Returns detailed results for each file.

**Request Body**:
```json
{
  "folder_name": "data/user01",
  "filenames": ["document1.pdf", "notes.txt", "old_file.docx"]
}
```
```bash
# Delete multiple files
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-file" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "folder_name": "data/user01",
    "filenames": ["document1.pdf", "notes.txt", "old_file.docx"]
  }'
```

**Response**:
```json
{
  "folder_name": "data/user01",
  "total_requested": 3,
  "deleted": 2,
  "not_deleted": 1,
  "deleted_files": [
    "document1.pdf",
    "notes.txt"
  ],
  "not_deleted_files": [
    {
      "filename": "old_file.docx",
      "reason": "File not found"
    }
  ]
}
```

**Common Reasons for Not Deleted**:
- `"File not found"` - File doesn't exist
- `"Not a file (directory or special file)"` - Target is a directory
- `"Permission denied"` - Insufficient permissions
- `"File outside target folder"` - Security violation

**Automatic Cleanup**:

When deleting files, the system automatically cleans up:
- **Metadata files**: `_metadata/{filename}.json`
- **Pipeline artifacts**: Processing intermediates in `_pipeline/`
  - `step1_processed/texts/` and `metadata/`
  - `step2_entities/`
  - `step3_chunks/chunks/`
  - `step5_linked/`

This ensures no orphaned data remains after file deletion.

**Use Cases**:
- Clean up old documents after processing
- Remove uploaded files with errors
- User-initiated file deletion
- Batch cleanup operations

---

### 4. Delete Entire Folder

**Endpoint**: `POST /delete-folder`

Delete an entire folder and all its contents recursively.

**⚠️ CRITICAL**: Cannot delete the root `data/` directory (protected).

**Request Body**:
```json
{
  "folder_name": "data/user01"
}
```
```bash
# Delete user folder
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-folder" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "folder_name": "data/user01"
  }'
```

**Response**:
```json
{
  "folder_name": "data/user01",
  "deleted": true,
  "message": "Successfully deleted folder 'data/user01' and all contents",
  "files_deleted": 12
}
```

**Security - Protected Operations**:
```bash
# ❌ BLOCKED: Attempt to delete root directory
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-folder" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_name": "data"}'

# Response: HTTP 403 Forbidden
{
  "detail": "Cannot delete protected folder: data. Root 'data' directory is protected."
}

# ❌ BLOCKED: Path traversal attempt
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-folder" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_name": "data/../etc"}'

# Response: HTTP 400 Bad Request
{
  "detail": "Path traversal not allowed"
}

# ❌ BLOCKED: Absolute path outside data/
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-folder" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_name": "/etc/passwd"}'

# Response: HTTP 400 Bad Request
{
  "detail": "Path traversal not allowed"
}
```

**Use Cases**:
- Remove user account data
- Clean up completed projects
- Delete temporary processing folders
- Tenant offboarding

---

### File Management Workflow Examples

#### Example 1: User Offboarding
```bash
# 1. Check what files exist
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files?folder_name=data/user01" \
  -H "X-API-Key: ************"

# 2. Backup important files (application logic)

# 3. Delete user's folder
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-folder" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_name": "data/user01"}'
```

#### Example 2: Selective File Cleanup
```bash
# 1. List all files
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files?folder_name=data/project_x" \
  -H "X-API-Key: ************"

# 2. Delete only temporary files
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-file" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "folder_name": "data/project_x",
    "filenames": ["temp_draft.pdf", "old_version.docx", "test_data.txt"]
  }'
```

#### Example 3: Audit Storage Usage
```python
import requests
import json

API_KEY = "************"
BASE_URL = "https://second.amar.blaiq.ai/pipeline"

def get_storage_report(folder):
    """Get storage usage for a folder"""
    response = requests.get(
        f"{BASE_URL}/get-user-files",
        headers={"X-API-Key": API_KEY},
        params={"folder_name": folder}
    )
    data = response.json()
    
    print(f"Folder: {data['folder_name']}")
    print(f"Files: {data['total_files']}")
    print(f"Directories: {data['total_directories']}")
    print(f"Total Size: {data['total_size_bytes'] / 1024 / 1024:.2f} MB")
    
    return data

# Get storage for all users
users = ["user01", "user02", "user03"]
total_size = 0

for user in users:
    data = get_storage_report(f"data/{user}")
    total_size += data['total_size_bytes']
    print("-" * 50)

print(f"\nTotal Storage: {total_size / 1024 / 1024:.2f} MB")
```

---

#### 3. Start Pipeline Processing

**Endpoint**: `POST /process`

Process uploaded documents and index them in Qdrant with metadata.

**Cleanup strategies**:
```python
cleanup = "none"        # Keep everything (original files + processing artifacts)
cleanup = "subfolders"  # Keep original documents + metadata, delete _pipeline/
cleanup = "all"         # Delete entire folder (for temporary/one-time processing)
```

**⚠️ CRITICAL**: Use the **exact same `folder_path`** as used in upload!
```bash
curl -X POST "https://second.amar.blaiq.ai/pipeline/process" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "folder_path": "data/user01",
    "steps": {
      "document_processing": true,
      "entity_extraction": false,
      "chunking": true,
      "vector_indexing": true,
      "entity_linking": false,
      "neo4j_ingestion": false
    },
    "chunking_method": "semantic_embedding",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "collection_name": "user01_documents",
    "recreate_collection": false,
    "cleanup": "none"
  }'
```

**Response**:
```json
{
  "job_id": "job_1761667639115",
  "status": "queued",
  "message": "Processing 2 files with steps: document_processing, chunking, vector_indexing",
  "folder_path": "data/user01"
}
```

**Directory Structure After Processing**:
```
data/
└── user01/
    ├── report_q1.pdf
    ├── meeting_notes.txt
    ├── _metadata/
    │   ├── report_q1.pdf.json
    │   └── meeting_notes.txt.json
    └── _pipeline/
        ├── step1_processed/
        │   ├── texts/
        │   └── metadata/
        └── step3_chunks/
            └── chunks/
```

**Pipeline Parameters Reference**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `folder_path` | string | **required** | Path to documents (e.g., `data/user01`) |
| `collection_name` | string | `graphrag_chunks` | Qdrant collection name (also Neo4j filter_label) |
| `steps.document_processing` | bool | true | Extract text from documents |
| `steps.chunking` | bool | true | Create semantic chunks |
| `steps.vector_indexing` | bool | true | Index chunks in Qdrant |
| `steps.entity_extraction` | bool | false | Extract entities with LLM |
| `steps.entity_linking` | bool | false | Link entities to chunks |
| `steps.neo4j_ingestion` | bool | false | Ingest into Neo4j graph |
| `chunking_method` | string | `semantic_embedding` | `simple` or `semantic_embedding` |
| `chunk_size` | int | 1000 | Target chunk size in tokens |
| `chunk_overlap` | int | 200 | Overlap between chunks in tokens |
| `force_reprocess` | bool | false | Reprocess already processed documents |
| `quality_threshold` | float | 0.5 | Minimum extraction quality (0-1) |
| `recreate_collection` | bool | false | Recreate Qdrant collection if exists |
| `cleanup` | string | `none` | Cleanup strategy: `none`, `subfolders`, `all` |
| `qdrant_url` | string | null | Override Qdrant URL |
| `entity_extraction_config.chunk_size` | int | 4000 | Chunk size for entity extraction |
| `entity_extraction_config.max_workers` | int | 4 | Parallel workers for extraction |
| `entity_template` | object | null | Custom entity types JSON schema |
| `relationship_template` | object | null | Custom relationship types JSON schema |
| `neo4j_config.uri` | string | env var | Neo4j URI (e.g., `bolt://host:7687`, in our production: `neo4j+s://neo4j.api.blaiq.ai:7689`) |
| `neo4j_config.user` | string | env var | Neo4j username |
| `neo4j_config.password` | string | env var | Neo4j password |

#### 4. Check Job Status
```bash
curl "https://second.amar.blaiq.ai/pipeline/status/job_1761667639115" \
  -H "X-API-Key: ************"
```

**Response**:
```json
{
  "job_id": "job_1761667639115",
  "status": "completed",
  "message": "Status: completed",
  "progress": {
    "step": "vector_indexing",
    "status": "completed"
  },
  "folder_path": "data/user01"
}
```

#### 5. Get Processing Results
```bash
curl "https://second.amar.blaiq.ai/pipeline/result/job_1761667639115" \
  -H "X-API-Key: ************"
```

**Response**:
```json
{
  "job_id": "job_1761667639115",
  "status": "completed",
  "folder_path": "data/user01",
  "steps_executed": {
    "document_processing": true,
    "chunking": true,
    "vector_indexing": true
  },
  "documents_processed": 2,
  "chunks_created": 15,
  "vectors_indexed": 15,
  "processing_time": 8.5,
  "cleanup_performed": "none",
  "errors": []
}
```

---

## 🗑️ Database Document Deletion

Delete processed documents from Qdrant and Neo4j databases while maintaining data integrity.

### Delete from Qdrant

**Endpoint**: `DELETE /document/qdrant`

Remove all vector embeddings for a specific document from Qdrant collection.

**Query Parameters**:
- `doc_id`: Document ID to delete
- `collection_name`: Qdrant collection name
- `filter_label`: Tenant filter label

```bash
curl -X DELETE "https://second.amar.blaiq.ai/pipeline/document/qdrant?doc_id=report_q1_abc123&collection_name=user01_documents&filter_label=user01_documents" \
  -H "X-API-Key: ************"
```

**Response**:
```json
{
  "deleted": 15,
  "collection_name": "user01_documents",
  "doc_id": "report_q1_abc123",
  "filter_label": "user01_documents"
}
```

---

### Delete from Neo4j

**Endpoint**: `DELETE /document/neo4j`

Remove document, chunks, orphaned entities, and relationships from Neo4j graph.

**Orphaned Entity Handling**: Only deletes entities that have **no connections to other documents**. This prevents data loss when entities appear in multiple documents.

**Query Parameters**:
- `doc_id`: Document ID to delete
- `filter_label`: Tenant filter label

```bash
curl -X DELETE "https://second.amar.blaiq.ai/pipeline/document/neo4j?doc_id=report_q1_abc123&filter_label=user01_documents" \
  -H "X-API-Key: ************"
```

**Response**:
```json
{
  "documents": 1,
  "chunks": 15,
  "entities": 3,
  "relationships": 8,
  "doc_id": "report_q1_abc123",
  "filter_label": "user01_documents"
}
```

**What Gets Deleted**:
1. **Document node**: The main document entry
2. **Chunk nodes**: All chunks from this document
3. **Orphaned entities**: Entities connected **only** to this document's chunks
4. **Relationships**: All relationships involving deleted nodes

**What Stays Protected**:
- Entities that appear in other documents remain intact
- Cross-document relationships are preserved
- Tenant isolation via `filter_label` ensures safe deletion

---

### Complete Deletion Workflow

```bash
# Step 1: Delete from Qdrant (vector embeddings)
curl -X DELETE "https://second.amar.blaiq.ai/pipeline/document/qdrant?doc_id=report_q1_abc123&collection_name=user01_documents&filter_label=user01_documents" \
  -H "X-API-Key: ************"

# Step 2: Delete from Neo4j (graph data) - if using GraphRAG
curl -X DELETE "https://second.amar.blaiq.ai/pipeline/document/neo4j?doc_id=report_q1_abc123&filter_label=user01_documents" \
  -H "X-API-Key: ************"

# Step 3: Delete source files (optional)
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-file" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "folder_name": "data/user01",
    "filenames": ["report_q1.pdf"]
  }'
```

---

### Python Helper Function

```python
import requests

API_KEY = "************"
BASE_URL = "https://second.amar.blaiq.ai/pipeline"

def delete_document_completely(doc_id, collection_name, filter_label):
    """
    Delete a document from both Qdrant and Neo4j databases
    
    Args:
        doc_id: Document ID to delete
        collection_name: Qdrant collection name
        filter_label: Tenant filter label (usually same as collection_name)
    
    Returns:
        dict: Deletion results from both databases
    """
    headers = {"X-API-Key": API_KEY}
    
    # Delete from Qdrant
    qdrant_response = requests.delete(
        f"{BASE_URL}/document/qdrant",
        headers=headers,
        params={
            "doc_id": doc_id,
            "collection_name": collection_name,
            "filter_label": filter_label
        }
    )
    
    # Delete from Neo4j (if GraphRAG enabled)
    neo4j_response = requests.delete(
        f"{BASE_URL}/document/neo4j",
        headers=headers,
        params={
            "doc_id": doc_id,
            "filter_label": filter_label
        }
    )
    
    return {
        "qdrant": qdrant_response.json(),
        "neo4j": neo4j_response.json()
    }

# Usage
result = delete_document_completely(
    doc_id="report_q1_abc123",
    collection_name="user01_documents",
    filter_label="user01_documents"
)

print(f"Qdrant: Deleted {result['qdrant']['deleted']} vectors")
print(f"Neo4j: Deleted {result['neo4j']['chunks']} chunks, {result['neo4j']['entities']} entities")
```

---

## 🗄️ Direct Qdrant Access

You can query metadata directly from Qdrant without using the Retriever API. Since metadata is set on a file level you can access by "original_filename", "doc_id" or "chunk_id" and set limit=1 to get best performance.

### Base Information

- **Qdrant URL**: https://qdrant.api.blaiq.ai
- **Authentication**: `api-key` header
- **Endpoint**: `/collections/{collection_name}/points/scroll`

### Filter by original_filename

Get all chunks from a specific file:
```bash
curl -X POST "https://qdrant.api.blaiq.ai/collections/user01_documents/points/scroll" \
  -H "api-key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "original_filename",
          "match": {
            "value": "report_q1.pdf"
          }
        }
      ]
    },
    "limit": 100,
    "with_payload": true,
    "with_vector": false
  }'
```

**Response**:
```json
{
  "result": {
    "points": [
      {
        "id": 123456789,
        "payload": {
          "doc_id": "report_q1_abc123",
          "chunk_id": "report_q1_abc123_chunk_001",
          "text": "Q1 revenue increased by 15%...",
          "chunk_index": 0,
          "original_filename": "report_q1.pdf",
          "metadata": {
            "created_user_id": "user_123",
            "department": "Engineering",
            "created_user_name": "Oliver Ilnicki",
            "project": "GraphRAG",
            "priority": "high"
          }
        }
      }
    ],
    "next_page_offset": null
  },
  "status": "ok"
}
```

### Filter by doc_id

Get all chunks from a document by its internal ID:
```bash
curl -X POST "https://qdrant.api.blaiq.ai/collections/user01_documents/points/scroll" \
  -H "api-key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "doc_id",
          "match": {
            "value": "report_q1_abc123"
          }
        }
      ]
    },
    "limit": 100,
    "with_payload": true,
    "with_vector": false
  }'
```

### Filter by chunk_id

Get a specific chunk:
```bash
curl -X POST "https://qdrant.api.blaiq.ai/collections/user01_documents/points/scroll" \
  -H "api-key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "chunk_id",
          "match": {
            "value": "report_q1_abc123_chunk_001"
          }
        }
      ]
    },
    "limit": 1,
    "with_payload": true,
    "with_vector": false
  }'
```

### Filter by Metadata Fields

Get chunks from Engineering department:
```bash
curl -X POST "https://qdrant.api.blaiq.ai/collections/user01_documents/points/scroll" \
  -H "api-key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "metadata.department",
          "match": {
            "value": "Engineering"
          }
        }
      ]
    },
    "limit": 100,
    "with_payload": true,
    "with_vector": false
  }'
```

### Combined Filters

Get high-priority chunks from GraphRAG project:
```bash
curl -X POST "https://qdrant.api.blaiq.ai/collections/user01_documents/points/scroll" \
  -H "api-key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "metadata.project",
          "match": {
            "value": "GraphRAG"
          }
        },
        {
          "key": "metadata.priority",
          "match": {
            "value": "high"
          }
        }
      ]
    },
    "limit": 100,
    "with_payload": true,
    "with_vector": false
  }'
```

### Get Only Metadata (No Text)

Retrieve just metadata and identifiers:
```bash
curl -X POST "https://qdrant.api.blaiq.ai/collections/user01_documents/points/scroll" \
  -H "api-key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "original_filename",
          "match": {
            "value": "report_q1.pdf"
          }
        }
      ]
    },
    "limit": 1,
    "with_payload": ["metadata", "original_filename", "chunk_id", "doc_id"],
    "with_vector": false
  }'
```

### Python Example: Direct Qdrant Access
```python
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

# Connect to Qdrant
client = QdrantClient(
    url="https://qdrant.api.blaiq.ai",
    api_key="************"
)

# Get all chunks from a specific file
results = client.scroll(
    collection_name="user01_documents",
    scroll_filter=Filter(
        must=[
            FieldCondition(
                key="original_filename",
                match=MatchValue(value="report_q1.pdf")
            )
        ]
    ),
    limit=100,
    with_payload=True
)

for point in results[0]:
    print(f"Chunk: {point.payload['chunk_id']}")
    print(f"Metadata: {point.payload['metadata']}")
    print(f"Text: {point.payload['text'][:100]}...")
    print("-" * 50)

# Filter by department
engineering_docs = client.scroll(
    collection_name="user01_documents",
    scroll_filter=Filter(
        must=[
            FieldCondition(
                key="metadata.department",
                match=MatchValue(value="Engineering")
            )
        ]
    ),
    limit=100,
    with_payload=True
)

print(f"Found {len(engineering_docs[0])} Engineering chunks")

# Get unique users
all_chunks = client.scroll(
    collection_name="user01_documents",
    limit=1000,
    with_payload=["metadata"]
)

users = set()
for point in all_chunks[0]:
    user = point.payload.get('metadata', {}).get('created_user_name')
    if user:
        users.add(user)

print(f"Documents created by: {users}")
```

---

## 🔍 Retriever API

Base URL: `https://second.amar.blaiq.ai/retriever`  
Version: `3.0.0`

The Retriever API provides two query modes for searching your processed documents with optional LLM-powered answer generation.

### Endpoints Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/query/rag` | POST | Vector + Keyword search (Qdrant only) |
| `/query/graphrag` | POST | Hybrid: Neo4j Graph + Qdrant Vector + Keyword |
| `/status` | GET | Check system connections (Qdrant, Neo4j, LLM) |
| `/` | GET | Health check and service info |

---

### 1. RAG Query (Vector + Keyword)

**Endpoint**: `POST /query/rag`

Traditional RAG retrieval using vector similarity and keyword search. Best for simple queries without entity relationships.

**How it works**:
1. Query expansion (keywords, numbers, patterns)
2. Vector similarity search in Qdrant
3. Keyword search for exact matches
4. RRF (Reciprocal Rank Fusion) of results
5. Optional: LLM answer generation

```bash
curl -X POST "https://second.amar.blaiq.ai/retriever/query/rag" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Was sind die Ziele der Digitalisierungsstrategie?",
    "collection_name": "my_collection",
    "k": 10,
    "generate_answer": true
  }'
```

**Response**:
```json
{
  "query": "Was sind die Ziele der Digitalisierungsstrategie?",
  "answer": "ANTWORT: Die Digitalisierungsstrategie verfolgt mehrere Ziele...\n\nKONTEXT: Diese Information stammt aus dem Abschnitt zur strategischen Ausrichtung.\n\nQUELLE: Dokument strategie.pdf, Seiten 12-15",
  "chunks_retrieved": 10,
  "retrieval_stats": {
    "total_candidates": 85,
    "vector_chunks": 50,
    "keyword_chunks": 35,
    "adjacent_chunks": 20,
    "retrieval_methods_used": 3,
    "mode": "rag"
  },
  "retrieval_time": 1.23,
  "answer_time": 2.45,
  "total_time": 3.68
}
```

---

### 2. GraphRAG Query (Graph + Vector + Keyword)

**Endpoint**: `POST /query/graphrag`

Hybrid retrieval combining knowledge graph traversal with vector and keyword search. Best for complex queries involving entities and their relationships.

**How it works**:
1. LLM-based entity extraction from query
2. Graph traversal in Neo4j (filtered by tenant/filter_label)
3. Vector similarity search in Qdrant
4. Keyword search for exact matches
5. Weighted RRF fusion of all results
6. Optional: LLM answer generation
7. Optional: Mermaid graph visualization

```bash
curl -X POST "https://second.amar.blaiq.ai/retriever/query/graphrag" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Wie wird KI in der Pflege und Medizin eingesetzt?",
    "collection_name": "my_collection",
    "k": 10,
    "generate_answer": true,
    "include_graph": true,
    "graph_depth": 1
  }'
```

**Response**:
```json
{
  "query": "Wie wird KI in der Pflege und Medizin eingesetzt?",
  "answer": "ANTWORT: Künstliche Intelligenz wird in der Pflege und Medizin vielfältig eingesetzt...\n\nKONTEXT: Diese Informationen stammen aus den Abschnitten zur KI-Anwendung im Gesundheitswesen.\n\nQUELLE: Dokument ki_strategie.pdf, Seiten 72-78",
  "chunks_retrieved": 10,
  "retrieval_stats": {
    "total_candidates": 143,
    "graph_chunks": 91,
    "vector_chunks": 50,
    "keyword_chunks": 50,
    "adjacent_chunks": 36,
    "entities_extracted": ["KI", "Pflege", "Medizin"],
    "retrieval_methods_used": 4,
    "filter_label": "my_collection",
    "neo4j_enabled": true,
    "graph_used": true,
    "mode": "graphrag"
  },
  "retrieval_time": 2.39,
  "answer_time": 3.68,
  "total_time": 6.07,
  "graph": {
    "mermaid_code": "graph LR\n    E0((\"Künstliche Intelligenz\"))\n    E1{{\"Niedersachsen\"}}\n    E2([\"Pflege\"])\n    E0 -->|BEZIEHT SICH| E1\n    E0 -->|BEZIEHT SICH| E2",
    "nodes": 15,
    "edges": 12,
    "entities": [...],
    "relationships": [...]
  }
}
```

---

### Query Parameters Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Your question |
| `collection_name` | string | config default | Qdrant collection & Neo4j filter_label |
| `k` | int | 20 | Number of chunks to retrieve (1-50) |
| `generate_answer` | bool | true | Generate LLM answer or return only chunks |
| `system_prompt` | string | null | Custom system prompt for LLM |
| `user_prompt` | string | null | Custom user prompt (use `{context}` and `{query}`) |
| `entity_extraction_prompt` | string | null | Custom entity extraction prompt (use `{query}`) (GraphRAG only) |
| `include_graph` | bool | false | Include Mermaid graph visualization (GraphRAG only) |
| `graph_depth` | int | 1 | Graph traversal depth 1-3 hops (GraphRAG only) |
| `debug` | bool | false | Enable debug output in logs |
| `qdrant_url` | string | null | Override Qdrant URL (e.g., `https://...`) |
| `qdrant_host` | string | null | Override Qdrant host |
| `qdrant_port` | int | null | Override Qdrant port |
| `qdrant_api_key` | string | null | Override Qdrant API key |

---

### Context-Only Mode

Get only retrieved chunks without LLM answer generation (useful for custom processing):

```bash
curl -X POST "https://second.amar.blaiq.ai/retriever/query/graphrag" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Welche Organisationen sind beteiligt?",
    "collection_name": "my_collection",
    "k": 5,
    "generate_answer": false
  }'
```

**Response**:
```json
{
  "query": "Welche Organisationen sind beteiligt?",
  "chunks": [
    {
      "chunk_id": "doc1_abc123_chunk_005",
      "doc_id": "doc1_abc123",
      "chunk_index": 5,
      "text": "Das Niedersächsische Ministerium für Wirtschaft...",
      "score": 0.0234,
      "metadata": {
        "qdrant_id": 12345678,
        "retrieval_rank": 1
      }
    }
  ],
  "retrieval_stats": {...},
  "retrieval_time": 1.85
}
```

---

### Graph Visualization

When `include_graph: true`, the response includes Mermaid diagram code for visualizing entity relationships:

```json
{
  "graph": {
    "mermaid_code": "graph LR\n    E0((\"Künstliche Intelligenz\"))\n    E1{{\"Niedersachsen\"}}\n    E2([\"Masterplan Digitalisierung\"])\n    E0 -->|BEZIEHT SICH| E1\n    E0 -->|ERWAEHNT| E2\n\n    %% Styling\n    classDef person fill:#e1f5fe,stroke:#01579b\n    classDef org fill:#fff3e0,stroke:#e65100\n    classDef place fill:#e8f5e9,stroke:#2e7d32\n    classDef concept fill:#f3e5f5,stroke:#7b1fa2",
    "nodes": 3,
    "edges": 2,
    "entities": [
      {"id": "KONZEPT_2222244", "name": "Künstliche Intelligenz", "type": "KONZEPT"},
      {"id": "ORT_123456", "name": "Niedersachsen", "type": "ORT"},
      {"id": "DOKUMENT_789", "name": "Masterplan Digitalisierung", "type": "DOKUMENT"}
    ],
    "relationships": [
      {"source_id": "KONZEPT_2222244", "target_id": "ORT_123456", "type": "BEZIEHT_SICH_AUF"},
      {"source_id": "KONZEPT_2222244", "target_id": "DOKUMENT_789", "type": "ERWAEHNT"}
    ]
  }
}
```

**Render Options**:
- Use [Mermaid.js](https://mermaid.js.org/) in browser
- Use Node.js mermaid-cli for server-side SVG rendering
- Copy to [Mermaid Live Editor](https://mermaid.live/)

**Node shapes by entity type**:

| Entity Type | Mermaid Shape | Example |
|-------------|---------------|---------|
| PERSON, ROLLE | Rectangle | `["Dr. Müller"]` |
| ORGANISATION | Stadium | `(["Ministerium"])` |
| ORT, IMMOBILIE | Rhombus | `{{"Berlin"}}` |
| KONZEPT | Circle | `(("KI"))` |
| DOKUMENT, EVENT | Stadium | `(["Masterplan"])` |

---

### Custom Prompts

Override default prompts for answer generation and entity extraction:

```bash
curl -X POST "https://second.amar.blaiq.ai/retriever/query/graphrag" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Summarize the key points",
    "collection_name": "my_collection",
    "k": 10,
    "generate_answer": true,
    "system_prompt": "You are a helpful assistant. Always respond in English. Be concise.",
    "user_prompt": "Based on the following context, answer the question.\n\nContext:\n{context}\n\nQuestion: {query}\n\nProvide a clear, structured answer:",
    "entity_extraction_prompt": "Extract all relevant entities from the following query. Return ONLY a JSON array.\n\nQuery: {query}\n\nJSON array:"
  }'
```

**Placeholder variables**:
- **For `user_prompt`**:
  - `{context}` - Retrieved chunks formatted as text
  - `{query}` - User's original question
- **For `entity_extraction_prompt`** (GraphRAG only):
  - `{query}` - User's original question

---

### Check System Status

```bash
curl "https://second.amar.blaiq.ai/retriever/status" \
  -H "X-API-Key: ************"
```

**Response**:
```json
{
  "api": "online",
  "qdrant": "connected",
  "neo4j": "connected",
  "llm": "configured"
}
```

---

## 🔒 Multi-Tenant Isolation

The system provides strict data isolation between tenants using `collection_name` / `filter_label`.

### How Multi-Tenancy Works

1. **Qdrant**: Each tenant gets a separate collection
2. **Neo4j**: All entities and relationships are tagged with `filter_label`
3. **Queries**: Automatically filtered to only return tenant's data

### Setting Up Multi-Tenant

```bash
# Tenant A - Upload & Process
curl -X POST ".../upload" -F "folder_path=data/tenant_a" ...
curl -X POST ".../process" -d '{"folder_path": "data/tenant_a", "collection_name": "tenant_a", ...}'

# Tenant B - Upload & Process  
curl -X POST ".../upload" -F "folder_path=data/tenant_b" ...
curl -X POST ".../process" -d '{"folder_path": "data/tenant_b", "collection_name": "tenant_b", ...}'

# Query Tenant A only - data from Tenant B is never visible
curl -X POST ".../query/graphrag" -d '{"query": "...", "collection_name": "tenant_a"}'

# Query Tenant B only
curl -X POST ".../query/graphrag" -d '{"query": "...", "collection_name": "tenant_b"}'
```

### Isolation Guarantees

- ✅ Same entity name in different tenants = **separate** graph nodes
- ✅ Graph traversals **never** cross tenant boundaries
- ✅ Vector searches isolated by collection
- ✅ Entity extraction tagged with filter_label
- ✅ All Neo4j queries include `filter_label` constraint

---

## 📊 Metadata System

### Metadata Structure in Qdrant

Every chunk in Qdrant has this structure:
```json
{
  "id": 123456789,
  "vector": [0.1, 0.2, ...],
  "payload": {
    "doc_id": "report_q1_abc123",
    "chunk_id": "report_q1_abc123_chunk_001",
    "text": "Full chunk text...",
    "chunk_index": 0,
    "original_filename": "report_q1.pdf",
    "metadata": {
      "created_at": "2025-10-28T10:30:00Z",
      "created_user_id": "user_123",
      "created_user_name": "Oliver Ilnicki",
      "department": "Engineering",
      "project": "GraphRAG",
      "priority": "high",
      "custom_field": "any_value"
    }
  }
}
```

### System Fields (Always Present)

- `doc_id`: Internal document identifier
- `chunk_id`: Unique chunk identifier
- `text`: Chunk content
- `chunk_index`: Position in document (0-based)
- `original_filename`: Original uploaded filename

### User Metadata (Flexible)

The `metadata` object can contain any JSON-serializable key-value pairs:

- **Timestamps**: `created_at`, `updated_at`, `processed_at`
- **User Info**: `created_user_id`, `created_user_name`, `department`
- **Organization**: `project`, `team`, `category`, `tags`
- **Permissions**: `access_level`, `confidential`, `visibility`
- **Workflow**: `status`, `priority`, `version`, `approval_status`
- **Custom**: Any domain-specific fields

### Use Cases for Metadata

**1. Multi-Tenancy**:
```json
{
  "tenant_id": "acme_corp",
  "user_id": "user_123",
  "access_level": "manager"
}
```

**2. Document Lifecycle**:
```json
{
  "status": "published",
  "version": "2.1",
  "approved_by": "jane_smith",
  "approval_date": "2025-10-28"
}
```

**3. Content Classification**:
```json
{
  "category": "financial_report",
  "tags": "quarterly,revenue,forecast",
  "confidential": true,
  "retention_years": 7
}
```

**4. Workflow Tracking**:
```json
{
  "stage": "review",
  "assigned_to": "oliver",
  "due_date": "2025-11-15",
  "priority": "high"
}
```

---

## 🔄 Complete Workflow Examples

### Example 1: Multi-User Document Management
```bash
# User 1 uploads documents
curl -X POST "https://second.amar.blaiq.ai/pipeline/upload" \
  -H "X-API-Key: ************" \
  -F "files=@user1_doc.pdf" \
  -F "folder_path=data/user01" \
  -F 'metadata={"user1_doc.pdf": {"user_id": "user01", "department": "Sales"}}'

# User 2 uploads documents
curl -X POST "https://second.amar.blaiq.ai/pipeline/upload" \
  -H "X-API-Key: ************" \
  -F "files=@user2_doc.pdf" \
  -F "folder_path=data/user02" \
  -F 'metadata={"user2_doc.pdf": {"user_id": "user02", "department": "Engineering"}}'

# Process User 1's documents
curl -X POST "https://second.amar.blaiq.ai/pipeline/process" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "data/user01", "collection_name": "user01_docs"}'

# Process User 2's documents
curl -X POST "https://second.amar.blaiq.ai/pipeline/process" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "data/user02", "collection_name": "user02_docs"}'

# Query only User 1's documents (via Qdrant)
curl -X POST "https://qdrant.api.blaiq.ai/collections/user01_docs/points/scroll" \
  -H "api-key: ************" \
  -H "Content-Type: application/json" \
  -d '{"filter": {"must": [{"key": "metadata.user_id", "match": {"value": "user01"}}]}}'
```

### Example 2: Department-Based Access Control
```python
import requests

API_KEY = "************"
BASE_URL = "https://second.amar.blaiq.ai/pipeline"
QDRANT_URL = "https://qdrant.api.blaiq.ai"
QDRANT_API_KEY = "************"

# Upload with department metadata
files = [("files", open("report.pdf", "rb"))]
data = {
    "folder_path": "data/company",
    "metadata": json.dumps({
        "report.pdf": {
            "department": "Engineering",
            "confidential": True,
            "access_level": "manager"
        }
    })
}

response = requests.post(
    f"{BASE_URL}/upload",
    headers={"X-API-Key": API_KEY},
    files=files,
    data=data
)

# Process
requests.post(
    f"{BASE_URL}/process",
    headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    json={"folder_path": "data/company", "collection_name": "company_docs"}
)

# Query only Engineering documents
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

engineering_docs = client.scroll(
    collection_name="company_docs",
    scroll_filter=Filter(
        must=[
            FieldCondition(
                key="metadata.department",
                match=MatchValue(value="Engineering")
            ),
            FieldCondition(
                key="metadata.access_level",
                match=MatchValue(value="manager")
            )
        ]
    ),
    limit=100
)

for point in engineering_docs[0]:
    print(f"Doc: {point.payload['original_filename']}")
    print(f"User: {point.payload['metadata'].get('created_user_name')}")
```

### Example 3: Complete Lifecycle with Cleanup
```bash
# 1. Upload documents
curl -X POST "https://second.amar.blaiq.ai/pipeline/upload" \
  -H "X-API-Key: ************" \
  -F "files=@temp_analysis.pdf" \
  -F "folder_path=data/temp_project"

# 2. List uploaded files
curl -X GET "https://second.amar.blaiq.ai/pipeline/get-user-files?folder_name=data/temp_project" \
  -H "X-API-Key: ************"

# 3. Process documents
curl -X POST "https://second.amar.blaiq.ai/pipeline/process" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "data/temp_project", "collection_name": "temp_docs"}'

# 4. After use - Clean up temporary project
curl -X POST "https://second.amar.blaiq.ai/pipeline/delete-folder" \
  -H "X-API-Key: ************" \
  -H "Content-Type: application/json" \
  -d '{"folder_name": "data/temp_project"}'
```

---

## 🏗️ System Overview

### Architecture Components
```
Documents → Upload → Extract → Chunk → Embed → Qdrant
    ↓         ↓         ↓        ↓       ↓        ↓
  +Metadata  Store   Process  Index  Vector  +Metadata
    ↓                                            ↓
File Mgmt  ←─────────────────────────────────  Query
```

**Key Features**:
- **Flexible Metadata**: Attach any key-value pairs to documents
- **Multi-Tenancy**: Separate folders and collections per user/tenant
- **File Management**: List, delete files/folders with security
- **Database Deletion**: Remove documents from Qdrant & Neo4j with orphan cleanup
- **Direct Access**: Query Qdrant directly with REST API
- **Filtering**: Filter by filename, doc_id, chunk_id, or custom metadata
- **Hybrid Search**: Combine vector similarity with metadata filters

### Data Flow
```
1. Upload:
   data/user01/document.pdf
   data/user01/_metadata/document.pdf.json

2. Process:
   data/user01/_pipeline/step1_processed/
   data/user01/_pipeline/step3_chunks/

3. Index:
   Qdrant → Collection: user01_docs
   └── Points with metadata in payload.metadata

4. Query:
   Direct: Qdrant REST API
   Via: Retriever API

5. Manage:
   List: GET /get-user-files
   Delete Files: POST /delete-file or POST /delete-folder

6. Database Deletion:
   Qdrant: DELETE /document/qdrant
   Neo4j: DELETE /document/neo4j (with orphan cleanup)
```

### LLM Integration

The Retriever API uses LLM for:
- **Entity Extraction** (GraphRAG): Identifying entities in user queries
- **Answer Generation**: Creating natural language responses from retrieved chunks

**Resilience Features**:
- **Primary/Fallback Models**: If the primary LLM model fails, the system automatically falls back to a secondary model
- **Timeout Protection**: All LLM calls enforce a client-side timeout (default 25 seconds) to prevent hanging requests
- **Error Logging**: LLM failures and fallback events are logged for monitoring and debugging

This ensures the retriever remains operational even when LLM services experience issues.

---

## ⚙️ Configuration

### Environment Variables (`.env`)

#### Core API Configuration
```bash
# API Authentication
API_KEY=YOUR_API_KEY_HERE

# OpenAI (answer LLM; optional but recommended)
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
```

#### Qdrant Configuration
```bash
# Qdrant (inside Docker / GraphRAG)
# Internal URL via Docker network (service name: qdrant)
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=YOUR_QDRANT_API_KEY

# For direct external access (admin / debugging), use:
#   https://qdrant.api.blaiq.ai  with header:  api-key: <QDRANT_API_KEY>
```

#### Neo4j Configuration
```bash
# Neo4j (optional, with TLS in production)
# Local dev example:
# NEO4J_URI=bolt://localhost:7687

# Production (with TLS)
NEO4J_URI=neo4j+s://neo4j.api.blaiq.ai:7689
NEO4J_USER=neo4j
NEO4J_PASSWORD=YOUR_NEO4J_PASSWORD
```

#### LLM Configuration
```bash
# OpenAI-compatible LLM endpoint
OPENAI_API_KEY=YOUR_LLM_API_KEY
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# LLM Resilience & Fallback (Retriever API)
OPENAI_FALLBACK_MODEL=gpt-3.5-turbo  # Optional: fallback if primary fails
LLM_TIMEOUT_SECONDS=25                # Client-side timeout for LLM calls
LLM_MAX_OUTPUT_TOKENS=4000            # Max tokens for response (default: 4000). Set to 0 for unlimited (model max).
```

**LLM Resilience Behavior**:
- The retriever wraps all LLM calls in a helper that enforces `LLM_TIMEOUT_SECONDS`
- If the primary model (`OPENAI_MODEL`) fails or times out, the system automatically tries the fallback model (`OPENAI_FALLBACK_MODEL`)
- If no fallback is configured or both models fail, an error is returned
- All failures and successful fallbacks are logged to `LLM_ERROR_LOG_PATH`

#### LLM Error Logging
```bash
# LLM Error & Fallback Logging
LLM_ERROR_LOG_PATH=logs/llm_error.log      # Path to JSON log file
LLM_ERROR_LOG_MAX_BYTES=5242880            # 5MB per file (before rotation)
LLM_ERROR_LOG_BACKUP_COUNT=5               # Keep 5 backup files
```

**Log Format**: JSON lines, one event per line:
```json
{"ts": "2025-01-08T10:30:00.000Z", "event": "llm_error", "service": "python", "module": "src.retriever.graphrag_retriever", "model": "gpt-4o-mini", "error_type": "Timeout", "error_message": "Request timed out after 25s", ...}
{"ts": "2025-01-08T10:30:01.500Z", "event": "llm_fallback_success", "service": "python", "primary_model": "gpt-4o-mini", "used_model": "gpt-3.5-turbo", "duration_ms": 1200, ...}
```

---

## 🐋 Deployment

### Docker Deployment
```bash
# Build and start
docker-compose up --build -d

# Check logs
docker-compose logs -f pipeline-api
docker-compose logs -f retriever-api

# Stop
docker-compose down
```

### Production Checklist

- ✅ Set strong `API_KEY` in `.env`
- ✅ Configure HTTPS for production
- ✅ Set up Qdrant persistence
- ✅ Configure backup strategy for `data/` directory
- ✅ Implement rate limiting
- ✅ Add monitoring (Prometheus/Grafana)
- ✅ Set up audit logging for file operations
- ✅ Document disaster recovery
- ✅ Configure file retention policies
- ✅ Set up automated cleanup jobs
- ✅ Configure LLM timeout and fallback models
- ✅ Set up LLM error log monitoring

---

## 📊 Monitoring & Logging

### LLM Error Logs

The Retriever API logs all LLM-related errors and fallback events to a dedicated log file.

**Log Location**: By default `logs/llm_error.log` (configurable via `LLM_ERROR_LOG_PATH`)

**Log Format**: JSON lines (one event per line), using rotating file handler:
- **Max file size**: 5MB (configurable via `LLM_ERROR_LOG_MAX_BYTES`)
- **Backup files**: 5 (configurable via `LLM_ERROR_LOG_BACKUP_COUNT`)

**Event Types**:
- `llm_error`: Primary or fallback model failed
- `llm_fallback_success`: Primary failed but fallback succeeded

**Example Entries**:
```json
{"ts": "2025-01-08T10:30:00.000Z", "event": "llm_error", "service": "python", "module": "src.retriever.graphrag_retriever", "model": "gpt-4o-mini", "primary_model": "gpt-4o-mini", "duration_ms": 25100, "timeout_s": 25, "error_type": "Timeout", "error_message": "Request timed out"}

{"ts": "2025-01-08T10:30:01.500Z", "event": "llm_fallback_success", "call_id": "abc-123", "service": "python", "module": "src.retriever.rag_retriever", "primary_model": "gpt-4o-mini", "used_model": "gpt-3.5-turbo", "duration_ms": 1200, "timeout_s": 25, "prompt_chars": 2500}
```

**Use Cases**:
- Monitor LLM service health and uptime
- Identify patterns in timeout or failure events
- Track fallback model usage frequency
- Debug slow or failing queries
- Analyze cost/performance trade-offs between primary and fallback models

**Analysis Tips**:
- Use `jq` or Python to parse JSON logs
- Filter by `event` type or `module` for specific analysis
- Monitor `duration_ms` to detect slow LLM calls
- Track `used_model` vs `primary_model` to measure fallback rate

**Example log analysis**:
```bash
# Count errors by model
cat logs/llm_error.log | jq -r 'select(.event=="llm_error") | .model' | sort | uniq -c

# Count successful fallbacks
cat logs/llm_error.log | jq -r 'select(.event=="llm_fallback_success")' | wc -l

# Get average duration for successful fallbacks
cat logs/llm_error.log | jq -r 'select(.event=="llm_fallback_success") | .duration_ms' | awk '{sum+=$1; n++} END {print sum/n " ms"}'
```

### System Monitoring

For production deployments, consider monitoring:
- API response times and error rates
- Qdrant memory/disk usage
- Neo4j query performance
- LLM error rates and fallback frequency
- Pipeline processing queue length
- Storage usage per tenant
- Authentication failures

---

## 🔐 Security Best Practices

### API Key Management

- **Never commit** API keys to git
- Use **separate keys** for dev/staging/prod
- **Rotate keys** regularly
- Store in **secrets management** (AWS Secrets Manager, HashiCorp Vault)

### Metadata Privacy

- **Do not store** sensitive PII in metadata (SSN, credit cards)
- Use **IDs instead** of names when possible
- Implement **field-level encryption** for sensitive data
- Apply **GDPR compliance** for European data

### Multi-Tenancy Security

- **Isolate** users via separate collections and folders
- Validate `folder_path` for **path traversal** attacks (✅ built-in)
- Implement **RBAC** for collection access
- Audit **all metadata changes**

### File Management Security

- **Path Traversal Protection**: Built-in validation prevents `..` and absolute paths
- **Root Protection**: `data/` directory cannot be deleted
- **Scope Isolation**: All operations restricted to `data/` directory
- **Audit Logging**: Log all file deletions with user, timestamp, and reason
- **Soft Delete**: Consider implementing soft delete for critical data
- **Backup Before Delete**: Always backup before bulk deletion operations

### LLM Security

- **Timeout Protection**: Prevent runaway LLM calls with `LLM_TIMEOUT_SECONDS`
- **Model Validation**: Ensure only trusted models are configured
- **Prompt Injection**: Custom prompts should be sanitized if user-provided
- **Cost Control**: Monitor LLM usage and fallback rates to control costs
- **API Key Rotation**: Rotate `OPENAI_API_KEY` regularly

---

## 📚 Additional Resources

### API Specifications

- **Pipeline API OpenAPI/Swagger**: `https://second.amar.blaiq.ai/pipeline/docs`
- **Retriever API OpenAPI/Swagger**: `https://second.amar.blaiq.ai/retriever/docs`
- **Consolidated Endpoint Reference**: [API_ENDPOINTS.md](API_ENDPOINTS.md)
- **Qdrant API Documentation**: https://qdrant.tech/documentation/

### API Endpoints Summary

#### Pipeline API (`https://second.amar.blaiq.ai/pipeline`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Health check and service info |
| `/upload` | POST | Upload documents with metadata |
| `/process` | POST | Start pipeline processing job |
| `/status/{job_id}` | GET | Check job status |
| `/result/{job_id}` | GET | Get processing results |
| `/get-user-files` | GET | List files and folders (tree view) |
| `/get-user-files-flat` | GET | List files (flat, paginated, with search) |
| `/delete-file` | POST | Delete multiple files |
| `/delete-folder` | POST | Delete entire folder |
| `/files` | GET | List files in data/ (legacy) |
| `/files/{filename}` | DELETE | Delete single file (legacy) |
| `/jobs` | GET | List all processing jobs |
| `/job/{job_id}` | DELETE | Delete a job from storage |
| `/jobs/cleanup` | POST | Clean up old jobs (max_age_hours param) |
| `/storage/stats` | GET | Get storage statistics |
| `/document/qdrant` | DELETE | Delete document vectors from Qdrant |
| `/document/neo4j` | DELETE | Delete document from Neo4j graph |

#### Retriever API (`https://second.amar.blaiq.ai/retriever`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Health check and service info |
| `/status` | GET | Check system connections (Qdrant, Neo4j, LLM) |
| `/query/rag` | POST | RAG query (Vector + Keyword search) |
| `/query/graphrag` | POST | GraphRAG query (Graph + Vector + Keyword) |
