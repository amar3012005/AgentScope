# src/utils/delete_document_from_db.py

"""
Utility functions to delete a document from Qdrant and Neo4j databases.
Uses environment variables for connection details.
"""

import os
from typing import Dict, Optional # 251215–BundB Jun: Added Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

load_dotenv()


def delete_document_from_qdrant(
    doc_id: str,
    collection_name: str,
    filter_label: Optional[str] = None,  # 251216-BundB Jun: optional (kept for backward compatibility; not used for Qdrant delete)

) -> Dict:
    """
    Delete all vectors for a document from Qdrant.

    Connection via environment variables:
    - QDRANT_URL
    - QDRANT_API_KEY (optional)

    Args:
        doc_id: Document ID to delete
        collection_name: Qdrant collection name
        filter_label: Tenant filter label

    Returns:
        Dict with deletion stats
    """
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")

    if not qdrant_url:
        raise ValueError("QDRANT_URL environment variable required")

    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)

    # Count points before deletion
    count_before = 0
    try:
        count_result = client.count(
            collection_name=collection_name,
            count_filter=Filter(
                must=[
                    FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
                    # 251215–BundB Jun: Added filter_label optional
                    # FieldCondition(key="filter_label", match=MatchValue(value=filter_label)),
                ]
            ),
        )
        count_before = count_result.count
    except Exception as e:
        print(f"⚠️ Could not count points: {e}")

    if count_before == 0:
        print(f"ℹ️ No vectors found for doc_id='{doc_id}' in collection '{collection_name}'")
        return {
            "deleted": 0,
            "collection_name": collection_name,
            "doc_id": doc_id,
            "filter_label": filter_label,
        }

    # Delete by filter
    client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
                # 251215–BundB Jun: Added filter_label optional
                # FieldCondition(key="filter_label", match=MatchValue(value=filter_label)),
            ]
        ),
    )

    print(f"🗑️ Qdrant: Deleted {count_before} vectors for '{doc_id}' from '{collection_name}'")

    return {
        "deleted": count_before,
        "collection_name": collection_name,
        "doc_id": doc_id,
        "filter_label": filter_label,
    }


def delete_document_from_neo4j(
    doc_id: str,
    filter_label: str,
) -> Dict:
    """
    Delete a document and all related data from Neo4j.

    Connection via environment variables:
    - NEO4J_URI
    - NEO4J_USER
    - NEO4J_PASSWORD

    Logic:
    1. Identify Document node and all its Chunk nodes
    2. Identify Entities EXCLUSIVELY connected to these Document/Chunks
    3. Delete ALL relationships from these nodes
    4. Delete these Document, Chunk, and Entity nodes

    Args:
        doc_id: Document ID to delete
        filter_label: Tenant filter label

    Returns:
        Dict with counts of deleted items
    """
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not password:
        raise ValueError("NEO4J_URI and NEO4J_PASSWORD environment variables required")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    deleted = {
        "documents": 0,
        "chunks": 0,
        "entities": 0,
        "relationships": 0,
        "doc_id": doc_id,
        "filter_label": filter_label,
    }

    try:
        with driver.session() as session:
            # Step 1: Check if document exists
            result = session.run(
                """
                MATCH (d:Document {doc_id: $doc_id, filter_label: $fl})
                RETURN count(d) as count
                """,
                {"doc_id": doc_id, "fl": filter_label},
            )
            if result.single()["count"] == 0:
                print(
                    f"ℹ️ No document found with doc_id='{doc_id}' and filter_label='{filter_label}'"
                )
                return deleted

            # Step 2: Identify orphaned entities
            result = session.run(
                """
                MATCH (e:Entity {filter_label: $fl})-[:APPEARS_IN]->(c:Chunk {document_id: $doc_id, filter_label: $fl})
                WHERE NOT EXISTS {
                    MATCH (e)-[:APPEARS_IN]->(other_chunk:Chunk {filter_label: $fl})
                    WHERE other_chunk.document_id <> $doc_id
                }
                RETURN collect(DISTINCT id(e)) as orphaned_entity_ids
                """,
                {"doc_id": doc_id, "fl": filter_label},
            )
            orphaned_entity_ids = result.single()["orphaned_entity_ids"] or []

            print(f"  📋 Found {len(orphaned_entity_ids)} orphaned entities to delete")

            # Step 3a: Delete ALL relationships FROM/TO orphaned entities
            if orphaned_entity_ids:
                result = session.run(
                    """
                    MATCH (e:Entity)
                    WHERE id(e) IN $entity_ids
                    MATCH (e)-[r]-()
                    DELETE r
                    RETURN count(r) as deleted
                    """,
                    {"entity_ids": orphaned_entity_ids},
                )
                deleted["relationships"] += result.single()["deleted"]

            # Step 3b: Delete relationships FROM/TO chunks of this document
            result = session.run(
                """
                MATCH (c:Chunk {document_id: $doc_id, filter_label: $fl})
                MATCH (c)-[r]-()
                DELETE r
                RETURN count(r) as deleted
                """,
                {"doc_id": doc_id, "fl": filter_label},
            )
            deleted["relationships"] += result.single()["deleted"]

            # Step 3c: Delete relationships FROM/TO the document
            result = session.run(
                """
                MATCH (d:Document {doc_id: $doc_id, filter_label: $fl})
                MATCH (d)-[r]-()
                DELETE r
                RETURN count(r) as deleted
                """,
                {"doc_id": doc_id, "fl": filter_label},
            )
            deleted["relationships"] += result.single()["deleted"]

            # Step 4a: Delete orphaned entity nodes
            if orphaned_entity_ids:
                result = session.run(
                    """
                    MATCH (e:Entity)
                    WHERE id(e) IN $entity_ids
                    DELETE e
                    RETURN count(e) as deleted
                    """,
                    {"entity_ids": orphaned_entity_ids},
                )
                deleted["entities"] = result.single()["deleted"]

            # Step 4b: Delete chunk nodes
            result = session.run(
                """
                MATCH (c:Chunk {document_id: $doc_id, filter_label: $fl})
                DELETE c
                RETURN count(c) as deleted
                """,
                {"doc_id": doc_id, "fl": filter_label},
            )
            deleted["chunks"] = result.single()["deleted"]

            # Step 4c: Delete document node
            result = session.run(
                """
                MATCH (d:Document {doc_id: $doc_id, filter_label: $fl})
                DELETE d
                RETURN count(d) as deleted
                """,
                {"doc_id": doc_id, "fl": filter_label},
            )
            deleted["documents"] = result.single()["deleted"]

    finally:
        driver.close()

    print(
        f"🗑️ Neo4j: Deleted doc '{doc_id}' → "
        f"{deleted['documents']} doc, {deleted['chunks']} chunks, "
        f"{deleted['entities']} entities, {deleted['relationships']} relationships"
    )

    return deleted
