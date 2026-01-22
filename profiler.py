import time
import asyncio
import json
import os
import sys
from typing import Dict, Any

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from retriever.graphrag_retriever import GraphRAGRetriever

async def profile_retrieval(query: str):
    retriever = GraphRAGRetriever(debug=True)
    
    print(f"\n{'='*50}")
    print(f"PROFILING QUERY: {query}")
    print(f"{'='*50}\n")
    
    start_total = time.time()
    
    # query expansion
    start = time.time()
    expanded = retriever.expand_query_with_cot(query)
    q_expand_time = time.time() - start
    print(f"Query Expansion: {q_expand_time:.4f}s")
    
    # entity extraction
    start = time.time()
    entities = retriever.extract_entities_with_llm(query)
    entity_time = time.time() - start
    print(f"Entity Extraction: {entity_time:.4f}s")
    
    # vector search
    start = time.time()
    vector_results = retriever.vector_search(query, k=200)
    vector_time = time.time() - start
    print(f"Vector Search: {vector_time:.4f}s")
    
    # keyword search
    start = time.time()
    keyword_results = retriever.keyword_search(query, expanded, k=200)
    keyword_time = time.time() - start
    print(f"Keyword Search: {keyword_time:.4f}s")
    
    # graph search
    graph_time = 0
    if entities:
        start = time.time()
        graph_results = retriever.entity_based_retrieval(entities, k=200)
        graph_time = time.time() - start
        print(f"Graph Search: {graph_time:.4f}s")
    
    total_time = time.time() - start_total
    print(f"\nTOTAL TIME: {total_time:.4f}s")
    print(f"{'='*50}\n")
    
    retriever.close()

if __name__ == "__main__":
    test_query = "Who are the key people mentioned in the tourism concept?"
    asyncio.run(profile_retrieval(test_query))
