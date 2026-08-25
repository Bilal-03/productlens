from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.contracts import ComparisonResult, Driver, Evidence, MetricPoint


def safe_relative_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous)


def format_value(value: float, format_name: str) -> str:
    if format_name == "percentage":
        return f"{value * 100:.1f}%"
    if format_name == "currency":
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def compare_values(
    current: float,
    previous: float | None,
    format_name: str,
    current_label: str,
    previous_label: str = "Previous period",
    current_numerator: float | None = None,
    current_denominator: float | None = None,
    previous_numerator: float | None = None,
    previous_denominator: float | None = None,
) -> ComparisonResult:
    current_point = MetricPoint(
        label=current_label,
        value=current,
        formatted=format_value(current, format_name),
        numerator=current_numerator,
        denominator=current_denominator,
    )
    if previous is None:
        return ComparisonResult(current=current_point)
    previous_point = MetricPoint(
        label=previous_label,
        value=previous,
        formatted=format_value(previous, format_name),
        numerator=previous_numerator,
        denominator=previous_denominator,
    )
    delta = current - previous
    return ComparisonResult(
        current=current_point,
        previous=previous_point,
        absolute_delta=delta,
        relative_delta=safe_relative_change(current, previous),
        percentage_point_delta=delta if format_name == "percentage" else None,
    )


@dataclass(frozen=True)
class SegmentRate:
    segment: str
    numerator: float
    denominator: float

    @property
    def rate(self) -> float:
        return self.numerator / self.denominator if self.denominator else 0.0


def rate_contributions(
    dimension: str,
    current: list[SegmentRate],
    previous: list[SegmentRate],
    total_change: float,
) -> tuple[list[Driver], list[Evidence]]:
    current_map = {item.segment: item for item in current}
    previous_map = {item.segment: item for item in previous}
    current_total = sum(item.denominator for item in current)
    previous_total = sum(item.denominator for item in previous)
    drivers: list[Driver] = []
    evidence: list[Evidence] = []
    for index, segment in enumerate(sorted(current_map.keys() | previous_map.keys())):
        cur = current_map.get(segment, SegmentRate(segment, 0, 0))
        prev = previous_map.get(segment, SegmentRate(segment, 0, 0))
        cur_weight = cur.denominator / current_total if current_total else 0
        prev_weight = prev.denominator / previous_total if previous_total else 0
        performance = cur_weight * (cur.rate - prev.rate)
        mix = prev.rate * (cur_weight - prev_weight)
        contribution = performance + mix
        evidence_id = f"driver-{dimension}-{index + 1}"
        evidence.append(
            Evidence(
                id=evidence_id,
                label=f"{segment} {dimension}",
                value=f"{prev.rate * 100:.1f}% → {cur.rate * 100:.1f}%",
                detail=f"{int(prev.denominator):,} previous and {int(cur.denominator):,} current entities",
            )
        )
        drivers.append(
            Driver(
                dimension=dimension,
                segment=segment,
                current_value=cur.rate,
                previous_value=prev.rate,
                contribution=contribution,
                share_of_change=contribution / total_change if total_change else None,
                performance_effect=performance,
                mix_effect=mix,
                sample_size=int(cur.denominator),
                evidence_ids=[evidence_id],
            )
        )
    drivers.sort(key=lambda item: abs(item.contribution), reverse=True)
    return drivers, evidence


def additive_contributions(
    dimension: str,
    current: dict[str, float],
    previous: dict[str, float],
) -> tuple[list[Driver], list[Evidence]]:
    total_change = sum(current.values()) - sum(previous.values())
    drivers: list[Driver] = []
    evidence: list[Evidence] = []
    for index, segment in enumerate(sorted(current.keys() | previous.keys())):
        cur = current.get(segment, 0.0)
        prev = previous.get(segment, 0.0)
        contribution = cur - prev
        evidence_id = f"driver-{dimension}-{index + 1}"
        evidence.append(Evidence(id=evidence_id, label=f"{segment} {dimension}", value=f"${prev:,.0f} → ${cur:,.0f}", detail=f"Contribution ${contribution:,.0f}"))
        drivers.append(
            Driver(
                dimension=dimension,
                segment=segment,
                current_value=cur,
                previous_value=prev,
                contribution=contribution,
                share_of_change=contribution / total_change if total_change else None,
                sample_size=0,
                evidence_ids=[evidence_id],
            )
        )
    drivers.sort(key=lambda item: abs(item.contribution), reverse=True)
    return drivers, evidence


def confidence_level(
    current_sample: float | None,
    previous_sample: float | None,
    top_driver_share: float | None,
    ambiguous: bool = False,
    grounded: bool = True,
) -> str:
    minimum = min(current_sample or 0, previous_sample or 0)
    dominance = abs(top_driver_share or 0)
    if ambiguous or not grounded or minimum < 100:
        return "low"
    if minimum >= 500 and dominance >= 0.30:
        return "high"
    return "medium"


def finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None

