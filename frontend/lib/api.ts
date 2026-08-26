import type { AdvancedAnalyticsResponse, CopilotResponse, ExperimentAnalysisResponse, ExperimentListResponse, NotebookInsight, NotebookResponse, NotebookSummaryResponse, ProductPulseResponse, WeeklyReportResponse } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export function getSessionId(): string {
  if (typeof window === "undefined") return "server-render-session-id-placeholder";
  const key = "productlens-session";
  let value = localStorage.getItem(key);
  if (!value) { value = crypto.randomUUID(); localStorage.setItem(key, value); }
  return value;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function analyze(question: string, mode: "quick" | "deep", selected_metric?: string) {
  return api<CopilotResponse>("/copilot/analyze", { method: "POST", body: JSON.stringify({ question, mode, selected_metric, session_id: getSessionId() }) });
}

export function getHistoryItem(queryId: string) {
  return api<CopilotResponse>(`/history/${encodeURIComponent(queryId)}`, {
    headers: { "X-ProductLens-Session": getSessionId() },
  });
}

export function getNotebook(limit = 50) {
  return api<NotebookResponse>(`/notebook/insights?limit=${limit}`, {
    headers: { "X-ProductLens-Session": getSessionId() },
  });
}

export function getNotebookSummary(limit = 50) {
  return api<NotebookSummaryResponse>(`/notebook/summary?limit=${limit}`, {
    headers: { "X-ProductLens-Session": getSessionId() },
  });
}

export function saveNotebookInsight(sourceQueryId: string, title?: string) {
  return api<NotebookInsight>("/notebook/insights", {
    method: "POST",
    headers: { "X-ProductLens-Session": getSessionId() },
    body: JSON.stringify({ source_query_id: sourceQueryId, ...(title ? { title } : {}) }),
  });
}

export function deleteNotebookInsight(insightId: string) {
  return api<void>(`/notebook/insights/${encodeURIComponent(insightId)}`, {
    method: "DELETE",
    headers: { "X-ProductLens-Session": getSessionId() },
  });
}

export function getProductPulse(period = "last_30_days", limit = 20) {
  return api<ProductPulseResponse>(`/insights/pulse?period=${encodeURIComponent(period)}&limit=${limit}`);
}

export function getWeeklyReport(period = "last_week") {
  return api<WeeklyReportResponse>(`/reports/weekly?period=${encodeURIComponent(period)}`);
}

export function weeklyReportMarkdownUrl(period = "last_week") {
  return `${API_URL}/reports/weekly/markdown?period=${encodeURIComponent(period)}`;
}

export function getExperiments() {
  return api<ExperimentListResponse>("/experiments");
}

export function getExperimentAnalysis(experimentKey: string, period = "last_90_days") {
  return api<ExperimentAnalysisResponse>(`/experiments/${encodeURIComponent(experimentKey)}/analysis?period=${encodeURIComponent(period)}`);
}

export function getAdvancedAnalytics(period = "last_90_days") {
  return api<AdvancedAnalyticsResponse>(`/analytics/advanced?period=${encodeURIComponent(period)}`);
}
