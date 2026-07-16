# User stories & acceptance criteria

The business-level view the QA process starts from: who uses primav2, what they
need, and the acceptance criteria each story must meet. In a Jira-based team
these would be tracker issues; here they are versioned with the code. The
derivation chain is:

**user story (US-\*)** → **requirement (REQ-\*, [test-cases/TRACEABILITY.md](test-cases/TRACEABILITY.md))** → **test cases (TC-\*)** → **automation**

Acceptance criteria are written testably (Given/When/Then) — an ambiguous
criterion is a defect in its own right (QA-STRATEGY §1, "shift-left"). Statuses:
✅ shipped & tested · 🧭 exploratory-only.

## Personas

| Persona | Who they are |
|---|---|
| **SRE** | on-call reliability engineer investigating fleet health; knows machines, not SQL |
| **Platform owner** | operates/pays for the deployment; cares about cost, abuse, and data safety |
| **ML engineer** | maintains the detector arms and benchmark; cares about data trustworthiness |

---

## US-01 — Ask about fleet health in plain language ✅

**As an** SRE, **I want** to ask a natural-language question about the fleet
**so that** I can find anomalous machines without writing BigQuery SQL.

**Acceptance criteria**
- Given a question, when I press Analyze, then I get a briefing, the generated
  SQL (visible, labeled read-only), a detection summary (windows analyzed,
  flagged count, threshold), and a per-agent trace of what ran.
- Given the flagged windows, then the top offenders are identified by machine
  and time, and the root-cause panel ranks the deviating metrics.

Requirements: REQ-01 · Cases: TC-UI-01, TC-API-12 · Suite: e2e smoke, test_agent.py

## US-02 — Choose (or trust) the detector arm ✅

**As an** SRE, **I want** to force a specific detector arm or leave it on Auto
**so that** I can compare model opinions on the same data.

**Acceptance criteria**
- Given the four modes (auto / baseline / omnianomaly / forecast), when I select
  any of them, then the request is honored and the response says which arm ran.
- Given a mode that can't apply (no model loaded, data not a time series), when
  the arm falls back to the baseline, then the response carries an explanatory
  note — a fallback is never silent.
- Given an unknown mode value, then the API rejects it (422) rather than guessing.

Requirements: REQ-02 · Cases: TC-API-06/07, TC-UI-05 · Suite: test_agent.py routing tests

## US-03 — Forecast a machine 2 days ahead ✅

**As an** SRE, **I want** a 2-day forecast of a machine's metrics **so that** I
can anticipate capacity problems instead of reacting to them.

**Acceptance criteria**
- Given forecast mode, when analysis completes, then I see recent history, the
  median forecast, and a q10–q90 uncertainty band per metric, switchable by
  feature chip, with the horizon stated in days.
- Given a forecast-only run, then no anomaly verdict is implied (no flagged
  count, no threshold) — a forecast is not a detection.

Requirements: REQ-01, REQ-02 · Cases: TC-UI-02 · Suite: e2e smoke, test_agent.py forecast tests

## US-04 — The agent can never damage or leak data ✅

**As a** platform owner, **I want** every LLM-authored query validated before
execution **so that** a prompt injection cannot destroy, alter, or exfiltrate
warehouse data.

**Acceptance criteria**
- Given any generated SQL, when it is not a single read-only SELECT/WITH scoped
  to our project, then it is rejected before BigQuery sees it.
- Given a rejected query, then the request still completes gracefully with the
  error recorded — fail-safe, not fail-crash.
- Given a hostile question that manipulates the LLM into destructive SQL, then
  the payload never reaches the warehouse boundary (proven end-to-end).

Requirements: REQ-03 · Cases: TC-SEC-01…05 · Suite: test_security.py + exploratory charter #1

## US-05 — Abuse can't run up the bill ✅

**As a** platform owner, **I want** per-IP rate limits and a persistent search
quota **so that** anonymous abuse cannot generate unbounded Gemini/BigQuery spend.

**Acceptance criteria**
- Given a missing/wrong API key, then the request is rejected 401 with a stable
  `{code, message}` body that never echoes the submitted key.
- Given a burst over the per-minute limit, or a quota-exhausted IP, then 429
  with `rate_limited` / `quota_exceeded` codes; other IPs are unaffected.
