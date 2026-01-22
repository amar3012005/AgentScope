# src/pipeline/pipeline_api.py

"""
GraphRAG Pipeline FastAPI Application
Flexible document processing with configurable entity extraction and graph features
File-based job persistence for reliability across server restarts
"""

import json
import shutil
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field

from utils.auth import verify_api_key
from utils.delete_document_from_db import (
    delete_document_from_neo4j,
    delete_document_from_qdrant,
)
from utils.job_store import JobStore

# Import file manager
from .file_manager import (
    DeleteFilesRequest,
    DeleteFilesResponse,
    DeleteFolderRequest,
    DeleteFolderResponse,
    FileManagerError,
    GetUserFilesResponse,
    InvalidPathError,
    PathNotFoundError,
    ProtectedPathError,
    get_file_manager,
    GetUserFilesFlatResponse, # 251210–BundB Jun
)


# from .pipeline import run_graphrag_pipeline
def get_pipeline():
    """Lazy import of pipeline to avoid blocking startup"""
    from .pipeline import run_graphrag_pipeline

    return run_graphrag_pipeline


app = FastAPI(
    title="GraphRAG Pipeline API",
    description="Flexible document processing with optional entity extraction and graph features",
    version="2.3.0",
    dependencies=[Depends(verify_api_key)],
)

# File-based job storage (replaces in-memory dict)
job_store = JobStore(storage_dir="_jobs", api_name="pipeline")


# ============================================================
# PYDANTIC MODELS
# ============================================================


class CleanupStrategy(str, Enum):
    """Cleanup strategy after processing"""

    NONE = "none"
    SUBFOLDERS = "subfolders"
    ALL = "all"


class EntityExtractionConfig(BaseModel):
    """Entity extraction configuration (OpenAI)"""

    chunk_size: int = Field(default=4000, description="Chunk size for entity extraction")
    max_workers: int = Field(default=4, description="Number of parallel workers")
    # Note: Model and credentials are configured via environment variables:
    # OPENAI_API_KEY, OPENAI_MODEL


class PipelineSteps(BaseModel):
    """Pipeline steps configuration"""

    document_processing: bool = Field(default=True, description="Extract text from documents")
    entity_extraction: bool = Field(default=False, description="Extract entities with LLM")
    chunking: bool = Field(default=True, description="Create semantic chunks")
    vector_indexing: bool = Field(default=True, description="Index chunks in Qdrant")
    entity_linking: bool = Field(default=False, description="Link entities to chunks")
    neo4j_ingestion: bool = Field(default=False, description="Ingest into Neo4j graph")


class Neo4jConfig(BaseModel):
    """
    Neo4j configuration (optional - falls back to env vars)

    Priority order for each field:
    1. Value provided in this config (API request)
    2. Environment variable (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    3. config.yaml settings
    """

    uri: Optional[str] = Field(
        default=None,
        description="Neo4j URI (e.g., bolt://hostname:7687). Falls back to NEO4J_URI env var",
    )
    user: Optional[str] = Field(
        default=None,
        description="Neo4j username. Falls back to NEO4J_USER env var or 'neo4j'",
    )
    password: Optional[str] = Field(
        default=None,
        description="Neo4j password. Falls back to NEO4J_PASSWORD env var",
    )


