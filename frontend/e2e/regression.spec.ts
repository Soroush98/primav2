import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Regression-depth e2e (docs/test-cases/TC-UI.md): the unhappy paths users hit in
// production — quota exhaustion, empty results — plus an axe accessibility scan.
// Runs against the same stub backend as smoke.spec.ts; triggers are keyed on the
// question text ("quota", "quiet fleet", "boom" — see e2e/stub-backend.mjs).

async function ask(page: Page, question: string) {
  await page.goto("/");
  await page.getByPlaceholder(/Ask about a machine/).fill(question);
  await page.getByRole("button", { name: "Analyze" }).click();
}

test(
  "quota exhaustion (429) surfaces the limit message, not a crash",
  { tag: "@regression" },
  async ({ page }) => {
    // TC-UI-04: per-IP quota kicks in server-side; the visitor must see what
    // happened and that it is temporary — not a blank screen or spinner.
    await ask(page, "quota check please");
    await expect(page.getByText(/Request failed \(429\)/)).toBeVisible();
    await expect(page.getByText(/quota_exceeded|search limit reached/)).toBeVisible();
    // the app stays usable — the input and button are still enabled for later retry
    await expect(page.getByRole("button", { name: "Analyze" })).toBeEnabled();
  },
);

test(
  "empty result set renders an honest zero-state, not a broken chart",
  { tag: "@regression" },
  async ({ page }) => {
    // TC-UI-05: SQL that matches nothing → 0 windows, 0 flagged, and the agent
    // trace explains why ("no rows returned"). No score chart is drawn.
    await ask(page, "quiet fleet report");
    await expect(page.getByText("No telemetry rows matched", { exact: false })).toBeVisible();
    await expect(page.getByText("Windows analyzed")).toBeVisible();
    await expect(page.locator(".kpi").first()).toHaveText("0");
    await expect(page.getByText("no rows returned")).toBeVisible();
    await expect(page.getByText("Anomaly windows")).toHaveCount(0); // no chart section

  },
);

test(
  "a failed request leaves the app recoverable — next query succeeds",
  { tag: "@regression" },
  async ({ page }) => {
    // TC-UI-06: error state must clear on the next successful run (state
    // transition error → success), so one bad query can't wedge the session.
    await ask(page, "boom");
    await expect(page.getByText(/Request failed \(503\)/)).toBeVisible();

    await page.getByPlaceholder(/Ask about a machine/).fill("Which machines look anomalous?");
    await page.getByRole("button", { name: "Analyze" }).click();
    await expect(page.getByText("Fleet scan complete", { exact: false })).toBeVisible();
    await expect(page.getByText(/Request failed/)).toHaveCount(0);
  },
);

test(
  "landing page has no serious/critical accessibility violations",
  { tag: "@regression" },
  async ({ page }) => {
    // TC-UI-07: axe scan (WCAG 2.0/2.1 A+AA). Serious/critical violations are
    // treated as functional bugs, not lint noise.
    await page.goto("/");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const blocking = results.violations.filter((v) =>
      ["serious", "critical"].includes(v.impact ?? ""),
    );
    expect(
      blocking.map((v) => `${v.id}: ${v.help} → ${v.nodes.map((n) => n.target).join(", ")}`),
    ).toEqual([]);
  },
);

test(
  "results view has no serious/critical accessibility violations",
  { tag: "@regression" },
  async ({ page }) => {
    // TC-UI-08: the data-heavy state (KPIs, chart, chips, SQL block) stays accessible.
    await ask(page, "Which machines look anomalous?");
    await expect(page.getByText("Fleet scan complete", { exact: false })).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const blocking = results.violations.filter((v) =>
      ["serious", "critical"].includes(v.impact ?? ""),
    );
    expect(
      blocking.map((v) => `${v.id}: ${v.help} → ${v.nodes.map((n) => n.target).join(", ")}`),
    ).toEqual([]);
  },
);
