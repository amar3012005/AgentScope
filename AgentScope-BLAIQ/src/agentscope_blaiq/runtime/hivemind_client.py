"""HiveMind Enterprise API client for memory storage and retrieval."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx

from agentscope_blaiq.runtime.config import settings

logger = logging.getLogger(__name__)

# Module-level credential store (referenced by main.py)
_stored_credentials: dict[str, str] = {}


class HiveMindClient:
    """Client for HiveMind Enterprise API."""

    def __init__(self, credentials: dict[str, str] | None = None):
        # Use provided credentials, then stored, then env
        creds = credentials or _stored_credentials

        self.base_url = creds.get("base_url") or settings.hivemind_enterprise_base_url or "https://core.hivemind.davinciai.eu:8050"
        self.api_key = creds.get("api_key") or settings.hivemind_enterprise_api_key
        self.org_id = creds.get("org_id") or settings.hivemind_enterprise_org_id
        self.user_id = creds.get("user_id") or settings.hivemind_enterprise_user_id
        self.platform = settings.hivemind_enterprise_platform
        self.project = settings.hivemind_enterprise_project

    @property
    def headers(self) -> dict[str, str]:
        """Get auth headers for HiveMind API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-User-ID": self.user_id or "",
            "X-Org-ID": self.org_id or "",
        }

    async def store_memory(
        self,
        query: str,
        findings: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store research findings in HiveMind memory."""
        if not self.api_key:
            logger.warning("HiveMind API key not configured")
            return {"ok": False, "error": "API key not configured"}

        payload = {
            "query": query,
            "findings": findings,
            "timestamp": datetime.utcnow().isoformat(),
            "platform": self.platform,
            "project": self.project,
            "metadata": metadata or {},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                resp = await client.post(
                    f"{self.base_url}/api/memories",
                    headers=self.headers,
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    return {"ok": True, "data": resp.json()}
                else:
                    logger.error(f"HiveMind store_memory failed: {resp.status_code} {resp.text}")
                    return {"ok": False, "error": resp.text}
        except Exception as e:
            logger.error(f"HiveMind store_memory error: {e}")
            return {"ok": False, "error": str(e)}

    async def recall_memories(
        self,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Retrieve relevant memories from HiveMind."""
        if not self.api_key:
            logger.warning("HiveMind API key not configured")
            return {"ok": False, "error": "API key not configured", "memories": []}

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/api/memories",
                    headers=self.headers,
                    params={
                        "query": query,
                        "limit": limit,
                        "platform": self.platform,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {"ok": True, "memories": data.get("memories", [])}
                else:
                    logger.error(f"HiveMind recall_memories failed: {resp.status_code} {resp.text}")
                    return {"ok": False, "error": resp.text, "memories": []}
        except Exception as e:
            logger.error(f"HiveMind recall_memories error: {e}")
            return {"ok": False, "error": str(e), "memories": []}

    async def save_conversation(
        self,
        thread_id: str,
        messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save conversation to HiveMind."""
        if not self.api_key:
            logger.warning("HiveMind API key not configured")
            return {"ok": False, "error": "API key not configured"}

        payload = {
            "thread_id": thread_id,
            "messages": messages,
            "timestamp": datetime.utcnow().isoformat(),
            "platform": self.platform,
            "project": self.project,
            "metadata": metadata or {},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                resp = await client.post(
                    f"{self.base_url}/api/conversations",
                    headers=self.headers,
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    return {"ok": True, "data": resp.json()}
                else:
                    logger.error(f"HiveMind save_conversation failed: {resp.status_code} {resp.text}")
                    return {"ok": False, "error": resp.text}
        except Exception as e:
            logger.error(f"HiveMind save_conversation error: {e}")
            return {"ok": False, "error": str(e)}

    async def retrieve_conversation(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        """Retrieve conversation from HiveMind."""
        if not self.api_key:
            logger.warning("HiveMind API key not configured")
            return {"ok": False, "error": "API key not configured", "messages": []}

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/api/conversations/{thread_id}",
                    headers=self.headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {"ok": True, "messages": data.get("messages", [])}
                else:
                    logger.error(f"HiveMind retrieve_conversation failed: {resp.status_code} {resp.text}")
                    return {"ok": False, "error": resp.text, "messages": []}
        except Exception as e:
            logger.error(f"HiveMind retrieve_conversation error: {e}")
            return {"ok": False, "error": str(e), "messages": []}


# Singleton instance
_hivemind_client: HiveMindClient | None = None


def get_hivemind_client() -> HiveMindClient:
    """Get or create HiveMind client singleton."""
    global _hivemind_client
    if _hivemind_client is None:
        _hivemind_client = HiveMindClient()
    return _hivemind_client
