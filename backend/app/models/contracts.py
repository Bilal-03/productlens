from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Intent(StrEnum):
    KPI = "kpi"
    TREND = "trend"
    COMPARISON = "comparison"
    RANKING = "ranking"
    SEGMENTATION = "segmentation"
    FUNNEL = "funnel"
    RETENTION = "retention"
    COHORT = "cohort"
    FEATURE_ADOPTION = "feature_adoption"
    REVENUE = "revenue"
    ACQUISITION = "acquisition"
    DIAGNOSTIC = "diagnostic"


class AnalysisMode(StrEnum):
    QUICK = "quick"
    DEEP = "deep"


class DateRange(BaseModel):
    start: date
    end: date = Field(description="Exclusive UTC end date")
    label: str


class Filter(BaseModel):
    dimension: str
    operator: Literal["eq", "in"] = "eq"
    value: str | list[str]


class AnalyticsPlan(BaseModel):
    intent: Intent
    metric: str
    time_range: DateRange
    comparison: DateRange | None = None
    dimensions: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    requires_segmentation: bool = False
    requires_comparison: bool = False
    assumptions: list[str] = Field(default_factory=list)


class SQLProposal(BaseModel):
    query: str
    purpose: str
    tables_used: list[str]
    metrics_used: list[str]
    assumptions: list[str] = Field(default_factory=list)


class SQLValidation(BaseModel):
    valid: bool
    normalized_query: str | None = None
    errors: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    limited: bool = False
    failure_kind: Literal["syntax", "schema", "unsafe", "complexity"] | None = None


class MetricPoint(BaseModel):
    label: str
    value: float
    formatted: str
    numerator: float | None = None
    denominator: float | None = None


class ComparisonResult(BaseModel):
    current: MetricPoint
    previous: MetricPoint | None = None
    absolute_delta: float | None = None
    relative_delta: float | None = None
    percentage_point_delta: float | None = None


class Evidence(BaseModel):
    id: str
    label: str
    value: str
    detail: str


class Driver(BaseModel):
    dimension: str
    segment: str
    current_value: float
    previous_value: float
    contribution: float
    share_of_change: float | None = None
    performance_effect: float | None = None
    mix_effect: float | None = None
    sample_size: int
    evidence_ids: list[str]


class Finding(BaseModel):
    kind: Literal["observed", "likely_driver", "hypothesis", "recommended_investigation"]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    priority: Literal["high", "medium", "low"]
    action: str
    expected_impact: str
    evidence_ids: list[str]
    how_to_validate: str


class ChartSpec(BaseModel):
    chart_type: Literal[
        "line", "bar", "stacked_bar", "funnel", "heatmap", "histogram", "scatter", "table", "none"
    ]
    title: str
    x: str | None = None
    y: str | None = None
    series: str | None = None
    data: list[dict[str, Any]] = Field(default_factory=list)
    x_labels: list[str] = Field(default_factory=list)
    y_labels: list[str] = Field(default_factory=list)
    matrix: list[list[float | None]] = Field(default_factory=list)
    description: str


class Timings(BaseModel):
    total_ms: float
    planner_ms: float = 0
    sql_ms: float = 0
    execution_ms: float = 0
    analysis_ms: float = 0
    interpretation_ms: float = 0


class Interpretation(BaseModel):
    intent: Intent
    metric: str
    metric_label: str
    metric_definition: str
    current_period: DateRange
    comparison_period: DateRange | None = None
    dimensions: list[str]
    assumptions: list[str]


class SQLTransparency(BaseModel):
    query: str
    purpose: str
    tables: list[str]
    metrics: list[str]
    validated: bool
    row_count: int


class AnalysisMetadata(BaseModel):
    query_id: str
    generated_at: datetime
    dataset_as_of: date
    provider: str
    confidence: Literal["high", "medium", "low"]
    timings: Timings
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class AnalysisResponse(BaseModel):
    type: Literal["analysis"] = "analysis"
    question: str
    mode: AnalysisMode
    headline: str
    summary: str
    interpretation: Interpretation
    comparison: ComparisonResult
    chart: ChartSpec
    findings: list[Finding]
    drivers: list[Driver]
    evidence: list[Evidence]
    recommendations: list[Recommendation]
    follow_up_questions: list[str]
    investigation_trace: list[str]
    sql: SQLTransparency
    caveats: list[str]
    metadata: AnalysisMetadata


class SaveInsightRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    source_query_id: UUID
    title: str | None = Field(default=None, max_length=160)


class NotebookInsight(BaseModel):
    insight_id: UUID
    source_query_id: UUID
    title: str
    question: str
    mode: AnalysisMode
    headline: str
    summary: str
    interpretation: Interpretation
    comparison: ComparisonResult
    chart: ChartSpec
    findings: list[Finding]
    drivers: list[Driver]
    evidence: list[Evidence]
    recommendations: list[Recommendation]
    created_at: datetime


class NotebookResponse(BaseModel):
    type: Literal["analysis_notebook"] = "analysis_notebook"
    insights: list[NotebookInsight]
    limit: int


class ClarificationOption(BaseModel):
    metric: str
    label: str
    definition: str


class ClarificationResponse(BaseModel):
    type: Literal["clarification"] = "clarification"
    question: str
    reason: str
    options: list[ClarificationOption]


class ErrorResponse(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool
    query_id: str | None = None


class CopilotRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=500)
    mode: AnalysisMode = AnalysisMode.QUICK
    session_id: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    selected_metric: str | None = None


CopilotResponse = AnalysisResponse | ClarificationResponse | ErrorResponse


class AnalyticsRequest(BaseModel):
    metric: str
    period: str = "last_30_days"
    comparison: str | None = None
    dimension: str | None = None
    filters: list[Filter] = Field(default_factory=list)


class AcquisitionRequest(BaseModel):
    period: str = "last_30_days"
    comparison: str | None = None
    dimension: str = "channel"
    filters: list[Filter] = Field(default_factory=list)


class AcquisitionSegment(BaseModel):
    segment: str
    visitors: float
    signups: float
    activated_users: float
    paid_users: float
    signup_conversion: float
    activation_conversion: float
    paid_conversion: float


class AcquisitionAnalyticsResponse(BaseModel):
    type: Literal["acquisition_analysis"] = "acquisition_analysis"
    period: DateRange
    comparison_period: DateRange | None = None
    dataset_as_of: date
    dimension: str
    segments: list[AcquisitionSegment]
    sql: SQLTransparency
    execution_ms: float
    previous_segments: list[AcquisitionSegment] = Field(default_factory=list)


class OverviewRequest(BaseModel):
    period: str = "last_30_days"


class FeatureAdoptionRow(BaseModel):
    feature: str
    eligible_users: float
    adopting_users: float
    adoption_rate: float
    total_uses: float
    uses_per_adopter: float
    feature_user_d30: float | None = None
    non_feature_user_d30: float | None = None
    feature_d30_sample_size: int = 0
    non_feature_d30_sample_size: int = 0
    association_delta: float | None = None


class FeatureAdoptionAnalyticsResponse(BaseModel):
    type: Literal["feature_adoption_analysis"] = "feature_adoption_analysis"
    period: DateRange
    comparison_period: DateRange | None = None
    dataset_as_of: date
    dimension: str | None
    rows: list[FeatureAdoptionRow]
    sql: SQLTransparency
    execution_ms: float
    previous_rows: list[FeatureAdoptionRow] = Field(default_factory=list)


class FunnelRequest(BaseModel):
    funnel: Literal["acquisition", "onboarding", "checkout"] = "checkout"
    period: str = "last_30_days"
    comparison: str | None = None
    dimension: str | None = None
    filters: list[Filter] = Field(default_factory=list)


class RetentionRequest(BaseModel):
    cohort_type: Literal["signup", "activation"] = "signup"
    period: str = "last_90_days"
    dimension: str | None = None
    windows: list[int] = Field(default_factory=lambda: [1, 7, 30], min_length=1, max_length=3)
    filters: list[Filter] = Field(default_factory=list)


class RetentionWindow(BaseModel):
    day: int
    label: str
    metric: str


