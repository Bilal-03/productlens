from __future__ import annotations

import hashlib
import json
from typing import Any

from app.analytics.sql_compiler import compile_funnel, compile_metric, compile_retention_curve
from app.analytics.time_ranges import DATASET_AS_OF, default_comparison, resolve_period
from app.database.service import DatabaseService
from app.models.contracts import (
    AnalyticsRequest,
    FunnelRequest,
    RetentionAnalyticsResponse,
    RetentionRequest,
    RetentionWindow,
    SQLProposal,
)
from app.security.sql_validator import SQLValidator
from app.semantic.registry import registry


class AnalyticsService:
    def __init__(self, database: DatabaseService, validator: SQLValidator) -> None:
        self.database = database
        self.validator = validator

    def execute(self, proposal: SQLProposal) -> tuple[list[dict[str, Any]], str, float]:
        validation = self.validator.validate(proposal.query)
        if not validation.valid:
            raise ValueError("Trusted analytics SQL failed validation: " + "; ".join(validation.errors))
        rows, elapsed = self.database.execute_readonly(validation)
        return rows, validation.normalized_query or proposal.query, elapsed

    def metric(self, request: AnalyticsRequest) -> dict[str, Any]:
        cache_key = self._cache_key("metric", request.model_dump(mode="json"))
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return cached
        registry.validate_dimension(request.metric, request.dimension)
        current_period = resolve_period(request.period)
        previous_period = resolve_period(request.comparison) if request.comparison else default_comparison(request.period)
        current, current_sql, current_ms = self.execute(
            compile_metric(request.metric, current_period, request.dimension, request.filters)
        )
        previous: list[dict[str, Any]] = []
        previous_sql = ""
        previous_ms = 0.0
        if previous_period:
            previous, previous_sql, previous_ms = self.execute(
                compile_metric(request.metric, previous_period, request.dimension, request.filters)
            )
        payload = {
            "metric": registry.metric(request.metric).model_dump(),
            "current_period": current_period.model_dump(),
            "comparison_period": previous_period.model_dump() if previous_period else None,
            "dataset_as_of": DATASET_AS_OF.isoformat(),
            "current": current,
            "previous": previous,
            "sql": {"current": current_sql, "previous": previous_sql},
            "execution_ms": current_ms + previous_ms,
        }
        if dataset_version:
            self.database.cache_put(cache_key, dataset_version, payload, self.database.settings.result_cache_ttl_seconds)
        return payload

    def funnel(self, request: FunnelRequest) -> dict[str, Any]:
        cache_key = self._cache_key("funnel", request.model_dump(mode="json"))
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return cached
        period = resolve_period(request.period)
        rows, sql, elapsed = self.execute(
            compile_funnel(request.funnel, period, request.dimension, request.filters)
        )
        by_segment: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_segment.setdefault(str(row["segment"]), []).append(row)
        for stages in by_segment.values():
            first = float(stages[0]["users"]) if stages else 0
            previous = first
            for stage in stages:
                users = float(stage["users"])
                stage["stage_conversion"] = users / previous if previous else 0
                stage["overall_conversion"] = users / first if first else 0
                stage["drop_off"] = previous - users
                previous = users
        payload = {"funnel": request.funnel, "period": period.model_dump(), "dataset_as_of": DATASET_AS_OF.isoformat(), "segments": by_segment, "sql": sql, "execution_ms": elapsed}
        if dataset_version:
            self.database.cache_put(cache_key, dataset_version, payload, self.database.settings.result_cache_ttl_seconds)
        return payload

    def trend(self, request: AnalyticsRequest) -> dict[str, Any]:
        period = resolve_period(request.period)
        duration = (period.end - period.start).days
        step = 7 if duration > 45 else 1
        points: list[dict[str, Any]] = []
        sql_fragments: list[str] = []
        execution_ms = 0.0
        cursor = period.start
        while cursor < period.end:
            bucket_end = min(cursor.fromordinal(cursor.toordinal() + step), period.end)
            proposal_period = type(period)(start=cursor, end=bucket_end, label=cursor.isoformat())
            rows, sql, elapsed = self.execute(
                compile_metric(request.metric, proposal_period, request.dimension, request.filters)
            )
            row = rows[0] if rows else {"value": 0, "numerator": 0, "denominator": 0}
            points.append(
                {
                    "label": cursor.isoformat(),
                    "value": float(row.get("value") or 0),
                    "numerator": float(row.get("numerator") or 0),
                    "denominator": float(row.get("denominator") or 0),
                }
            )
            sql_fragments.append(sql)
            execution_ms += elapsed
            cursor = bucket_end
        return {
            "metric": registry.metric(request.metric).model_dump(),
            "period": period.model_dump(),
            "dataset_as_of": DATASET_AS_OF.isoformat(),
            "dimension": request.dimension,
            "points": points,
            "sql": sql_fragments,
            "execution_ms": execution_ms,
        }

    def retention(self, request: RetentionRequest) -> dict[str, Any]:
        cache_key = self._cache_key("retention", request.model_dump(mode="json"))
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return cached

        windows = sorted(set(request.windows))
        if not windows or any(day not in {1, 7, 30} for day in windows):
            raise ValueError("Retention windows must be selected from D1, D7, and D30")
        period = resolve_period(request.period)
        registry.validate_dimension("d30_retention", request.dimension)
        heatmap_proposal = compile_retention_curve(
            period,
            windows,
            request.cohort_type,
            dimension=None,
            filters=request.filters,
        )
        heatmap_rows, heatmap_sql, heatmap_ms = self.execute(heatmap_proposal)
        trend_rows = heatmap_rows
        trend_sql = heatmap_sql
        trend_ms = 0.0
        if request.dimension:
            trend_proposal = compile_retention_curve(
                period,
                windows,
                request.cohort_type,
                dimension=request.dimension,
                filters=request.filters,
            )
            trend_rows, trend_sql, trend_ms = self.execute(trend_proposal)

        window_labels = [f"D{day}" for day in windows]
        heatmap_map: dict[str, dict[str, Any]] = {}
        for row in heatmap_rows:
            bucket = self._date_label(row.get("bucket"))
            heatmap_map[bucket] = row
        y_labels = sorted(heatmap_map)
        matrix = [
            [self._optional_float(heatmap_map[bucket].get(f"d{day}")) for day in windows]
            for bucket in y_labels
        ]
        cohort_sizes = [int(float(heatmap_map[bucket].get("cohort_size") or 0)) for bucket in y_labels]

        points: list[dict[str, Any]] = []
        segments: set[str] = set()
        for row in trend_rows:
            bucket = self._date_label(row.get("bucket"))
            segment = str(row.get("segment") or "Unknown")
            segments.add(segment)
            for day, label in zip(windows, window_labels, strict=True):
                points.append(
                    {
                        "period": bucket,
                        "segment": segment,
                        "window": label,
                        "value": self._optional_float(row.get(f"d{day}")),
                    }
                )

        heatmap_validation = self.validator.validate(heatmap_proposal.query)
        payload_model = RetentionAnalyticsResponse(
            cohort_type=request.cohort_type,
            period=period,
            dataset_as_of=DATASET_AS_OF,
            dimension=request.dimension,
            windows=[
                RetentionWindow(day=day, label=f"D{day} Retention", metric=f"d{day}_retention")
                for day in windows
            ],
            heatmap={
                "x_labels": window_labels,
                "y_labels": y_labels,
                "matrix": matrix,
                "cohort_sizes": cohort_sizes,
            },
            time_series={
                "points": points,
                "segments": sorted(segments),
            },
            sql={
                "heatmap": heatmap_sql,
                "trend": trend_sql,
                "tables": heatmap_validation.tables,
                "metrics": [f"d{day}_retention" for day in windows],
                "validated": True,
            },
            execution_ms=heatmap_ms + trend_ms,
        )
        payload = payload_model.model_dump(mode="json")
        if dataset_version:
            self.database.cache_put(cache_key, dataset_version, payload, self.database.settings.result_cache_ttl_seconds)
        return payload

    @staticmethod
    def _date_label(value: Any) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        return None if value is None else float(value)

    @staticmethod
    def _cache_key(kind: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