class PipelineRequest(BaseModel):
    """Complete pipeline configuration request"""

    # Required
    folder_path: str = Field(..., description="Path to folder containing documents")

    # Pipeline steps
    steps: PipelineSteps = Field(
        default_factory=PipelineSteps, description="Which steps to execute"
    )

    # Document processing
    force_reprocess: bool = Field(
        default=False, description="Reprocess already processed documents"
    )
    quality_threshold: float = Field(default=0.5, description="Minimum extraction quality (0-1)")

    # Chunking configuration
    chunking_method: str = Field(
        default="semantic_embedding", description="simple or semantic_embedding"
    )
    chunk_size: int = Field(default=1000, description="Target chunk size in tokens")
    chunk_overlap: int = Field(default=200, description="Overlap between chunks in tokens")

    # Entity extraction (optional)
    entity_extraction_config: Optional[EntityExtractionConfig] = Field(
        default=None,
        description="Entity extraction configuration (required if entity_extraction=true)",
    )

    # Entity/Relationship templates (optional - defaults to src/entity_template/)
    entity_template: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom entity types JSON schema. If not provided, uses default from src/entity_template/entity_types.json",
    )
    relationship_template: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom relationship types JSON schema. If not provided, uses default from src/entity_template/relationship_types.json",
    )

    # Qdrant configuration
    qdrant_url: Optional[str] = Field(default=None, description="Qdrant URL (if cloud/remote)")
    collection_name: str = Field(default="graphrag_chunks", description="Qdrant collection name")
    recreate_collection: bool = Field(default=False, description="Recreate collection if exists")

    # Neo4j (optional)
    neo4j_config: Optional[Neo4jConfig] = Field(
        default=None,
        description="Neo4j configuration. If not provided, uses NEO4J_* environment variables",
    )

    # Cleanup
    cleanup: CleanupStrategy = Field(
        default=CleanupStrategy.NONE, description="Cleanup strategy after processing"
    )


class JobStatus(BaseModel):
    """Job status response"""

    job_id: str
    status: str
    message: str
    progress: Optional[Dict] = None
    folder_path: Optional[str] = None

    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # 251216–BundB Jun – expose error information for failed jobs
    error: Optional[str] = None
    errors: Optional[List[str]] = None
    error_details: Optional[str] = None
    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


class ProcessResponse(BaseModel):
    """Processing result"""

    job_id: str
    status: str
    folder_path: str
    steps_executed: Dict[str, bool]

    # Core results
    documents_processed: Optional[int] = None
    chunks_created: Optional[int] = None
    vectors_indexed: Optional[int] = None

    # Entity/Graph results (optional)
    entities_extracted: Optional[int] = None
    total_entities: Optional[int] = None
    linked_entities: Optional[int] = None
    entity_chunk_links: Optional[int] = None
    neo4j_documents: Optional[int] = None
    neo4j_entities: Optional[int] = None
    neo4j_relationships: Optional[int] = None

    processing_time: float
    cleanup_performed: str
    errors: List[str] = []


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def normalize_folder_path(folder_path: str) -> str:
    """Normalize folder_path to always be inside data/ directory."""
    if not folder_path:
        return "data/"

    folder_path = folder_path.strip().strip("/")

    if ".." in folder_path:
        raise ValueError("Invalid folder path: path traversal not allowed")

    # Ensure data/ prefix
    if not folder_path.startswith("data"):
        folder_path = f"data/{folder_path}"

    return folder_path


def update_job_status(job_id: str, progress_dict: Dict):
    """Callback to update job progress"""
    job = job_store.load_job(job_id)
    if job:
        job["progress"] = progress_dict
        job_store.save_job(job_id, job)


