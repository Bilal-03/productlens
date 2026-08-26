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

test("proactive analytics routes are reachable", async ({ page }) => {
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Product Pulse" })).toBeVisible();

  await page.goto("/reports/weekly");
  await expect(page.getByRole("heading", { name: "Weekly product report" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Download Markdown/ })).toBeVisible();
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
