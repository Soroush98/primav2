"""Adversarial benchmark: MAD/EVT baseline vs OmniAnomaly on the same series,
graded with BOTH strict (raw best-F1, AUC-PR) and lenient (point-adjusted
best-F1) metrics.

The harness reports both detectors and the inflation gap; it does NOT prejudge a
winner — the data decides which is worth its cost, and where (mle-practices §2, §5).
The OmniAnomaly import is lazy so this module stays torch-free until used.
"""

from __future__ import annotations

import json

import numpy as np

from app.eval.metrics import evaluate

_REPORT_COLS = ("raw_best_f1", "pa_best_f1", "auc_pr", "inflation_gap", "prevalence")


def benchmark_series(
    X_train,
    X_test,
    y_test,
    *,
    baseline_kwargs: dict | None = None,
    omni_kwargs: dict | None = None,
) -> dict:
    """Fit both detectors on (clean) ``X_train``, grade them on ``X_test`` against
    ``y_test``. Returns ``{"baseline": {...}, "omnianomaly": {...}}``."""
    from app.detectors.baseline import BaselineDetector
    from app.detectors.omnianomaly import OmniAnomalyDetector

    X_train = np.asarray(X_train, dtype=np.float32)
    X_test = np.asarray(X_test, dtype=np.float32)

    baseline = BaselineDetector(**(baseline_kwargs or {})).fit(X_train)
    omni = OmniAnomalyDetector(n_features=X_train.shape[1], **(omni_kwargs or {}))
    omni.fit(X_train)

    return {
        "baseline": evaluate(y_test, baseline.score(X_test)).as_dict(),
        "omnianomaly": evaluate(y_test, omni.score(X_test)).as_dict(),
    }


def format_table(results: dict) -> str:
    """Markdown comparison table with the strict/lenient caveat inline."""
    header = "| detector | " + " | ".join(_REPORT_COLS) + " |"
    sep = "|" + "---|" * (len(_REPORT_COLS) + 1)
    lines = [header, sep]
    for name, r in results.items():
        lines.append("| " + name + " | " + " | ".join(f"{r[c]:.3f}" for c in _REPORT_COLS) + " |")
    lines += [
        "",
        "> `raw_best_f1` / `auc_pr` are strict; `pa_best_f1` is lenient "
        "(point-adjusted — inflated, for comparability only). "
        "`inflation_gap = pa − raw`. Testbed data overstates real-world F1.",
    ]
    return "\n".join(lines)


def save_report(results: dict, path: str) -> None:
    with open(path, "w") as fh:
        json.dump(results, fh, indent=2)
