"use client";

import Link from "next/link";
import { ArrowRight, BarChart3, Download, FileText, RefreshCw, ShieldAlert } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getWeeklyReport, weeklyReportMarkdownUrl } from "@/lib/api";
import type { AnomalyRecord, ReportMetric, WeeklyReportResponse } from "@/lib/types";
import { Badge, Button, Card } from "@/components/ui";
import { PageHeading } from "@/components/page-heading";

function changeText(metric: ReportMetric) {
  if (metric.relative_delta == null) return "Unavailable";
  return `${metric.relative_delta >= 0 ? "+" : "−"}${Math.abs(metric.relative_delta * 100).toFixed(1)}%`;
}

function ReportMetricRow({ metric }: { metric: ReportMetric }) {
  const positive = (metric.relative_delta ?? 0) >= 0;
  return <div className="rounded-xl border border-[#edf0f4] p-3"><div className="flex items-center justify-between gap-3"><span className="text-sm font-semibold">{metric.label}</span><span className={`text-xs font-bold ${metric.relative_delta == null ? "text-[#858c9b]" : positive ? "text-[#16875d]" : "text-[#c63f4f]"}`}>{changeText(metric)}</span></div><div className="mt-2 flex items-end justify-between gap-3"><span className="text-xl font-bold">{metric.current?.formatted ?? "Unavailable"}</span><span className="text-xs text-[#858c9b]">vs {metric.previous?.formatted ?? "—"}</span></div></div>;
}

