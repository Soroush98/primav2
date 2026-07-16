import { expect, test } from "@playwright/test";

// Runs against the production build proxying to e2e/stub-backend.mjs (see
// playwright.config.ts). The stub 401s on a missing/wrong X-API-Key, so the happy
// paths below also verify the proxy's server-side key and IP forwarding wiring.

test("analyze renders briefing, KPIs, score chart, root cause and SQL", { tag: "@smoke" }, async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder(/Ask about a machine/).fill("Which machines look anomalous?");
  await page.getByRole("button", { name: "Analyze" }).click();

  await expect(page.getByText("Fleet scan complete", { exact: false })).toBeVisible();
  await expect(page.getByText("Anomalies flagged")).toBeVisible();
  await expect(page.locator(".kpi.warn")).toHaveText("3");

  // ScoreChart: threshold line label, three flagged red dots, top-window chips.
  await expect(page.getByText("POT threshold 3.50")).toBeVisible();
  await expect(page.locator('circle[fill="var(--bad)"]')).toHaveCount(3);
  await expect(page.getByText("m_1043 · 12:00 · 9.10")).toBeVisible();

  await expect(page.locator(".bar-label").first()).toHaveText("cpu_util_percent");
  await expect(page.locator("pre.sql")).toContainText("SELECT machine_id");
});

test("forecast arm renders the Chronos chart with switchable feature chips", { tag: "@smoke" }, async ({ page }) => {
  await page.goto("/");
  await page.locator("select").selectOption("forecast");
  await page.getByRole("button", { name: "Analyze" }).click();

  await expect(page.getByText("Chronos forecast ready", { exact: false })).toBeVisible();
  await expect(page.getByText("Forecast horizon")).toBeVisible();
  await expect(page.getByText("forecast median")).toBeVisible();
  await expect(page.getByText("q10–q90 band")).toBeVisible();
  await expect(page.getByText("cpu · m_1043")).toBeVisible();

  await page.getByRole("button", { name: "mem", exact: true }).click();
  await expect(page.getByText("mem · m_1043")).toBeVisible();
});

test("a backend failure surfaces the error card", { tag: "@smoke" }, async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder(/Ask about a machine/).fill("boom");
  await page.getByRole("button", { name: "Analyze" }).click();

  await expect(page.getByText("Error:", { exact: false })).toBeVisible();
  await expect(page.getByText(/Request failed \(503\)/)).toBeVisible();
});