class RetentionHeatmap(BaseModel):
    x_labels: list[str]
    y_labels: list[str]
    matrix: list[list[float | None]]
    cohort_sizes: list[int]


class RetentionTimeSeriesPoint(BaseModel):
    period: str
    segment: str
    window: str
    value: float | None


class RetentionTimeSeries(BaseModel):
    points: list[RetentionTimeSeriesPoint]
    segments: list[str]


class RetentionSQLTransparency(BaseModel):
    heatmap: str
    trend: str
    tables: list[str]
    metrics: list[str]
    validated: bool


class RetentionAnalyticsResponse(BaseModel):
    type: Literal["retention_analysis"] = "retention_analysis"
    cohort_type: Literal["signup", "activation"]
    period: DateRange
    dataset_as_of: date
    dimension: str | None
    windows: list[RetentionWindow]
    heatmap: RetentionHeatmap
    time_series: RetentionTimeSeries
    sql: RetentionSQLTransparency
    execution_ms: float


class OverviewAnalyticsResponse(BaseModel):
    type: Literal["overview_analysis"] = "overview_analysis"
    period: DateRange
    comparison_period: DateRange | None = None
    dataset_as_of: date
    kpis: dict[str, dict[str, Any]]
    revenue_trend: dict[str, Any]
    user_growth_trend: dict[str, Any]
    acquisition: AcquisitionAnalyticsResponse
    activation_funnel: dict[str, Any]
    retention_snapshot: RetentionAnalyticsResponse


class AnomalySeverity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class AnomalyDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"


class MetricSeriesPoint(BaseModel):
    bucket: date
    value: float | None
    numerator: float | None = None
    denominator: float | None = None
    sample_size: int | None = None


class AnomalyMethodology(BaseModel):
    policy_version: str
    bucket: Literal["day"] = "day"
    analysis_period: DateRange
    baseline_days: int
    minimum_baseline_points: int
    minimum_sample_size: int
    z_score_threshold: float
    rate_change_threshold: float
    count_change_threshold: float
    period_end_exclusive: bool = True


class ProactiveSQLTransparency(BaseModel):
    tables: list[str]
    metrics: list[str]
    query_count: int
    validated: bool


class ProactiveMetadata(BaseModel):
    generated_at: datetime
    execution_ms: float
    provider: str = "deterministic"
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ExperimentSummary(BaseModel):
    experiment_key: str
    name: str
    hypothesis: str
    primary_metric: str
    primary_metric_label: str
    control_variant: str
    variants: list[str]
    status: Literal["draft", "running", "paused", "completed"]
    started_at: date
    ended_at: date | None = None


class ExperimentListResponse(BaseModel):
    type: Literal["experiment_list"] = "experiment_list"
    dataset_as_of: date
    experiments: list[ExperimentSummary]
    sql: ProactiveSQLTransparency | None = None
    execution_ms: float = 0


class ExperimentVariantResult(BaseModel):
    variant: str
    is_control: bool
    sample_size: int
    conversions: int
    conversion_rate: float | None
    formatted_conversion_rate: str


class ExperimentComparison(BaseModel):
    variant: str
    control_variant: str
    control_sample_size: int
    variant_sample_size: int
    control_conversion_rate: float | None
    variant_conversion_rate: float | None
    absolute_uplift: float | None
    relative_uplift: float | None
    confidence_interval_low: float | None
    confidence_interval_high: float | None
    p_value: float | None
    statistically_significant: bool
    significance_note: str


class ExperimentMethodology(BaseModel):
    assignment_unit: Literal["user"] = "user"
    confidence_level: float = 0.95
    alpha: float = 0.05
    minimum_sample_size: int = 100
    significance_test: str
    conversion_definition: str
    period_end_exclusive: bool = True


class ExperimentAnalysisResponse(BaseModel):
    type: Literal["experiment_analysis"] = "experiment_analysis"
    experiment: ExperimentSummary
    period: DateRange
    dataset_as_of: date
    variants: list[ExperimentVariantResult]
    comparisons: list[ExperimentComparison]
    methodology: ExperimentMethodology
    sql: ProactiveSQLTransparency
    warnings: list[str] = Field(default_factory=list)
    metadata: ProactiveMetadata


