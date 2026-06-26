"""Shared Alibaba cluster-trace-v2018 loaders + synthetic anomaly injection.

The OmniAnomaly trainer (``scripts/train_omni.py``) and the benchmark both need the
same two things: regular, gap-filled per-machine 5-min series from the
``usage_5min`` table, and a documented way to inject labeled anomalies (there are no
ground-truth labels in the trace). This module is the single source of truth.

Coverage filtering happens in SQL so we never stream the whole 8.4M-row table —
only the first ``limit`` qualifying machines (ordered by id, so it is deterministic).
"""

from __future__ import annotations

import numpy as np

FEATURES = ["cpu", "mem", "net_in", "net_out", "disk_io"]


def ffill(X: np.ndarray) -> np.ndarray:
    """Forward-fill then back-fill NaNs along time (axis 0), per feature."""
    for j in range(X.shape[1]):
        col = X[:, j]
        last = np.nan
        for i in range(len(col)):
            if np.isnan(col[i]):
                col[i] = last
            else:
                last = col[i]
        nxt = np.nan
        for i in range(len(col) - 1, -1, -1):
            if np.isnan(col[i]):
                col[i] = nxt
            else:
                nxt = col[i]
    return X


def load_machines(
    project: str,
    table: str,
    limit: int,
    *,
    features: list[str] = FEATURES,
    min_len: int = 600,
    min_coverage: float = 0.85,
) -> dict[str, np.ndarray]:
    """Return ``{machine_id: X[n, n_features] float32}`` of regular, gap-filled series.

    ``limit`` caps how many qualifying machines are pulled (coverage-filtered in SQL).
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    cols = ", ".join(f"u.{c}" for c in ["machine_id", "bin", *features])
    sql = f"""
    WITH per_m AS (
      SELECT machine_id, COUNT(*) AS bins, MAX(bin)-MIN(bin)+1 AS span
      FROM `{table}` GROUP BY machine_id ),
    ok AS (
      SELECT machine_id FROM per_m
      WHERE bins >= {min_len} AND SAFE_DIVIDE(bins, span) >= {min_coverage}
      ORDER BY machine_id LIMIT {limit} )
    SELECT {cols} FROM `{table}` u JOIN ok USING (machine_id)
    ORDER BY u.machine_id, u.bin"""

    raw: dict[str, list] = {}
    for r in client.query(sql).result():
        raw.setdefault(r["machine_id"], []).append(
            (int(r["bin"]), [r[c] for c in features])
        )

    series: dict[str, np.ndarray] = {}
    for mid, rows in raw.items():
        bins = [b for b, _ in rows]
        lo, hi = min(bins), max(bins)
        span = hi - lo + 1
        if span < min_len or len(rows) / span < min_coverage:
            continue
        X = np.full((span, len(features)), np.nan, dtype=np.float32)
        for b, vals in rows:
            X[b - lo] = [np.nan if v is None else float(v) for v in vals]
        X = ffill(X)
        if np.isnan(X).any():
            continue
        series[mid] = X
    return series


def inject_anomalies(
    X: np.ndarray,
    rng: np.random.Generator,
    gmin: np.ndarray,
    gmax: np.ndarray,
    *,
    events: int = 6,
    ctx_len: tuple[int, int] = (12, 24),
    spike_len: tuple[int, int] = (1, 3),
    margin: int = 120,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(X_anom, labels[n], types[n])`` with two deliberately-different types:

    * ``spike``   — short, large magnitude excursion outside the global range; a
                    per-feature robust z-score nails it (baseline-favorable).
    * ``context`` — replace a segment of ONE feature with a random resample of that
                    same feature's own values: the marginal is unchanged, so a
                    per-feature z-score is blind to it; only the joint/temporal model
                    can see it (OmniAnomaly-favorable).
    """
    X = X.copy()
    n, d = X.shape
    y = np.zeros(n, dtype=int)
    types = np.array(["" for _ in range(n)], dtype=object)
    for _ in range(events):
        kind = rng.choice(["spike", "context"])
        j = int(rng.integers(d))
        if kind == "spike":
            length = int(rng.integers(*spike_len))
            start = int(rng.integers(margin, n - margin - length))
            X[start : start + length, j] = gmax[j] + 3.0 * (gmax[j] - gmin[j] + 1e-6)
        else:
            length = int(rng.integers(*ctx_len))
            start = int(rng.integers(margin, n - margin - length))
            X[start : start + length, j] = rng.choice(X[:, j], size=length)
        y[start : start + length] = 1
        types[start : start + length] = kind
    return X, y, types