def process_pipeline_wrapper(job_id: str, params: PipelineRequest):
    """Wrapper for background pipeline execution"""
    try:
        # Lazy import here
        run_graphrag_pipeline = get_pipeline()
    except Exception as e:
        job = job_store.load_job(job_id)
        if job:
            job.update(
                {
                    "status": "failed",
                    "error": f"Failed to load pipeline: {str(e)}",
                    "errors": [str(e)],
                }
            )
            job_store.save_job(job_id, job)
        return # 251216–BundB Jun – abort if pipeline cannot be loaded
    try:
        # Update status to processing
        job = job_store.load_job(job_id)
        if job:
            job["status"] = "processing"
            job_store.save_job(job_id, job)

        # Convert Pydantic models to dict
        config_dict = params.dict()

        # Run pipeline
        result = run_graphrag_pipeline(
            job_id=job_id, config_dict=config_dict, progress_callback=update_job_status
        )

        # Update job with results
        job = job_store.load_job(job_id)
        if job:
            if result.get("success"):
                job.update(
                    {
                        "status": "completed",
                        "results": result.get("results", {}),
                        "steps_executed": result.get("steps_executed", {}),
                        "processing_time": result.get("processing_time", 0),
                        "cleanup_performed": result.get("cleanup_performed", "none"),
                        "errors": result.get("errors", []),
                    }
                )
            else:
                job.update(
                    {
                        "status": "failed",
                        "error": result.get("error", "Unknown error"),
                        "error_details": result.get("error_details", ""),
                        "errors": result.get("errors", []),
                    }
                )

            job_store.save_job(job_id, job)

    except Exception as e:
        job = job_store.load_job(job_id)
        if job:
            job.update({"status": "failed", "error": str(e), "errors": [str(e)]})
            job_store.save_job(job_id, job)


# ============================================================
# API ENDPOINTS
# ============================================================


@app.get("/")
async def root():
    """Health check and service info"""
    stats = job_store.get_stats()

    return {
        "status": "healthy",
        "service": "GraphRAG Pipeline API",
        "version": "2.3.0",
        "features": [
            "Document Processing",
            "Entity Extraction (OpenAI GPT)",
            "Custom Entity/Relationship Templates",
            "Semantic Chunking",
            "Vector Search (Qdrant)",
            "Entity-Chunk Linking",
            "Graph Database (Neo4j) with filter_label",
            "File Management",
            "Document Deletion from DBs",
        ],
        "neo4j_config": {
            "note": "Neo4j connection can be configured via API request or environment variables",
            "env_vars": ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"],
            "priority": "API request > Environment variables > config.yaml",
        },
        "storage": {
            "type": "file-based",
            "total_jobs": stats["total_jobs"],
            "storage_size_mb": stats["total_size_mb"],
            "storage_dir": stats["storage_dir"],
        },
    }


# ============================================================
# DOCUMENT UPLOAD ENDPOINTS
# ============================================================


@app.post("/upload", dependencies=[Depends(verify_api_key)])
def upload_documents(
    files: List[UploadFile] = File(...),
    metadata: Optional[str] = Form(None),
    folder_path: Optional[str] = Form("data"),
):
    """
    Upload documents with optional flexible metadata

    - **files**: One or more files (PDF, DOCX, TXT, MD, PPTX, XLSX)
    - **metadata**: Optional JSON object with metadata per file (filename as key)
    - **folder_path**: Target folder path (default: "data", e.g., "data/user01", "data/customers/acme")

    Examples:
    - folder_path="data" → uploads to data/
    - folder_path="data/user01" → uploads to data/user01/
    - folder_path="data/customers/acme" → uploads to data/customers/acme/

    Metadata structure:
    {
      "file1.pdf": {
        "created_at": "2025-01-28T10:30:00Z",
        "created_user_id": "user123",
        "created_user_name": "John Doe",
        "department": "Sales"
      }
    }

    The metadata will be stored in Qdrant under payload.metadata
    """
    # Parse metadata if provided
    files_metadata = {}
    if metadata:
        try:
            files_metadata = json.loads(metadata)
            if not isinstance(files_metadata, dict):
                raise ValueError("Metadata must be a JSON object")
        except Exception as e:
            raise HTTPException(400, f"Invalid metadata JSON: {str(e)}")

    # Construct upload directory from folder_path
    # Sanitize folder_path to prevent path traversal attacks
    folder_path = normalize_folder_path(folder_path)

    upload_dir = Path(folder_path)

    # Ensure upload directory exists
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Metadata directory inside upload_dir
    metadata_dir = upload_dir / "_metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    uploaded_files = []
    failed_files = []

    supported_extensions = {".pdf", ".docx", ".txt", ".md", ".pptx", ".xlsx"}

    for file in files:
        try:
            # Check file extension
            file_extension = Path(file.filename).suffix.lower()
            if file_extension not in supported_extensions:
                failed_files.append(
                    {"filename": file.filename, "error": f"Unsupported file type: {file_extension}"}
                )
                continue

            # Save file
            file_path = upload_dir / file.filename

            # Handle duplicate filenames
            counter = 1
            original_stem = file_path.stem
            while file_path.exists():
                file_path = upload_dir / f"{original_stem}_{counter}{file_extension}"
                counter += 1

            # Write file
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            # Get metadata for this file (default to empty dict)
            file_meta = files_metadata.get(file.filename, {})

            # Always save metadata file (even if empty)
            meta_file = metadata_dir / f"{file_path.name}.json"
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(file_meta, f, indent=2, ensure_ascii=False)

            uploaded_files.append(
                {
                    "filename": file.filename,
                    "saved_as": file_path.name,
                    "path": str(file_path),
                    "size_bytes": file_path.stat().st_size,
                    "metadata": file_meta,
                }
            )

        except Exception as e:
            failed_files.append({"filename": file.filename, "error": str(e)})

    return {
        "uploaded": len(uploaded_files),
        "failed": len(failed_files),
        "folder_path": str(upload_dir),
        "files": uploaded_files,
        "errors": failed_files if failed_files else None,
    }