class ChurnRiskRow(BaseModel):
    dimension: Literal["plan", "company_size", "channel"]
    segment: str
    active_subscriptions: int
    cancellations: int
    churn_rate: float | None
    recent_activity_rate: float | None
    risk_band: Literal["low", "medium", "high", "unavailable"]


class JourneyPath(BaseModel):
    path: str
    users: int
    share: float


class StickinessPoint(BaseModel):
    period: str
    dau: int
    wau: int
    mau: int
    dau_wau: float | None
    dau_mau: float | None
    power_users: int


class RevenueCohortRow(BaseModel):
    cohort: str
    cohort_size: int
    mature: bool
    revenue: float
    revenue_per_user: float | None
    active_revenue_users: int


class AdvancedMethodology(BaseModel):
    analysis_period: DateRange
    churn_definition: str
    recent_activity_window_days: int
    journey_max_steps: int
    power_user_definition: str
    ltv_definition: str
    retention_caveat: str


class AdvancedAnalyticsResponse(BaseModel):
    type: Literal["advanced_analytics"] = "advanced_analytics"
    period: DateRange
    dataset_as_of: date
    churn_risk: list[ChurnRiskRow]
    journeys: list[JourneyPath]
    stickiness: list[StickinessPoint]
    revenue_cohorts: list[RevenueCohortRow]
    methodology: AdvancedMethodology
    sql: ProactiveSQLTransparency
    warnings: list[str] = Field(default_factory=list)
    metadata: ProactiveMetadata


class AnomalyRecord(BaseModel):
    id: str
    metric: str
    metric_label: str
    metric_format: Literal["integer", "percentage", "currency"]
    dimension: str | None = None
    segment: str | None = None
    period: DateRange
    observed: MetricPoint
    baseline: MetricPoint
    absolute_delta: float
    relative_delta: float | None
    z_score: float | None
    direction: AnomalyDirection
    severity: AnomalySeverity
    sample_size: int
    evidence_ids: list[str]
    drivers: list[Driver] = Field(default_factory=list)
    summary: str
    copilot_question: str


class AnomaliesResponse(BaseModel):
    type: Literal["anomaly_detection"] = "anomaly_detection"
    period: DateRange
    dataset_as_of: date
    anomalies: list[AnomalyRecord]
    evidence: list[Evidence]
    methodology: AnomalyMethodology
    sql: ProactiveSQLTransparency
    warnings: list[str] = Field(default_factory=list)
    metadata: ProactiveMetadata


class ProductPulseResponse(BaseModel):
    type: Literal["product_pulse"] = "product_pulse"
    period: DateRange
    dataset_as_of: date
    items: list[AnomalyRecord]
    evidence: list[Evidence]
    methodology: AnomalyMethodology
    sql: ProactiveSQLTransparency
    warnings: list[str] = Field(default_factory=list)
    metadata: ProactiveMetadata


class ReportMetric(BaseModel):
    metric: str
    label: str
    format: Literal["integer", "percentage", "currency"]
    current: MetricPoint | None
    previous: MetricPoint | None
    absolute_delta: float | None
    relative_delta: float | None
    evidence_id: str | None = None


class ReportSection(BaseModel):
    key: Literal["growth", "activation", "engagement", "retention", "revenue"]
    title: str
    summary: str
    metrics: list[ReportMetric]
    findings: list[Finding] = Field(default_factory=list)


class WeeklyReportResponse(BaseModel):
    type: Literal["weekly_report"] = "weekly_report"
    period: DateRange
    comparison_period: DateRange
    dataset_as_of: date
    headline: str
    summary: str
    sections: list[ReportSection]
    anomalies: list[AnomalyRecord]
    drivers: list[Driver]
    evidence: list[Evidence]
    recommendations: list[Recommendation]
    follow_up_questions: list[str]
    caveats: list[str]
    methodology: AnomalyMethodology
    sql: ProactiveSQLTransparency
    warnings: list[str] = Field(default_factory=list)
    metadata: ProactiveMetadata
