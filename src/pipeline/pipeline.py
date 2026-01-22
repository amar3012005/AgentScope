# src/pipeline/pipeline.py

"""
GraphRAG Pipeline Orchestration
Handles all pipeline steps with configurable entity extraction and graph features
Supports custom entity/relationship templates and filter_label for multi-tenant Neo4j
"""

import json
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from dotenv import load_dotenv

from .doc_processor import DocumentProcessor
from .entity_chunk_linker import FastEntityChunkLinker
from .entity_finder import FastEntityExtractor, FastEntitySchema
from .neo4j_graphrag_feeder import Neo4jGraphRAGIngestion
from .qdrant_feeder import QdrantVectorDB
from .semantic_chunker import DocumentChunker

load_dotenv()

# Default template location
DEFAULT_TEMPLATE_DIR = Path("src/entity_template")


def normalize_folder_path(folder_path: str) -> str:
    """
    Normalize folder_path to always be inside data/ directory.

    Examples:
        "testuser" -> "data/testuser"
        "data/testuser" -> "data/testuser"
        "/testuser" -> "data/testuser"
    """
    if not folder_path:
        return "data"

    # Convert to string if Path
    folder_path = str(folder_path)

    # Strip whitespace and slashes
    folder_path = folder_path.strip().strip("/")

    # Security: prevent path traversal
    if ".." in folder_path:
        raise ValueError("Invalid folder path: path traversal not allowed")

    # Ensure data/ prefix
    if not folder_path.startswith("data"):
        folder_path = f"data/{folder_path}"

    # Clean up double slashes
    while "//" in folder_path:
        folder_path = folder_path.replace("//", "/")

    return folder_path


class PipelineConfig:
    """Pipeline configuration container"""

    def __init__(self, config_dict: Dict[str, Any]):
        # Normalize folder_path to ensure data/ prefix
        raw_folder_path = config_dict["folder_path"]
        normalized_path = normalize_folder_path(raw_folder_path)
        self.folder_path = Path(normalized_path)

        # Pipeline steps
        self.steps = config_dict.get(
            "steps",
            {
                "document_processing": True,
                "entity_extraction": False,
                "chunking": True,
                "vector_indexing": True,
                "entity_linking": False,
                "neo4j_ingestion": False,
            },
        )

        # Document processing
        self.force_reprocess = config_dict.get("force_reprocess", False)
        self.quality_threshold = config_dict.get("quality_threshold", 0.5)

        # Chunking
        self.chunking_method = config_dict.get("chunking_method", "semantic_embedding")
        self.chunk_size = config_dict.get("chunk_size", 1000)
        self.chunk_overlap = config_dict.get("chunk_overlap", 200)

        # Entity extraction (optional)
        self.entity_config = config_dict.get(
            "entity_extraction_config",
            {"engine": "openai", "model": "gpt-4o-mini", "chunk_size": 4000, "max_workers": 4},
        )

        # Entity/Relationship templates
        self.entity_template = config_dict.get("entity_template")
        self.relationship_template = config_dict.get("relationship_template")

        # Qdrant
        self.qdrant_url = config_dict.get("qdrant_url")
        self.qdrant_api_key = config_dict.get("qdrant_api_key")
        self.collection_name = config_dict.get("collection_name", "graphrag_chunks")
        self.recreate_collection = config_dict.get("recreate_collection", False)

        # filter_label is derived from collection_name
        self.filter_label = self.collection_name

        # Neo4j (optional) - store the full config dict for passthrough
        self.neo4j_config = config_dict.get("neo4j_config") or {}

        # Cleanup
        self.cleanup_strategy = config_dict.get("cleanup", "none")

        # API overrides
        self.openai_base_url = config_dict.get("openai_base_url")

        # Internal paths
        self.pipeline_base = self.folder_path / "_pipeline"
        self.step1_output = self.pipeline_base / "step1_processed"
        self.step2_output = self.pipeline_base / "step2_entities"
        self.step3_output = self.pipeline_base / "step3_chunks"
        # Step 5: Single folder for linked data (contains {doc_id}_linked.json files)
        self.step5_linked = self.pipeline_base / "step5_linked"

        # Schema directory (where entity_types.json and relationship_types.json are stored)
        self.schema_dir = self.folder_path


