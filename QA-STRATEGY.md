# QA Strategy

The quality-assurance strategy for primav2 — what can fail, how much each failure
matters, which test level catches it, and the gates that keep it caught. Structure
and vocabulary follow the ISTQB Foundation syllabus; the concrete suites all exist
and run in CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

Related documents: [docs/user-stories.md](docs/user-stories.md) (personas,
stories, acceptance criteria — where the requirements derive from),
[SECURITY.md](SECURITY.md) (threat model),
[loadtest/PERF-PLAN.md](loadtest/PERF-PLAN.md) (performance),
[docs/test-cases/](docs/test-cases/) (test cases + traceability matrix).

## 1. Quality objectives

1. **Never execute unsafe SQL.** An LLM authors queries from untrusted input; the
   guard boundary must hold under adversarial prompting.
2. **Never show a silently-wrong verdict.** Detector output must be honestly
   labeled (which arm ran, what was flagged, why a fallback happened).
3. **Fail visibly and recoverably.** Backend/LLM/storage failures surface as
   explained error states, never crashes, blank screens, or wedged sessions.
4. **Stay cheap under abuse.** Rejection paths (401/422/429) must be correct,
   fast, and cost-free (no LLM/BigQuery spend for rejected traffic).
5. **Keep the data trustworthy.** The warehouse tables and every transformation
   feeding a model honor their documented invariants.

## 2. Product risk analysis

Risk-based prioritization: test effort follows this table, top first.

| # | Risk | L×I | Primary mitigation (tested by) |
|---|------|-----|-------------------------------|
| R1 | Prompt-injected SQL reaches BigQuery (data loss / exfiltration / cost) | High | Guard corpus + fail-safe e2e graph test — `tests/test_security.py` (TC-SEC-01…05) |
| R2 | Wrong/garbled analysis shown as fact (detector mislabel, fallback hidden) | High | Agent-graph routing/fallback tests — `tests/test_agent.py`; UI honesty checks — e2e TC-UI-05 |
| R3 | Data-integrity drift in `usage_5min` or the loaders feeding models | High | 3-layer suite — `tests/test_data_integrity.py` (TC-DATA-01…13) |
| R4 | Quota/rate-limit failure → runaway Gemini/BigQuery spend or lockout | Med-High | Boundary + fake-Firestore + degrade-open tests — `tests/test_quota.py`, `tests/test_api_contract.py`; burst k6 suite |
| R5 | API contract drift breaks the frontend proxy / e2e stub / k6 clients | Med | OpenAPI contract snapshot — TC-API-12 |
| R6 | UI unusable on error paths or small screens / for keyboard & AT users | Med | Regression e2e + axe scans, desktop & mobile projects (TC-UI-04…08) |
| R7 | Performance regression (latency SLO, cold starts, memory soak) | Med | Thresholded k6 suites — [loadtest/PERF-PLAN.md](loadtest/PERF-PLAN.md) |
| R8 | Vulnerable dependency ships | Med | `pip-audit` + `npm audit` gate in CI |

## 3. Test levels (the pyramid, as implemented)

| Level | Suite | Scope | Externals |
|---|---|---|---|
| **Unit** | `backend/tests` (detectors, metrics, quota decision, guards, data shaping); `frontend` vitest (charts, api client, proxy route) | pure logic | none |
| **Integration / API** | `tests/test_api*.py`, `test_quota.py`, `test_security.py` via httpx against the ASGI app | HTTP surface, DI-faked agent + fake Firestore | none |
| **System / E2E** | Playwright against the **production build** (standalone bundle, server-side proxy, stub backend that enforces the API key) | real user paths, desktop + mobile viewports | stubbed backend |
| **Non-functional** | k6 (perf), axe (accessibility), audits (deps); live BigQuery data-quality suite | SLOs & invariants | opt-in (real cloud / spend) |

Checks live at the lowest level that can catch them: quota window math is a unit
test, the 429 body shape is an API test, and only "the visitor sees the limit
message" is an e2e test.

## 4. Test design techniques

Named ISTQB black-box techniques, applied where they pay:

- **Equivalence partitioning** — request fields: valid / missing / wrong-type /
  out-of-enum (TC-API-04…07).
- **Boundary-value analysis** — `question` length 2000/2001, quota window at
  exactly-elapsed vs one-tick-before, count == limit (TC-API-01…03, TC-DATA-14).
- **State-transition testing** — quota window lifecycle (fill → block → reset);
  UI error → success recovery (TC-UI-06).
- **Error guessing / abuse corpus** — the injection corpus in
  `test_security.py`, grown whenever a new probe shape appears in the logs.
- **Exploratory testing** — time-boxed charters (§8).

