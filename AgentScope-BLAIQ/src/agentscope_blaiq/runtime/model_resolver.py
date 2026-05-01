from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from openai import AuthenticationError

from agentscope_blaiq.runtime.config import Settings, settings
from agentscope_blaiq.runtime.provider_clients import GroqProviderClient, OpenAICompatibleProviderClient


@dataclass(frozen=True)
class ResolvedModel:
    role: str
    model_name: str
    provider: str
    api_key: str | None
    api_base: str | None
    timeout_seconds: int
    max_output_tokens: int
    temperature: float
    reasoning_effort: str | None = None
    fallback_model: str | None = None


class _ResolverBase:
    """Central LiteLLM routing policy for all AgentScope-BLAIQ agents."""

    def __init__(self, runtime_settings: Settings | None = None) -> None:
        self.settings = runtime_settings or settings

    @classmethod
    def from_settings(cls, runtime_settings: Settings | None = None) -> "_ResolverBase":
        return cls(runtime_settings=runtime_settings)

    def build_agentscope_model(self, role: str, *, stream: bool = False) -> "ResolvedModelClient":
        resolved = self.resolve(role)
        if resolved.provider == "groq":
            return self._build_groq_model(resolved, stream=stream)
        return ResolvedModelClient(self, resolved, stream=stream)

    def build_agentscope_model_from_resolved(self, resolved: ResolvedModel, *, stream: bool = False) -> "ResolvedModelClient":
        if resolved.provider == "groq":
            return self._build_groq_model(resolved, stream=stream)
        return ResolvedModelClient(self, resolved, stream=stream)

    def _provider_for_model(self, model_name: str) -> str:
        if model_name.startswith("groq/"):
            return "groq"
        if model_name.startswith(("openai/", "vertex_ai/", "aws-cris/", "gemini/", "anthropic/")):
            return "openai_compatible"
        return "openai_compatible"

    @staticmethod
    def _strip_provider_prefix(model_name: str) -> str:
        if "/" not in model_name:
            return model_name
        return model_name.split("/", 1)[1]

    def _runtime_model_name(self, resolved: ResolvedModel, model_name: str) -> str:
        if resolved.provider == "groq":
            return self._strip_provider_prefix(model_name)
        if resolved.api_base:
            return model_name
        return self._strip_provider_prefix(model_name)

    def _prefer_litellm_proxy(self) -> bool:
        return bool(self.settings.litellm_api_base_url)

    @staticmethod
    def _normalize_temperature_for_model(model_name: str, temperature: float) -> float:
        normalized = (model_name or "").lower()
        if "gpt-5" in normalized:
            return 1.0
        return temperature

    @staticmethod
    def _needs_proxy_modify_params(model_name: str, api_base: str | None) -> bool:
        if not api_base:
            return False
        normalized = (model_name or "").lower()
        return normalized.startswith(("vertex_ai/claude", "anthropic/", "claude-")) or "/claude" in normalized

    def _build_resolved_model(
        self,
        *,
        role: str,
        model_name: str,
        temperature: float,
        fallback_model: str | None,
    ) -> ResolvedModel:
        provider = self._provider_for_model(model_name)
        if self._prefer_litellm_proxy():
            api_key = self.settings.litellm_api_key or self.settings.openai_api_key
            api_base = self.settings.litellm_api_base_url
        elif provider == "groq":
            api_key = self.settings.groq_api_key or self.settings.litellm_api_key or self.settings.openai_api_key
            api_base = self.settings.groq_api_base_url
        else:
            api_key = self.settings.openai_api_key
            api_base = self.settings.openai_api_base_url

        return ResolvedModel(
            role=role,
            model_name=model_name,
            provider=provider,
            api_key=api_key,
            api_base=api_base,
            timeout_seconds=self.settings.llm_timeout_seconds,
            max_output_tokens=self.settings.llm_max_output_tokens,
            temperature=self._normalize_temperature_for_model(model_name, temperature),
            reasoning_effort=self.settings.model_reasoning_effort,
            fallback_model=fallback_model,
        )

    def _build_groq_model(self, resolved: ResolvedModel, *, stream: bool = False) -> GroqProviderClient:
        return GroqProviderClient(
            api_key=resolved.api_key,
            model_name=self._runtime_model_name(resolved, resolved.model_name),
            stream=stream,
            temperature=resolved.temperature,
            timeout_seconds=resolved.timeout_seconds,
            max_tokens=resolved.max_output_tokens,
            reasoning_effort=resolved.reasoning_effort,
        )

    def resolve(self, role: str) -> ResolvedModel:
        role_key = role.lower()
        if role_key == "skill_selector":
            return self._build_resolved_model(role=role_key, model_name=self.settings.skill_selector_model, temperature=0.0, fallback_model=self.settings.llm_fallback_model)
        if role_key == "routing":
            return self._build_resolved_model(role=role_key, model_name=self.settings.routing_model, temperature=0.0, fallback_model=self.settings.llm_fallback_model)
        if role_key == "strategic":
            return self._build_resolved_model(role=role_key, model_name=self.settings.strategic_model, temperature=self.settings.strategic_temperature, fallback_model=self.settings.llm_fallback_model)
        if role_key == "research":
            return self._build_resolved_model(role=role_key, model_name=self.settings.research_model, temperature=self.settings.research_temperature, fallback_model=self.settings.llm_fallback_model)
        if role_key == "hitl":
            return self._build_resolved_model(role=role_key, model_name=self.settings.hitl_model, temperature=self.settings.hitl_temperature, fallback_model=self.settings.llm_fallback_model)
        if role_key == "content_director":
            resolved = self._build_resolved_model(role=role_key, model_name=self.settings.content_director_model, temperature=self.settings.strategic_temperature, fallback_model=self.settings.llm_fallback_model)
            return ResolvedModel(role=resolved.role, model_name=resolved.model_name, provider=resolved.provider, api_key=resolved.api_key, api_base=resolved.api_base, timeout_seconds=600, max_output_tokens=self.settings.content_director_max_output_tokens, temperature=resolved.temperature, reasoning_effort=resolved.reasoning_effort, fallback_model=resolved.fallback_model)
        if role_key == "vangogh":
            resolved = self._build_resolved_model(role=role_key, model_name=self.settings.vangogh_model, temperature=self.settings.vangogh_temperature, fallback_model=self.settings.llm_fallback_model)
            return ResolvedModel(role=resolved.role, model_name=resolved.model_name, provider=resolved.provider, api_key=resolved.api_key, api_base=resolved.api_base, timeout_seconds=600, max_output_tokens=self.settings.vangogh_max_output_tokens, temperature=resolved.temperature, reasoning_effort=resolved.reasoning_effort, fallback_model=resolved.fallback_model)
        if role_key == "governance":
            return self._build_resolved_model(role=role_key, model_name=self.settings.governance_model, temperature=self.settings.governance_temperature, fallback_model=self.settings.llm_fallback_model)
        if role_key == "text_buddy":
            resolved = self._build_resolved_model(role=role_key, model_name=self.settings.text_buddy_model, temperature=self.settings.text_buddy_temperature, fallback_model=self.settings.llm_fallback_model)
            return ResolvedModel(role=resolved.role, model_name=resolved.model_name, provider=resolved.provider, api_key=resolved.api_key, api_base=resolved.api_base, timeout_seconds=resolved.timeout_seconds, max_output_tokens=self.settings.text_buddy_max_output_tokens, temperature=resolved.temperature, reasoning_effort=resolved.reasoning_effort, fallback_model=resolved.fallback_model)
        if role_key == "graph_knowledge":
            return self._build_resolved_model(role=role_key, model_name=self.settings.research_model, temperature=self.settings.research_temperature, fallback_model=self.settings.llm_fallback_model)
        if role_key == "data_scientist":
            return self._build_resolved_model(role=role_key, model_name=self.settings.research_model, temperature=0.1, fallback_model=self.settings.llm_fallback_model)
        if role_key == "oracle":
            return self._build_resolved_model(role=role_key, model_name=self.settings.hitl_model, temperature=0.3, fallback_model=self.settings.llm_fallback_model)
        if role_key == "custom":
            return self._build_resolved_model(role=role_key, model_name=self.settings.strategic_model, temperature=self.settings.strategic_temperature, fallback_model=self.settings.llm_fallback_model)
        raise ValueError(f"Unknown model role: {role}")

    def resolve_model_name(self, model_name: str, *, role: str, temperature: float | None = None, max_output_tokens: int | None = None, fallback_model: str | None = None) -> ResolvedModel:
        resolved_role = role.lower()
        base = self.resolve(resolved_role)
        resolved = self._build_resolved_model(role=resolved_role, model_name=model_name, temperature=base.temperature if temperature is None else temperature, fallback_model=fallback_model)
        if max_output_tokens is None:
            return resolved
        return ResolvedModel(role=resolved.role, model_name=resolved.model_name, provider=resolved.provider, api_key=resolved.api_key, api_base=resolved.api_base, timeout_seconds=resolved.timeout_seconds, max_output_tokens=max_output_tokens, temperature=resolved.temperature, reasoning_effort=resolved.reasoning_effort, fallback_model=resolved.fallback_model)

    def _build_openai_chat_model(self, resolved: ResolvedModel, *, stream: bool = False) -> OpenAICompatibleProviderClient:
        model_name = self._runtime_model_name(resolved, resolved.model_name)
        return OpenAICompatibleProviderClient(
            model_name=model_name,
            api_key=resolved.api_key,
            api_base=resolved.api_base,
            stream=stream,
            temperature=resolved.temperature,
            timeout_seconds=resolved.timeout_seconds,
            max_tokens=resolved.max_output_tokens,
            reasoning_effort=resolved.reasoning_effort,
        )

    async def acompletion(self, role: str, messages: list[dict[str, str]], *, model_name: str | None = None, stream: bool = False, response_format: dict[str, Any] | None = None, max_tokens: int | None = None, temperature: float | None = None) -> Any:
        resolved = self.resolve(role)
        try:
            from litellm import acompletion
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("litellm is required to execute AgentScope-BLAIQ model calls") from exc
        final_model = model_name if model_name is not None else resolved.model_name
        actual_model = self._runtime_model_name(resolved, final_model)
        kwargs: dict[str, Any] = {
            "model": actual_model,
            "messages": messages,
            "api_key": resolved.api_key,
            "api_base": resolved.api_base,
            "timeout": resolved.timeout_seconds,
            "stream": stream,
            "temperature": self._normalize_temperature_for_model(final_model, resolved.temperature if temperature is None else temperature),
            "max_tokens": resolved.max_output_tokens if max_tokens is None else max_tokens,
        }
        if resolved.api_base:
            kwargs["custom_llm_provider"] = "openai"
        if self._needs_proxy_modify_params(final_model, resolved.api_base):
            kwargs["modify_params"] = True
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            return await acompletion(**kwargs)
        except Exception:
            if resolved.fallback_model and resolved.fallback_model != resolved.model_name:
                fallback = self.resolve_model_name(resolved.fallback_model, role=role, temperature=kwargs["temperature"], max_output_tokens=kwargs["max_tokens"])
                kwargs["model"] = self._runtime_model_name(fallback, fallback.model_name)
                kwargs["api_key"] = fallback.api_key
                kwargs["api_base"] = fallback.api_base
                kwargs["timeout"] = fallback.timeout_seconds
                kwargs["temperature"] = self._normalize_temperature_for_model(fallback.model_name, fallback.temperature)
                kwargs["max_tokens"] = fallback.max_output_tokens
                if fallback.api_base:
                    kwargs["custom_llm_provider"] = "openai"
                    if self._needs_proxy_modify_params(fallback.model_name, fallback.api_base):
                        kwargs["modify_params"] = True
                    else:
                        kwargs.pop("modify_params", None)
                else:
                    kwargs.pop("custom_llm_provider", None)
                    kwargs.pop("modify_params", None)
                return await acompletion(**kwargs)
            raise

    @staticmethod
    def extract_text(response: Any) -> str:
        choice = response.choices[0]
        message = getattr(choice, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content.strip()
            if content is not None:
                return str(content).strip()
        text = getattr(choice, "text", None)
        if isinstance(text, str):
            return text.strip()
        return str(response).strip()

    @staticmethod
    def extract_json_text(text: str) -> str:
        if not text:
            return ""
        cleaned = text.strip()
        block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if block_match:
            cleaned = block_match.group(1).strip()
        else:
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()
        if cleaned:
            return cleaned
        object_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if object_match:
            return object_match.group(1).strip()
        array_match = re.search(r"(\[.*\])", text, re.DOTALL)
        if array_match:
            return array_match.group(1).strip()
        return text.strip()

    @staticmethod
    def safe_json_loads(text: str) -> dict[str, Any]:
        if not text:
            raise json.JSONDecodeError("Empty input text", "", 0)
        cleaned = _ResolverBase.extract_json_text(text)
        if not cleaned:
            raise json.JSONDecodeError("No JSON content found in payload", text, 0)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        object_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if object_match:
            try:
                return json.loads(object_match.group(0))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        array_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if array_match:
            try:
                parsed = json.loads(array_match.group(0))
                if isinstance(parsed, dict):
                    return parsed
                return {"items": parsed}
            except json.JSONDecodeError:
                pass
        array_match_raw = re.search(r"\[.*\]", text, re.DOTALL)
        if array_match_raw:
            try:
                parsed = json.loads(array_match_raw.group(0))
                if isinstance(parsed, dict):
                    return parsed
                return {"items": parsed}
            except json.JSONDecodeError:
                pass
        raise json.JSONDecodeError("No JSON object found in payload", cleaned, 0)


class ResolvedModelClient(_ResolverBase):
    """Wrapper around AgentScope's OpenAIChatModel with centralized fallback."""

    def __init__(self, resolver: "_ResolverBase", resolved: ResolvedModel, stream: bool = False) -> None:
        self._resolver = resolver
        self._resolved = resolved
        self._stream = stream
        self._client = resolver._build_openai_chat_model(resolved, stream=stream)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def __call__(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        try:
            return await self._client(messages, **kwargs)
        except AuthenticationError:
            fallback_model = self._resolved.fallback_model
            if not fallback_model or fallback_model == self._resolved.model_name:
                raise
            fallback = self._resolver.resolve_model_name(
                fallback_model,
                role=self._resolved.role,
                temperature=self._resolved.temperature,
                max_output_tokens=self._resolved.max_output_tokens,
            )
            fallback_client = self._resolver._build_openai_chat_model(fallback, stream=self._stream)
            return await fallback_client(messages, **kwargs)


LiteLLMModelResolver = _ResolverBase
