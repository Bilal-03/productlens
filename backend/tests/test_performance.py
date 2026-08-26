from datetime import date
from typing import Any

from app.analytics.service import AnalyticsService
from app.models.contracts import AnalyticsRequest


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
