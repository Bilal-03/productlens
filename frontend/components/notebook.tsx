"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Bookmark, Check, Clock, ExternalLink, Sparkles, Trash2 } from "lucide-react";
import { deleteNotebookInsight, getNotebook } from "@/lib/api";
import type { NotebookInsight } from "@/lib/types";
import { Badge, Button, Card } from "@/components/ui";
import { PageHeading } from "@/components/page-heading";

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function NotebookCard({ item, onDelete, deleting }: { item: NotebookInsight; onDelete: (id: string) => void; deleting: boolean }) {
  const findings = item.findings.slice(0, 4);
  const drivers = item.drivers.slice(0, 3);
  return <Card className="overflow-hidden">
    <div className="border-b border-[#e5e8ee] bg-gradient-to-r from-[#fbfaff] to-white p-5 md:p-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2"><Badge tone="accent">{item.mode}</Badge><Badge>{item.interpretation.metric_label}</Badge><span className="flex items-center gap-1 text-[11px] text-[#858c9b]"><Clock size={12}/>{formatDate(item.created_at)}</span></div>
          <h2 className="mt-3 text-xl font-bold tracking-tight">{item.title}</h2>
          <p className="mt-1 text-sm font-semibold text-[#5148d9]">{item.headline}</p>
        </div>
        <div className="shrink-0 rounded-xl bg-[#f1f0ff] p-3 text-[#635bff]"><Bookmark size={19}/></div>
      </div>
      <p className="mt-4 max-w-3xl text-sm leading-6 text-[#626a7a]">{item.summary}</p>
    </div>

    <div className="grid gap-5 p-5 md:grid-cols-[1.2fr_1fr] md:p-6">
      <div>
        <div className="eyebrow">Signal map</div>
        <div className="mt-3 border-l-2 border-[#d8d4ff] pl-4">
          <div className="flex items-center gap-2 text-sm font-bold"><Bookmark size={15} className="text-[#635bff]"/> Investigation saved</div>
          <div className="mt-3 space-y-3">
            {findings.length > 0 ? findings.map((finding, index) => <div key={`${finding.kind}-${index}`} className="flex gap-2 text-sm text-[#5f6676]"><Check size={15} className="mt-0.5 shrink-0 text-[#16875d]"/><span>{finding.text}</span></div>) : <p className="text-sm text-[#747b8b]">The full analysis contains the supporting findings.</p>}
          </div>
        </div>
      </div>
      <div>
        <div className="eyebrow">Top segment drivers</div>
        {drivers.length > 0 ? <div className="mt-3 space-y-2">{drivers.map((driver) => <div key={`${driver.dimension}-${driver.segment}`} className="rounded-xl border border-[#e6e9ef] px-3 py-2.5"><div className="flex items-center justify-between gap-3 text-sm"><span className="font-semibold">{driver.segment}</span><span className="text-xs text-[#7b8292]">n={driver.sample_size.toLocaleString()}</span></div><div className="mt-1 text-xs text-[#747b8b]">{driver.dimension} · current {driver.current_value.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div></div>)}</div> : <p className="mt-3 text-sm text-[#747b8b]">No segment drivers were returned.</p>}
      </div>
    </div>

    <div className="flex flex-col justify-between gap-3 border-t border-[#e5e8ee] bg-[#fafbfc] p-4 sm:flex-row sm:items-center">
      <div className="text-xs text-[#7b8292]">Question: <span className="font-medium text-[#596071]">{item.question}</span></div>
      <div className="flex shrink-0 items-center gap-2">
        <Button asChild variant="secondary" size="sm"><Link href={`/copilot?query_id=${encodeURIComponent(item.source_query_id)}`}><ExternalLink size={14}/>Open full analysis</Link></Button>
        <Button variant="danger" size="sm" onClick={() => onDelete(item.insight_id)} disabled={deleting}><Trash2 size={14}/>{deleting ? "Removing…" : "Remove"}</Button>
      </div>
    </div>
  </Card>;
}

export function NotebookPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["notebook"], queryFn: () => getNotebook() });
  const removal = useMutation({
    mutationFn: (insightId: string) => deleteNotebookInsight(insightId),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["notebook"] }); },
  });
  const insights = query.data?.insights ?? [];

  return <>
    <PageHeading eyebrow="Analysis notebook" title="Saved investigations" description="Pin the evidence you want to carry into the next decision. Saved analyses stay scoped to this anonymous browser session." action={<Button asChild><Link href="/copilot"><Sparkles size={15}/>Pin a new analysis</Link></Button>}/>
    {query.isLoading && <div className="space-y-4"><div className="skeleton h-64"/><div className="skeleton h-64"/></div>}
    {query.isError && <Card className="border-[#ffd8dc] bg-[#fffafb] p-6"><Badge tone="warning">Notebook unavailable</Badge><h2 className="mt-3 text-lg font-bold">Saved investigations could not be loaded</h2><p className="mt-2 text-sm text-[#747b8b]">{query.error instanceof Error ? query.error.message : "The notebook service is unavailable."}</p></Card>}
    {!query.isLoading && !query.isError && insights.length === 0 && <Card className="grid min-h-80 place-items-center p-6 text-center"><div><div className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[#f1f0ff] text-[#635bff]"><Bookmark size={20}/></div><h2 className="mt-4 font-bold">No saved analyses yet</h2><p className="mt-2 max-w-sm text-sm leading-6 text-[#747b8b]">Run an investigation in Copilot, then choose “Save to notebook” to build a decision trail.</p><Button asChild className="mt-5"><Link href="/copilot"><Sparkles size={15}/>Start an analysis</Link></Button></div></Card>}
    {insights.length > 0 && <div className="space-y-5">{insights.map((item) => <NotebookCard key={item.insight_id} item={item} onDelete={(id) => removal.mutate(id)} deleting={removal.isPending && removal.variables === item.insight_id}/>)}</div>}
    {query.data && <div className="mt-5 flex items-center gap-2 text-xs text-[#7b8292]"><Bookmark size={13}/>Showing {insights.length} saved {insights.length === 1 ? "investigation" : "investigations"} · content is a snapshot of the validated analysis.</div>}
  </>;
}
