# Benchmark — MAD/EVT baseline vs OmniAnomaly (Alibaba cluster-trace-v2018)

Per-machine telemetry resampled to a **regular 5-min time series** (`warehouse/alibaba_windowing.sql`). Unlike NF-UQ-NIDS-v2, this data has a real time axis. Device `mps`, seed 0.

## Setup
- **Train:** 50 normal machines (['cpu', 'mem', 'net_in', 'net_out', 'disk_io']). **Test:** 40 machines, 91,910 bins, 2,232 injected anomaly bins.
- **Injected (synthetic, labeled):** 6 events/machine, a mix of `spike` (magnitude → baseline-favorable) and `context` (one feature resampled from its OWN marginal → per-feature-undetectable by construction; only the joint/temporal model can see it → OmniAnomaly-favorable).
- **OmniAnomaly:** `{'window': 100, 'z_dim': 3, 'hidden': 64, 'n_flows': 2, 'epochs': 12, 'batch': 256, 'mc_samples': 8, 'lr': 0.001, 'seed': 0}`. Per-machine scoring.

## Results

### Overall

| detector | raw_best_f1 | pa_best_f1 | auc_pr | inflation_gap | prevalence |
|---|---|---|---|---|---|
| baseline | 0.156 | 0.260 | 0.115 | 0.104 | 0.024 |
| omnianomaly | 0.096 | 0.130 | 0.204 | 0.033 | 0.024 |

### `spike` anomalies only (magnitude)

| detector | raw_best_f1 | pa_best_f1 | auc_pr | inflation_gap | prevalence |
|---|---|---|---|---|---|
| baseline | 1.000 | 1.000 | 1.000 | 0.000 | 0.002 |
| omnianomaly | 0.749 | 0.757 | 0.753 | 0.008 | 0.002 |

### `context` anomalies only (per-feature-normal; joint/temporal break)

| detector | raw_best_f1 | pa_best_f1 | auc_pr | inflation_gap | prevalence |
|---|---|---|---|---|---|
| baseline | 0.044 | 0.153 | 0.021 | 0.109 | 0.022 |
| omnianomaly | 0.044 | 0.164 | 0.117 | 0.121 | 0.022 |

## Verdict
- **Overall AUC-PR:** OmniAnomaly 0.204 vs baseline 0.115 → **OmniAnomaly**.
- **The decisive cell is `context` AUC-PR** (OmniAnomaly 0.117 vs baseline 0.021): these anomalies are per-feature normal by construction, so a robust z-score is blind to them; only a joint/temporal model can see them. `spike` (magnitude) is the baseline-favorable control.
- AUC-PR is the trusted metric; `pa_best_f1` is inflated (point-adjustment), shown for continuity with the other reports.

## Caveats (mle-practices §3, §4)
- **Synthetic labels.** Anomalies are injected, not ground-truth — the verdict is about *which detector sees which anomaly type*, not real-world cluster failures. The trace's real `disk_io` abnormals (-1/101) are too sparse (0.12%) to label on.
- Single seed, capped machines, simplified/short-trained OmniAnomaly (hidden 64, 12 epochs). Full config in `alibaba_benchmark_results.json`.
