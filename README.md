# primav2

A **machine-reliability anomaly-detection agent** over the
[Alibaba cluster-trace-v2018](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2018)
telemetry (~247M per-machine samples · 4,023 machines · 8 days), rebuilt on Google
Cloud. It ports [Soroush98/prima](https://github.com/Soroush98/prima) — a LangGraph
reliability-analysis agent — from a local SMD-in-SQLite setup to a BigQuery +
Vertex AI stack.

Ask a natural-language question about cluster health; a LangGraph agent fleet turns
it into a read-only BigQuery query and **routes it to one of three model arms**: two
anomaly detectors (MAD/EVT baseline · OmniAnomaly), which also rank the contributing
metrics, or a **2-day Chronos-Bolt forecast**. A narrator then writes a briefing —
with **Gemini 2.5 Flash on Vertex AI** as the reasoning engine.

---

## What it does (request flow)

```
 Browser (Next.js 16)                       Google Cloud
 ───────────────────                        ─────────────
   ask + detector selector ─POST /api/analyze─▶ FastAPI · LangGraph fleet (app/agent/graph.py)
   app/page.tsx

   orchestrator ─▶ sql_analyst ─▶ ⟨route_detector⟩ ─┬─▶ detector_baseline   (MAD/EVT · NumPy)
   parse intent    text→SQL +      conditional edge  ├─▶ detector_omni       (OmniAnomaly · torch)
     (Gemini)      read-only run    by mode + shape   └─▶ detector_forecast   (Chronos-Bolt · torch)
                   (Gemini + BQ)                                  │
                anomaly arms ─▶ root_cause ─▶ narrator ─▶ AnalyzeResponse → UI
                                rank (NumPy)    briefing (Gemini)
                forecast arm ──────────────▶ narrator   (2-day forecast — no anomaly step)
```

Each node is a method on [`AgentNodes`](backend/app/agent/nodes.py). The graph
([`graph.py`](backend/app/agent/graph.py)) is linear except for the detector step,
which is a **conditional route**: after `sql_analyst`, `route_detector` picks an arm
(by the request's detector mode + the data shape). The anomaly arms converge into
`root_cause`; the forecast arm produces no anomalies, so it goes straight to the
`narrator`. The UI exposes the choice as a selector; `auto` sends per-machine time
series to OmniAnomaly and latest-bin snapshots to the baseline.

| Node | Role | Uses |
|---|---|---|
| `orchestrator` | parse the question into structured intent (focus + entities) | Gemini |
| `sql_analyst` | author **one** read-only SQL (snapshot vs per-machine series, by mode), run it | Gemini + BigQuery |
| `route_detector` | **conditional edge** — choose the detector arm by mode (+ data shape for `auto`) | — |
| `detector_baseline` | MAD/EVT robust z-score + POT; order-invariant — fleet snapshots | NumPy/SciPy |
| `detector_omni` | OmniAnomaly VAE — windows each machine's series for temporal anomalies | PyTorch |
| `detector_forecast` | Chronos-Bolt zero-shot **2-day forecast** of a machine's metrics (no anomaly detection) | PyTorch / transformers |
| `root_cause` | rank the metrics that drove the top anomalies (per-feature MAD deviation) | NumPy |
| `narrator` | turn the evidence into a human briefing | Gemini |

A 3rd-arm-style extension (a new detector or an ensemble) drops in as one more
`detector_*` node + a `route_detector` branch + a graph entry — nothing else changes.

**Safety:** the only SQL that reaches BigQuery is gated by
[`assert_read_only()`](backend/app/agent/bigquery_tool.py) (SELECT/WITH only — write
and DDL keywords are rejected). CORS is locked to the frontend origin in
[`main.py`](backend/app/main.py).

---

## What runs on Google Cloud

| Component | Google Cloud service | Role | In the request path? |
|---|---|---|---|
| Data warehouse | **BigQuery** (`primav2.alibaba_cluster`) | stores raw + resampled telemetry; serves the `sql_analyst`'s queries | ✅ yes |
| Reasoning engine | **Vertex AI — Gemini 2.5 Flash** (via the [`google-genai`](backend/app/llm/gemini.py) SDK, `vertexai=True`) | intent parsing, text→SQL, narration | ✅ yes (3 nodes) |
| API / compute | **Cloud Run** (stateless container) — **live** (CI/CD on push to main) | hosts the FastAPI app + serves the detector arms | ✅ |
| Auth | **Application Default Credentials** (`gcloud auth application-default login`) | no API keys in the Gemini path | ✅ |

**Cost-conscious by design:** the only paid calls in the request path are managed
Gemini API calls and BigQuery queries. There are **no persistent Vertex AI model
endpoints** — OmniAnomaly is trained **offline, run-to-completion** (a Vertex custom
job on a Spot GPU; see [TRAINING.md](TRAINING.md)) and the resulting checkpoint is
loaded once at container startup to **score on demand**; Chronos-Bolt is **zero-shot**
(no training). The detector torch/transformers arms make the image larger and cold
starts slower, so they're opt-in via env (`OMNI_CHECKPOINT_URI`, `CHRONOS_MODEL`);
unset ⇒ the agent serves the baseline only.

### BigQuery contents (`primav2.alibaba_cluster`)

| Table | Rows | What |
|---|---|---|
| `machine_usage` | 246,934,820 | raw per-machine samples (cpu/mem/net/disk, `time_stamp` in seconds) |
| `usage_5min` | 8,389,672 | regular 5-min-bin per-machine series — the detector's unit (built by [`alibaba_windowing.sql`](warehouse/alibaba_windowing.sql)) |
| `machine_meta` | 17,592 | machine status snapshots |

The exact table/column descriptions the agent sees live in `SCHEMA_HINT` in
[`nodes.py`](backend/app/agent/nodes.py).

---

## Detection & evaluation

Two anomaly-detection arms (graded the same way) plus a forecast arm, each the right
tool for a different regime:

- **MAD/EVT baseline** ([`baseline.py`](backend/app/detectors/baseline.py)) — cheap,
  deterministic robust z-score + Peaks-Over-Threshold (SPOT, Siffer et al. 2017).
  Order-invariant; the default for fleet snapshots and the always-available fallback.
- **OmniAnomaly** ([`detectors/omnianomaly/`](backend/app/detectors/omnianomaly/)) — a
  PyTorch port of the stochastic-RNN VAE (Su et al., KDD 2019;
  [NetManAIOps/OmniAnomaly](https://github.com/NetManAIOps/OmniAnomaly)). Trained
  globally (see [TRAINING.md](TRAINING.md)) and **served on demand** for per-machine
  temporal anomalies. Mechanisms + deviations: [its README](backend/app/detectors/omnianomaly/README.md).
- **Chronos-Bolt** ([`chronos.py`](backend/app/detectors/chronos.py)) — Amazon's
  zero-shot time-series foundation model, serving a pure **2-day forecast**: the
  machine's 5-min series is resampled to hourly means and the model predicts the next
  48 hours per metric with a q10/q50/q90 uncertainty band — inside its native 64-step
  single-shot horizon, and short relative to the trace's 8 days of history. No anomaly
  detection — no scores, thresholds, or flags on this arm.

The two anomaly arms implement the same `score`/`threshold_` shape; all three are
behind `route_detector` and the user picks one (or `auto`) from the UI selector.

**Metric rigor** ([`metrics.py`](backend/app/eval/metrics.py)): every comparison
reports **raw best-F1 and AUC-PR (strict, trusted)** alongside **point-adjusted
best-F1 (lenient, inflated)**. Point-adjustment flatters — a near-random scorer can
reach ~1.0 (Kim et al. 2022) — so it is shown only for comparability, never as the
verdict.

### Key finding (the whole reason for the dataset choice)

OmniAnomaly is a *temporal* model; it only pays off when the data has a real time
axis. Demonstrated across datasets:

| Dataset | Time axis? | Winner (AUC-PR) | Report |
|---|---|---|---|
| Alibaba cluster trace | ✅ real | **OmniAnomaly** overall (0.204 vs 0.115); the *only* detector that sees per-feature-normal contextual anomalies (0.117 vs baseline 0.021 ≈ chance) | [alibaba_benchmark_results.md](warehouse/alibaba_benchmark_results.md) |
| SMD (faithfulness check) | ✅ real | OmniAnomaly beats the baseline on all 3 machines (4–7× floor) — confirms the port is faithful | [smd_validation.md](warehouse/smd_validation.md) |
| *NF-UQ-NIDS-v2 (removed)* | ✗ none | baseline won — no timestamp, so the temporal model had nothing to exploit | *(explored, then removed)* |

Run them yourself: [`run_alibaba_benchmark.py`](backend/scripts/run_alibaba_benchmark.py)
(baseline vs OmniAnomaly with injected, labeled anomalies) and
[`validate_smd.py`](backend/scripts/validate_smd.py) (port faithfulness vs the paper).

---

## Repository layout

```
primav2/
├─ backend/                         FastAPI app + agent + detectors + eval
│  ├─ app/
│  │  ├─ main.py                    app factory, lifespan, CORS
│  │  ├─ config.py                  pydantic-settings (env-driven)
│  │  ├─ schemas.py                 request/response models
│  │  ├─ api/routes.py              /api/health, /api/analyze
│  │  ├─ llm/gemini.py              Gemini-on-Vertex provider (ADC auth)
│  │  ├─ agent/                     graph.py · nodes.py · runtime.py · state.py · bigquery_tool.py
│  │  ├─ detectors/                 baseline.py · omnianomaly/
│  │  └─ eval/                      metrics.py · benchmark.py
│  ├─ scripts/                      run_alibaba_benchmark.py · validate_smd.py
│  └─ tests/                        pytest: unit · API contract · security · data integrity
├─ frontend/                        Next.js 16 dashboard (App Router, React 19.2)
│  ├─ app/                          page.tsx · components/Architecture.tsx · lib/api.ts
│  └─ e2e/                          Playwright (desktop + mobile) + stub backend
├─ docs/                            user-stories.md · test-cases/ (catalog + traceability)
├─ loadtest/                        k6 perf suites · PERF-PLAN.md · recorded results
├─ warehouse/                       alibaba_windowing.sql + benchmark/validation reports
├─ QA-STRATEGY.md                   risk-based test strategy (levels, gates, defects)
└─ scripts/get_alibaba.sh           download trace → load into BigQuery
```

---

## Quickstart

**Prerequisites:** a GCP project with BigQuery + Vertex AI enabled, the `gcloud` CLI,
`uv` (Python), and Node.js 20+.

```bash
# 0. Auth (no API keys — Application Default Credentials)
gcloud auth application-default login

# 1. Backend
cd backend && uv sync                 # add --group ml for the OmniAnomaly/benchmark deps (torch)
cp .env.example .env                  # set GOOGLE_CLOUD_PROJECT; BIGQUERY_DATASET=alibaba_cluster
uv run fastapi dev app/main.py        # http://localhost:8000  (/api/health, /api/analyze)

# 2. Frontend (separate terminal)
cd frontend && npm install && npm run dev   # http://localhost:3000

# 3. (Optional) Load the data + reproduce the benchmarks
bash scripts/get_alibaba.sh                                   # → BigQuery alibaba_cluster.*
bq query --use_legacy_sql=false < warehouse/alibaba_windowing.sql   # → usage_5min
uv run --directory backend --group ml python scripts/run_alibaba_benchmark.py
```

Tests: `uv run --directory backend pytest` (the OmniAnomaly/benchmark tests also need
`--group ml`).

---

## Quality & testing

Strategy, risk analysis and gates: [QA-STRATEGY.md](QA-STRATEGY.md) · user
stories + acceptance criteria: [docs/user-stories.md](docs/user-stories.md) ·
test cases + traceability: [docs/test-cases/](docs/test-cases/) · performance:
[loadtest/PERF-PLAN.md](loadtest/PERF-PLAN.md). CI
([.github/workflows/ci.yml](.github/workflows/ci.yml)) gates every PR on all of
the below except the opt-in suites.

```bash
# backend: lint + unit/API/security/data-integrity tests + coverage gate
cd backend && uv run ruff check app scripts tests && uv run pytest --cov=app

# frontend: unit (vitest) + e2e (Playwright, desktop & mobile, incl. axe a11y)
cd frontend && npm run test && npm run test:e2e          # or test:e2e:smoke

# opt-in: live BigQuery data-quality · cross-engine e2e · perf
BQ_INTEGRITY=1 uv run pytest tests/test_data_integrity.py   # backend/
PW_ALL_BROWSERS=1 npm run test:e2e                          # frontend/
k6 run loadtest/health-ramp.js                              # see PERF-PLAN.md
```

## Deploy

Both services run on **Cloud Run** (containerized; the backend image excludes
`torch`). Step-by-step — service account, both deploys, CORS, and a Vercel
alternative for the frontend — in **[DEPLOY.md](DEPLOY.md)**.

```bash
cd backend && gcloud run deploy prima-backend --source . --region us-central1 ...
# then build the frontend image with the backend URL and deploy it. See DEPLOY.md.
```

## Stack

| Plane | Tech |
|---|---|
| Data | BigQuery (cluster by `machine_id`) |
| Model | Gemini 2.5 Flash on Vertex AI — [`google-genai`](https://github.com/googleapis/python-genai) SDK |
| Agent | [LangGraph](https://github.com/langchain-ai/langgraph) (fleet + conditional detector route) |
| Model arms | MAD/EVT (NumPy/SciPy) · OmniAnomaly (PyTorch) · Chronos-Bolt 2-day forecast (transformers) — routed |
| Backend | Python 3.13 · [FastAPI](https://fastapi.tiangolo.com/) 0.138 · `uv` |
| Frontend | [Next.js 16](https://nextjs.org/) (App Router, Turbopack, React 19.2) |
| Compute | Cloud Run — live (scale-to-zero; no persistent Vertex endpoints) |

## References

- **prima** (the project this rebuilds) — <https://github.com/Soroush98/prima>
- **Alibaba cluster-trace-v2018** (dataset) — <https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2018>
- **OmniAnomaly** — Su et al., *Robust Anomaly Detection for Multivariate Time Series through Stochastic Recurrent Neural Networks*, KDD 2019 · code + SMD dataset: <https://github.com/NetManAIOps/OmniAnomaly>
- **SPOT/POT (EVT thresholding)** — Siffer et al., *Anomaly Detection in Streams with Extreme Value Theory*, KDD 2017
- **Point-adjustment caveat** — Kim et al., *Towards a Rigorous Evaluation of Time-series Anomaly Detection*, AAAI 2022