@app.get("/files")
async def list_uploaded_files():
    """List all uploaded files in the data directory"""
    data_dir = Path("data")

    if not data_dir.exists():
        return {"files": [], "total": 0}

    files = []
    supported_extensions = {".pdf", ".docx", ".txt", ".md", ".pptx", ".xlsx"}

    for file_path in data_dir.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
            files.append(
                {
                    "filename": file_path.name,
                    "size_bytes": file_path.stat().st_size,
                    "size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
                    "modified": file_path.stat().st_mtime,
                }
            )

    return {"files": sorted(files, key=lambda x: x["modified"], reverse=True), "total": len(files)}


@app.delete("/files/{filename}")
async def delete_file(filename: str):
    """Delete an uploaded file"""
    data_dir = Path("data")
    file_path = data_dir / filename

    if not file_path.exists():
        raise HTTPException(404, f"File not found: {filename}")

    if not file_path.is_file():
        raise HTTPException(400, f"Not a file: {filename}")
    try:
        file_path.unlink()

        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
        # 251201–BundB Jun – BEGIN
        # Delete metadata file, if exists
        metadata_dir = data_dir / "_metadata"
        try:
            if metadata_dir.exists() and metadata_dir.is_dir():
                metadata_file = metadata_dir / f"{file_path.name}.json"
                if metadata_file.exists() and metadata_file.is_file():
                    metadata_file.unlink()
            # Even if the metadata file does not exist, we ignore the error
        except Exception:
            # Ignore errors when deleting metadata file
            pass
        # 251201–BundB Jun – END
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

        return {"message": f"File deleted: {filename}"}
    except Exception as e:
        raise HTTPException(500, f"Failed to delete file: {str(e)}")


# ============================================================
# FILE MANAGEMENT ENDPOINTS (NEW)
# ============================================================


@app.post("/delete-file", response_model=DeleteFilesResponse)
async def delete_files(request: DeleteFilesRequest):
    """
    Delete multiple files from a specific folder

    - **folder_name**: Target folder path (e.g., "data/user01")
    - **filenames**: List of filenames to delete

    Returns:
    - Number of files deleted
    - Number of files not deleted
    - List of files that couldn't be deleted with reasons

    **Security**: Path traversal protection enabled. Files must be within data directory.
    """
    try:
        file_manager = get_file_manager()
        return file_manager.delete_files(request.folder_name, request.filenames)

    except InvalidPathError as e:
        raise HTTPException(400, str(e))
    except PathNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, f"Permission denied: {str(e)}")
    except FileManagerError as e:
        raise HTTPException(500, str(e))


