"use client";

import { useCallback, useState } from "react";
import { ArrowRight, RefreshCw, ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getProductPulse } from "@/lib/api";
import type { AnomalyRecord, Evidence, ProductPulseResponse } from "@/lib/types";
import { Badge, Button, Card } from "@/components/ui";
import { PageHeading } from "@/components/page-heading";
import { useAnalyticsStream } from "@/lib/use-analytics-stream";

type PulsePeriod = "last_30_days" | "last_90_days";

function contributionText(item: AnomalyRecord, contribution: number) {
  if (item.metric_format === "percentage") return `${contribution >= 0 ? "+" : ""}${(contribution * 100).toFixed(1)}pp`;
  if (item.metric_format === "currency") return `${contribution >= 0 ? "+" : "−"}$${Math.abs(contribution).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  return `${contribution >= 0 ? "+" : "−"}${Math.abs(contribution).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function AnomalyCard({ item, evidence }: { item: AnomalyRecord; evidence: Evidence[] }) {
  const isIncrease = item.direction === "increase";
  const itemEvidence = evidence.filter((entry) => item.evidence_ids.includes(entry.id));
  return <Card className="flex h-full flex-col p-5">
    <div className="flex items-start justify-between gap-3">
      <div className="flex items-center gap-2">
        <div className={`grid h-9 w-9 place-items-center rounded-xl ${item.severity === "critical" ? "bg-[#fff0f1] text-[#c63f4f]" : "bg-[#fff5e7] text-[#9b6017]"}`}>
          <ShieldAlert size={17} />
        </div>
        <div><div className="text-sm font-bold">{item.metric_label}</div>{item.segment && <div className="mt-1 text-[11px] font-semibold text-[#5148d9]">{item.segment}</div>}<div className="mt-1 text-[11px] text-[#858c9b]">{item.period.label}</div></div>
      </div>
      <Badge tone={item.severity === "critical" ? "warning" : "accent"}>{item.severity}</Badge>
    </div>
    <div className="mt-6 grid grid-cols-2 gap-3 rounded-xl bg-[#f8f9fb] p-3">
      <div><div className="text-[10px] font-bold uppercase tracking-[.12em] text-[#9299a8]">Observed</div><div className="mt-1 text-xl font-bold">{item.observed.formatted}</div><div className="mt-1 text-[11px] text-[#858c9b]">{item.observed.label}</div><div className="mt-1 text-[11px] font-semibold text-[#697080]">sample {item.sample_size.toLocaleString()}</div></div>
      <div><div className="text-[10px] font-bold uppercase tracking-[.12em] text-[#9299a8]">Baseline</div><div className="mt-1 text-xl font-bold">{item.baseline.formatted}</div><div className="mt-1 text-[11px] text-[#858c9b]">28-day rolling average</div></div>
    </div>
    <div className={`mt-4 flex items-center gap-2 text-sm font-bold ${isIncrease ? "text-[#16875d]" : "text-[#c63f4f]"}`}>
      {isIncrease ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
      {item.relative_delta == null ? "Change unavailable" : `${isIncrease ? "+" : "−"}${Math.abs(item.relative_delta * 100).toFixed(1)}% vs baseline`}
      {item.z_score == null ? <span className="text-xs font-normal text-[#858c9b]">zero baseline variance</span> : <span className="text-xs font-normal text-[#858c9b]">z {item.z_score.toFixed(2)}</span>}
    </div>
    <p className="mt-3 text-sm leading-6 text-[#697080]">{item.summary}</p>
    {itemEvidence.length > 0 && <details className="mt-3 rounded-lg border border-[#edf0f4] px-3 py-2"><summary className="cursor-pointer text-xs font-bold text-[#596071]">Evidence ({itemEvidence.length})</summary><div className="mt-2 space-y-2 text-xs text-[#697080]">{itemEvidence.map((entry) => <div key={entry.id}><div className="font-semibold">{entry.label}</div><div>{entry.value}</div><div className="text-[#858c9b]">{entry.detail}</div></div>)}</div></details>}
    <div className="mt-4 flex-1">
      <div className="eyebrow">Largest measured contributors</div>
      {item.drivers.length > 0 ? <div className="mt-2 space-y-2">{item.drivers.slice(0, 3).map((driver) => <div key={`${driver.dimension}-${driver.segment}`} className="flex items-center justify-between rounded-lg border border-[#edf0f4] px-3 py-2 text-xs"><span className="min-w-0 truncate font-semibold">{driver.segment}<span className="ml-1 font-normal text-[#858c9b]">· {driver.dimension.replaceAll("_", " ")}</span></span><span className="ml-3 shrink-0 font-bold text-[#5148d9]">{contributionText(item, driver.contribution)}</span></div>)}</div> : <p className="mt-2 text-xs text-[#858c9b]">No segment drill-down was available for this signal.</p>}
    </div>
    <Button asChild variant="secondary" className="mt-5 w-full"><Link href={`/copilot?question=${encodeURIComponent(item.copilot_question)}`}>
      Investigate in Copilot <ArrowRight size={15} />
    </Link></Button>
  </Card>;
}

function PulseResults({ result }: { result: ProductPulseResponse }) {
  return <>
    {result.warnings.length > 0 && <Card className="mb-5 border-[#f0d9ad] bg-[#fffaf0] p-4 text-sm text-[#7d5a1a]"><div className="flex items-center gap-2 font-semibold"><ShieldAlert size={16} /> Partial signal coverage</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></Card>}
    {result.items.length === 0 ? <Card className="grid min-h-80 place-items-center p-8 text-center"><div><div className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[#e8f7f1] text-[#16875d]"><TrendingUp size={21} /></div><h2 className="mt-4 font-bold">No material signals detected</h2><p className="mt-2 max-w-md text-sm leading-6 text-[#747b8b]">The governed metrics stayed within the configured rolling baseline policy for this period.</p></div></Card> : <div className="grid gap-5 lg:grid-cols-2">{result.items.map((item) => <AnomalyCard key={item.id} item={item} evidence={result.evidence} />)}</div>}
    <Card className="mt-5 flex flex-col gap-2 p-4 text-xs text-[#7b8292] sm:flex-row sm:items-center sm:justify-between"><span>{result.items.length} signal{result.items.length === 1 ? "" : "s"} · {result.sql.metrics.length} governed metrics · {result.sql.query_count} validated SQL statements</span><span>Data through {result.dataset_as_of} · {result.metadata.execution_ms.toFixed(0)}ms</span></Card>
  </>;
}

export function ProductPulse() {
  const [period, setPeriod] = useState<PulsePeriod>("last_30_days");
  const query = useQuery({ queryKey: ["product-pulse", period], queryFn: () => getProductPulse(period), staleTime: 300_000 });
  const { refetch } = query;
  const handleStreamUpdate = useCallback(() => void refetch(), [refetch]);
  const live = useAnalyticsStream({ metric: "mau", period, enabled: query.data !== undefined, onUpdate: handleStreamUpdate });
  return <>
    <PageHeading eyebrow="Proactive analytics" title="Product Pulse" description="A governed feed of unusual movement across growth, activation, engagement, checkout, revenue, and churn." action={<div className="flex flex-wrap items-center gap-2"><label className="sr-only" htmlFor="pulse-period">Pulse period</label><select id="pulse-period" value={period} onChange={(event) => setPeriod(event.target.value as PulsePeriod)} className="h-10 rounded-lg border border-[#e1e5ec] bg-white px-3 text-sm font-semibold text-[#596071]"><option value="last_30_days">Last 30 days</option><option value="last_90_days">Last 90 days</option></select><Button variant="secondary" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw size={15} className={query.isFetching ? "animate-spin" : ""} /> Refresh</Button><Button asChild variant="secondary"><Link href="/reports/weekly">Weekly report <ArrowRight size={15} /></Link></Button></div>} />
    <Card className="mb-5 flex flex-wrap items-center justify-between gap-2 p-3 text-xs text-[#697080]"><span className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${live.status === "live" ? "bg-[#21a273]" : live.status === "connecting" ? "bg-[#d28124]" : "bg-[#a1a7b3]"}`} /> Live analytics updates: {live.status}</span>{live.lastEvent?.formatted && <span>Latest {live.lastEvent.metric_label}: {live.lastEvent.formatted}</span>}</Card>
    {query.isLoading && <div className="grid gap-5 lg:grid-cols-2"><div className="skeleton h-[450px]"/><div className="skeleton h-[450px]"/><div className="skeleton h-[450px]"/><div className="skeleton h-[450px]"/></div>}
    {query.isError && <Card className="border-[#ffd8dc] bg-[#fffafb] p-6"><Badge tone="warning">Pulse unavailable</Badge><h2 className="mt-3 text-lg font-bold">Signals could not be loaded</h2><p className="mt-2 text-sm text-[#707786]">{query.error.message}</p><Button className="mt-5" variant="secondary" onClick={() => void query.refetch()}>Try again</Button></Card>}
    {query.data && <PulseResults result={query.data} />}
  </>;
}
