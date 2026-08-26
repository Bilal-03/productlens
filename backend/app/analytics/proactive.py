from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.ai.insights import GroundedInsight, InsightService
from app.analytics.anomalies import (
    AnomalyCandidate,
    AnomalyPolicy,
    collapse_anomaly_runs,
    detect_anomalies,
)
from app.analytics.calculations import (
    SegmentRate,
    additive_contributions,
    format_value,
    rate_contributions,
    safe_relative_change,
)
from app.analytics.sql_compiler import compile_metric, compile_metric_series
from app.analytics.time_ranges import DATASET_AS_OF, default_comparison, resolve_period
from app.database.service import DatabaseService, DatabaseUnavailable
from app.models.contracts import (
    AnomaliesResponse,
    AnomalyMethodology,
    AnomalyRecord,
    AnomalySeverity,
    DateRange,
    Driver,
    Evidence,
    Finding,
    MetricPoint,
    MetricSeriesPoint,
    ProactiveMetadata,
    ProactiveSQLTransparency,
    ProductPulseResponse,
    Recommendation,
    ReportMetric,
    ReportSection,
    WeeklyReportResponse,
)
from app.security.sql_validator import SQLValidator
from app.semantic.registry import MetricDefinition, registry


class ProactiveAnalyticsService:
    """On-demand anomaly, pulse, and report orchestration.

    All source queries are trusted compiler output and pass through the same
    SQL validator and read-only database role as the interactive analytics
    APIs. Only the final optional report prose is provider-backed.
    """

    SERIES_METRICS = (
        "revenue",
        "signups",
        "activation_rate",
        "checkout_conversion",
        "payment_success_rate",
        "payment_failures",
        "churn_rate",
        "dau",
    )
    DIMENSION_SERIES_METRICS = frozenset(
        {"checkout_conversion", "payment_success_rate", "payment_failures"}
    )
    DRIVER_DIMENSIONS: dict[str, tuple[str, ...]] = {
        "revenue": ("revenue_motion", "customer_type", "failure_reason", "plan", "company_size"),
        "signups": ("channel", "campaign", "device", "country"),
        "activation_rate": ("channel", "device", "plan", "company_size"),
        "checkout_conversion": ("checkout_context", "device", "browser", "channel"),
        "payment_success_rate": ("checkout_context", "device", "browser", "channel"),
        "payment_failures": ("checkout_context", "device", "browser", "channel"),
        "churn_rate": ("plan", "company_size", "channel"),
        "dau": ("channel", "device", "plan"),
    }
    REPORT_METRICS = (
        ("growth", "Growth", ("signups",)),
        ("activation", "Activation", ("activation_rate",)),
        ("engagement", "Engagement", ("wau", "stickiness")),
        ("retention", "Retention", ("weekly_retention",)),
        ("revenue", "Revenue", ("revenue", "mrr")),
    )

    def __init__(
        self,
        database: DatabaseService,
        validator: SQLValidator,
        insights: InsightService | None = None,
        policy: AnomalyPolicy | None = None,
    ) -> None:
        self.database = database
        self.validator = validator
        self.insights = insights
        self.policy = policy or AnomalyPolicy()

    def anomalies(self, period_name: str = "last_30_days", limit: int = 50) -> AnomaliesResponse:
        period = self._resolve_public_period(period_name)
        bounded_limit = self._bounded_limit(limit)
        cache_key = self._cache_key("proactive-anomalies", {"period": period_name, "limit": bounded_limit})
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return AnomaliesResponse.model_validate(cached)

        records, evidence, methodology, sql, warnings, execution_ms = self._build_anomalies(period, bounded_limit)
        response = AnomaliesResponse(
            period=period,
            dataset_as_of=DATASET_AS_OF,
            anomalies=records,
            evidence=evidence,
            methodology=methodology,
            sql=sql,
            warnings=warnings,
            metadata=ProactiveMetadata(execution_ms=execution_ms, generated_at=datetime.now(UTC)),
        )
        self._cache_response(cache_key, dataset_version, response.model_dump(mode="json"))
        return response

    def pulse(self, period_name: str = "last_30_days", limit: int = 20) -> ProductPulseResponse:
        period = self._resolve_public_period(period_name)
        bounded_limit = self._bounded_limit(limit)
        cache_key = self._cache_key("product-pulse", {"period": period_name, "limit": bounded_limit})
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return ProductPulseResponse.model_validate(cached)

        records, evidence, methodology, sql, warnings, execution_ms = self._build_anomalies(period, bounded_limit)
        enriched, driver_evidence, driver_queries, driver_tables, driver_warnings = self._enrich_records(records[:5])
        by_id = {record.id: record for record in enriched}
        records = [by_id.get(record.id, record) for record in records]
        response = ProductPulseResponse(
            period=period,
            dataset_as_of=DATASET_AS_OF,
            items=records,
            evidence=[*evidence, *driver_evidence],
            methodology=methodology,
            sql=ProactiveSQLTransparency(
                tables=sorted(set([*sql.tables, *driver_tables])),
                metrics=sql.metrics,
                query_count=sql.query_count + driver_queries,
                validated=sql.validated,
            ),
            warnings=[*warnings, *driver_warnings],
            metadata=ProactiveMetadata(
                execution_ms=execution_ms,
                generated_at=datetime.now(UTC),
            ),
        )
        self._cache_response(cache_key, dataset_version, response.model_dump(mode="json"))
        return response

    def weekly_report(self, period_name: str = "last_week") -> WeeklyReportResponse:
        if period_name != "last_week":
            raise ValueError("Weekly reports currently support only the last completed week")
        period = resolve_period(period_name)
        comparison_period = default_comparison(period_name)
        if comparison_period is None:
            raise ValueError("A weekly comparison period could not be resolved")
        cache_key = self._cache_key("weekly-report", {"period": period_name})
        dataset_version = self.database.dataset_version()
        if dataset_version:
            cached = self.database.cache_get(cache_key, dataset_version)
            if cached is not None:
                return WeeklyReportResponse.model_validate(cached)

        started = time.perf_counter()
        anomalies, evidence, methodology, anomaly_sql, warnings, _ = self._build_anomalies(period, 10)
        anomalies, driver_evidence, driver_queries, driver_tables, driver_warnings = self._enrich_records(anomalies[:5])
        warnings.extend(driver_warnings)
        evidence.extend(driver_evidence)

        sections: list[ReportSection] = []
        report_evidence: list[Evidence] = []
        report_tables = set(anomaly_sql.tables) | set(driver_tables)
        report_metrics = set(anomaly_sql.metrics)
        report_queries = anomaly_sql.query_count + driver_queries
        successful_report_queries = 0
        for key, title, metrics in self.REPORT_METRICS:
            section_metrics: list[ReportMetric] = []
            section_evidence: list[Evidence] = []
            section_warnings: list[str] = []
            for metric in metrics:
                try:
                    report_metric, metric_evidence, query_count, tables = self._report_metric(
                        metric,
                        period if metric != "weekly_retention" else resolve_period("last_90_days"),
                        comparison_period if metric != "weekly_retention" else default_comparison("last_90_days"),
                    )
                    section_metrics.append(report_metric)
                    if metric_evidence:
                        section_evidence.append(metric_evidence)
                    successful_report_queries += query_count
                    report_queries += query_count
                    report_tables.update(tables)
                    report_metrics.add(metric)
                except DatabaseUnavailable:
                    section_warnings.append(f"{metric} was unavailable while this report was generated.")
                except ValueError as exc:
                    section_warnings.append(str(exc))
            if section_warnings:
                warnings.extend(section_warnings)
            report_evidence.extend(section_evidence)
            summary = self._section_summary(title, section_metrics)
            sections.append(
                ReportSection(
                    key=key,
                    title=title,
                    summary=summary,
                    metrics=section_metrics,
                    findings=(
                        [
                            Finding(
                                kind="observed",
                                text=summary,
                                evidence_ids=[item.id for item in section_evidence],
                            )
                        ]
                        if section_evidence
                        else []
                    ),
                )
            )

        if successful_report_queries == 0 and anomaly_sql.query_count == 0:
            raise DatabaseUnavailable("The proactive analytics database is unavailable")

        evidence = [*report_evidence, *evidence]
        drivers = [driver for anomaly in anomalies for driver in anomaly.drivers][:10]
        recommendations = self._recommendations(anomalies)
        deterministic = self._deterministic_report_insight(sections, anomalies, recommendations, evidence)
        narrative, provider, _ = self._interpret_report(deterministic, evidence, period)
        caveats = [
            "Signals use daily UTC buckets and a 28-day rolling baseline.",
            "Anomalies identify unusual movement and do not establish causation.",
            "Retention is shown only for mature cohorts; unavailable values are not treated as zero.",
        ]
        metadata_usage = self.insights.last_usage if self.insights else None
        response = WeeklyReportResponse(
            period=period,
            comparison_period=comparison_period,
            dataset_as_of=DATASET_AS_OF,
            headline=narrative.headline,
            summary=narrative.summary,
            sections=sections,
            anomalies=anomalies,
            drivers=drivers,
            evidence=evidence,
            recommendations=narrative.recommendations,
            follow_up_questions=narrative.follow_up_questions,
            caveats=[*caveats, *narrative.caveats],
            methodology=methodology,
            sql=ProactiveSQLTransparency(
                tables=sorted(report_tables),
                metrics=sorted(report_metrics),
                query_count=report_queries,
                validated=anomaly_sql.validated,
            ),
            warnings=warnings,
            metadata=ProactiveMetadata(
                execution_ms=(time.perf_counter() - started) * 1000,
                generated_at=datetime.now(UTC),
                provider=provider,
                model=metadata_usage.model if metadata_usage else None,
                input_tokens=metadata_usage.input_tokens if metadata_usage else None,
                output_tokens=metadata_usage.output_tokens if metadata_usage else None,
            ),
        )
        self._cache_response(cache_key, dataset_version, response.model_dump(mode="json"))
        return response

    @staticmethod
    def to_markdown(report: WeeklyReportResponse) -> str:
        lines = [
            "# ProductLens Weekly Product Report",
            "",
            f"**Period:** {report.period.label} ({report.period.start} to {report.period.end}, end exclusive)",
            f"**Comparison:** {report.comparison_period.label}",
            f"**Dataset as of:** {report.dataset_as_of}",
            "",
            f"## {report.headline}",
            "",
            report.summary,
            "",
        ]
        for section in report.sections:
            lines.extend([f"## {section.title}", "", section.summary, ""])
            if section.metrics:
                lines.extend(["| Metric | Current | Previous | Change |", "| --- | ---: | ---: | ---: |"])
                for metric in section.metrics:
                    current = metric.current.formatted if metric.current else "Unavailable"
                    previous = metric.previous.formatted if metric.previous else "Unavailable"
                    change = (
                        f"{metric.relative_delta * 100:+.1f}%"
                        if metric.relative_delta is not None
                        else "Unavailable"
                    )
                    lines.append(
                        f"| {ProactiveAnalyticsService._markdown_cell(metric.label)} | {current} | {previous} | {change} |"
                    )
                lines.append("")

        lines.extend(["## Anomalies", ""])
        if report.anomalies:
            lines.extend(["| Severity | Metric | Period | Observed | Baseline | Change |", "| --- | --- | --- | ---: | ---: | ---: |"])
            for anomaly in report.anomalies:
                change = f"{anomaly.relative_delta * 100:+.1f}%" if anomaly.relative_delta is not None else "Unavailable"
                metric_label = anomaly.metric_label + (f" — {anomaly.segment}" if anomaly.segment else "")
                lines.append(
                    f"| {anomaly.severity.value} | {ProactiveAnalyticsService._markdown_cell(metric_label)} | {anomaly.period.label} | {anomaly.observed.formatted} | {anomaly.baseline.formatted} | {change} |"
                )
        else:
            lines.append("No material anomalies crossed the configured detection policy.")
        lines.append("")

        markdown_drivers = [(anomaly, driver) for anomaly in report.anomalies for driver in anomaly.drivers]
        if markdown_drivers:
            lines.extend(["## Key Drivers", ""])
            for anomaly, driver in markdown_drivers:
                contribution = format_value(driver.contribution, anomaly.metric_format)
                lines.append(
                    f"- **{ProactiveAnalyticsService._markdown_cell(driver.segment)}** ({driver.dimension}): {contribution} contribution; sample size {driver.sample_size:,}."
                )
            lines.append("")

        lines.extend(["## Recommended Actions", ""])
        if report.recommendations:
            for recommendation in report.recommendations:
                lines.extend(
                    [
                        f"- **{recommendation.priority.title()}: {ProactiveAnalyticsService._markdown_cell(recommendation.action)}**",
                        f"  - Expected impact: {ProactiveAnalyticsService._markdown_cell(recommendation.expected_impact)}",
                        f"  - Validate: {ProactiveAnalyticsService._markdown_cell(recommendation.how_to_validate)}",
                    ]
                )
        else:
            lines.append("Continue monitoring the governed metrics.")
        lines.extend(["", "## Methodology", "", "- Daily UTC buckets.", f"- {report.methodology.baseline_days}-day rolling baseline.", f"- Minimum baseline observations: {report.methodology.minimum_baseline_points}.", f"- Minimum sample size: {report.methodology.minimum_sample_size}.", f"- SQL statements validated: {str(report.sql.validated).lower()} ({report.sql.query_count} statements)."])
        if report.warnings:
            lines.extend(["", "## Warnings", "", *[f"- {ProactiveAnalyticsService._markdown_cell(warning)}" for warning in report.warnings]])
        return "\n".join(lines) + "\n"

    def _build_anomalies(
        self,
        period: DateRange,
        limit: int,
    ) -> tuple[list[AnomalyRecord], list[Evidence], AnomalyMethodology, ProactiveSQLTransparency, list[str], float]:
        started = time.perf_counter()
        analysis_period = resolve_period("last_90_days")
        series_period = DateRange(
            start=analysis_period.start - timedelta(days=self.policy.baseline_days),
            end=analysis_period.end,
            label="Anomaly history with baseline",
        )
        all_episodes: list[tuple[date, date, AnomalyCandidate]] = []
        tables: set[str] = set()
        metrics: set[str] = set()
        warnings: list[str] = []
        query_count = 0
        database_error: DatabaseUnavailable | None = None
        for metric in self.SERIES_METRICS:
            definition = registry.metric(metric)
            try:
                proposal = compile_metric_series(metric, series_period)
                rows, _, _, query_tables = self._execute(proposal.query)
                query_count += 1
                tables.update(query_tables)
                metrics.add(metric)
                points = self._complete_points(rows, series_period, definition.kind)
                candidates = detect_anomalies(
                    points,
                    metric=metric,
                    kind=definition.kind,
                    policy=self.policy,
                )
                if not candidates and metric in self.DIMENSION_SERIES_METRICS:
                    segment_candidates, segment_queries, segment_tables = self._segment_candidates(
                        metric,
                        series_period,
                        definition.kind,
                    )
                    candidates.extend(segment_candidates)
                    query_count += segment_queries
                    tables.update(segment_tables)
                all_episodes.extend(collapse_anomaly_runs(candidates))
            except DatabaseUnavailable as exc:
                database_error = database_error or exc
                warnings.append(f"{definition.label} was unavailable while signals were calculated.")
            except ValueError as exc:
                warnings.append(str(exc))
        if query_count == 0 and database_error is not None:
            raise database_error

        selected_episodes = [
            (max(start, period.start), min(end, period.end), peak)
            for start, end, peak in all_episodes
            if period.start <= peak.bucket < period.end
        ][:limit]
        records: list[AnomalyRecord] = []
        evidence: list[Evidence] = []
        for start, end, peak in selected_episodes:
            record, metric_evidence = self._record_from_candidate(start, end, peak)
            records.append(record)
            evidence.append(metric_evidence)
        methodology = AnomalyMethodology(
            policy_version=self.policy.policy_version,
            analysis_period=analysis_period,
            baseline_days=self.policy.baseline_days,
            minimum_baseline_points=self.policy.minimum_baseline_points,
            minimum_sample_size=self.policy.minimum_sample_size,
            z_score_threshold=self.policy.z_score_threshold,
            rate_change_threshold=self.policy.rate_change_threshold,
            count_change_threshold=self.policy.count_change_threshold,
        )
        sql = ProactiveSQLTransparency(
            tables=sorted(tables),
            metrics=sorted(metrics),
            query_count=query_count,
            validated=True,
        )
        return records, evidence, methodology, sql, warnings, (time.perf_counter() - started) * 1000

    def _segment_candidates(
        self,
        metric: str,
        period: DateRange,
        kind: str,
    ) -> tuple[list[AnomalyCandidate], int, set[str]]:
        """Run the same detector on the first governed drill-down dimension.

        Segment samples are evaluated over the current bucket plus the trailing
        baseline window. This preserves the 100-sample guard for narrow but
        meaningful incident segments without lowering the aggregate policy.
        """

        definition = registry.metric(metric)
        candidates: list[AnomalyCandidate] = []
        query_count = 0
        tables: set[str] = set()
        for dimension in self.DRIVER_DIMENSIONS.get(metric, ())[:2]:
            proposal = compile_metric_series(metric, period, dimension)
            rows, _, _, query_tables = self._execute(proposal.query)
            query_count += 1
            tables.update(query_tables)
            by_segment: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                segment = str(row.get("segment") or "Unknown")
                by_segment.setdefault(segment, []).append(row)
            dimension_candidates: list[AnomalyCandidate] = []
            for segment, segment_rows in sorted(by_segment.items()):
                points = self._with_evaluation_sample(
                    self._complete_points(segment_rows, period, kind)
                )
                dimension_candidates.extend(
                    replace(item, dimension=dimension, segment=segment)
                    for item in detect_anomalies(
                        points,
                        metric=metric,
                        kind=definition.kind,
                        policy=self.policy,
                    )
                )
            candidates.extend(dimension_candidates)
            if dimension_candidates:
                break
        return candidates, query_count, tables

    def _enrich_records(
        self,
        records: list[AnomalyRecord],
    ) -> tuple[list[AnomalyRecord], list[Evidence], int, list[str], list[str]]:
        enriched: list[AnomalyRecord] = []
        evidence: list[Evidence] = []
        query_count = 0
        tables: set[str] = set()
        warnings: list[str] = []
        for record in records:
            drivers, driver_evidence, queries, driver_tables, driver_warnings = self._drivers_for_record(record)
            query_count += queries
            tables.update(driver_tables)
            warnings.extend(driver_warnings)
            evidence.extend(driver_evidence)
            enriched.append(
                record.model_copy(
                    update={
                        "drivers": drivers,
                        "evidence_ids": [record.evidence_ids[0], *[item.id for item in driver_evidence]],
                    }
                )
            )
        return enriched, evidence, query_count, sorted(tables), warnings

    def _drivers_for_record(
        self,
        record: AnomalyRecord,
    ) -> tuple[list[Driver], list[Evidence], int, list[str], list[str]]:
        duration = record.period.end - record.period.start
        if duration.days <= 0:
            return [], [], 0, [], []
        previous_period = DateRange(
            start=record.period.start - duration,
            end=record.period.start,
            label="Previous equal-length period",
        )
        definition = registry.metric(record.metric)
        all_drivers: list[Driver] = []
        all_evidence: list[Evidence] = []
        query_count = 0
        tables: set[str] = set()
        warnings: list[str] = []
        for dimension in self.DRIVER_DIMENSIONS.get(record.metric, ())[:2]:
            try:
                current_rows, _, _, current_tables = self._execute(
                    compile_metric(record.metric, record.period, dimension).query
                )
                previous_rows, _, _, previous_tables = self._execute(
                    compile_metric(record.metric, previous_period, dimension).query
                )
                query_count += 2
                tables.update(current_tables)
                tables.update(previous_tables)
                drivers, evidence = self._rank_driver_rows(
                    definition,
                    dimension,
                    current_rows,
                    previous_rows,
                )
                for index, driver in enumerate(drivers[:3], start=1):
                    old_id = driver.evidence_ids[0] if driver.evidence_ids else ""
                    original = next((item for item in evidence if item.id == old_id), None)
                    if original is None:
                        continue
                    new_id = f"{record.id}-{dimension}-{index}"
                    all_evidence.append(
                        original.model_copy(
                            update={
                                "id": new_id,
                                "label": f"{record.metric_label}: {original.label}",
                            }
                        )
                    )
                    all_drivers.append(driver.model_copy(update={"evidence_ids": [new_id]}))
            except DatabaseUnavailable:
                warnings.append(f"Segment drivers for {record.metric_label} were unavailable.")
            except ValueError as exc:
                warnings.append(str(exc))
        all_drivers.sort(key=lambda item: (abs(item.contribution), item.sample_size), reverse=True)
        return all_drivers[:5], all_evidence, query_count, sorted(tables), warnings

    @staticmethod
    def _rank_driver_rows(
        definition: MetricDefinition,
        dimension: str,
        current_rows: list[dict[str, Any]],
        previous_rows: list[dict[str, Any]],
    ) -> tuple[list[Driver], list[Evidence]]:
        if definition.kind in {"count", "additive"}:
            return additive_contributions(
                dimension,
                {str(row.get("segment") or "Unknown"): float(row.get("value") or 0) for row in current_rows},
                {str(row.get("segment") or "Unknown"): float(row.get("value") or 0) for row in previous_rows},
                definition.format,
            )
        current_rates = [
            SegmentRate(
                str(row.get("segment") or "Unknown"),
                float(row.get("numerator") or 0),
                float(row.get("denominator") or 0),
            )
            for row in current_rows
        ]
        previous_rates = [
            SegmentRate(
                str(row.get("segment") or "Unknown"),
                float(row.get("numerator") or 0),
                float(row.get("denominator") or 0),
            )
            for row in previous_rows
        ]
        current_denominator = sum(item.denominator for item in current_rates)
        previous_denominator = sum(item.denominator for item in previous_rates)
        current_rate = (
            sum(item.numerator for item in current_rates) / current_denominator
            if current_denominator
            else 0
        )
        previous_rate = (
            sum(item.numerator for item in previous_rates) / previous_denominator
            if previous_denominator
            else 0
        )
        return rate_contributions(dimension, current_rates, previous_rates, current_rate - previous_rate)

    def _report_metric(
        self,
        metric: str,
        current_period: DateRange,
        previous_period: DateRange | None,
    ) -> tuple[ReportMetric, Evidence | None, int, list[str]]:
        definition = registry.metric(metric)
        current, _, _, current_tables = self._metric_snapshot(metric, current_period)
        previous: MetricPoint | None = None
        query_count = 1
        tables = set(current_tables)
        if previous_period is not None:
            previous, _, _, previous_tables = self._metric_snapshot(metric, previous_period)
            query_count += 1
            tables.update(previous_tables)
        absolute_delta = current.value - previous.value if current and previous else None
        relative_delta = safe_relative_change(current.value, previous.value) if current and previous else None
        evidence = None
        evidence_id = f"report-{metric}"
        if current:
            previous_text = previous.formatted if previous else "no comparison"
            relative_text = f"{relative_delta * 100:+.1f}% relative change" if relative_delta is not None else "no relative change available"
            evidence = Evidence(
                id=evidence_id,
                label=definition.label,
                value=f"{current.formatted} vs {previous_text}",
                detail=f"{current_period.label}; {relative_text}",
            )
        return (
            ReportMetric(
                metric=metric,
                label=definition.label,
                format=definition.format,
                current=current,
                previous=previous,
                absolute_delta=absolute_delta,
                relative_delta=relative_delta,
                evidence_id=evidence_id if evidence else None,
            ),
            evidence,
            query_count,
            sorted(tables),
        )

    def _metric_snapshot(
        self,
        metric: str,
        period: DateRange,
    ) -> tuple[MetricPoint | None, str, float, list[str]]:
        proposal = compile_metric(metric, period)
        rows, query, elapsed, tables = self._execute(proposal.query)
        if not rows:
            return None, query, elapsed, tables
        row = rows[0]
        raw_value = row.get("value")
        if raw_value is None:
            return None, query, elapsed, tables
        numerator = row.get("numerator")
        denominator = row.get("denominator")
        definition = registry.metric(metric)
        return (
            MetricPoint(
                label=period.label,
                value=float(raw_value),
                formatted=format_value(float(raw_value), definition.format),
                numerator=float(numerator) if numerator is not None else None,
                denominator=float(denominator) if denominator is not None else None,
            ),
            query,
            elapsed,
            tables,
        )

    @staticmethod
    def _section_summary(title: str, metrics: list[ReportMetric]) -> str:
        available = [metric for metric in metrics if metric.current is not None]
        if not available:
            return f"{title} metrics are unavailable for this dataset."
        changes = []
        for metric in available:
            if metric.relative_delta is None:
                changes.append(f"{metric.label} is {metric.current.formatted if metric.current else 'unavailable'}")
            else:
                direction = "increased" if metric.relative_delta >= 0 else "decreased"
                changes.append(f"{metric.label} {direction} {abs(metric.relative_delta) * 100:.1f}% week over week")
        return "; ".join(changes) + "."

    @staticmethod
    def _deterministic_report_insight(
        sections: list[ReportSection],
        anomalies: list[AnomalyRecord],
        recommendations: list[Recommendation],
        evidence: list[Evidence],
    ) -> GroundedInsight:
        if anomalies:
            headline = f"{anomalies[0].metric_label} is the strongest weekly signal"
            summary = anomalies[0].summary
        else:
            headline = "Weekly product pulse is within expected movement"
            summary = "No material anomalies crossed the configured detection policy in the last completed week."
        findings = [finding for section in sections for finding in section.findings]
        if anomalies:
            findings.append(
                Finding(
                    kind="likely_driver",
                    text=anomalies[0].summary,
                    evidence_ids=anomalies[0].evidence_ids,
                )
            )
            findings.append(
                Finding(
                    kind="hypothesis",
                    text="The detected movement is an observational signal for investigation, not a causal conclusion.",
                    evidence_ids=anomalies[0].evidence_ids,
                )
            )
        else:
            findings.append(
                Finding(
                    kind="observed",
                    text=summary,
                    evidence_ids=[evidence[0].id] if evidence else [],
                )
            )
        return GroundedInsight(
            headline=headline,
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            follow_up_questions=[
                "Which metric should we investigate next?",
                "Which segment contributed most to the strongest signal?",
            ],
            caveats=["Report values are calculated deterministically from the governed analytics dataset."],
        )

    def _interpret_report(
        self,
        deterministic: GroundedInsight,
        evidence: list[Evidence],
        period: DateRange,
    ) -> tuple[GroundedInsight, str, bool]:
        if self.insights is None:
            return deterministic, "deterministic", True
        return self.insights.interpret(
            question=f"Prepare the weekly product report for {period.label}.",
            metric_label="Weekly Product Report",
            evidence=evidence[:40],
            deterministic=deterministic,
        )

    def _record_from_candidate(
        self,
        start: date,
        end: date,
        candidate: AnomalyCandidate,
    ) -> tuple[AnomalyRecord, Evidence]:
        definition = registry.metric(candidate.metric)
        scope_key = f"{candidate.dimension or 'all'}:{candidate.segment or 'all'}"
        scope_suffix = (
            f"-{hashlib.sha256(scope_key.encode('utf-8')).hexdigest()[:10]}"
            if candidate.segment
            else ""
        )
        record_id = f"anomaly-{candidate.metric}-{candidate.bucket.isoformat()}{scope_suffix}"
        period = DateRange(start=start, end=end, label=self._period_label(start, end))
        observed = MetricPoint(
            label=self._period_label(candidate.bucket, candidate.bucket + timedelta(days=1)),
            value=candidate.value,
            formatted=format_value(candidate.value, definition.format),
            numerator=candidate.numerator,
            denominator=candidate.denominator,
        )
        baseline = MetricPoint(
            label="28-day rolling baseline",
            value=candidate.baseline,
            formatted=format_value(candidate.baseline, definition.format),
        )
        direction = "increased" if candidate.direction.value == "increase" else "decreased"
        scope = f" for {candidate.segment}" if candidate.segment else ""
        summary = (
            f"{definition.label}{scope} {direction} to {observed.formatted}, "
            f"{abs(candidate.relative_delta) * 100:.1f}% relative to its 28-day baseline during {period.label}."
        )
        evidence_id = f"{record_id}-metric"
        z_text = "baseline variance was zero" if candidate.z_score is None else f"signed z-score {candidate.z_score:+.2f}"
        evidence = Evidence(
            id=evidence_id,
            label=f"{definition.label}{scope} anomaly",
            value=f"{observed.formatted} vs {baseline.formatted}",
            detail=f"{period.label}; {abs(candidate.relative_delta) * 100:.1f}% relative change; {z_text}; sample size {candidate.sample_size:,}.",
        )
        record = AnomalyRecord(
            id=record_id,
            metric=candidate.metric,
            metric_label=definition.label,
            metric_format=definition.format,
            dimension=candidate.dimension,
            segment=candidate.segment,
            period=period,
            observed=observed,
            baseline=baseline,
            absolute_delta=candidate.absolute_delta,
            relative_delta=candidate.relative_delta,
            z_score=candidate.z_score,
            direction=candidate.direction,
            severity=candidate.severity,
            sample_size=candidate.sample_size,
            evidence_ids=[evidence_id],
            summary=summary,
            copilot_question=(
                f"Why did {definition.label.lower()} {candidate.direction.value}"
                f"{scope} during {period.label}?"
            ),
        )
        return record, evidence

    def _execute(self, query: str) -> tuple[list[dict[str, Any]], str, float, list[str]]:
        validation = self.validator.validate(query)
        if not validation.valid or not validation.normalized_query:
            raise ValueError("Trusted proactive SQL failed validation: " + "; ".join(validation.errors))
        rows, elapsed = self.database.execute_readonly(validation)
        return rows, validation.normalized_query, elapsed, validation.tables

    @staticmethod
    def _complete_points(
        rows: list[dict[str, Any]],
        period: DateRange,
        kind: str,
    ) -> list[MetricSeriesPoint]:
        by_bucket: dict[date, MetricSeriesPoint] = {}
        for row in rows:
            bucket = ProactiveAnalyticsService._as_date(row.get("bucket"))
            value = row.get("value")
            by_bucket[bucket] = MetricSeriesPoint(
                bucket=bucket,
                value=float(value) if value is not None else None,
                numerator=float(row["numerator"]) if row.get("numerator") is not None else None,
                denominator=float(row["denominator"]) if row.get("denominator") is not None else None,
            )
        points: list[MetricSeriesPoint] = []
        cursor = period.start
        while cursor < period.end:
            existing = by_bucket.get(cursor)
            if existing is not None:
                points.append(existing)
            elif kind in {"count", "additive"}:
                points.append(MetricSeriesPoint(bucket=cursor, value=0, numerator=0, denominator=0))
            else:
                points.append(MetricSeriesPoint(bucket=cursor, value=None, numerator=0, denominator=0))
            cursor += timedelta(days=1)
        return points

    def _with_evaluation_sample(self, points: list[MetricSeriesPoint]) -> list[MetricSeriesPoint]:
        evaluated: list[MetricSeriesPoint] = []
        for index, point in enumerate(points):
            start = max(0, index - self.policy.baseline_days)
            baseline_sample = sum(
                max(int(item.denominator or 0), 0) for item in points[start:index]
            )
            current_sample = max(int(point.denominator or 0), 0)
            evaluated.append(
                point.model_copy(update={"sample_size": baseline_sample + current_sample})
            )
        return evaluated

    @staticmethod
    def _as_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    @staticmethod
    def _period_label(start: date, end: date) -> str:
        last = end - timedelta(days=1)
        if start == last:
            return f"{start.strftime('%b')} {start.day}, {start.year}"
        if start.year == last.year and start.month == last.month:
            return f"{start.strftime('%b')} {start.day}–{last.day}, {last.year}"
        return f"{start.strftime('%b')} {start.day}–{last.strftime('%b')} {last.day}, {last.year}"

    @staticmethod
    def _resolve_public_period(period_name: str) -> DateRange:
        if period_name not in {"last_week", "last_30_days", "last_90_days"}:
            raise ValueError("Proactive analytics support last_week, last_30_days, or last_90_days")
        return resolve_period(period_name)

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        return max(1, min(limit, 50))

    def _cache_response(self, cache_key: str, dataset_version: str | None, payload: dict[str, Any]) -> None:
        if dataset_version:
            self.database.cache_put(cache_key, dataset_version, payload, self.database.settings.result_cache_ttl_seconds)

    def _cache_key(self, kind: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"kind": kind, "policy": self.policy.policy_version, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _recommendations(anomalies: list[AnomalyRecord]) -> list[Recommendation]:
        recommendations: list[Recommendation] = []
        for index, anomaly in enumerate(anomalies[:3]):
            evidence_ids = anomaly.evidence_ids[:4]
            recommendations.append(
                Recommendation(
                    priority="high" if index == 0 or anomaly.severity == AnomalySeverity.CRITICAL else "medium",
                    action=f"Investigate the {anomaly.metric_label.lower()} {anomaly.direction.value} signal first",
                    expected_impact="Determine whether the strongest measured signal reflects a product, acquisition, or payment issue",
                    evidence_ids=evidence_ids,
                    how_to_validate="Compare the affected segment, event details, and failure reasons with the preceding equal-length period",
                )
            )
        return recommendations

    @staticmethod
    def _markdown_cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")
