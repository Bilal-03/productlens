import pytest

from app.ai.insights import GroundedInsight
from app.ai.pipeline import CopilotPipeline
from app.analytics.calculations import (
    SegmentRate,
    additive_contributions,
    compare_values,
    confidence_level,
    rate_contributions,
)
from app.models.contracts import Evidence, Finding


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


def test_count_contributions_use_exact_segment_deltas() -> None:
    drivers, evidence = additive_contributions(
        "channel",
        {"Paid Social": 80, "Organic Search": 120},
        {"Paid Social": 100, "Organic Search": 110},
        "integer",
    )
    assert round(sum(item.contribution for item in drivers), 8) == -10
    paid = next(item for item in drivers if item.segment == "Paid Social")
    assert paid.contribution == -20
    assert paid.sample_size == 80
    assert next(item for item in evidence if item.id == paid.evidence_ids[0]).value == "100 → 80"


def test_confidence_rubric() -> None:
    assert confidence_level(1000, 900, 0.4) == "high"
    assert confidence_level(300, 300, 0.2) == "medium"
    assert confidence_level(50, 300, 0.8) == "low"
    assert confidence_level(1000, 1000, 0.8, grounded=False) == "low"


def test_diagnostic_findings_always_have_safe_categories() -> None:
    narrative = GroundedInsight(
        headline="Metric changed",
        summary="The metric changed.",
        findings=[Finding(kind="observed", text="The metric changed.", evidence_ids=["metric-change"])],
        recommendations=[],
        follow_up_questions=["What changed?", "Where did it change?"],
        caveats=[],
    )
    result = CopilotPipeline._ensure_diagnostic_findings(
        narrative,
        [Evidence(id="metric-change", label="Change", value="1", detail="1")],
    )
    assert {finding.kind for finding in result.findings} == {
        "observed",
        "likely_driver",
        "hypothesis",
        "recommended_investigation",
    }
