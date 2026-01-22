# src/pipeline/neo4j_graphrag_feeder.py

"""
Neo4j GraphRAG Ingestion Module

Ingests linked entity data from entity_chunk_linker into Neo4j.
Reads single {doc_id}_linked.json files containing entities, relationships, and chunks.

Key features:
- Multi-tenant isolation via filter_label
- Qdrant point IDs stored as strings (avoids integer overflow)
- MERGE operations for re-run safety
- Entity deduplication within Neo4j
- Skip existing documents for incremental processing
"""

import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


class Neo4jGraphRAGIngestion:
    """
    Neo4j ingestion for GraphRAG with complete multi-tenant isolation.

    Reads {doc_id}_linked.json files and creates:
    - Entity nodes (with type, chunk references, qdrant_point_ids)
    - Relationship edges (entity-to-entity)
    - Document nodes
    - Chunk nodes (with qdrant_point_id)
    - EXTRACTED_FROM edges (entity → document)
    - APPEARS_IN edges (entity → chunk)
    - PART_OF edges (chunk → document)

    All nodes and edges include filter_label for tenant isolation.
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        filter_label: str = None,
        uri: str = None,
        user: str = None,
        password: str = None,
    ):
        """
        Initialize Neo4j connection.

        Args:
            config_path: Path to config.yaml
            filter_label: REQUIRED for multi-tenant isolation
            uri: Override Neo4j URI
            user: Override Neo4j user
            password: Override Neo4j password
        """
        self.config = self._load_config(config_path)
        self.filter_label = filter_label

        if not self.filter_label:
            print("⚠️ WARNING: No filter_label provided. Multi-tenant isolation disabled!")
        else:
            print(f"🏷️ Neo4j ingestion with filter_label: {self.filter_label}")

        # Neo4j connection - priority: parameter > environment > config
        neo4j_config = self.config.get("neo4j", {})

        self.uri = uri or os.getenv("NEO4J_URI") or neo4j_config.get("uri")
        if not self.uri:
            raise ValueError("Neo4j URI not found")

        self.user = user or os.getenv("NEO4J_USER") or neo4j_config.get("user", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD")
        if not self.password:
            raise ValueError("NEO4J_PASSWORD not found")

        print(f"🔌 Neo4j URI: {self.uri}")
        print(f"👤 Neo4j User: {self.user}")

        # Performance settings
        perf_config = self.config.get("performance", {})
        self.max_retries = perf_config.get("neo4j_max_retries", 3)
        self.batch_size = perf_config.get("neo4j_batch_size", 50)

        # Connect
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self._test_connection()
        self._setup_schema()

        # Cache for entity global_ids within this run
        self.entity_identity_cache = {}

        # Statistics
        self.stats = {
            "documents_processed": 0,
            "documents_skipped": 0,
            "entities_created": 0,
            "entities_updated": 0,
            "relationships_created": 0,
            "chunks_created": 0,
            "entity_chunk_links": 0,
        }

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        config_file = Path(config_path)
        if not config_file.exists():
            config_file = Path("..") / config_path
            if not config_file.exists():
                return {}

        with open(config_file, "r") as f:
            return yaml.safe_load(f)

    def _test_connection(self):
        """Test Neo4j connection."""
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
            print("✅ Connected to Neo4j!")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Neo4j: {e}")

    def _setup_schema(self):
        """Create indexes for multi-tenant GraphRAG."""
        schema_queries = [
            # Entity indexes
            "CREATE CONSTRAINT entity_tenant_unique IF NOT EXISTS FOR (e:Entity) REQUIRE (e.global_id, e.filter_label) IS UNIQUE",
            "CREATE INDEX entity_name_filter IF NOT EXISTS FOR (e:Entity) ON (e.name, e.filter_label)",
            "CREATE INDEX entity_type_filter IF NOT EXISTS FOR (e:Entity) ON (e.type, e.filter_label)",
            # Document indexes
            "CREATE INDEX document_docid_filter IF NOT EXISTS FOR (d:Document) ON (d.doc_id, d.filter_label)",
            # Chunk indexes
            "CREATE INDEX chunk_id_filter IF NOT EXISTS FOR (c:Chunk) ON (c.chunk_id, c.filter_label)",
        ]

        with self.driver.session() as session:
            for query in schema_queries:
                try:
                    session.run(query)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"  ⚠️ Schema warning: {e}")

        print("✅ Multi-tenant GraphRAG schema ready")

    def _execute_with_retry(
        self, session, query: str, params: dict = None, max_retries: int = None
    ):
        """Execute query with retry logic for deadlocks."""
        retries = max_retries or self.max_retries

        for attempt in range(retries):
            try:
                result = session.run(query, params or {})
                return result.data()
            except Exception as e:
                error_str = str(e).lower()
                if "deadlock" in error_str or "lock" in error_str:
                    wait_time = (2**attempt) + random.uniform(0, 1)
                    time.sleep(wait_time)
                    if attempt == retries - 1:
                        raise
                else:
                    raise

        raise Exception(f"Query failed after {retries} attempts")

    def normalize_entity_name(self, name: str) -> str:
        """Normalize entity name for matching."""
        if not name:
            return ""
        normalized = name.lower().strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def generate_global_entity_id(self, name: str, entity_type: str, filter_label: str) -> str:
        """Generate unique entity ID including filter_label for tenant isolation."""
        normalized_name = self.normalize_entity_name(name)
        composite = f"{normalized_name}_{entity_type}_{filter_label or 'default'}"
        return f"{entity_type}_{hash(composite) % 10000000:07d}"

    def _deduplicate_list(self, items: list) -> list:
        """Deduplicate list while preserving order."""
        seen = set()
        result = []
        for item in items:
            item_key = str(item)
            if item_key not in seen:
                seen.add(item_key)
                result.append(item)
        return result

    def document_exists(self, doc_id: str, filter_label: str = None) -> bool:
        """
        Check if a document already exists in Neo4j.

        Args:
            doc_id: Document ID to check
            filter_label: Tenant filter label (uses instance filter_label if not provided)

        Returns:
            True if document exists, False otherwise
        """
        fl = filter_label or self.filter_label
        if not fl:
            return False

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (d:Document {doc_id: $doc_id, filter_label: $filter_label})
                    RETURN count(d) > 0 as exists
                    """,
                    {"doc_id": doc_id, "filter_label": fl},
                )
                record = result.single()
                return record["exists"] if record else False
        except Exception as e:
            print(f"⚠️ Error checking document existence: {e}")
            return False

    def _get_indexed_doc_ids(self) -> set:
        """Get all doc_ids already in Neo4j for this filter_label."""
        if not self.filter_label:
            return set()

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (d:Document {filter_label: $filter_label})
                    RETURN d.doc_id as doc_id
                    """,
                    {"filter_label": self.filter_label},
                )
                return {record["doc_id"] for record in result}
        except Exception as e:
            print(f"⚠️ Error getting indexed doc_ids: {e}")
            return set()

    def ingest_linked_document(
        self, linked_file: Path, skip_existing: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Ingest a single {doc_id}_linked.json file into Neo4j.

        Args:
            linked_file: Path to the linked JSON file
            skip_existing: If True, skip documents that already exist in Neo4j

        Returns:
            Result dict with statistics, or None on skip/failure
        """
        # Load the linked file
        with open(linked_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc_id = data.get("doc_id", linked_file.stem.replace("_linked", ""))
        current_filter_label = data.get("filter_label") or self.filter_label
        source_file = data.get("source_file", f"{doc_id}.pdf")

        if not current_filter_label:
            print(f"  ⚠️ No filter_label for {doc_id}, skipping")
            return None

        # Check if document already exists
        if skip_existing and self.document_exists(doc_id, current_filter_label):
            self.stats["documents_skipped"] += 1
            return {"doc_id": doc_id, "skipped": True, "filter_label": current_filter_label}

        entities = data.get("entities", [])
        relationships = data.get("relationships", [])
        chunks = data.get("chunks", [])

        # Track stats
        entities_created = 0
        entities_updated = 0
        relationships_created = 0
        chunks_created = 0
        entity_chunk_links = 0

        with self.driver.session() as session:
            # Step 1: Create Document node
            self._execute_with_retry(
                session,
                """
                MERGE (d:Document {doc_id: $doc_id, filter_label: $filter_label})
                ON CREATE SET 
                    d.source_file = $source_file,
                    d.created_at = datetime()
                ON MATCH SET 
                    d.updated_at = datetime()
                """,
                {
                    "doc_id": doc_id,
                    "filter_label": current_filter_label,
                    "source_file": source_file,
                },
            )

            # Step 2: Create Entity nodes
            for entity in entities:
                entity_name = entity.get("name", "")
                entity_type = entity.get("type", "UNKNOWN")

                if not entity_name:
                    continue

                global_id = self.generate_global_entity_id(
                    entity_name, entity_type, current_filter_label
                )

                # Qdrant point IDs are already strings from entity_chunk_linker
                qdrant_point_ids = entity.get("qdrant_point_ids", [])
                chunk_ids = entity.get("chunk_ids", [])

                # Use MERGE to handle re-runs
                result = self._execute_with_retry(
                    session,
                    """
                    MERGE (e:Entity {global_id: $global_id, filter_label: $filter_label})
                    ON CREATE SET 
                        e.name = $name,
                        e.type = $type,
                        e.name_normalized = $name_normalized,
                        e.context = $context,
                        e.chunk_ids = $chunk_ids,
                        e.qdrant_point_ids = $qdrant_point_ids,
                        e.total_chunk_appearances = $appearances,
                        e.total_matches = $matches,
                        e.created_at = datetime()
                    ON MATCH SET
                        e.chunk_ids = $chunk_ids,
                        e.qdrant_point_ids = $qdrant_point_ids,
                        e.total_chunk_appearances = $appearances,
                        e.total_matches = $matches,
                        e.updated_at = datetime()
                    WITH e
                    MATCH (d:Document {doc_id: $doc_id, filter_label: $filter_label})
                    MERGE (e)-[r:EXTRACTED_FROM]->(d)
                    SET r.filter_label = $filter_label
                    RETURN e.created_at = e.updated_at as is_new
                    """,
                    {
                        "global_id": global_id,
                        "filter_label": current_filter_label,
                        "name": entity_name,
                        "type": entity_type,
                        "name_normalized": self.normalize_entity_name(entity_name),
                        "context": entity.get("context", ""),
                        "chunk_ids": chunk_ids,
                        "qdrant_point_ids": qdrant_point_ids,
                        "appearances": entity.get("total_chunk_appearances", 0),
                        "matches": entity.get("total_matches", 0),
                        "doc_id": doc_id,
                    },
                )

                # Track if created or updated
                if result and result[0].get("is_new"):
                    entities_created += 1
                else:
                    entities_updated += 1

                # Cache for relationship creation
                cache_key = (
                    self.normalize_entity_name(entity_name),
                    entity_type,
                    current_filter_label,
                )
                self.entity_identity_cache[cache_key] = global_id

            # Step 3: Create Relationship edges (entity-to-entity)
            for rel in relationships:
                source_name = rel.get("source", "")
                target_name = rel.get("target", "")
                rel_type = rel.get("type", "RELATED_TO")

                if not source_name or not target_name:
                    continue

                # Sanitize relationship type for Cypher
                rel_type_safe = re.sub(r"[^A-Za-z0-9_]", "_", rel_type.upper())

                result = self._execute_with_retry(
                    session,
                    f"""
                    MATCH (s:Entity {{filter_label: $filter_label}})
                    WHERE s.name_normalized = $source_normalized
                    MATCH (t:Entity {{filter_label: $filter_label}})
                    WHERE t.name_normalized = $target_normalized
                    AND s <> t
                    MERGE (s)-[r:{rel_type_safe}]->(t)
                    SET r.context = $context,
                        r.document_id = $doc_id,
                        r.filter_label = $filter_label,
                        r.updated_at = datetime()
                    RETURN count(r) as created
                    """,
                    {
                        "filter_label": current_filter_label,
                        "source_normalized": self.normalize_entity_name(source_name),
                        "target_normalized": self.normalize_entity_name(target_name),
                        "context": rel.get("context", ""),
                        "doc_id": doc_id,
                    },
                )

                if result and result[0].get("created", 0) > 0:
                    relationships_created += 1

            # Step 4: Create Chunk nodes and link to document
            for chunk in chunks:
                chunk_id = chunk.get("chunk_id", "")
                if not chunk_id:
                    continue

                # qdrant_point_id is already a string from entity_chunk_linker
                qdrant_point_id = chunk.get("qdrant_point_id", "")
                entities_in_chunk = chunk.get("entities_in_chunk", [])

                # Create chunk node
                self._execute_with_retry(
                    session,
                    """
                    MERGE (c:Chunk {chunk_id: $chunk_id, filter_label: $filter_label})
                    ON CREATE SET 
                        c.qdrant_point_id = $qdrant_point_id,
                        c.document_id = $doc_id,
                        c.chunk_index = $chunk_index,
                        c.entity_count = $entity_count,
                        c.created_at = datetime()
                    ON MATCH SET
                        c.updated_at = datetime()
                    WITH c
                    MATCH (d:Document {doc_id: $doc_id, filter_label: $filter_label})
                    MERGE (c)-[r:PART_OF]->(d)
                    SET r.filter_label = $filter_label
                    """,
                    {
                        "chunk_id": chunk_id,
                        "filter_label": current_filter_label,
                        "qdrant_point_id": qdrant_point_id,
                        "doc_id": doc_id,
                        "chunk_index": chunk.get("chunk_index", 0),
                        "entity_count": chunk.get("entity_count", 0),
                    },
                )
                chunks_created += 1

                # Step 5: Create APPEARS_IN edges (entity → chunk)
                for entity_name in entities_in_chunk:
                    result = self._execute_with_retry(
                        session,
                        """
                        MATCH (c:Chunk {chunk_id: $chunk_id, filter_label: $filter_label})
                        MATCH (e:Entity {filter_label: $filter_label})
                        WHERE e.name_normalized = $entity_normalized
                        MERGE (e)-[r:APPEARS_IN]->(c)
                        SET r.filter_label = $filter_label,
                            r.updated_at = datetime()
                        RETURN count(r) as linked
                        """,
                        {
                            "chunk_id": chunk_id,
                            "filter_label": current_filter_label,
                            "entity_normalized": self.normalize_entity_name(entity_name),
                        },
                    )

                    if result and result[0].get("linked", 0) > 0:
                        entity_chunk_links += 1

        # Update global stats
        self.stats["documents_processed"] += 1
        self.stats["entities_created"] += entities_created
        self.stats["entities_updated"] += entities_updated
        self.stats["relationships_created"] += relationships_created
        self.stats["chunks_created"] += chunks_created
        self.stats["entity_chunk_links"] += entity_chunk_links

        return {
            "doc_id": doc_id,
            "skipped": False,
            "filter_label": current_filter_label,
            "entities_created": entities_created,
            "entities_updated": entities_updated,
            "relationships_created": relationships_created,
            "chunks_created": chunks_created,
            "entity_chunk_links": entity_chunk_links,
        }

    def ingest_all_linked_entities(
        self, linked_entities_folder: str, skip_existing: bool = True
    ) -> Dict[str, Any]:
        """
        Ingest all {doc_id}_linked.json files from folder.

        Args:
            linked_entities_folder: Path to folder with _linked.json files
            skip_existing: If True, skip documents already in Neo4j

        Returns:
            Dict with ingestion statistics
        """
        folder_path = Path(linked_entities_folder)

        if not folder_path.exists():
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        # Look for *_linked.json files
        linked_files = list(folder_path.glob("*_linked.json"))

        # if not linked_files:
        #     raise FileNotFoundError(f"No _linked.json files found in {folder_path}")

        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
        # 251216–BundB Jun: Added logic to handle case where no *_linked.json files are found
        # NOTE:
        # It is possible that entity_linking completed successfully but produced
        # no *_linked.json files (e.g. no entities / no matches for this corpus).
        # In that case, Neo4j ingestion should be treated as a no-op instead of
        # failing the whole pipeline.
        if not linked_files:
            print(f"⚠️ No _linked.json files found in {folder_path} – skipping Neo4j ingestion")

            empty_stats = {
                "input_folder": str(folder_path),
                "total_documents": 0,
                "successful_documents": 0,
                "skipped_documents": 0,
                "failed_documents": 0,
                "processing_time": 0.0,
                "global_stats": {
                    "documents_processed": 0,
                    "documents_skipped": 0,
                    "entities_created": 0,
                    "entities_updated": 0,
                    "relationships_created": 0,
                    "chunks_created": 0,
                    "entity_chunk_links": 0,
                },
                "results": [],
                "filter_label": self.filter_label,
                "neo4j_ingestion_skipped": True,
            }
            return empty_stats
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

        print(f"📊 Found {len(linked_files)} documents in {folder_path}")
        if self.filter_label:
            print(f"🏷️ Tenant (filter_label): {self.filter_label}")

        # Get already indexed doc_ids if skipping existing
        already_indexed = set()
        if skip_existing:
            already_indexed = self._get_indexed_doc_ids()
            if already_indexed:
                print(f"  ⏭️ Found {len(already_indexed)} documents already in Neo4j")

        start_time = time.time()
        all_results = []
        skipped_count = 0

        for linked_file in linked_files:
            try:
                result = self.ingest_linked_document(linked_file, skip_existing=skip_existing)

                if result:
                    if result.get("skipped"):
                        skipped_count += 1
                        print(f"  ⏭️ Skipped {result['doc_id']} (already in Neo4j)")
                    else:
                        all_results.append(result)
                        print(
                            f"  ✅ {result['doc_id']}: {result['entities_created']} entities, "
                            f"{result['chunks_created']} chunks, {result['entity_chunk_links']} links"
                        )
            except Exception as e:
                print(f"  ❌ {linked_file.stem}: {e}")

        total_time = time.time() - start_time

        if skipped_count > 0:
            print(f"\n  ⏭️ Skipped {skipped_count} documents (already in Neo4j)")

        print(f"\n📊 Final Stats for tenant '{self.filter_label}':")
        print(f"   • Documents processed: {self.stats['documents_processed']}")
        print(f"   • Documents skipped: {self.stats['documents_skipped']}")
        print(
            f"   • Entities: {self.stats['entities_created']} created, {self.stats['entities_updated']} updated"
        )
        print(f"   • Chunks: {self.stats['chunks_created']}")
        print(f"   • Relationships: {self.stats['relationships_created']}")
        print(f"   • Entity-Chunk Links: {self.stats['entity_chunk_links']}")

        return {
            "input_folder": str(folder_path),
            "total_documents": len(linked_files),
            "successful_documents": len(all_results),
            "skipped_documents": skipped_count,
            "failed_documents": len(linked_files) - len(all_results) - skipped_count,
            "processing_time": total_time,
            "global_stats": self.stats.copy(),
            "results": all_results,
            "filter_label": self.filter_label,
        }

    def delete_document(self, doc_id: str, filter_label: str = None) -> Dict[str, int]:
        """
        Delete a document and all its related data from Neo4j.
        Handles entity cleanup carefully - only deletes orphaned entities.

        Args:
            doc_id: Document ID to delete
            filter_label: Tenant filter label (uses instance filter_label if not provided)

        Returns:
            Dict with counts of deleted items
        """
        fl = filter_label or self.filter_label
        if not fl:
            raise ValueError("filter_label is required for deletion")

        deleted = {"chunks": 0, "relationships": 0, "entities": 0, "documents": 0}

        with self.driver.session() as session:
            # 1. Delete APPEARS_IN relationships (Entity → Chunk)
            result = self._execute_with_retry(
                session,
                """
                MATCH (e:Entity)-[r:APPEARS_IN]->(c:Chunk {document_id: $doc_id, filter_label: $fl})
                DELETE r
                RETURN count(r) as deleted
                """,
                {"doc_id": doc_id, "fl": fl},
            )

            # 2. Delete Chunks
            result = self._execute_with_retry(
                session,
                """
                MATCH (c:Chunk {document_id: $doc_id, filter_label: $fl})
                DETACH DELETE c
                RETURN count(c) as deleted
                """,
                {"doc_id": doc_id, "fl": fl},
            )
            deleted["chunks"] = result[0].get("deleted", 0) if result else 0

            # 3. Delete EXTRACTED_FROM relationships
            result = self._execute_with_retry(
                session,
                """
                MATCH (e:Entity)-[r:EXTRACTED_FROM]->(d:Document {doc_id: $doc_id, filter_label: $fl})
                DELETE r
                RETURN count(r) as deleted
                """,
                {"doc_id": doc_id, "fl": fl},
            )

            # 4. Delete "orphaned" Entities (no chunk connections anymore)
            # IMPORTANT: Only delete entities that have NO APPEARS_IN relationships to ANY chunk
            result = self._execute_with_retry(
                session,
                """
                MATCH (e:Entity {filter_label: $fl})
                WHERE NOT (e)-[:APPEARS_IN]->(:Chunk)
                DETACH DELETE e
                RETURN count(e) as deleted
                """,
                {"fl": fl},
            )
            deleted["entities"] = result[0].get("deleted", 0) if result else 0

            # 5. Delete Document Node
            result = self._execute_with_retry(
                session,
                """
                MATCH (d:Document {doc_id: $doc_id, filter_label: $fl})
                DETACH DELETE d
                RETURN count(d) as deleted
                """,
                {"doc_id": doc_id, "fl": fl},
            )
            deleted["documents"] = result[0].get("deleted", 0) if result else 0

        print(f"🗑️ Deleted document '{doc_id}': {deleted}")
        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for current tenant."""
        with self.driver.session() as session:
            result = self._execute_with_retry(
                session,
                """
                MATCH (e:Entity {filter_label: $filter_label})
                WITH count(e) as entities
                MATCH (d:Document {filter_label: $filter_label})
                WITH entities, count(d) as documents
                MATCH (c:Chunk {filter_label: $filter_label})
                WITH entities, documents, count(c) as chunks
                OPTIONAL MATCH ()-[r]->() WHERE r.filter_label = $filter_label
                RETURN entities, documents, chunks, count(r) as relationships
                """,
                {"filter_label": self.filter_label or ""},
            )

            if result:
                return {
                    "filter_label": self.filter_label,
                    "entities": result[0].get("entities", 0),
                    "documents": result[0].get("documents", 0),
                    "chunks": result[0].get("chunks", 0),
                    "relationships": result[0].get("relationships", 0),
                }
            return {
                "filter_label": self.filter_label,
                "entities": 0,
                "documents": 0,
                "chunks": 0,
                "relationships": 0,
            }

    def clear_tenant_data(self, confirm: bool = False) -> Dict[str, int]:
        """Clear all data for this tenant. DANGEROUS!"""
        if not self.filter_label:
            raise ValueError("Cannot clear without filter_label")

        if not confirm:
            raise ValueError("Set confirm=True to delete")

        deleted = {"entities": 0, "relationships": 0, "documents": 0, "chunks": 0}

        with self.driver.session() as session:
            # Delete relationships
            result = self._execute_with_retry(
                session,
                "MATCH ()-[r]->() WHERE r.filter_label = $fl DELETE r RETURN count(r) as d",
                {"fl": self.filter_label},
            )
            deleted["relationships"] = result[0].get("d", 0) if result else 0

            # Delete entities
            result = self._execute_with_retry(
                session,
                "MATCH (e:Entity {filter_label: $fl}) DETACH DELETE e RETURN count(e) as d",
                {"fl": self.filter_label},
            )
            deleted["entities"] = result[0].get("d", 0) if result else 0

            # Delete chunks
            result = self._execute_with_retry(
                session,
                "MATCH (c:Chunk {filter_label: $fl}) DETACH DELETE c RETURN count(c) as d",
                {"fl": self.filter_label},
            )
            deleted["chunks"] = result[0].get("d", 0) if result else 0

            # Delete documents
            result = self._execute_with_retry(
                session,
                "MATCH (d:Document {filter_label: $fl}) DETACH DELETE d RETURN count(d) as d",
                {"fl": self.filter_label},
            )
            deleted["documents"] = result[0].get("d", 0) if result else 0

        print(f"🗑️ Cleared tenant '{self.filter_label}': {deleted}")
        return deleted

    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            print("🔌 Neo4j connection closed")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Neo4j GraphRAG Ingestion")
    parser.add_argument("--folder", type=str, required=True, help="Folder with _linked.json files")
    parser.add_argument("--filter-label", type=str, required=True, help="Tenant filter label")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config file")
    parser.add_argument(
        "--force", action="store_true", help="Force reprocess (don't skip existing)"
    )

    args = parser.parse_args()

    ingestion = Neo4jGraphRAGIngestion(
        config_path=args.config,
        filter_label=args.filter_label,
    )

    try:
        results = ingestion.ingest_all_linked_entities(args.folder, skip_existing=not args.force)
        print(
            f"\n✅ Ingested {results['successful_documents']}/{results['total_documents']} documents"
        )
        if results["skipped_documents"] > 0:
            print(f"   Skipped {results['skipped_documents']} (already in Neo4j)")
    finally:
        ingestion.close()
