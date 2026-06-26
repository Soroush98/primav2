# Security Analysis

A senior-security-developer review of primav2. The central risk in this system is
that an **LLM authors SQL from untrusted natural-language input and a cloud data
warehouse executes it** — a classic confused-deputy / injection surface. This
document records the threat model, the controls in place, and the residual risks.

## Trust boundaries

```
 untrusted          semi-trusted (LLM)        trusted (our code)        Google Cloud
 ─────────          ──────────────────        ──────────────────        ────────────
 user question ──▶  Gemini writes SQL  ──▶  assert_read_only +     ──▶  BigQuery
                    (orchestrator,           assert_tables_in_project    (ADC identity)
                     sql_analyst,            + bytes cap + timeout
                     narrator)
```

The LLM is **not** trusted to produce safe SQL. Every query it emits is validated by
our code before BigQuery sees it.

## Controls in place

| # | Control | Where | Mitigates |
|---|---|---|---|
| 1 | **Read-only guard** — only `SELECT`/`WITH`; `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/MERGE/TRUNCATE/GRANT/REVOKE/CALL/EXPORT/LOAD/BEGIN/COMMIT` rejected | [`assert_read_only`](backend/app/agent/bigquery_tool.py) | data tampering / destruction |
| 2 | **No multi-statement** — embedded `;` rejected | `assert_read_only` | stacked-query injection |
| 3 | **Project allow-list** — every 3-part `project.dataset.table` ref must be in the configured project | [`assert_tables_in_project`](backend/app/agent/bigquery_tool.py) | cross-project/dataset exfiltration via prompt injection |
| 4 | **Cost cap** — `maximum_bytes_billed` (~50 GB, configurable) | `BigQueryRunner` | cost-DoS from full-table scans on the 247M-row table |
| 5 | **Query timeout** — 60s job + result timeout | `BigQueryRunner` | hung requests / latency-DoS |
| 6 | **Input bounds** — question `min_length=1, max_length=2000` | [`AnalyzeRequest`](backend/app/schemas.py) | oversized-input abuse |
| 7 | **CORS allow-list** — locked to `FRONTEND_ORIGIN`, methods `GET/POST` | [`main.py`](backend/app/main.py) | cross-origin abuse from arbitrary sites |
| 8 | **No static credentials** — Gemini uses Application Default Credentials; no API keys in code or env | [`gemini.py`](backend/app/llm/gemini.py) | key leakage |
| 9 | **Secrets ignored by git** — `.env`, `*.key`, `*-service-account*.json`, `data/` are git-ignored | [`.gitignore`](.gitignore) | secret/PII commit |
| 10 | **API key on `/api/analyze`** — constant-time `X-API-Key` check; the key lives server-side in the Next.js proxy ([`route.ts`](frontend/app/api/analyze/route.ts)), never in the browser | [`security.py`](backend/app/api/security.py) | anonymous abuse of a paid endpoint |
| 11 | **Rate limiting** — per-IP sliding window (default 30/min) → `429` | [`security.py`](backend/app/api/security.py) | request-flood / cost abuse |
| 12 | **Scale + budget caps** — Cloud Run `max-instances=3`, `concurrency=40`; a $25/mo billing budget with 50/90/100% alerts | deploy flags / GCP billing | runaway compute cost |
| 13 | **Keyless CI deploy** — GitHub→GCP via Workload Identity Federation, scoped to this repo; no SA JSON key stored | [`deploy.yml`](.github/workflows/deploy.yml) | CI credential leakage |

The agent also fails **closed and gracefully**: a rejected or failing query is caught,
recorded as `error`, and surfaced to the narrator — it never crashes the request or
silently executes.

## Residual risks & recommendations

Ranked; none block local/single-user use, all matter before a multi-tenant deploy.

1. **Least-privilege service account (highest priority for prod).** Control #3 stops
   *cross-project* reads, but within the project the ADC identity can read any dataset
   it is granted. In production, run the API as a dedicated service account with
   BigQuery read access scoped to **only** `alibaba_cluster` — defence in depth behind
   the allow-list.
2. **Client error sanitization.** `error` strings (BigQuery messages) are returned to
   the client and can disclose schema/internal detail. Log them server-side; return a
   generic message to the caller.
3. **Stronger auth (done at the shared-secret level).** `/api/analyze` now requires a
   server-held API key + per-IP rate limiting (controls #10–#11), so it is no longer
   anonymously abusable. For a multi-user product, upgrade the shared secret to real
   per-user identity (OAuth / IAP) and move the key to Secret Manager.
4. **Prompt-injection monitoring.** The allow-list + read-only guard contain the blast
   radius, but log generated SQL and alert on rejections to catch probing.
5. **Pin/scan dependencies.** `uv.lock` pins the backend; run dependency and image
   scanning (e.g. `pip-audit`, container scan) in CI.

## Credential & data handling

- **No secrets in the repo.** `.env` holds only non-secret config (project id, model,
  dataset, CORS origin) and is git-ignored; `.env.example` is the committed template.
- **Auth** is ADC (`gcloud auth application-default login`) — credentials live in the
  user/host environment, never in the repository.
- **Dataset** is public research data (Alibaba cluster-trace-v2018, CC-licensed) — no
  PII.

## Reporting

Open a private security advisory on the GitHub repository rather than a public issue.
