import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductPulse } from "@/components/product-pulse";
import { WeeklyReport } from "@/components/weekly-report";
import { getProductPulse, getWeeklyReport, weeklyReportMarkdownUrl } from "@/lib/api";
import type { AnomalyMethodology, ProductPulseResponse, WeeklyReportResponse } from "@/lib/types";

vi.mock("next/link", () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));
vi.mock("@/lib/api", () => ({
  getProductPulse: vi.fn(),
  getWeeklyReport: vi.fn(),
  weeklyReportMarkdownUrl: vi.fn(() => "https://api.example.test/reports/weekly/markdown?period=last_week"),
}));

const methodology: AnomalyMethodology = {
  policy_version: "rolling-zscore-v1",
  bucket: "day",
  analysis_period: { start: "2026-05-26", end: "2026-08-24", label: "Last 90 Days" },
  baseline_days: 28,
  minimum_baseline_points: 14,
  minimum_sample_size: 100,
  z_score_threshold: 2,
  rate_change_threshold: 0.1,
  count_change_threshold: 0.15,
  period_end_exclusive: true,
};

const pulse: ProductPulseResponse = {
  type: "product_pulse",
  period: { start: "2026-07-25", end: "2026-08-24", label: "Last 30 Days" },
  dataset_as_of: "2026-08-24",
  items: [{
    id: "anomaly-checkout_conversion-2026-08-18",
    metric: "checkout_conversion",
    metric_label: "Checkout Conversion",
    metric_format: "percentage",
    period: { start: "2026-08-18", end: "2026-08-24", label: "Aug 18–23, 2026" },
    observed: { label: "Aug 18, 2026", value: 0.1, formatted: "10.0%" },
    baseline: { label: "28-day rolling baseline", value: 0.12, formatted: "12.0%" },
    absolute_delta: -0.02,
    relative_delta: -0.166,
    z_score: -3,
    direction: "decrease",
    severity: "critical",
    sample_size: 500,
    evidence_ids: ["metric"],
    drivers: [],
    summary: "Checkout Conversion decreased to 10.0%.",
    copilot_question: "Why did checkout conversion decrease?",
  }],
  evidence: [],
  methodology,
  sql: { tables: ["events"], metrics: ["checkout_conversion"], query_count: 1, validated: true },
  warnings: [],
  metadata: { generated_at: "2026-08-26T00:00:00Z", execution_ms: 12, provider: "deterministic" },
};

const report: WeeklyReportResponse = {
  type: "weekly_report",
  period: { start: "2026-08-17", end: "2026-08-24", label: "Last completed week" },
  comparison_period: { start: "2026-08-10", end: "2026-08-17", label: "Previous completed week" },
  dataset_as_of: "2026-08-24",
  headline: "Checkout Conversion is the strongest weekly signal",
  summary: "Checkout Conversion decreased to 10.0%.",
  sections: ["growth", "activation", "engagement", "retention", "revenue"].map((key) => ({ key: key as "growth" | "activation" | "engagement" | "retention" | "revenue", title: key[0].toUpperCase() + key.slice(1), summary: `${key} summary.`, metrics: [], findings: [] })),
  anomalies: [],
  drivers: [],
  evidence: [],
  recommendations: [],
  follow_up_questions: ["What changed?", "Where did it change?"],
  caveats: [],
  methodology,
  sql: { tables: ["events"], metrics: ["checkout_conversion"], query_count: 1, validated: true },
  warnings: [],
  metadata: { generated_at: "2026-08-26T00:00:00Z", execution_ms: 12, provider: "deterministic" },
};

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("proactive analytics surfaces", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders a Product Pulse signal with a Copilot investigation link", async () => {
    vi.mocked(getProductPulse).mockResolvedValue(pulse);
    renderWithQuery(<ProductPulse />);
    expect(await screen.findByText("Checkout Conversion")).toBeVisible();
    expect(screen.getByText("critical")).toBeVisible();
    expect(screen.getByText("sample 500")).toBeVisible();
    expect(screen.getByRole("link", { name: /Investigate in Copilot/ })).toHaveAttribute("href", expect.stringContaining("/copilot?question="));
  });

  it("renders weekly report sections and Markdown download", async () => {
    vi.mocked(getWeeklyReport).mockResolvedValue(report);
    renderWithQuery(<WeeklyReport />);
    expect(await screen.findByRole("heading", { name: "Weekly product report" })).toBeVisible();
    expect(await screen.findByText("Growth")).toBeVisible();
    expect(screen.getByRole("link", { name: /Download Markdown/ })).toHaveAttribute("href", "https://api.example.test/reports/weekly/markdown?period=last_week");
    expect(weeklyReportMarkdownUrl).toHaveBeenCalled();
  });
});