def setup_entity_templates(config: PipelineConfig) -> Path:
    """
    Setup entity and relationship templates in the folder_path.

    If templates are provided in config, save them to folder_path.
    If not provided, copy defaults from src/entity_template/.

    Returns:
        Path to the schema directory (folder_path)
    """
    schema_dir = config.schema_dir
    entity_file = schema_dir / "entity_types.json"
    relationship_file = schema_dir / "relationship_types.json"

    # Handle entity_types.json
    if config.entity_template:
        # Save provided template
        print(f"  📝 Saving custom entity template to {entity_file}")
        with open(entity_file, "w", encoding="utf-8") as f:
            json.dump(config.entity_template, f, indent=2, ensure_ascii=False)
    elif not entity_file.exists():
        # Copy default template
        default_entity_file = DEFAULT_TEMPLATE_DIR / "entity_types.json"
        if default_entity_file.exists():
            print(f"  📋 Copying default entity template from {default_entity_file}")
            shutil.copy(default_entity_file, entity_file)
        else:
            raise FileNotFoundError(
                f"No entity template provided and default not found at {default_entity_file}"
            )
    else:
        print(f"  ✅ Using existing entity template at {entity_file}")

    # Handle relationship_types.json
    if config.relationship_template:
        # Save provided template
        print(f"  📝 Saving custom relationship template to {relationship_file}")
        with open(relationship_file, "w", encoding="utf-8") as f:
            json.dump(config.relationship_template, f, indent=2, ensure_ascii=False)
    elif not relationship_file.exists():
        # Copy default template
        default_relationship_file = DEFAULT_TEMPLATE_DIR / "relationship_types.json"
        if default_relationship_file.exists():
            print(f"  📋 Copying default relationship template from {default_relationship_file}")
            shutil.copy(default_relationship_file, relationship_file)
        else:
            raise FileNotFoundError(
                f"No relationship template provided and default not found at {default_relationship_file}"
            )
    else:
        print(f"  ✅ Using existing relationship template at {relationship_file}")

    return schema_dir


def cleanup_folder(folder_path: Path, strategy: str):
    """Cleanup strategy after processing

    strategy = "none"        # Keep everything (original files + processing artifacts)
    strategy = "subfolders"  # Keep original files + metadata, delete _pipeline/ only
    strategy = "all"          # Delete entire folder (for temporary/one-time processing)"""
    if strategy == "none":
        return

    if strategy == "all":
        if folder_path.exists():
            shutil.rmtree(folder_path)

    elif strategy == "subfolders":
        pipeline_dir = folder_path / "_pipeline"
        if pipeline_dir.exists():
            shutil.rmtree(pipeline_dir)
            print(f"  Deleted pipeline folder: {pipeline_dir}")


