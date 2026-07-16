# TC-PERF — performance & load

Automation: k6 scripts in [loadtest/](../../loadtest/) with SLOs encoded as
`thresholds` (a breach exits non-zero — pass/fail, not a demo). Plan, workload
models and run book: [loadtest/PERF-PLAN.md](../../loadtest/PERF-PLAN.md).
Results are committed to [loadtest/results/](../../loadtest/results/).
Priority follows risks R4/R7. Not in the PR gate: TC-PERF-01/02 are free but
environment-dependent; TC-PERF-03 spends real money.

| ID | Title | Req | Pri | Given / When / Then | Automation |
|----|-------|-----|-----|---------------------|------------|
| TC-PERF-01 | Health under ramping load | REQ-09 | P2 | Given 5→50 RPS ramping arrival rate on `/api/health` / When held at peak / Then p95 < 500 ms and zero failures (cold starts allowed only at the tail) | `health-ramp.js` |
| TC-PERF-02 | Rejection chain under hostile burst | REQ-04, REQ-09 | P1 | Given 30 RPS wrong-key + 5 RPS over-limit traffic / When sustained / Then every response is the correct rejection (401 / 422→429), never 5xx, rejection p95 < 300 ms — protection must be cheaper than the attack | `burst-rejections.js` |
| TC-PERF-03 | Analyze soak (real spend) | REQ-09 | P2 | Given paced real analyze traffic (distinct synthetic IPs) against staging / When sustained ≥ 5 min / Then p95 < 45 s, error rate < 2%, and Cloud Run memory stays flat (the 1 GiB × concurrency=40 ceiling is the hunted failure mode) | `soak-analyze.js` — deliberate, human-triggered |

Latest recorded run: [results/2026-07-16-local-baseline.md](../../loadtest/results/2026-07-16-local-baseline.md)
— TC-PERF-01 and TC-PERF-02 PASS on the local baseline (rejection p95 ≈ 3–4 ms).
