import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { Card } from "@/components/ui";

export function MetricCard({ label, value, delta, note, loading = false }: { label: string; value: string; delta?: number | null; note: string; loading?: boolean }) {
  if (loading) return <Card className="p-5"><div className="skeleton h-3 w-24"/><div className="skeleton mt-5 h-8 w-28"/><div className="skeleton mt-3 h-3 w-36"/></Card>;
  const positive = (delta ?? 0) > 0;
  const negative = (delta ?? 0) < 0;
  return <Card className="p-5"><div className="text-xs font-semibold text-[#72798a]">{label}</div><div className="mt-3 flex items-end justify-between"><div className="text-2xl font-bold tracking-tight">{value}</div>{delta != null && <div className={`flex items-center gap-1 text-xs font-bold ${positive ? "text-[#16875d]" : negative ? "text-[#c63f4f]" : "text-[#697080]"}`}>{positive ? <ArrowUpRight size={14}/> : negative ? <ArrowDownRight size={14}/> : <Minus size={14}/>} {Math.abs(delta * 100).toFixed(1)}%</div>}</div><div className="mt-2 text-[11px] text-[#9299a8]">{note}</div></Card>;
}

