"""Benchmark — MAD/EVT baseline vs OmniAnomaly on Alibaba cluster-trace-v2018
per-machine telemetry (the `primav2.alibaba_cluster.usage_5min` table built by
warehouse/alibaba_windowing.sql).

The point of this run (vs NF-UQ-NIDS-v2): the data has a REAL time axis, so each
machine is a regular multivariate time series — OmniAnomaly's home regime. The
hypothesis: where temporal/joint structure exists, OmniAnomaly should beat the
order-invariant baseline, especially on anomalies that don't trip a per-feature
threshold.

No labels ship with the trace, so we inject a documented MIX of synthetic
anomalies into held-out (test) machines and report PER TYPE (mle-practices §2):
  • spike  — a short, large magnitude excursion in one feature → a per-feature
             robust z-score catches it easily (baseline-favorable).
  • shift  — a sustained level shift in ONE feature, kept inside that feature's
             global range → it breaks the multivariate JOINT pattern without
             tripping a per-feature threshold (OmniAnomaly-favorable).
Train is on normal (un-injected) machines only. Both detectors are scored
per-machine (no cross-machine window leakage). Report raw + point-adjusted F1
and AUC-PR; trust AUC-PR (PA-F1 is inflated — see the NF benchmark).

Run:  uv run --directory backend --group ml python scripts/run_alibaba_benchmark.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from google.cloud import bigquery

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ root → import app.*

from app.detectors.baseline import BaselineDetector
from app.detectors.omnianomaly import OmniAnomalyDetector
from app.eval.metrics import evaluate

PROJECT = "primav2"
TABLE = "primav2.alibaba_cluster.usage_5min"
REPORT = Path(__file__).resolve().parents[2] / "warehouse" / "alibaba_benchmark_results.md"
JSON_PATH = Path(__file__).resolve().parents[2] / "warehouse" / "alibaba_benchmark_results.json"

FEATURES = ["cpu", "mem", "net_in", "net_out", "disk_io"]

# Selection / sizing (deterministic; machines sorted by id).
MIN_LEN = 600          # bins required to use a machine (≥ window + room for injection)
MIN_COVERAGE = 0.85    # fraction of bins present (rest forward-filled)
N_TRAIN = 50
N_TEST = 40
SEED = 0

OMNI_KW = dict(window=100, z_dim=3, hidden=64, n_flows=2,
               epochs=12, batch=256, mc_samples=8, lr=1e-3, seed=SEED)

# Injection knobs.
EVENTS_PER_MACHINE = 6
CTX_LEN = (12, 24)     # bins (~1–2h)
SPIKE_LEN = (1, 3)


def _device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


LIMIT_MACHINES = 120  # buffer above N_TRAIN+N_TEST; pull only what we need (not all 8.4M rows)


def load_series():
    """Return {machine_id: X[n,5] float32} as regular, gap-filled sequences.
    Pulls only the first LIMIT_MACHINES qualifying machines (by id) — coverage
    filtered in SQL so we don't stream the whole 8.4M-row table."""
    client = bigquery.Client(project=PROJECT)
    cols = ", ".join([f"u.{c}" for c in ["machine_id", "bin", *FEATURES]])
    sql = f"""
    WITH per_m AS (
      SELECT machine_id, COUNT(*) AS bins, MAX(bin)-MIN(bin)+1 AS span
      FROM `{TABLE}` GROUP BY machine_id ),
    ok AS (
      SELECT machine_id FROM per_m
      WHERE bins >= {MIN_LEN} AND SAFE_DIVIDE(bins, span) >= {MIN_COVERAGE}
      ORDER BY machine_id LIMIT {LIMIT_MACHINES} )
    SELECT {cols} FROM `{TABLE}` u JOIN ok USING (machine_id)
    ORDER BY u.machine_id, u.bin"""
    raw: dict = {}
    for r in client.query(sql).result():
        raw.setdefault(r["machine_id"], []).append(
            (int(r["bin"]), [r[c] for c in FEATURES]))

    series: dict = {}
    for mid, rows in raw.items():
        bins = [b for b, _ in rows]
        lo, hi = min(bins), max(bins)
        span = hi - lo + 1
        if span < MIN_LEN or len(rows) / span < MIN_COVERAGE:
            continue
        X = np.full((span, len(FEATURES)), np.nan, dtype=np.float32)
        for b, vals in rows:
            X[b - lo] = [np.nan if v is None else float(v) for v in vals]
        X = _ffill(X)
        if np.isnan(X).any():
            continue
        series[mid] = X
    return series


