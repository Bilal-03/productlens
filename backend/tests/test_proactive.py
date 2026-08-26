from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from app.ai.insights import GroundedInsight, InsightService
from app.ai.providers import ProviderError
from app.analytics.anomalies import AnomalyPolicy
from app.analytics.proactive import ProactiveAnalyticsService
from app.database.service import DatabaseUnavailable
from app.models.contracts import SQLValidation
from app.security.sql_validator import SQLValidator


class FakeDatabase:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(result_cache_ttl_seconds=300)
        self.version = "dataset-v1"
        self.cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls = 0

    def dataset_version(self) -> str:
        return self.version

    def cache_get(self, cache_key: str, dataset_version: str) -> dict[str, Any] | None:
        return self.cache.get((cache_key, dataset_version))

    def cache_put(self, cache_key: str, dataset_version: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        del ttl_seconds
        self.cache[(cache_key, dataset_version)] = payload

    def execute_readonly(self, validation: SQLValidation) -> tuple[list[dict[str, Any]], float]:
        self.calls += 1
        query = validation.normalized_query or ""
        if "AS BUCKET" in query.upper():
            if "PAYMENT_FAILED" not in query.upper():
                return [], 1.0
            rows: list[dict[str, Any]] = []
            cursor = date(2026, 4, 28)
            while cursor < date(2026, 8, 24):
                value = 220 if cursor >= date(2026, 8, 18) else 100
                rows.append({"bucket": cursor, "value": value, "numerator": value, "denominator": value})
                cursor += timedelta(days=1)
            return rows, 1.0
        if "concat_ws" in query:
            return [{"segment": "Mobile / Safari / Paid Social", "value": 220, "numerator": 220, "denominator": 220}], 1.0
        if "s.device" in query:
            return [{"segment": "Mobile", "value": 220, "numerator": 220, "denominator": 220}], 1.0
        return [{"segment": "All", "value": 100, "numerator": 100, "denominator": 200}], 1.0


def service(database: FakeDatabase | None = None) -> tuple[ProactiveAnalyticsService, FakeDatabase]:
    selected = database or FakeDatabase()
    return ProactiveAnalyticsService(selected, SQLValidator()), selected


class NarrativeRouter:
    available = True

    def __init__(self, response: GroundedInsight | None = None, error: bool = False) -> None:
        self.response = response
        self.error = error
        self.calls = 0
        self.last_usage = None

    def complete_structured(self, response_model: type[Any], system: str, user: str) -> tuple[GroundedInsight, str]:
        del response_model, system, user
        self.calls += 1
        if self.error:
            raise ProviderError("provider unavailable")
        assert self.response is not None
        return self.response, "fake"


class PartialDatabase(FakeDatabase):
    def execute_readonly(self, validation: SQLValidation) -> tuple[list[dict[str, Any]], float]:
        query = validation.normalized_query or ""
        if "AS BUCKET" in query.upper() and "PAYMENT_FAILED" in query.upper():
            raise DatabaseUnavailable("payment failure series unavailable")
        return super().execute_readonly(validation)


class SegmentDatabase(FakeDatabase):
    def execute_readonly(self, validation: SQLValidation) -> tuple[list[dict[str, Any]], float]:
        query = validation.normalized_query or ""
        if "AS BUCKET" in query.upper():
            if "CONCAT_WS" not in query.upper():
                return [], 1.0
            rows: list[dict[str, Any]] = []
            cursor = date(2026, 4, 28)
            while cursor < date(2026, 8, 24):
                value = 0.58 if cursor >= date(2026, 8, 18) else 0.89
                rows.append(
                    {
                        "bucket": cursor,
                        "segment": "Mobile / Safari / Paid Social",
                        "value": value,
                        "numerator": value * 40,
                        "denominator": 40,
                    }
                )
                cursor += timedelta(days=1)
            return rows, 1.0
        return super().execute_readonly(validation)


def test_product_pulse_detects_and_enriches_a_signal_then_uses_cache() -> None:
    proactive, database = service()
    first = proactive.pulse("last_30_days", 20)
    assert first.type == "product_pulse"
    assert first.items
    assert first.items[0].metric == "payment_failures"
    assert first.items[0].drivers
    assert first.items[0].evidence_ids
    calls_after_first = database.calls

    second = proactive.pulse("last_30_days", 20)
    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert database.calls == calls_after_first

    database.version = "dataset-v2"
    proactive.pulse("last_30_days", 20)
    assert database.calls > calls_after_first


def test_proactive_cache_key_includes_policy_version() -> None:
    default_service, database = service()
    revised_service = ProactiveAnalyticsService(
        database,
        SQLValidator(),
        policy=AnomalyPolicy(policy_version="rolling-zscore-v2"),
    )

    assert default_service._cache_key("pulse", {"period": "last_30_days"}) != revised_service._cache_key(
        "pulse", {"period": "last_30_days"}
    )


def test_anomalies_keep_partial_results_with_metric_warning() -> None:
    response = ProactiveAnalyticsService(PartialDatabase(), SQLValidator()).anomalies()

    assert response.sql.query_count >= 7
    assert any("Payment Failures" in warning for warning in response.warnings)


def test_product_pulse_can_surface_a_governed_segment_episode() -> None:
    response = ProactiveAnalyticsService(SegmentDatabase(), SQLValidator()).pulse()

    segment_items = [
        item
        for item in response.items
        if item.metric == "checkout_conversion" and item.segment == "Mobile / Safari / Paid Social"
    ]
    assert segment_items
    assert segment_items[0].dimension == "checkout_context"
    assert "Mobile / Safari / Paid Social" in segment_items[0].summary


def test_weekly_report_has_all_sections_and_markdown_export() -> None:
    proactive, database = service()
    report = proactive.weekly_report()
    assert report.type == "weekly_report"
    assert [section.key for section in report.sections] == [
        "growth",
        "activation",
        "engagement",
        "retention",
        "revenue",
    ]
    assert report.anomalies
    assert report.sql.validated is True
    markdown = proactive.to_markdown(report)
    assert "# ProductLens Weekly Product Report" in markdown
    assert "## Growth" in markdown
    assert "## Anomalies" in markdown
    assert "## Methodology" in markdown
    calls_after_first = database.calls
    cached_report = proactive.weekly_report()
    assert cached_report.model_dump(mode="json") == report.model_dump(mode="json")
    assert database.calls == calls_after_first


def test_weekly_report_provider_failure_falls_back_to_deterministic_prose() -> None:
    router = NarrativeRouter(error=True)
    database = FakeDatabase()
    report = ProactiveAnalyticsService(database, SQLValidator(), InsightService(router)).weekly_report()

    assert router.calls == 1
    assert report.metadata.provider == "deterministic"
    assert report.headline.endswith("strongest weekly signal")


def test_weekly_report_rejects_ungrounded_provider_numbers() -> None:
    router = NarrativeRouter(
        response=GroundedInsight(
            headline="Untrusted 999999 signal",
            summary="Untrusted 999999 signal.",
            findings=[],
            recommendations=[],
            follow_up_questions=["What changed?", "Where did it change?"],
            caveats=[],
        )
    )
    report = ProactiveAnalyticsService(FakeDatabase(), SQLValidator(), InsightService(router)).weekly_report()

    assert router.calls == 1
    assert report.metadata.provider == "deterministic-grounding-fallback"
    assert "999999" not in report.headline


def test_weekly_report_skips_provider_when_response_budget_is_low() -> None:
    router = NarrativeRouter(
        response=GroundedInsight(
            headline="Provider headline",
            summary="Provider summary.",
            findings=[],
            recommendations=[],
            follow_up_questions=["What changed?", "Where did it change?"],
            caveats=[],
        )
    )
    proactive = ProactiveAnalyticsService(FakeDatabase(), SQLValidator(), InsightService(router))
    proactive.REPORT_PROVIDER_RESERVE_MS = 60_000

    report = proactive.weekly_report()

    assert router.calls == 0
    assert report.metadata.provider == "deterministic-budget-fallback"
    assert any("provider prose was skipped" in warning for warning in report.warnings)
