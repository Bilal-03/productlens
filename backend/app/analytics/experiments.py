from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, date, datetime
from typing import Any

from app.analytics.sql_compiler import compile_experiment_analysis, compile_experiments
from app.analytics.time_ranges import resolve_period, source_as_of
from app.database.service import DatabaseService
from app.models.contracts import (
    ExperimentAnalysisResponse,
    ExperimentComparison,
    ExperimentListResponse,
    ExperimentMethodology,
    ExperimentSummary,
    ExperimentVariantResult,
    ProactiveMetadata,
    ProactiveSQLTransparency,
)
from app.security.sql_validator import SQLValidator
from app.semantic.registry import registry


class ExperimentAnalyticsService:
    """Deterministic assignment-level experiment analysis.

    Experiment metadata and assignments are read through explicit analytics
    views. The service owns the statistical calculation, while the compiler
    owns every SQL shape and keeps arbitrary experiment SQL out of the API.
    """

    MINIMUM_SAMPLE_SIZE = 100
    ALPHA = 0.05
    CONFIDENCE_LEVEL = 0.95

    def __init__(
        self,
        database: DatabaseService,
        validator: SQLValidator,
        *,
        minimum_sample_size: int = MINIMUM_SAMPLE_SIZE,
    ) -> None:
        self.database = database
        self.validator = validator
        self.minimum_sample_size = max(1, minimum_sample_size)

    def list_experiments(self) -> ExperimentListResponse:
        started = time.perf_counter()
        as_of = source_as_of(self.database)
        dataset_version = self.database.dataset_version()
        cache_key = self._cache_key("experiment-list", {})
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return ExperimentListResponse.model_validate(cached)

        proposal = compile_experiments()
        rows, validation = self._execute(proposal)
        experiments = [self._summary_from_row(row) for row in rows]
        response = ExperimentListResponse(
            dataset_as_of=as_of,
            experiments=experiments,
            sql=ProactiveSQLTransparency(
                tables=validation.tables,
                metrics=[],
                query_count=1,
                validated=True,
            ),
            execution_ms=(time.perf_counter() - started) * 1000,
        )
        self._cache_response(cache_key, dataset_version, response.model_dump(mode="json"))
        return response

    def analysis(self, experiment_key: str, period_name: str = "last_90_days") -> ExperimentAnalysisResponse:
        if period_name not in {"last_week", "last_30_days", "last_90_days"}:
            raise ValueError("Experiment analysis supports last_week, last_30_days, or last_90_days")
        normalized_key = experiment_key.strip()
        if not normalized_key:
            raise ValueError("Experiment key is required")
        as_of = source_as_of(self.database)
        period = resolve_period(period_name, as_of)
        dataset_version = self.database.dataset_version()
        cache_key = self._cache_key(
            "experiment-analysis",
            {"experiment_key": normalized_key, "period": period_name},
        )
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return ExperimentAnalysisResponse.model_validate(cached)

        catalog = self.list_experiments()
        experiment = next(
            (item for item in catalog.experiments if item.experiment_key == normalized_key),
            None,
        )
        if experiment is None:
            raise ValueError(f"Unknown experiment: {normalized_key}")

        started = time.perf_counter()
        proposal = compile_experiment_analysis(
            experiment.experiment_key,
            period,
            experiment.primary_metric,
        )
        rows, validation = self._execute(proposal)
        by_variant = {str(row.get("variant")): row for row in rows}
        variants = [
            self._variant_result(experiment, variant, by_variant.get(variant))
            for variant in experiment.variants
        ]
        comparisons, warnings = self._comparisons(experiment, variants)
        if not rows:
            warnings.append("No assigned users or eligible observations were found for this period.")
        response = ExperimentAnalysisResponse(
            experiment=experiment,
            period=period,
            dataset_as_of=as_of,
            variants=variants,
            comparisons=comparisons,
            methodology=ExperimentMethodology(
                minimum_sample_size=self.minimum_sample_size,
                significance_test="Two-sided two-proportion z-test with a 95% normal-approximation confidence interval",
                conversion_definition=self._conversion_definition(experiment.primary_metric),
            ),
            sql=ProactiveSQLTransparency(
                tables=validation.tables,
                metrics=proposal.metrics_used,
                query_count=1,
                validated=True,
            ),
            warnings=warnings,
            metadata=ProactiveMetadata(
                generated_at=datetime.now(UTC),
                execution_ms=(time.perf_counter() - started) * 1000,
                source_id=getattr(self.database, "source_id", None),
                tenant_id=getattr(self.database, "tenant_id", None),
            ),
        )
        self._cache_response(cache_key, dataset_version, response.model_dump(mode="json"))
        return response

    def _execute(self, proposal: Any) -> tuple[list[dict[str, Any]], Any]:
        validation = self.validator.validate(proposal.query)
        if not validation.valid or not validation.normalized_query:
            raise ValueError("The governed experiment query did not pass validation")
        rows, _ = self.database.execute_readonly(validation)
        return rows, validation

    @staticmethod
    def _summary_from_row(row: dict[str, Any]) -> ExperimentSummary:
        primary_metric = str(row.get("primary_metric") or "")
        raw_variants = row.get("variants") or []
        variants = sorted({str(item) for item in raw_variants if item is not None})
        control_variant = str(row.get("control_variant") or "control")
        if control_variant not in variants:
            variants.insert(0, control_variant)
        return ExperimentSummary(
            experiment_key=str(row.get("experiment_key") or ""),
            name=str(row.get("name") or row.get("experiment_key") or "Experiment"),
            hypothesis=str(row.get("hypothesis") or ""),
            primary_metric=primary_metric,
            primary_metric_label=registry.metric(primary_metric).label,
            control_variant=control_variant,
            variants=variants,
            status=str(row.get("status") or "draft"),
            started_at=ExperimentAnalyticsService._as_date(row.get("started_at")),
            ended_at=(
                ExperimentAnalyticsService._as_date(row.get("ended_at"))
                if row.get("ended_at") is not None
                else None
            ),
        )

    def _variant_result(
        self,
        experiment: ExperimentSummary,
        variant: str,
        row: dict[str, Any] | None,
    ) -> ExperimentVariantResult:
        sample_size = int(float((row or {}).get("sample_size") or 0))
        conversions = int(float((row or {}).get("conversions") or 0))
        raw_rate = (row or {}).get("conversion_rate")
        rate = float(raw_rate) if raw_rate is not None else None
        return ExperimentVariantResult(
            variant=variant,
            is_control=variant == experiment.control_variant,
            sample_size=sample_size,
            conversions=conversions,
            conversion_rate=rate,
            formatted_conversion_rate=f"{rate * 100:.1f}%" if rate is not None else "Unavailable",
        )

    def _comparisons(
        self,
        experiment: ExperimentSummary,
        variants: list[ExperimentVariantResult],
    ) -> tuple[list[ExperimentComparison], list[str]]:
        control = next(
            (item for item in variants if item.variant == experiment.control_variant),
            None,
        )
        warnings: list[str] = []
        comparisons: list[ExperimentComparison] = []
        if control is None:
            return [], ["The configured control variant was not present in the assignment data."]
        for variant in variants:
            if variant.variant == experiment.control_variant:
                continue
            comparison = self._compare_pair(control, variant)
            comparisons.append(comparison)
            if not comparison.statistically_significant:
                warnings.append(
                    f"{variant.variant} does not meet the statistical significance policy; treat uplift as directional."
                )
        if len(variants) <= 1:
            warnings.append("Only the control variant is available for this experiment.")
        return comparisons, warnings

    def _compare_pair(
        self,
        control: ExperimentVariantResult,
        variant: ExperimentVariantResult,
    ) -> ExperimentComparison:
        control_rate = control.conversion_rate
        variant_rate = variant.conversion_rate
        enough_data = (
            control.sample_size >= self.minimum_sample_size
            and variant.sample_size >= self.minimum_sample_size
            and control_rate is not None
            and variant_rate is not None
        )
        if not enough_data:
            return ExperimentComparison(
                variant=variant.variant,
                control_variant=control.variant,
                control_sample_size=control.sample_size,
                variant_sample_size=variant.sample_size,
                control_conversion_rate=control.conversion_rate,
                variant_conversion_rate=variant.conversion_rate,
                absolute_uplift=self._delta(control, variant),
                relative_uplift=self._relative_delta(control, variant),
                confidence_interval_low=None,
                confidence_interval_high=None,
                p_value=None,
                statistically_significant=False,
                significance_note=f"Requires at least {self.minimum_sample_size:,} observations per variant.",
            )

        assert control_rate is not None and variant_rate is not None
        difference = variant_rate - control_rate
        pooled = (control.conversions + variant.conversions) / (control.sample_size + variant.sample_size)
        pooled_se = math.sqrt(
            max(0.0, pooled * (1 - pooled) * (1 / control.sample_size + 1 / variant.sample_size))
        )
        z_score = difference / pooled_se if pooled_se else 0.0
        p_value = math.erfc(abs(z_score) / math.sqrt(2)) if pooled_se else 1.0
        unpooled_se = math.sqrt(
            max(
                0.0,
                control_rate * (1 - control_rate) / control.sample_size
                + variant_rate * (1 - variant_rate) / variant.sample_size,
            )
        )
        margin = 1.96 * unpooled_se
        low, high = difference - margin, difference + margin
        significant = p_value < self.ALPHA
        return ExperimentComparison(
            variant=variant.variant,
            control_variant=control.variant,
            control_sample_size=control.sample_size,
            variant_sample_size=variant.sample_size,
            control_conversion_rate=control_rate,
            variant_conversion_rate=variant_rate,
            absolute_uplift=difference,
            relative_uplift=difference / abs(control_rate) if control_rate else None,
            confidence_interval_low=low,
            confidence_interval_high=high,
            p_value=p_value,
            statistically_significant=significant,
            significance_note=(
                "Statistically significant at alpha=0.05."
                if significant
                else "Not statistically significant at alpha=0.05; treat uplift as directional."
            ),
        )

    @staticmethod
    def _delta(control: ExperimentVariantResult, variant: ExperimentVariantResult) -> float | None:
        if control.conversion_rate is None or variant.conversion_rate is None:
            return None
        return variant.conversion_rate - control.conversion_rate

    @staticmethod
    def _relative_delta(control: ExperimentVariantResult, variant: ExperimentVariantResult) -> float | None:
        delta = ExperimentAnalyticsService._delta(control, variant)
        if delta is None or not control.conversion_rate:
            return None
        return delta / abs(control.conversion_rate)

    @staticmethod
    def _conversion_definition(metric: str) -> str:
        if metric == "activation_rate":
            return "Assigned users who complete signup and onboarding within seven days of signup"
        if metric == "checkout_conversion":
            return "Assigned sessions that reach payment success after checkout start"
        return "Assigned sessions with a payment submission that reach payment success"

    @staticmethod
    def _as_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    def _cache_response(
        self,
        cache_key: str,
        dataset_version: str | None,
        payload: dict[str, Any],
    ) -> None:
        if dataset_version:
            self.database.cache_put(
                cache_key,
                dataset_version,
                payload,
                self.database.settings.result_cache_ttl_seconds,
            )

    @staticmethod
    def _cache_key(kind: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"kind": kind, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
