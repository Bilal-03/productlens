from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.models.contracts import AnomalyDirection, AnomalySeverity, MetricSeriesPoint


@dataclass(frozen=True)
class AnomalyPolicy:
    policy_version: str = "rolling-zscore-v1"
    baseline_days: int = 28
    minimum_baseline_points: int = 14
    minimum_sample_size: int = 100
    z_score_threshold: float = 2.0
    rate_change_threshold: float = 0.10
    count_change_threshold: float = 0.15
    critical_z_score: float = 3.0
    critical_change_multiplier: float = 2.0


@dataclass(frozen=True)
class AnomalyCandidate:
    metric: str
    kind: Literal["count", "rate", "additive"]
    bucket: date
    value: float
    baseline: float
    absolute_delta: float
    relative_delta: float
    numerator: float | None
    denominator: float | None
    z_score: float | None
    direction: AnomalyDirection
    severity: AnomalySeverity
    sample_size: int
    score: float
    dimension: str | None = None
    segment: str | None = None


def detect_anomalies(
    points: Sequence[MetricSeriesPoint],
    *,
    metric: str,
    kind: Literal["count", "rate", "additive"],
    policy: AnomalyPolicy | None = None,
) -> list[AnomalyCandidate]:
    selected_policy = policy or AnomalyPolicy()
    ordered = sorted(points, key=lambda item: item.bucket)
    candidates: list[AnomalyCandidate] = []
    for index, point in enumerate(ordered):
        if point.value is None or not math.isfinite(point.value):
            continue
        raw_sample_size: float | None = point.sample_size
        if raw_sample_size is None:
            raw_sample_size = point.denominator if point.denominator is not None else point.value
        if raw_sample_size is None or not math.isfinite(raw_sample_size):
            continue
        sample_size = int(raw_sample_size)
        if sample_size < selected_policy.minimum_sample_size:
            continue
        baseline_start = point.bucket - timedelta(days=selected_policy.baseline_days)
        baseline_values = [
            previous.value
            for previous in ordered[:index]
            if baseline_start <= previous.bucket < point.bucket
            and previous.value is not None
            and math.isfinite(previous.value)
        ]
        if len(baseline_values) < selected_policy.minimum_baseline_points:
            continue
        baseline = statistics.fmean(baseline_values)
        if not math.isfinite(baseline) or baseline == 0:
            continue
        absolute_delta = point.value - baseline
        relative_delta = absolute_delta / abs(baseline)
        change_threshold = (
            selected_policy.rate_change_threshold
            if kind == "rate"
            else selected_policy.count_change_threshold
        )
        if abs(relative_delta) < change_threshold:
            continue
        deviation = statistics.pstdev(baseline_values)
        if deviation == 0:
            z_score = None
            z_gate = True
            score = abs(relative_delta) / change_threshold
        else:
            z_score = absolute_delta / deviation
            z_gate = abs(z_score) >= selected_policy.z_score_threshold
            score = max(abs(z_score) / selected_policy.z_score_threshold, abs(relative_delta) / change_threshold)
        if not z_gate:
            continue
        severity = (
            AnomalySeverity.CRITICAL
            if (z_score is not None and abs(z_score) >= selected_policy.critical_z_score)
            or abs(relative_delta) >= change_threshold * selected_policy.critical_change_multiplier
            else AnomalySeverity.WARNING
        )
        candidates.append(
            AnomalyCandidate(
                metric=metric,
                kind=kind,
                bucket=point.bucket,
                value=point.value,
                baseline=baseline,
                absolute_delta=absolute_delta,
                relative_delta=relative_delta,
                numerator=point.numerator,
                denominator=point.denominator,
                z_score=z_score,
                direction=(
                    AnomalyDirection.INCREASE
                    if absolute_delta > 0
                    else AnomalyDirection.DECREASE
                ),
                severity=severity,
                sample_size=sample_size,
                score=score,
            )
        )
    return candidates


def collapse_anomaly_runs(candidates: Sequence[AnomalyCandidate]) -> list[tuple[date, date, AnomalyCandidate]]:
    """Collapse adjacent same-metric/same-direction flags into episodes."""

    ordered = sorted(candidates, key=lambda item: (item.metric, item.direction, item.bucket))
    episodes: list[tuple[date, date, AnomalyCandidate]] = []
    current: tuple[date, date, AnomalyCandidate] | None = None
    for candidate in ordered:
        if current is None:
            current = (candidate.bucket, candidate.bucket + timedelta(days=1), candidate)
            continue
        start, end, peak = current
        adjacent = candidate.bucket == end
        same_series = (
            candidate.metric == peak.metric
            and candidate.direction == peak.direction
            and candidate.dimension == peak.dimension
            and candidate.segment == peak.segment
        )
        if adjacent and same_series:
            current = (
                start,
                candidate.bucket + timedelta(days=1),
                candidate if candidate.score > peak.score else peak,
            )
        else:
            episodes.append(current)
            current = (candidate.bucket, candidate.bucket + timedelta(days=1), candidate)
    if current is not None:
        episodes.append(current)
    severity_rank = {AnomalySeverity.CRITICAL: 0, AnomalySeverity.WARNING: 1}
    episodes.sort(
        key=lambda item: (
            severity_rank[item[2].severity],
            -item[2].score,
            -item[1].toordinal(),
        )
    )
    return episodes
