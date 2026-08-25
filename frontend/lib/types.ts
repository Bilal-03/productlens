export type DateRange = { start: string; end: string; label: string };
export type Evidence = { id: string; label: string; value: string; detail: string };
export type Driver = { dimension: string; segment: string; current_value: number; previous_value: number; contribution: number; share_of_change: number | null; sample_size: number; evidence_ids: string[] };
export type Finding = { kind: "observed" | "likely_driver" | "hypothesis" | "recommended_investigation"; text: string; evidence_ids: string[] };
export type ChartSpec = { chart_type: "line" | "bar" | "stacked_bar" | "funnel" | "heatmap" | "histogram" | "scatter" | "table" | "none"; title: string; x?: string; y?: string; series?: string; data: Record<string, string | number | null>[]; x_labels: string[]; y_labels: string[]; matrix: (number | null)[][]; description: string };
export type AnalysisResponse = {
  type: "analysis"; question: string; mode: "quick" | "deep"; headline: string; summary: string;
  interpretation: { intent: string; metric: string; metric_label: string; metric_definition: string; current_period: DateRange; comparison_period: DateRange | null; dimensions: string[]; assumptions: string[] };
  comparison: { current: { label: string; value: number; formatted: string; numerator?: number; denominator?: number }; previous: { label: string; value: number; formatted: string; numerator?: number; denominator?: number } | null; absolute_delta: number | null; relative_delta: number | null; percentage_point_delta: number | null };
  chart: ChartSpec; findings: Finding[]; drivers: Driver[]; evidence: Evidence[];
  recommendations: { priority: string; action: string; expected_impact: string; evidence_ids: string[]; how_to_validate: string }[];
  follow_up_questions: string[]; investigation_trace: string[]; sql: { query: string; purpose: string; tables: string[]; metrics: string[]; validated: boolean; row_count: number };
  caveats: string[]; metadata: { query_id: string; generated_at: string; dataset_as_of: string; provider: string; confidence: "high" | "medium" | "low"; timings: { total_ms: number; planner_ms: number; execution_ms: number; analysis_ms: number; interpretation_ms: number } };
};
export type ClarificationResponse = { type: "clarification"; question: string; reason: string; options: { metric: string; label: string; definition: string }[] };
export type ErrorResponse = { type: "error"; code: string; message: string; retryable: boolean; query_id?: string };
export type CopilotResponse = AnalysisResponse | ClarificationResponse | ErrorResponse;

