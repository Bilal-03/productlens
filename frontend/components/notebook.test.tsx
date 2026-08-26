import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotebookPage } from "@/components/notebook";
import { getNotebook, getNotebookSummary } from "@/lib/api";
import type { NotebookInsight, NotebookResponse, NotebookSummary } from "@/lib/types";

vi.mock("next/link", () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));
vi.mock("@/lib/api", () => ({ deleteNotebookInsight: vi.fn(), getNotebook: vi.fn(), getNotebookSummary: vi.fn() }));

const insight: NotebookInsight = {
  insight_id: "11111111-1111-4111-8111-111111111111",
  source_query_id: "22222222-2222-4222-8222-222222222222",
  title: "Checkout incident",
  question: "Why did checkout conversion fall?",
  mode: "deep",
  headline: "Checkout conversion fell on mobile",
  summary: "Mobile Safari contributed the largest observed decline.",
  interpretation: {
    intent: "diagnostic", metric: "checkout_conversion", metric_label: "Checkout Conversion",
    metric_definition: "Paid users divided by checkout starters.",
    current_period: { start: "2026-08-17", end: "2026-08-24", label: "Last week" },
    comparison_period: { start: "2026-08-10", end: "2026-08-17", label: "Previous week" }, dimensions: ["browser"], assumptions: [],
  },
  comparison: {
    current: { label: "Last week", value: 0.1, formatted: "10.0%" },
    previous: { label: "Previous week", value: 0.12, formatted: "12.0%" }, absolute_delta: -0.02, relative_delta: -0.16, percentage_point_delta: -0.02,
  },
  chart: { chart_type: "line", title: "Checkout conversion", data: [], x_labels: [], y_labels: [], matrix: [], description: "Daily rate." },
  findings: [{ kind: "observed", text: "Conversion decreased week over week.", evidence_ids: ["metric"] }],
  drivers: [{ dimension: "browser", segment: "Safari", current_value: 0.08, previous_value: 0.14, contribution: -0.03, share_of_change: 0.5, sample_size: 500, evidence_ids: ["safari"] }],
  evidence: [{ id: "metric", label: "Checkout conversion", value: "10.0%", detail: "Observed value." }],
  recommendations: [], created_at: "2026-08-26T00:00:00Z",
};

const summary: NotebookSummary = {
  generated_at: "2026-08-26T00:00:00Z",
  headline: "Executive summary across 1 saved investigation",
  summary: "The saved evidence points to a checkout conversion issue on Safari.",
  source_insight_ids: [insight.insight_id],
  themes: [{ metric: "checkout_conversion", metric_label: "Checkout Conversion", insight_count: 1, headline: insight.headline, summary: insight.summary, evidence_ids: ["metric"], source_insight_ids: [insight.insight_id] }],
  findings: [{ ...insight.findings[0], source_insight_ids: [insight.insight_id] }],
  drivers: [{ ...insight.drivers[0], source_insight_ids: [insight.insight_id] }],
  recommendations: [],
  methodology: { source_insight_count: 1, evidence_bound: true, snapshot_only: true, deterministic: true },
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><NotebookPage /></QueryClientProvider>);
}

describe("analysis notebook", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders the empty state and a path to Copilot", async () => {
    vi.mocked(getNotebook).mockResolvedValue({ type: "analysis_notebook", insights: [], limit: 50 });
    renderPage();

    expect(await screen.findByRole("heading", { name: "Saved investigations" })).toBeVisible();
    expect(await screen.findByText("No saved analyses yet")).toBeVisible();
    expect(screen.getByRole("link", { name: /Start an analysis/ })).toHaveAttribute("href", "/copilot");
  });

  it("renders a saved signal map and opens the source analysis", async () => {
    const payload: NotebookResponse = { type: "analysis_notebook", insights: [insight], limit: 50 };
    vi.mocked(getNotebook).mockResolvedValue(payload);
    vi.mocked(getNotebookSummary).mockResolvedValue({ type: "notebook_summary", summary, insight_count: 1, limit: 50, warnings: [] });
    renderPage();

    expect(await screen.findByText("Checkout incident")).toBeVisible();
    expect(screen.getByText("Conversion decreased week over week.")).toBeVisible();
    expect(screen.getByText("Safari")).toBeVisible();
    expect(screen.getByRole("link", { name: /Open full analysis/ })).toHaveAttribute("href", `/copilot?query_id=${insight.source_query_id}`);
    fireEvent.click(screen.getByRole("button", { name: "Generate executive summary" }));
    expect(await screen.findByRole("heading", { name: summary.headline })).toBeVisible();
    expect(screen.getByText("Key themes")).toBeVisible();
  });
});
