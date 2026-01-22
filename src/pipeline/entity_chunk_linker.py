# src/pipeline/entity_chunk_linker.py

"""
Entity-Chunk Linker for GraphRAG Pipeline

Links extracted entities to document chunks and prepares data for Neo4j ingestion.
Outputs a single JSON file per document containing entities, relationships, and chunks.

Key features:
- Entity deduplication across chunks
- Qdrant point ID computation (as strings to avoid Neo4j integer overflow)
- filter_label propagation for multi-tenant isolation
- Single output file per document for clean Neo4j ingestion
"""

import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.qdrant_helpers import compute_point_id


class FastEntityChunkLinker:
    """
    Fast entity-chunk linker with Qdrant point ID computation.

    Creates a single output file per document containing:
    - Entities (deduplicated, with chunk references and qdrant_point_ids)
    - Relationships (entity-entity, with filter_label)
    - Chunks (with qdrant_point_id and entity references)

    Supports filter_label for multi-tenant GraphRAG.
    """

    def __init__(
        self,
        chunks_folder: str = "../data/chunked_docs/chunks/",
        entities_folder: str = "../data/extracted_entities/",
        output_folder: str = "../data/step5_linked/",
        filter_label: str = None,
    ):
        """
        Initialize the entity-chunk linker.

        Args:
            chunks_folder: Path to folder with {doc_id}_chunks.json files
            entities_folder: Path to folder with {doc_id}_entities.json files
            output_folder: Path for output {doc_id}_linked.json files (single folder)
            filter_label: Tenant identifier for multi-tenant isolation
        """
        self.chunks_folder = Path(chunks_folder)
        self.entities_folder = Path(entities_folder)
        self.output_folder = Path(output_folder)
        self.filter_label = filter_label

        # Create output directory
        self.output_folder.mkdir(parents=True, exist_ok=True)

        # Statistics
        self.stats = {
            "documents_processed": 0,
            "entities_processed": 0,
            "chunks_processed": 0,
            "entity_chunk_links": 0,
            "qdrant_point_ids_computed": 0,
            "processing_time": 0.0,
        }

        if self.filter_label:
            print(f"🏷️ FastEntityChunkLinker initialized with filter_label: {self.filter_label}")

    def normalize_entity_name(self, name: str) -> str:
        """Normalize entity name for matching."""
        if not name:
            return ""
        # Lowercase, strip whitespace
        normalized = name.lower().strip()
        # Replace multiple spaces with single space
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def find_entity_in_chunk(self, entity_name: str, chunk_text: str) -> Dict:
        """
        Find entity occurrences in chunk text.

        Returns:
            Dict with match_count and positions
        """
        if not entity_name or not chunk_text:
            return {"match_count": 0, "positions": []}

        # Case-insensitive search
        pattern = re.compile(re.escape(entity_name), re.IGNORECASE)
        matches = list(pattern.finditer(chunk_text))

        return {"match_count": len(matches), "positions": [m.start() for m in matches]}

    def process_single_document(self, doc_id: str) -> Optional[Dict]:
        """
        Process a single document: link entities to chunks.

        Args:
            doc_id: Document identifier (without extension)

        Returns:
            Result dict with statistics, or None on failure
        """
        try:
            # Load entities file
            entities_file = self.entities_folder / f"{doc_id}_entities.json"
            if not entities_file.exists():
                print(f"  ⚠️ Entities file not found: {entities_file}")
                return None

            with open(entities_file, "r", encoding="utf-8") as f:
                entities_data = json.load(f)

            # Load chunks file
            chunks_file = self.chunks_folder / f"{doc_id}_chunks.json"
            if not chunks_file.exists():
                print(f"  ⚠️ Chunks file not found: {chunks_file}")
                return None

            with open(chunks_file, "r", encoding="utf-8") as f:
                chunks_data = json.load(f)

            entities = entities_data.get("entities", [])
            relationships = entities_data.get("relationships", [])
            chunks = chunks_data.get("chunks", [])

            if not entities:
                print(f"  ⚠️ No entities found for {doc_id}")
                return None

            if not chunks:
                print(f"  ⚠️ No chunks found for {doc_id}")
                return None

            # Get filter_label from entities data or use instance filter_label
            current_filter_label = entities_data.get("filter_label") or self.filter_label

            # Process: link entities to chunks
            enhanced_entities, enhanced_chunks, chunk_entity_map = self._link_entities_to_chunks(
                doc_id, entities, chunks, current_filter_label
            )

            # Enhance relationships with filter_label
            enhanced_relationships = []
            for rel in relationships:
                enhanced_rel = rel.copy()
                if current_filter_label and "filter_label" not in enhanced_rel:
                    enhanced_rel["filter_label"] = current_filter_label
                enhanced_relationships.append(enhanced_rel)

            # Calculate statistics
            entities_with_chunks = sum(
                1 for e in enhanced_entities if e["total_chunk_appearances"] > 0
            )
            chunks_with_entities = sum(1 for c in enhanced_chunks if c["entity_count"] > 0)
            total_links = sum(e["total_chunk_appearances"] for e in enhanced_entities)

            # Build output structure - SINGLE FILE with everything
            output_data = {
                "doc_id": doc_id,
                "source_file": entities_data.get("source_file", f"{doc_id}.pdf"),
                "filter_label": current_filter_label,
                "processed_at": datetime.now().isoformat(),
                # Entities with chunk references and qdrant_point_ids
                "entities": enhanced_entities,
                # Relationships between entities
                "relationships": enhanced_relationships,
                # Chunks with entity references
                "chunks": enhanced_chunks,
                # Statistics for debugging
                "statistics": {
                    "total_entities": len(enhanced_entities),
                    "entities_with_chunks": entities_with_chunks,
                    "entities_without_chunks": len(enhanced_entities) - entities_with_chunks,
                    "total_relationships": len(enhanced_relationships),
                    "total_chunks": len(enhanced_chunks),
                    "chunks_with_entities": chunks_with_entities,
                    "chunks_without_entities": len(enhanced_chunks) - chunks_with_entities,
                    "total_entity_chunk_links": total_links,
                },
            }

            # Save to single output file
            output_file = self.output_folder / f"{doc_id}_linked.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            # Update stats
            self.stats["documents_processed"] += 1
            self.stats["entities_processed"] += len(enhanced_entities)
            self.stats["chunks_processed"] += len(enhanced_chunks)
            self.stats["entity_chunk_links"] += total_links

            return {
                "doc_id": doc_id,
                "filter_label": current_filter_label,
                "entities": len(enhanced_entities),
                "relationships": len(enhanced_relationships),
                "chunks": len(enhanced_chunks),
                "links": total_links,
                "output_file": str(output_file),
            }

        except Exception as e:
            print(f"  ❌ Error processing {doc_id}: {e}")
            return None

    def _link_entities_to_chunks(
        self, doc_id: str, entities: List[Dict], chunks: List[Dict], filter_label: str
    ) -> Tuple[List[Dict], List[Dict], Dict]:
        """
        Link entities to chunks and compute Qdrant point IDs.

        Returns:
            Tuple of (enhanced_entities, enhanced_chunks, chunk_entity_map)
        """
        # Build mappings
        chunk_entity_map = defaultdict(list)  # chunk_id -> [entity_names]
        entity_chunk_map = defaultdict(list)  # entity_name -> [chunk_refs]

        # Pre-compute Qdrant point IDs for all chunks (as strings!)
        chunk_qdrant_ids = {}
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            if chunk_id:
                # IMPORTANT: Store as string to avoid Neo4j integer overflow
                chunk_qdrant_ids[chunk_id] = str(compute_point_id(chunk_id))

        self.stats["qdrant_point_ids_computed"] += len(chunk_qdrant_ids)

        # Link entities to chunks by searching for entity names in chunk text
        for entity in entities:
            entity_name = entity.get("name", "")
            if not entity_name:
                continue

            for chunk in chunks:
                chunk_id = chunk.get("chunk_id", "")
                chunk_text = chunk.get("text", "")

                if not chunk_id or not chunk_text:
                    continue

                # Find entity in chunk
                match_info = self.find_entity_in_chunk(entity_name, chunk_text)

                if match_info["match_count"] > 0:
                    qdrant_point_id = chunk_qdrant_ids.get(chunk_id, "")

                    # Add to mappings
                    chunk_entity_map[chunk_id].append(entity_name)
                    entity_chunk_map[entity_name].append(
                        {
                            "chunk_id": chunk_id,
                            "qdrant_point_id": qdrant_point_id,
                            "chunk_index": chunk.get("chunk_index", 0),
                            "match_count": match_info["match_count"],
                        }
                    )

        # Build enhanced entities (deduplicated, with all chunk references)
        enhanced_entities = []
        for entity in entities:
            entity_name = entity.get("name", "")
            chunk_refs = entity_chunk_map.get(entity_name, [])

            # Deduplicate chunk_ids and qdrant_point_ids
            chunk_ids = list(dict.fromkeys([ref["chunk_id"] for ref in chunk_refs]))
            qdrant_point_ids = list(dict.fromkeys([ref["qdrant_point_id"] for ref in chunk_refs]))

            enhanced_entity = {
                "name": entity_name,
                "type": entity.get("type", "UNKNOWN"),  # PRESERVE ENTITY TYPE!
                "context": entity.get("context", ""),
                "chunk_ids": chunk_ids,
                "qdrant_point_ids": qdrant_point_ids,  # Already strings
                "total_chunk_appearances": len(chunk_ids),
                "total_matches": sum(ref["match_count"] for ref in chunk_refs),
                "filter_label": filter_label,
            }

            # Preserve any additional fields from original entity
            for key in ["aliases", "description", "importance"]:
                if key in entity:
                    enhanced_entity[key] = entity[key]

            enhanced_entities.append(enhanced_entity)

        # Build enhanced chunks (with entity references)
        enhanced_chunks = []
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            entities_in_chunk = chunk_entity_map.get(chunk_id, [])
            qdrant_point_id = chunk_qdrant_ids.get(chunk_id, "")

            enhanced_chunk = {
                "chunk_id": chunk_id,
                "chunk_index": chunk.get("chunk_index", 0),
                "qdrant_point_id": qdrant_point_id,  # Already string
                "document_id": doc_id,
                "entities_in_chunk": entities_in_chunk,
                "entity_count": len(entities_in_chunk),
                "filter_label": filter_label,
            }

            # Note: We don't store chunk text here - it's already in Qdrant

            enhanced_chunks.append(enhanced_chunk)

        return enhanced_entities, enhanced_chunks, dict(chunk_entity_map)

    def process_all_documents_parallel(self, max_workers: int = 6) -> Dict:
        """
        Process all documents in parallel.

        Returns:
            Summary dict with statistics
        """
        # Find all entity files
        entity_files = list(self.entities_folder.glob("*_entities.json"))

        if not entity_files:
            print(f"⚠️ No entity files found in {self.entities_folder}")
            return {"error": "No entity files found"}

        print(f"🚀 Processing {len(entity_files)} documents with {max_workers} workers...")
        print(f"   🏷️ Filter label: {self.filter_label}")

        start_time = datetime.now()
        results = []
        failed = []

        # Extract doc_ids from filenames
        doc_ids = [f.stem.replace("_entities", "") for f in entity_files]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_doc = {
                executor.submit(self.process_single_document, doc_id): doc_id for doc_id in doc_ids
            }

            for future in as_completed(future_to_doc):
                doc_id = future_to_doc[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                        print(
                            f"  ✅ {result['entities']} entities, {result['chunks']} chunks, "
                            f"{result['links']} links, filter_label: {result['filter_label']}"
                        )
                    else:
                        failed.append(doc_id)
                except Exception as e:
                    print(f"  ❌ {doc_id}: {e}")
                    failed.append(doc_id)

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        self.stats["processing_time"] = processing_time

        print(f"\n📊 Processing complete in {processing_time:.2f}s")
        print(f"   ✅ Successful: {len(results)}/{len(doc_ids)}")
        if failed:
            print(f"   ❌ Failed: {len(failed)}")

        return {
            "total_documents": len(doc_ids),
            "successful_documents": len(results),
            "failed_documents": len(failed),
            "failed_doc_ids": failed,
            "processing_time_seconds": processing_time,
            "statistics": self.stats.copy(),
            "results": results,
        }

    def get_document_info(self, doc_id: str) -> Optional[Dict]:
        """
        Get information about a processed document.

        Args:
            doc_id: Document identifier

        Returns:
            Document statistics or None if not found
        """
        output_file = self.output_folder / f"{doc_id}_linked.json"

        if not output_file.exists():
            return None

        try:
            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            return {
                "doc_id": doc_id,
                "filter_label": data.get("filter_label"),
                "processed_at": data.get("processed_at"),
                "statistics": data.get("statistics", {}),
            }
        except Exception as e:
            print(f"Error reading {output_file}: {e}")
            return None


# CLI usage
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Entity-Chunk Linker")
    parser.add_argument("--chunks", type=str, required=True, help="Chunks folder")
    parser.add_argument("--entities", type=str, required=True, help="Entities folder")
    parser.add_argument("--output", type=str, required=True, help="Output folder")
    parser.add_argument("--filter-label", type=str, help="Tenant filter label")
    parser.add_argument("--workers", type=int, default=6, help="Parallel workers")
    parser.add_argument("--doc-id", type=str, help="Process single document")

    args = parser.parse_args()

    linker = FastEntityChunkLinker(
        chunks_folder=args.chunks,
        entities_folder=args.entities,
        output_folder=args.output,
        filter_label=args.filter_label,
    )

    if args.doc_id:
        result = linker.process_single_document(args.doc_id)
        if result:
            print(f"✅ Processed: {result}")
        else:
            print("❌ Failed")
    else:
        results = linker.process_all_documents_parallel(max_workers=args.workers)
        print(
            f"\n📊 Summary: {results['successful_documents']}/{results['total_documents']} successful"
        )
