import json
import logging
from typing import List, Dict, Optional
from core.cache_manager import CacheManager

logger = logging.getLogger("graphrag_api")

class SessionManager:
    """
    Manages chat history persistence in Redis for multi-tenant sessions.
    """
    def __init__(self, cache_manager: CacheManager, history_ttl: int = 86400 * 7): # Default 7 days
        self.cache = cache_manager
        self.ttl = history_ttl

    def _get_key(self, tenant: str, session_id: str) -> str:
        return f"history:{tenant}:{session_id}"

    async def get_history(self, tenant: str, session_id: str, limit: int = 10) -> List[Dict]:
        """Fetch chat history for a session."""
        if not self.cache.enabled or not session_id:
            return []
            
        key = self._get_key(tenant, session_id)
        try:
            data = await self.cache.client.get(key)
            if data:
                history = json.loads(data)
                return history[-limit:]
            return []
        except Exception as e:
            logger.error(f"❌ Failed to fetch history for {session_id}: {e}")
            return []

    async def add_message(self, tenant: str, session_id: str, role: str, content: str):
        """Append a message to the session history."""
        if not self.cache.enabled or not session_id:
            return
            
        key = self._get_key(tenant, session_id)
        try:
            # 1. Get existing history
            data = await self.cache.client.get(key)
            history = json.loads(data) if data else []
            
            # 2. Append new message
            history.append({"role": role, "content": content})
            
            # 3. Trim to last 20 messages for performance
            history = history[-20:]
            
            # 4. Save back to Redis
            await self.cache.client.set(key, json.dumps(history), ex=self.ttl)
        except Exception as e:
            logger.error(f"❌ Failed to save history for {session_id}: {e}")

    async def clear_session(self, tenant: str, session_id: str):
        """Delete a session's history."""
        if not self.cache.enabled:
            return
        key = self._get_key(tenant, session_id)
        await self.cache.client.delete(key)
