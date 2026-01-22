# src/pipeline/qdrant_feeder.py

"""
Simplified Qdrant Vector Database for Document Chunks
Using OpenAI text-embedding-3-small via LangChain
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from utils.bge_m3_embedding import BGEM3Embeddings
from utils.qdrant_helpers import compute_point_id  # Importing the helper function

# Load environment variables
load_dotenv()


class QdrantVectorDB:
    """Simple Qdrant vector database handler with OpenAI embeddings."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection_name: str = "document_chunks",
        embedding_model: str = "bge-m3",
        openai_api_key: Optional[str] = None,
        openai_base_url: Optional[str] = None,
    ):
        """
        Initialize Qdrant Vector Database with BGE-M3 embeddings

        Args:
            host: Qdrant host (default: localhost)
            port: Qdrant port (default: 6333)
            url: Full Qdrant URL (if provided, overrides host/port)
            api_key: Qdrant API key (for cloud instances)
            collection_name: Name of the collection
            embedding_model: Embedding model name (now always "bge-m3")
            openai_api_key: Deprecated (kept for compatibility)
            openai_base_url: Deprecated (kept for compatibility)
        """
        # Initialize Qdrant client
        if url:
            # Use URL-based connection (for cloud/remote instances)
            self.client = QdrantClient(url=url, api_key=api_key)
            print(f"✅ Connected to Qdrant at {url}")
        else:
            # Use host/port connection (for local instances)
            self.client = QdrantClient(host=host, port=port)
            print(f"✅ Connected to Qdrant at {host}:{port}")

        self.collection_name = collection_name
        self.embedding_model_name = "bge-m3"

        # Initialize BGE-M3 embeddings
        try:
            self.embeddings = BGEM3Embeddings(
                timeout=180,
            )
            self.use_langchain = True  # Keep for compatibility
            self.embedding_dim = 1024  # Titan dimension

            print(f"✅ Using Amazon Bedrock Titan Embedding: {self.embedding_model_name}")

            print(f"   Embedding dimension: {self.embedding_dim}")

        except Exception as e:
            raise RuntimeError(f"Failed to initialize Titan Embedding embeddings: {e}")

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text."""
        try:
            embedding = self.embeddings.embed_query(text)
            return embedding
        except Exception as e:
            print(f"Error getting embedding: {e}")
            # Return zero vector as fallback
            return [0.0] * self.embedding_dim

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for multiple texts."""
        try:
            return self.embeddings.embed_documents(texts)
        except Exception as e:
            print(f"Error getting batch embeddings: {e}")
            # Fallback to individual embeddings
            embeddings = []
            for text in texts:
                embeddings.append(self.get_embedding(text))
            return embeddings

    def _get_indexed_doc_ids(self) -> set:
        """Get all doc_ids already indexed in the collection."""
        try:
            # Check if collection exists
            collections = [c.name for c in self.client.get_collections().collections]
            if self.collection_name not in collections:
                return set()

            doc_ids = set()
            offset = None

            while True:
                records, next_offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=1000,
                    offset=offset,
                    with_payload=["doc_id"],
                )

                for record in records:
                    if record.payload and "doc_id" in record.payload:
                        doc_ids.add(record.payload["doc_id"])

                if next_offset is None:
                    break
                offset = next_offset

            return doc_ids

        except Exception as e:
            print(f"⚠️ Error getting indexed doc_ids: {e}")
            return set()

    def create_collection(self, recreate=False):
        """Create or recreate collection."""
        collections = [c.name for c in self.client.get_collections().collections]

        if self.collection_name in collections:
            if recreate:
                self.client.delete_collection(self.collection_name)
                print(f"   Deleted existing collection '{self.collection_name}'")
            else:
                print(f"Collection '{self.collection_name}' already exists")
                return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
        )
        print(f"✅ Created collection '{self.collection_name}'")

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for similar chunks."""
        # Generate query embedding
        query_embedding = self.get_embedding(query)

        # Use the new query_points method
        results = self.client.search(
            collection_name=self.collection_name, query_vector=query_embedding, limit=limit
        )

        # Format results
        return [
            {
                "score": point.score,
                "doc_id": point.payload.get("doc_id"),
                "chunk_id": point.payload.get("chunk_id"),
                "text": point.payload.get("text"),
                "original_filename": point.payload.get("original_filename"),
            }
            for point in results
        ]

    def index_documents(self, chunks_folder: str, skip_existing: bool = True) -> Dict:
        """
        Index all document chunks from folder.

        Args:
            chunks_folder: Path to folder with chunk JSON files
            skip_existing: If True, skip documents already in collection

        Returns:
            Dict with indexing statistics
        """
        chunk_files = list(Path(chunks_folder).glob("*_chunks.json"))
        print(f"📂 Found {len(chunk_files)} documents to index")

        # Check which documents are already indexed
        already_indexed = set()
        if skip_existing:
            already_indexed = self._get_indexed_doc_ids()
            if already_indexed:
                print(f"  ⏭️ Found {len(already_indexed)} documents already in Qdrant")

        all_points = []
        batch_texts = []
        batch_metadata = []
        skipped_docs = 0
        indexed_docs = 0

        # Collect all texts for batch embedding
        for chunk_file in chunk_files:
            with open(chunk_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            doc_id = data["doc_id"]

            # Skip if already indexed
            if doc_id in already_indexed:
                skipped_docs += 1
                continue

            indexed_docs += 1
            chunks = data["chunks"]

            for chunk in chunks:
                chunk_text = chunk["text"]
                chunk_id = chunk["chunk_id"]

                # Get original_filename if available
                original_filename = chunk.get("original_filename") or data.get("original_filename")

                # Load upload metadata based on original_filename
                upload_metadata = {}
                if original_filename:
                    try:
                        metadata_dir = self._find_metadata_dir(chunks_folder)

                        if metadata_dir:
                            metadata_file = metadata_dir / f"{original_filename}.json"

                            if metadata_file.exists():
                                with open(metadata_file, "r", encoding="utf-8") as f:
                                    upload_metadata = json.load(f)
                                # Only print once per unique file (avoid spam)
                                if chunk.get("chunk_index", 0) == 0:
                                    print(f"  ✓ Loaded metadata for {original_filename}")
                    except Exception as e:
                        print(f"  ⚠ Warning: Could not load metadata for {original_filename}: {e}")

                batch_texts.append(chunk_text)
                batch_metadata.append(
                    {
                        "doc_id": doc_id,
                        "chunk_id": chunk_id,
                        "chunk_index": chunk.get("chunk_index", 0),
                        "original_filename": original_filename,
                        "upload_metadata": upload_metadata,
                    }
                )

        if skipped_docs > 0:
            print(f"  ⏭️ Skipped {skipped_docs} documents (already indexed)")

        # If nothing to index, return early
        if not batch_texts:
            print("  ✅ No new documents to index")
            return {
                "indexed": 0,
                "skipped": skipped_docs,
                "total_points": 0,
            }

        # Get embeddings in batches
        print(f"  Generating embeddings for {len(batch_texts)} chunks...")
        batch_size = 100
        all_embeddings = []

        for i in range(0, len(batch_texts), batch_size):
            batch = batch_texts[i : i + batch_size]
            embeddings = self.get_embeddings_batch(batch)
            all_embeddings.extend(embeddings)

            # Progress indicator
            if (i + batch_size) % 500 == 0 or i + batch_size >= len(batch_texts):
                print(
                    f"    Processed {min(i + batch_size, len(batch_texts))}/{len(batch_texts)} chunks"
                )

        # Create points for Qdrant
        for i, (text, metadata, embedding) in enumerate(
            zip(batch_texts, batch_metadata, all_embeddings)
        ):
            # Generate unique ID
            chunk_id = metadata["chunk_id"]
            point_id = compute_point_id(chunk_id)

            # Create payload
            payload = {
                "doc_id": metadata["doc_id"],
                "chunk_id": chunk_id,
                "text": text,
                "chunk_index": metadata["chunk_index"],
            }

            # Add original_filename if available
            if metadata.get("original_filename"):
                payload["original_filename"] = metadata["original_filename"]

            # Add upload metadata as nested object
            upload_meta = metadata.get("upload_metadata", {})
            payload["metadata"] = upload_meta

            # Create point
            point = PointStruct(id=point_id, vector=embedding, payload=payload)
            all_points.append(point)

        # Batch upload to Qdrant
        print(f"  Uploading {len(all_points)} points to Qdrant...")
        upload_batch_size = 100
        for i in range(0, len(all_points), upload_batch_size):
            batch = all_points[i : i + upload_batch_size]
            self.client.upsert(collection_name=self.collection_name, points=batch)

        print(f"✅ Indexed {len(all_points)} chunks from {indexed_docs} new documents")

        return {
            "indexed": indexed_docs,
            "skipped": skipped_docs,
            "total_points": len(all_points),
        }

    def _find_metadata_dir(self, chunks_folder: str) -> Optional[Path]:
        """
        Find the _metadata directory by navigating from chunks_folder.

        The chunks_folder follows the pattern: {folder_path}/_pipeline/step3_chunks/chunks
        We want to find: {folder_path}/_metadata

        Examples:
        - data/_pipeline/step3_chunks/chunks → data/_metadata
        - data/user1/_pipeline/step3_chunks/chunks → data/user1/_metadata
        - data/customers/acme/_pipeline/step3_chunks/chunks → data/customers/acme/_metadata

        Returns:
            Path to _metadata directory if found, None otherwise
        """
        chunks_path = Path(chunks_folder).resolve()
        parts = chunks_path.parts

        # Find index of '_pipeline' in path parts
        try:
            pipeline_index = parts.index("_pipeline")
        except ValueError:
            # _pipeline not found in path
            print(f"  ⚠ Warning: '_pipeline' not found in path: {chunks_path}")
            return None

        # Construct path up to (but not including) _pipeline
        # This gives us the folder_path
        base_path = Path(*parts[:pipeline_index])
        metadata_dir = base_path / "_metadata"

        if metadata_dir.exists():
            return metadata_dir
        else:
            # Metadata dir doesn't exist yet (no files were uploaded with metadata)
            # This is not an error, just means no metadata was provided
            return None

    def get_rag_context(self, query: str, max_chunks: int = 5) -> str:
        """Get context for RAG/LLM."""
        results = self.search(query, limit=max_chunks)

        context_parts = []
        for r in results:
            source = r.get("original_filename") or r["doc_id"]
            context_parts.append(f"[Source: {source}]\n{r['text']}")

        return "\n\n---\n\n".join(context_parts)

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict]:
        """Get a specific chunk by its chunk_id (no vector needed)."""
        # Convert chunk_id to the same point_id format we used for indexing
        point_id = int(hashlib.md5(chunk_id.encode()).hexdigest()[:16], 16)

        try:
            # Retrieve point by ID
            points = self.client.retrieve(collection_name=self.collection_name, ids=[point_id])

            if points:
                point = points[0]
                return {
                    "chunk_id": point.payload.get("chunk_id"),
                    "doc_id": point.payload.get("doc_id"),
                    "text": point.payload.get("text"),
                    "chunk_index": point.payload.get("chunk_index"),
                    "original_filename": point.payload.get("original_filename"),
                }
            return None
        except Exception as e:
            print(f"Error retrieving chunk {chunk_id}: {e}")
            return None

    def get_multiple_chunks(self, chunk_ids: List[str]) -> List[Dict]:
        """Get multiple chunks by their IDs (batch retrieval)."""
        # Convert chunk_ids to point_ids
        point_ids = [int(hashlib.md5(cid.encode()).hexdigest()[:16], 16) for cid in chunk_ids]

        try:
            points = self.client.retrieve(collection_name=self.collection_name, ids=point_ids)

            results = []
            for point in points:
                results.append(
                    {
                        "chunk_id": point.payload.get("chunk_id"),
                        "doc_id": point.payload.get("doc_id"),
                        "text": point.payload.get("text"),
                        "chunk_index": point.payload.get("chunk_index"),
                        "original_filename": point.payload.get("original_filename"),
                    }
                )
            return results
        except Exception as e:
            print(f"Error retrieving chunks: {e}")
            return []

    def get_document_chunks(self, doc_id: str) -> List[Dict]:
        """Get all chunks from a specific document."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        # Use scroll to get all chunks from a document
        chunks = []
        offset = None

        while True:
            records, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
                limit=100,
                offset=offset,
            )

            for record in records:
                chunks.append(
                    {
                        "chunk_id": record.payload.get("chunk_id"),
                        "chunk_index": record.payload.get("chunk_index"),
                        "text": record.payload.get("text") or record.payload.get("content"),
                        "original_filename": record.payload.get("original_filename"),
                    }
                )

            if next_offset is None:
                break
            offset = next_offset

        # Sort by chunk_index
        chunks.sort(key=lambda x: x.get("chunk_index", 0))
        return chunks

    def delete_document(self, doc_id: str) -> int:
        """
        Delete all chunks for a specific document.

        Args:
            doc_id: Document ID to delete

        Returns:
            Number of points deleted
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        try:
            # Count before deletion
            chunks_before = self.get_document_chunks(doc_id)
            count_before = len(chunks_before)

            if count_before == 0:
                print(f"  No chunks found for doc_id: {doc_id}")
                return 0

            # Delete by filter
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
            )

            print(f"  ✅ Deleted {count_before} chunks for doc_id: {doc_id}")
            return count_before

        except Exception as e:
            print(f"  ❌ Error deleting document {doc_id}: {e}")
            return 0

    def update_collection_with_openai_embeddings(self, chunks_folder: str):
        """
        Re-index existing collection with OpenAI embeddings.
        Useful for migrating from sentence-transformers to OpenAI.
        """
        print(f"🔄 Re-indexing collection with OpenAI {self.embedding_model_name}...")

        # Delete and recreate collection
        self.create_collection(recreate=True)

        # Re-index with OpenAI embeddings
        self.index_documents(chunks_folder, skip_existing=False)

        print("✅ Collection re-indexed with OpenAI embeddings")


# Simple usage example
if __name__ == "__main__":
    # Initialize with OpenAI embeddings
    db = QdrantVectorDB(collection_name="graphrag_chunks")

    # Create collection
    db.create_collection(recreate=True)

    # Index documents
    chunks_folder = "../data/step3_chunks/chunks"
    if Path(chunks_folder).exists():
        db.index_documents(chunks_folder)

        # Test search
        query = "Was ist die Digitalisierungsstrategie?"
        print(f"\n🔍 Searching for: '{query}'")
        results = db.search(query, limit=3)

        for i, result in enumerate(results, 1):
            print(f"\n{i}. Score: {result['score']:.3f}")
            print(f"   Doc: {result['doc_id']}")
            print(f"   Text: {result['text'][:150]}...")

        # Get RAG context
        print("\n📚 RAG Context:")
        context = db.get_rag_context(query, max_chunks=3)
        print(context[:500] + "..." if len(context) > 500 else context)

        # Example: Direct chunk access
        print("\n🎯 Direct chunk access example:")
        if results:
            first_chunk_id = results[0]["chunk_id"]
            direct_chunk = db.get_chunk_by_id(first_chunk_id)
            if direct_chunk:
                print(f"   Retrieved chunk: {direct_chunk['chunk_id']}")
                print(f"   From document: {direct_chunk['doc_id']}")
                print(f"   Text preview: {direct_chunk['text'][:100]}...")

        # Example: Get all chunks from a document
        print("\n📄 Get all chunks from a document:")
        if results:
            doc_id = results[0]["doc_id"]
            doc_chunks = db.get_document_chunks(doc_id)
            print(f"   Document {doc_id} has {len(doc_chunks)} chunks")
            if doc_chunks:
                print(f"   First chunk: {doc_chunks[0]['chunk_id']}")
                print(f"   Last chunk: {doc_chunks[-1]['chunk_id']}")
    else:
        print(f"❌ Chunks folder not found: {chunks_folder}")
