from __future__ import annotations

from typing import Any

from app.ai.planner import AdHocQuestion, QuestionPlanner
from app.ai.providers import ProviderError
from app.ai.sql_generation import SQLGenerator
from app.models.contracts import SQLProposal
from app.security.sql_validator import SQLSafetyPolicy, SQLValidator


class FakeStructuredRouter:
    def __init__(self, responses: list[SQLProposal]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    @property
    def available(self) -> bool:
        return True

    def complete_structured(self, response_model: type[Any], system: str, user: str) -> tuple[SQLProposal, str]:
        self.calls.append({"response_model": response_model, "system": system, "user": user})
        return self.responses.pop(0), "fake"


class RepairUnavailableRouter(FakeStructuredRouter):
    def complete_structured(self, response_model: type[Any], system: str, user: str) -> tuple[SQLProposal, str]:
        if self.calls:
            self.calls.append({"response_model": response_model, "system": system, "user": user})
            raise ProviderError("repair unavailable")
        return super().complete_structured(response_model, system, user)


def proposal(query: str) -> SQLProposal:
    return SQLProposal(
        query=query,
        purpose="Inspect approved analytics data",
        tables_used=["users"],
        metrics_used=[],
    )


def generator(router: FakeStructuredRouter) -> SQLGenerator:
    return SQLGenerator(router, SQLValidator(SQLSafetyPolicy(max_rows=5000)))


def test_ad_hoc_question_is_classified_outside_governed_templates() -> None:
    result = QuestionPlanner().plan("What is the average session duration by browser?")
    assert isinstance(result, AdHocQuestion)


def test_valid_structured_sql_does_not_trigger_repair() -> None:
    router = FakeStructuredRouter([proposal("SELECT user_id FROM analytics.users")])

    result = generator(router).generate("List users")

    assert result.proposal is not None
    assert result.validation.valid
    assert result.attempts == 1
    assert not result.repaired
    assert len(router.calls) == 1
    assert "approved_schema" in router.calls[0]["user"]


def test_schema_error_gets_exactly_one_safe_repair_attempt() -> None:
    router = FakeStructuredRouter(
        [
            proposal("SELECT missing_column FROM analytics.users"),
            proposal("SELECT user_id FROM analytics.users"),
        ]
    )

    result = generator(router).generate("List user identifiers")

    assert result.proposal is not None
    assert result.validation.valid
    assert result.repaired
    assert result.attempts == 2
    assert len(router.calls) == 2
    assert "validation_errors" in router.calls[1]["user"]


def test_unsafe_sql_is_rejected_without_repair() -> None:
    router = FakeStructuredRouter(
        [proposal("DROP TABLE analytics.users")]
    )

    result = generator(router).generate("List users")

    assert result.proposal is None
    assert not result.validation.valid
    assert result.validation.failure_kind == "unsafe"
    assert result.error_code == "UNSAFE_SQL"
    assert not result.repaired
    assert result.attempts == 1
    assert len(router.calls) == 1


def test_unbounded_limit_shape_is_rejected_without_repair() -> None:
    router = FakeStructuredRouter(
        [
            proposal("SELECT user_id FROM analytics.users LIMIT requested_limit"),
            proposal("SELECT user_id FROM analytics.users"),
        ]
    )

    result = generator(router).generate("List users")

    assert result.proposal is None
    assert result.error_code == "UNSAFE_SQL"
    assert result.validation.failure_kind == "complexity"
    assert len(router.calls) == 1


def test_repair_failure_is_terminal_after_second_validation() -> None:
    router = FakeStructuredRouter(
        [
            proposal("SELECT missing_column FROM analytics.users"),
            proposal("SELECT another_missing_column FROM analytics.users"),
        ]
    )

    result = generator(router).generate("List user identifiers")

    assert result.proposal is None
    assert not result.validation.valid
    assert result.repaired
    assert result.attempts == 2
    assert result.error_code == "SQL_GENERATION_FAILED"
    assert len(router.calls) == 2


def test_repair_provider_failure_does_not_retry_again() -> None:
    router = RepairUnavailableRouter([proposal("SELECT missing_column FROM analytics.users")])

    result = generator(router).generate("List user identifiers")

    assert result.proposal is None
    assert result.error_code == "LLM_UNAVAILABLE"
    assert result.repaired
    assert result.attempts == 2
    assert len(router.calls) == 2