def run_graphrag_pipeline(
    job_id: str,
    config_dict: Dict[str, Any],
    progress_callback: Optional[Callable[[str, Dict], None]] = None,
) -> Dict[str, Any]:
    """
    Main GraphRAG pipeline orchestration

    Args:
        job_id: Unique job identifier
        config_dict: Pipeline configuration dictionary
        progress_callback: Optional callback function(job_id, progress_dict)

    Returns:
        Dict with processing results and statistics
    """

    def update_progress(step: str, details: Dict = None):
        """Helper to update job progress"""
        if progress_callback:
            progress_callback(job_id, {"step": step, **(details or {})})

    def _get_processed_doc_ids(folder: Path, pattern: str) -> set:
        """Get set of doc_ids that have already been processed (file exists)."""
        if not folder.exists():
            return set()
        processed = set()
        for f in folder.glob(pattern):
            stem = f.stem
            for suffix in ["_entities", "_chunks", "_linked"]:
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            processed.add(stem)
        return processed

    try:
        start_time = time.time()
        config = PipelineConfig(config_dict)
        results = {}
        errors = []

        # Validate folder
        if not config.folder_path.exists():
            raise ValueError(f"Folder not found: {config.folder_path}")

        # Override API URLs if provided
        if config.openai_base_url:
            os.environ["OPENAI_API_BASE_URL"] = config.openai_base_url

        # Create pipeline structure
        config.pipeline_base.mkdir(exist_ok=True)

        # ============================================================
        # SETUP: Entity/Relationship Templates
        # ============================================================
        if config.steps.get("entity_extraction", False):
            print("📋 Setting up entity/relationship templates...")
            schema_dir = setup_entity_templates(config)
            print(f"  ✅ Schema directory: {schema_dir}")
            print(f"  🏷️ Filter label: {config.filter_label}")

        # ============================================================
        # STEP 1: DOCUMENT PROCESSING
        # ============================================================
        if config.steps.get("document_processing", True):
            update_progress("document_processing", {"status": "starting"})

            try:
                processor = DocumentProcessor(
                    output_dir=str(config.step1_output),
                    preserve_filenames=True,
                    quality_threshold=config.quality_threshold,
                    track_performance=False,
                )

                # Check which documents already processed (if not force_reprocess)
                already_processed = set()
                if not config.force_reprocess:
                    texts_folder = config.step1_output / "texts"
                    if texts_folder.exists():
                        already_processed = {f.stem for f in texts_folder.glob("*.txt")}
                        if already_processed:
                            print(f"  ⏭️ Found {len(already_processed)} already processed documents")

                # Get list of all source files
                all_files = []
                for pattern in ["*.pdf", "*.docx", "*.pptx", "*.xlsx", "*.txt", "*.md"]:
                    all_files.extend(config.folder_path.glob(pattern))

                # Filter out already processed (based on doc_id)
                files_to_process = []
                skipped_count = 0
                for file_path in all_files:
                    doc_id = processor.generate_doc_id(str(file_path))
                    if doc_id in already_processed:
                        skipped_count += 1
                    else:
                        files_to_process.append(file_path)

                if skipped_count > 0:
                    print(f"  ⏭️ Skipping {skipped_count} already processed documents")

                # Process only new documents
                doc_results = []
                for file_path in files_to_process:
                    result = processor.process_single_file(str(file_path), verbose=True)
                    if result:
                        doc_results.append(result)

                # Load metadata for skipped docs (for accurate total count)
                metadata_folder = config.step1_output / "metadata"
                for doc_id in already_processed:
                    meta_file = metadata_folder / f"{doc_id}.json"
                    if meta_file.exists():
                        with open(meta_file, "r") as f:
                            doc_results.append(json.load(f))

                results["documents"] = len(doc_results)
                results["documents_new"] = len(files_to_process)
                results["documents_skipped"] = skipped_count
                update_progress(
                    "document_processing",
                    {
                        "status": "completed",
                        "documents": len(doc_results),
                        "new": len(files_to_process),
                        "skipped": skipped_count,
                    },
                )

            except Exception as e:
                errors.append(f"Document processing: {str(e)}")
                raise

        # ============================================================
        # STEP 2: ENTITY EXTRACTION (OPTIONAL)
        # ============================================================
        if config.steps.get("entity_extraction", False):
            update_progress("entity_extraction", {"status": "starting"})

            try:
                # Initialize schema from folder_path (where templates are stored)
                schema = FastEntitySchema(schema_dir=str(config.schema_dir))

                extractor = FastEntityExtractor(
                    schema=schema,
                    provider=config.entity_config.get("engine", "openai"),
                    chunk_size=config.entity_config.get("chunk_size", 4000),
                    max_workers=config.entity_config.get("max_workers", 4),
                    config_path="config.yaml",
                    filter_label=config.filter_label,
                )

                # Load documents from step 1
                texts_folder = config.step1_output / "texts"
                metadata_folder = config.step1_output / "metadata"

                # Check which documents already have entities extracted
                config.step2_output.mkdir(parents=True, exist_ok=True)
                already_extracted = set()
                if not config.force_reprocess:
                    already_extracted = _get_processed_doc_ids(
                        config.step2_output, "*_entities.json"
                    )
                    if already_extracted:
                        print(
                            f"  ⏭️ Found {len(already_extracted)} documents with existing entities"
                        )

                text_files = list(texts_folder.glob("*.txt"))
                documents = []
                skipped_count = 0

                for text_file in text_files:
                    doc_id = text_file.stem

                    # Skip if already extracted
                    if doc_id in already_extracted:
                        skipped_count += 1
                        continue

                    with open(text_file, "r", encoding="utf-8") as f:
                        text = f.read()

                    metadata = {}
                    meta_file = metadata_folder / f"{doc_id}.json"
                    if meta_file.exists():
                        with open(meta_file, "r") as f:
                            metadata = json.load(f)

                    documents.append((doc_id, text, metadata))

                if skipped_count > 0:
                    print(f"  ⏭️ Skipping {skipped_count} documents (entities already extracted)")

                # Extract entities only for new documents
                entity_results = []
                if documents:
                    entity_results = extractor.extract_entities_threaded(documents)

                    # Save results
                    for result in entity_results:
                        doc_id = result["doc_id"]
                        output_file = config.step2_output / f"{doc_id}_entities.json"
                        with open(output_file, "w", encoding="utf-8") as f:
                            json.dump(result, f, indent=2, ensure_ascii=False)

                results["entities_extracted"] = len(entity_results)
                results["entities_skipped"] = skipped_count
                results["total_entities"] = sum(len(r.get("entities", [])) for r in entity_results)

                update_progress(
                    "entity_extraction",
                    {
                        "status": "completed",
                        "documents": len(entity_results),
                        "skipped": skipped_count,
                        "entities": results["total_entities"],
                    },
                )

            except Exception as e:
                errors.append(f"Entity extraction: {str(e)}")
                raise

        # ============================================================
        # STEP 3: CHUNKING
        # ============================================================
        if config.steps.get("chunking", True):
            update_progress("chunking", {"status": "starting"})

            try:
                chunker = DocumentChunker(
                    config_path="config.yaml",
                    method=config.chunking_method,
                    chunk_size=config.chunk_size,
                    chunk_overlap=config.chunk_overlap,
                    output_dir=str(config.step3_output),
                    track_performance=False,
                )

                # Check which documents already have chunks
                chunks_folder = config.step3_output / "chunks"
                chunks_folder.mkdir(parents=True, exist_ok=True)

                already_chunked = set()
                if not config.force_reprocess:
                    already_chunked = _get_processed_doc_ids(chunks_folder, "*_chunks.json")
                    if already_chunked:
                        print(f"  ⏭️ Found {len(already_chunked)} documents with existing chunks")

                # Load documents from step 1
                texts_folder = config.step1_output / "texts"
                metadata_folder = config.step1_output / "metadata"
                text_files = list(texts_folder.glob("*.txt"))

                chunk_results = []
                skipped_count = 0
                total_chunks = 0

                for text_file in text_files:
                    doc_id = text_file.stem

                    # Skip if already chunked
                    if doc_id in already_chunked:
                        skipped_count += 1
                        # Load existing chunk count for statistics
                        existing_chunk_file = chunks_folder / f"{doc_id}_chunks.json"
                        if existing_chunk_file.exists():
                            with open(existing_chunk_file, "r") as f:
                                existing_data = json.load(f)
                                total_chunks += existing_data.get("total_chunks", 0)
                        continue

                    # Load text and metadata
                    with open(text_file, "r", encoding="utf-8") as f:
                        text = f.read()

                    metadata = {}
                    original_filename = None
                    meta_file = metadata_folder / f"{doc_id}.json"
                    if meta_file.exists():
                        with open(meta_file, "r") as f:
                            metadata = json.load(f)
                            original_filename = metadata.get("original_filename") or metadata.get(
                                "filename"
                            )

                    # Chunk document
                    result = chunker.chunk_document(
                        doc_id=doc_id,
                        text=text,
                        metadata=metadata,
                        original_filename=original_filename,
                        verbose=True,
                    )
                    chunk_results.append(result)
                    total_chunks += result.get("total_chunks", 0)

                if skipped_count > 0:
                    print(f"  ⏭️ Skipped {skipped_count} documents (already chunked)")

                results["chunks"] = total_chunks
                results["chunks_new"] = len(chunk_results)
                results["chunks_skipped"] = skipped_count
                update_progress(
                    "chunking",
                    {
                        "status": "completed",
                        "chunks": total_chunks,
                        "new": len(chunk_results),
                        "skipped": skipped_count,
                    },
                )

            except Exception as e:
                errors.append(f"Chunking: {str(e)}")
                raise

        # ============================================================
        # STEP 4: VECTOR INDEXING
        # ============================================================
        if config.steps.get("vector_indexing", True):
            update_progress("vector_indexing", {"status": "starting"})

            try:
                # Get API settings
                openai_api_key = os.getenv("OPENAI_API_KEY")
                openai_base_url = config.openai_base_url or os.getenv("OPENAI_API_BASE_URL")

                # Initialize Qdrant - prioritize URL from environment
                qdrant_url = os.getenv("QDRANT_URL") or config.qdrant_url
                qdrant_api_key = os.getenv("QDRANT_API_KEY") or config.qdrant_api_key
                qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))

                if qdrant_url:
                    vdb = QdrantVectorDB(
                        url=qdrant_url,
                        api_key=qdrant_api_key,
                        collection_name=config.collection_name,
                        openai_api_key=openai_api_key,
                        openai_base_url=openai_base_url,
                    )
                else:
                    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
                    vdb = QdrantVectorDB(
                        host=qdrant_host,
                        port=qdrant_port,
                        collection_name=config.collection_name,
                        openai_api_key=openai_api_key,
                        openai_base_url=openai_base_url,
                    )

                # Create/recreate collection
                if config.recreate_collection:
                    vdb.create_collection(recreate=True)
                else:
                    try:
                        vdb.client.get_collection(config.collection_name)
                    except:
                        vdb.create_collection(recreate=False)

                # Index chunks (mit Skip-Logik im Feeder)
                chunks_folder = config.step3_output / "chunks"
                if not chunks_folder.exists():
                    raise ValueError(f"Chunks folder not found: {chunks_folder}")

                # Pass force_reprocess to feeder
                index_results = vdb.index_documents(
                    str(chunks_folder), skip_existing=not config.force_reprocess
                )

                # Get vector count
                collection_info = vdb.client.get_collection(config.collection_name)
                results["vectors"] = collection_info.points_count
                results["vectors_new"] = index_results.get("indexed", 0)
                results["vectors_skipped"] = index_results.get("skipped", 0)

                update_progress(
                    "vector_indexing",
                    {
                        "status": "completed",
                        "vectors": results["vectors"],
                        "new": results.get("vectors_new", 0),
                        "skipped": results.get("vectors_skipped", 0),
                    },
                )

            except Exception as e:
                errors.append(f"Vector indexing: {str(e)}")
                raise

        # ============================================================
        # STEP 5: ENTITY-CHUNK LINKING (OPTIONAL)
        # ============================================================
        if config.steps.get("entity_linking", False):
            update_progress("entity_linking", {"status": "starting"})

            try:
                # Create single output directory for linked data
                config.step5_linked.mkdir(parents=True, exist_ok=True)

                # Check which documents already have linked data
                already_linked = set()
                if not config.force_reprocess:
                    already_linked = _get_processed_doc_ids(config.step5_linked, "*_linked.json")
                    if already_linked:
                        print(
                            f"  ⏭️ Found {len(already_linked)} documents with existing linked data"
                        )

                linker = FastEntityChunkLinker(
                    chunks_folder=str(config.step3_output / "chunks"),
                    entities_folder=str(config.step2_output),
                    output_folder=str(config.step5_linked),
                    filter_label=config.filter_label,
                )

                # Get list of entity files to process
                entity_files = list(config.step2_output.glob("*_entities.json"))
                docs_to_process = []
                skipped_count = 0

                for entity_file in entity_files:
                    doc_id = entity_file.stem.replace("_entities", "")
                    if doc_id in already_linked:
                        skipped_count += 1
                    else:
                        docs_to_process.append(doc_id)

                if skipped_count > 0:
                    print(f"  ⏭️ Skipping {skipped_count} documents (already linked)")

                # Process only new documents
                successful_count = 0
                total_links = 0
                for doc_id in docs_to_process:
                    result = linker.process_single_document(doc_id)
                    if result:
                        successful_count += 1
                        total_links += result.get("links", 0)

                results["linked_entities"] = successful_count
                results["linked_skipped"] = skipped_count
                results["entity_chunk_links"] = total_links

                update_progress(
                    "entity_linking",
                    {
                        "status": "completed",
                        "documents": successful_count,
                        "skipped": skipped_count,
                        "links": total_links,
                    },
                )

            except Exception as e:
                errors.append(f"Entity linking: {str(e)}")
                raise

        # ============================================================
        # STEP 6: NEO4J INGESTION (OPTIONAL)
        # ============================================================
        if config.steps.get("neo4j_ingestion", False):
            update_progress("neo4j_ingestion", {"status": "starting"})

            ingestion = None
            try:
                neo4j_uri = None
                neo4j_user = None
                neo4j_password = None

                if config.neo4j_config:
                    neo4j_uri = config.neo4j_config.get("uri")
                    neo4j_user = config.neo4j_config.get("user")
                    neo4j_password = config.neo4j_config.get("password")

                print(
                    f"  🔌 Neo4j URI from request: {neo4j_uri or '(not provided, using env/config)'}"
                )

                ingestion = Neo4jGraphRAGIngestion(
                    config_path="config.yaml",
                    filter_label=config.filter_label,
                    uri=neo4j_uri,
                    user=neo4j_user,
                    password=neo4j_password,
                )

                # Ingest with skip logic (im Feeder)
                ingest_results = ingestion.ingest_all_linked_entities(
                    linked_entities_folder=str(config.step5_linked),
                    skip_existing=not config.force_reprocess,
                )

                results["neo4j_documents"] = ingest_results.get("successful_documents", 0)
                results["neo4j_skipped"] = ingest_results.get("skipped_documents", 0)
                results["neo4j_entities"] = ingest_results.get("global_stats", {}).get(
                    "entities_created", 0
                )
                results["neo4j_chunks"] = ingest_results.get("global_stats", {}).get(
                    "chunks_created", 0
                )
                results["neo4j_relationships"] = ingest_results.get("global_stats", {}).get(
                    "relationships_created", 0
                )
                results["neo4j_entity_chunk_links"] = ingest_results.get("global_stats", {}).get(
                    "entity_chunk_links", 0
                )

                update_progress(
                    "neo4j_ingestion",
                    {
                        "status": "completed",
                        "documents": results["neo4j_documents"],
                        "skipped": results.get("neo4j_skipped", 0),
                        "entities": results["neo4j_entities"],
                        "chunks": results["neo4j_chunks"],
                        "relationships": results["neo4j_relationships"],
                    },
                )

            except Exception as e:
                errors.append(f"Neo4j ingestion: {str(e)}")
                raise
            finally:
                if ingestion is not None:
                    try:
                        ingestion.close()
                    except Exception:
                        pass

        # ============================================================
        # CLEANUP
        # ============================================================
        cleanup_folder(config.folder_path, config.cleanup_strategy)

        # ============================================================
        # FINAL RESULTS
        # ============================================================
        processing_time = time.time() - start_time

        return {
            "success": True,
            "job_id": job_id,
            "folder_path": str(config.folder_path),
            "steps_executed": {k: v for k, v in config.steps.items() if v},
            "results": results,
            "processing_time": processing_time,
            "cleanup_performed": config.cleanup_strategy,
            "filter_label": config.filter_label,
            "errors": errors,
        }

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"\nPIPELINE ERROR for {job_id}:")
        print(error_details)

        return {
            "success": False,
            "job_id": job_id,
            "error": str(e),
            "error_details": error_details,
            "errors": errors + [str(e)],
        }
