from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

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


class FunnelRequest(BaseModel):
    funnel: Literal["acquisition", "onboarding", "checkout"] = "checkout"
    period: str = "last_30_days"
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
