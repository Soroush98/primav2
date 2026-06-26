# Training the global OmniAnomaly model

This trains **one** OmniAnomaly model on a pool of normal Alibaba machines and writes
a checkpoint to GCS. It's a **run-to-completion** job: a GPU spins up, trains,
uploads the checkpoint, and **terminates** — no persistent endpoint, no idle GPU.

```
 usage_5min (BigQuery)  ──▶  train_omni.py  ──▶  gs://primav2-models/omni/omni_global.pt
   N normal machines          (GPU, runs once)        + metrics.json
                                                              │
                                                              ▼  (serving step, later)
                                                    Cloud Run loads at startup
```

## Why a global model (not per-machine)

The Alibaba fleet is homogeneous (scheduler-balanced, 5 metrics) and each machine has
only ~2,000 5-min bins — too thin to train a good per-machine VAE. Pooling a few
hundred machines gives ~0.5–1M training windows and **one model that scores any
machine, including unseen ones**. The benchmark already showed this generalizes:
trained on 50 machines, it beat the baseline on 40 disjoint machines. See
[`fit_series`](backend/app/detectors/omnianomaly/detector.py) — windows are built
*within* each machine (no cross-boundary leakage); standardization + threshold are
pooled.

## Run it on GCP (recommended)

One-time: you need the runtime SA from [DEPLOY.md](DEPLOY.md) step 0 (`prima-run`,
with `aiplatform.user` + read-only BigQuery). The script creates the GCS bucket and
grants the SA write access itself.

```bash
cd backend
./scripts/submit_train_job.sh
# stronger config:
HIDDEN=256 N_FLOWS=20 EPOCHS=40 N_TRAIN=500 ./scripts/submit_train_job.sh
# cheaper GPU:
ACCELERATOR=NVIDIA_TESLA_T4 MACHINE_TYPE=n1-standard-8 ./scripts/submit_train_job.sh
```

It builds [`Dockerfile.train`](backend/Dockerfile.train) (CUDA torch), pushes to
Artifact Registry, and submits a Vertex **custom job** on 1× L4.

- **Cost:** ~30–90 min on L4 ($0.7/hr) ≈ **$1–3, one-time**. Only the checkpoint
  lingers in GCS (~free). Your $25/mo budget alert backstops it.
- **Watch:** `gcloud ai custom-jobs list --region=us-central1 --project=primav2`
- **Output:** `gs://primav2-models/omni/omni_global.pt` + `metrics.json`
  (best-seed AUC-PR overall/spike/context, plus mean±std across seeds).

> Use a Vertex **custom job**, not a raw GPU VM. The custom job auto-terminates and
> leaves no disk; a forgotten VM keeps billing (and its disk bills even when stopped).

## Run it locally first (free smoke test)

CPU/MPS, tiny config, local output — good for verifying the pipeline before paying
for a GPU:

```bash
cd backend
N_TRAIN=20 N_VAL=6 HIDDEN=32 N_FLOWS=2 EPOCHS=3 SEEDS=0 CHECKPOINT_DIR=./omni_out \
  uv run --group ml python scripts/train_omni.py
# → ./omni_out/omni_global.pt + metrics.json
```

## Config knobs (env vars)

| Var | Default | Notes |
|---|---|---|
| `N_TRAIN` / `N_VAL` | 300 / 40 | pooled train machines / held-out validation machines |
| `HIDDEN` | 128 | GRU width — the main size lever (paper uses 500) |
| `N_FLOWS` | 10 | planar-flow depth (paper ~20) |
| `Z_DIM` | 3 | latent bottleneck |
| `WINDOW` | 100 | sequence length (~8 h of 5-min bins) |
| `EPOCHS` | 30 | |
| `BATCH` | 256 | |
| `MC_SAMPLES` | 8 | posterior samples at scoring |
| `SEEDS` | 0,1,2 | trains each; ships the best-AUC-PR one, reports mean±std |
| `CHECKPOINT_DIR` | `gs://primav2-models/omni` | local path or `gs://…`; Vertex's `AIP_MODEL_DIR` is honoured if unset |

## Serving the checkpoint (next step — not wired yet)

`OmniAnomalyDetector.load("omni_global.pt")` returns a ready-to-`score` detector
(weights + standardization + threshold). To put it in the request path, the backend
would download it from GCS at startup and the `detector` node would call `.score()`
(no fit). That adds CPU torch to the serving image — tracked separately as "Option
A." Until then, training produces a validated checkpoint you can benchmark offline.
