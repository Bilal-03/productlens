from datetime import date, timedelta

from app.analytics.anomalies import AnomalyPolicy, collapse_anomaly_runs, detect_anomalies
from app.analytics.sql_compiler import (
    PROACTIVE_METRICS,
    PROACTIVE_SERIES_MAX_DAYS,
    compile_metric,
    compile_metric_series,
)
from app.models.contracts import DateRange, MetricSeriesPoint
from app.security.sql_validator import SQLValidator


def points(values: list[float], *, sample_size: int = 200) -> list[MetricSeriesPoint]:
    start = date(2026, 7, 1)
    return [
        MetricSeriesPoint(
            bucket=start + timedelta(days=index),
            value=value,
            numerator=value,
            denominator=sample_size,
        )
        for index, value in enumerate(values)
    ]


def test_detector_requires_both_change_and_z_score_gates() -> None:
    baseline = [100, 105, 98, 103, 101, 99, 104, 102] * 3 + [100, 101, 99, 102]
    detected = detect_anomalies(
        points([*baseline, 140]),
        metric="signups",
        kind="count",
    )
    assert len(detected) == 1
    assert detected[0].bucket == date(2026, 7, 29)
    assert detected[0].relative_delta > 0.15
    assert detected[0].z_score is not None

    below_change_threshold = detect_anomalies(
        points([*baseline, 110]),
        metric="signups",
        kind="count",
    )
    assert below_change_threshold == []


def test_detector_handles_zero_variance_and_sample_guards() -> None:
    policy = AnomalyPolicy(minimum_sample_size=100)
    detected = detect_anomalies(
        points([100] * 28 + [130]),
        metric="checkout_conversion",
        kind="rate",
        policy=policy,
    )
    assert len(detected) == 1
    assert detected[0].z_score is None
    assert detected[0].severity.value == "critical"

    too_small = detect_anomalies(
        points([100] * 28 + [130], sample_size=99),
        metric="checkout_conversion",
        kind="rate",
        policy=policy,
    )
    assert too_small == []

    zero_baseline = detect_anomalies(
        points([0] * 28 + [150]),
        metric="payment_failures",
        kind="count",
        policy=policy,
    )
    assert zero_baseline == []


def test_adjacent_flags_collapse_to_one_episode_with_peak() -> None:
    candidates = detect_anomalies(
        points([100] * 28 + [150, 160, 155]),
        metric="payment_failures",
        kind="count",
    )
    episodes = collapse_anomaly_runs(candidates)
    assert len(episodes) == 1
    start, end, peak = episodes[0]
    assert start == date(2026, 7, 29)
    assert end == date(2026, 8, 1)
    assert peak.bucket == date(2026, 7, 30)


def test_proactive_compilers_are_allowlisted_and_safe() -> None:
    validator = SQLValidator()
    period = DateRange(start=date(2026, 5, 1), end=date(2026, 8, 24), label="test")
    for metric in PROACTIVE_METRICS:
        proposal = compile_metric_series(metric, period)
        validation = validator.validate(proposal.query)
        assert validation.valid, (metric, validation.errors)
        assert "generate_series" not in proposal.query

    payment_failures = validator.validate(compile_metric("payment_failures", period).query)
    assert payment_failures.valid
    payment_failure_sql = compile_metric("payment_failures", period).query
    assert "checkout_started" in payment_failure_sql
    assert "payment_failed" in payment_failure_sql

    too_long = DateRange(
        start=date(2026, 1, 1),
        end=date(2026, 1, 1) + timedelta(days=PROACTIVE_SERIES_MAX_DAYS + 1),
        label="too long",
    )
    try:
        compile_metric_series("dau", too_long)
    except ValueError as exc:
        assert str(PROACTIVE_SERIES_MAX_DAYS) in str(exc)
    else:
        raise AssertionError("an unbounded proactive series was compiled")
