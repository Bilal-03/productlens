from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.analytics.advanced import AdvancedAnalyticsService
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
        query = (validation.normalized_query or "").lower()
        if "dau_wau" in query:
            return [
                {
                    "period": "2026-08-23",
                    "dau": 80,
                    "wau": 160,
                    "mau": 400,
                    "dau_wau": 0.5,
                    "dau_mau": 0.2,
                    "power_users": 12,
                }
            ], 1.0
        if "revenue_per_user" in query:
            return [
                {
                    "cohort": "2026-08-01",
                    "cohort_size": 120,
                    "mature": "false",
                    "revenue": 2400,
                    "revenue_per_user": 20,
                    "active_revenue_users": 80,
                }
            ], 1.0
        if "array_to_string" in query:
            return [{"path": "signup_completed → onboarding_completed", "users": 42, "share": 0.7}], 1.0
        assert "active_subscriptions" in query
        return [
            {
                "segment": "Pro",
                "active_subscriptions": 100,
                "cancellations": 25,
                "churn_rate": 0.25,
                "recent_activity_rate": 0.4,
            }
        ], 1.0


class PartialDatabase(FakeDatabase):
    def execute_readonly(self, validation: SQLValidation) -> tuple[list[dict[str, Any]], float]:
        if "dau_wau" in (validation.normalized_query or "").lower():
            raise DatabaseUnavailable("stickiness unavailable")
        return super().execute_readonly(validation)


def test_advanced_report_returns_risk_journeys_stickiness_and_observed_ltv() -> None:
    database = FakeDatabase()
    service = AdvancedAnalyticsService(database, SQLValidator())

    response = service.report("last_90_days")

    assert response.type == "advanced_analytics"
    assert len(response.churn_risk) == 3
    assert all(row.risk_band == "high" for row in response.churn_risk)
    assert response.journeys[0].users == 42
    assert response.stickiness[0].dau_mau == pytest.approx(0.2)
    assert response.stickiness[0].power_users == 12
    assert response.revenue_cohorts[0].mature is False
    assert response.revenue_cohorts[0].revenue_per_user == pytest.approx(20)
    assert response.sql.validated is True
    assert response.sql.query_count == 6

    cached = service.report("last_90_days")
    assert cached.model_dump(mode="json") == response.model_dump(mode="json")
    assert database.calls == 6

    database.version = "dataset-v2"
    service.report("last_90_days")
    assert database.calls == 12


def test_advanced_report_keeps_partial_metric_failures_visible() -> None:
    response = AdvancedAnalyticsService(PartialDatabase(), SQLValidator()).report("last_30_days")

    assert response.stickiness == []
    assert any("stickiness" in warning for warning in response.warnings)
    assert response.journeys
    assert response.sql.query_count == 5


def test_advanced_report_rejects_unsupported_periods() -> None:
    with pytest.raises(ValueError, match="supports"):
        AdvancedAnalyticsService(FakeDatabase(), SQLValidator()).report("last_week")
