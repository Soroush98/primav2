"""MAD/EVT statistical baseline detector.

Score: robust z-score (MAD-based) per feature, aggregated to one anomaly score
per window. Threshold: Peaks-Over-Threshold (EVT/SPOT, Siffer et al. 2017),
fitting a Generalized Pareto tail to the score distribution.

Deliberately cheap, deterministic, and dependency-light — this is the floor the
OmniAnomaly arm must beat to justify its cost (mle-practices §2). It is also the
detector wired into the live agent by default.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import genpareto

# Phi^-1(0.75): makes the MAD a consistent estimator of sigma for normal data.
_MAD_SCALE = 0.6744897501960817


def fit_baseline(train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-feature median and MAD from (assumed-clean) training windows.

    ``train`` has shape ``(n_windows, n_features)``; returns ``(median, mad)``,
    each ``(n_features,)``.
    """
    median = np.median(train, axis=0)
    mad = np.median(np.abs(train - median), axis=0)
    mad = np.where(mad == 0, 1e-9, mad)  # guard constant features
    return median, mad


def anomaly_scores(X: np.ndarray, median: np.ndarray, mad: np.ndarray) -> np.ndarray:
    """Aggregate per-feature robust z into one score per row.

    Uses the max across features (worst-channel deviation) — sensitive to attacks
    that spike a single feature (e.g. a port-scan's unique-dst-port count).
    """
    z = _MAD_SCALE * np.abs(X - median) / mad
    return z.max(axis=1)


def pot_threshold(
    scores: np.ndarray,
    q: float = 1e-3,
    init_quantile: float = 0.98,
) -> float:
    """EVT/POT threshold (SPOT initialization).

    Fits a GPD to exceedances over a high init quantile ``t`` and returns the
    level whose tail probability is ``q``. Falls back to ``t`` when the tail is
    too thin to fit.
    """
    scores = np.asarray(scores, dtype=float)
    t = float(np.quantile(scores, init_quantile))
    peaks = scores[scores > t] - t
    if peaks.size < 10:
        return t
    c, _loc, scale = genpareto.fit(peaks, floc=0.0)
    n, n_t = scores.size, peaks.size
    if abs(c) < 1e-8:
        return t - scale * np.log(q * n / n_t)
    return t + (scale / c) * ((q * n / n_t) ** (-c) - 1.0)


class BaselineDetector:
    def __init__(self, q: float = 1e-3, init_quantile: float = 0.98) -> None:
        self.q = q
        self.init_quantile = init_quantile
        self.median_: np.ndarray | None = None
        self.mad_: np.ndarray | None = None
        self.threshold_: float | None = None

    def fit(self, train: np.ndarray) -> "BaselineDetector":
        self.median_, self.mad_ = fit_baseline(train)
        train_scores = anomaly_scores(train, self.median_, self.mad_)
        self.threshold_ = pot_threshold(train_scores, self.q, self.init_quantile)
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        assert self.median_ is not None, "call fit() first"
        return anomaly_scores(X, self.median_, self.mad_)

    def predict(self, X: np.ndarray) -> np.ndarray:
        assert self.threshold_ is not None, "call fit() first"
        return (self.score(X) >= self.threshold_).astype(int)