function ReportAnomaly({ item }: { item: AnomalyRecord }) {
  return <div className="rounded-xl border border-[#edf0f4] p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Badge tone={item.severity === "critical" ? "warning" : "accent"}>{item.severity}</Badge><span className="font-semibold">{item.metric_label}{item.segment ? ` · ${item.segment}` : ""}</span></div><span className="text-xs text-[#858c9b]">{item.period.label}</span></div><p className="mt-2 text-sm leading-5 text-[#697080]">{item.summary}</p><div className="mt-3 flex flex-wrap items-center gap-3 text-xs"><span><strong>{item.observed.formatted}</strong> observed</span><span className="text-[#858c9b]">baseline {item.baseline.formatted}</span><Link className="font-semibold text-[#5148d9]" href={`/copilot?question=${encodeURIComponent(item.copilot_question)}`}>Investigate <ArrowRight className="inline" size={13} /></Link></div></div>;
}

function ReportView({ report }: { report: WeeklyReportResponse }) {
  return <>
    <Card className="mb-5 border-[#e4e1ff] bg-[#faf9ff] p-5"><div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#eeecff] text-[#635bff]"><FileText size={19} /></div><div><div className="eyebrow">Executive summary</div><h2 className="mt-2 text-xl font-bold">{report.headline}</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-[#626a7a]">{report.summary}</p></div></div></Card>
    {report.warnings.length > 0 && <Card className="mb-5 border-[#f0d9ad] bg-[#fffaf0] p-4 text-sm text-[#7d5a1a]"><div className="flex items-center gap-2 font-semibold"><ShieldAlert size={16} /> Some report inputs were unavailable</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></Card>}
    <div className="grid gap-5 lg:grid-cols-2">{report.sections.map((section) => <Card key={section.key} className="p-5"><div className="flex items-center gap-2"><BarChart3 size={17} className="text-[#635bff]" /><div className="eyebrow">{section.title}</div></div><p className="mt-3 text-sm leading-5 text-[#697080]">{section.summary}</p><div className="mt-4 space-y-2">{section.metrics.map((metric) => <ReportMetricRow key={metric.metric} metric={metric} />)}</div></Card>)}</div>
    <Card className="mt-5 p-5"><div className="flex items-center justify-between gap-3"><div><div className="eyebrow">Anomalies</div><h2 className="mt-2 text-lg font-bold">Signals from the completed week</h2></div><Badge tone={report.anomalies.length > 0 ? "warning" : "success"}>{report.anomalies.length} detected</Badge></div><div className="mt-4 space-y-3">{report.anomalies.length > 0 ? report.anomalies.map((item) => <ReportAnomaly key={item.id} item={item} />) : <p className="rounded-xl bg-[#f8f9fb] p-4 text-sm text-[#697080]">No material anomalies crossed the configured policy.</p>}</div></Card>
    <div className="mt-5 grid gap-5 lg:grid-cols-2"><Card className="p-5"><div className="eyebrow">Key drivers</div><h2 className="mt-2 text-lg font-bold">Where to look first</h2>{report.drivers.length > 0 ? <div className="mt-4 space-y-2">{report.drivers.slice(0, 6).map((driver) => <div key={`${driver.dimension}-${driver.segment}`} className="flex items-center justify-between rounded-xl border border-[#edf0f4] px-3 py-3 text-sm"><div><span className="font-semibold">{driver.segment}</span><span className="ml-2 text-xs text-[#858c9b]">{driver.dimension.replaceAll("_", " ")}</span></div><span className="text-xs font-bold text-[#5148d9]">sample {driver.sample_size.toLocaleString()}</span></div>)}</div> : <p className="mt-4 rounded-xl bg-[#f8f9fb] p-4 text-sm text-[#697080]">No segment drivers were available.</p>}</Card><Card className="p-5"><div className="eyebrow">Recommended actions</div><h2 className="mt-2 text-lg font-bold">Turn signals into next steps</h2><div className="mt-4 space-y-3">{report.recommendations.length > 0 ? report.recommendations.map((recommendation, index) => <div key={`${recommendation.action}-${index}`} className="rounded-xl border border-[#edf0f4] p-4"><div className="flex items-center justify-between gap-3"><span className="text-sm font-semibold">{recommendation.action}</span><Badge tone={recommendation.priority === "high" ? "warning" : "neutral"}>{recommendation.priority}</Badge></div><p className="mt-2 text-xs leading-5 text-[#697080]">{recommendation.expected_impact}</p><p className="mt-2 text-xs font-semibold leading-5 text-[#5148d9]">Validate: {recommendation.how_to_validate}</p></div>) : <p className="text-sm text-[#697080]">Continue monitoring the governed metrics.</p>}</div></Card></div>
    <details className="panel mt-5 p-5"><summary className="cursor-pointer text-sm font-bold">How this report was calculated</summary><div className="mt-4 grid gap-3 text-xs text-[#697080] sm:grid-cols-2"><div>Daily UTC buckets · {report.methodology.baseline_days}-day rolling baseline</div><div>Minimum sample size · {report.methodology.minimum_sample_size.toLocaleString()}</div><div>{report.sql.metrics.length} governed metrics · {report.sql.query_count} validated statements</div><div>Provider · {report.metadata.provider} · {report.metadata.execution_ms.toFixed(0)}ms</div></div><p className="mt-4 text-xs leading-5 text-[#858c9b]">Anomalies identify unusual movement and do not establish causation. Retention values are shown only for mature cohorts.</p></details>
    <Card className="mt-5 flex flex-col gap-2 p-4 text-xs text-[#7b8292] sm:flex-row sm:items-center sm:justify-between"><span>{report.period.label} · Data through {report.dataset_as_of}</span><span>{report.follow_up_questions.length} suggested follow-up questions</span></Card>
  </>;
}

export function WeeklyReport() {
  const query = useQuery({ queryKey: ["weekly-report", "last_week"], queryFn: () => getWeeklyReport(), staleTime: 300_000 });
  return <>
    <PageHeading eyebrow="Proactive analytics" title="Weekly product report" description="A deterministic weekly readout of growth, activation, engagement, retention, revenue, and the signals worth investigating." action={<div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw size={15} className={query.isFetching ? "animate-spin" : ""} /> Refresh</Button><Button asChild variant="secondary"><a href={weeklyReportMarkdownUrl()} target="_blank" rel="noreferrer"><Download size={15} /> Download Markdown</a></Button></div>} />
    {query.isLoading && <div className="space-y-5"><div className="skeleton h-32"/><div className="grid gap-5 lg:grid-cols-2"><div className="skeleton h-64"/><div className="skeleton h-64"/><div className="skeleton h-64"/><div className="skeleton h-64"/></div></div>}
    {query.isError && <Card className="border-[#ffd8dc] bg-[#fffafb] p-6"><Badge tone="warning">Report unavailable</Badge><h2 className="mt-3 text-lg font-bold">The weekly report could not be loaded</h2><p className="mt-2 text-sm text-[#707786]">{query.error.message}</p><Button className="mt-5" variant="secondary" onClick={() => void query.refetch()}>Try again</Button></Card>}
    {query.data && <ReportView report={query.data} />}
  </>;
}
