"""Anomaly-detection metrics with the strict-vs-lenient pairing.

We always report BOTH:
  - raw best-F1 (strict): threshold swept, no point-adjustment.
  - point-adjusted best-F1 (lenient): the metric most time-series-anomaly papers
    report. It is known to be heavily inflated — a random scorer can reach ~1.0
    when anomalies occur in segments (Kim et al. 2022) — so it is shown only for
    comparability with prior work and ALWAYS next to the strict number.
Plus AUC-PR, the threshold-free strict metric, reported next to its no-skill
floor (the positive prevalence).

This module is the project's honesty gate: it is built before any detector so
every comparison is graded the same way (mle-practices §3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from sklearn.metrics import average_precision_score


def point_adjust(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Standard point-adjustment (Xu et al. 2018 / Su et al. 2019).

    For every contiguous ground-truth anomaly segment, if the detector fires on
    at least one point inside it, the entire segment is credited as detected.
    Returns an adjusted copy of ``y_pred``.
    """
    y_true = np.asarray(y_true).astype(bool)
    y_pred = np.asarray(y_pred).astype(bool).copy()
    n = len(y_true)
    i = 0
    while i < n:
        if y_true[i]:
            j = i
            while j < n and y_true[j]:
                j += 1
            if y_pred[i:j].any():
                y_pred[i:j] = True
            i = j
        else:
            i += 1
    return y_pred


def _prf(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    tp = int(np.sum(y_pred & y_true))
    fp = int(np.sum(y_pred & ~y_true))
    fn = int(np.sum(~y_pred & y_true))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def best_f1(
    y_true,
    scores,
    *,
    adjusted: bool,
    n_thresholds: int = 200,
) -> tuple[float, float, float, float]:
    """Sweep thresholds and return ``(precision, recall, f1, threshold)`` at the
    best F1. ``adjusted=True`` applies point-adjustment before scoring.

    This uses an *oracle* threshold (it peeks at the labels), so it is optimistic
    — the lenient bound, never the deployable number.
    """
    y_true = np.asarray(y_true).astype(bool)
    scores = np.asarray(scores, dtype=float)
    lo, hi = float(scores.min()), float(scores.max())
    thresholds = np.array([lo]) if lo == hi else np.linspace(lo, hi, n_thresholds)

    best = (0.0, 0.0, 0.0, lo)
    for thr in thresholds:
        y_pred = scores >= thr
        if adjusted:
            y_pred = point_adjust(y_true, y_pred)
        p, r, f1 = _prf(y_true, y_pred)
        if f1 > best[2]:
            best = (p, r, f1, float(thr))
    return best


@dataclass
class EvalResult:
    prevalence: float       # positive rate = the AUC-PR no-skill floor
    auc_pr: float           # strict, threshold-free
    raw_best_f1: float      # strict (oracle threshold)
    pa_best_f1: float       # lenient (point-adjusted — inflated)
    raw_precision: float
    raw_recall: float
    inflation_gap: float    # pa_best_f1 - raw_best_f1; the gap this gate exposes

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(y_true, scores) -> EvalResult:
    """Grade anomaly ``scores`` against binary ``y_true``; returns strict and
    lenient metrics together so the inflation is always visible."""
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores, dtype=float)
    prevalence = float(y_true.mean())
    auc_pr = (
        float(average_precision_score(y_true, scores))
        if 0 < prevalence < 1
        else 0.0
    )
    rp, rr, rf1, _ = best_f1(y_true, scores, adjusted=False)
    _, _, paf1, _ = best_f1(y_true, scores, adjusted=True)
    return EvalResult(
        prevalence=prevalence,
        auc_pr=auc_pr,
        raw_best_f1=rf1,
        pa_best_f1=paf1,
        raw_precision=rp,
        raw_recall=rr,
        inflation_gap=paf1 - rf1,
    )
