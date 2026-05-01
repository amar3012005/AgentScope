from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from openai import AuthenticationError

try:
    from agentscope.model import OpenAIChatModel
except ImportError:  # pragma: no cover
    OpenAIChatModel = None  # type: ignore[assignment]

try:
    from groq import AsyncGroq
except ImportError:  # pragma: no cover
    AsyncGroq = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    messages: list[dict[str, str]]
    api_key: str | None
    api_base: str | None
    timeout_seconds: int
    max_tokens: int
    temperature: float
    reasoning_effort: str | None = None
    stream: bool = False
    extra: dict[str, Any] | None = None


class ProviderClient(Protocol):
    async def __call__(self, messages: list[dict[str, str]], **kwargs: Any) -> Any: ...


class OpenAICompatibleProviderClient:
    def __init__(self, *, model_name: str, api_key: str | None, api_base: str | None, stream: bool, temperature: float, timeout_seconds: int, max_tokens: int, reasoning_effort: str | None = None) -> None:
        if OpenAIChatModel is None:  # pragma: no cover
            raise RuntimeError("agentscope is required to construct runtime models")
        client_kwargs: dict[str, Any] = {}
        if api_base:
            client_kwargs["base_url"] = api_base
        self._client = OpenAIChatModel(
            model_name=model_name,
            api_key=api_key,
            stream=stream,
            reasoning_effort=reasoning_effort,
            client_kwargs=client_kwargs or None,
            generate_kwargs={"temperature": temperature, "max_tokens": max_tokens, "timeout": timeout_seconds},
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def __call__(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        return await self._client(messages, **kwargs)


class GroqProviderClient:
    class _TextBlockAdapter:
        @staticmethod
        def make(text: str) -> dict[str, str]:
            return {"type": "text", "text": text}

    class _ResponseAdapter:
        def __init__(self, response: Any) -> None:
            self._response = response
            self.content = self._extract_content(response)

        @staticmethod
        def _extract_content(response: Any) -> list[dict[str, str]]:
            choice = response.choices[0] if getattr(response, "choices", None) else None
            if choice is None:
                return []
            message = getattr(choice, "message", None)
            if message is not None:
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    return [GroqProviderClient._TextBlockAdapter.make(content)]
                if content is not None:
                    return [GroqProviderClient._TextBlockAdapter.make(str(content))]
            text = getattr(choice, "text", None)
            if isinstance(text, str):
                return [GroqProviderClient._TextBlockAdapter.make(text)]
            return [GroqProviderClient._TextBlockAdapter.make(str(response))]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._response, name)

    class _StreamChunkAdapter:
        def __init__(self, chunk: Any) -> None:
            self._chunk = chunk
            self.choices = getattr(chunk, "choices", None)
            self.content = self._extract_content(chunk)

        @staticmethod
        def _extract_content(chunk: Any) -> list[dict[str, str]]:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                return []
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is not None:
                content = getattr(delta, "content", None)
                if isinstance(content, str):
                    return [GroqProviderClient._TextBlockAdapter.make(content)]
                if content is not None:
                    return [GroqProviderClient._TextBlockAdapter.make(str(content))]
            message = getattr(choice, "message", None)
            if message is not None:
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    return [GroqProviderClient._TextBlockAdapter.make(content)]
                if content is not None:
                    return [GroqProviderClient._TextBlockAdapter.make(str(content))]
            text = getattr(choice, "text", None)
            if isinstance(text, str):
                return [GroqProviderClient._TextBlockAdapter.make(text)]
            return []

        def __getattr__(self, name: str) -> Any:
            return getattr(self._chunk, name)

    class _StreamResponseAdapter:
        def __init__(self, stream: Any) -> None:
            self._stream = stream
            self.content: list[dict[str, str]] = []
            self.choices: list[Any] = []

        def __aiter__(self) -> "GroqProviderClient._StreamResponseAdapter":
            return self

        async def __anext__(self) -> Any:
            chunk = await self._stream.__anext__()
            adapted = GroqProviderClient._StreamChunkAdapter(chunk)
            self.content.extend(adapted.content)
            if getattr(adapted, "choices", None):
                self.choices = adapted.choices
            return adapted

    def __init__(self, *, api_key: str | None, model_name: str, stream: bool, temperature: float, timeout_seconds: int, max_tokens: int, reasoning_effort: str | None = None, extra: dict[str, Any] | None = None) -> None:
        if AsyncGroq is None:  # pragma: no cover
            raise RuntimeError("groq is required to construct Groq runtime models")
        self._client = AsyncGroq(api_key=api_key)
        self._model_name = model_name
        self._stream = stream
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._extra = dict(extra or {})

    @property
    def stream(self) -> bool:
        return self._stream

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    @staticmethod
    def _normalize_tool_choice(tool_choice: Any) -> Any:
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            return tool_choice if tool_choice in {"none", "auto", "required"} else "auto"
        if isinstance(tool_choice, dict):
            choice_type = tool_choice.get("type")
            if choice_type in {"none", "auto", "required"}:
                return choice_type
            return "auto"
        return "auto"

    @classmethod
    def _sanitize_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(payload)
        if "tool_choice" in sanitized:
            normalized = cls._normalize_tool_choice(sanitized.get("tool_choice"))
            if normalized is None:
                sanitized.pop("tool_choice", None)
            else:
                sanitized["tool_choice"] = normalized
        return sanitized

    async def __call__(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "temperature": self._temperature,
            "max_completion_tokens": self._max_tokens,
            "stream": self._stream,
            "timeout": self._timeout_seconds,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        if self._extra:
            payload.update(self._extra)
        if kwargs:
            payload.update(kwargs)
        payload = self._sanitize_payload(payload)
        response = await self._client.chat.completions.create(**payload)
        if self._stream:
            return self._StreamResponseAdapter(response)
        return self._ResponseAdapter(response)
