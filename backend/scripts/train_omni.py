"""Run-to-completion trainer for ONE global OmniAnomaly model on Alibaba telemetry.

Pools N normal machines from BigQuery ``usage_5min``, trains the model once per seed,
validates AUC-PR on a held-out set with synthetic anomalies, and writes the
**best-AUC-PR** checkpoint (+ a metrics.json) to ``CHECKPOINT_DIR`` — a local path or
a ``gs://`` URI. Multi-seed is a robustness check; only the single best model ships.

Built for a Vertex AI custom job (GPU, auto-terminates — no idle cost) but also runs
locally on CPU/MPS. Every knob is an env var so the Vertex worker spec can set them:

  PROJECT, TABLE, CHECKPOINT_DIR (or Vertex's AIP_MODEL_DIR),
  N_TRAIN, N_VAL, WINDOW, Z_DIM, HIDDEN, N_FLOWS, EPOCHS, BATCH, LR,
  MC_SAMPLES, SEEDS (comma-sep), EVENTS_PER_MACHINE

Local run:  uv run --directory backend --group ml python scripts/train_omni.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ → import app.*

from app.eval.alibaba import FEATURES, inject_anomalies, load_machines
from app.eval.metrics import evaluate
from app.detectors.omnianomaly import OmniAnomalyDetector


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


PROJECT = _env("PROJECT", "primav2")
TABLE = _env("TABLE", "primav2.alibaba_cluster.usage_5min")
# Vertex injects AIP_MODEL_DIR (a gs:// path); honour it if CHECKPOINT_DIR is unset.
CHECKPOINT_DIR = _env("CHECKPOINT_DIR", os.environ.get("AIP_MODEL_DIR", "./omni_out"))

N_TRAIN = _int("N_TRAIN", 300)
N_VAL = _int("N_VAL", 40)
EVENTS_PER_MACHINE = _int("EVENTS_PER_MACHINE", 6)
SEEDS = [int(s) for s in _env("SEEDS", "0,1,2").split(",") if s.strip()]

OMNI_KW = dict(
    window=_int("WINDOW", 100),
    z_dim=_int("Z_DIM", 3),
    hidden=_int("HIDDEN", 128),
    n_flows=_int("N_FLOWS", 10),
    epochs=_int("EPOCHS", 30),
    batch=_int("BATCH", 256),
    mc_samples=_int("MC_SAMPLES", 8),
    lr=float(_env("LR", "1e-3")),
)


def _device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _score_pooled(detector: OmniAnomalyDetector, seqs: list[np.ndarray]) -> np.ndarray:
    return np.concatenate([detector.score(X) for X in seqs])


def _auc_by_type(y, scores, types) -> dict[str, float]:
    benign = types == ""
    out = {}
    for name, mask in (
        ("overall", np.ones(len(y), dtype=bool)),
        ("spike", benign | (types == "spike")),
        ("context", benign | (types == "context")),
    ):
        out[name] = float(evaluate(y[mask], scores[mask]).as_dict()["auc_pr"])
    return out


def _upload(local: str, gs_uri: str) -> None:
    from google.cloud import storage

    bucket, _, blob = gs_uri.removeprefix("gs://").partition("/")
    storage.Client().bucket(bucket).blob(blob).upload_from_filename(local)


def _write(local_name: str, gs_or_local_dir: str, src_path: str) -> str:
    """Place ``src_path`` at ``<dir>/<local_name>`` (GCS or local). Returns the URI."""
    dest = gs_or_local_dir.rstrip("/") + "/" + local_name
    if dest.startswith("gs://"):
        _upload(src_path, dest)
    else:
        Path(gs_or_local_dir).mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(Path(src_path).read_bytes())
    return dest


def main() -> None:
    dev = _device()
    print(f">> training global OmniAnomaly on {dev}", flush=True)
    print(f">> config: {OMNI_KW} | seeds={SEEDS} | train={N_TRAIN} val={N_VAL}", flush=True)

    limit = N_TRAIN + N_VAL + 20  # small buffer past what we need
    series = load_machines(PROJECT, TABLE, limit, min_len=OMNI_KW["window"] * 6)
    ids = sorted(series)
    if len(ids) < N_TRAIN + N_VAL:
        raise SystemExit(f"only {len(ids)} machines qualify; need {N_TRAIN + N_VAL}")
    print(f">> {len(ids)} machines loaded (median len "
          f"{int(np.median([len(series[m]) for m in ids]))} bins)", flush=True)

    train_ids = ids[:N_TRAIN]
    val_ids = ids[N_TRAIN : N_TRAIN + N_VAL]
    train_series = [series[m] for m in train_ids]

    # Held-out validation: inject synthetic anomalies (range from TRAIN, no leakage).
    gtrain = np.concatenate(train_series, axis=0)
    gmin, gmax = gtrain.min(0), gtrain.max(0)
    val_seqs, val_y, val_t = [], [], []
    for k, m in enumerate(val_ids):
        Xa, y, t = inject_anomalies(
            series[m], np.random.default_rng(1000 + k), gmin, gmax,
            events=EVENTS_PER_MACHINE,
        )
        val_seqs.append(Xa)
        val_y.append(y)
        val_t.append(t)
    y_all = np.concatenate(val_y)
    t_all = np.concatenate(val_t)
    print(f">> validation: {len(val_ids)} machines, {len(y_all):,} bins, "
          f"{int(y_all.sum())} injected ({y_all.mean():.1%})", flush=True)

    best = None  # (overall_auc, seed, detector, metrics)
    per_seed = []
    for seed in SEEDS:
        t0 = time.time()
        det = OmniAnomalyDetector(n_features=len(FEATURES), device=dev, seed=seed, **OMNI_KW)
        hist = det.fit_series(train_series)
        scores = _score_pooled(det, val_seqs)
        aucs = _auc_by_type(y_all, scores, t_all)
        dt = time.time() - t0
        per_seed.append({"seed": seed, "auc_pr": aucs, "final_elbo": hist[-1], "secs": round(dt)})
        print(f"   seed {seed}: overall AUC-PR {aucs['overall']:.3f} "
              f"(spike {aucs['spike']:.3f}, context {aucs['context']:.3f}) "
              f"| ELBO {hist[-1]:.1f} | {dt:.0f}s", flush=True)
        if best is None or aucs["overall"] > best[0]:
            best = (aucs["overall"], seed, det, aucs)

    best_auc, best_seed, best_det, best_aucs = best
    overall = [s["auc_pr"]["overall"] for s in per_seed]
    print(f">> best seed {best_seed}: overall AUC-PR {best_auc:.3f} "
          f"(across seeds: mean {np.mean(overall):.3f} ± {np.std(overall):.3f})", flush=True)

    # Save the best model + a metrics report to CHECKPOINT_DIR (local or gs://).
    with tempfile.TemporaryDirectory() as tmp:
        ckpt = str(Path(tmp) / "omni_global.pt")
        best_det.save(ckpt)
        metrics = {
            "config": {"project": PROJECT, "table": TABLE, "device": dev,
                       "n_train": len(train_ids), "n_val": len(val_ids),
                       "events_per_machine": EVENTS_PER_MACHINE, **OMNI_KW},
            "best_seed": best_seed,
            "best_auc_pr": best_aucs,
            "auc_pr_overall_mean": float(np.mean(overall)),
            "auc_pr_overall_std": float(np.std(overall)),
            "per_seed": per_seed,
        }
        mpath = str(Path(tmp) / "metrics.json")
        Path(mpath).write_text(json.dumps(metrics, indent=2))
        ck_uri = _write("omni_global.pt", CHECKPOINT_DIR, ckpt)
        m_uri = _write("metrics.json", CHECKPOINT_DIR, mpath)

    print(f">> checkpoint: {ck_uri}", flush=True)
    print(f">> metrics:    {m_uri}", flush=True)


if __name__ == "__main__":
    main()
