from __future__ import annotations

import hashlib
import json
from typing import Any

from app.analytics.sql_compiler import (
    compile_acquisition,
    compile_funnel,
    compile_metric,
    compile_retention_curve,
)
from app.analytics.time_ranges import DATASET_AS_OF, default_comparison, resolve_period
from app.database.service import DatabaseService
from app.models.contracts import (
    AcquisitionAnalyticsResponse,
    AcquisitionRequest,
    AcquisitionSegment,
    AnalyticsRequest,
    FeatureAdoptionAnalyticsResponse,
    FeatureAdoptionRow,
    FunnelRequest,
    OverviewAnalyticsResponse,
    OverviewRequest,
    RetentionAnalyticsResponse,
    RetentionHeatmap,
    RetentionRequest,
    RetentionSQLTransparency,
    RetentionTimeSeries,
    RetentionTimeSeriesPoint,
    RetentionWindow,
    SQLProposal,
    SQLTransparency,
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
        if request.metric == "feature_adoption":
            return self.feature_adoption(request)
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

    def acquisition(self, request: AcquisitionRequest) -> dict[str, Any]:
        cache_key = self._cache_key("acquisition", request.model_dump(mode="json"))
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return cached
        period = resolve_period(request.period)
        comparison_period = resolve_period(request.comparison) if request.comparison else default_comparison(request.period)
        current_proposal = compile_acquisition(period, request.dimension, request.filters)
        current_rows, current_sql, current_ms = self.execute(current_proposal)
        previous_rows: list[dict[str, Any]] = []
        previous_sql = ""
        previous_ms = 0.0
        if comparison_period:
            previous_rows, previous_sql, previous_ms = self.execute(
                compile_acquisition(comparison_period, request.dimension, request.filters)
            )

        def normalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for row in rows:
                visitors = float(row.get("visitors") or 0)
                signups = float(row.get("signups") or 0)
                activated = float(row.get("activated_users") or 0)
                paid = float(row.get("paid_users") or 0)
                result.append(
                    AcquisitionSegment(
                        segment=str(row.get("segment") or "Unknown"),
                        visitors=visitors,
                        signups=signups,
                        activated_users=activated,
                        paid_users=paid,
                        signup_conversion=signups / visitors if visitors else 0,
                        activation_conversion=activated / signups if signups else 0,
                        paid_conversion=paid / signups if signups else 0,
                    ).model_dump(mode="json")
                )
            return result

        current_segments = normalize(current_rows)
        previous_segments = normalize(previous_rows)
        validation = self.validator.validate(current_proposal.query)
        payload = AcquisitionAnalyticsResponse(
            period=period,
            comparison_period=comparison_period,
            dataset_as_of=DATASET_AS_OF,
            dimension=request.dimension,
            segments=[AcquisitionSegment.model_validate(item) for item in current_segments],
            sql=SQLTransparency(
                query=current_sql + (f"\n\n-- Comparison\n{previous_sql}" if previous_sql else ""),
                purpose=current_proposal.purpose,
                tables=validation.tables,
                metrics=["visitors", "signups", "activated_users", "paid_users", "channel_conversion"],
                validated=True,
                row_count=len(current_rows) + len(previous_rows),
            ),
            execution_ms=current_ms + previous_ms,
            previous_segments=[AcquisitionSegment.model_validate(item) for item in previous_segments],
        ).model_dump(mode="json")
        if dataset_version:
            self.database.cache_put(cache_key, dataset_version, payload, self.database.settings.result_cache_ttl_seconds)
        return payload

    def feature_adoption(self, request: AnalyticsRequest) -> dict[str, Any]:
        if request.metric != "feature_adoption":
            raise ValueError("The feature-adoption endpoint requires the feature_adoption metric")
        cache_key = self._cache_key("feature_adoption", request.model_dump(mode="json"))
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return cached
        period = resolve_period(request.period)
        comparison_period = resolve_period(request.comparison) if request.comparison else default_comparison(request.period)
        current_proposal = compile_metric("feature_adoption", period, request.dimension or "feature", request.filters)
        current_rows, current_sql, current_ms = self.execute(current_proposal)
        previous_rows: list[dict[str, Any]] = []
        previous_sql = ""
        previous_ms = 0.0
        if comparison_period:
            previous_rows, previous_sql, previous_ms = self.execute(
                compile_metric("feature_adoption", comparison_period, request.dimension or "feature", request.filters)
            )

        def normalize(rows: list[dict[str, Any]]) -> list[FeatureAdoptionRow]:
            result: list[FeatureAdoptionRow] = []
            for row in rows:
                feature_user_d30_denominator = float(row.get("feature_d30_denominator") or 0)
                non_feature_d30_denominator = float(row.get("non_feature_d30_denominator") or 0)
                feature_d30 = (
                    float(row.get("feature_d30_numerator") or 0) / feature_user_d30_denominator
                    if feature_user_d30_denominator
                    else None
                )
                non_feature_d30 = (
                    float(row.get("non_feature_d30_numerator") or 0) / non_feature_d30_denominator
                    if non_feature_d30_denominator
                    else None
                )
                result.append(
                    FeatureAdoptionRow(
                        feature=str(row.get("segment") or "Other"),
                        eligible_users=float(row.get("eligible_users") or row.get("denominator") or 0),
                        adopting_users=float(row.get("adopting_users") or row.get("numerator") or 0),
                        adoption_rate=float(row.get("value") or 0),
                        total_uses=float(row.get("total_uses") or 0),
                        uses_per_adopter=float(row.get("uses_per_adopter") or 0),
                        feature_user_d30=feature_d30,
                        non_feature_user_d30=non_feature_d30,
                        feature_d30_sample_size=int(feature_user_d30_denominator),
                        non_feature_d30_sample_size=int(non_feature_d30_denominator),
                        association_delta=(feature_d30 - non_feature_d30) if feature_d30 is not None and non_feature_d30 is not None else None,
                    )
                )
            return result

        current = normalize(current_rows)
        previous = normalize(previous_rows)
        validation = self.validator.validate(current_proposal.query)
        payload = FeatureAdoptionAnalyticsResponse(
            period=period,
            comparison_period=comparison_period,
            dataset_as_of=DATASET_AS_OF,
            dimension=request.dimension or "feature",
            rows=current,
            sql=SQLTransparency(
                query=current_sql + (f"\n\n-- Comparison\n{previous_sql}" if previous_sql else ""),
                purpose=current_proposal.purpose,
                tables=validation.tables,
                metrics=["feature_adoption", "d30_retention"],
                validated=True,
                row_count=len(current_rows) + len(previous_rows),
            ),
            execution_ms=current_ms + previous_ms,
            previous_rows=previous,
        ).model_dump(mode="json")
        if dataset_version:
            self.database.cache_put(cache_key, dataset_version, payload, self.database.settings.result_cache_ttl_seconds)
        return payload

    def overview(self, request: OverviewRequest) -> dict[str, Any]:
        cache_key = self._cache_key("overview", request.model_dump(mode="json"))
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return cached
        period = resolve_period(request.period)
        comparison_period = default_comparison(request.period)
        kpi_period = request.period
        kpi_names = ["mau", "activation_rate", "checkout_conversion", "mrr", "d30_retention", "churn_rate"]
        kpis: dict[str, dict[str, Any]] = {}
        for metric_name in kpi_names:
            metric_period = "last_90_days" if metric_name == "d30_retention" else kpi_period
            kpis[metric_name] = self.metric(AnalyticsRequest(metric=metric_name, period=metric_period))
        acquisition = AcquisitionAnalyticsResponse.model_validate(
            self.acquisition(AcquisitionRequest(period=kpi_period, dimension="channel"))
        )
        activation_funnel = self.funnel(FunnelRequest(funnel="onboarding", period=kpi_period))
        retention_snapshot = RetentionAnalyticsResponse.model_validate(
            self.retention(RetentionRequest(period="last_90_days", windows=[1, 7, 30]))
        )
        revenue_trend = self.trend(AnalyticsRequest(metric="revenue", period="last_90_days"))
        user_growth_trend = self.trend(AnalyticsRequest(metric="signups", period="last_90_days"))
        payload = OverviewAnalyticsResponse(
            period=period,
            comparison_period=comparison_period,
            dataset_as_of=DATASET_AS_OF,
            kpis=kpis,
            revenue_trend=revenue_trend,
            user_growth_trend=user_growth_trend,
            acquisition=acquisition,
            activation_funnel=activation_funnel,
            retention_snapshot=retention_snapshot,
        ).model_dump(mode="json")
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
        comparison_period = resolve_period(request.comparison) if request.comparison else default_comparison(request.period)
        rows, sql, elapsed = self.execute(
            compile_funnel(request.funnel, period, request.dimension, request.filters)
        )
        previous_rows: list[dict[str, Any]] = []
        previous_sql = ""
        if comparison_period:
            previous_rows, previous_sql, previous_elapsed = self.execute(
                compile_funnel(request.funnel, comparison_period, request.dimension, request.filters)
            )
            elapsed += previous_elapsed

        def enrich(funnel_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
            by_segment: dict[str, list[dict[str, Any]]] = {}
            for row in funnel_rows:
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
            return by_segment

        payload = {
            "funnel": request.funnel,
            "period": period.model_dump(),
            "comparison_period": comparison_period.model_dump() if comparison_period else None,
            "dataset_as_of": DATASET_AS_OF.isoformat(),
            "segments": enrich(rows),
            "previous_segments": enrich(previous_rows) if previous_rows else {},
            "sql": sql + (f"\n\n-- Comparison\n{previous_sql}" if previous_sql else ""),
            "execution_ms": elapsed,
        }
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
            heatmap=RetentionHeatmap(
                x_labels=window_labels,
                y_labels=y_labels,
                matrix=matrix,
                cohort_sizes=cohort_sizes,
            ),
            time_series=RetentionTimeSeries(
                points=[RetentionTimeSeriesPoint.model_validate(point) for point in points],
                segments=sorted(segments),
            ),
            sql=RetentionSQLTransparency(
                heatmap=heatmap_sql,
                trend=trend_sql,
                tables=heatmap_validation.tables,
                metrics=[f"d{day}_retention" for day in windows],
                validated=True,
            ),
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
