export type DateRange = { start: string; end: string; label: string };
export type Evidence = { id: string; label: string; value: string; detail: string };
export type Driver = { dimension: string; segment: string; current_value: number; previous_value: number; contribution: number; share_of_change: number | null; performance_effect?: number | null; mix_effect?: number | null; sample_size: number; evidence_ids: string[] };
export type Finding = { kind: "observed" | "likely_driver" | "hypothesis" | "recommended_investigation"; text: string; evidence_ids: string[] };
export type ChartSpec = { chart_type: "line" | "bar" | "stacked_bar" | "funnel" | "heatmap" | "histogram" | "scatter" | "table" | "none"; title: string; x?: string; y?: string; series?: string; data: Record<string, string | number | null>[]; x_labels: string[]; y_labels: string[]; matrix: (number | null)[][]; description: string };
export type AnalysisResponse = {
  type: "analysis"; question: string; mode: "quick" | "deep"; headline: string; summary: string;
  interpretation: { intent: string; metric: string; metric_label: string; metric_definition: string; current_period: DateRange; comparison_period: DateRange | null; dimensions: string[]; assumptions: string[] };
  comparison: { current: { label: string; value: number; formatted: string; numerator?: number; denominator?: number }; previous: { label: string; value: number; formatted: string; numerator?: number; denominator?: number } | null; absolute_delta: number | null; relative_delta: number | null; percentage_point_delta: number | null };
  chart: ChartSpec; findings: Finding[]; drivers: Driver[]; evidence: Evidence[];
  recommendations: { priority: string; action: string; expected_impact: string; evidence_ids: string[]; how_to_validate: string }[];
  follow_up_questions: string[]; investigation_trace: string[]; sql: { query: string; purpose: string; tables: string[]; metrics: string[]; validated: boolean; row_count: number };
  caveats: string[]; metadata: { query_id: string; generated_at: string; dataset_as_of: string; provider: string; confidence: "high" | "medium" | "low"; model?: string | null; input_tokens?: number | null; output_tokens?: number | null; timings: { total_ms: number; planner_ms: number; execution_ms: number; analysis_ms: number; interpretation_ms: number } };
};
export type ClarificationResponse = { type: "clarification"; question: string; reason: string; options: { metric: string; label: string; definition: string }[] };
export type ErrorResponse = { type: "error"; code: string; message: string; retryable: boolean; query_id?: string };
export type CopilotResponse = AnalysisResponse | ClarificationResponse | ErrorResponse;

export type AcquisitionSegment = {
  segment: string;
  visitors: number;
  signups: number;
  activated_users: number;
  paid_users: number;
  signup_conversion: number;
  activation_conversion: number;
  paid_conversion: number;
};

export type AcquisitionResponse = {
  type: "acquisition_analysis";
  period: DateRange;
  comparison_period: DateRange | null;
  dataset_as_of: string;
  dimension: string;
  segments: AcquisitionSegment[];
  previous_segments: AcquisitionSegment[];
  sql: { query: string; purpose: string; tables: string[]; metrics: string[]; validated: boolean; row_count: number };
  execution_ms: number;
};

export type OverviewResponse = {
  type: "overview_analysis";
  period: DateRange;
  comparison_period: DateRange | null;
  dataset_as_of: string;
  kpis: Record<string, { metric?: { label: string; format: string }; current?: { value: number }[]; previous?: { value: number }[]; current_period?: { label: string } }>;
  revenue_trend: { points: { label: string; value: number }[] };
  user_growth_trend: { points: { label: string; value: number }[] };
  acquisition: AcquisitionResponse;
  activation_funnel: { segments: Record<string, { stage: string; users: number }[]> };
  retention_snapshot: { heatmap: { x_labels: string[]; y_labels: string[]; matrix: (number | null)[][]; cohort_sizes: number[] } };
};

export type ExperimentSummary = {
  experiment_key: string;
  name: string;
  hypothesis: string;
  primary_metric: string;
  primary_metric_label: string;
  control_variant: string;
  variants: string[];
  status: "draft" | "running" | "paused" | "completed";
  started_at: string;
  ended_at: string | null;
};

export type ExperimentListResponse = {
  type: "experiment_list";
  dataset_as_of: string;
  experiments: ExperimentSummary[];
  sql: ProactiveSQLTransparency | null;
  execution_ms: number;
};

export type ExperimentVariantResult = {
  variant: string;
  is_control: boolean;
  sample_size: number;
  conversions: number;
  conversion_rate: number | null;
  formatted_conversion_rate: string;
};

export type ExperimentComparison = {
  variant: string;
  control_variant: string;
  control_sample_size: number;
  variant_sample_size: number;
  control_conversion_rate: number | null;
  variant_conversion_rate: number | null;
  absolute_uplift: number | null;
  relative_uplift: number | null;
  confidence_interval_low: number | null;
  confidence_interval_high: number | null;
  p_value: number | null;
  statistically_significant: boolean;
  significance_note: string;
};

export type ExperimentAnalysisResponse = {
  type: "experiment_analysis";
  experiment: ExperimentSummary;
  period: DateRange;
  dataset_as_of: string;
  variants: ExperimentVariantResult[];
  comparisons: ExperimentComparison[];
  methodology: {
    assignment_unit: "user";
    confidence_level: number;
    alpha: number;
    minimum_sample_size: number;
    significance_test: string;
    conversion_definition: string;
    period_end_exclusive: boolean;
  };
  sql: ProactiveSQLTransparency;
  warnings: string[];
  metadata: ProactiveMetadata;
};

