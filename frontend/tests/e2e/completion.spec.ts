import { expect, test } from "@playwright/test";

test("overview exposes the completed product journey", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your product, in focus" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Ask a question/ })).toBeVisible();
});

test("acquisition and data catalog routes are reachable", async ({ page }) => {
  await page.goto("/analytics/acquisition");
  await expect(page.getByRole("heading", { name: "Acquisition analytics" })).toBeVisible();

  await page.goto("/data/catalog");
  await expect(page.getByRole("heading", { name: "Data catalog" })).toBeVisible();
});

test("history route is reachable", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByRole("heading", { name: "Recent investigations" })).toBeVisible();
});

test("analysis notebook route is reachable", async ({ page }) => {
  await page.goto("/notebook");
  await expect(page.getByRole("heading", { name: "Saved investigations" })).toBeVisible();
});

test("analysis notebook generates an executive summary from saved evidence", async ({ page }) => {
  await page.route("**/notebook/insights*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        type: "analysis_notebook",
        insights: [{
          insight_id: "11111111-1111-4111-8111-111111111111",
          source_query_id: "22222222-2222-4222-8222-222222222222",
          title: "Checkout incident",
          question: "Why did checkout conversion fall?",
          mode: "deep",
          headline: "Checkout conversion fell on mobile",
          summary: "Mobile Safari contributed the largest observed decline.",
          created_at: "2026-08-26T00:00:00Z",
          interpretation: { metric_label: "Checkout Conversion" },
          findings: [{ kind: "observed", text: "Conversion decreased week over week." }],
          drivers: [{ dimension: "browser", segment: "Safari", sample_size: 500, current_value: 0.08 }],
        }],
        limit: 50,
      }),
    });
  });
  await page.route("**/notebook/summary*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        type: "notebook_summary",
        insight_count: 1,
        limit: 50,
        warnings: [],
        summary: {
          generated_at: "2026-08-26T00:00:00Z",
          headline: "Executive summary across 1 saved investigation",
          summary: "The saved evidence points to a checkout conversion issue on Safari.",
          source_insight_ids: ["11111111-1111-4111-8111-111111111111"],
          themes: [{
            metric: "checkout_conversion",
            metric_label: "Checkout Conversion",
            insight_count: 1,
            headline: "Checkout conversion fell on mobile",
            summary: "Mobile Safari contributed the largest observed decline.",
            evidence_ids: ["metric"],
            source_insight_ids: ["11111111-1111-4111-8111-111111111111"],
          }],
          findings: [{
            kind: "observed",
            text: "Conversion decreased week over week.",
            evidence_ids: ["metric"],
            source_insight_ids: ["11111111-1111-4111-8111-111111111111"],
          }],
          drivers: [],
          recommendations: [],
          methodology: { source_insight_count: 1, evidence_bound: true, snapshot_only: true, deterministic: true },
        },
      }),
    });
  });

  await page.goto("/notebook");
  await expect(page.getByRole("button", { name: "Generate executive summary" })).toBeVisible();
  await page.getByRole("button", { name: "Generate executive summary" }).click();
  await expect(page.getByRole("heading", { name: "Executive summary across 1 saved investigation" })).toBeVisible();
  await expect(page.getByText("How this summary was created")).toBeVisible();
});

test("proactive analytics routes are reachable", async ({ page }) => {
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Product Pulse" })).toBeVisible();

  await page.goto("/reports/weekly");
  await expect(page.getByRole("heading", { name: "Weekly product report" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Download Markdown/ })).toBeVisible();
});

test("experiment and advanced analytics routes are reachable", async ({ page }) => {
  await page.goto("/analytics/experiments");
  await expect(page.getByRole("heading", { name: "Experiment analytics" })).toBeVisible();

  await page.goto("/analytics/advanced");
  await expect(page.getByRole("heading", { name: "Advanced analytics" })).toBeVisible();
});

test("mobile navigation exposes every primary destination", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "The compact navigation is only rendered in the mobile project.");
  await page.goto("/");
  const openNavigation = page.getByRole("button", { name: "Open navigation" });
  await expect(openNavigation).toBeVisible();
  await openNavigation.click();
  const navigation = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Acquisition" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "History" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Analysis Notebook" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Product Pulse" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Weekly Report" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Experiments" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Advanced Analytics" })).toBeVisible();
});
