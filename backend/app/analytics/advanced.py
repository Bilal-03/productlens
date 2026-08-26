from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from app.analytics.sql_compiler import (
    compile_churn_risk,
    compile_journeys,
    compile_revenue_cohorts,
    compile_stickiness,
)
from app.analytics.time_ranges import DATASET_AS_OF, resolve_period
from app.database.service import DatabaseService, DatabaseUnavailable
from app.models.contracts import (
    AdvancedAnalyticsResponse,
    AdvancedMethodology,
    ChurnRiskRow,
    JourneyPath,
    ProactiveMetadata,
    ProactiveSQLTransparency,
    RevenueCohortRow,
    StickinessPoint,
)
from app.security.sql_validator import SQLValidator


class AdvancedAnalyticsService:
    """Bounded, deterministic implementations of the first Phase 40 slice."""

    QUERY_WORKERS = 4
    RISK_DIMENSIONS = ("plan", "company_size", "channel")
    CACHE_VERSION = "advanced-analytics-v2"

    def __init__(self, database: DatabaseService, validator: SQLValidator) -> None:
        self.database = database
        self.validator = validator

    def report(self, period_name: str = "last_90_days") -> AdvancedAnalyticsResponse:
        if period_name not in {"last_30_days", "last_90_days"}:
            raise ValueError("Advanced analytics supports last_30_days or last_90_days")
        period = resolve_period(period_name)
        dataset_version = self.database.dataset_version()
        cache_key = self._cache_key(self.CACHE_VERSION, {"period": period_name})
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return AdvancedAnalyticsResponse.model_validate(cached)

        started = time.perf_counter()
        jobs: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=self.QUERY_WORKERS) as executor:
            for dimension in self.RISK_DIMENSIONS:
                jobs[f"risk:{dimension}"] = executor.submit(
                    self._execute,
                    compile_churn_risk(period, dimension),
                )
            jobs["journeys"] = executor.submit(self._execute, compile_journeys(period))
            jobs["stickiness"] = executor.submit(self._execute, compile_stickiness(period))
            jobs["revenue_cohorts"] = executor.submit(self._execute, compile_revenue_cohorts(period))

            results: dict[str, tuple[list[dict[str, Any]], Any, float, list[str]]] = {}
            warnings: list[str] = []
            for key in [*(f"risk:{dimension}" for dimension in self.RISK_DIMENSIONS), "journeys", "stickiness", "revenue_cohorts"]:
                try:
                    results[key] = jobs[key].result()
                except DatabaseUnavailable:
                    warnings.append(f"{key.replace(':', ' ')} was unavailable while advanced analytics were calculated.")
                except ValueError as exc:
                    warnings.append(str(exc))

        if not results:
            raise DatabaseUnavailable("The advanced analytics database is unavailable")

        risk_rows = [
            item
            for dimension in self.RISK_DIMENSIONS
            for item in self._risk_rows(dimension, results.get(f"risk:{dimension}", ([], None, 0))[0])
        ]
        journey_rows = self._journey_rows(results.get("journeys", ([], None, 0))[0])
        stickiness_rows = self._stickiness_rows(results.get("stickiness", ([], None, 0))[0])
        revenue_cohorts = self._revenue_cohort_rows(results.get("revenue_cohorts", ([], None, 0))[0])
        tables = sorted({table for _, validation, _, _ in results.values() for table in validation.tables})
        metrics = sorted({metric for _, _, _, used_metrics in results.values() for metric in used_metrics})
        response = AdvancedAnalyticsResponse(
            period=period,
            dataset_as_of=DATASET_AS_OF,
            churn_risk=risk_rows,
            journeys=journey_rows,
            stickiness=stickiness_rows,
            revenue_cohorts=revenue_cohorts,
            methodology=AdvancedMethodology(
                analysis_period=period,
                churn_definition="Cancellations during the period divided by subscriptions active at period start",
                recent_activity_window_days=30,
                journey_max_steps=5,
                power_user_definition="At least 10 distinct active days in a trailing 30-day window",
                ltv_definition="Observed net revenue per signed-up user through the period end; not a forecast",
                retention_caveat="Revenue cohorts are labeled immature until 30 days are observable; immature values are not treated as zero.",
            ),
            sql=ProactiveSQLTransparency(
                tables=tables,
                metrics=metrics,
                query_count=len(results),
                validated=all(validation.valid for _, validation, _, _ in results.values()),
            ),
            warnings=warnings,
            metadata=ProactiveMetadata(
                generated_at=datetime.now(UTC),
                execution_ms=(time.perf_counter() - started) * 1000,
            ),
        )
        self._cache_response(cache_key, dataset_version, response.model_dump(mode="json"))
        return response

    def _execute(self, proposal: Any) -> tuple[list[dict[str, Any]], Any, float, list[str]]:
        validation = self.validator.validate(proposal.query)
        if not validation.valid or not validation.normalized_query:
            raise ValueError(f"The governed advanced query did not pass validation: {proposal.purpose}")
        rows, elapsed = self.database.execute_readonly(validation)
        return rows, validation, elapsed, list(proposal.metrics_used)

    @staticmethod
    def _risk_rows(dimension: str, rows: list[dict[str, Any]]) -> list[ChurnRiskRow]:
        output: list[ChurnRiskRow] = []
        for row in rows:
            active = int(float(row.get("active_subscriptions") or 0))
            cancellations = int(float(row.get("cancellations") or 0))
            churn_rate = float(row["churn_rate"]) if row.get("churn_rate") is not None else None
            activity_rate = float(row["recent_activity_rate"]) if row.get("recent_activity_rate") is not None else None
            if active <= 0:
                risk_band = "unavailable"
            elif (churn_rate is not None and churn_rate >= 0.20) or (activity_rate is not None and activity_rate < 0.50):
                risk_band = "high"
            elif (churn_rate is not None and churn_rate >= 0.10) or (activity_rate is not None and activity_rate < 0.70):
                risk_band = "medium"
            else:
                risk_band = "low"
            output.append(
                ChurnRiskRow(
                    dimension=dimension,
                    segment=str(row.get("segment") or "Unknown"),
                    active_subscriptions=active,
                    cancellations=cancellations,
                    churn_rate=churn_rate,
                    recent_activity_rate=activity_rate,
                    risk_band=risk_band,
                )
            )
        return output

    @staticmethod
    def _journey_rows(rows: list[dict[str, Any]]) -> list[JourneyPath]:
        return [
            JourneyPath(
                path=str(row.get("path") or "Unknown"),
                users=int(float(row.get("users") or 0)),
                share=float(row.get("share") or 0),
            )
            for row in rows
        ]

    @staticmethod
    def _stickiness_rows(rows: list[dict[str, Any]]) -> list[StickinessPoint]:
        return [
            StickinessPoint(
                period=str(row.get("period") or ""),
                dau=int(float(row.get("dau") or 0)),
                wau=int(float(row.get("wau") or 0)),
                mau=int(float(row.get("mau") or 0)),
                dau_wau=float(row["dau_wau"]) if row.get("dau_wau") is not None else None,
                dau_mau=float(row["dau_mau"]) if row.get("dau_mau") is not None else None,
                power_users=int(float(row.get("power_users") or 0)),
            )
            for row in rows
        ]

    @staticmethod
    def _revenue_cohort_rows(rows: list[dict[str, Any]]) -> list[RevenueCohortRow]:
        output: list[RevenueCohortRow] = []
        for row in rows:
            cohort = str(row.get("cohort") or "")
            cohort_size = int(float(row.get("cohort_size") or 0))
            revenue = float(row.get("revenue") or 0)
            raw_mature = row.get("mature")
            mature = bool(raw_mature) if not isinstance(raw_mature, str) else raw_mature.lower() in {"true", "t"}
            output.append(
                RevenueCohortRow(
                    cohort=cohort,
                    cohort_size=cohort_size,
                    mature=mature,
                    revenue=revenue,
                    revenue_per_user=(float(row["revenue_per_user"]) if row.get("revenue_per_user") is not None else None),
                    active_revenue_users=int(float(row.get("active_revenue_users") or 0)),
                )
            )
        return output

    def _cache_response(self, cache_key: str, dataset_version: str | None, payload: dict[str, Any]) -> None:
        if dataset_version:
            self.database.cache_put(cache_key, dataset_version, payload, self.database.settings.result_cache_ttl_seconds)

    @staticmethod
    def _cache_key(kind: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
