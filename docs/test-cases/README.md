# Test-case catalog

The repo-native equivalent of a centralized test-case management tool (AIO Tests /
Zephyr): every case has a stable ID, traces to a requirement, and names the
automation that implements it. In a Jira-based team these records would live in
the TCM tool and be linked from stories; the conventions transfer 1:1 — here they
live next to the code so they are versioned with it and reviewed in the same PRs.

## Conventions

- **ID scheme** — `TC-<AREA>-<NN>`: `API` (contract/negative/limits), `SEC`
  (security), `DATA` (data integrity), `UI` (end-to-end/accessibility), `PERF`
  (performance). IDs are never reused; a retired case keeps its number and is
  marked *retired*.
- **Every case records**: requirement (`REQ-*`, defined in
  [TRACEABILITY.md](TRACEABILITY.md) and derived from the user stories in
  [../user-stories.md](../user-stories.md)), priority (from the risk table in
  [QA-STRATEGY.md](../../QA-STRATEGY.md) §2), level, steps (Given/When/Then),
  expected result, and automation status.
- **Automation linkage** — the implementing test carries the case ID in its
  docstring or a comment; grep the ID to jump from case to code:
  `grep -rn "TC-API-12" backend/tests frontend/e2e`
- **Manual cases** (automation column = *manual* or *exploratory*) are run per
  the cadence noted on the case; findings are filed with the
  [bug template](../../.github/ISSUE_TEMPLATE/bug_report.yml).

## Files

| File | Area | Cases |
|---|---|---|
| [TC-API.md](TC-API.md) | API contract, validation, auth, rate limit, quota | TC-API-01…15 |
| [TC-SEC.md](TC-SEC.md) | SQL guard, prompt injection, log privacy | TC-SEC-01…08 |
| [TC-DATA.md](TC-DATA.md) | data shaping, artifacts, live warehouse | TC-DATA-01…13 |
| [TC-UI.md](TC-UI.md) | end-to-end UI, error paths, accessibility | TC-UI-01…08 |
| [TC-PERF.md](TC-PERF.md) | load, spike, soak | TC-PERF-01…03 |
| [TRACEABILITY.md](TRACEABILITY.md) | requirements ↔ cases ↔ automation matrix | — |
