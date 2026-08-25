from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from app.config import Settings

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """Provider failure with a safe, non-secret attempt trace."""

    def __init__(self, message: str, *, attempts: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.attempts = attempts


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete_structured(self, response_model: type[T], system: str, user: str) -> T:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        import httpx

        self.client = httpx.Client(timeout=45.0)
        self.api_key = api_key
        self.model = model

    def complete_structured(self, response_model: type[T], system: str, user: str) -> T:
        try:
            response = self.client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json={
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseJsonSchema": response_model.model_json_schema(),
                        "temperature": 0.1,
                    },
                },
            )
            response.raise_for_status()
            content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return response_model.model_validate_json(content)
        except Exception as exc:
            raise ProviderError("Gemini structured completion failed") from exc


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str) -> None:
        from groq import Groq

        self.client = Groq(api_key=api_key)
        self.model = model

    def complete_structured(self, response_model: type[T], system: str, user: str) -> T:
        schema = response_model.model_json_schema()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": response_model.__name__, "strict": True, "schema": schema},
                },
                temperature=0.1,
            )
            content = response.choices[0].message.content
            if not content:
                raise ProviderError("Groq returned an empty response")
            return response_model.model_validate_json(content)
        except Exception as exc:
            raise ProviderError("Groq structured completion failed") from exc


class ProviderRouter:
    def __init__(self, settings: Settings) -> None:
        self.providers: list[LLMProvider] = []
        self._configure(settings)

    def _configure(self, settings: Settings) -> None:
        configured: dict[str, LLMProvider] = {}
        if settings.gemini_api_key and settings.gemini_api_key.get_secret_value():
            configured["gemini"] = GeminiProvider(settings.gemini_api_key.get_secret_value(), settings.llm_model)
        if settings.groq_api_key and settings.groq_api_key.get_secret_value():
            configured["groq"] = GroqProvider(settings.groq_api_key.get_secret_value(), settings.groq_model)
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
        last_error: Exception | None = None
        attempts: list[str] = []
        for provider in self.providers[:2]:
            attempts.append(provider.name)
            try:
                result = provider.complete_structured(response_model, system, user)
                # The trace contains provider names only; request content, keys,
                # exception messages, and response data never enter telemetry.
                return result, "->".join(attempts)
            except ProviderError as exc:
                last_error = exc
        raise ProviderError("All configured providers failed", attempts=tuple(attempts)) from last_error
