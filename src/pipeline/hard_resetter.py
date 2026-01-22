# src/pipeline/hard_resetter.py

#!/usr/bin/env python3
"""
Pipeline Cleanup Script - Cleans processing data while protecting source documents.
"""

import os
import shutil
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Get project root (2 levels up from this file: src/pipeline/hard_resetter.py)
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Load pipeline configuration from YAML file"""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        return yaml.safe_load(f)


def cleanup_all_data(config: dict) -> bool:
    """Clean all pipeline data: _pipeline folder, Qdrant collection, Neo4j database"""
    print("PIPELINE CLEANUP - Deleting processing data...\n")
    errors = []

    # 1. Delete _pipeline folder
    raw_docs = config.get("folders", {}).get("raw_docs", "data")

    # Resolve path relative to project root
    if not Path(raw_docs).is_absolute():
        raw_docs = PROJECT_ROOT / raw_docs

    pipeline_folder = Path(raw_docs) / "_pipeline"

    if pipeline_folder.exists():
        try:
            shutil.rmtree(pipeline_folder)
            print("  ✓ Deleted: _pipeline/ folder")
        except Exception as e:
            errors.append(f"_pipeline folder: {str(e)}")
    else:
        print("  ✓ _pipeline/ folder does not exist, skipping.")

    # 2. Clear Qdrant (from .env)
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
    collection_name = config.get("vector_db", {}).get("collection_name", "graphrag_chunks")

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=qdrant_host, port=qdrant_port)

        if collection_name in [c.name for c in client.get_collections().collections]:
            client.delete_collection(collection_name)
            print(f"  ✓ Deleted Qdrant collection: {collection_name}")
        else:
            print(f"  ✓ Qdrant collection '{collection_name}' does not exist, skipping.")
    except Exception as e:
        errors.append(f"Qdrant: {str(e)}")

    # 3. Clear Neo4j (from .env)
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD")

    if neo4j_uri and neo4j_password:
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
                print("  ✓ Cleared Neo4j database")
            driver.close()
        except Exception as e:
            errors.append(f"Neo4j: {str(e)}")
    else:
        if neo4j_uri and not neo4j_password:
            print("  ⚠ Neo4j: NEO4J_PASSWORD not set in .env, skipping.")
        else:
            print("  ⚠ Neo4j: NEO4J_URI not set in .env, skipping.")

    # Summary
    status = "SUCCESS" if not errors else f"COMPLETED with {len(errors)} error(s)"
    print(f"\n{status}")

    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  • {error}")

    return len(errors) == 0


def main():
    """Main function for terminal execution"""
    # Allow custom config path, but default to project root
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
    else:
        config_path = CONFIG_PATH

    try:
        config = load_config(config_path)

        print("WARNING: Delete ALL pipeline processing data?")
        print("Source documents in raw_docs will be preserved. Type 'DELETE' to confirm:")

        if input().strip() != "DELETE":
            print("Cancelled.")
            return

        success = cleanup_all_data(config)
        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
