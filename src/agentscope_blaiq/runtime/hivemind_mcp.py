from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx


class HivemindMCPError(RuntimeError):
    pass


@dataclass
class HivemindWebJobResult:
    job_id: str
    status: str
    payload: dict[str, Any]


@dataclass
class EnterpriseChatWriteResult:
    sid: str
    turn_number: int | None
    turn_memory_id: str | None
    status: str | None
    raw: dict[str, Any]


class HivemindMCPClient:
    def __init__(
        self,
        *,
        rpc_url: str | None,
        api_key: str | None,
        enterprise_base_url: str | None = None,
        enterprise_api_key: str | None = None,
        enterprise_org_id: str | None = None,
        enterprise_user_id: str | None = None,
        enterprise_platform: str = "chatbot",
        enterprise_project: str = "enterprise/chat",
        enterprise_agent_name: str = "blaiq-agent",
        timeout_seconds: int = 20,
        poll_interval_seconds: float = 1.0,
        poll_attempts: int = 10,
    ) -> None:
        self.rpc_url = rpc_url
        self.api_key = api_key
        self.enterprise_base_url = (enterprise_base_url or "").rstrip("/") or None
        self.enterprise_api_key = enterprise_api_key or api_key
        self.enterprise_org_id = enterprise_org_id
        self.enterprise_user_id = enterprise_user_id
        self.enterprise_platform = enterprise_platform
        self.enterprise_project = enterprise_project
        self.enterprise_agent_name = enterprise_agent_name
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_attempts = poll_attempts

    @property
    def enabled(self) -> bool:
        return bool(self.rpc_url and self.api_key)

    @property
    def enterprise_chat_enabled(self) -> bool:
        return bool(self.enterprise_base_url and self.enterprise_api_key and self.enterprise_org_id)

    async def tools_list(self) -> dict[str, Any]:
        return await self._rpc("tools/list", {})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        return response

    async def recall(self, *, query: str, limit: int = 20, mode: str = "insight") -> dict[str, Any]:
        return await self.call_tool("hivemind_recall", {"query": query, "limit": limit, "mode": mode})

    async def query_with_ai(self, *, question: str, context_limit: int = 8) -> dict[str, Any]:
        return await self.call_tool("hivemind_query_with_ai", {"question": question, "context_limit": context_limit})

    async def get_memory(self, *, memory_id: str) -> dict[str, Any]:
        return await self.call_tool("hivemind_get_memory", {"memory_id": memory_id})

    async def traverse_graph(self, *, memory_id: str, depth: int = 2) -> dict[str, Any]:
        return await self.call_tool("hivemind_traverse_graph", {"memory_id": memory_id, "depth": depth})

    async def web_search(self, *, query: str, domains: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if domains:
            payload["domains"] = domains
        return await self.call_tool("hivemind_web_search", payload)

    async def web_crawl(self, *, urls: list[str], depth: int = 1, page_limit: int = 5) -> dict[str, Any]:
        return await self.call_tool("hivemind_web_crawl", {"urls": urls, "depth": depth, "page_limit": page_limit})

    async def web_job_status(self, *, job_id: str) -> dict[str, Any]:
        return await self.call_tool("hivemind_web_job_status", {"job_id": job_id})

    async def web_usage(self) -> dict[str, Any]:
        return await self.call_tool("hivemind_web_usage", {})

    async def save_memory(self, *, title: str, content: str, tags: list[str] | None = None, project: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "content": content, "source_type": "research_summary"}
        if tags:
            payload["tags"] = tags
        if project:
            payload["project"] = project
        return await self.call_tool("hivemind_save_memory", payload)

    async def save_conversation(self, *, title: str, messages: list[dict[str, str]], tags: list[str] | None = None, project: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "messages": messages, "platform": "blaiq"}
        if tags:
            payload["tags"] = tags
        if project:
            payload["project"] = project
        return await self.call_tool("hivemind_save_conversation", payload)

    async def save_enterprise_chat_turn(
        self,
        *,
        sid: str,
        turn: str,
        content: str,
        is_new_chat: bool,
        turn_number: int | None = None,
        idempotency_key: str | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
        platform: str | None = None,
        agent_name: str | None = None,
        project: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EnterpriseChatWriteResult:
        if not self.enterprise_chat_enabled:
            raise HivemindMCPError("Enterprise chat writer is not configured")

        payload: dict[str, Any] = {
            "org_id": org_id or self.enterprise_org_id,
            "user_id": user_id or self.enterprise_user_id,
            "sid": sid,
            "turn": turn,
            "content": content,
            "platform": platform or self.enterprise_platform,
            "agent_name": agent_name or self.enterprise_agent_name,
            "project": project or self.enterprise_project,
        }
        if turn_number is not None:
            payload["turn_number"] = turn_number
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        if metadata:
            payload["metadata"] = metadata
        if not payload.get("org_id") or not payload.get("user_id"):
            raise HivemindMCPError("Enterprise chat writer requires org_id and user_id")

        endpoint = "/api/enterprise/chat/save_chat_new" if is_new_chat else "/api/enterprise/chat/save_chat_old"
        response = await self._post_json(
            endpoint,
            payload,
            auth_key=self.enterprise_api_key,
            error_context=f"Enterprise chat write {turn} for sid={sid}",
        )
        return EnterpriseChatWriteResult(
            sid=sid,
            turn_number=response.get("turn_number"),
            turn_memory_id=response.get("turn_memory_id"),
            status=response.get("status"),
            raw=response,
        )

    async def poll_web_job(self, *, job_id: str) -> HivemindWebJobResult:
        last_payload: dict[str, Any] | None = None
        for _ in range(self.poll_attempts):
            payload = await self.web_job_status(job_id=job_id)
            last_payload = payload
            normalized = self._extract_tool_payload(payload)
            status = str(normalized.get("status") or normalized.get("state") or "").lower()
            if status in {"succeeded", "success", "completed", "complete"}:
                return HivemindWebJobResult(job_id=job_id, status=status, payload=normalized)
            if status in {"failed", "error"}:
                raise HivemindMCPError(f"HIVE-MIND web job failed: {normalized}")
            await asyncio.sleep(self.poll_interval_seconds)
        raise HivemindMCPError(f"HIVE-MIND web job did not finish in time: {last_payload}")

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise HivemindMCPError("HIVE-MIND MCP is not configured")
        payload = await self._post_json(
            self.rpc_url,
            {"method": method, "params": params, "id": 1},
            auth_key=self.api_key,
            error_context=f"HIVE-MIND RPC calling {method} at {self.rpc_url}",
        )
        if "error" in payload and payload["error"]:
            raise HivemindMCPError(str(payload["error"]))
        return payload.get("result") or payload

    async def _post_json(
        self,
        url_or_path: str,
        payload: dict[str, Any],
        *,
        auth_key: str | None,
        error_context: str,
    ) -> dict[str, Any]:
        target_url = url_or_path
        if target_url.startswith("/"):
            if not self.enterprise_base_url:
                raise HivemindMCPError("Enterprise base URL is not configured")
            target_url = f"{self.enterprise_base_url}{target_url}"

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            try:
                response = await client.post(
                    target_url,
                    headers={
                        "Authorization": f"Bearer {auth_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as exc:
                raise HivemindMCPError(f"{error_context} timed out after {self.timeout_seconds}s") from exc
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else "unknown"
                detail = ""
                try:
                    body = exc.response.json() if exc.response is not None else None
                    if isinstance(body, dict):
                        detail = body.get("error") or body.get("detail") or ""
                except Exception:
                    detail = ""
                suffix = f": {detail}" if detail else ""
                raise HivemindMCPError(f"{error_context} failed with HTTP {status_code}{suffix}") from exc
            except httpx.HTTPError as exc:
                raise HivemindMCPError(f"{error_context} transport error: {exc.__class__.__name__}") from exc

    @staticmethod
    def _extract_tool_payload(result: dict[str, Any]) -> dict[str, Any]:
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, dict):
                        return text
                    if isinstance(text, str):
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict):
                            return parsed
            return {"content": content}
        if isinstance(result.get("metadata"), dict):
            return result["metadata"]
        return result
