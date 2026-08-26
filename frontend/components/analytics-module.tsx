"use client";

import { useState } from "react";
import { useMutation, useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { Filter, Play, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { AnalyticsChart } from "@/components/chart";
import { Badge, Button, Card } from "@/components/ui";
import { PageHeading } from "@/components/page-heading";
import type { AcquisitionResponse, ChartSpec, FeatureAdoptionResponse } from "@/lib/types";

type ModuleName = "funnels" | "retention" | "cohorts" | "segments" | "feature-adoption" | "acquisition";

type ModuleConfig = {
  title: string;
  description: string;
  endpoint: string;
  body: Record<string, unknown>;
  question: string;
};

const configs: Record<ModuleName, ModuleConfig> = {
  funnels: {
    title: "Funnel analysis",
    description: "Find the exact transition where users lose momentum, with stage and overall conversion.",
    endpoint: "/analytics/funnel",
    body: { funnel: "onboarding", period: "last_30_days" },
    question: "Where are users dropping during onboarding?",
  },
  retention: {
    title: "Retention analysis",
    description: "Read cohort maturity at a glance with D1, D7, and D30 retention heatmaps and weekly curves.",
    endpoint: "/analytics/retention",
    body: { cohort_type: "signup", period: "last_90_days", windows: [1, 7, 30], dimension: "channel" },
    question: "How does D30 retention differ by acquisition channel?",
  },
  cohorts: {
    title: "Cohort explorer",
    description: "Compare signup cohorts without mixing immature D30 windows with cohorts that have had time to mature.",
    endpoint: "/analytics/cohort",
    body: { cohort_type: "signup", period: "last_90_days", windows: [1, 7, 30] },
    question: "Which signup cohort has the strongest retention?",
  },
  segments: {
    title: "Segment comparison",
    description: "Compare governed metrics across valid product and acquisition dimensions.",
    endpoint: "/analytics/segment",
    body: { metric: "activation_rate", period: "last_30_days", dimension: "channel" },
    question: "How does activation differ by acquisition channel?",
  },
  "feature-adoption": {
    title: "Feature adoption",
    description: "Measure reach and usage while keeping association separate from causation.",
    endpoint: "/analytics/feature-adoption",
    body: { metric: "feature_adoption", period: "last_30_days", dimension: "feature" },
    question: "Which features are associated with better retention?",
  },
  acquisition: {
    title: "Acquisition analytics",
    description: "Compare visitor volume, signup quality, activation, and paid conversion across governed acquisition segments.",
    endpoint: "/analytics/acquisition",
    body: { period: "last_30_days", dimension: "channel" },
    question: "Which acquisition channel converts best?",
  },
};

type MetricResult = {
  metric: { label: string; format: string };
  current_period: { label: string };
  current: { segment: string; value: number; numerator: number; denominator: number }[];
  previous: { segment: string; value: number }[];
  sql: { current: string };
  dataset_as_of: string;
  execution_ms: number;
};

type FunnelResult = {
  funnel: string;
  period: { label: string };
  comparison_period?: { label: string } | null;
  segments: Record<string, { stage: string; users: number; stage_conversion: number; overall_conversion: number; drop_off: number }[]>;
  previous_segments?: Record<string, { stage: string; users: number; stage_conversion: number; overall_conversion: number; drop_off: number }[]>;
  sql: string;
  dataset_as_of: string;
  execution_ms: number;
};

type RetentionWindow = { day: number; label: string; metric: string };
type RetentionResult = {
  type: "retention_analysis";
  cohort_type: "signup" | "activation";
  period: { label: string };
  dataset_as_of: string;
  dimension: string | null;
  windows: RetentionWindow[];
  heatmap: {
    x_labels: string[];
    y_labels: string[];
    matrix: (number | null)[][];
    cohort_sizes: number[];
  };
  time_series: {
    points: { period: string; segment: string; window: string; value: number | null }[];
    segments: string[];
  };
  sql: { heatmap: string; trend: string; tables: string[]; metrics: string[]; validated: boolean };
  execution_ms: number;
};

type AnalyticsResult = MetricResult | FunnelResult | RetentionResult;
type ModuleResult = AnalyticsResult | AcquisitionResponse | FeatureAdoptionResponse;

function isAcquisitionResult(result: ModuleResult | undefined): result is AcquisitionResponse {
  return Boolean(result && "type" in result && result.type === "acquisition_analysis");
}

function isFeatureAdoptionResult(result: ModuleResult | undefined): result is FeatureAdoptionResponse {
  return Boolean(result && "type" in result && result.type === "feature_adoption_analysis");
}

function isRetentionResult(result: ModuleResult | undefined): result is RetentionResult {
  return Boolean(result && "heatmap" in result);
}

function RetentionResults({ result }: { result: RetentionResult }) {
  const windowQueries = useQueries({ queries: ["weekly_retention", "monthly_retention"].map((metric) => ({ queryKey: ["retention-window", metric], queryFn: () => api<MetricResult>("/analytics/kpi", { method: "POST", body: JSON.stringify({ metric, period: "last_90_days" }) }) })) });
  const [trendSegment, setTrendSegment] = useState("All");
  const availableSegments = result.time_series.segments;
  const activeSegment = availableSegments.includes(trendSegment) ? trendSegment : availableSegments[0] ?? "All";

  const heatmapSpec: ChartSpec = {
    chart_type: "heatmap",
    title: `${result.cohort_type === "activation" ? "Activation" : "Signup"} cohort retention`,
    x_labels: result.heatmap.x_labels,
    y_labels: result.heatmap.y_labels,
    matrix: result.heatmap.matrix,
    data: [],
    description: "Retention heatmap by weekly cohort. Blank cells indicate a window that has not matured yet.",
  };
  const trendSpec: ChartSpec = {
    chart_type: "line",
    title: `${activeSegment} retention over cohort weeks`,
    x: "period",
    y: "value",
    series: "window",
    data: result.time_series.points
      .filter((point) => point.segment === activeSegment)
      .map((point) => ({ period: point.period, window: point.window, value: point.value })),
    x_labels: [],
    y_labels: [],
    matrix: [],
    description: "Line chart showing D1, D7, and D30 retention over weekly cohort periods.",
  };

  return <>
    <div className="mb-5 grid gap-3 sm:grid-cols-2"><Card className="p-4"><div className="eyebrow">Weekly retention</div><div className="mt-2 text-2xl font-bold">{windowQueries[0].isLoading ? "—" : windowQueries[0].data?.current[0]?.value == null ? "Unavailable" : `${(windowQueries[0].data.current[0].value * 100).toFixed(1)}%`}</div><p className="mt-1 text-xs text-[#747b8b]">Return activity during days 7–13 after signup.</p></Card><Card className="p-4"><div className="eyebrow">Monthly retention</div><div className="mt-2 text-2xl font-bold">{windowQueries[1].isLoading ? "—" : windowQueries[1].data?.current[0]?.value == null ? "Unavailable" : `${(windowQueries[1].data.current[0].value * 100).toFixed(1)}%`}</div><p className="mt-1 text-xs text-[#747b8b]">Return activity during days 30–59 after signup.</p></Card></div>
    <div className="grid gap-5 xl:grid-cols-[1.45fr_1fr]">
      <Card className="p-4"><AnalyticsChart spec={heatmapSpec} /></Card>
      <Card className="p-4"><AnalyticsChart spec={trendSpec} /></Card>
    </div>
    <Card className="mt-5 overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-[#e5e8ee] p-4 sm:flex-row sm:items-center sm:justify-between">
        <div><div className="eyebrow">Cohort detail</div><p className="mt-1 text-sm text-[#747b8b]">D30 is shown as unavailable until each cohort reaches day 30.</p></div>
        {availableSegments.length > 1 && <label className="text-xs font-semibold text-[#747b8b]">Trend segment<select aria-label="Retention trend segment" value={activeSegment} onChange={(event) => setTrendSegment(event.target.value)} className="ml-2 h-9 rounded-lg border border-[#dfe3ea] bg-white px-2 text-sm font-normal text-[#252936]">{availableSegments.map((segment) => <option key={segment}>{segment}</option>)}</select></label>}
      </div>
      <div className="max-h-[390px] overflow-auto"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-[#fafbfc] text-xs text-[#747b8b]"><tr><th className="px-4 py-3">Cohort week</th><th className="px-4 py-3">Cohort size</th>{result.heatmap.x_labels.map((window) => <th key={window} className="px-4 py-3">{window}</th>)}</tr></thead><tbody>{result.heatmap.y_labels.map((cohort, rowIndex) => <tr key={cohort} className="border-t border-[#edf0f4]"><td className="px-4 py-3 font-semibold">{cohort}</td><td className="px-4 py-3 text-[#6d7484]">{result.heatmap.cohort_sizes[rowIndex]?.toLocaleString() ?? "—"}</td>{result.heatmap.matrix[rowIndex]?.map((value, index) => <td key={`${cohort}-${index}`} className="px-4 py-3">{value == null ? "—" : `${(value * 100).toFixed(1)}%`}</td>)}</tr>)}</tbody></table></div>
      <div className="border-t border-[#e5e8ee] p-4 text-xs text-[#7b8292]">Executed in {result.execution_ms.toFixed(0)}ms · Data through {result.dataset_as_of} · UTC cohorts · validated SQL</div>
    </Card>
  </>;
}

function AcquisitionResults({ result }: { result: AcquisitionResponse }) {
  const chart: ChartSpec = {
    chart_type: "stacked_bar",
    title: "Acquisition funnel by segment",
    x: "segment",
    y: "users",
    series: "stage",
    data: result.segments.flatMap((row) => [
      { segment: row.segment, stage: "Visitors", users: row.visitors },
      { segment: row.segment, stage: "Signups", users: row.signups },
      { segment: row.segment, stage: "Activated", users: row.activated_users },
      { segment: row.segment, stage: "Paid", users: row.paid_users },
    ]),
    x_labels: [],
    y_labels: [],
    matrix: [],
    description: "Stacked bar chart comparing visitor, signup, activated, and paid-user counts by acquisition segment.",
  };
  return <div className="space-y-5"><div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]"><Card className="p-4"><AnalyticsChart spec={chart}/></Card><Card className="overflow-hidden"><div className="border-b border-[#e5e8ee] p-4"><div className="eyebrow">Segment table</div><p className="mt-1 text-xs text-[#747b8b]">Current period: {result.period.label}</p></div><div className="max-h-[390px] overflow-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="bg-[#fafbfc] text-xs text-[#747b8b]"><tr><th className="px-4 py-3">Segment</th><th className="px-4 py-3">Visitors</th><th className="px-4 py-3">Signups</th><th className="px-4 py-3">Activated</th><th className="px-4 py-3">Paid</th><th className="px-4 py-3">Signup %</th><th className="px-4 py-3">Activation %</th><th className="px-4 py-3">Paid %</th></tr></thead><tbody>{result.segments.map((row)=><tr key={row.segment} className="border-t border-[#edf0f4]"><td className="px-4 py-3 font-semibold">{row.segment}</td><td className="px-4 py-3">{row.visitors.toLocaleString()}</td><td className="px-4 py-3">{row.signups.toLocaleString()}</td><td className="px-4 py-3">{row.activated_users.toLocaleString()}</td><td className="px-4 py-3">{row.paid_users.toLocaleString()}</td><td className="px-4 py-3">{(row.signup_conversion*100).toFixed(1)}%</td><td className="px-4 py-3">{(row.activation_conversion*100).toFixed(1)}%</td><td className="px-4 py-3">{(row.paid_conversion*100).toFixed(1)}%</td></tr>)}</tbody></table></div></Card></div><Card className="p-4 text-xs text-[#7b8292]">Data through {result.dataset_as_of} · {result.segments.length} segments · validated SQL · executed in {result.execution_ms.toFixed(0)}ms</Card></div>;
}

function FeatureAdoptionResults({ result }: { result: FeatureAdoptionResponse }) {
  const segmentLabel = result.dimension && result.dimension !== "feature" ? result.dimension.replaceAll("_", " ") : "feature";
  const chart: ChartSpec = {
    chart_type: "bar",
    title: `${segmentLabel} adoption rate`,
    x: "feature",
    y: "adoption_rate",
    data: result.rows.map((row) => ({ feature: row.feature, adoption_rate: row.adoption_rate })),
    x_labels: [],
    y_labels: [],
    matrix: [],
    description: "Bar chart comparing feature adoption rates. The D30 comparison is observational and does not establish causation.",
  };
  return <div className="space-y-5"><div className="grid gap-5 xl:grid-cols-[1.15fr_1.85fr]"><Card className="p-4"><AnalyticsChart spec={chart}/></Card><Card className="overflow-hidden"><div className="border-b border-[#e5e8ee] p-4"><div className="eyebrow">Feature detail</div><p className="mt-1 text-xs text-[#747b8b]">D30 retention is shown only for mature users; n values are eligible mature samples.</p></div><div className="max-h-[390px] overflow-auto"><table className="w-full min-w-[1120px] text-left text-sm"><thead className="bg-[#fafbfc] text-xs text-[#747b8b]"><tr><th className="px-4 py-3">{segmentLabel}</th><th className="px-4 py-3">Eligible</th><th className="px-4 py-3">Adopting</th><th className="px-4 py-3">Adoption rate</th><th className="px-4 py-3">Total uses</th><th className="px-4 py-3">Uses / adopter</th><th className="px-4 py-3">D30 users</th><th className="px-4 py-3">D30 non-users</th><th className="px-4 py-3">Association</th></tr></thead><tbody>{result.rows.map((row)=><tr key={row.feature} className="border-t border-[#edf0f4]"><td className="px-4 py-3 font-semibold">{row.feature}</td><td className="px-4 py-3">{row.eligible_users.toLocaleString()}</td><td className="px-4 py-3">{row.adopting_users.toLocaleString()}</td><td className="px-4 py-3">{(row.adoption_rate*100).toFixed(1)}%</td><td className="px-4 py-3">{row.total_uses.toLocaleString()}</td><td className="px-4 py-3">{row.uses_per_adopter.toFixed(1)}</td><td className="px-4 py-3">{row.feature_user_d30 == null ? "—" : `${(row.feature_user_d30*100).toFixed(1)}% (n=${row.feature_d30_sample_size.toLocaleString()})`}</td><td className="px-4 py-3">{row.non_feature_user_d30 == null ? "—" : `${(row.non_feature_user_d30*100).toFixed(1)}% (n=${row.non_feature_d30_sample_size.toLocaleString()})`}</td><td className="px-4 py-3">{row.association_delta == null ? "—" : `${row.association_delta >= 0 ? "+" : ""}${(row.association_delta*100).toFixed(1)}pp`}</td></tr>)}</tbody></table></div></Card></div><Card className="border-[#e4e1ff] bg-[#faf9ff] p-4 text-xs leading-5 text-[#68627f]">Feature adoption and D30 differences are observational associations. They do not establish that using a feature causes higher retention.</Card></div>;
}

export function AnalyticsModule({ module }: { module: ModuleName }) {
  const config = configs[module];
  const [dimension, setDimension] = useState(typeof config.body.dimension === "string" ? config.body.dimension : "");
  const isRetention = module === "retention" || module === "cohorts";
  const mutation = useMutation({
    mutationFn: () => api<AnalyticsResult | AcquisitionResponse | FeatureAdoptionResponse>(config.endpoint, {
      method: "POST",
      body: JSON.stringify({ ...config.body, ...(dimension ? { dimension } : {}) }),
    }),
  });
  const result = mutation.data;
  const retention = isRetentionResult(result);
  const acquisition = isAcquisitionResult(result);
  const featureAdoption = isFeatureAdoptionResult(result);
  const funnel = Boolean(result && "segments" in result && !retention && !acquisition);
  const genericResult = result && !retention && !acquisition && !featureAdoption ? result : undefined;
  const rows: Record<string, unknown>[] = genericResult
    ? (funnel ? Object.values((genericResult as FunnelResult).segments)[0] ?? [] : (genericResult as MetricResult).current)
    : [];
  const spec = genericResult ? {
    chart_type: (funnel ? "funnel" : "bar") as "funnel" | "bar",
    title: funnel ? `${(genericResult as FunnelResult).funnel} funnel` : `${(genericResult as MetricResult).metric.label} by ${dimension || "segment"}`,
    x: funnel ? "stage" : "segment",
    y: funnel ? "users" : "value",
    data: rows as Record<string, string | number | null>[],
    x_labels: [],
    y_labels: [],
    matrix: [],
    description: funnel ? "Funnel chart showing users remaining at each product journey stage." : "Bar chart comparing the governed metric across segments.",
  } satisfies ChartSpec : null;

  return <>
    <PageHeading eyebrow="Product analytics" title={config.title} description={config.description} action={<Button asChild variant="secondary"><Link href={`/copilot?question=${encodeURIComponent(config.question)}`}><Sparkles size={15} /> Ask Copilot</Link></Button>} />
    <Card className="mb-5 flex flex-col gap-4 p-4 sm:flex-row sm:items-end"><div className="flex-1"><label htmlFor="dimension" className="eyebrow">{isRetention ? "Trend breakdown" : "Breakdown"}</label><select id="dimension" value={dimension} onChange={(event) => setDimension(event.target.value)} className="mt-2 h-10 w-full rounded-lg border border-[#dfe3ea] bg-white px-3 text-sm sm:max-w-xs"><option value="">Overall</option><option value="channel">Channel</option><option value="campaign">Campaign</option><option value="device">Device</option><option value="browser">Browser</option><option value="country">Country</option><option value="plan">Plan</option><option value="company_size">Company size</option>{module === "feature-adoption" && <option value="feature">Feature</option>}</select></div><Button onClick={() => mutation.mutate()} disabled={mutation.isPending}><Play size={15} />{mutation.isPending ? "Analyzing…" : "Run analysis"}</Button></Card>
    {mutation.isError && <Card className="border-[#ffd9dd] bg-[#fffafb] p-5"><Badge tone="warning">Analysis unavailable</Badge><p className="mt-3 text-sm text-[#6f7686]">{mutation.error.message}</p></Card>}
    {!result && !mutation.isPending && !mutation.isError && <Card className="grid min-h-[390px] place-items-center p-8 text-center"><div><div className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[#f0efff] text-[#635bff]"><Filter size={20} /></div><h2 className="mt-4 font-bold">Ready to analyze</h2><p className="mt-2 max-w-sm text-sm leading-6 text-[#747b8b]">Choose a governed breakdown and run the analysis. SQL and methodology remain inspectable.</p></div></Card>}
    {mutation.isPending && <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]"><div className="skeleton h-[390px]" /><div className="skeleton h-[390px]" /></div>}
    {retention && <RetentionResults result={result} />}
    {acquisition && <AcquisitionResults result={result} />}
    {featureAdoption && <FeatureAdoptionResults result={result} />}
    {genericResult && spec && <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]"><Card className="p-4"><AnalyticsChart spec={spec} /></Card><Card className="overflow-hidden"><div className="border-b border-[#e5e8ee] p-4"><div className="eyebrow">Result table</div>{funnel && (genericResult as FunnelResult).comparison_period && <p className="mt-1 text-xs text-[#747b8b]">Comparison: {(genericResult as FunnelResult).comparison_period?.label}</p>}</div><div className="max-h-[360px] overflow-auto"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-[#fafbfc] text-xs text-[#747b8b]"><tr><th className="px-4 py-3">{funnel ? "Stage" : "Segment"}</th><th className="px-4 py-3">{funnel ? "Users" : "Value"}</th><th className="px-4 py-3">{funnel ? "Stage conversion" : "Sample"}</th></tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t border-[#edf0f4]"><td className="px-4 py-3 font-semibold">{String(row[funnel ? "stage" : "segment"])}</td><td className="px-4 py-3">{funnel ? Number(row.users).toLocaleString() : `${(Number(row.value) * 100).toFixed(1)}%`}</td><td className="px-4 py-3 text-[#6d7484]">{funnel ? `${(Number(row.stage_conversion) * 100).toFixed(1)}%` : Number(row.denominator).toLocaleString()}</td></tr>)}</tbody></table></div><div className="border-t border-[#e5e8ee] p-4 text-xs text-[#7b8292]">Executed in {((genericResult as FunnelResult | MetricResult).execution_ms).toFixed(0)}ms · Data through {genericResult.dataset_as_of} · UTC periods · validated SQL</div></Card></div>}
  </>;
}
