# Performance & Load Test Plan

Companion to [QA-STRATEGY.md](../QA-STRATEGY.md) §6. Tooling is [k6](https://k6.io)
(`brew install k6`). Every script encodes its SLOs as k6 `thresholds`, so a run is
**pass/fail**, not a demo — a threshold breach exits non-zero.

## Test types → scripts

| ISTQB perf type | Question it answers | Script | Cost |
|---|---|---|---|
| **Load (ramp)** | Does `/api/health` hold its latency SLO while Cloud Run scales out? What do cold starts add at the tail? | [`health-ramp.js`](health-ramp.js) | Free (no LLM/BQ) |
| **Spike / negative load** | Are rejections (401 / 422 / 429) fast, correct, and never 5xx under a hostile burst? | [`burst-rejections.js`](burst-rejections.js) | Free (protection chain rejects before the agent runs) |
| **Soak** | Does the real analyze path (Gemini + BigQuery) hold p95 and error-rate over sustained traffic? Does memory drift toward the 1 GiB × concurrency=40 failure mode? | [`soak-analyze.js`](soak-analyze.js) | **Real money** — every iteration spends Gemini + BigQuery. Run deliberately, against staging. |

## SLOs (thresholds encoded in the scripts)

| Surface | SLO | Where |
|---|---|---|
| `/api/health` | p95 < 500 ms (includes cold starts at the tail) | `health-ramp.js` `P95_MS` |
| Rejection paths (401/422/429) | p95 < 300 ms, 100% correct status, never 5xx | `burst-rejections.js` `REJECT_P95_MS` + checks |
| `/api/analyze` (LLM-bound) | p95 < 45 s, error rate < 2% | `soak-analyze.js` `P95_MS` |

Rejections are a performance surface in their own right: if a 429 is slow or
expensive, the rate limiter is itself a DoS vector.

## Workload modeling

- Arrival-rate executors (`constant-arrival-rate`, `ramping-arrival-rate`), not
  looping VUs — we model *offered load*, which keeps pressure honest when latency
  grows.
- `soak-analyze.js` spreads synthetic `X-Real-Client-IP` values across VUs so the
  per-IP limiter and Firestore quota see *distinct users*, measuring capacity
  rather than one IP's rate limit. (The header is only trusted behind the API
  key — see `backend/app/api/security.py`.)

## Run book

```bash
# local backend (free suites)
cd backend && API_KEY=local-perf-key uv run uvicorn app.main:app --port 8123
BASE_URL=http://127.0.0.1:8123 k6 run health-ramp.js
BASE_URL=http://127.0.0.1:8123 API_KEY=local-perf-key k6 run burst-rejections.js

# staging Cloud Run (spends money — see soak-analyze.js header first)
BASE_URL=https://prima-backend-....run.app API_KEY=$BACKEND_API_KEY k6 run soak-analyze.js
```

## Recording results

Every meaningful run gets a file in [`results/`](results/): date, git revision,
environment, the numbers, and an interpretation. An untracked perf result might
as well not have happened. Use `--summary-export out.json` for the raw numbers.

Watch during Cloud Run runs: instance count, memory per instance (the
1 GiB / concurrency=40 ceiling is the known failure mode `soak-analyze.js`
exists to catch), and 5xx counts in the Cloud Run metrics dashboard.
