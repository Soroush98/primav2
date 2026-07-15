# Load tests (k6)

Three scoped [k6](https://grafana.com/docs/k6/latest/) scenarios for the FastAPI
backend. A full-throttle stress test of `/api/analyze` would mostly load-test the
Vertex/BigQuery bill, so each script targets one specific question instead:

| Script | Question it answers | Cost |
|---|---|---|
| `burst-rejections.js` | Do auth/rate-limit/quota rejections stay fast, correct, and 5xx-free under a burst? | Free — no request reaches Gemini/BigQuery |
| `soak-analyze.js` | Does the real analyze path hold latency/error SLOs under sustained paced load (memory headroom at `--concurrency=40` on 1 GiB)? | **Real Gemini + BigQuery spend per iteration** |
| `health-ramp.js` | How do cold starts / `max-instances` saturation look as request rate ramps? | Free |

## Install

```sh
brew install k6        # or: https://grafana.com/docs/k6/latest/set-up/install-k6/
```

## Run

Against a local backend:

```sh
cd backend && API_KEY=dev-key uv run uvicorn app.main:app --port 8000
```

```sh
cd loadtest
BASE_URL=http://127.0.0.1:8000 API_KEY=dev-key k6 run burst-rejections.js
BASE_URL=http://127.0.0.1:8000 k6 run health-ramp.js
BASE_URL=http://127.0.0.1:8000 API_KEY=dev-key RATE_PER_MIN=6 DURATION=2m k6 run soak-analyze.js
```

Against Cloud Run (prefer a staging revision, not prod):

```sh
BASE_URL=https://prima-backend-<hash>.run.app API_KEY=$BACKEND_API_KEY \
  REJECT_P95_MS=500 k6 run burst-rejections.js   # higher budget for WAN RTT
```

All knobs are env vars with defaults visible at the top of each script
(`DURATION`, `RATE_PER_MIN`, `PEAK_RPS`, `P95_MS`, …). Thresholds are enforced:
k6 exits non-zero when one fails, so the scripts are CI-gateable as-is.

## How the free scripts avoid spend

The backend runs its protection dependencies (API key → rate limit → quota)
*before* request-body validation, so `burst-rejections.js` sends a body that fails
pydantic (`question: ""`). Every request exercises the full protection chain and is
rejected at 401/422/429 without ever building SQL or calling Gemini.

Both scripts set `X-Real-Client-IP` (the header the Next.js proxy normally
forwards; the backend trusts it only because reaching it requires the API key):
`burst-rejections.js` pins one synthetic IP so the rate-limit window fills
deterministically; `soak-analyze.js` gives each VU its own so the soak measures
capacity, not a single IP's limit.

## Reading results

- **burst**: any 5xx or a slow rejection (`p(95)` over budget) fails the run — that
  means the limiter or auth path degrades under concurrency. All-`422` with no
  `429` in `over_limit` means the server's rate limit is disabled; all-`422` in
  `bad_key` means `API_KEY` isn't set on the server.
- **soak**: watch the Cloud Run *memory utilization* dashboard while it runs. OOM
  restarts or a climbing p95 mean `--concurrency=40` is too high for 1 GiB with the
  torch/Chronos models resident — lower concurrency or raise memory. Per-IP quota
  (`QUOTA_PER_WINDOW`) must be 0 (or generous) on the target, or the soak will wall
  at 429s once each synthetic IP burns its budget.
- **health-ramp**: p99 spikes during the ramp are cold starts (expected with
  `min-instances=1` warm); sustained errors at peak mean `max-instances=3` is
  saturated and callers queue or get 429/503 from Cloud Run itself.
