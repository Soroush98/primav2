# primav2

A **machine-reliability anomaly-detection agent** over the
[Alibaba cluster-trace-v2018](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2018)
telemetry (~247M per-machine samples · 4,023 machines · 8 days), rebuilt on Google
Cloud. It ports [Soroush98/prima](https://github.com/Soroush98/prima) — a LangGraph
reliability-analysis agent — from a local SMD-in-SQLite setup to a BigQuery +
Vertex AI stack.

Ask a natural-language question about cluster health; a five-node agent fleet turns
it into a read-only BigQuery query, runs anomaly detection over the result, ranks the
contributing metrics, and writes a briefing — with **Gemini 2.5 Flash on Vertex AI**
as the reasoning engine.

---

## What it does (request flow)

```
 Browser (Next.js 16)                          Google Cloud
 ───────────────────                          ─────────────
   AnalyzeForm  ──POST /api/analyze──▶  FastAPI  ──┐
   app/ui/analyze-form.tsx                         │  LangGraph fleet (app/agent/graph.py)
                                                   ▼
        ┌───────────────┬───────────────┬───────────────┬───────────────┬─────────────┐
        │ orchestrator  │  sql_analyst  │   detector    │  root_cause   │   narrator  │
        │ parse intent  │ text→SQL,     │ MAD/EVT score │ rank metrics  │ write the   │
        │   (Gemini)    │ read-only run │ + grade       │ by deviation  │  briefing   │
        │               │  (Gemini+BQ)  │  (NumPy)      │  (NumPy)      │  (Gemini)   │
        └───────┬───────┴───────┬───────┴───────────────┴───────────────┴──────┬──────┘
                │               │                                               │
          Vertex AI       BigQuery  ◀── read-only SELECT/WITH (guarded)         ▼
          (Gemini)        alibaba_cluster.*                          AnalyzeResponse → UI
```

Each node is a plain method on [`AgentNodes`](backend/app/agent/nodes.py), wired into
a linear graph in [`graph.py`](backend/app/agent/graph.py) and compiled once in
[`runtime.py`](backend/app/agent/runtime.py):

| Node | Role | Uses |
|---|---|---|
| `orchestrator` | parse the question into structured intent (focus + entities) | Gemini |
| `sql_analyst` | author **one** read-only SQL, validate it, run it on BigQuery | Gemini + BigQuery |
| `detector` | score each row with the MAD/EVT baseline; grade (raw + PA F1) if labels exist | NumPy/SciPy |
| `root_cause` | rank the metrics that drove the top anomalies (per-feature MAD deviation) | NumPy |
| `narrator` | turn the evidence into a human briefing | Gemini |

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
| API / compute | **Cloud Run** (stateless container) — *target deployment* | hosts the FastAPI app; runs locally in dev | n/a |
| Auth | **Application Default Credentials** (`gcloud auth application-default login`) | no API keys in the Gemini path | ✅ |

**Cost-conscious by design:** the only paid calls in the request path are managed
Gemini API calls and BigQuery queries. There are **no persistent Vertex AI model
endpoints** — the OmniAnomaly arm is trained **offline, run-to-completion** (locally
on Apple MPS / CPU) and batch-scored; nothing GPU-backed sits idle.

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

Two detectors are compared on the same data, graded the same way:

- **MAD/EVT baseline** ([`baseline.py`](backend/app/detectors/baseline.py)) — cheap,
  deterministic robust z-score + Peaks-Over-Threshold (SPOT, Siffer et al. 2017).
  **This is the shipped detector** (wired into the agent's `detector` node).
- **OmniAnomaly** ([`detectors/omnianomaly/`](backend/app/detectors/omnianomaly/)) — a
  PyTorch port of the stochastic-RNN VAE (Su et al., KDD 2019;
  [NetManAIOps/OmniAnomaly](https://github.com/NetManAIOps/OmniAnomaly)). Kept as the
  graded deep-learning comparison arm + per-dimension root-cause interpreter.
  Load-bearing mechanisms and documented deviations: [its README](backend/app/detectors/omnianomaly/README.md).

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
│  └─ tests/                        11 tests (pytest)
├─ frontend/                        Next.js 16 dashboard (App Router, React 19.2)
│  └─ app/                          page.tsx · components/Architecture.tsx · lib/api.ts
├─ warehouse/                       alibaba_windowing.sql + benchmark/validation reports
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

## Stack

| Plane | Tech |
|---|---|
| Data | BigQuery (cluster by `machine_id`) |
| Model | Gemini 2.5 Flash on Vertex AI — [`google-genai`](https://github.com/googleapis/python-genai) SDK |
| Agent | [LangGraph](https://github.com/langchain-ai/langgraph) (5-node linear fleet) |
| Detectors | MAD/EVT (NumPy/SciPy) · OmniAnomaly (PyTorch, `ml` dep group) |
| Backend | Python 3.13 · [FastAPI](https://fastapi.tiangolo.com/) 0.138 · `uv` |
| Frontend | [Next.js 16](https://nextjs.org/) (App Router, Turbopack, React 19.2) |
| Compute | Cloud Run (target; no persistent Vertex endpoints) |

## References

- **prima** (the project this rebuilds) — <https://github.com/Soroush98/prima>
- **Alibaba cluster-trace-v2018** (dataset) — <https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2018>
- **OmniAnomaly** — Su et al., *Robust Anomaly Detection for Multivariate Time Series through Stochastic Recurrent Neural Networks*, KDD 2019 · code + SMD dataset: <https://github.com/NetManAIOps/OmniAnomaly>
- **SPOT/POT (EVT thresholding)** — Siffer et al., *Anomaly Detection in Streams with Extreme Value Theory*, KDD 2017
- **Point-adjustment caveat** — Kim et al., *Towards a Rigorous Evaluation of Time-series Anomaly Detection*, AAAI 2022