## 5. Entry / exit criteria (the CI gate)

A change may merge when [`ci.yml`](.github/workflows/ci.yml) is green:

- backend: ruff clean · pytest green · line coverage ≥ **75%** (tripwire against
  untested new code — the number is a floor, not a target; GCP/torch-bound
  modules are exercised by opt-in suites instead)
- frontend: eslint clean · vitest green · production build succeeds
- e2e: smoke + regression on desktop **and** mobile viewports, including axe
  scans with zero serious/critical violations
- audit: no known HIGH+ vulnerabilities in production dependencies

Deploys are additionally gated by `deploy.yml`'s verify job. Release to prod =
push to main; the same suites must pass there.

Opt-in (not in the PR gate, by design):
- `BQ_INTEGRITY=1 pytest tests/test_data_integrity.py` — live warehouse checks
  (small real queries) after any reload/re-windowing of the dataset.
- `PW_ALL_BROWSERS=1 npm run test:e2e` — Firefox + WebKit cross-engine pass.
- k6 soak against staging — real Gemini/BigQuery spend, run deliberately.

## 6. Non-functional testing

- **Performance** — [loadtest/PERF-PLAN.md](loadtest/PERF-PLAN.md): load, spike
  (on the rejection chain) and soak suites with SLOs encoded as k6 thresholds;
  results are committed with interpretation in
  [loadtest/results/](loadtest/results/).
- **Security** — controls documented in [SECURITY.md](SECURITY.md) each have an
  enforcing test (`test_security.py`, `test_api_contract.py`); dependency audits
  gate CI. The structured search log is tested to carry no secrets and to bound
  hostile input (TC-SEC-06…08).
- **Accessibility** — axe (WCAG 2.0/2.1 A+AA) runs inside the e2e suite on both
  the landing and results views; serious/critical findings are defects
  (BUG-002 was found exactly this way).

## 7. Test environments

| Env | What runs | Notes |
|---|---|---|
| Local dev | everything except live-cloud suites | no GCP needed: agent faked via DI, Firestore faked, e2e uses the stub backend |
| CI (GitHub Actions) | the full PR gate | keyless (WIF) — no secrets needed by tests |
| Staging Cloud Run revision | k6 soak, manual exploratory | real spend; budget-capped project |
| Live warehouse | `BQ_INTEGRITY=1` data-quality suite | run after data loads / windowing changes |

## 8. Exploratory testing charters

Time-boxed (≤ 45 min), findings filed as issues:

1. *Probe the SQL guard as an attacker* — jailbreak phrasing (translations,
   role-play, encodings) trying to get destructive SQL authored; every emitted
   rejection joins the corpus in `test_security.py`.
2. *Quota edges on shared IPs* — behavior around window reset with concurrent
   tabs; look for premature lockout or double-count.
3. *LLM output weirdness* — force odd questions (emoji, non-Latin scripts,
   2000-char inputs) and judge the narrator's briefing for honesty against the
   detection payload.

## 9. Defect management

- Reported via the [bug template](.github/ISSUE_TEMPLATE/bug_report.yml):
  reproduction steps, expected vs actual, evidence, environment, severity &
  priority.
- **Severity** (impact): S1 data loss/security breach/total outage · S2 core flow
  broken, no workaround · S3 degraded with workaround · S4 cosmetic.
  **Priority** (urgency): P1 fix now · P2 this iteration · P3 scheduled · P4
  opportunistic. They are independent axes.
- Every fixed defect gets a regression test that failed before the fix, tagged
  with the defect ID. Worked examples from 2026-07-16, both found by the new
  mobile e2e project on its first run:
  - **BUG-001** (S2/P1): on phone-width viewports the ask-row overflowed and the
    Analyze button was unclickable. Fix: `globals.css` wrap rule; regression =
    every e2e test on the `mobile-chrome` project.
  - **BUG-002** (S3/P2): the generated-SQL block was scrollable but not
    keyboard-focusable (WCAG 2.1.1). Fix: focusable labeled region in
    `page.tsx`; regression = axe scan TC-UI-08.

## 10. Deliberately not automated

- **LLM answer quality** — the narrator's prose is judged by the eval/benchmark
  harness (`warehouse/*.md`) and exploratory charter #3, not asserted in CI:
  natural-language assertions on a nondeterministic model would be flaky by
  construction. CI pins everything *around* the LLM (guards, contracts,
  fallbacks) and the model is faked at the DI seam.
- **Visual pixel diffs** — the UI is one page and chart internals are covered by
  vitest component tests; screenshot baselines would cost more flake than they
  catch. Revisit if the surface grows.
- **k6 soak in CI** — it spends real money; it is a deliberate, human-triggered
  run against staging (see run book).