def _ffill(X: np.ndarray) -> np.ndarray:
    """Forward-fill then back-fill NaNs along time (axis 0), per feature."""
    for j in range(X.shape[1]):
        col = X[:, j]
        last = np.nan
        for i in range(len(col)):
            if np.isnan(col[i]):
                col[i] = last
            else:
                last = col[i]
        # back-fill any leading NaNs
        nxt = np.nan
        for i in range(len(col) - 1, -1, -1):
            if np.isnan(col[i]):
                col[i] = nxt
            else:
                nxt = col[i]
    return X


def inject(X: np.ndarray, rng: np.random.Generator, gmin, gmax):
    """Return (X_anom, labels[n], types[n]) — labels/types only on injected bins.
    Two deliberately-different anomaly types:
      • spike   — short, large magnitude excursion (way outside the global range)
                  → a per-feature robust z-score nails it (baseline-favorable).
      • context — replace a segment of ONE feature with a random RESAMPLE of that
                  same feature's own values. The marginal is unchanged, so a
                  per-feature z-score is blind to it; only the temporal + cross-
                  feature JOINT structure reveals it's out of place. The fair test
                  of OmniAnomaly's edge."""
    X = X.copy()
    n, d = X.shape
    y = np.zeros(n, dtype=int)
    types = np.array(["" for _ in range(n)], dtype=object)
    margin = 120  # keep events away from the edges
    for _ in range(EVENTS_PER_MACHINE):
        kind = rng.choice(["spike", "context"])
        j = int(rng.integers(d))
        if kind == "spike":
            length = int(rng.integers(*SPIKE_LEN))
            start = int(rng.integers(margin, n - margin - length))
            X[start:start + length, j] = gmax[j] + 3.0 * (gmax[j] - gmin[j] + 1e-6)
        else:  # context: per-feature marginal preserved, joint/temporal structure broken
            length = int(rng.integers(*CTX_LEN))
            start = int(rng.integers(margin, n - margin - length))
            X[start:start + length, j] = rng.choice(X[:, j], size=length)
        y[start:start + length] = 1
        types[start:start + length] = kind
    return X, y, types


def score_pooled(detector, seqs):
    scores = [detector.score(X) for X in seqs]
    return np.concatenate(scores)


def main() -> None:
    dev = _device()
    print(f">> Alibaba benchmark on {dev}")
    print(">> loading regular per-machine series from BigQuery ...")
    series = load_series()
    ids = sorted(series)
    print(f"   {len(ids)} machines pass coverage≥{MIN_COVERAGE}/len≥{MIN_LEN} "
          f"(median len {int(np.median([len(series[m]) for m in ids]))} bins)")

    train_ids = ids[:N_TRAIN]
    test_ids = ids[N_TRAIN:N_TRAIN + N_TEST]
    X_train = np.vstack([series[m] for m in train_ids])
    gmin, gmax = X_train.min(0), X_train.max(0)

    # Inject anomalies into the test machines (deterministic per-machine).
    test_seqs, test_y, test_types = [], [], []
    for k, m in enumerate(test_ids):
        Xa, y, t = inject(series[m], np.random.default_rng(SEED + 1 + k), gmin, gmax)
        test_seqs.append(Xa)
        test_y.append(y)
        test_types.append(t)
    y_all = np.concatenate(test_y)
    t_all = np.concatenate(test_types)
    n_test = len(y_all)
    print(f"   train {len(train_ids)} machines / {len(X_train):,} bins (normal); "
          f"test {len(test_ids)} machines / {n_test:,} bins, "
          f"{int(y_all.sum())} injected ({y_all.mean():.1%}): "
          f"spike={int((t_all=='spike').sum())}, context={int((t_all=='context').sum())}")

    print(">> fitting baseline (MAD/EVT) ...")
    baseline = BaselineDetector().fit(X_train)
    print(">> fitting OmniAnomaly ...")
    t0 = time.time()
    omni = OmniAnomalyDetector(n_features=len(FEATURES), device=dev, **OMNI_KW)
    hist = omni.fit(X_train)
    print(f"   OmniAnomaly trained ({time.time()-t0:.0f}s, final ELBO {hist[-1]:.1f})")

    b_scores = score_pooled(baseline, test_seqs)
    o_scores = score_pooled(omni, test_seqs)

    def grade(mask):
        return {
            "baseline": evaluate(y_all[mask], b_scores[mask]).as_dict(),
            "omnianomaly": evaluate(y_all[mask], o_scores[mask]).as_dict(),
        }

    benign = t_all == ""
    results = {
        "overall": grade(np.ones(n_test, dtype=bool)),
        "spike": grade(benign | (t_all == "spike")),
        "context": grade(benign | (t_all == "context")),
    }

    config = dict(table=TABLE, features=FEATURES, device=dev, seed=SEED,
                  n_train=len(train_ids), n_test=len(test_ids), test_bins=n_test,
                  injected=int(y_all.sum()), omni_kwargs=OMNI_KW,
                  events_per_machine=EVENTS_PER_MACHINE)
    JSON_PATH.write_text(json.dumps({"config": config, "results": results}, indent=2))
    report = _render(config, results)
    print("\n" + report)
    REPORT.write_text(report + "\n")
    print(f">> wrote {REPORT}")