export type ChurnRiskRow = {
  dimension: "plan" | "company_size" | "channel";
  segment: string;
  active_subscriptions: number;
  cancellations: number;
  churn_rate: number | null;
  recent_activity_rate: number | null;
  risk_band: "low" | "medium" | "high" | "unavailable";
};

export type AdvancedAnalyticsResponse = {
  type: "advanced_analytics";
  period: DateRange;
  dataset_as_of: string;
  churn_risk: ChurnRiskRow[];
  journeys: { path: string; users: number; share: number }[];
  stickiness: { period: string; dau: number; wau: number; mau: number; dau_wau: number | null; dau_mau: number | null; power_users: number }[];
  revenue_cohorts: { cohort: string; cohort_size: number; mature: boolean; revenue: number; revenue_per_user: number | null; active_revenue_users: number }[];
  methodology: {
    analysis_period: DateRange;
    churn_definition: string;
    recent_activity_window_days: number;
    journey_max_steps: number;
    power_user_definition: string;
    ltv_definition: string;
    retention_caveat: string;
  };
  sql: ProactiveSQLTransparency;
  warnings: string[];
  metadata: ProactiveMetadata;
};

export type FeatureAdoptionRow = {
  feature: string;
  eligible_users: number;
  adopting_users: number;
  adoption_rate: number;
  total_uses: number;
  uses_per_adopter: number;
  feature_user_d30: number | null;
  non_feature_user_d30: number | null;
  feature_d30_sample_size: number;
  non_feature_d30_sample_size: number;
  association_delta: number | null;
};

export type FeatureAdoptionResponse = {
  type: "feature_adoption_analysis";
  period: DateRange;
  comparison_period: DateRange | null;
  dataset_as_of: string;
  dimension: string | null;
  rows: FeatureAdoptionRow[];
  previous_rows: FeatureAdoptionRow[];
  sql: { query: string; purpose: string; tables: string[]; metrics: string[]; validated: boolean; row_count: number };
  execution_ms: number;
};

export type CatalogColumn = { name: string; data_type: string; description: string; sample_values: (string | number)[]; pii: boolean };
export type CatalogTable = { name: string; description: string; primary_key: string; foreign_keys: Record<string, string>; columns: string[]; pii_columns: string[]; allowed_dimensions: string[]; column_metadata: CatalogColumn[]; row_count: number | null };
export type CatalogResponse = { metrics: { name: string; label: string; description: string; kind: string; entity: string; format: string; valid_dimensions: string[] }[]; dimensions: { name: string; label: string; table: string; column: string; sample_values: string[]; expression?: string | null; valid_metrics?: string[] }[]; tables: CatalogTable[] };

export type ProactiveMetricPoint = { label: string; value: number; formatted: string; numerator?: number | null; denominator?: number | null };
export type AnomalyRecord = {
  id: string; metric: string; metric_label: string; metric_format: "integer" | "percentage" | "currency"; dimension?: string | null; segment?: string | null;
  period: DateRange; observed: ProactiveMetricPoint; baseline: ProactiveMetricPoint;
  absolute_delta: number; relative_delta: number | null; z_score: number | null;
  direction: "increase" | "decrease"; severity: "warning" | "critical"; sample_size: number;
  evidence_ids: string[]; drivers: Driver[]; summary: string; copilot_question: string;
};
export type AnomalyMethodology = {
  policy_version: string; bucket: "day"; analysis_period: DateRange; baseline_days: number;
  minimum_baseline_points: number; minimum_sample_size: number; z_score_threshold: number;
  rate_change_threshold: number; count_change_threshold: number; period_end_exclusive: boolean;
};
export type ProactiveSQLTransparency = { tables: string[]; metrics: string[]; query_count: number; validated: boolean };
export type ProactiveMetadata = { generated_at: string; execution_ms: number; provider: string; model?: string | null; input_tokens?: number | null; output_tokens?: number | null };
export type AnomaliesResponse = {
  type: "anomaly_detection"; period: DateRange; dataset_as_of: string; anomalies: AnomalyRecord[];
  evidence: Evidence[]; methodology: AnomalyMethodology; sql: ProactiveSQLTransparency;
  warnings: string[]; metadata: ProactiveMetadata;
};
export type ProductPulseResponse = {
  type: "product_pulse"; period: DateRange; dataset_as_of: string; items: AnomalyRecord[];
  evidence: Evidence[]; methodology: AnomalyMethodology; sql: ProactiveSQLTransparency;
  warnings: string[]; metadata: ProactiveMetadata;
};
export type ReportMetric = {
  metric: string; label: string; format: "integer" | "percentage" | "currency";
  current: ProactiveMetricPoint | null; previous: ProactiveMetricPoint | null;
  absolute_delta: number | null; relative_delta: number | null; evidence_id?: string | null;
};
export type ReportSection = {
  key: "growth" | "activation" | "engagement" | "retention" | "revenue";
  title: string; summary: string; metrics: ReportMetric[]; findings: Finding[];
};
export type WeeklyReportResponse = {
  type: "weekly_report"; period: DateRange; comparison_period: DateRange; dataset_as_of: string;
  headline: string; summary: string; sections: ReportSection[]; anomalies: AnomalyRecord[];
  drivers: Driver[]; evidence: Evidence[]; recommendations: AnalysisResponse["recommendations"];
  follow_up_questions: string[]; caveats: string[]; methodology: AnomalyMethodology;
  sql: ProactiveSQLTransparency; warnings: string[]; metadata: ProactiveMetadata;
};
