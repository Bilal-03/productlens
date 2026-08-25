"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowRight, Database, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { Card, Button } from "@/components/ui";
import { MetricCard } from "@/components/metric-card";
import { AnalyticsChart } from "@/components/chart";
import { PageHeading } from "@/components/page-heading";

type MetricPayload = { metric: { name: string; label: string; format: string }; current: { value: number }[]; previous: { value: number }[]; current_period: { label: string } };
const metricNames = ["mau", "activation_rate", "checkout_conversion", "mrr", "d30_retention", "churn_rate"];

function format(value: number, formatName: string) { if (formatName === "percentage") return `${(value * 100).toFixed(1)}%`; if (formatName === "currency") return `$${value.toLocaleString(undefined,{maximumFractionDigits:0})}`; return value.toLocaleString(undefined,{maximumFractionDigits:0}); }

export function Overview() {
  const metrics = useQueries({ queries: metricNames.map((metric) => ({ queryKey: ["metric", metric], queryFn: () => api<MetricPayload>("/analytics/kpi", { method: "POST", body: JSON.stringify({ metric, period: metric === "d30_retention" ? "last_90_days" : "last_30_days" }) }) })) });
  const revenue = metrics[3].data;
  const chartData = revenue ? { chart_type: "bar" as const, title: "Current vs previous MRR", x: "period", y: "value", data: [{ period: "Previous", value: revenue.previous[0]?.value ?? 0 }, { period: "Current", value: revenue.current[0]?.value ?? 0 }], x_labels: [], y_labels: [], matrix: [], description: "Bar chart comparing monthly recurring revenue across two periods." } : null;
  return <>
    <PageHeading eyebrow="Analytics overview" title="Your product, in focus" description="A governed view of growth, activation, monetization, and retention. Every metric resolves through the same semantic layer used by Copilot." action={<Button asChild><Link href="/copilot"><Sparkles size={16}/> Ask a question</Link></Button>} />
    <div className="mb-7 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
      {metricNames.map((name, index) => { const query = metrics[index]; const payload = query.data; const current = payload?.current[0]?.value ?? 0; const previous = payload?.previous[0]?.value ?? 0; return <MetricCard key={name} label={payload?.metric.label ?? name.replaceAll("_"," ")} value={query.isError ? "Unavailable" : payload ? format(current,payload.metric.format) : "—"} delta={payload && previous ? (current-previous)/Math.abs(previous) : null} note={query.isError ? "Database may be paused" : payload?.current_period.label ?? "Loading governed metric"} loading={query.isLoading}/>; })}
    </div>
    <div className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
      <Card className="min-h-[410px] p-3 md:p-5">{chartData ? <AnalyticsChart spec={chartData}/> : <div className="skeleton h-[350px] w-full"/>}</Card>
      <div className="grid gap-5">
        <Card className="p-5"><div className="flex items-center justify-between"><div><div className="eyebrow">Flagship investigation</div><h2 className="mt-2 text-lg font-bold">Checkout conversion incident</h2></div><div className="rounded-xl bg-[#eeecff] p-3 text-[#5148d9]"><Sparkles size={20}/></div></div><p className="mt-3 text-sm leading-6 text-[#697080]">Ask why checkout conversion fell last week. Deep Dive checks device, browser, and channel contribution before forming a hypothesis.</p><Button asChild variant="secondary" className="mt-5 w-full"><Link href="/copilot?question=Why%20did%20checkout%20conversion%20fall%20last%20week%3F">Run investigation <ArrowRight size={15}/></Link></Button></Card>
        <div className="grid grid-cols-2 gap-3"><Card className="p-4"><ShieldCheck size={19} className="text-[#16875d]"/><div className="mt-3 text-sm font-bold">Read-only SQL</div><p className="mt-1 text-xs leading-5 text-[#7b8292]">AST validation and database permissions</p></Card><Card className="p-4"><Database size={19} className="text-[#5148d9]"/><div className="mt-3 text-sm font-bold">Synthetic data</div><p className="mt-1 text-xs leading-5 text-[#7b8292]">Known, testable business scenarios</p></Card></div>
      </div>
    </div>
  </>;
}
