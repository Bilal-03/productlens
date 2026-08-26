import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { AnalyticsChart } from "@/components/chart";
import type { ChartSpec } from "@/lib/types";

type PlotProps = { data?: { type?: string }[] };

vi.mock("next/dynamic", () => ({
  default: () => function MockPlot({ data }: PlotProps) {
    return <div data-testid="plot" data-chart-type={data?.[0]?.type ?? "unknown"} />;
  },
}));

const base = {
  title: "Test chart",
  data: [{ segment: "A", value: 1 }],
  x_labels: ["A"],
  y_labels: ["A"],
  matrix: [[1]],
  description: "Accessible chart description",
} satisfies Omit<ChartSpec, "chart_type">;

describe("controlled analytics charts", () => {
  it.each([
    ["line", "scatter"],
    ["bar", "bar"],
    ["stacked_bar", "bar"],
    ["funnel", "funnel"],
    ["heatmap", "heatmap"],
    ["histogram", "histogram"],
    ["scatter", "scatter"],
  ] as const)("renders %s through the controlled Plotly contract", (chartType, expectedType) => {
    render(<AnalyticsChart spec={{ ...base, chart_type: chartType }} />);
    expect(screen.getByRole("img", { name: base.description })).toBeVisible();
    expect(screen.getByTestId("plot")).toHaveAttribute("data-chart-type", expectedType);
  });

  it("renders a table as semantic HTML", () => {
    render(<AnalyticsChart spec={{ ...base, chart_type: "table" }} />);
    expect(screen.getByRole("table")).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "segment" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "A" })).toBeVisible();
  });

  it("renders an explicit no-chart state", () => {
    render(<AnalyticsChart spec={{ ...base, chart_type: "none" }} />);
    expect(screen.getByText("No chart is appropriate for this result.")).toBeVisible();
  });
});
