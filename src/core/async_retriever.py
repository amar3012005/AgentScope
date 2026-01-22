"""
Async Parallel Retrieval for GraphRAG
Runs Vector, Graph, and Keyword searches concurrently.
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor


class AsyncRetriever:
    """
    Wrapper to run synchronous retrieval methods in parallel using asyncio.
    
    This converts the sequential GraphRAG pipeline into concurrent execution:
    - Vector search (Qdrant)
    - Graph search (Neo4j)
    - Keyword search (Qdrant)
    
    Expected speedup: 2-3x for retrieval phase
    """
    
    def __init__(self, retriever, max_workers: int = 3):
        """
        Initialize async wrapper.
        
        Args:
            retriever: GraphRAGRetriever instance
            max_workers: Max concurrent threads
        """
        self.retriever = retriever
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
    async def run_vector_search(self, query: str, k: int) -> Tuple[Dict[int, float], float]:
        """Run vector search in thread pool."""
        start = time.time()
        loop = asyncio.get_event_loop()
        
        results = await loop.run_in_executor(
            self.executor,
            self.retriever.vector_search,
            query,
            k
        )
        
        elapsed = time.time() - start
        return results, elapsed
    
    async def run_graph_search(
        self,
        entities: List[str],
        k: int
    ) -> Tuple[Dict[int, float], float]:
        """Run graph search in thread pool."""
        if not entities or not self.retriever.neo4j_driver:
            return {}, 0.0
        
        start = time.time()
        loop = asyncio.get_event_loop()
        
        results = await loop.run_in_executor(
            self.executor,
            self.retriever.entity_based_retrieval,
            entities,
            k
        )
        
        elapsed = time.time() - start
        return results, elapsed
    
    async def run_keyword_search(
        self,
        query: str,
        expanded_query: Dict,
        k: int
    ) -> Tuple[Dict[int, float], float]:
        """Run keyword search in thread pool."""
        start = time.time()
        loop = asyncio.get_event_loop()
        
        results = await loop.run_in_executor(
            self.executor,
            self.retriever.keyword_search,
            query,
            expanded_query,
            k
        )
        
        elapsed = time.time() - start
        return results, elapsed
    
    async def parallel_retrieval(
        self,
        query: str,
        entities: List[str],
        expanded_query: Dict,
        k: int
    ) -> Tuple[Dict[str, Dict[int, float]], Dict[str, float]]:
        """
        Run all retrieval methods in parallel.
        
        Args:
            query: User query
            entities: Extracted entities
            expanded_query: Query expansion results
            k: Number of results per method
            
        Returns:
            (rankings dict, timing dict)
        """
        # Launch all searches concurrently
        tasks = [
            self.run_vector_search(query, k),
            self.run_graph_search(entities, k),
            self.run_keyword_search(query, expanded_query, k)
        ]
        
        # Wait for all to complete
        results = await asyncio.gather(*tasks)
        
        # Unpack results
        vector_results, vector_time = results[0]
        graph_results, graph_time = results[1]
        keyword_results, keyword_time = results[2]
        
        # Build rankings dict
        rankings = {
            "vector": vector_results,
            "keyword": keyword_results
        }
        
        if graph_results:
            rankings["graph"] = graph_results
        
        # Build timing dict
        timings = {
            "vector_search": vector_time,
            "graph_search": graph_time,
            "keyword_search": keyword_time,
            "total_parallel": max(vector_time, graph_time, keyword_time)
        }
        
        return rankings, timings
    
    def shutdown(self):
        """Shutdown thread pool."""
        self.executor.shutdown(wait=True)
