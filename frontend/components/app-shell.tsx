"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Activity, BarChart3, BookOpen, Bookmark, BrainCircuit, ChevronDown, CircleAlert, Database, FileText, History, LayoutDashboard, LogIn, LogOut, Menu, Network, Sparkles, Target, TrendingUp, Users, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/components/ui";
import { useAuth } from "@/components/auth-provider";
import { getAccessContext, getAccessToken, getConnectorStatus } from "@/lib/api";

const links = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/copilot", label: "Ask Copilot", icon: Sparkles },
  { href: "/insights", label: "Product Pulse", icon: TrendingUp },
  { href: "/reports/weekly", label: "Weekly Report", icon: FileText },
  { section: "Analytics" },
  { href: "/analytics/funnels", label: "Funnels", icon: Network },
  { href: "/analytics/retention", label: "Retention", icon: Activity },
  { href: "/analytics/cohorts", label: "Cohorts", icon: Users },
  { href: "/analytics/segments", label: "Segments", icon: BarChart3 },
  { href: "/analytics/feature-adoption", label: "Feature Adoption", icon: Target },
  { href: "/analytics/acquisition", label: "Acquisition", icon: TrendingUp },
  { href: "/analytics/experiments", label: "Experiments", icon: Target },
  { href: "/analytics/advanced", label: "Advanced Analytics", icon: BarChart3 },
  { section: "Data" },
  { href: "/data/metrics", label: "Metrics", icon: BookOpen },
  { href: "/data/catalog", label: "Data Catalog", icon: Database },
  { href: "/notebook", label: "Analysis Notebook", icon: Bookmark },
  { href: "/history", label: "History", icon: History },
];

function SidebarContent({ close }: { close?: () => void }) {
  const pathname = usePathname();
  return <>
    <div className="flex h-16 items-center gap-3 border-b border-[#e7e9ef] px-5">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#171a23] text-white"><BrainCircuit size={19} /></div>
      <div><div className="font-bold tracking-tight">ProductLens</div><div className="text-[10px] font-semibold uppercase tracking-[.16em] text-[#7c8393]">Analytics AI</div></div>
    </div>
    <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="Primary navigation">
      {links.map((item, index) => item.section ? (
        <div key={`${item.section}-${index}`} className="px-3 pb-1 pt-5 text-[10px] font-bold uppercase tracking-[.16em] text-[#9299a8]">{item.section}</div>
      ) : (
        <Link key={item.href} href={item.href!} onClick={close} className={cn("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[#596071] transition-colors hover:bg-[#f1f2f6] hover:text-[#1b1e27]", pathname === item.href && "bg-[#eeecff] text-[#5148d9]") }>
          {item.icon && <item.icon size={17} />}<span>{item.label}</span>
        </Link>
      ))}
    </nav>
    <div className="border-t border-[#e7e9ef] p-4"><div className="rounded-xl bg-[#f4f3ff] p-3"><div className="text-xs font-bold text-[#5148d9]">Synthetic workspace</div><p className="mt-1 text-[11px] leading-relaxed text-[#73798a]">Data through Aug 23, 2026 · UTC</p></div></div>
  </>;
}

function WorkspaceStatus() {
  const auth = useAuth();
  const accessScope = auth.session?.access_token ?? getAccessToken() ?? "anonymous";
  const context = useQuery({
    queryKey: ["access-context", accessScope],
    queryFn: getAccessContext,
    staleTime: 60_000,
    retry: false,
  });
  const connector = useQuery({
    queryKey: ["connector-status", accessScope],
    queryFn: getConnectorStatus,
    staleTime: 60_000,
    retry: false,
    enabled: Boolean(
      context.data &&
      context.data.auth_mode !== "anonymous" &&
      context.data.source_configured !== false,
    ),
  });
  if (context.isLoading) return <div className="hidden items-center gap-2 text-xs text-[#788091] sm:flex"><span className="h-2 w-2 rounded-full bg-[#c8ccd5]" /> Checking workspace…</div>;
  if (context.isError) return <div className="hidden items-center gap-2 text-xs text-[#bd3446] sm:flex"><CircleAlert size={14} /> Workspace status unavailable</div>;
  const source = context.data?.source_id ?? "demo";
  if (context.data?.auth_mode === "anonymous") return <div className="hidden items-center gap-2 text-xs text-[#788091] sm:flex"><span className="h-2 w-2 rounded-full bg-[#21a273]" /> Demo dataset connected</div>;
  if (context.data?.source_configured === false) return <div className="hidden items-center gap-2 text-xs text-[#9b6017] sm:flex"><span className="h-2 w-2 rounded-full bg-[#d28124]" /> {context.data?.role ?? "workspace"} · source unconfigured</div>;
  if (connector.isLoading) return <div className="hidden items-center gap-2 text-xs text-[#788091] sm:flex"><span className="h-2 w-2 rounded-full bg-[#d28124]" /> {context.data?.role ?? "workspace"} · checking {source}</div>;
  if (connector.isError || !connector.data?.source.healthy) return <div className="hidden items-center gap-2 text-xs text-[#bd3446] sm:flex"><CircleAlert size={14} /> {context.data?.role ?? "workspace"} · {source} unavailable</div>;
  return <div className="hidden items-center gap-2 text-xs text-[#788091] sm:flex"><span className="h-2 w-2 rounded-full bg-[#21a273]" /> {context.data?.role ?? "workspace"} · {source} connected</div>;
}

function AuthControl() {
  const auth = useAuth();
  if (auth.loading) return <span className="hidden text-xs text-[#788091] sm:inline">Loading access…</span>;
  if (auth.user) return <div className="flex items-center gap-2"><span className="hidden max-w-36 truncate text-xs font-semibold text-[#596071] md:inline">{auth.user.email ?? "Workspace user"}</span><button onClick={() => void auth.signOut()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-[#e1e5ec] px-3 text-xs font-semibold text-[#596071] hover:bg-[#f4f5f8]" aria-label="Sign out"><LogOut size={14} /> <span className="hidden sm:inline">Sign out</span></button></div>;
  return <Link href="/auth/login" className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#635bff] px-3 text-xs font-semibold text-white hover:bg-[#5149e6]"><LogIn size={14} /> Sign in</Link>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return <div className="min-h-screen">
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-[#e1e5ec] bg-white lg:flex"><SidebarContent /></aside>
    {open && <div className="fixed inset-0 z-40 bg-black/30 lg:hidden" onClick={() => setOpen(false)}><aside className="h-full w-72 bg-white" onClick={(event) => event.stopPropagation()}><SidebarContent close={() => setOpen(false)} /></aside></div>}
    <div className="lg:pl-60">
      <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-[#e1e5ec] bg-white/90 px-4 backdrop-blur md:px-8">
        <button className="rounded-lg p-2 hover:bg-[#f1f2f6] lg:hidden" onClick={() => setOpen(!open)} aria-label="Open navigation">{open ? <X size={20}/> : <Menu size={20}/>}</button>
        <WorkspaceStatus />
        <div className="flex items-center gap-2"><div className="hidden items-center gap-2 rounded-lg border border-[#e1e5ec] bg-white px-3 py-2 text-xs font-medium text-[#606778] sm:flex">Portfolio workspace <ChevronDown size={14}/></div><AuthControl /></div>
      </header>
      <main className="mx-auto max-w-[1480px] p-4 md:p-8">{children}</main>
    </div>
  </div>;
}