@app.post("/delete-folder", response_model=DeleteFolderResponse)
async def delete_folder(request: DeleteFolderRequest):
    """
    Delete an entire folder and all its contents

    - **folder_name**: Folder path to delete (e.g., "data/user01")

    **CRITICAL**: Cannot delete the root 'data/' folder. This is a protected directory.

    Returns:
    - Whether deletion was successful
    - Number of files deleted
    - Confirmation message

    **Security**: Path traversal protection enabled. Protected directories cannot be deleted.
    """
    try:
        file_manager = get_file_manager()
        return file_manager.delete_folder(request.folder_name)

    except InvalidPathError as e:
        raise HTTPException(400, str(e))
    except ProtectedPathError as e:
        raise HTTPException(403, str(e))
    except PathNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, f"Permission denied: {str(e)}")
    except FileManagerError as e:
        raise HTTPException(500, str(e))


@app.get("/get-user-files", response_model=GetUserFilesResponse)
async def get_user_files(folder_name: str = "data"):
    """
    Get file tree structure for a folder (like Unix 'tree' command)

    Query parameter:
    - **folder_name**: Folder path to list (default: "data")

    Returns:
    - Hierarchical tree structure of all files and folders
    - Total counts of files, directories
    - Total size in bytes

    **Format**: Returns nested structure with files and subdirectories.
    Hidden files and metadata directories are excluded.

    Example usage:
    - GET /get-user-files?folder_name=data
    - GET /get-user-files?folder_name=data/user01
    """
    try:
        file_manager = get_file_manager()
        return file_manager.get_file_tree(folder_name)

    except InvalidPathError as e:
        raise HTTPException(400, str(e))
    except PathNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, f"Permission denied: {str(e)}")
    except FileManagerError as e:
        raise HTTPException(500, str(e))

# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# 251210–BundB Jun – BEGIN
@app.get("/get-user-files-flat", response_model=GetUserFilesFlatResponse)
async def get_user_files_flat(
    folder_name: str = "data",
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
):
    """
    Get flat, paginated file list for a folder.

    Query parameters:
    - **folder_name**: Folder path to list (default: "data")
    - **page**: Page number (1-based, default: 1)
    - **limit**: Items per page (default: 50, max: 200)
    - **search**: Optional search string (min 2 characters)
                  Filter by filename and basic metadata (e.g., created_user_name)

    Returns:
    - Flat list of files only (no directories)
    - Attached metadata (from _metadata/*.json)
    - Pagination information (page, limit, has_more)
    """
    try:
        file_manager = get_file_manager()
        return file_manager.get_file_list_flat(
            folder_name=folder_name,
            page=page,
            limit=limit,
            search=search,
        )

    except InvalidPathError as e:
        raise HTTPException(400, str(e))
    except PathNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, f"Permission denied: {str(e)}")
    except FileManagerError as e:
        raise HTTPException(500, str(e))
# 251210–BundB Jun – END
# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ============================================================
# PIPELINE PROCESSING ENDPOINTS
# ============================================================


