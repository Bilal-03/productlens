"use client";

import dynamic from "next/dynamic";
import type { ChartSpec } from "@/lib/types";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false, loading: () => <div className="skeleton h-[320px] w-full" /> });

export function AnalyticsChart({ spec }: { spec: ChartSpec }) {
  if (spec.chart_type === "none") return <div className="grid h-56 place-items-center text-sm text-[#73798a]">No chart is appropriate for this result.</div>;
  if (spec.chart_type === "heatmap") {
    return <div role="img" aria-label={spec.description}><Plot data={[{ type: "heatmap", x: spec.x_labels, y: spec.y_labels, z: spec.matrix, colorscale: [[0,"#f4f3ff"],[1,"#635bff"]], hoverongaps: false }]} layout={layout(spec.title)} config={config} style={{ width: "100%", height: 360 }} /></div>;
  }
  const type: "scatter" | "funnel" | "bar" = spec.chart_type === "line" ? "scatter" : spec.chart_type === "funnel" ? "funnel" : "bar";
  const series = spec.series
    ? [...new Set(spec.data.map((row) => String(row[spec.series as string] ?? "Unknown")))]
    : [undefined];
  const traces = series.map((seriesName) => {
    const rows = seriesName ? spec.data.filter((row) => String(row[spec.series as string] ?? "Unknown") === seriesName) : spec.data;
    return {
      type,
      name: seriesName,
      x: rows.map((row) => row[spec.x ?? "segment"] as string),
      y: rows.map((row) => row[spec.y ?? "value"] as number | null),
      mode: type === "scatter" ? ("lines+markers" as const) : undefined,
      marker: { color: "#635bff" },
      line: { color: "#635bff", width: 3 },
    };
  });
  return <div role="img" aria-label={spec.description}><Plot data={traces} layout={layout(spec.title)} config={config} style={{ width: "100%", height: 350 }} /></div>;
}

const config = { displayModeBar: false, responsive: true };
function layout(title: string) { return { title: { text: title, font: { size: 15, color: "#252936" }, x: .02 }, margin: { l: 56, r: 18, t: 54, b: 54 }, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Arial, sans-serif", color: "#6c7383", size: 11 }, xaxis: { gridcolor: "#eef0f4", zerolinecolor: "#e1e5ec" }, yaxis: { gridcolor: "#eef0f4", zerolinecolor: "#e1e5ec" }, autosize: true }; }
