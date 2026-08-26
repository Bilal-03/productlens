from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.ai.providers import ProviderError, ProviderRouter, ProviderUsage
from app.models.contracts import SQLProposal, SQLValidation
from app.security.sql_validator import SQLValidator
from app.semantic.registry import registry

T = TypeVar("T", bound=BaseModel)


class StructuredCompletionRouter(Protocol):
    @property
    def available(self) -> bool:
        ...

    def complete_structured(self, response_model: type[T], system: str, user: str) -> tuple[T, str]:
        ...


@dataclass(frozen=True)
class SQLGenerationResult:
    proposal: SQLProposal | None
    validation: SQLValidation
    provider: str
    repaired: bool = False
    attempts: int = 1
    initial_query: str | None = None
    initial_validation: SQLValidation | None = None
    repair_query: str | None = None
    error_code: str | None = None
    usage: ProviderUsage | None = None


class SQLGenerator:
    """Generate one governed ad-hoc SQL proposal and optionally repair it once.

    The model is never allowed to decide whether a query is safe. Every initial
    and repaired proposal is passed through the same SQLGlot validator before it
    can reach the read-only executor. Unsafe and over-complex queries are never
    sent to the repair prompt.
    """

    SYSTEM_PROMPT = """
You generate one read-only PostgreSQL query for ProductLens AI.
Return only the requested structured JSON object. Use only the approved analytics
views and visible columns in the supplied catalog. Do not use core, operational,
system catalogs, PII, comments, multiple statements, DML/DDL, SELECT INTO,
locking clauses, unsafe functions, cross joins, or unbounded joins. Use a single
SELECT or WITH ... SELECT statement. Qualify columns when joins are present and
use explicit aliases. Keep the result useful for the question and deterministic.
The application will parse, validate, cap, and execute the query in a read-only
transaction; never put credentials or secrets in SQL.
""".strip()

    REPAIR_PROMPT = """
Repair exactly one generated ProductLens SQL query. Return only the same
structured JSON object. Fix syntax or approved-schema mistakes using only the
supplied catalog. Preserve the user's analytical intent. Do not change a query
into DML/DDL, a multi-statement query, a system-catalog query, a query with
unsafe functions, a cross/unbounded join, or any other unsafe shape. If a safe
repair is not possible, return the original query unchanged so the validator
can reject it.
""".strip()

    def __init__(
        self,
        router: StructuredCompletionRouter | ProviderRouter,
        validator: SQLValidator,
    ) -> None:
        self.router = router
        self.validator = validator

    @property
    def available(self) -> bool:
        return self.router.available

    def generate(self, question: str) -> SQLGenerationResult:
        if not self.router.available:
            raise ProviderError("No structured SQL provider is configured")

        context = registry.relevant_schema_context(question)
        payload = json.dumps(
            {"question": question, "approved_schema": context},
            sort_keys=True,
            separators=(",", ":"),
        )
        candidate, provider = self.router.complete_structured(SQLProposal, self.SYSTEM_PROMPT, payload)
        usage = getattr(self.router, "last_usage", None)
        first_validation = self.validator.validate(candidate.query)
        if first_validation.valid:
            return SQLGenerationResult(
                proposal=self._validated_proposal(candidate, first_validation),
                validation=first_validation,
                provider=provider,
                initial_query=candidate.query,
                initial_validation=first_validation,
                usage=usage,
            )

        # Safety failures are terminal. In particular, do not let a repair
        # prompt turn a destructive query into an apparently safe one.
        if first_validation.failure_kind not in {"syntax", "schema"}:
            return SQLGenerationResult(
                proposal=None,
                validation=first_validation,
                provider=provider,
                initial_query=candidate.query,
                initial_validation=first_validation,
                error_code=self._error_code(first_validation),
                usage=usage,
            )

        repair_payload = json.dumps(
            {
                "question": question,
                "approved_schema": context,
                "original_proposal": candidate.model_dump(mode="json"),
                "validation_errors": first_validation.errors,
                "failure_kind": first_validation.failure_kind,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            repaired, repair_provider = self.router.complete_structured(
                SQLProposal,
                self.REPAIR_PROMPT,
                repair_payload,
            )
            repair_usage = getattr(self.router, "last_usage", None)
        except ProviderError:
            return SQLGenerationResult(
                proposal=None,
                validation=first_validation,
                provider=provider,
                repaired=True,
                attempts=2,
                initial_query=candidate.query,
                initial_validation=first_validation,
                error_code="LLM_UNAVAILABLE",
                usage=usage,
            )
        repaired_validation = self.validator.validate(repaired.query)
        provider_trace = provider if repair_provider == provider else f"{provider}+repair:{repair_provider}"
        if repaired_validation.valid:
            return SQLGenerationResult(
                proposal=self._validated_proposal(repaired, repaired_validation),
                validation=repaired_validation,
                provider=provider_trace,
                repaired=True,
                attempts=2,
                initial_query=candidate.query,
                initial_validation=first_validation,
                repair_query=repaired.query,
                usage=repair_usage,
            )
        return SQLGenerationResult(
            proposal=None,
            validation=repaired_validation,
            provider=provider_trace,
            repaired=True,
            attempts=2,
            initial_query=candidate.query,
            initial_validation=first_validation,
            repair_query=repaired.query,
            error_code=self._error_code(repaired_validation),
            usage=repair_usage,
        )

    @staticmethod
    def _validated_proposal(proposal: SQLProposal, validation: SQLValidation) -> SQLProposal:
        """Keep model metadata but make execution use validator-normalized SQL."""

        return proposal.model_copy(update={"query": validation.normalized_query or proposal.query})

    @staticmethod
    def _error_code(validation: SQLValidation) -> str:
        if validation.failure_kind in {"unsafe", "complexity"}:
            return "UNSAFE_SQL"
        return "SQL_GENERATION_FAILED"
