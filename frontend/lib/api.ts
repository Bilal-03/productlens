import type { AccessContextResponse, AdvancedAnalyticsResponse, ConnectorStatusResponse, CopilotResponse, ExperimentAnalysisResponse, ExperimentListResponse, NotebookInsight, NotebookResponse, NotebookSummaryResponse, ProductPulseResponse, WeeklyReportResponse } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const ACCESS_TOKEN_KEY = "productlens-access-token";
const SUPABASE_SESSION_KEY = "productlens-supabase-session";

export function getSessionId(): string {
  if (typeof window === "undefined") return "server-render-session-id-placeholder";
  const key = "productlens-session";
  let value = localStorage.getItem(key);
  if (!value) { value = crypto.randomUUID(); localStorage.setItem(key, value); }
  return value;
}

/** Store a short-lived assertion supplied by an external SSO callback. */
export function setAccessToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.sessionStorage.setItem(ACCESS_TOKEN_KEY, token);
  else window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  const explicitToken = window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
  if (explicitToken) return explicitToken;

  // Supabase persists its short-lived session before AuthProvider's effect
  // hydrates. Reusing only a valid JWT here prevents the first authenticated
  // page request from racing ahead as anonymous demo traffic on refresh.
  try {
    const rawSession = window.localStorage.getItem(SUPABASE_SESSION_KEY);
    if (!rawSession) return null;
    const session = JSON.parse(rawSession) as { access_token?: unknown; expires_at?: unknown };
    if (typeof session.access_token !== "string" || !session.access_token) return null;
    if (typeof session.expires_at === "number" && session.expires_at <= Math.floor(Date.now() / 1000)) {
      return null;
    }
    return session.access_token;
  } catch {
    return null;
  }
}

export function getAccessHeaders(): Record<string, string> {
  const token = getAccessToken();
  if (!token) return {};
  if (token.startsWith("plx1.")) return { "X-ProductLens-Access": token };
  // OIDC access tokens are standard three-part JWTs and use the bearer scheme.
  if (token.split(".").length === 3) return { Authorization: `Bearer ${token}` };
  return { "X-ProductLens-Access": token };
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const accessHeaders = getAccessHeaders();
  for (const [key, value] of Object.entries(accessHeaders)) headers.set(key, value);
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getAccessContext() {
  return api<AccessContextResponse>("/access/context");
}

export function getConnectorStatus() {
  return api<ConnectorStatusResponse>("/connectors/status");
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

export async function downloadWeeklyReportMarkdown(period = "last_week") {
  const response = await fetch(weeklyReportMarkdownUrl(period), { headers: getAccessHeaders() });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed (${response.status})`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition");
  const filename = disposition?.match(/filename="([A-Za-z0-9._-]+)"/)?.[1] ?? "productlens-weekly-report.md";
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
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
