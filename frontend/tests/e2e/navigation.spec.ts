import { expect, test } from "@playwright/test";

test("copilot renders a structured question surface", async ({ page }) => {
  await page.goto("/copilot");
  await expect(page.getByRole("heading", { name: "Ask your product data" })).toBeVisible();
  await expect(page.getByLabel("Product analytics question")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run analysis" })).toBeDisabled();
});

test("catalog route is reachable from the application", async ({ page }) => {
  await page.goto("/data/metrics");
  await expect(page.getByRole("heading", { name: "Metrics catalog" })).toBeVisible();
});

