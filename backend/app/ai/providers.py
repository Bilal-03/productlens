from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from app.config import Settings

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ProviderUsage:
    provider: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class ProviderError(RuntimeError):
    """Provider failure with a safe, non-secret attempt trace."""

    def __init__(self, message: str, *, attempts: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.attempts = attempts


class LLMProvider(ABC):
    name: str
    last_usage: ProviderUsage | None = None

    @abstractmethod
    def complete_structured(
        self,
        response_model: type[T],
        system: str,
        user: str,
        *,
        timeout_seconds: float | None = None,
    ) -> T:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 45.0) -> None:
        import httpx

        self.client = httpx.Client(timeout=timeout_seconds)
        self.api_key = api_key
        self.model = model

    def complete_structured(
        self,
        response_model: type[T],
        system: str,
        user: str,
        *,
        timeout_seconds: float | None = None,
    ) -> T:
        started = time.perf_counter()
        try:
            request_params = {"key": self.api_key}
            request_json = {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": response_model.model_json_schema(),
                    "temperature": 0.1,
                },
            }
            request_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            if timeout_seconds is None:
                response = self.client.post(request_url, params=request_params, json=request_json)
            else:
                response = self.client.post(
                    request_url,
                    params=request_params,
                    json=request_json,
                    timeout=timeout_seconds,
                )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usageMetadata", {})
            self.last_usage = ProviderUsage(
                provider=self.name,
                model=self.model,
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
            return response_model.model_validate_json(content)
        except Exception as exc:
            raise ProviderError("Gemini structured completion failed") from exc


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 45.0) -> None:
        from groq import Groq

        self.client = Groq(api_key=api_key, timeout=timeout_seconds)
        self.model = model

    def complete_structured(
        self,
        response_model: type[T],
        system: str,
        user: str,
        *,
        timeout_seconds: float | None = None,
    ) -> T:
        started = time.perf_counter()
        schema = response_model.model_json_schema()
        try:
            request_messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            request_format = {
                "type": "json_schema",
                "json_schema": {"name": response_model.__name__, "strict": True, "schema": schema},
            }
            create_completion = cast(Any, self.client.chat.completions.create)
            if timeout_seconds is None:
                response = create_completion(
                    model=self.model,
                    messages=request_messages,
                    response_format=request_format,
                    temperature=0.1,
                )
            else:
                response = create_completion(
                    model=self.model,
                    messages=request_messages,
                    response_format=request_format,
                    temperature=0.1,
                    timeout=timeout_seconds,
                )
            content = response.choices[0].message.content
            if not content:
                raise ProviderError("Groq returned an empty response")
            usage = getattr(response, "usage", None)
            self.last_usage = ProviderUsage(
                provider=self.name,
                model=self.model,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            return response_model.model_validate_json(content)
        except Exception as exc:
            raise ProviderError("Groq structured completion failed") from exc


class ProviderRouter:
    def __init__(
        self,
        settings: Settings,
        *,
        timeout_seconds: float | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.providers: list[LLMProvider] = []
        self.last_usage: ProviderUsage | None = None
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, min(max_attempts, 2))
        self._configure(settings)

    def _configure(self, settings: Settings) -> None:
        configured: dict[str, LLMProvider] = {}
        if settings.gemini_api_key and settings.gemini_api_key.get_secret_value():
            configured["gemini"] = GeminiProvider(
                settings.gemini_api_key.get_secret_value(),
                settings.llm_model,
                timeout_seconds=self.timeout_seconds or 45.0,
            )
        if settings.groq_api_key and settings.groq_api_key.get_secret_value():
            configured["groq"] = GroqProvider(
                settings.groq_api_key.get_secret_value(),
                settings.groq_model,
                timeout_seconds=self.timeout_seconds or 45.0,
            )
        for name in [settings.llm_provider, settings.llm_fallback_provider]:
            provider = configured.get(name)
            if provider and provider not in self.providers:
                self.providers.append(provider)

    @property
    def available(self) -> bool:
        return bool(self.providers)

    @property
    def primary_name(self) -> str:
        return self.providers[0].name if self.providers else "deterministic"

    def complete_structured(self, response_model: type[T], system: str, user: str) -> tuple[T, str]:
        return self._complete(
            response_model,
            system,
            user,
            timeout_seconds=self.timeout_seconds,
            max_attempts=self.max_attempts,
        )

    def complete_structured_with_timeout(
        self,
        response_model: type[T],
        system: str,
        user: str,
        *,
        timeout_seconds: float,
        max_attempts: int = 1,
    ) -> tuple[T, str]:
        return self._complete(
            response_model,
            system,
            user,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )

    def _complete(
        self,
        response_model: type[T],
        system: str,
        user: str,
        *,
        timeout_seconds: float | None,
        max_attempts: int,
    ) -> tuple[T, str]:
        self.last_usage = None
        last_error: Exception | None = None
        attempts: list[str] = []
        for provider in self.providers[: max(1, min(max_attempts, 2))]:
            attempts.append(provider.name)
            try:
                if timeout_seconds is None:
                    result = provider.complete_structured(response_model, system, user)
                else:
                    result = provider.complete_structured(
                        response_model,
                        system,
                        user,
                        timeout_seconds=timeout_seconds,
                    )
                # The trace contains provider names only; request content, keys,
                # exception messages, and response data never enter telemetry.
                self.last_usage = provider.last_usage or ProviderUsage(
                    provider=provider.name,
                    model=getattr(provider, "model", None),
                )
                return result, "->".join(attempts)
            except ProviderError as exc:
                last_error = exc
        raise ProviderError("All configured providers failed", attempts=tuple(attempts)) from last_error
