# src/utils/qdrant_helpers.py

import hashlib


def compute_point_id(chunk_id: str) -> int:
    """
    Canonical Qdrant point ID computation.
    Used across the entire system for consistency.

    Args:
        chunk_id: Chunk identifier (e.g., "doc_123_chunk_001")

    Returns:
        Integer point ID for Qdrant
    """
    return int(hashlib.md5(chunk_id.encode()).hexdigest()[:16], 16)
