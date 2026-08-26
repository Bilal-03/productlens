import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Overview } from "@/components/overview";

vi.mock("next/link", () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));
vi.mock("@/components/auth-provider", () => ({ useAuth: () => ({ session: null }) }));
vi.mock("@/components/chart", () => ({ AnalyticsChart: () => <div data-testid="analytics-chart" /> }));
vi.mock("@/lib/api", () => ({
  api: vi.fn(() => new Promise(() => undefined)),
  getAccessToken: vi.fn(() => null),
  getOverviewSummary: vi.fn().mockResolvedValue({
    type: "overview_summary",
    period: { start: "2026-07-25", end: "2026-08-24", label: "Last 30 Days" },
    comparison_period: { start: "2026-06-25", end: "2026-07-25", label: "Previous equal-length period" },
    dataset_as_of: "2026-08-24",
    kpis: {
      mau: { metric: { label: "Monthly Active Users", format: "integer" }, current_period: { label: "Last 30 Days" }, current: [{ value: 16716 }], previous: [] },
      activation_rate: { metric: { label: "Activation Rate", format: "percentage" }, current_period: { label: "Last 30 Days" }, current: [{ value: 0.55 }], previous: [] },
      checkout_conversion: { metric: { label: "Checkout Conversion", format: "percentage" }, current_period: { label: "Last 30 Days" }, current: [{ value: 0.88 }], previous: [] },
      mrr: { metric: { label: "Monthly Recurring Revenue", format: "currency" }, current_period: { label: "Last 30 Days" }, current: [{ value: 660376 }], previous: [] },
      d30_retention: { metric: { label: "D30 Retention", format: "percentage" }, current_period: { label: "Last 90 Days" }, current: [{ value: 0.10 }], previous: [] },
      churn_rate: { metric: { label: "Subscription Churn", format: "percentage" }, current_period: { label: "Last 30 Days" }, current: [{ value: 0.28 }], previous: [] },
    },
    warnings: [],
  }),
}));

describe("overview loading path", () => {
  it("renders headline cards from the fast summary while details are pending", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><Overview /></QueryClientProvider>);

    expect(await screen.findByText("Monthly Active Users")).toBeVisible();
    expect(screen.getByText("16,716")).toBeVisible();
    expect(screen.getByText("Monthly Recurring Revenue")).toBeVisible();
    expect(screen.getByText("$660,376")).toBeVisible();
  });
});
