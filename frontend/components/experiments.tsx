"use client";

import { useState } from "react";
import { CheckCircle2, FlaskConical, RefreshCw, ShieldAlert } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getExperimentAnalysis, getExperiments } from "@/lib/api";
import type { ExperimentAnalysisResponse, ExperimentComparison, ExperimentVariantResult } from "@/lib/types";
import { Badge, Button, Card } from "@/components/ui";
import { PageHeading } from "@/components/page-heading";

type ExperimentPeriod = "last_30_days" | "last_90_days";

function percentage(value: number | null) {
  return value == null ? "Unavailable" : `${(value * 100).toFixed(1)}%`;
}

function relativeChange(value: number | null) {
  if (value == null) return "Unavailable";
  return `${value >= 0 ? "+" : "−"}${Math.abs(value * 100).toFixed(1)}%`;
}

function VariantTable({ variants }: { variants: ExperimentVariantResult[] }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm"><thead className="bg-[#fafbfc] text-xs text-[#747b8b]"><tr><th className="px-4 py-3">Variant</th><th className="px-4 py-3">Conversion</th><th className="px-4 py-3">Conversions</th><th className="px-4 py-3">Sample</th></tr></thead><tbody>{variants.map((variant) => <tr key={variant.variant} className="border-t border-[#edf0f4]"><td className="px-4 py-3 font-semibold">{variant.variant}{variant.is_control && <span className="ml-2 text-xs font-normal text-[#858c9b]">control</span>}</td><td className="px-4 py-3 font-bold">{variant.formatted_conversion_rate}</td><td className="px-4 py-3">{variant.conversions.toLocaleString()}</td><td className="px-4 py-3 text-[#697080]">{variant.sample_size.toLocaleString()}</td></tr>)}</tbody></table></div>;
}

function ComparisonCard({ comparison }: { comparison: ExperimentComparison }) {
  const positive = (comparison.absolute_uplift ?? 0) >= 0;
  return <div className="rounded-xl border border-[#edf0f4] p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-sm font-bold">{comparison.variant} vs {comparison.control_variant}</div><div className="mt-1 text-xs text-[#858c9b]">95% confidence interval for absolute uplift</div></div><Badge tone={comparison.statistically_significant ? "success" : "neutral"}>{comparison.statistically_significant ? "significant" : "directional"}</Badge></div><div className="mt-4 grid gap-3 sm:grid-cols-3"><div><div className="eyebrow">Absolute uplift</div><div className={`mt-1 text-lg font-bold ${positive ? "text-[#16875d]" : "text-[#c63f4f]"}`}>{percentage(comparison.absolute_uplift)}</div></div><div><div className="eyebrow">Relative uplift</div><div className="mt-1 text-lg font-bold">{relativeChange(comparison.relative_uplift)}</div></div><div><div className="eyebrow">p-value</div><div className="mt-1 text-lg font-bold">{comparison.p_value == null ? "—" : comparison.p_value.toFixed(4)}</div></div></div><p className="mt-3 text-xs leading-5 text-[#697080]">{comparison.significance_note}{comparison.confidence_interval_low == null ? "" : ` Interval: ${percentage(comparison.confidence_interval_low)} to ${percentage(comparison.confidence_interval_high)}.`}</p></div>;
}

function ExperimentView({ result }: { result: ExperimentAnalysisResponse }) {
  return <>
    <Card className="mb-5 border-[#e4e1ff] bg-[#faf9ff] p-5"><div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#eeecff] text-[#635bff]"><FlaskConical size={19} /></div><div><div className="flex flex-wrap items-center gap-2"><div className="eyebrow">{result.experiment.primary_metric_label}</div><Badge tone={result.experiment.status === "completed" ? "success" : "accent"}>{result.experiment.status}</Badge></div><h2 className="mt-2 text-xl font-bold">{result.experiment.name}</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-[#626a7a]">{result.experiment.hypothesis}</p><p className="mt-3 text-xs text-[#858c9b]">{result.period.label} · assignment unit: {result.methodology.assignment_unit} · data through {result.dataset_as_of}</p></div></div></Card>
    {result.warnings.length > 0 && <Card className="mb-5 border-[#f0d9ad] bg-[#fffaf0] p-4 text-sm text-[#7d5a1a]"><div className="flex items-center gap-2 font-semibold"><ShieldAlert size={16} /> Treat results with care</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></Card>}
    <div className="grid gap-5 xl:grid-cols-[1.15fr_.85fr]"><Card className="overflow-hidden"><div className="border-b border-[#e5e8ee] p-5"><div className="eyebrow">Variant performance</div><h2 className="mt-2 text-lg font-bold">Primary metric by assignment</h2></div><VariantTable variants={result.variants} /><div className="border-t border-[#e5e8ee] p-4 text-xs text-[#7b8292]">Observed conversion uses governed {result.experiment.primary_metric_label.toLowerCase()} semantics.</div></Card><Card className="p-5"><div className="eyebrow">Decision readout</div><h2 className="mt-2 text-lg font-bold">Variant comparisons</h2><div className="mt-4 space-y-3">{result.comparisons.length > 0 ? result.comparisons.map((comparison) => <ComparisonCard key={comparison.variant} comparison={comparison} />) : <p className="rounded-xl bg-[#f8f9fb] p-4 text-sm text-[#697080]">No non-control variant is available for this period.</p>}</div></Card></div>
    <details className="panel mt-5 p-5"><summary className="cursor-pointer text-sm font-bold">How this experiment was calculated</summary><div className="mt-4 grid gap-3 text-xs text-[#697080] sm:grid-cols-2"><div>Two-sided two-proportion z-test</div><div>Confidence level · {(result.methodology.confidence_level * 100).toFixed(0)}%</div><div>Minimum sample · {result.methodology.minimum_sample_size.toLocaleString()} per variant</div><div>SQL · {result.sql.query_count} validated statement</div></div><p className="mt-4 text-xs leading-5 text-[#858c9b]">{result.methodology.conversion_definition}. Statistical significance is a decision aid, not proof of causation.</p></details>
    <Card className="mt-5 flex flex-col gap-2 p-4 text-xs text-[#7b8292] sm:flex-row sm:items-center sm:justify-between"><span>{result.variants.length} variants · {result.sql.metrics.join(", ")} · validated SQL</span><span>{result.metadata.execution_ms.toFixed(0)}ms</span></Card>
  </>;
}

export function Experiments() {
  const [period, setPeriod] = useState<ExperimentPeriod>("last_90_days");
  const [selected, setSelected] = useState("");
  const catalog = useQuery({ queryKey: ["experiments"], queryFn: getExperiments, staleTime: 300_000 });
  const experimentKey = selected || catalog.data?.experiments[0]?.experiment_key || "";
  const analysis = useQuery({ queryKey: ["experiment-analysis", experimentKey, period], queryFn: () => getExperimentAnalysis(experimentKey, period), enabled: Boolean(experimentKey), staleTime: 300_000 });
  const activeExperiment = catalog.data?.experiments.find((item) => item.experiment_key === experimentKey);
  return <>
    <PageHeading eyebrow="Product analytics" title="Experiment analytics" description="Compare governed control and variant outcomes with sample sizes, uplift, confidence intervals, and significance guardrails." action={<div className="flex flex-wrap items-center gap-2"><label className="sr-only" htmlFor="experiment-period">Analysis period</label><select id="experiment-period" value={period} onChange={(event) => setPeriod(event.target.value as ExperimentPeriod)} className="h-10 rounded-lg border border-[#e1e5ec] bg-white px-3 text-sm font-semibold text-[#596071]"><option value="last_90_days">Last 90 days</option><option value="last_30_days">Last 30 days</option></select><Button variant="secondary" onClick={() => { void catalog.refetch(); void analysis.refetch(); }} disabled={catalog.isFetching || analysis.isFetching}><RefreshCw size={15} className={catalog.isFetching || analysis.isFetching ? "animate-spin" : ""} /> Refresh</Button></div>} />
    {catalog.isLoading && <div className="space-y-5"><div className="skeleton h-28" /><div className="skeleton h-96" /></div>}
    {catalog.isError && <Card className="border-[#ffd8dc] bg-[#fffafb] p-6"><Badge tone="warning">Experiments unavailable</Badge><p className="mt-3 text-sm text-[#707786]">{catalog.error.message}</p><Button className="mt-5" variant="secondary" onClick={() => void catalog.refetch()}>Try again</Button></Card>}
    {catalog.data && catalog.data.experiments.length === 0 && <Card className="grid min-h-80 place-items-center p-8 text-center"><div><CheckCircle2 className="mx-auto text-[#16875d]" size={24} /><h2 className="mt-4 font-bold">No experiments are registered</h2><p className="mt-2 max-w-md text-sm leading-6 text-[#747b8b]">Add a governed experiment and assignments before running a comparison.</p></div></Card>}
    {catalog.data && catalog.data.experiments.length > 0 && <><Card className="mb-5 flex flex-col gap-4 p-4 sm:flex-row sm:items-end"><div className="flex-1"><label className="eyebrow" htmlFor="experiment-key">Experiment</label><select id="experiment-key" value={experimentKey} onChange={(event) => setSelected(event.target.value)} className="mt-2 h-10 w-full rounded-lg border border-[#dfe3ea] bg-white px-3 text-sm sm:max-w-xl">{catalog.data.experiments.map((item) => <option key={item.experiment_key} value={item.experiment_key}>{item.name} · {item.primary_metric_label}</option>)}</select></div>{activeExperiment && <div className="text-xs text-[#858c9b]">{activeExperiment.started_at} → {activeExperiment.ended_at ?? "ongoing"}</div>}</Card>{analysis.isLoading && <div className="grid gap-5 xl:grid-cols-2"><div className="skeleton h-96" /><div className="skeleton h-96" /></div>}{analysis.isError && <Card className="border-[#ffd8dc] bg-[#fffafb] p-6"><Badge tone="warning">Experiment analysis unavailable</Badge><p className="mt-3 text-sm text-[#707786]">{analysis.error.message}</p><Button className="mt-5" variant="secondary" onClick={() => void analysis.refetch()}>Try again</Button></Card>}{analysis.data && <ExperimentView result={analysis.data} />}</>}
  </>;
}
