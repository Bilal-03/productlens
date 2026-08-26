from datetime import date
from typing import Any

from app.analytics.service import AnalyticsService
from app.database.service import DatabaseUnavailable
from app.models.contracts import AnalyticsRequest, OverviewRequest


def test_overview_trend_uses_one_grouped_series_query_and_keeps_weekly_shape() -> None:
    service = AnalyticsService(object(), object())  # type: ignore[arg-type]
    executed: list[Any] = []

    def execute(proposal: Any) -> tuple[list[dict[str, Any]], str, float]:
        executed.append(proposal)
        return (
            [
                {"bucket": date(2026, 5, 26), "value": 10, "numerator": 10, "denominator": 2},
                {"bucket": date(2026, 6, 1), "value": 20, "numerator": 20, "denominator": 4},
            ],
            "SELECT grouped_series",
            4.0,
        )

    service.execute = execute  # type: ignore[method-assign]

    result = service.trend(AnalyticsRequest(metric="revenue", period="last_90_days"))

    assert len(executed) == 1
    assert len(result["points"]) == 13
    assert result["points"][0] == {
        "label": "2026-05-26",
        "value": 30.0,
        "numerator": 30.0,
        "denominator": 6.0,
    }
    assert result["sql"] == ["SELECT grouped_series"]


def test_overview_summary_skips_comparisons_and_returns_partial_kpis() -> None:
    service = AnalyticsService(object(), object())  # type: ignore[arg-type]
    service.database = type("Database", (), {"dataset_version": lambda self: None})()  # type: ignore[assignment]
    calls: list[tuple[str, bool, bool]] = []

    def metric(
        request: AnalyticsRequest,
        *,
        use_cache: bool,
        include_comparison: bool,
        use_daily_activity_rollup: bool,
    ) -> dict[str, Any]:
        calls.append((request.metric, use_cache, include_comparison))
        assert use_daily_activity_rollup is True
        if request.metric == "d30_retention":
            raise DatabaseUnavailable("retention timeout")
        return {
            "metric": {"label": request.metric, "format": "integer"},
            "current_period": {"label": "Last 30 Days"},
            "current": [{"value": 10}],
            "previous": [],
        }

    service.metric = metric  # type: ignore[method-assign]
    service._dataset_as_of = lambda: date(2026, 8, 24)  # type: ignore[method-assign]

    result = service.overview_summary(OverviewRequest(period="last_30_days"))

    assert set(result["kpis"]) == {"mau", "activation_rate", "checkout_conversion", "mrr", "churn_rate"}
    assert result["warnings"] == ["d30_retention: unavailable"]
    assert {use_cache for _, use_cache, _ in calls} == {False}
    assert {include_comparison for _, _, include_comparison in calls} == {False}