- Given a Firestore outage, then the quota check degrades open — protection
  failure must never become an API outage.
- Given rejected traffic, then rejections are fast and cheap (p95 < 300 ms,
  never 5xx) so the protection can't be turned into a DoS.

Requirements: REQ-04, REQ-09 · Cases: TC-API-08…11, 13…15, TC-UI-04, TC-PERF-02 · Suite: test_api_contract.py, test_quota.py, e2e, burst-rejections.js

## US-06 — Usable on a phone ✅

**As an** SRE on call, **I want** the dashboard to work at phone widths
**so that** I can check the fleet from wherever the page gets me.

**Acceptance criteria**
- Given a small viewport, then the ask-row controls wrap and every control —
  including Analyze — is reachable and clickable.
- Given results, then KPIs, charts and chips render without horizontal page scroll.

Requirements: REQ-08 · Cases: all TC-UI on the `mobile-chrome` project
· Defect history: BUG-001 (found by this story's suite, fixed 2026-07-16)

## US-07 — Operable without a mouse ✅

**As a** keyboard / assistive-technology user, **I want** the dashboard to meet
WCAG A/AA **so that** I can run and read an analysis without a pointer.

**Acceptance criteria**
- Given the landing and results views, when scanned by axe (WCAG 2.0/2.1 A+AA),
  then zero serious/critical violations.
- Given scrollable content (the generated-SQL block), then it is
  keyboard-focusable and labeled.

Requirements: REQ-08 · Cases: TC-UI-07/08 · Defect history: BUG-002

## US-08 — Failures explain themselves and recover ✅

**As an** SRE, **I want** clear, recoverable error states **so that** a backend
hiccup or my exhausted quota doesn't wedge the session or leave me guessing.

**Acceptance criteria**
- Given a backend failure (5xx), then an error card explains it — no crash, no
  infinite spinner; given a quota rejection, then the limit message is shown and
  the form stays usable.
- Given a subsequent successful query, then the error clears and results render.
- Given SQL that matches nothing, then an honest zero-state (0 windows, "no rows
  returned") renders instead of a broken chart.

Requirements: REQ-08 · Cases: TC-UI-03…06 · Suite: e2e smoke + regression

## US-09 — Verdicts rest on trustworthy data ✅

**As an** ML engineer, **I want** the warehouse windowing and loaders to honor
their documented invariants **so that** detector verdicts and benchmark claims
are built on sound data.

**Acceptance criteria**
- Given the `usage_5min` table, then keys are unique, every raw sample reconciles
  into exactly one bin, metric domains hold, and NULL disk_io only ever means
  "all samples were abnormal markers".
- Given the model loaders, then gap-filling never rewrites observed values and
  never fabricates data for an empty feature; synthetic anomaly labels exactly
  match the modified regions.
- Given the committed benchmark artifacts, then they stay internally consistent
  (metrics are valid probabilities, config matches code).

Requirements: REQ-07 · Cases: TC-DATA-01…13 · Suite: test_data_integrity.py (+ `BQ_INTEGRITY=1` live layer)

## US-10 — Usage is observable without becoming a liability ✅

**As a** platform owner, **I want** structured logs of every search **so that**
I can monitor usage and probing attempts without logging secrets or unbounded
payloads.

**Acceptance criteria**
- Given a search, then exactly one parseable JSON line is emitted with the
  documented fields only — no credentials, headers, or key material.
- Given a pathological 50k-char question, then the logged copy is capped at
  2000 chars.

Requirements: REQ-06 · Cases: TC-SEC-06…08 · Suite: test_security.py

## US-11 — The narrator tells the truth about the models 🧭

**As an** SRE, **I want** the briefing's prose to faithfully reflect the
detection payload **so that** I'm never told a story the numbers don't support.

**Acceptance criteria**
- Given any completed analysis, then claims in the briefing (counts, top
  machine, direction of deviation) agree with the detection payload.

Deliberately not CI-automated (QA-STRATEGY §10 — nondeterministic LLM output);
covered by exploratory charter #3 and the offline benchmark reports in
[warehouse/](../warehouse/). Requirements: REQ-01.
