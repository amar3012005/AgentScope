from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from agentscope_blaiq.runtime.agent_base import BaseAgent

logger = logging.getLogger("agentscope_blaiq.agents.remote_proxy")


class RemoteA2AProxy(BaseAgent):
    """Concrete remote proxy for agents that follow the A2A protocol.

    Dispatches calls to a remote endpoint instead of running logic locally.
    """

    def __init__(
        self,
        endpoint_url: str,
        name: str,
        role: str,
        **kwargs,
    ) -> None:
        super().__init__(name=name, role=role, sys_prompt="", **kwargs)
        self.endpoint_url = endpoint_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=60.0)

    async def _post_remote(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send a POST request to the remote agent endpoint."""
        target_url = f"{self.endpoint_url}/{method}"
        try:
            response = await self.client.post(target_url, json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("Remote A2A call to %s failed: %s", target_url, e)
            raise RuntimeError(f"Remote agent {self.name} failed at {method}: {e}") from e

    async def build_plan(self, request: Any, **kwargs: Any) -> Any:
        """Strategist/Resolver: build a workflow plan."""
        payload = {"request": request.model_dump() if hasattr(request, "model_dump") else request}
        if "agent_catalog" in kwargs:
            payload["agent_catalog"] = [
                a.model_dump() if hasattr(a, "model_dump") else a
                for a in kwargs["agent_catalog"]
            ]
        return await self._post_remote("build_plan", payload)

    async def gather(self, **kwargs: Any) -> Any:
        """Research: gather evidence."""
        serializable = {k: v for k, v in kwargs.items() if k != "session"}
        result = await self._post_remote("gather", serializable)
        from agentscope_blaiq.contracts.evidence import EvidencePack
        return EvidencePack.model_validate(result)

    async def generate_artifact(self, **kwargs: Any) -> Any:
        """Content/Render: generate the final artifact."""
        return await self._post_remote("generate_artifact", kwargs)

    async def certify(self, **kwargs: Any) -> Any:
        """Governance: certify an artifact."""
        return await self._post_remote("certify", kwargs)

    async def clarify(self, **kwargs: Any) -> Any:
        """HITL: clarify user intent."""
        return await self._post_remote("clarify", kwargs)

    async def reply(self, x: Any = None, **kwargs: Any) -> Any:
        """Generic AgentScope reply."""
        payload = {"message": x.model_dump() if hasattr(x, "model_dump") else x}
        payload.update(kwargs)
        return await self._post_remote("reply", payload)
