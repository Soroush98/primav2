# Traceability matrix

Requirements ↔ test cases ↔ automation. Audit for gaps by scanning the last
column; every requirement must have at least one automated case in the CI gate
(or a documented reason it is opt-in/manual — see QA-STRATEGY §5, §10).

## Requirements

Derived from the user stories in [../user-stories.md](../user-stories.md)
(personas, story statements, and Given/When/Then acceptance criteria live
there), cross-checked against [README.md](../../README.md),
[SECURITY.md](../../SECURITY.md) and the deploy configuration. In a Jira-based
team the stories and their acceptance criteria would live in the tracker; the
chain is the same: story → requirement → test case → automation.

| ID | Requirement | Stories |
|----|-------------|---------|
| REQ-01 | A natural-language question returns an analysis: briefing, generated SQL, detection payload, root cause (when applicable) | US-01, US-03, US-11 |
| REQ-02 | Detector arm selection works (auto routes by data shape; forced modes honored) and every fallback is honestly labeled with a note | US-02, US-03 |
| REQ-03 | Only validated read-only SQL, scoped to the configured project, can reach BigQuery — under any input, including adversarial prompts | US-04 |
| REQ-04 | The API is protected: server-held key, per-IP rate limit, per-IP persistent quota; rejections use stable `{code, message}` shapes; protection failures degrade open, never take the API down | US-05 |
| REQ-05 | Request inputs are bounded and validated (question 1–2000 chars, detector enum); the OpenAPI contract is stable | US-01, US-05 |
| REQ-06 | Every search emits one structured JSON log line — parseable, size-bounded, no credentials | US-10 |
| REQ-07 | Warehouse tables and all data shaping feeding models honor their documented invariants (reconciliation, uniqueness, domains, gap-fill honesty) | US-09 |
| REQ-08 | The UI renders results, error states, and empty states usably and accessibly (WCAG A/AA) on desktop and mobile widths | US-06, US-07, US-08 |
| REQ-09 | Performance SLOs hold: health p95 < 500 ms, rejections p95 < 300 ms and never 5xx, analyze p95 < 45 s @ <2% errors | US-05 |
| REQ-10 | No known HIGH+ vulnerabilities in production dependencies | — (platform hygiene, tool-gated) |

## Matrix

| Req | Test cases | Automation | In CI gate? |
|-----|------------|------------|-------------|
| REQ-01 | TC-API-12; TC-UI-01 | test_api_contract.py; e2e smoke (+ test_api.py, test_agent.py) | ✅ |
| REQ-02 | TC-API-06, 07; TC-UI-02, 05 | test_api_contract.py; e2e; routing/fallback tests in test_agent.py | ✅ |
| REQ-03 | TC-SEC-01…05 | test_security.py, test_agent.py | ✅ |
| REQ-04 | TC-API-08…11, 13…15; TC-UI-04; TC-PERF-02 | test_api_contract.py, test_quota.py; e2e; burst-rejections.js | ✅ (perf: on demand) |
| REQ-05 | TC-API-01…05, 12 | test_api_contract.py | ✅ |
| REQ-06 | TC-SEC-06…08 | test_security.py | ✅ |
| REQ-07 | TC-DATA-01…08 (CI); TC-DATA-09…13 (live) | test_data_integrity.py | ✅ / opt-in (`BQ_INTEGRITY=1`) |
| REQ-08 | TC-UI-01…08 (desktop + mobile projects) | e2e smoke + regression incl. axe | ✅ |
| REQ-09 | TC-PERF-01…03 | k6 suites, results committed | on demand (free/spend split — PERF-PLAN.md) |
| REQ-10 | — (tool gate, no TC) | pip-audit + npm audit jobs in ci.yml | ✅ |

## Known gaps (tracked, deliberate)

- **LLM answer quality** has no CI assertion (QA-STRATEGY §10) — covered by the
  offline benchmark artifacts (TC-DATA-07/08 pin their integrity) and
  exploratory charter #3.
- **Cross-engine rendering** (Firefox/WebKit) is opt-in, not in the PR gate —
  chromium desktop + mobile run on every PR.
- **TC-PERF-03 (soak)** is never automated in CI by design: it spends real money.