@app.post("/process", response_model=JobStatus)
async def process_folder(background_tasks: BackgroundTasks, params: PipelineRequest):
    """
    Start a new GraphRAG pipeline job

    - **folder_path**: Path to folder containing documents
    - **steps**: Configure which pipeline steps to execute
    - **entity_template**: Optional custom entity types JSON (defaults to src/entity_template/entity_types.json)
    - **relationship_template**: Optional custom relationship types JSON (defaults to src/entity_template/relationship_types.json)
    - **entity_extraction_config**: Required if entity_extraction step is enabled
    - **neo4j_config**: Optional Neo4j connection config (falls back to NEO4J_* env vars)
    - **collection_name**: Qdrant collection name (also used as filter_label in Neo4j)

    Returns job_id for status tracking

    Neo4j Configuration:
    - Can be provided via neo4j_config in request body
    - Falls back to NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD environment variables
    - Falls back to config.yaml settings
    """

    # Validation
    folder_path = Path(normalize_folder_path(params.folder_path))
    if not folder_path.exists():
        raise HTTPException(404, f"Folder not found: {folder_path}")

    # Check if folder contains documents
    supported_files = (
        list(folder_path.glob("*.pdf"))
        + list(folder_path.glob("*.docx"))
        + list(folder_path.glob("*.txt"))
        + list(folder_path.glob("*.md"))
        + list(folder_path.glob("*.pptx"))
        + list(folder_path.glob("*.xlsx"))
    )

    if not supported_files:
        raise HTTPException(400, "No supported documents found in folder")

    # Validate entity extraction config
    if params.steps.entity_extraction and not params.entity_extraction_config:
        raise HTTPException(
            400,
            "entity_extraction_config is required when entity_extraction step is enabled",
        )

    # Note: neo4j_config is now optional - falls back to env vars
    # No validation needed here anymore

    # Validate step dependencies
    if params.steps.entity_linking and not params.steps.entity_extraction:
        raise HTTPException(400, "entity_linking requires entity_extraction to be enabled")

    if params.steps.neo4j_ingestion and not params.steps.entity_linking:
        raise HTTPException(400, "neo4j_ingestion requires entity_linking to be enabled")

    # Create job
    job_id = f"job_{int(time.time() * 1000)}"

    job_data = {
        "status": "queued",
        "created_at": time.time(),
        "folder_path": str(folder_path),
        "file_count": len(supported_files),
        "params": params.dict(),
        "steps_enabled": {k: v for k, v in params.steps.dict().items() if v},
        "collection_name": params.collection_name,
        "custom_templates": {
            "entity_template": params.entity_template is not None,
            "relationship_template": params.relationship_template is not None,
        },
        "neo4j_config_provided": params.neo4j_config is not None,
    }

    # Save job to disk
    if not job_store.save_job(job_id, job_data):
        raise HTTPException(500, "Failed to create job")

    # Start processing
    background_tasks.add_task(process_pipeline_wrapper, job_id, params)

    enabled_steps = [k for k, v in params.steps.dict().items() if v]

    return JobStatus(
        job_id=job_id,
        status="queued",
        message=f"Processing {len(supported_files)} files with steps: {', '.join(enabled_steps)}",
        folder_path=str(folder_path),
    )


@app.get("/status/{job_id}", response_model=JobStatus)
async def get_status(job_id: str):
    """Get current job status"""
    job = job_store.load_job(job_id)

    if not job:
        raise HTTPException(404, "Job not found")

    return JobStatus(
        job_id=job_id,
        status=job["status"],
        message=f"Status: {job['status']}",
        progress=job.get("progress"),
        folder_path=job.get("folder_path"),
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
        # 251216–BundB Jun – pass through error fields from job_store
        error=job.get("error"),
        errors=job.get("errors"),
        error_details=job.get("error_details"),
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    )


@app.get("/result/{job_id}", response_model=ProcessResponse)
async def get_result(job_id: str):
    """Get processing results"""
    job = job_store.load_job(job_id)

    if not job:
        raise HTTPException(404, "Job not found")

    if job["status"] != "completed":
        raise HTTPException(400, f"Job not completed: {job['status']}")

    r = job.get("results", {})

    return ProcessResponse(
        job_id=job_id,
        status="completed",
        folder_path=job["folder_path"],
        steps_executed=job.get("steps_executed", {}),
        documents_processed=r.get("documents"),
        chunks_created=r.get("chunks"),
        vectors_indexed=r.get("vectors"),
        entities_extracted=r.get("entities_extracted"),
        total_entities=r.get("total_entities"),
        linked_entities=r.get("linked_entities"),
        entity_chunk_links=r.get("entity_chunk_links"),
        neo4j_documents=r.get("neo4j_documents"),
        neo4j_entities=r.get("neo4j_entities"),
        neo4j_relationships=r.get("neo4j_relationships"),
        processing_time=job.get("processing_time", 0),
        cleanup_performed=job.get("cleanup_performed", "none"),
        errors=job.get("errors", []),
    )


