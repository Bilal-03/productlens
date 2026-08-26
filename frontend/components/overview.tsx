"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowRight, Database, ShieldCheck, Sparkles } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { api, getAccessToken, getOverviewSummary } from "@/lib/api";
import { Card, Button } from "@/components/ui";
import { MetricCard } from "@/components/metric-card";
import { AnalyticsChart } from "@/components/chart";
import { PageHeading } from "@/components/page-heading";
import type { ChartSpec, OverviewResponse } from "@/lib/types";

const metricNames = ["mau", "activation_rate", "checkout_conversion", "mrr", "d30_retention", "churn_rate"];

function format(value: number, formatName: string) { if (formatName === "percentage") return `${(value * 100).toFixed(1)}%`; if (formatName === "currency") return `$${value.toLocaleString(undefined,{maximumFractionDigits:0})}`; return value.toLocaleString(undefined,{maximumFractionDigits:0}); }

export function Overview() {
  const auth = useAuth();
  const accessScope = auth.session?.access_token ?? getAccessToken() ?? "anonymous";
  const summary = useQuery({
    queryKey: ["overview-summary", accessScope],
    queryFn: () => getOverviewSummary("last_30_days"),
    staleTime: 300_000,
    retry: false,
  });
  const overview = useQuery({
    queryKey: ["overview", accessScope],
    queryFn: () => api<OverviewResponse>("/analytics/overview", { method: "POST", body: JSON.stringify({ period: "last_30_days" }) }),
    staleTime: 300_000,
    retry: false,
    enabled: summary.isSuccess,
  });
  // Keep a small fallback for a temporarily unavailable summary endpoint.
  // Normal loads render the summary first and defer the extended overview.
  const fallbackMetrics = useQueries({ queries: metricNames.map((metric) => ({
    queryKey: ["metric", accessScope, metric],
    enabled: summary.isError,
    retry: false,
    queryFn: () => api<{ metric: { label: string; format: string }; current: { value: number }[]; previous: { value: number }[]; current_period: { label: string } }>("/analytics/kpi", { method: "POST", body: JSON.stringify({ metric, period: metric === "d30_retention" ? "last_90_days" : "last_30_days" }) }),
  })) });
  const overviewData = overview.data;
  const summaryData = summary.data;
  const revenue = overviewData?.kpis.mrr ?? fallbackMetrics[3].data;
  const chartData = revenue ? { chart_type: "bar" as const, title: "Current vs previous MRR", x: "period", y: "value", data: [{ period: "Previous", value: revenue.previous?.[0]?.value ?? 0 }, { period: "Current", value: revenue.current?.[0]?.value ?? 0 }], x_labels: [], y_labels: [], matrix: [], description: "Bar chart comparing monthly recurring revenue across two periods." } : null;
  const revenueChart: ChartSpec | null = overviewData ? { chart_type: "line", title: "Net revenue trend", x: "label", y: "value", data: overviewData.revenue_trend.points.map((point) => ({ label: point.label, value: point.value })), x_labels: [], y_labels: [], matrix: [], description: "Line chart showing net revenue over the last completed periods." } : null;
  const growthChart: ChartSpec | null = overviewData ? { chart_type: "line", title: "Signup growth trend", x: "label", y: "value", data: overviewData.user_growth_trend.points.map((point) => ({ label: point.label, value: point.value })), x_labels: [], y_labels: [], matrix: [], description: "Line chart showing signup volume over the resolved UTC period." } : null;
  const acquisitionChart: ChartSpec | null = overviewData ? { chart_type: "bar", title: "Acquisition visitors by channel", x: "segment", y: "visitors", data: overviewData.acquisition.segments.map((row) => ({ segment: row.segment, visitors: row.visitors })), x_labels: [], y_labels: [], matrix: [], description: "Bar chart comparing acquisition visitors by channel." } : null;
  const retentionChart: ChartSpec | null = overviewData ? { chart_type: "heatmap", title: "Retention snapshot", x_labels: overviewData.retention_snapshot.heatmap.x_labels, y_labels: overviewData.retention_snapshot.heatmap.y_labels, matrix: overviewData.retention_snapshot.heatmap.matrix, data: [], description: "Retention heatmap by weekly signup cohort. Blank cells indicate immature windows." } : null;
  return <>
    <PageHeading eyebrow="Analytics overview" title="Your product, in focus" description="A governed view of growth, activation, monetization, and retention. Every metric resolves through the same semantic layer used by Copilot." action={<Button asChild><Link href="/copilot"><Sparkles size={16}/> Ask a question</Link></Button>} />
    <div className="mb-7 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
      {metricNames.map((name, index) => {
        const payload = overviewData?.kpis[name] ?? summaryData?.kpis[name] ?? fallbackMetrics[index].data;
        const current = payload?.current?.[0]?.value ?? 0;
        const previous = payload?.previous?.[0]?.value ?? 0;
        const loading = !payload && (summary.isLoading || overview.isLoading || fallbackMetrics[index].isLoading);
        const unavailable = !payload && !loading && (summary.isError || overview.isError || fallbackMetrics[index].isError);
        return <MetricCard key={name} label={payload?.metric?.label ?? name.replaceAll("_", " ")} value={unavailable ? "Unavailable" : payload ? format(current, payload.metric?.format ?? "integer") : "—"} delta={payload && previous ? (current - previous) / Math.abs(previous) : null} note={unavailable ? "Database may be paused" : payload?.current_period?.label ?? "Loading governed metric"} loading={loading}/>;
      })}
    </div>
    <div className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
      <Card className="min-h-[410px] p-3 md:p-5">{chartData ? <AnalyticsChart spec={chartData}/> : <div className="skeleton h-[350px] w-full"/>}</Card>
      <div className="grid gap-5">
        <Card className="p-5"><div className="flex items-center justify-between"><div><div className="eyebrow">Flagship investigation</div><h2 className="mt-2 text-lg font-bold">Checkout conversion incident</h2></div><div className="rounded-xl bg-[#eeecff] p-3 text-[#5148d9]"><Sparkles size={20}/></div></div><p className="mt-3 text-sm leading-6 text-[#697080]">Ask why checkout conversion fell last week. Deep Dive checks device, browser, and channel contribution before forming a hypothesis.</p><Button asChild variant="secondary" className="mt-5 w-full"><Link href="/copilot?question=Why%20did%20checkout%20conversion%20fall%20last%20week%3F">Run investigation <ArrowRight size={15}/></Link></Button></Card>
        <div className="grid grid-cols-2 gap-3"><Card className="p-4"><ShieldCheck size={19} className="text-[#16875d]"/><div className="mt-3 text-sm font-bold">Read-only SQL</div><p className="mt-1 text-xs leading-5 text-[#7b8292]">AST validation and database permissions</p></Card><Card className="p-4"><Database size={19} className="text-[#5148d9]"/><div className="mt-3 text-sm font-bold">Synthetic data</div><p className="mt-1 text-xs leading-5 text-[#7b8292]">Known, testable business scenarios</p></Card></div>
      </div>
    </div>
    <div className="mt-6"><div className="eyebrow">Complete product view</div><h2 className="mt-2 text-xl font-bold">Growth, acquisition, and retention context</h2>{(overview.isError || (summary.isError && !overviewData))&&<Card className="mt-4 border-[#ffd9dd] bg-[#fffafb] p-5"><p className="text-sm text-[#6f7686]">The extended overview is temporarily unavailable. Headline KPIs remain available above.</p></Card>}{(summary.isLoading || overview.isLoading)&&<div className="mt-4 grid gap-5 lg:grid-cols-2"><div className="skeleton h-[300px]"/><div className="skeleton h-[300px]"/><div className="skeleton h-[300px]"/><div className="skeleton h-[300px]"/></div>}{overviewData&&<div className="mt-4 grid gap-5 lg:grid-cols-2">{revenueChart&&<Card className="p-4"><AnalyticsChart spec={revenueChart}/></Card>}{growthChart&&<Card className="p-4"><AnalyticsChart spec={growthChart}/></Card>}{acquisitionChart&&<Card className="p-4"><AnalyticsChart spec={acquisitionChart}/></Card>}{retentionChart&&<Card className="p-4"><AnalyticsChart spec={retentionChart}/></Card>}<Card className="overflow-hidden lg:col-span-2"><div className="border-b border-[#e5e8ee] p-4"><div className="eyebrow">Activation funnel</div><p className="mt-1 text-xs text-[#747b8b]">Stage counts for the onboarding journey.</p></div><div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="bg-[#fafbfc] text-xs text-[#747b8b]"><tr><th className="px-4 py-3">Segment</th><th className="px-4 py-3">Stage</th><th className="px-4 py-3">Users</th></tr></thead><tbody>{Object.entries(overviewData.activation_funnel.segments).flatMap(([segment, rows])=>rows.map((row,index)=><tr key={`${segment}-${row.stage}`} className="border-t border-[#edf0f4]"><td className="px-4 py-3 font-semibold">{index===0?segment:""}</td><td className="px-4 py-3">{row.stage}</td><td className="px-4 py-3">{row.users.toLocaleString()}</td></tr>))}</tbody></table></div></Card></div>}</div>
  </>;
}
