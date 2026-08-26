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