# ============================================================
# JOB MANAGEMENT ENDPOINTS
# ============================================================


@app.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job from storage"""
    success = job_store.delete_job(job_id)

    if not success:
        raise HTTPException(404, "Job not found")

    return {"message": f"Job {job_id} deleted"}


@app.get("/jobs")
async def list_jobs():
    """List all jobs"""
    all_jobs = job_store.get_all_jobs()

    return {
        "total": len(all_jobs),
        "jobs": [
            {
                "job_id": jid,
                "status": j["status"],
                "folder_path": j.get("folder_path"),
                "created_at": j["created_at"],
                "steps_enabled": j.get("steps_enabled", {}),
            }
            for jid, j in all_jobs.items()
        ],
    }


@app.post("/jobs/cleanup")
async def cleanup_old_jobs(max_age_hours: int = 24):
    """
    Clean up jobs older than specified hours

    - **max_age_hours**: Maximum age in hours (default: 24)
    """
    deleted_count = job_store.cleanup_old_jobs(max_age_hours)

    return {
        "message": f"Cleaned up {deleted_count} old jobs",
        "deleted_count": deleted_count,
        "max_age_hours": max_age_hours,
    }


@app.get("/storage/stats")
async def get_storage_stats():
    """Get job storage statistics"""
    return job_store.get_stats()


# ============================================================
# DATABASE DOCUMENT DELETION ENDPOINTS
# ============================================================


@app.delete("/document/qdrant")
async def delete_document_qdrant(
    doc_id: str,
    collection_name: str,
    filter_label: Optional[str] = None, # 251215–BundB Jun: Added filter_label optional
):
    """
    Delete a document's vectors from Qdrant.

    Connection uses environment variables:
    - QDRANT_URL
    - QDRANT_API_KEY (optional)

    Args:
        doc_id: Document ID to delete
        collection_name: Qdrant collection name
        filter_label: Tenant filter label (optional)
    """
    try:
        result = delete_document_from_qdrant(
            doc_id=doc_id,
            collection_name=collection_name,
            filter_label=filter_label,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to delete from Qdrant: {str(e)}")


@app.delete("/document/neo4j")
async def delete_document_neo4j(
    doc_id: str,
    filter_label: str,
):
    """
    Delete a document, its chunks, and orphaned entities from Neo4j.

    Connection uses environment variables:
    - NEO4J_URI
    - NEO4J_USER
    - NEO4J_PASSWORD

    Args:
        doc_id: Document ID to delete
        filter_label: Tenant filter label
    """
    try:
        result = delete_document_from_neo4j(
            doc_id=doc_id,
            filter_label=filter_label,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to delete from Neo4j: {str(e)}")


# ============================================================
# STARTUP & SHUTDOWN EVENTS
# ============================================================


@app.on_event("startup")
async def startup_event():
    """Actions to perform on startup"""
    stats = job_store.get_stats()
    print("\n" + "=" * 60)
    print("🚀 GraphRAG Pipeline API Started")
    print("=" * 60)
    print(f"📂 Job Storage: {stats['storage_dir']}")
    print(f"📊 Existing Jobs: {stats['total_jobs']}")
    print(f"💾 Storage Size: {stats['total_size_mb']} MB")
    print("=" * 60 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    """Actions to perform on shutdown"""
    print("\n" + "=" * 60)
    print("🛑 GraphRAG Pipeline API Shutting Down")
    print("=" * 60)
    stats = job_store.get_stats()
    print(f"📊 Total Jobs Stored: {stats['total_jobs']}")
    print(f"💾 Total Storage: {stats['total_size_mb']} MB")
    print("✅ All job data persisted to disk")
    print("=" * 60 + "\n")
