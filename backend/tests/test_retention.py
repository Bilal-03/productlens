from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from app.analytics.service import AnalyticsService
from app.models.contracts import RetentionRequest
from app.security.sql_validator import SQLValidator


class FakeDatabase:
    settings = SimpleNamespace(result_cache_ttl_seconds=300)

    def dataset_version(self) -> str | None:
        return None

    def execute_readonly(self, validation: Any) -> tuple[list[dict[str, Any]], float]:
        return [
            {
                "bucket": date(2026, 7, 20),
                "segment": "All",
                "cohort_size": 100.0,
                "d1": 0.62,
                "d7": 0.34,
                "d30": None,
            },
            {
                "bucket": date(2026, 7, 27),
                "segment": "All",
                "cohort_size": 90.0,
                "d1": 0.58,
                "d7": 0.31,
                "d30": 0.18,
            },
        ], 2.5


def test_retention_response_contains_heatmap_and_long_time_series() -> None:
    service = AnalyticsService(FakeDatabase(), SQLValidator())  # type: ignore[arg-type]

    result = service.retention(RetentionRequest(period="last_90_days"))

    assert result["type"] == "retention_analysis"
    assert result["heatmap"]["x_labels"] == ["D1", "D7", "D30"]
    assert result["heatmap"]["y_labels"] == ["2026-07-20", "2026-07-27"]
    assert result["heatmap"]["matrix"][0] == [0.62, 0.34, None]
    assert result["heatmap"]["cohort_sizes"] == [100, 90]
    assert len(result["time_series"]["points"]) == 6
    assert result["time_series"]["points"][0]["window"] == "D1"
    assert result["sql"]["validated"] is True


def test_retention_rejects_non_governed_window() -> None:
    service = AnalyticsService(FakeDatabase(), SQLValidator())  # type: ignore[arg-type]

    try:
        service.retention(RetentionRequest(windows=[14]))
    except ValueError as exc:
        assert "D1, D7, and D30" in str(exc)
    else:
        raise AssertionError("unsupported retention window was accepted")

