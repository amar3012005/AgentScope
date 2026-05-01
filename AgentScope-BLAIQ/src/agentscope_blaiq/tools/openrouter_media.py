from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
from pathlib import Path
from uuid import uuid4

import httpx
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from agentscope_blaiq.runtime.config import settings


class OpenRouterMediaService:
    def __init__(self) -> None:
        self.api_key = settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.artifact_dir = settings.artifact_dir / "openrouter_media"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _save_data_url(self, data_url: str, stem: str) -> str:
        header, encoded = data_url.split(",", 1)
        mime = header.split(";", 1)[0].split(":", 1)[1] if ":" in header else "image/png"
        extension = mimetypes.guess_extension(mime) or ".bin"
        file_path = self.artifact_dir / f"{stem}{extension}"
        file_path.write_bytes(base64.b64decode(encoded))
        return str(file_path)

    async def generate_image(
        self,
        *,
        prompt: str,
        reference_image: str | None = None,
        model: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": model or settings.openrouter_image_model,
            "modalities": ["image", "text"],
        }
        if reference_image:
            payload["messages"] = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": reference_image}},
                    ],
                }
            ]
        else:
            payload["messages"] = [{"role": "user", "content": prompt}]

        async with httpx.AsyncClient(timeout=settings.openrouter_request_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        message = ((data.get("choices") or [{}])[0]).get("message") or {}
        images = message.get("images") or []
        outputs: list[dict[str, str]] = []
        for index, image in enumerate(images, start=1):
            image_url = (((image or {}).get("image_url") or {}).get("url"))
            if not image_url:
                continue
            record = {"image_url": image_url}
            if image_url.startswith("data:"):
                record["saved_path"] = self._save_data_url(image_url, f"image_{uuid4().hex}_{index}")
            outputs.append(record)

        return {
            "model": payload["model"],
            "prompt": prompt,
            "images": outputs,
            "text": message.get("content", ""),
        }

    async def generate_video(
        self,
        *,
        prompt: str,
        model: str | None = None,
    ) -> dict[str, object]:
        payload = {
            "model": model or settings.openrouter_video_model,
            "prompt": prompt,
        }
        async with httpx.AsyncClient(timeout=settings.openrouter_request_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/videos",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            job = response.json()
            polling_url = job["polling_url"]

            for _ in range(settings.openrouter_video_poll_attempts):
                poll_response = await client.get(polling_url, headers=self._headers())
                poll_response.raise_for_status()
                status_data = poll_response.json()
                status = status_data.get("status")
                if status == "completed":
                    return {
                        "model": payload["model"],
                        "prompt": prompt,
                        "job_id": job.get("id"),
                        "status": status,
                        "unsigned_urls": status_data.get("unsigned_urls", []),
                    }
                if status == "failed":
                    return {
                        "model": payload["model"],
                        "prompt": prompt,
                        "job_id": job.get("id"),
                        "status": status,
                        "error": status_data.get("error", "Unknown error"),
                    }
                await asyncio.sleep(settings.openrouter_video_poll_interval_seconds)

        return {
            "model": payload["model"],
            "prompt": prompt,
            "job_id": job.get("id"),
            "status": "timeout",
            "error": "Video generation polling timed out",
        }


def image_tool_response(result: dict[str, object]) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=json.dumps(result, indent=2))])


def video_tool_response(result: dict[str, object]) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=json.dumps(result, indent=2))])