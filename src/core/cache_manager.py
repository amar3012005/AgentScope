"""
Redis Cache Manager for GraphRAG
Provides exact-match and semantic caching for query results.
"""

import hashlib
import json
import logging
from typing import Optional, Dict, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Redis-based caching for GraphRAG queries.
    
    Features:
    - Exact match caching (MD5 hash)
    - Configurable TTL
    - Async operations
    - Graceful degradation if Redis unavailable
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        ttl: int = 3600,
        prefix: str = "graphrag:",
        enabled: bool = True
    ):
        """
        Initialize cache manager.
        
        Args:
            redis_url: Redis connection URL
            ttl: Time-to-live in seconds (default: 1 hour)
            prefix: Key prefix for namespacing
            enabled: Enable/disable caching
        """
        self.redis_url = redis_url
        self.ttl = ttl
        self.prefix = prefix
        self.enabled = enabled
        self.client: Optional[redis.Redis] = None
        
        # Stats
        self.hits = 0
        self.misses = 0
    
    async def connect(self) -> bool:
        """Connect to Redis. Returns True if successful."""
        if not self.enabled:
            logger.info("Cache disabled")
            return False
            
        try:
            self.client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.client.ping()
            logger.info(f"✅ Redis cache connected: {self.redis_url}")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed: {e} - caching disabled")
            self.client = None
            self.enabled = False
            return False
    
    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            logger.info("Redis cache connection closed")
    
    def _generate_key(self, query: str, collection_name: Optional[str] = None) -> str:
        """Generate cache key from query and collection."""
        # Include collection name for multi-tenant isolation
        cache_input = f"{collection_name or 'default'}:{query}"
        hash_key = hashlib.md5(cache_input.encode()).hexdigest()
        return f"{self.prefix}{hash_key}"
    
    async def get(
        self,
        query: str,
        collection_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached result for query.
        
        Args:
            query: User query
            collection_name: Collection/tenant name
            
        Returns:
            Cached result dict or None if not found
        """
        if not self.enabled or not self.client:
            return None
        
        try:
            key = self._generate_key(query, collection_name)
            cached = await self.client.get(key)
            
            if cached:
                self.hits += 1
                logger.info(f"✅ CACHE HIT: {query[:50]}...")
                return json.loads(cached)
            else:
                self.misses += 1
                return None
                
        except Exception as e:
            logger.warning(f"Cache read error: {e}")
            return None
    
    async def set(
        self,
        query: str,
        result: Dict[str, Any],
        collection_name: Optional[str] = None,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache query result.
        
        Args:
            query: User query
            result: Result to cache
            collection_name: Collection/tenant name
            ttl: Override default TTL
            
        Returns:
            True if cached successfully
        """
        if not self.enabled or not self.client:
            return False
        
        try:
            key = self._generate_key(query, collection_name)
            ttl_seconds = ttl or self.ttl
            
            await self.client.setex(
                key,
                ttl_seconds,
                json.dumps(result)
            )
            logger.debug(f"Cached result for: {query[:50]}... (TTL: {ttl_seconds}s)")
            return True
            
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
            return False
    
    async def clear(self, pattern: Optional[str] = None) -> int:
        """
        Clear cache entries.
        
        Args:
            pattern: Key pattern to match (default: all graphrag keys)
            
        Returns:
            Number of keys deleted
        """
        if not self.enabled or not self.client:
            return 0
        
        try:
            search_pattern = pattern or f"{self.prefix}*"
            keys = await self.client.keys(search_pattern)
            
            if keys:
                deleted = await self.client.delete(*keys)
                logger.info(f"Cleared {deleted} cache entries")
                return deleted
            return 0
            
        except Exception as e:
            logger.warning(f"Cache clear error: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0
        
        return {
            "enabled": self.enabled,
            "connected": self.client is not None,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(hit_rate, 3),
            "ttl": self.ttl
        }
