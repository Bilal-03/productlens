import pytest

from app.analytics.calculations import (
    SegmentRate,
    compare_values,
    confidence_level,
    rate_contributions,
)


def test_percentage_points_are_not_relative_change() -> None:
    result = compare_values(0.102, 0.125, "percentage", "Current")
    assert result.percentage_point_delta == pytest.approx(-0.023)
    assert round(result.relative_delta or 0, 3) == -0.184


def test_rate_contributions_sum_to_total_change() -> None:
    current = [SegmentRate("Mobile", 70, 1000), SegmentRate("Desktop", 130, 1000)]
    previous = [SegmentRate("Mobile", 110, 1000), SegmentRate("Desktop", 140, 1000)]
    drivers, evidence = rate_contributions("device", current, previous, -0.025)
    assert round(sum(item.contribution for item in drivers), 8) == -0.025
    assert drivers[0].segment == "Mobile"
    assert len(evidence) == 2


def test_confidence_rubric() -> None:
    assert confidence_level(1000, 900, 0.4) == "high"
    assert confidence_level(300, 300, 0.2) == "medium"
    assert confidence_level(50, 300, 0.8) == "low"
    assert confidence_level(1000, 1000, 0.8, grounded=False) == "low"
