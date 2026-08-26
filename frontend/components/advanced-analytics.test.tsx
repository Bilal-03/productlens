import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdvancedAnalytics } from "@/components/advanced-analytics";
import { Experiments } from "@/components/experiments";
import { getAdvancedAnalytics, getExperimentAnalysis, getExperiments } from "@/lib/api";
import type { AdvancedAnalyticsResponse, ExperimentAnalysisResponse, ExperimentListResponse } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  getAdvancedAnalytics: vi.fn(),
  getExperimentAnalysis: vi.fn(),
  getExperiments: vi.fn(),
}));

const metadata = { generated_at: "2026-08-26T00:00:00Z", execution_ms: 12, provider: "deterministic" };
const experimentList: ExperimentListResponse = {
  type: "experiment_list",
  dataset_as_of: "2026-08-24",
  experiments: [{
    experiment_key: "onboarding-redesign",
    name: "Onboarding redesign",
    hypothesis: "Reducing onboarding friction increases activation",
    primary_metric: "activation_rate",
    primary_metric_label: "Activation Rate",
    control_variant: "control",
    variants: ["control", "variant"],
    status: "completed",
    started_at: "2026-05-01",
    ended_at: "2026-08-24",
  }],
  sql: { tables: ["experiments"], metrics: [], query_count: 1, validated: true },
  execution_ms: 2,
};
const experimentAnalysis: ExperimentAnalysisResponse = {
  type: "experiment_analysis",
  experiment: experimentList.experiments[0],
  period: { start: "2026-05-26", end: "2026-08-24", label: "Last 90 Days" },
  dataset_as_of: "2026-08-24",
  variants: [
    { variant: "control", is_control: true, sample_size: 200, conversions: 80, conversion_rate: 0.4, formatted_conversion_rate: "40.0%" },
    { variant: "variant", is_control: false, sample_size: 200, conversions: 120, conversion_rate: 0.6, formatted_conversion_rate: "60.0%" },
  ],
  comparisons: [{
    variant: "variant", control_variant: "control", control_sample_size: 200, variant_sample_size: 200,
    control_conversion_rate: 0.4, variant_conversion_rate: 0.6, absolute_uplift: 0.2,
    relative_uplift: 0.5, confidence_interval_low: 0.1, confidence_interval_high: 0.3,
    p_value: 0.01, statistically_significant: true, significance_note: "Statistically significant at alpha=0.05.",
  }],
  methodology: {
    assignment_unit: "user", confidence_level: 0.95, alpha: 0.05, minimum_sample_size: 100,
    significance_test: "Two-sided two-proportion z-test", conversion_definition: "Signup and onboarding",
    period_end_exclusive: true,
  },
  sql: { tables: ["events"], metrics: ["activation_rate"], query_count: 1, validated: true },
  warnings: [],
  metadata,
};
const advanced: AdvancedAnalyticsResponse = {
  type: "advanced_analytics",
  period: { start: "2026-05-26", end: "2026-08-24", label: "Last 90 Days" },
  dataset_as_of: "2026-08-24",
  churn_risk: [{ dimension: "channel", segment: "Paid Social", active_subscriptions: 100, cancellations: 25, churn_rate: 0.25, recent_activity_rate: 0.4, risk_band: "high" }],
  journeys: [{ path: "signup_completed → onboarding_completed", users: 42, share: 0.7 }],
  stickiness: [{ period: "2026-08-23", dau: 80, wau: 160, mau: 400, dau_wau: 0.5, dau_mau: 0.2, power_users: 12 }],
  revenue_cohorts: [{ cohort: "2026-08-01", cohort_size: 120, mature: false, revenue: 2400, revenue_per_user: 20, active_revenue_users: 80 }],
  methodology: {
    analysis_period: { start: "2026-05-26", end: "2026-08-24", label: "Last 90 Days" },
    churn_definition: "Observed cancellations / active subscriptions", recent_activity_window_days: 30,
    journey_max_steps: 5, power_user_definition: "Ten active days", ltv_definition: "Observed revenue per signup",
    retention_caveat: "Immature cohorts are unavailable",
  },
  sql: { tables: ["events", "subscriptions"], metrics: ["dau"], query_count: 6, validated: true },
  warnings: [],
  metadata,
};

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("Phase 39 and 40 analytics surfaces", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders experiment uplift and statistical significance", async () => {
    vi.mocked(getExperiments).mockResolvedValue(experimentList);
    vi.mocked(getExperimentAnalysis).mockResolvedValue(experimentAnalysis);
    renderWithQuery(<Experiments />);

    expect(await screen.findByRole("heading", { name: "Experiment analytics" })).toBeVisible();
    expect(await screen.findByText("60.0%")).toBeVisible();
    expect(screen.getByText("significant")).toBeVisible();
    expect(screen.getByText("+50.0%")).toBeVisible();
  });

  it("renders churn, journeys, stickiness, and revenue cohorts", async () => {
    vi.mocked(getAdvancedAnalytics).mockResolvedValue(advanced);
    renderWithQuery(<AdvancedAnalytics />);

    expect(await screen.findByRole("heading", { name: "Advanced analytics" })).toBeVisible();
    expect(await screen.findByText("Who needs attention?")).toBeVisible();
    expect(screen.getByText("high")).toBeVisible();
    expect(screen.getByText("signup_completed → onboarding_completed")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Observed revenue per signup" })).toBeVisible();
    expect(screen.getByText("immature")).toBeVisible();
  });
});
