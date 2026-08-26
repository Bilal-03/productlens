from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.analytics.experiments import ExperimentAnalyticsService
from app.models.contracts import ExperimentVariantResult, SQLValidation
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
        if "array_agg" in query:
            return [
                {
                    "experiment_key": "onboarding-redesign",
                    "name": "Onboarding redesign",
                    "hypothesis": "Reducing onboarding friction increases activation",
                    "primary_metric": "activation_rate",
                    "control_variant": "control",
                    "status": "completed",
                    "started_at": datetime(2026, 5, 1, tzinfo=UTC),
                    "ended_at": datetime(2026, 8, 24, tzinfo=UTC),
                    "variants": ["control", "variant"],
                }
            ], 1.0
        assert "onboarding_completed" in query
        return [
            {"variant": "control", "sample_size": 250, "conversions": 100, "conversion_rate": 0.4},
            {"variant": "variant", "sample_size": 250, "conversions": 150, "conversion_rate": 0.6},
        ], 1.0


def result(name: str, sample_size: int, conversions: int) -> ExperimentVariantResult:
    rate = conversions / sample_size if sample_size else None
    return ExperimentVariantResult(
        variant=name,
        is_control=name == "control",
        sample_size=sample_size,
        conversions=conversions,
        conversion_rate=rate,
        formatted_conversion_rate=f"{rate * 100:.1f}%" if rate is not None else "Unavailable",
    )


def test_experiment_analysis_calculates_uplift_significance_and_uses_dataset_cache() -> None:
    database = FakeDatabase()
    service = ExperimentAnalyticsService(database, SQLValidator())

    response = service.analysis("onboarding-redesign", "last_90_days")

    assert response.experiment.primary_metric == "activation_rate"
    assert [item.sample_size for item in response.variants] == [250, 250]
    comparison = response.comparisons[0]
    assert comparison.absolute_uplift == pytest.approx(0.2)
    assert comparison.relative_uplift == pytest.approx(0.5)
    assert comparison.confidence_interval_low is not None and comparison.confidence_interval_low > 0
    assert comparison.p_value is not None and comparison.p_value < 0.05
    assert comparison.statistically_significant is True
    assert database.calls == 2

    cached = service.analysis("onboarding-redesign", "last_90_days")
    assert cached.model_dump(mode="json") == response.model_dump(mode="json")
    assert database.calls == 2

    database.version = "dataset-v2"
    service.analysis("onboarding-redesign", "last_90_days")
    assert database.calls == 4


def test_experiment_significance_has_minimum_sample_and_zero_variance_guards() -> None:
    service = ExperimentAnalyticsService(FakeDatabase(), SQLValidator())

    underpowered = service._compare_pair(result("control", 99, 50), result("variant", 200, 150))
    assert underpowered.p_value is None
    assert underpowered.statistically_significant is False
    assert "at least 100" in underpowered.significance_note

    zero_rate = service._compare_pair(result("control", 100, 0), result("variant", 100, 0))
    assert zero_rate.p_value == 1.0
    assert zero_rate.confidence_interval_low == 0.0
    assert zero_rate.confidence_interval_high == 0.0
    assert zero_rate.statistically_significant is False


def test_experiment_analysis_rejects_invalid_periods_and_unknown_experiments() -> None:
    service = ExperimentAnalyticsService(FakeDatabase(), SQLValidator())

    with pytest.raises(ValueError, match="supports"):
        service.analysis("onboarding-redesign", "last_7_days")
    with pytest.raises(ValueError, match="Unknown experiment"):
        service.analysis("missing-experiment", "last_90_days")
