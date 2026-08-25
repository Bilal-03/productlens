import type { CopilotResponse } from "./types";

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
  return response.json() as Promise<T>;
}

export function analyze(question: string, mode: "quick" | "deep", selected_metric?: string) {
  return api<CopilotResponse>("/copilot/analyze", { method: "POST", body: JSON.stringify({ question, mode, selected_metric, session_id: getSessionId() }) });
}