_METRICS = ("raw_best_f1", "pa_best_f1", "auc_pr", "inflation_gap", "prevalence")


def _table(res) -> str:
    header = "| detector | " + " | ".join(_METRICS) + " |"
    sep = "|" + "---|" * (len(_METRICS) + 1)
    rows = [header, sep]
    for name in ("baseline", "omnianomaly"):
        r = res[name]
        rows.append("| " + name + " | " + " | ".join(f"{r[m]:.3f}" for m in _METRICS) + " |")
    return "\n".join(rows)


def _render(config, results) -> str:
    o, b = results["overall"]["omnianomaly"], results["overall"]["baseline"]
    winner = ("OmniAnomaly" if o["auc_pr"] > b["auc_pr"] + 0.02
              else "the baseline" if b["auc_pr"] > o["auc_pr"] + 0.02 else "neither (tie)")
    parts = [
        "# Benchmark — MAD/EVT baseline vs OmniAnomaly (Alibaba cluster-trace-v2018)",
        "",
        "Per-machine telemetry resampled to a **regular 5-min time series** "
        "(`warehouse/alibaba_windowing.sql`). Unlike NF-UQ-NIDS-v2, this data has a "
        f"real time axis. Device `{config['device']}`, seed {config['seed']}.",
        "",
        "## Setup",
        f"- **Train:** {config['n_train']} normal machines "
        f"({config['features']}). **Test:** {config['n_test']} machines, "
        f"{config['test_bins']:,} bins, {config['injected']:,} injected anomaly bins.",
        f"- **Injected (synthetic, labeled):** {config['events_per_machine']} events/machine, "
        "a mix of `spike` (magnitude → baseline-favorable) and `context` (one feature "
        "resampled from its OWN marginal → per-feature-undetectable by construction; only "
        "the joint/temporal model can see it → OmniAnomaly-favorable).",
        f"- **OmniAnomaly:** `{config['omni_kwargs']}`. Per-machine scoring.",
        "",
        "## Results",
        "",
        "### Overall",
        "",
        _table(results["overall"]),
        "",
        "### `spike` anomalies only (magnitude)",
        "",
        _table(results["spike"]),
        "",
        "### `context` anomalies only (per-feature-normal; joint/temporal break)",
        "",
        _table(results["context"]),
        "",
        "## Verdict",
        f"- **Overall AUC-PR:** OmniAnomaly {o['auc_pr']:.3f} vs baseline {b['auc_pr']:.3f} "
        f"→ **{winner}**.",
        f"- **The decisive cell is `context` AUC-PR** "
        f"(OmniAnomaly {results['context']['omnianomaly']['auc_pr']:.3f} vs baseline "
        f"{results['context']['baseline']['auc_pr']:.3f}): these anomalies are per-feature "
        "normal by construction, so a robust z-score is blind to them; only a joint/temporal "
        "model can see them. `spike` (magnitude) is the baseline-favorable control.",
        "- AUC-PR is the trusted metric; `pa_best_f1` is inflated (point-adjustment), shown "
        "for continuity with the other reports.",
        "",
        "## Caveats (mle-practices §3, §4)",
        "- **Synthetic labels.** Anomalies are injected, not ground-truth — the verdict is "
        "about *which detector sees which anomaly type*, not real-world cluster failures. "
        "The trace's real `disk_io` abnormals (-1/101) are too sparse (0.12%) to label on.",
        "- Single seed, capped machines, simplified/short-trained OmniAnomaly "
        "(hidden 64, 12 epochs). Full config in `alibaba_benchmark_results.json`.",
    ]
    return "\n".join(parts)


if __name__ == "__main__":
    main()
