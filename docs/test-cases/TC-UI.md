# TC-UI — end-to-end UI, error paths & accessibility

Automation: [frontend/e2e/smoke.spec.ts](../../frontend/e2e/smoke.spec.ts) (@smoke),
[frontend/e2e/regression.spec.ts](../../frontend/e2e/regression.spec.ts) (@regression).
Every case runs on TWO Playwright projects — `chromium` (Desktop Chrome) and
`mobile-chrome` (Pixel 7) — against the production standalone build with the stub
backend (which enforces the API key, so a green run also proves the server-side
proxy wiring). Cross-engine (`PW_ALL_BROWSERS=1` → Firefox + WebKit) is opt-in.
Priority follows risks R2/R6.

| ID | Title | Req | Pri | Given / When / Then | Automation |
|----|-------|-----|-----|---------------------|------------|
| TC-UI-01 | Anomaly dashboard renders end-to-end | REQ-01, REQ-08 | P1 | Given a question / When analyzed / Then briefing, KPIs, threshold + flagged dots on the score chart, top-window chips, root-cause bars and the generated SQL all render | smoke: "analyze renders briefing…" |
| TC-UI-02 | Forecast arm renders with switchable features | REQ-02, REQ-08 | P1 | Given detector=forecast / When analyzed / Then Chronos chart with horizon, median + q10–q90 band, and feature chips switch the plotted metric | smoke: "forecast arm renders…" |
| TC-UI-03 | Backend failure surfaces the error card | REQ-08 | P1 | Given the backend 503s / When analyzed / Then an explanatory error card — no crash, no infinite spinner | smoke: "a backend failure surfaces…" |
| TC-UI-04 | Quota exhaustion shows the limit message | REQ-04, REQ-08 | P1 | Given the per-IP quota is exhausted (429) / When analyzed / Then the limit message is shown and the form stays enabled for a later retry | regression: "quota exhaustion (429)…" |
| TC-UI-05 | Empty result renders an honest zero-state | REQ-02, REQ-08 | P2 | Given SQL that matches nothing / When analyzed / Then 0-KPIs, the trace explains "no rows returned", and no chart section is drawn | regression: "empty result set renders…" |
| TC-UI-06 | Error state recovers on next success | REQ-08 | P2 | Given a failed request (state: error) / When a valid question follows / Then results render and the error clears (state transition error → success) | regression: "a failed request leaves the app recoverable…" |
| TC-UI-07 | Landing page passes axe (WCAG A/AA) | REQ-08 | P2 | Given the landing page / When scanned by axe / Then zero serious/critical violations | regression: "landing page has no serious/critical…" |
| TC-UI-08 | Results view passes axe (WCAG A/AA) | REQ-08 | P2 | Given a rendered result (KPIs, chart, chips, SQL block) / When scanned / Then zero serious/critical violations | regression: "results view has no serious/critical…" |

## Defects found by this suite

| Defect | Found by | Fixed in | Regression guard |
|---|---|---|---|
| **BUG-001** (S2/P1) — ask-row overflow made the Analyze button unclickable at phone widths | first run of the `mobile-chrome` project (TC-UI-01…06 all failed to click) | `globals.css` wrap rule @ ≤640px | every TC on `mobile-chrome` |
| **BUG-002** (S3/P2) — generated-SQL block scrollable but not keyboard-focusable (WCAG 2.1.1) | TC-UI-08 axe scan on mobile | focusable labeled region in `page.tsx` | TC-UI-08 |
