import { render, screen } from "@testing-library/react";
import { Badge, Button, Card } from "@/components/ui";

describe("shared UI", () => {
  it("renders accessible controls and containers", () => {
    render(<Card><Badge tone="success">Validated</Badge><Button>Run analysis</Button></Card>);
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
    expect(screen.getByText("Validated")).toBeVisible();
  });
});

