"""
Performance Comparison: Original vs Optimized GraphRAG

This script benchmarks the original sequential retrieval against
the optimized parallel + cached version.
"""

import time
import asyncio
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from retriever.graphrag_retriever import GraphRAGRetriever
from core.async_retriever import AsyncRetriever


def benchmark_original(retriever, query: str, k: int = 200):
    """Benchmark original sequential retrieval."""
    print("\n" + "="*60)
    print("ORIGINAL (Sequential) Retrieval")
    print("="*60)
    
    start_total = time.time()
    
    # Query expansion
    start = time.time()
    expanded = retriever.expand_query_with_cot(query)
    t_expand = time.time() - start
    print(f"Query Expansion:    {t_expand:.3f}s")
    
    # Entity extraction
    start = time.time()
    entities = retriever.extract_entities_with_llm(query)
    t_entity = time.time() - start
    print(f"Entity Extraction:  {t_entity:.3f}s")
    
    # Sequential searches
    start = time.time()
    vector_results = retriever.vector_search(query, k=k)
    t_vector = time.time() - start
    print(f"Vector Search:      {t_vector:.3f}s")
    
    start = time.time()
    keyword_results = retriever.keyword_search(query, expanded, k=k)
    t_keyword = time.time() - start
    print(f"Keyword Search:     {t_keyword:.3f}s")
    
    start = time.time()
    graph_results = retriever.entity_based_retrieval(entities, k=k) if entities else {}
    t_graph = time.time() - start
    print(f"Graph Search:       {t_graph:.3f}s")
    
    total_time = time.time() - start_total
    retrieval_time = t_vector + t_keyword + t_graph
    
    print(f"\nRetrieval Time:     {retrieval_time:.3f}s (sum of searches)")
    print(f"Total Time:         {total_time:.3f}s")
    
    return {
        "expand": t_expand,
        "entity": t_entity,
        "vector": t_vector,
        "keyword": t_keyword,
        "graph": t_graph,
        "retrieval": retrieval_time,
        "total": total_time
    }


async def benchmark_optimized(retriever, query: str, k: int = 200):
    """Benchmark optimized parallel retrieval."""
    print("\n" + "="*60)
    print("OPTIMIZED (Parallel) Retrieval")
    print("="*60)
    
    start_total = time.time()
    
    # Query expansion
    start = time.time()
    expanded = retriever.expand_query_with_cot(query)
    t_expand = time.time() - start
    print(f"Query Expansion:    {t_expand:.3f}s")
    
    # Entity extraction
    start = time.time()
    entities = retriever.extract_entities_with_llm(query)
    t_entity = time.time() - start
    print(f"Entity Extraction:  {t_entity:.3f}s")
    
    # Parallel searches
    async_wrapper = AsyncRetriever(retriever)
    rankings, timings = await async_wrapper.parallel_retrieval(
        query, entities, expanded, k
    )
    async_wrapper.shutdown()
    
    print(f"Vector Search:      {timings['vector_search']:.3f}s  ┐")
    print(f"Keyword Search:     {timings['keyword_search']:.3f}s  ├─ Parallel")
    print(f"Graph Search:       {timings['graph_search']:.3f}s  ┘")
    
    total_time = time.time() - start_total
    retrieval_time = timings['total_parallel']
    
    print(f"\nRetrieval Time:     {retrieval_time:.3f}s (max of searches)")
    print(f"Total Time:         {total_time:.3f}s")
    
    return {
        "expand": t_expand,
        "entity": t_entity,
        "vector": timings['vector_search'],
        "keyword": timings['keyword_search'],
        "graph": timings['graph_search'],
        "retrieval": retrieval_time,
        "total": total_time
    }


async def main():
    """Run comparison benchmark."""
    
    # Test query
    query = "What are the main tourism development strategies mentioned in the documents?"
    
    print("\n" + "🚀 GraphRAG Performance Benchmark ".center(60, "="))
    print(f"\nQuery: {query}")
    print(f"Top-K: 200 (broad retrieval)")
    
    # Initialize retriever
    print("\nInitializing retriever...")
    retriever = GraphRAGRetriever(debug=False)
    
    # Benchmark original
    original_times = benchmark_original(retriever, query)
    
    # Benchmark optimized
    optimized_times = await benchmark_optimized(retriever, query)
    
    # Calculate improvements
    print("\n" + "="*60)
    print("PERFORMANCE COMPARISON")
    print("="*60)
    
    print(f"\n{'Component':<20} {'Original':<12} {'Optimized':<12} {'Speedup':<10}")
    print("-" * 60)
    
    for key in ["expand", "entity", "retrieval", "total"]:
        orig = original_times[key]
        opt = optimized_times[key]
        speedup = orig / opt if opt > 0 else 0
        
        label = {
            "expand": "Query Expansion",
            "entity": "Entity Extraction",
            "retrieval": "Retrieval Phase",
            "total": "Total Time"
        }[key]
        
        print(f"{label:<20} {orig:>8.3f}s    {opt:>8.3f}s    {speedup:>6.2f}x")
    
    # Highlight key wins
    retrieval_speedup = original_times["retrieval"] / optimized_times["retrieval"]
    total_speedup = original_times["total"] / optimized_times["total"]
    
    print("\n" + "="*60)
    print("KEY IMPROVEMENTS")
    print("="*60)
    print(f"✅ Retrieval Phase: {retrieval_speedup:.1f}x faster (parallel execution)")
    print(f"✅ Overall:         {total_speedup:.1f}x faster")
    print(f"✅ Keyword Search:  {original_times['keyword']:.3f}s → {optimized_times['keyword']:.3f}s")
    print(f"   (Optimized Qdrant MatchText filters)")
    
    # Cleanup
    retriever.close()
    
    print("\n" + "="*60)
    print("Benchmark complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
