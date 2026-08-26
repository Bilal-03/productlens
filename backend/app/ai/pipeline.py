from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from app.ai.insights import GroundedInsight, InsightService
from app.ai.planner import AdHocQuestion, AmbiguousQuestion, QuestionPlanner, UnsafeQuestion
from app.ai.providers import ProviderError
from app.ai.sql_generation import SQLGenerationResult, SQLGenerator
from app.analytics.calculations import (
    SegmentRate,
    additive_contributions,
    compare_values,
    confidence_level,
    rate_contributions,
)
from app.analytics.service import AnalyticsService
from app.analytics.sql_compiler import compile_metric
from app.analytics.time_ranges import DATASET_AS_OF
from app.config import Settings
from app.database.service import DatabaseService, DatabaseUnavailable
from app.models.contracts import (
    AnalysisMetadata,
    AnalysisResponse,
    ChartSpec,
    ClarificationResponse,
    ComparisonResult,
    CopilotRequest,
    DateRange,
    Driver,
    ErrorResponse,
    Evidence,
    Finding,
    Intent,
    Interpretation,
    MetricPoint,
    Recommendation,
    SQLTransparency,
    SQLValidation,
    Timings,
)
from app.security.session import hash_session
from app.security.sql_validator import SQLValidator
from app.semantic.registry import registry


class CopilotPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        database: DatabaseService,
        analytics: AnalyticsService,
        planner: QuestionPlanner,
        validator: SQLValidator,
        insights: InsightService,
        sql_generator: SQLGenerator | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.analytics = analytics
        self.planner = planner
        self.validator = validator
        self.insights = insights
        self.sql_generator = sql_generator

    def analyze(self, request: CopilotRequest) -> AnalysisResponse | ClarificationResponse | ErrorResponse:
        started = time.perf_counter()
        query_id = uuid4()
        session_hash = hash_session(request.session_id, self.settings.session_hmac_secret.get_secret_value())
        try:
            if not self.database.consume_quota(
                session_hash,
                self.settings.ai_requests_per_session_hour,
                self.settings.ai_requests_global_day,
            ):
                return ErrorResponse(
                    code="RATE_LIMITED",
                    message="The public demo's analysis quota is temporarily exhausted. Try again later.",
                    retryable=True,
                    query_id=str(query_id),
                )
        except DatabaseUnavailable:
            return ErrorResponse(
                code="DATABASE_UNAVAILABLE",
                message="The demo database is unavailable or paused. Please try again shortly.",
                retryable=True,
                query_id=str(query_id),
            )

        planner_started = time.perf_counter()
        try:
            plan = self.planner.plan(request.question, request.selected_metric)
        except UnsafeQuestion:
            validation = self.validator.validate("DROP TABLE analytics.users")
            self._safe_audit(query_id, session_hash, request.question, None, validation, "rejected", None, None, "UNSAFE_REQUEST")
            return ErrorResponse(
                code="UNSAFE_REQUEST",
                message="This request contains an unsupported database operation. ProductLens only performs read-only analysis.",
                retryable=False,
                query_id=str(query_id),
            )
        if isinstance(plan, AmbiguousQuestion):
            return ClarificationResponse(question=request.question, reason=plan.reason, options=plan.options)
        planner_ms = (time.perf_counter() - planner_started) * 1000

        if isinstance(plan, AdHocQuestion):
            return self._analyze_ad_hoc(
                request=request,
                query_id=query_id,
                session_hash=session_hash,
                started=started,
                planner_ms=planner_ms,
            )

        definition = registry.metric(plan.metric)
        current_proposal = compile_metric(plan.metric, plan.time_range, filters=plan.filters)
        current_validation = self.validator.validate(current_proposal.query)
        if not current_validation.valid:
            self._safe_audit(query_id, session_hash, request.question, current_proposal.query, current_validation, None, None, None, "SQL_VALIDATION_FAILED")
            return ErrorResponse(code="SQL_VALIDATION_FAILED", message="The analytical query did not pass safety validation.", retryable=False, query_id=str(query_id))

        try:
            current_rows, current_sql, current_ms = self.analytics.execute(current_proposal)
            previous_rows: list[dict[str, Any]] = []
            previous_sql = ""
            previous_ms = 0.0
            if plan.comparison:
                previous_rows, previous_sql, previous_ms = self.analytics.execute(
                    compile_metric(plan.metric, plan.comparison, filters=plan.filters)
                )
        except (DatabaseUnavailable, ValueError):
            self._safe_audit(query_id, session_hash, request.question, current_proposal.query, current_validation, "failed", None, None, "QUERY_EXECUTION_FAILED")
            return ErrorResponse(code="QUERY_EXECUTION_FAILED", message="The validated analysis could not be completed.", retryable=True, query_id=str(query_id))

        current = self._first(current_rows)
        previous = self._first(previous_rows) if previous_rows else None
        comparison = compare_values(
            current=float(current.get("value") or 0),
            previous=float(previous.get("value") or 0) if previous else None,
            format_name=definition.format,
            current_label=plan.time_range.label,
            previous_label=plan.comparison.label if plan.comparison else "Previous period",
            current_numerator=float(current.get("numerator") or 0),
            current_denominator=float(current.get("denominator") or 0),
            previous_numerator=float(previous.get("numerator") or 0) if previous else None,
            previous_denominator=float(previous.get("denominator") or 0) if previous else None,
        )
        evidence = [self._comparison_evidence(definition.label, comparison)]
        drivers: list[Driver] = []
        driver_rows: list[dict[str, Any]] = []
        dimension_limit = 6 if request.mode.value == "deep" else 1
        for dimension in plan.dimensions[:dimension_limit]:
            if not plan.comparison:
                break
            try:
                cur_segments, _, seg_current_ms = self.analytics.execute(
                    compile_metric(plan.metric, plan.time_range, dimension, plan.filters)
                )
                prev_segments, _, seg_previous_ms = self.analytics.execute(
                    compile_metric(plan.metric, plan.comparison, dimension, plan.filters)
                )
                current_ms += seg_current_ms
                previous_ms += seg_previous_ms
                new_drivers, new_evidence = self._drivers(
                    definition.kind,
                    dimension,
                    cur_segments,
                    prev_segments,
                    comparison,
                    definition.format,
                )
                drivers.extend(new_drivers[:5])
                evidence.extend(new_evidence)
                if not driver_rows:
                    driver_rows = cur_segments
            except (ValueError, DatabaseUnavailable):
                continue
        drivers.sort(key=lambda item: (abs(item.contribution), item.sample_size), reverse=True)
        primary_driver = drivers[0] if drivers else None
        deterministic = self._deterministic_insight(
            request.question,
            definition.label,
            comparison,
            evidence,
            primary_driver,
            diagnostic=plan.intent == Intent.DIAGNOSTIC,
        )
        interpretation_started = time.perf_counter()
        narrative, provider, grounded = self.insights.interpret(
            question=request.question,
            metric_label=definition.label,
            evidence=evidence,
            deterministic=deterministic,
        )
        if plan.intent == Intent.DIAGNOSTIC:
            narrative = self._ensure_diagnostic_findings(narrative, evidence)
        # Grounding is part of the confidence contract: a large sample cannot
        # produce a high-confidence answer when the model narrative failed its
        # evidence-ID/numeric grounding checks.
        confidence = confidence_level(
            comparison.current.denominator,
            comparison.previous.denominator if comparison.previous else None,
            primary_driver.share_of_change if primary_driver else None,
            grounded=grounded,
        )
        interpretation_ms = (time.perf_counter() - interpretation_started) * 1000
        chart = self._chart(
            definition.label,
            comparison,
            driver_rows,
            plan.dimensions[0] if plan.dimensions else None,
            plan.intent,
        )
        total_ms = (time.perf_counter() - started) * 1000
        timings = Timings(
            total_ms=total_ms,
            planner_ms=planner_ms,
            sql_ms=0,
            execution_ms=current_ms + previous_ms,
            analysis_ms=max(0, total_ms - planner_ms - current_ms - previous_ms - interpretation_ms),
            interpretation_ms=interpretation_ms,
        )
        result = AnalysisResponse(
            question=request.question,
            mode=request.mode,
            headline=narrative.headline,
            summary=narrative.summary,
            interpretation=Interpretation(
                intent=plan.intent,
                metric=plan.metric,
                metric_label=definition.label,
                metric_definition=definition.description,
                current_period=plan.time_range,
                comparison_period=plan.comparison,
                dimensions=plan.dimensions,
                assumptions=plan.assumptions,
            ),
            comparison=comparison,
            chart=chart,
            findings=narrative.findings,
            drivers=drivers[:10],
            evidence=evidence,
            recommendations=narrative.recommendations,
            follow_up_questions=narrative.follow_up_questions,
            investigation_trace=self._trace(plan.dimensions[:dimension_limit], bool(drivers)),
            sql=SQLTransparency(
                query=current_sql + (f"\n\n-- Comparison\n{previous_sql}" if previous_sql else ""),
                purpose=current_proposal.purpose,
                tables=current_validation.tables,
                metrics=[plan.metric],
                validated=True,
                row_count=len(current_rows) + len(previous_rows),
            ),
            caveats=narrative.caveats + ([] if grounded else ["Model narrative failed grounding checks; deterministic wording was used."]),
            metadata=AnalysisMetadata(
                query_id=str(query_id),
                generated_at=datetime.now(UTC),
                dataset_as_of=DATASET_AS_OF,
                provider=provider,
                confidence=confidence,
                timings=timings,
                model=self.insights.last_usage.model if self.insights.last_usage else None,
                input_tokens=self.insights.last_usage.input_tokens if self.insights.last_usage else None,
                output_tokens=self.insights.last_usage.output_tokens if self.insights.last_usage else None,
            ),
        )
        self._safe_audit(
            query_id,
            session_hash,
            request.question,
            current_sql,
            current_validation,
            "success",
            current_ms + previous_ms,
            result.sql.row_count,
            None,
            provider=provider,
            model=self.insights.last_usage.model if self.insights.last_usage else None,
            input_tokens=self.insights.last_usage.input_tokens if self.insights.last_usage else None,
            output_tokens=self.insights.last_usage.output_tokens if self.insights.last_usage else None,
        )
        self._safe_history(query_id, session_hash, request, result)
        return result

    def _analyze_ad_hoc(
        self,
        *,
        request: CopilotRequest,
        query_id: UUID,
        session_hash: str,
        started: float,
        planner_ms: float,
    ) -> AnalysisResponse | ErrorResponse:
        sql_started = time.perf_counter()
        if self.sql_generator is None or not self.sql_generator.available:
            validation = SQLValidation(
                valid=False,
                errors=["No structured SQL provider is configured"],
                failure_kind="syntax",
            )
            self._safe_audit(
                query_id,
                session_hash,
                request.question,
                None,
                validation,
                "rejected",
                None,
                None,
                "LLM_UNAVAILABLE",
            )
            return ErrorResponse(
                code="LLM_UNAVAILABLE",
                message="This question needs the structured SQL provider, which is unavailable right now.",
                retryable=True,
                query_id=str(query_id),
            )

        try:
            generated = self.sql_generator.generate(request.question)
        except ProviderError:
            validation = SQLValidation(
                valid=False,
                errors=["Structured SQL generation failed"],
                failure_kind="syntax",
            )
            self._safe_audit(
                query_id,
                session_hash,
                request.question,
                None,
                validation,
                "failed",
                None,
                None,
                "LLM_UNAVAILABLE",
            )
            return ErrorResponse(
                code="LLM_UNAVAILABLE",
                message="The structured SQL provider could not complete this request. Please retry.",
                retryable=True,
                query_id=str(query_id),
            )

        sql_ms = (time.perf_counter() - sql_started) * 1000
        self._audit_sql_attempts(query_id, session_hash, request.question, generated)
        if generated.proposal is None or not generated.validation.valid:
            code = generated.error_code or "SQL_GENERATION_FAILED"
            self._safe_audit(
                query_id,
                session_hash,
                request.question,
                generated.repair_query or generated.initial_query,
                generated.validation,
                "rejected",
                None,
                None,
                code,
            )
            return ErrorResponse(
                code=code,
                message=(
                    "The generated query did not pass the read-only safety boundary."
                    if code == "UNSAFE_SQL"
                    else "The structured SQL repair provider was unavailable. Please retry."
                    if code == "LLM_UNAVAILABLE"
                    else "The generated query could not be validated after one safe repair attempt."
                ),
                retryable=code != "UNSAFE_SQL",
                query_id=str(query_id),
            )

        try:
            rows, sql, execution_ms = self.analytics.execute(generated.proposal)
        except (DatabaseUnavailable, ValueError):
            self._safe_audit(
                query_id,
                session_hash,
                request.question,
                generated.proposal.query,
                generated.validation,
                "failed",
                None,
                None,
                "QUERY_EXECUTION_FAILED",
            )
            return ErrorResponse(
                code="QUERY_EXECUTION_FAILED",
                message="The validated ad-hoc query could not be completed.",
                retryable=True,
                query_id=str(query_id),
            )

        result = self._ad_hoc_response(
            request=request,
            query_id=query_id,
            generated=generated,
            rows=rows,
            sql=sql,
            planner_ms=planner_ms,
            sql_ms=sql_ms,
            execution_ms=execution_ms,
            started=started,
        )
        self._safe_audit(
            query_id,
            session_hash,
            request.question,
            sql,
            generated.validation,
            "success",
            execution_ms,
            len(rows),
            None,
            provider=generated.provider,
            model=generated.usage.model if generated.usage else None,
            input_tokens=generated.usage.input_tokens if generated.usage else None,
            output_tokens=generated.usage.output_tokens if generated.usage else None,
        )
        self._safe_history(query_id, session_hash, request, result)
        return result

    def _audit_sql_attempts(
        self,
        query_id: UUID,
        session_hash: str,
        question: str,
        generated: SQLGenerationResult,
    ) -> None:
        if generated.initial_query:
            self._safe_audit(
                query_id,
                session_hash,
                question,
                generated.initial_query,
                generated.initial_validation or generated.validation,
                "generated",
                None,
                None,
                "SQL_GENERATED",
                provider=generated.provider,
                model=generated.usage.model if generated.usage else None,
                input_tokens=generated.usage.input_tokens if generated.usage else None,
                output_tokens=generated.usage.output_tokens if generated.usage else None,
            )
        if generated.repaired:
            self._safe_audit(
                query_id,
                session_hash,
                question,
                generated.repair_query,
                generated.validation,
                "repair_attempted",
                None,
                None,
                "SQL_REPAIR_ATTEMPT",
                provider=generated.provider,
                model=generated.usage.model if generated.usage else None,
                input_tokens=generated.usage.input_tokens if generated.usage else None,
                output_tokens=generated.usage.output_tokens if generated.usage else None,
            )

    def _ad_hoc_response(
        self,
        *,
        request: CopilotRequest,
        query_id: UUID,
        generated: SQLGenerationResult,
        rows: list[dict[str, Any]],
        sql: str,
        planner_ms: float,
        sql_ms: float,
        execution_ms: float,
        started: float,
    ) -> AnalysisResponse:
        row_count = len(rows)
        proposal = generated.proposal
        if proposal is None:
            raise ValueError("An ad-hoc response requires a validated SQL proposal")
        period = DateRange(
            start=DATASET_AS_OF - timedelta(days=30),
            end=DATASET_AS_OF,
            label="Query-defined period",
        )
        point = MetricPoint(
            label="Validated query result",
            value=float(row_count),
            formatted=f"{row_count:,} rows",
            numerator=float(row_count),
            denominator=float(row_count),
        )
        evidence = [
            Evidence(
                id="ad-hoc-row-count",
                label="Rows returned",
                value=f"{row_count:,}",
                detail="The validated read-only query returned this many rows after the safety row cap.",
            )
        ]
        finding = Finding(
            kind="observed",
            text=f"The validated read-only query returned {row_count:,} rows.",
            evidence_ids=["ad-hoc-row-count"],
        )
        recommendation = Recommendation(
            priority="medium",
            action="Use the returned table as the starting point for a governed follow-up question.",
            expected_impact="Keeps the next interpretation tied to a defined metric and evidence set.",
            evidence_ids=["ad-hoc-row-count"],
            how_to_validate="Ask a follow-up that names the metric, period, and approved dimension explicitly.",
        )
        chart_rows = [
            {str(key): self._json_value(value) for key, value in row.items()}
            for row in rows[:100]
        ]
        total_ms = (time.perf_counter() - started) * 1000
        return AnalysisResponse(
            question=request.question,
            mode=request.mode,
            headline=f"Ad-hoc query returned {row_count:,} rows",
            summary="A structured read-only SQL query was generated, validated, and executed against the approved analytics views.",
            interpretation=Interpretation(
                intent=Intent.KPI,
                metric="ad_hoc",
                metric_label="Ad-hoc query result",
                metric_definition="A read-only query over the approved, PII-free analytics catalog.",
                current_period=period,
                comparison_period=None,
                dimensions=[],
                assumptions=[
                    "The generated SQL defines its own filters and date semantics.",
                    "Only approved analytics views and visible columns were available to the generator.",
                ],
            ),
            comparison=ComparisonResult(current=point),
            chart=ChartSpec(
                chart_type="table",
                title=proposal.purpose,
                data=chart_rows,
                description="Table of the first 100 rows from the validated query result.",
            ),
            findings=[finding],
            drivers=[],
            evidence=evidence,
            recommendations=[recommendation],
            follow_up_questions=[
                "Which governed metric should we calculate from this result?",
                "Should this result be broken down by an approved dimension?",
            ],
            investigation_trace=[
                "Classified the question as outside governed templates",
                "Retrieved only relevant approved schema context",
                f"Generated structured SQL ({generated.attempts} attempt(s))",
                "AST-validated the query and applied the read-only row cap",
                "Executed in a read-only transaction",
            ],
            sql=SQLTransparency(
                query=sql,
                purpose=proposal.purpose,
                tables=generated.validation.tables,
                metrics=proposal.metrics_used,
                validated=True,
                row_count=row_count,
            ),
            caveats=[
                "Ad-hoc results are exploratory and do not replace governed metric definitions.",
                "The displayed table is capped at the first 100 rows; the execution cap is 5,000 rows.",
            ],
            metadata=AnalysisMetadata(
                query_id=str(query_id),
                generated_at=datetime.now(UTC),
                dataset_as_of=DATASET_AS_OF,
                provider=generated.provider,
                confidence="low",
                timings=Timings(
                    total_ms=total_ms,
                    planner_ms=planner_ms,
                    sql_ms=sql_ms,
                    execution_ms=execution_ms,
                    analysis_ms=max(0, total_ms - planner_ms - sql_ms - execution_ms),
                    interpretation_ms=0,
                ),
                model=generated.usage.model if generated.usage else None,
                input_tokens=generated.usage.input_tokens if generated.usage else None,
                output_tokens=generated.usage.output_tokens if generated.usage else None,
            ),
        )

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    @staticmethod
    def _first(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return rows[0] if rows else {"value": 0, "numerator": 0, "denominator": 0}

    @staticmethod
    def _comparison_evidence(label: str, comparison: ComparisonResult) -> Evidence:
        if comparison.previous:
            relative = comparison.relative_delta * 100 if comparison.relative_delta is not None else 0
            detail = f"{comparison.previous.formatted} in the comparison period; {relative:+.1f}% relative change"
        else:
            detail = "No comparison period was requested"
        return Evidence(id="metric-change", label=label, value=comparison.current.formatted, detail=detail)

    @staticmethod
    def _drivers(
        kind: str,
        dimension: str,
        current: list[dict[str, Any]],
        previous: list[dict[str, Any]],
        comparison: ComparisonResult,
        format_name: str = "currency",
    ) -> tuple[list[Driver], list[Evidence]]:
        if kind in {"additive", "count"}:
            return additive_contributions(
                dimension,
                {str(row["segment"]): float(row.get("value") or 0) for row in current},
                {str(row["segment"]): float(row.get("value") or 0) for row in previous},
                format_name,
            )
        current_rates = [SegmentRate(str(row["segment"]), float(row.get("numerator") or 0), float(row.get("denominator") or 0)) for row in current]
        previous_rates = [SegmentRate(str(row["segment"]), float(row.get("numerator") or 0), float(row.get("denominator") or 0)) for row in previous]
        return rate_contributions(dimension, current_rates, previous_rates, float(comparison.absolute_delta or 0))

    @staticmethod
    def _deterministic_insight(
        question: str,
        label: str,
        comparison: ComparisonResult,
        evidence: list[Evidence],
        driver: Driver | None,
        *,
        diagnostic: bool = False,
    ) -> GroundedInsight:
        if comparison.previous:
            relative = (comparison.relative_delta or 0) * 100
            direction = "increased" if (comparison.absolute_delta or 0) >= 0 else "decreased"
            headline = f"{label} {direction} {abs(relative):.1f}%"
            summary = f"{label} moved from {comparison.previous.formatted} to {comparison.current.formatted}."
        else:
            headline = f"{label} is {comparison.current.formatted}"
            summary = f"The governed {label} value for the selected period is {comparison.current.formatted}."
        findings = [Finding(kind="observed", text=summary, evidence_ids=["metric-change"])]
        recommendations: list[Recommendation] = []
        if driver:
            findings.extend([
                Finding(kind="likely_driver", text=f"{driver.segment} was the strongest observed {driver.dimension} contributor.", evidence_ids=driver.evidence_ids),
                Finding(kind="hypothesis", text="The concentration is consistent with a segment-specific product or payment issue, but observational data cannot establish causation.", evidence_ids=driver.evidence_ids),
                Finding(kind="recommended_investigation", text=f"Inspect {driver.segment} telemetry and failure details around the first day of the change.", evidence_ids=driver.evidence_ids),
            ])
            recommendations.append(Recommendation(priority="high", action=f"Investigate the {driver.segment} {driver.dimension} segment first", expected_impact="Addresses the largest measured contributor before broader changes", evidence_ids=driver.evidence_ids, how_to_validate="Compare event errors, payment failure reasons, and session behavior before and after the change"))
        else:
            recommendations.append(Recommendation(priority="medium", action="Continue monitoring the governed metric", expected_impact="Confirms whether the observed level persists", evidence_ids=["metric-change"], how_to_validate="Re-run the same comparison after the next complete period"))
            if diagnostic:
                findings.extend(
                    [
                        Finding(kind="likely_driver", text="No single segment met the supported dominance threshold; the change is distributed across the inspected dimensions.", evidence_ids=["metric-change"]),
                        Finding(kind="hypothesis", text="The distributed pattern may reflect a mix of smaller product or payment issues, but observational data cannot establish causation.", evidence_ids=["metric-change"]),
                        Finding(kind="recommended_investigation", text="Inspect the highest-volume segments and failure details around the first day of the change.", evidence_ids=["metric-change"]),
                    ]
                )
        return GroundedInsight(
            headline=headline,
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            follow_up_questions=[f"When did {label.lower()} begin to change?", f"How does {label.lower()} differ by channel?", "Which segment contributed most?"],
            caveats=["Results use synthetic data anchored to 2026-08-24 UTC.", "Segment relationships are observational and do not establish causality."],
        )

    @staticmethod
    def _ensure_diagnostic_findings(narrative: GroundedInsight, evidence: list[Evidence]) -> GroundedInsight:
        """Ensure every diagnostic response exposes the four decision-safe finding kinds."""

        present = {finding.kind for finding in narrative.findings}
        fallback_evidence = [evidence[0].id] if evidence else []
        missing: dict[Literal["observed", "likely_driver", "hypothesis", "recommended_investigation"], str] = {
            "observed": "The resolved metric and comparison are the observed result.",
            "likely_driver": "No additional dominant driver was supported by the available evidence.",
            "hypothesis": "The observed pattern is a hypothesis for investigation, not a causal conclusion.",
            "recommended_investigation": "Inspect the highest-volume segments and relevant event or payment details next.",
        }
        additions = [
            Finding(kind=kind, text=text, evidence_ids=fallback_evidence)
            for kind, text in missing.items()
            if kind not in present
        ]
        if not additions:
            return narrative
        return narrative.model_copy(update={"findings": [*narrative.findings, *additions]})

    @staticmethod
    def _chart(
        label: str,
        comparison: ComparisonResult,
        segment_rows: list[dict[str, Any]],
        dimension: str | None,
        intent: Intent | None = None,
    ) -> ChartSpec:
        if segment_rows:
            data = [{"segment": str(row["segment"]), "value": float(row.get("value") or 0)} for row in segment_rows]
            return ChartSpec(chart_type="bar", title=f"{label} by {dimension}", x="segment", y="value", data=data, description=f"Bar chart comparing {label.lower()} across {dimension} segments.")
        data = [{"period": comparison.current.label, "value": comparison.current.value}]
        if comparison.previous:
            data.insert(0, {"period": comparison.previous.label, "value": comparison.previous.value})
        chart_type = "line" if intent in {Intent.TREND, Intent.COMPARISON} else "bar"
        description = (
            f"Line chart showing {label.lower()} across the resolved periods."
            if chart_type == "line"
            else f"Bar chart comparing {label.lower()} across the resolved periods."
        )
        return ChartSpec(
            chart_type=chart_type,
            title=f"{label} period comparison",
            x="period",
            y="value",
            data=data,
            description=description,
        )

    @staticmethod
    def _trace(dimensions: list[str], has_drivers: bool) -> list[str]:
        steps = ["Resolved the governed metric and date range", "Generated and AST-validated read-only SQL", "Calculated the metric deterministically"]
        labels = {
            "failure_reason": "Checked payment failure reasons",
            "revenue_motion": "Compared charges, renewals, and refunds",
            "customer_type": "Compared new and returning customers",
        }
        steps.extend(labels.get(dimension, f"Compared {dimension} segments") for dimension in dimensions)
        if has_drivers:
            steps.append("Ranked contribution to the total change")
        steps.extend(["Bound conclusions to evidence", "Prepared recommended next investigations"])
        return steps

    def _safe_audit(
        self,
        query_id: UUID,
        session_hash: str,
        question: str,
        sql: str | None,
        validation: Any,
        status: str | None,
        elapsed: float | None,
        rows: int | None,
        error: str | None,
        *,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        try:
            self.database.audit(
                query_id=query_id,
                session_hash=session_hash,
                question=question,
                generated_sql=sql,
                validation=validation,
                execution_status=status,
                execution_ms=elapsed,
                row_count=rows,
                error_code=error,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception:
            pass

    def _safe_history(self, query_id: UUID, session_hash: str, request: CopilotRequest, response: AnalysisResponse) -> None:
        try:
            self.database.save_history({
                "query_id": query_id,
                "session_hash": session_hash,
                "question": request.question,
                "mode": request.mode.value,
                "intent": response.interpretation.intent.value,
                "metric": response.interpretation.metric,
                "generated_sql": response.sql.query,
                "response": response.model_dump(mode="json"),
                "chart_spec": response.chart.model_dump(mode="json"),
                "provider": response.metadata.provider,
                "latency_ms": response.metadata.timings.total_ms,
                "status": "success",
                "error_code": None,
            })
        except Exception:
            pass
