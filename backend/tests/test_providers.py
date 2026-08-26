from __future__ import annotations

from typing import TypeVar

import pytest
from pydantic import BaseModel

from app.ai.providers import LLMProvider, ProviderError, ProviderRouter, ProviderUsage
from app.config import Settings


class Completion(BaseModel):
    value: int


TModel = TypeVar("TModel", bound=BaseModel)


class FailingProvider(LLMProvider):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def complete_structured(self, response_model: type[TModel], system: str, user: str) -> TModel:
        self.calls += 1
        raise ProviderError(f"{self.name} unavailable")


class SuccessfulProvider(LLMProvider):
    name = "groq"

    def __init__(self) -> None:
        self.calls = 0

    def complete_structured(self, response_model: type[TModel], system: str, user: str) -> TModel:
        self.calls += 1
        return response_model.model_validate({"value": 7})


class UsageProvider(SuccessfulProvider):
    def complete_structured(self, response_model: type[TModel], system: str, user: str) -> TModel:
        result = super().complete_structured(response_model, system, user)
        self.last_usage = ProviderUsage(provider=self.name, model="test-model", input_tokens=11, output_tokens=7, latency_ms=1.5)
        return result


class TimeoutAwareProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        self.timeout_seconds: float | None = None

    def complete_structured(
        self,
        response_model: type[TModel],
        system: str,
        user: str,
        *,
        timeout_seconds: float | None = None,
    ) -> TModel:
        del system, user
        self.timeout_seconds = timeout_seconds
        return response_model.model_validate({"value": 9})


def router_with_providers(*providers: LLMProvider) -> ProviderRouter:
    router = ProviderRouter(Settings(gemini_api_key=None, groq_api_key=None))
    router.providers = list(providers)
    return router


def test_provider_failover_returns_safe_attempt_trace() -> None:
    primary = FailingProvider("gemini")
    fallback = SuccessfulProvider()
    router = router_with_providers(primary, fallback)

    result, trace = router.complete_structured(Completion, "system", "user")

    assert result.value == 7
    assert trace == "gemini->groq"
    assert primary.calls == 1
    assert fallback.calls == 1


def test_provider_router_attempts_at_most_one_fallback() -> None:
    primary = FailingProvider("gemini")
    fallback = FailingProvider("groq")
    third = SuccessfulProvider()
    router = router_with_providers(primary, fallback, third)

    with pytest.raises(ProviderError) as raised:
        router.complete_structured(Completion, "system", "user")

    assert raised.value.attempts == ("gemini", "groq")
    assert primary.calls == 1
    assert fallback.calls == 1
    assert third.calls == 0


def test_provider_router_exposes_non_sensitive_usage_metadata() -> None:
    provider = UsageProvider()
    router = router_with_providers(provider)
    result, trace = router.complete_structured(Completion, "system", "user")
    assert result.value == 7
    assert trace == "groq"
    assert router.last_usage is not None
    assert router.last_usage.model == "test-model"
    assert router.last_usage.input_tokens == 11
    assert router.last_usage.output_tokens == 7


def test_provider_router_supports_one_bounded_attempt() -> None:
    provider = TimeoutAwareProvider()
    router = router_with_providers(provider)

    result, trace = router.complete_structured_with_timeout(
        Completion,
        "system",
        "user",
        timeout_seconds=0.25,
        max_attempts=1,
    )

    assert result.value == 9
    assert trace == "gemini"
    assert provider.timeout_seconds == 0.25
